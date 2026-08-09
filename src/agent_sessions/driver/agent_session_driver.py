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
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from agent_sessions.driver import agent_runner, discussion_manager, gate, gh_query

SPEC_LABEL = "agent-session:spec"
PARK_LABEL = "agent-session:needs-human"
INTERACTIVE_LABEL = "agent-session:needs-human-interactive"
MERGE_READY_LABEL = "agent-session:merge-ready"
MARKER = "<!-- agent-session:spec -->"

CURRENT_LOCK_ISSUE: str | None = None


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
    labels: list[dict] = []
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


def park_reason(issue_number: str | int, state_dir: Path) -> str:
    runs_log = state_dir / "runs.jsonl"
    if not runs_log.is_file():
        return "no history recorded on this host"
    last_reason = ""
    for line in runs_log.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
            if str(row.get("issue")) == str(issue_number):
                reason = row.get("reason", "")
                if reason:
                    last_reason = reason
        except Exception:
            pass
    return last_reason or "no history recorded on this host"


def apply_park_state(
    issue_number: str | int,
    outcome: str,
    ts: str,
    reason: str,
    repo: str,
    state_dir: Path,
    parked_log: Path,
) -> None:
    iss_num = str(issue_number)
    if outcome in ("parked", "failed", "no-gate"):
        row = {"issue": int(iss_num), "repo": repo, "parked_at": ts, "outcome": outcome, "reason": reason}
        with open(parked_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        park_label_add(iss_num, repo)
        clear_attempt_labels(iss_num, repo)
        say(f"  parked -- excluded from future selection unless --retry {iss_num}")
        notify_human(iss_num, f"{outcome}: {reason}", state_dir)
    elif outcome == "gate-human":
        row = {"issue": int(iss_num), "repo": repo, "parked_at": ts, "outcome": outcome, "reason": reason}
        with open(parked_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        park_label_add(iss_num, repo)
        clear_attempt_labels(iss_num, repo)
        say(f"  parked for human review -- excluded from future selection unless --retry {iss_num}")
        notify_human(iss_num, f"gate-human: {reason}", state_dir)
    elif outcome == "incomplete":
        row = {"issue": int(iss_num), "repo": repo, "parked_at": ts, "outcome": outcome, "reason": reason}
        with open(parked_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        say("  incomplete -- leaving unparked so the loop can re-evaluate later")
        park_label_remove(iss_num, repo)
    elif outcome == "gate-eligible":
        label_mgr = Path(__file__).parent.parent / "scripts" / "label_manager.py"
        cmd = [sys.executable, str(label_mgr)]
        if repo:
            cmd.extend(["--repo", repo])
        cmd.extend(["merge-ready", "--issue", iss_num])
        try:
            subprocess.run(cmd, capture_output=True, check=True)
        except Exception:
            pass
        notify_human(iss_num, f"gate-eligible: {reason}", state_dir)


def release_lock(repo_path: Path) -> None:
    global CURRENT_LOCK_ISSUE
    if CURRENT_LOCK_ISSUE:
        log(f"Releasing lock for #{CURRENT_LOCK_ISSUE}...")
        try:
            subprocess.run(
                ["git", "-C", str(repo_path), "push", "origin", f":refs/locks/issue-{CURRENT_LOCK_ISSUE}"],
                capture_output=True,
            )
        except Exception:
            pass
        CURRENT_LOCK_ISSUE = None


def acquire_lock(issue_number: str | int, phase: str, repo_path: Path) -> bool:
    global CURRENT_LOCK_ISSUE
    if not repo_path or not str(repo_path):
        return True
    try:
        res_git = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
        )
        if res_git.returncode != 0:
            return True
    except Exception:
        return True

    try:
        res_remote = subprocess.run(
            ["git", "-C", str(repo_path), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
        )
        if res_remote.returncode != 0:
            return True
            return True
    except Exception:
        return True

    lock_ref = f"refs/locks/issue-{issue_number}"
    empty_tree_sha = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
    try:
        host = os.uname().nodename
    except Exception:
        host = "unknown-host"
    run_id = str(uuid.uuid4())

    ttl_seconds = 600 if phase in ("triage", "groom", "refine") else 7200
    commit_msg = f"agent-session lock: issue {issue_number}\n\nphase: {phase}\nhost: {host}\nrun_id: {run_id}"

    try:
        res = subprocess.run(
            ["git", "-C", str(repo_path), "commit-tree", empty_tree_sha],
            input=commit_msg,
            capture_output=True,
            text=True,
            check=True,
        )
        lock_sha = res.stdout.strip()
    except Exception:
        return False

    try:
        res = subprocess.run(
            ["git", "-C", str(repo_path), "ls-remote", "origin", lock_ref],
            capture_output=True,
            text=True,
        )
        current_lock = res.stdout.split()[0] if res.stdout.strip() else ""
    except Exception:
        current_lock = ""

    if not current_lock:
        try:
            res_push = subprocess.run(
                ["git", "-C", str(repo_path), "push", "origin", f"{lock_sha}:{lock_ref}"],
                capture_output=True,
                text=True,
            )
            if res_push.returncode == 0:
                CURRENT_LOCK_ISSUE = str(issue_number)
                log(f"Acquired fresh lock for #{issue_number} (phase: {phase})")
                return True
            else:
                return False
        except Exception:
            return False

    try:
        subprocess.run(
            ["git", "-C", str(repo_path), "fetch", "origin", lock_ref, "--depth", "1", "-q"],
            capture_output=True,
            text=True,
        )
        res_log = subprocess.run(
            ["git", "-C", str(repo_path), "log", "-1", "--format=%ct", current_lock],
            capture_output=True,
            text=True,
        )
        lock_time = int(res_log.stdout.strip() or "0")
    except Exception:
        lock_time = 0

    now = int(time.time())
    lock_age = now - lock_time

    if lock_age < ttl_seconds:
        return False
    else:
        try:
            res_force = subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo_path),
                    "push",
                    f"--force-with-lease={lock_ref}:{current_lock}",
                    "origin",
                    f"{lock_sha}:{lock_ref}",
                ],
                capture_output=True,
                text=True,
            )
            if res_force.returncode == 0:
                CURRENT_LOCK_ISSUE = str(issue_number)
                log(f"Stole stale lock for #{issue_number} (age {lock_age}s > TTL {ttl_seconds}s)")
                return True
            else:
                return False
        except Exception:
            return False


