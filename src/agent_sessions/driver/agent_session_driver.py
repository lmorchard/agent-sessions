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
from agent_sessions.driver import (
    agent_runner,
    credentials,
    discussion_manager,
    gate,
    gh_query,
    router,
    writes,
)

PARK_LABEL = "agent-session:needs-human"
INTERACTIVE_LABEL = "agent-session:needs-human-interactive"
MERGE_READY_LABEL = "agent-session:merge-ready"
SPEC_LABEL = "agent-session:spec"
MARKER = "<!-- agent-session:spec -->"

PHASE_TIERS = {
    "triage": "low",
    "refine": "low",
    "execute": "high",
    "address_comments": "high",
    "fix_ci": "high",
    "fix_conflict": "high",
    "request_review": "low",
    "grade_gate": "low",
}


def is_specced(iss: dict) -> bool:
    labels = [l.get("name") for l in iss.get("labels", []) if isinstance(l, dict)]
    return SPEC_LABEL in labels or MARKER in (iss.get("body") or "")

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


def decrement_attempts(issue_number: str | int, repo: str) -> None:
    count = get_attempts(issue_number, repo) - 1
    if count < 0:
        count = 0
    label_mgr = Path(__file__).parent.parent / "scripts" / "label_manager.py"
    cmd = [sys.executable, str(label_mgr)]
    if repo:
        cmd.extend(["--repo", repo])
    if count == 0:
        cmd.extend(["clear-attempts", "--issue", str(issue_number)])
    else:
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


def has_new_human_comment(
    issue_number: str | int,
    repo: str,
    bot_logins: frozenset[str] | set[str] | None = None,
    park_time: str = "",
) -> tuple[bool, str]:
    """Check if a human user posted a comment on a parked issue AFTER it was parked.
    Returns (has_human_comment, author_login).

    `bot_logins` must include the driver's own login (`credentials.bot_logins`
    builds it). A PAT-backed account carries no `[bot]` suffix, so without it the
    driver's own park explanation reads as a human reply and unparks the issue it
    just parked -- issue #183.
    """
    known_bots = {name.lower() for name in (bot_logins or credentials.ALWAYS_BOT_LOGINS)}
    try:
        cmd = ["gh", "issue", "view", str(issue_number), "--repo", repo, "--json", "comments"]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(res.stdout)
        comments = data.get("comments", [])
        if not comments:
            return False, ""

        norm_park_time = park_time.replace("-", "").replace(":", "").replace(" ", "") if park_time else ""

        for comment_obj in reversed(comments):
            author = comment_obj.get("author", {}) if isinstance(comment_obj, dict) else {}
            login = author.get("login", "") if isinstance(author, dict) else ""
            if not login or login.endswith("[bot]") or login.lower() in known_bots:
                continue

            if norm_park_time:
                created_at = str(comment_obj.get("createdAt", "")) if isinstance(comment_obj, dict) else ""
                norm_created = created_at.replace("-", "").replace(":", "").replace(" ", "")
                if norm_created and norm_created <= norm_park_time:
                    continue

            return True, login

        try:
            pr_cmd = ["gh", "pr", "view", str(issue_number), "--repo", repo, "--json", "reviews"]
            pr_res = subprocess.run(pr_cmd, capture_output=True, text=True)
            if pr_res.returncode == 0:
                pr_data = json.loads(pr_res.stdout)
                reviews = pr_data.get("reviews", [])
                for rev in reversed(reviews):
                    author = rev.get("author", {}) if isinstance(rev, dict) else {}
                    login = author.get("login", "") if isinstance(author, dict) else ""
                    if not login or login.endswith("[bot]") or login.lower() in known_bots:
                        continue
                    if norm_park_time:
                        created_at = str(rev.get("submittedAt", "")) if isinstance(rev, dict) else ""
                        norm_created = created_at.replace("-", "").replace(":", "").replace(" ", "")
                        if norm_created and norm_created <= norm_park_time:
                            continue
                    return True, login
        except Exception:
            pass

        return False, ""
    except Exception:
        return False, ""


