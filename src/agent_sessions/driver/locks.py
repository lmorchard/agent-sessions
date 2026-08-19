"""Git ref lock acquisition and release for issue execution."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from datetime import timezone
from pathlib import Path

CURRENT_LOCK_ISSUE: str | None = None


def log(msg: str) -> None:
    from agent_sessions.driver import agent_session_driver

    ts = agent_session_driver.datetime.now(timezone.utc).strftime("%H:%M:%SZ")
    sys.stderr.write(f"{ts}  {msg}\n")


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
