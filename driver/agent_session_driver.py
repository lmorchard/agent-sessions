#!/usr/bin/env python3
"""Agent session board driver and reconciliation loop in Python.

Stateless state machine that evaluates GitHub repository state (issues, PRs,
review comments, CI status) and dispatches tightly-scoped, short-lived LLM agents.
Stdlib only, importable and testable with pytest.
"""

from __future__ import annotations

import argparse
import atexit
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import agent_runner
import discussion_manager
import gate
import gh_query


PARK_LABEL = "agent-session:needs-human"
INTERACTIVE_LABEL = "agent-session:needs-human-interactive"
MERGE_READY_LABEL = "agent-session:merge-ready"
MARKER = "<!-- agent-session:spec -->"


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%SZ")
    sys.stderr.write(f"{ts}  {msg}\n")


def say(msg: str) -> None:
    sys.stdout.write(f"{msg}\n")


def die(msg: str, code: int = 2) -> None:
    sys.stderr.write(f"error: {msg}\n")
    sys.exit(code)


def abspath(p: str) -> Path:
    path = Path(p)
    if path.is_absolute():
        return path.resolve()
    return (Path.cwd() / path).resolve()


def get_attempts(issue_number: str | int, repo: str, issues_json: list[dict] | None = None) -> int:
    labels = []
    if issues_json:
        for iss in issues_json:
            if str(iss.get("number")) == str(issue_number):
                labels = iss.get("labels") or []
                break
    if not labels:
        try:
            res = subprocess.run(
                ["gh", "issue", "view", str(issue_number), "--repo", repo, "--json", "labels"],
                capture_output=True,
                text=True,
                check=True,
            )
            data = json.loads(res.stdout)
            labels = data.get("labels", [])
        except Exception:
            labels = []

    label_names = [l.get("name", "") for l in labels if isinstance(l, dict)]
    if "agent-session:attempt-3" in label_names:
        return 3
    elif "agent-session:attempt-2" in label_names:
        return 2
    elif "agent-session:attempt-1" in label_names:
        return 1
    return 0


def clear_attempt_labels(issue_number: str | int, repo: str) -> None:
    label_mgr = Path(__file__).parent.parent / "scripts" / "label_manager.py"
    cmd = [sys.executable, str(label_mgr)]
    if repo:
        cmd.extend(["--repo", repo])
    cmd.extend(["clear-attempts", "--issue", str(issue_number)])
    try:
        subprocess.run(cmd, capture_output=True, check=True)
    except Exception:
        pass


def increment_attempts(issue_number: str | int, repo: str) -> None:
    count = get_attempts(issue_number, repo) + 1
    label_mgr = Path(__file__).parent.parent / "scripts" / "label_manager.py"
    cmd = [sys.executable, str(label_mgr)]
    if repo:
        cmd.extend(["--repo", repo])
    cmd.extend(["attempt", "--issue", str(issue_number), "--count", str(count)])
    try:
        subprocess.run(cmd, capture_output=True, check=True)
    except Exception:
        pass


def park_label_add(issue_number: str | int, repo: str) -> None:
    label_mgr = Path(__file__).parent.parent / "scripts" / "label_manager.py"
    cmd = [sys.executable, str(label_mgr)]
    if repo:
        cmd.extend(["--repo", repo])
    cmd.extend(["park", "--issue", str(issue_number)])
    try:
        subprocess.run(cmd, capture_output=True, check=True)
    except Exception:
        say(f"  WARNING: could not add the {PARK_LABEL} label to #{issue_number} -- it stays selectable")


def park_label_remove(issue_number: str | int, repo: str) -> None:
    label_mgr = Path(__file__).parent.parent / "scripts" / "label_manager.py"
    cmd = [sys.executable, str(label_mgr)]
    if repo:
        cmd.extend(["--repo", repo])
    cmd.extend(["unpark", "--issue", str(issue_number)])
    try:
        subprocess.run(cmd, capture_output=True, check=True)
    except Exception:
        say(f"  WARNING: could not remove the {PARK_LABEL} label from #{issue_number} -- it stays parked")


def notify_human(issue_number: str | int, reason: str, state_dir: Path | None) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if state_dir and state_dir.exists():
        inbox = state_dir / "inbox.md"
        with open(inbox, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] Issue #{issue_number} escalated: {reason}\n")