def build_prompt(url_or_number: str | int, phase: str, skill_dir: Path) -> str:
    if str(url_or_number).startswith("http"):
        url = str(url_or_number)
    else:
        url = f"issue #{url_or_number}"

    phase_file = "phases/express.md" if phase == "execute" else f"phases/{phase}.md"
    comments_note = ""
    if phase == "triage":
        comments_note = (
            "\nWhen viewing the issue using gh issue view, pass --comments so you read the full comment thread.\n"
        )

    return f"""You are running unattended, invoked by the agent-session board-driver.

Read {skill_dir}/SKILL.md, then read {skill_dir}/{phase_file} and follow it
exactly for this issue:

  {url}
{comments_note}
The skill is not installed as a registered skill. Its files live at {skill_dir} and
you must read them from there by absolute path.

Stop at the merge gate and report the verdict. Do not merge the PR and do not enable
auto-merge.

There is no human watching this run. If the phase directs you to stop and surface
something, stop and state plainly what needs a decision and why. Do not substitute
your own judgment for the decision just because nobody is here to answer: a parked
issue is a normal, expected outcome for this driver, and an unattended guess is not."""


def fetch_board_json(board: str) -> list[dict]:
    if not board or "/" not in board:
        return []
    owner, num = board.split("/", 1)
    try:
        cmd = ["gh", "project", "item-list", num, "--owner", owner, "--format", "json", "--limit", "500"]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(res.stdout)
        items = data.get("items", [])
        say(f"board {board}: read {len(items)} items (advisory only; does not gate)")
        return items if isinstance(items, list) else []
    except Exception:
        return []