def get_park_time(issue_number: str | int, state_dir: Path | None) -> str:
    """Find the latest timestamp for issue_number in parked.jsonl or runs.jsonl."""
    if not state_dir:
        return ""
    last_ts = ""
    for filename, field in (("parked.jsonl", "parked_at"), ("runs.jsonl", "started")):
        log = state_dir / filename
        if not log.is_file():
            continue
        for line in log.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                if str(row.get("issue")) == str(issue_number):
                    ts = str(row.get(field, ""))
                    if ts and ts > last_ts:
                        last_ts = ts
            except Exception:
                pass
    return last_ts


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
    quiet: bool = False,
) -> None:
    iss_num = str(issue_number)
    if outcome in ("parked", "failed", "no-gate"):
        row = {"issue": int(iss_num), "repo": repo, "parked_at": ts, "outcome": outcome, "reason": reason}
        with open(parked_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        park_label_add(iss_num, repo)
        if not quiet:
            say(f"  parked -- excluded from future selection unless --retry {iss_num}")
        notify_human(iss_num, f"{outcome}: {reason}", state_dir)
    elif outcome == "gate-human":
        row = {"issue": int(iss_num), "repo": repo, "parked_at": ts, "outcome": outcome, "reason": reason}
        with open(parked_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        park_label_add(iss_num, repo)
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


def build_prompt(url_or_number: str | int, phase: str, skill_dir: Path, writes_file: Path | str = "", extra_context: str = "") -> str:
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

    extra_note = ""
    if extra_context:
        extra_note = f"\n\nAdditional Resumed Context:\n{extra_context}\n"

    manifest = str(writes_file) if writes_file else f"the path in ${agent_runner.WRITES_FILE_VAR}"

    return f"""You are running unattended, invoked by the agent-session board-driver.

Read {skill_dir}/SKILL.md, then read {skill_dir}/{phase_file} and follow it
exactly for this issue:

  {url}
{comments_note}{extra_note}
The skill is not installed as a registered skill. Its files live at {skill_dir} and
you must read them from there by absolute path.

Your GitHub credential is read-scoped. Reads work normally -- gh issue view, gh pr
view, gh pr checks, gh api graphql queries -- but every write will be refused, and
no amount of retrying will change that. Record the writes you want instead, by
appending one JSON object per line to the write manifest at:

  {manifest}

The driver validates that file and performs the writes for you after this run ends.
Read {skill_dir}/references/write-manifest.md for the entry shapes. A write you do
not record does not happen, so record it before you finish.

Stop at the merge gate and report the verdict. There is no manifest entry that
merges a PR or enables auto-merge, by design.

There is no human watching this run. If the phase directs you to stop and surface
something, record an issue_comment entry explaining plainly what needs a decision,
why, and what options exist, plus a label entry applying the parking label, and
state the verdict. Do not substitute your own judgment for the decision just because
nobody is here to answer: a parked issue is a normal, expected outcome for this
driver, and an unattended guess is not."""


def is_git_ignored(path: Path | str, repo_path: Path | str) -> bool:
    """Whether git would refuse to add `path`. Absent files count as ignored: there
    is nothing there to commit, and treating "no file" as exposed would refuse every
    run that configures the driver entirely from the environment."""
    p = Path(path)
    if not p.exists():
        return True
    try:
        res = subprocess.run(
            ["git", "-C", str(repo_path), "check-ignore", "-q", str(p.resolve())],
            capture_output=True,
        )
        return res.returncode == 0
    except Exception:
        # Not a repo, or no git. Nothing here can be committed by this driver.
        return True


def whoami(env: dict[str, str]) -> str:
    """The GitHub login a token authenticates as, or "" if it cannot be resolved."""
    try:
        res = subprocess.run(
            ["gh", "api", "user", "--jq", ".login"],
            capture_output=True,
            text=True,
            check=True,
            env=env,
        )
        return res.stdout.strip()
    except Exception:
        return ""


def perform_writes(writes_file: Path, repo: str, repo_path: Path, rundir: Path, board: str = "") -> dict:
    """Run the agent's write manifest under the driver's write credential.

    The agent could not perform these itself -- its token is read-scoped -- so this
    is where the run's comments, labels, branch push and PR actually happen. The
    driver validates first and applies nothing if any entry is malformed.
    """
    messages: list[str] = []
    try:
        entries = writes.load(writes_file)
        result = writes.execute(
            entries,
            repo=repo,
            repo_path=repo_path,
            scratch=rundir / "writes",
            env=dict(os.environ),
            board=board,
        )
    except writes.ManifestError as e:
        entries = []
        result = {"ok": False, "errors": [str(e)], "results": []}

    applied = sum(1 for r in result["results"] if r.get("status") == "ok")
    (rundir / "writes-result.json").write_text(
        json.dumps({"entries": entries, **result}, indent=2), encoding="utf-8"
    )

    if not entries and result["ok"]:
        messages.append("  writes   none recorded")
    else:
        messages.append(f"  writes   {applied}/{len(entries)} applied by the driver")
    for err in result["errors"]:
        messages.append(f"  WRITE REJECTED  {err}")
    for r in result["results"]:
        if r.get("status") == "failed":
            messages.append(f"  WRITE FAILED    {r.get('kind')}: {(r.get('stderr') or '').strip()[:200]}")

    result["messages"] = messages
    result["entries"] = entries
    result["applied"] = applied
    return result


def writes_summary(result: dict) -> str:
    """A one-line account of a manifest that did not fully apply, for `reason`."""
    if result["ok"]:
        return ""
    if result["errors"]:
        return f"write manifest rejected ({len(result['errors'])} error(s)): {result['errors'][0]}"
    failed = [r for r in result["results"] if r.get("status") == "failed"]
    if failed:
        return f"write failed at {failed[0].get('kind')}: {(failed[0].get('stderr') or '').strip()[:200]}"
    return "write manifest did not fully apply"


def board_command(board: str, limit: int = 500) -> list[str]:
    """The one place the board read is spelled.

    `make doctor` runs this too. It used to probe the board with a GraphQL query
    instead, which succeeded while this failed -- `gh project` needs `read:org` to
    resolve `--owner` and dies with `unknown owner type` without it. A check that
    asks a different question than the code it is checking reported a configuration
    that could not select an issue as healthy.
    """
    owner, num = board.split("/", 1)
    return ["gh", "project", "item-list", num, "--owner", owner, "--format", "json", "--limit", str(limit)]


def fetch_board_json(board: str) -> list[dict]:
    if not board or "/" not in board:
        return []
    try:
        res = subprocess.run(board_command(board), capture_output=True, text=True, check=True)
        data = json.loads(res.stdout)
        items = data.get("items", [])
        say(f"board {board}: read {len(items)} items (advisory only; does not gate)")
        return items if isinstance(items, list) else []
    except Exception as e:
        # Saying nothing here is how an unreadable board looks like an empty one.
        # Selection then falls back to priority labels, and if no issue carries one
        # the pass reports `eligible: 0` with no hint that a credential is at fault.
        detail = getattr(e, "stderr", "") or str(e)
        say(f"board {board}: UNREADABLE ({' '.join(str(detail).split())[:120]}) -- selection falls back to priority labels")
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


def check_pr_reviews(repo: str, pr_num: str | int) -> tuple[int, int, str]:
    """Returns (requested_count, reviewed_count, reviewDecision)."""
    try:
        cmd = ["gh", "pr", "view", str(pr_num), "--repo", repo, "--json", "reviewRequests,reviews,reviewDecision"]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(res.stdout)
        req = len(data.get("reviewRequests", []))
        rev = len(data.get("reviews", []))
        decision = data.get("reviewDecision") or ""
        return req, rev, decision
    except Exception:
        return 0, 0, ""


def load_env_file(env_file: Path | str = ".env") -> set[str]:
    """Apply a `.env`, and report which keys it *contains*.

    Containment, not application: a key already set in the environment is not
    overwritten, but it is still sitting in a file on disk, which is what the write
    token exposure check cares about.
    """
    path = Path(env_file)
    keys: set[str] = set()
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                keys.add(k.strip())
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return keys


def main(argv: list[str] | None = None) -> int:
    env_file = Path(".env")
    env_file_keys = load_env_file(env_file)

    parser = argparse.ArgumentParser(description="Agent session driver")
    parser.add_argument("--repo", default=os.environ.get("REPO") or os.environ.get("DRIVER_REPO") or "")
    parser.add_argument("--skill-dir", default=os.environ.get("SKILL_DIR") or os.environ.get("DRIVER_SKILL_DIR") or "")
    parser.add_argument("--repo-path", default=os.environ.get("REPO_PATH") or os.environ.get("DRIVER_REPO_PATH") or "")
    parser.add_argument("--issue", default=os.environ.get("ISSUE") or "")
    parser.add_argument("--max-issues", type=int, default=int(os.environ.get("MAX_ISSUES", "1")))
    parser.add_argument(
        "--max-budget-usd",
        type=float,
        default=float(os.environ.get("MAX_BUDGET_USD") or os.environ.get("MAX_BUDGET") or "10.0"),
    )
    parser.add_argument("--max-phase-attempts", type=int, default=int(os.environ.get("MAX_PHASE_ATTEMPTS", "3")))
    parser.add_argument(
        "--timeout", type=int, default=int(os.environ.get("RUN_TIMEOUT") or os.environ.get("TIMEOUT") or "5400")
    )
    parser.add_argument("--state-dir", default=os.environ.get("STATE_DIR") or "")
    parser.add_argument("--board", default=os.environ.get("BOARD") or os.environ.get("DRIVER_BOARD") or "")
    parser.add_argument(
        "--backend", default=os.environ.get("BACKEND") or os.environ.get("DRIVER_BACKEND") or "claude"
    )
    parser.add_argument("--model", default=os.environ.get("MODEL") or "")
    parser.add_argument("--high-tier-model", default=os.environ.get("HIGH_TIER_MODEL") or "")
    parser.add_argument("--low-tier-model", default=os.environ.get("LOW_TIER_MODEL") or "")
    parser.add_argument("--retry", default=os.environ.get("RETRY") or "")
    parser.add_argument("--classify-only", default="")
    parser.add_argument("--resumed-from", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-nested-skill-dir", action="store_true")
    parser.add_argument("--all-issues", action="store_true")

    args = parser.parse_args(argv)

    repo = args.repo
    if not repo:
        die("--repo (or REPO in .env) is required")

    parts = repo.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1] or "." in parts or ".." in parts:
        die(f"--repo must be owner/name, with exactly one '/': {repo}")

    if not args.skill_dir:
        die("--skill-dir (or SKILL_DIR in .env) is required")
    if not args.repo_path:
        die("--repo-path (or REPO_PATH in .env) is required")

    skill_dir = abspath(args.skill_dir)
    repo_path = abspath(args.repo_path)

    # The credential split, before anything spends either credential. There is no
    # degraded mode: the driver runs under its own GitHub account or it does not run.
    #
    # The user-level file loads second, so a project `.env` still wins. It exists so
    # the write credential has somewhere durable to live that is neither shell
    # history nor a file inside the agent's working tree.
    user_config = credentials.user_config_path()
    mode_problem = credentials.file_mode_error(user_config)
    if mode_problem:
        die(mode_problem)
    user_config_keys = load_env_file(user_config)

    creds = credentials.resolve()
    for keys, path in ((env_file_keys, env_file), (user_config_keys, user_config)):
        exposure = credentials.exposure_error(keys, path, repo_path, git_ignored=is_git_ignored(path, repo_path))
        if exposure:
            die(exposure)
    config_problem = credentials.config_error(creds)
    if config_problem:
        die(config_problem)

    read_login = whoami(credentials.agent_env(dict(os.environ), creds))
    write_login = whoami(credentials.driver_env(dict(os.environ), creds))
    identity_problem = credentials.identity_error(creds, read_login=read_login, write_login=write_login)
    if identity_problem:
        die(identity_problem)
    say(f"identity: acting as {creds.login} (agent reads, driver writes)")
    # Resolved once. If the read token came from a `_CMD`, this is what stops
    # `agent_runner` re-running the keychain lookup for the child.
    os.environ[credentials.READ_TOKEN_VAR] = creds.read_token

    driver_bots = credentials.bot_logins(creds)
    try:
        res = subprocess.run(
            ["git", "-C", str(repo_path), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=True,
        )
        remote_warning = credentials.remote_warning(res.stdout)
    except Exception:
        remote_warning = ""
    if remote_warning:
        say(remote_warning)
    credentials.apply_driver_env(creds)

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
            pr_body = matching_pr_dict.get("body", "")
            head_sha = ""
            changed_files = None
            base_ref = ""
            files_list: list[str] = []
            try:
                res = subprocess.run(
                    ["gh", "pr", "view", str(pr_num), "--repo", repo, "--json", "headRefOid,changedFiles,baseRefName,files"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                pr_data = json.loads(res.stdout)
                head_sha = pr_data.get("headRefOid", "")
                changed_files = pr_data.get("changedFiles", None)
                base_ref = pr_data.get("baseRefName", "")
                files_list = [str(f.get("path")) for f in pr_data.get("files", []) if isinstance(f, dict) and f.get("path") is not None]
            except Exception:
                head_sha = ""
                changed_files = None
                base_ref = ""
                files_list = []

            failed_ci, _ = check_pr_ci_status(repo, pr_num)
            ci_checks = "failed" if failed_ci > 0 else "pass"
            outcome_res = gate.classify(
                pr_body,
                head_sha=head_sha,
                ci_checks=ci_checks,
                changed_files=changed_files,
                pr_files=files_list,
            )
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

    try:
        cmd = ["gh", "issue", "list", "--repo", repo, "--state", "open", "--limit", "500", "--json", "number,title,body,labels,url"]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        open_issues = json.loads(res.stdout)
    except Exception as e:
        log(f"failed to list open issues: {e}")
        open_issues = []

    board_nums = set()
    for item in board_items:
        st = item.get("status", "")
        prio = item.get("priority", "")
        if st == "Ready" or prio in ("P0", "P1"):
            content = item.get("content", {})
            if isinstance(content, dict) and "number" in content:
                board_nums.add(str(content["number"]))

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

    candidates_json = [
        iss
        for iss in filtered_issues
        if is_specced(iss)
        and not any(
            isinstance(l, dict) and l.get("name") == MERGE_READY_LABEL
            for l in iss.get("labels", [])
        )
    ]
    markerless_json = [iss for iss in filtered_issues if not is_specced(iss)]
    all_issues_json = candidates_json + markerless_json
    parked = parked_numbers(all_issues_json)

    open_prs = gh_query.fetch_open_prs(repo)

    parked_nums = parked
    park_reasons = {}
    attempts_map = {}
    human_comments_map = {}
    pr_details_map = {}

    for iss in all_issues_json:
        n = str(iss.get("number"))
        if n in parked_nums and n != args.retry:
            park_t = get_park_time(n, state_dir)
            has_human, login = has_new_human_comment(n, repo, driver_bots, park_time=park_t)
            human_comments_map[n] = (has_human, login)
            if not has_human:
                park_reasons[n] = park_reason(n, state_dir)
        attempts_map[n] = get_attempts(n, repo, issues_json=all_issues_json)

    for pr in open_prs:
        prnum = str(pr.get("number"))
        unresolved = check_pr_unresolved_threads(repo, prnum)
        failed_ci, pending_ci = check_pr_ci_status(repo, prnum)
        req_rev, revd, rev_decision = check_pr_reviews(repo, prnum)
        pr_details_map[prnum] = {
            "unresolved": unresolved,
            "failed_ci": failed_ci,
            "pending_ci": pending_ci,
            "req_rev": req_rev,
            "revd": revd,
            "rev_decision": rev_decision,
            "merge_state_status": pr.get("mergeStateStatus"),
            "mergeable": pr.get("mergeable"),
        }

    config = {
        "repo": repo,
        "all_issues": args.all_issues,
        "max_phase_attempts": args.max_phase_attempts,
        "retry": args.retry,
        "issue": args.issue,
    }

    sel_res = router.select(
        open_issues=open_issues,
        open_prs=open_prs,
        board_items=board_items,
        parked_nums=parked_nums,
        park_reasons=park_reasons,
        attempts_map=attempts_map,
        human_comments_map=human_comments_map,
        pr_details_map=pr_details_map,
        config=config,
    )

    for msg in sel_res["messages"]:
        say(msg)

    ts_str = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for m in sel_res["unpark_actions"]:
        park_label_remove(m, repo)

    for m, reason in sel_res["park_actions"]:
        apply_park_state(m, "parked", ts_str, f"parked by loop breaker: {reason}", repo, state_dir, parked_log, quiet=True)

    all_candidates = sel_res["candidates"]

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

        writes_file = rundir / "writes.jsonl"

        extra_context = ""
        prline = gh_query.pr_for_issue(num, open_prs)
        if prline:
            prnum = prline.split("\t")[0]
            try:
                res = subprocess.run(
                    ["gh", "pr", "view", str(prnum), "--repo", repo, "--json", "body,comments"],
                    capture_output=True,
                    text=True,
                )
                if res.returncode == 0:
                    pr_data = json.loads(res.stdout)
                    pr_body = pr_data.get("body", "")
                    if "Handoff / Parked State" in pr_body:
                        extra_context += f"Draft PR Body (Handoff State):\n{pr_body}\n\n"
                    pr_comments = pr_data.get("comments", [])
                    if pr_comments:
                        extra_context += "Recent PR Comments:\n"
                        for c in pr_comments[-3:]:  # last 3 comments
                            extra_context += f"- {c.get('author', {}).get('login', 'unknown')}: {c.get('body', '')}\n"
            except Exception:
                pass

        try:
            res = subprocess.run(
                ["gh", "issue", "view", str(num), "--repo", repo, "--json", "comments"],
                capture_output=True,
                text=True,
            )
            if res.returncode == 0:
                issue_data = json.loads(res.stdout)
                issue_comments = issue_data.get("comments", [])
                if issue_comments:
                    extra_context += "Recent Issue Comments:\n"
                    for c in issue_comments[-3:]:  # last 3 comments
                        extra_context += f"- {c.get('author', {}).get('login', 'unknown')}: {c.get('body', '')}\n"
        except Exception:
            pass

        prompt = build_prompt(url, phase, skill_dir, writes_file, extra_context=extra_context)
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
            ok = discussion_manager.post_start(
                repo=repo, issue=num, phase=phase, budget=args.max_budget_usd, rundir=str(rundir)
            )
            if not ok:
                say("  NOTE: could not post start discussion note to Lab Notebook")
        except Exception as e:
            say(f"  NOTE: failed to post start discussion note: {e}")

        # Write inflight marker
        inflight_file.write_text(
            json.dumps({"issue": int(num), "started": ts, "run_dir": str(rundir), "url": url}), encoding="utf-8"
        )

        if phase not in PHASE_TIERS:
            die(f"unknown phase: {phase}")
        tier = PHASE_TIERS[phase]

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
            "--tier", tier,
            "--writes-file", str(writes_file),
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

        # Perform the agent's GitHub writes, with the driver's credential. This has
        # to happen before classification: the PR the gate reads is one of them.
        writes_result = perform_writes(writes_file, repo, repo_path, rundir, args.board)
        for line in writes_result["messages"]:
            say(line)

        # Classify outcome
        prurl = ""
        changed_files = None
        head_sha = ""
        base_ref = ""
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
                        if "inconclusive" in final_text.lower():
                            reason = f"parked (inconclusive reply) by agent during {phase}: {final_text[:400]}"
                            decrement_attempts(num, repo)
                        else:
                            reason = f"parked by agent during {phase}: {final_text[:400]}"
                    else:
                        outcome = "incomplete"
                        reason = f"{phase} completed; issue unparked for re-evaluation: {final_text[:400]}"
                else:
                    outcome = "parked"
                    if "inconclusive" in final_text.lower():
                        reason = f"parked (inconclusive reply); run's own account: {final_text[:400]}"
                        decrement_attempts(num, repo)
                    else:
                        reason = f"no PR opened; run's own account: {final_text[:400]}"
            else:
                prnum, prurl = prline.split("\t")[:2]
                changed_files = None
                base_ref = ""
                files_list = []
                try:
                    res = subprocess.run(
                        ["gh", "pr", "view", prnum, "--repo", repo, "--json", "body,headRefOid,changedFiles,baseRefName,files"],
                        capture_output=True,
                        text=True,
                        check=True,
                    )
                    pr_data = json.loads(res.stdout)
                    pr_body = pr_data.get("body", "")
                    head_sha = pr_data.get("headRefOid", "")
                    changed_files = pr_data.get("changedFiles", None)
                    base_ref = pr_data.get("baseRefName", "")
                    files_list = [str(f.get("path")) for f in pr_data.get("files", []) if isinstance(f, dict) and f.get("path") is not None]
                except Exception:
                    pr_body = ""
                    head_sha = ""

                failed_ci, _ = check_pr_ci_status(repo, prnum)
                ci_checks = "failed" if failed_ci > 0 else "pass"
                outcome_res = gate.classify(
                    pr_body,
                    head_sha=head_sha,
                    ci_checks=ci_checks,
                    changed_files=changed_files,
                    pr_files=files_list,
                )
                outcome = outcome_res["outcome"]
                reason = outcome_res["reason"]
                (rundir / "gate.yaml").write_text(outcome_res.get("gate", ""), encoding="utf-8")

        write_note = writes_summary(writes_result)
        if write_note:
            reason = f"{reason} [{write_note}]"

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
            "phase": phase,
            "started": ts,
            "exit": ret,
            "cost_usd": cost,
            "session_id": session_id,
            "outcome": outcome,
            "reason": reason,
            "pr": prurl,
            "changed_files": changed_files if changed_files is not None else 0,
            "base_diff_sha": f"{base_ref}..{head_sha[:8]}" if (base_ref and head_sha) else head_sha[:8],
            "run_dir": str(rundir),
            "writes": {
                "recorded": len(writes_result["entries"]),
                "applied": writes_result["applied"],
                "ok": writes_result["ok"],
            },
            "provenance": {},
        }
        with open(runs_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")

        apply_park_state(num, outcome, ts, reason, repo, state_dir, parked_log)

        # Post finish discussion note
        try:
            ok = discussion_manager.post_finish(
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
            if not ok:
                say("  NOTE: could not post finish discussion note to Lab Notebook")
        except Exception as e:
            say(f"  NOTE: failed to post finish discussion note: {e}")

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