def parked_numbers(issues: list[dict]) -> set[str]:
    parked = set()
    for iss in issues:
        labels = iss.get("labels") or []
        for l in labels:
            if isinstance(l, dict) and l.get("name") in (PARK_LABEL, INTERACTIVE_LABEL):
                parked.add(str(iss.get("number")))
    return parked


def build_prompt(issue_number: str | int, repo: str, phase: str, skill_dir: Path, comments: bool = True) -> str:
    # Fetch issue details
    cmd = ["gh", "issue", "view", str(issue_number), "--repo", repo, "--json", "title,body,comments"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(res.stdout)
    except Exception:
        data = {"title": f"Issue #{issue_number}", "body": "", "comments": []}

    title = data.get("title", "")
    body = data.get("body", "")
    comms = data.get("comments", [])

    prompt_lines = [
        f"You are working on issue #{issue_number}: {title}.",
        f"Phase: {phase}.",
        "",
        "Issue body:",
        body,
        "",
    ]
    if comments and comms:
        prompt_lines.append("Issue comments:")
        for c in comms:
            author = c.get("author", {}).get("login", "unknown")
            body_c = c.get("body", "")
            prompt_lines.append(f"- @{author}: {body_c}")
        prompt_lines.append("")

    prompt_lines.append(f"Please execute the workflow using skill at {skill_dir}.")
    return "\n".join(prompt_lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Agent session driver")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--skill-dir", required=True)
    parser.add_argument("--repo-path", required=True)
    parser.add_argument("--issue", default="")
    parser.add_argument("--max-issues", type=int, default=1)
    parser.add_argument("--max-budget-usd", type=float, default=10.0)
    parser.add_argument("--timeout", type=int, default=5400)
    parser.add_argument("--state-dir", default="")
    parser.add_argument("--board", default="")
    parser.add_argument("--backend", default="claude")
    parser.add_argument("--model", default="")
    parser.add_argument("--high-tier-model", default="")
    parser.add_argument("--low-tier-model", default="")
    parser.add_argument("--retry", default="")
    parser.add_argument("--classify-only", default="")
    parser.add_argument("--resumed-from", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-nested-skill-dir", action="store_true")
    parser.add_argument("--all-issues", action="store_true")

    args = parser.parse_args(argv)

    # Load .env if present
    env_file = Path(".env")
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

    repo = args.repo
    parts = repo.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1] or "." in parts or ".." in parts:
        die(f"--repo must be owner/name, with exactly one '/': {repo}")

    skill_dir = abspath(args.skill_dir) if args.skill_dir else Path("")
    repo_path = abspath(args.repo_path) if args.repo_path else Path("")

    state_dir_str = args.state_dir
    if not state_dir_str:
        xdg = os.environ.get("XDG_STATE_HOME")
        home = os.environ.get("HOME")
        if not xdg and not home:
            die("no --state-dir given and neither XDG_STATE_HOME nor HOME is set; pass --state-dir")
        base = Path(xdg) if xdg else Path(str(home)) / ".local" / "state"
        state_dir_str = str(base / "agent-session" / repo.replace("/", "-"))
    state_dir = abspath(state_dir_str)

    log(f"state dir  {state_dir}")

    # Check nested skill dir
    if skill_dir and repo_path:
        try:
            skill_dir.relative_to(repo_path)
            nested = True
        except ValueError:
            nested = False
        if nested and not args.allow_nested_skill_dir:
            die(f"error: --skill-dir ({skill_dir}) resolves inside --repo-path ({repo_path}); pass --allow-nested-skill-dir to proceed")

    state_dir.mkdir(parents=True, exist_ok=True)
    runs_dir = state_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    runs_log = state_dir / "runs.jsonl"
    parked_log = state_dir / "parked.jsonl"
    runs_log.touch(exist_ok=True)
    parked_log.touch(exist_ok=True)

    hook_settings_template = Path(__file__).parent / "settings.json"
    hook_script = Path(__file__).parent / "merge-block-hook.sh"
    hook_settings_file = state_dir / "settings.json"
    if hook_settings_template.is_file():
        try:
            template_data = json.loads(hook_settings_template.read_text(encoding="utf-8"))
            if "hooks" not in template_data:
                template_data["hooks"] = {}
            if "PreToolUse" not in template_data["hooks"]:
                template_data["hooks"]["PreToolUse"] = [{}]
            template_data["hooks"]["PreToolUse"][0]["command"] = str(hook_script.resolve())
            hook_settings_file.write_text(json.dumps(template_data, indent=2), encoding="utf-8")
        except Exception:
            pass

    # Handle classify-only mode
    if args.classify_only:
        issue_num = args.classify_only
        log(f"classify-only requested for issue #{issue_num}")
        open_prs = gh_query.fetch_open_prs(repo)
        matching_pr = None
        for pr in open_prs:
            refs = pr.get("closingIssuesReferences") or []
            if any(str(r.get("number")) == str(issue_num) for r in refs):
                matching_pr = pr
                break
        if not matching_pr:
            for pr in open_prs:
                body = pr.get("body") or ""
                if f"#{issue_num}" in body or str(issue_num) in body:
                    matching_pr = pr
                    break

        if not matching_pr:
            log(f"no open PR found for issue #{issue_num}")
            return 1

        pr_body = matching_pr.get("body", "")
        head_sha = matching_pr.get("headRefName", "")
        outcome_res = gate.classify(pr_body, head_sha=head_sha)
        outcome = outcome_res["outcome"]
        reason = outcome_res["reason"]
        say(f"outcome: {outcome}\treason: {reason}")
        return 0

    # Dry run or selection
    log(f"selecting eligible issues for {repo}")
    try:
        cmd = ["gh", "issue", "list", "--repo", repo, "--state", "open", "--json", "number,title,body,labels,url"]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        issues = json.loads(res.stdout)
    except Exception as e:
        log(f"failed to list issues: {e}")
        issues = []

    parked = parked_numbers(issues)
    open_prs = gh_query.fetch_open_prs(repo)

    eligible = []
    for iss in issues:
        num = str(iss.get("number"))
        if num == args.retry:
            pass
        elif num in parked:
            log(f"SKIP  #{num} is parked")
            continue
        
        body = iss.get("body", "")
        if MARKER not in body:
            log(f"SKIP  #{num} has no session marker")
            continue

        tier = gate.tier_of(body)
        if tier != "auto-ok":
            log(f"SKIP  #{num} tier is {tier}")
            continue

        blocking = gh_query.pr_blocking_issue(num, open_prs)
        if blocking:
            log(f"SKIP  #{num} has blocking PR #{blocking.split()[0]}")
            continue

        eligible.append(iss)

    log(f"found {len(eligible)} eligible issue(s)")
    for iss in eligible:
        say(f"ELIGIBLE  #{iss.get('number')}  {iss.get('title')}")

    if args.dry_run:
        return 0

    # Execute run on eligible issues up to max-issues
    count = 0
    for iss in eligible:
        if count >= args.max_issues:
            break
        num = str(iss.get("number"))
        if args.issue and num != args.issue:
            continue

        log(f"running issue #{num}")
        increment_attempts(num, repo)
        prompt = build_prompt(num, repo, "express", skill_dir)
        prompt_file = state_dir / f"prompt-{num}.txt"
        prompt_file.write_text(prompt, encoding="utf-8")

        raw_output = runs_dir / f"run-{num}-{int(time.time())}.jsonl"
        stderr_output = runs_dir / f"run-{num}-{int(time.time())}.err"

        runner_args = [
            "--backend", args.backend,
            "--repo-path", str(repo_path),
            "--skill-dir", str(skill_dir),
            "--prompt-file", str(prompt_file),
            "--raw-output", str(raw_output),
            "--stderr-output", str(stderr_output),
            "--max-budget", str(args.max_budget_usd),
            "--timeout", str(args.timeout),
            "--settings", str(hook_settings_file),
        ]
        if args.model:
            runner_args.extend(["--model", args.model])
        if args.high_tier_model:
            runner_args.extend(["--high-tier-model", args.high_tier_model])
        if args.low_tier_model:
            runner_args.extend(["--low-tier-model", args.low_tier_model])

        ret = agent_runner.run_agent(runner_args)
        log(f"agent runner exited with {ret}")
        count += 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