def check_pr_unresolved_threads(repo: str, pr_num: str | int) -> int:
    parts = repo.split("/")
    if len(parts) != 2:
        return 0
    owner, repo_name = parts
    query = """query($owner:String!,$repo:String!,$pr:Int!){
      repository(owner:$owner,name:$repo){
        pullRequest(number:$pr){
          reviewThreads(first:100){
            nodes{isResolved}
          }
        }
      }
    }"""
    try:
        cmd = [
            "gh",
            "api",
            "graphql",
            "-f",
            f"query={query}",
            "-F",
            f"owner={owner}",
            "-F",
            f"repo={repo_name}",
            "-F",
            f"pr={pr_num}",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(res.stdout)
        nodes = (
            data.get("data", {})
            .get("repository", {})
            .get("pullRequest", {})
            .get("reviewThreads", {})
            .get("nodes", [])
        )
        return sum(1 for n in nodes if isinstance(n, dict) and not n.get("isResolved"))
    except Exception:
        return 0


def check_pr_ci_status(repo: str, pr_num: str | int) -> tuple[int, int]:
    """Returns (failed_count, pending_count)."""
    try:
        cmd = ["gh", "pr", "checks", str(pr_num), "--repo", repo, "--json", "name,bucket"]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        checks = json.loads(res.stdout)
        failed = sum(1 for c in checks if isinstance(c, dict) and c.get("bucket") not in ("pass", "skipping", "pending"))
        pending = sum(1 for c in checks if isinstance(c, dict) and c.get("bucket") == "pending")
        return failed, pending
    except Exception:
        return 0, 0


def check_pr_reviews(repo: str, pr_num: str | int) -> tuple[int, int]:
    """Returns (requested_count, reviewed_count)."""
    try:
        cmd = ["gh", "pr", "view", str(pr_num), "--repo", repo, "--json", "reviewRequests,reviews"]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(res.stdout)
        req = len(data.get("reviewRequests", []))
        rev = len(data.get("reviews", []))
        return req, rev
    except Exception:
        return 0, 0


def fetch_pr_gate_text(repo: str, prnum: str | int) -> tuple[str, str]:
    """Returns (full_text_including_comments, head_sha)."""
    try:
        res = subprocess.run(
            ["gh", "pr", "view", str(prnum), "--repo", repo, "--json", "body,comments,headRefOid"],
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(res.stdout)
        body = data.get("body", "") or ""
        head_sha = data.get("headRefOid", "") or ""
        comms = data.get("comments", []) or []
        comment_texts = [c.get("body", "") for c in comms if isinstance(c, dict) and c.get("body")]
        full_text = body + ("\n\n" + "\n\n".join(comment_texts) if comment_texts else "")
        return full_text, head_sha
    except Exception:
        return "", ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Agent session driver")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--skill-dir", required=True)
    parser.add_argument("--repo-path", required=True)
    parser.add_argument("--issue", default="")
    parser.add_argument("--max-issues", type=int, default=1)
    parser.add_argument("--max-budget-usd", type=float, default=10.0)
    parser.add_argument("--max-phase-attempts", type=int, default=3)
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
            die(
                f"error: --skill-dir ({skill_dir}) resolves inside --repo-path ({repo_path}); pass --allow-nested-skill-dir to proceed"
            )

    state_dir.mkdir(parents=True, exist_ok=True)
    runs_dir = state_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    runs_log = state_dir / "runs.jsonl"
    parked_log = state_dir / "parked.jsonl"
    runs_log.touch(exist_ok=True)
    parked_log.touch(exist_ok=True)

    atexit.register(lambda: release_lock(repo_path))

    # Handle orphan process warning/refusal
    inflight_file = state_dir / "inflight.json"
    if inflight_file.is_file():
        say("WARNING: a previous run died before recording its outcome:")
        try:
            inf = json.loads(inflight_file.read_text(encoding="utf-8"))
            say(f"  issue #{inf.get('issue')}  started {inf.get('started')}  run dir {inf.get('run_dir')}")
            run_dir_p = Path(inf.get("run_dir", ""))
            pid_file = run_dir_p / "child.pid"
            ipid = pid_file.read_text(encoding="utf-8").strip() if pid_file.is_file() else ""
            if ipid:
                try:
                    os.kill(int(ipid), 0)
                    is_alive = True
                except OSError:
                    is_alive = False
                if is_alive:
                    say(f"  ORPHAN STILL RUNNING (pid {ipid}, reparented) -- it is unsupervised and still spending.")
                    say(f"  Let it finish, then:  --classify-only {inf.get('issue')}")
                    say(f"  Or kill it:           kill -TERM {ipid}")
                    if not args.dry_run:
                        die("refusing to start a second run while an orphan is live")
                    say("")
                else:
                    say(f"  recover it with:  --classify-only {inf.get('issue')}")
                    say("")
            else:
                say(f"  recover it with:  --classify-only {inf.get('issue')}")
                say("")
        except Exception:
            pass

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
        say(f"== classify-only #{issue_num} ==")
        open_prs = gh_query.fetch_prs(repo, state="all")
        matching_pr = gh_query.pr_for_issue(issue_num, open_prs)

        matching_pr_dict = None
        if matching_pr:
            pr_num = matching_pr.split("\t")[0]
            for pr in open_prs:
                if str(pr.get("number")) == str(pr_num):
                    matching_pr_dict = pr
                    break

        runs_matching = sorted(runs_dir.glob(f"{issue_num}-*"), key=lambda p: p.stat().st_mtime, reverse=True)
        rundir = runs_matching[0] if runs_matching else None

        cost = 0.0
        session = ""
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        if rundir and (rundir / "stream.jsonl").is_file():
            say(f"  run dir  {rundir}")
            raw = rundir / "stream.jsonl"
            parsed = agent_runner.parse_result_stream(args.backend, raw)
            cost = parsed["total_cost_usd"]
            session = parsed["session_id"]
            ts = rundir.name.replace(f"{issue_num}-", "")
            say(f"  recovered from stream: cost ${cost}  session {session or 'none'}")
        else:
            say(f"  no run dir found for #{issue_num}; classifying from the PR alone")

        if not matching_pr_dict:
            outcome = "parked"
            reason = f"no open PR found for #{issue_num}"
            prurl = ""
        else:
            pr_num = matching_pr_dict.get("number") or ""
            prurl = matching_pr_dict.get("url", "")
            pr_text, head_sha = fetch_pr_gate_text(repo, pr_num)
            failed_ci, _ = check_pr_ci_status(repo, pr_num)
            ci_checks = "failed" if failed_ci > 0 else "pass"
            outcome_res = gate.classify(pr_text, head_sha=head_sha, ci_checks=ci_checks)
            outcome = outcome_res["outcome"]
            reason = outcome_res["reason"]

        say(f"  outcome  {outcome}")
        say(f"  reason   {reason}")
        if prurl:
            say(f"  pr       {prurl}")

        apply_park_state(issue_num, outcome, ts, reason, repo, state_dir, parked_log)
        if inflight_file.is_file():
            inflight_file.unlink(missing_ok=True)
        say("\nrecorded to runs.jsonl. Nothing was merged.")
        return 0

    # Dry run or selection
    say("== select ==")
    board_items = fetch_board_json(args.board) if args.board and not args.all_issues else []

    board_nums = set()
    for item in board_items:
        st = item.get("status", "")
        prio = item.get("priority", "")
        if st == "Ready" or prio in ("P0", "P1"):
            content = item.get("content", {})
            if isinstance(content, dict) and "number" in content:
                board_nums.add(str(content["number"]))

    try:
        cmd = ["gh", "issue", "list", "--repo", repo, "--state", "open", "--limit", "500", "--json", "number,title,body,labels,url"]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        open_issues = json.loads(res.stdout)
    except Exception as e:
        log(f"failed to list open issues: {e}")
        open_issues = []

    total_issues = len(open_issues)

    if not args.all_issues:
        filtered_issues = []
        for iss in open_issues:
            num_str = str(iss.get("number"))
            labels = [l.get("name", "") for l in iss.get("labels", []) if isinstance(l, dict)]
            has_priority_label = any(p_lbl in labels for p_lbl in ("P0", "P1", "P2", "P3", "P4", "P5"))
            if num_str in board_nums or has_priority_label:
                filtered_issues.append(iss)
    else:
        filtered_issues = open_issues

    candidates_json = []
    markerless_json = []
    for iss in filtered_issues:
        labels = [l.get("name", "") for l in iss.get("labels", []) if isinstance(l, dict)]
        if SPEC_LABEL in labels:
            if MERGE_READY_LABEL not in labels:
                candidates_json.append(iss)
        else:
            markerless_json.append(iss)
    all_issues_json = candidates_json + markerless_json
    parked = parked_numbers(all_issues_json)

    open_prs = gh_query.fetch_open_prs(repo)

    p1_unblock: list[tuple[str, str]] = []
    p2_execute: list[tuple[str, str]] = []
    p3_groom: list[tuple[str, str]] = []
    p4_escalate: list[tuple[str, str]] = []

    # Process markerless issues
    markerless_list = []
    for m_iss in markerless_json:
        m = str(m_iss.get("number"))
        markerless_list.append(f"#{m}")
        if m in parked and str(m) != args.retry:
            reason = park_reason(m, state_dir)
            say(f"  SKIP    #{m}  parked: {reason}")
        else:
            phase = "triage"
            attempts = get_attempts(m, repo, issues_json=all_issues_json)
            if attempts >= args.max_phase_attempts:
                reason = f"MAX_PHASE_ATTEMPTS ({args.max_phase_attempts}) reached for phase {phase}"
                apply_park_state(m, "parked", datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"), f"parked by loop breaker: {reason}", repo, state_dir, parked_log)
                say(f"  SKIP    #{m}  {reason}")
            else:
                p3_groom.append((m, phase))
                say(f"  ELIGIBLE #{m}  triage (Priority 3: Groom)")

    if markerless_json:
        say(f"repo {repo}: read {total_issues} open issues ({len(candidates_json)} carry the label; {len(markerless_json)} do not: {', '.join(markerless_list)} -- run triage)")
    else:
        say(f"repo {repo}: read {total_issues} open issues")

    # Process specced candidates
    for c_iss in candidates_json:
        n = str(c_iss.get("number"))
        body = c_iss.get("body", "")
        labels = [l.get("name", "") for l in c_iss.get("labels", []) if isinstance(l, dict)]
        tier = gate.tier_of(body, labels=labels)

        is_parked = n in parked and str(n) != args.retry
        parked_r = park_reason(n, state_dir) if is_parked else ""

        is_invalid_tier = tier in ("conflict", "unparsed")
        tier_r = f"tier is invalid ({tier})"

        prline = gh_query.pr_blocking_issue(n, open_prs)
        if prline:
            prnum = prline.split("\t")[0]
            unresolved = check_pr_unresolved_threads(repo, prnum)
            if unresolved > 0:
                phase = "address_comments"
            else:
                failed_ci, pending_ci = check_pr_ci_status(repo, prnum)
                if failed_ci > 0:
                    phase = "fix_ci"
                elif pending_ci > 0:
                    say(f"  SKIP    #{n}  PR #{prnum} CI is still pending; waiting...")
                    continue
                else:
                    req_rev, revd = check_pr_reviews(repo, prnum)
                    if req_rev == 0 and revd == 0:
                        phase = "request_review"
                    else:
                        phase = "grade_gate"

            attempts = get_attempts(n, repo, issues_json=all_issues_json)
            if attempts >= args.max_phase_attempts:
                reason = f"MAX_PHASE_ATTEMPTS ({args.max_phase_attempts}) reached for phase {phase}"
                apply_park_state(n, "parked", datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"), f"parked by loop breaker: {reason}", repo, state_dir, parked_log)
                say(f"  SKIP    #{n}  {reason}")
            else:
                p1_unblock.append((n, phase))
                say(f"  ELIGIBLE #{n}  tier: auto-ok (Priority 1: Unblock - {phase})")
                if is_parked:
                    say(f"  NOTE    #{n}  Bypassing park state (parked: {parked_r}) to perform Unblock phase: {phase}")
        else:
            if is_parked:
                say(f"  SKIP    #{n}  parked: {parked_r}")
            elif is_invalid_tier:
                say(f"  SKIP    #{n}  {tier_r}")
            elif tier in ("needs-review", "missing"):
                phase = "refine"
                attempts = get_attempts(n, repo, issues_json=all_issues_json)
                if attempts >= args.max_phase_attempts:
                    reason = f"MAX_PHASE_ATTEMPTS ({args.max_phase_attempts}) reached for phase {phase}"
                    apply_park_state(n, "parked", datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"), f"parked by loop breaker: {reason}", repo, state_dir, parked_log)
                    say(f"  SKIP    #{n}  {reason}")
                else:
                    p3_groom.append((n, phase))
                    say(f"  ELIGIBLE #{n}  tier: needs-review (Priority 3: Groom - {phase})")
            elif tier == "auto-ok":
                phase = "execute"
                attempts = get_attempts(n, repo, issues_json=all_issues_json)
                if attempts >= args.max_phase_attempts:
                    reason = f"MAX_PHASE_ATTEMPTS ({args.max_phase_attempts}) reached for phase {phase}"
                    apply_park_state(n, "parked", datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"), f"parked by loop breaker: {reason}", repo, state_dir, parked_log)
                    say(f"  SKIP    #{n}  {reason}")
                else:
                    p2_execute.append((n, phase))
                    say(f"  ELIGIBLE #{n}  tier: auto-ok (Priority 2: Execute - {phase})")

    all_candidates: list[tuple[str, str]] = p1_unblock + p2_execute + p3_groom + p4_escalate

    # Single issue override
    if args.issue:
        iss_override = str(args.issue)
        say(f"== select (single issue: #{iss_override}) ==")
        phase = "execute"
        prline = gh_query.pr_for_issue(iss_override, open_prs)
        if prline:
            prnum = prline.split("\t")[0]
            unresolved = check_pr_unresolved_threads(repo, prnum)
            if unresolved > 0:
                phase = "address_comments"
            else:
                failed_ci, pending_ci = check_pr_ci_status(repo, prnum)
                if failed_ci > 0:
                    phase = "fix_ci"
                elif pending_ci > 0:
                    phase = "wait_ci"
                else:
                    phase = "grade_gate"

        if phase == "wait_ci":
            say(f"PR for #{iss_override} CI is still pending; waiting...")
            all_candidates = []
        else:
            say("  eligibility check bypassed by --issue")
            all_candidates = [(iss_override, phase)]

    locked_candidates: list[tuple[str, str]] = []
    for cand_item in all_candidates:
        num, cand_phase = cand_item
        if acquire_lock(num, cand_phase, repo_path):
            locked_candidates.append(cand_item)
            break
        else:
            say(f"  SKIP    #{num}  lock contention (another agent holds or held lock)")

    c_count = len(locked_candidates)
    eligible_str = f"{locked_candidates[0][0]}:{locked_candidates[0][1]}" if locked_candidates else ""
    say(f"eligible: {c_count} ({eligible_str})")

    if args.dry_run:
        say("\ndry run -- no claude invocation.")
        return 0

    if not locked_candidates:
        say("\n== report ==")
        say("nothing eligible; no runs attempted. Reasons are listed above.")
        return 0

    # Execute run on eligible issues up to max-issues
    attempted = 0
    total_cost = 0.0
    summary_rows = []

    for num, phase in locked_candidates:
        if attempted >= args.max_issues:
            say("\nreached --max-issues; stopping with issues still eligible.")
            break

        increment_attempts(num, repo)
        url = f"https://github.com/{repo}/issues/{num}"
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        rundir = state_dir / "runs" / f"{num}-{ts}"
        rundir.mkdir(parents=True, exist_ok=True)
        raw_output = rundir / "stream.jsonl"
        stderr_output = rundir / "stderr.txt"

        prompt = build_prompt(url, phase, skill_dir)
        prompt_file = rundir / "prompt.txt"
        prompt_file.write_text(prompt, encoding="utf-8")

        say("")
        say(f"== invoke #{num} ==")
        say(f"  issue    {url}")
        say(f"  cwd      {repo_path}")
        say(f"  budget   ${args.max_budget_usd}   timeout {args.timeout}s")
        say(f"  run dir  {rundir}")

        # Post start discussion note
        try:
            discussion_manager.post_start(
                repo=repo, issue=num, phase=phase, budget=args.max_budget_usd, rundir=str(rundir)
            )
        except Exception:
            pass

        # Write inflight marker
        inflight_file.write_text(
            json.dumps({"issue": int(num), "started": ts, "run_dir": str(rundir), "url": url}), encoding="utf-8"
        )

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
        pid_file = rundir / "child.pid"
        if pid_file.is_file():
            pid_file.unlink(missing_ok=True)

        parsed = agent_runner.parse_result_stream(args.backend, raw_output)
        final_text = parsed.get("final", "")
        cost = parsed.get("total_cost_usd", 0.0)
        session_id = parsed.get("session_id", "")
        cost_known = parsed.get("cost_known", False)

        (rundir / "parsed.json").write_text(json.dumps(parsed, indent=2), encoding="utf-8")
        (rundir / "final.txt").write_text(final_text, encoding="utf-8")

        say(f"  exit {ret}   cost ${cost}   session {session_id or 'none'}")

        # Classify outcome
        prurl = ""
        if ret == 124:
            outcome = "failed"
            reason = f"timed out after {args.timeout}s"
        elif ret != 0 and not session_id and cost == 0.0 and not agent_runner.stream_has_events(raw_output):
            outcome = "driver-fault"
            reason = f"{args.backend} exited {ret} before starting (no readable events, no session, no spend) -- see {stderr_output}"
        elif ret != 0 and not agent_runner.has_success_result(args.backend, raw_output):
            outcome = "failed"
            reason = f"{args.backend} exited {ret}" if cost_known else f"{args.backend} exited {ret}; cost undetermined"
        else:
            prs_json = gh_query.fetch_open_prs(repo)
            prline = gh_query.pr_for_issue(num, prs_json)
            if not prline:
                if phase in ("triage", "refine"):
                    try:
                        res = subprocess.run(["gh", "issue", "view", num, "--repo", repo, "--json", "labels"], capture_output=True, text=True, check=True)
                        lbls = [l.get("name") for l in json.loads(res.stdout).get("labels", []) if isinstance(l, dict)]
                    except Exception:
                        lbls = []
                    if PARK_LABEL in lbls or INTERACTIVE_LABEL in lbls:
                        outcome = "parked"
                        reason = f"parked by agent during {phase}: {final_text[:400]}"
                    else:
                        outcome = "incomplete"
                        reason = f"{phase} completed; issue unparked for re-evaluation: {final_text[:400]}"
                else:
                    outcome = "parked"
                    reason = f"no PR opened; run's own account: {final_text[:400]}"
            else:
                prnum, prurl = prline.split("\t")[:2]
                pr_text, head_sha = fetch_pr_gate_text(repo, prnum)
                failed_ci, _ = check_pr_ci_status(repo, prnum)
                ci_checks = "failed" if failed_ci > 0 else "pass"
                outcome_res = gate.classify(pr_text, head_sha=head_sha, ci_checks=ci_checks)
                outcome = outcome_res["outcome"]
                reason = outcome_res["reason"]
                (rundir / "gate.yaml").write_text(outcome_res.get("gate", ""), encoding="utf-8")

        if outcome in ("incomplete", "parked", "no-gate") and cost >= (args.max_budget_usd * 0.95):
            outcome = "budget-exhausted"
            reason = f"spent ${cost} of ${args.max_budget_usd} (>=95%) and never reached the gate"

        say(f"  outcome  {outcome}")
        say(f"  reason   {reason}")
        if prurl:
            say(f"  pr       {prurl}")

        # Record run
        row = {
            "issue": int(num),
            "repo": repo,
            "started": ts,
            "exit": ret,
            "cost_usd": cost,
            "session_id": session_id,
            "outcome": outcome,
            "reason": reason,
            "pr": prurl,
            "run_dir": str(rundir),
            "provenance": {},
        }
        with open(runs_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")

        apply_park_state(num, outcome, ts, reason, repo, state_dir, parked_log)

        # Post finish discussion note
        try:
            discussion_manager.post_finish(
                repo=repo,
                issue=num,
                phase=phase,
                outcome=outcome,
                cost=cost,
                session=session_id or "none",
                prurl=prurl or "none",
                reason=reason,
                rundir=str(rundir),
            )
        except Exception:
            pass

        if inflight_file.is_file():
            inflight_file.unlink(missing_ok=True)

        total_cost += cost
        attempted += 1
        summary_rows.append((num, outcome, reason, prurl))

        if outcome in ("failed", "driver-fault", "budget-exhausted"):
            say("\nstopping the loop: outcome means an assumption is wrong, and retrying spends money on it.")
            break

    say("\n== report ==")
    say(f"attempted {attempted} issue(s), total cost ${total_cost:.4f}")
    for num, outcome, reason, prurl in summary_rows:
        say(f"  #{num}  {outcome}")
        say(f"        {reason}")
        if prurl:
            say(f"        {prurl}")

    say("\nNothing was merged. eligible-for-auto-merge is a finding, not an action --")
    say("acting on it is a separate decision (phase 3 of docs/design.md's rollout).")
    say(f"State: {state_dir}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
