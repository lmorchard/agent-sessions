"""Issue parking, labels, attempt management, and human notification."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from agent_sessions.driver import credentials, output
from agent_sessions.driver.output import say

PARK_LABEL = "agent-session:needs-human"
INTERACTIVE_LABEL = "agent-session:needs-human-interactive"
MERGE_READY_LABEL = "agent-session:merge-ready"
SPEC_LABEL = "agent-session:spec"
MARKER = "<!-- agent-session:spec -->"




def is_specced(iss: dict) -> bool:
    labels = [l.get("name") for l in iss.get("labels", []) if isinstance(l, dict)]
    return SPEC_LABEL in labels or MARKER in (iss.get("body") or "")


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
    issue_updated_at: str = "",
) -> tuple[bool, str]:
    norm_park_time = park_time.replace("-", "").replace(":", "").replace(" ", "") if park_time else ""
    known_bots = {name.lower() for name in (bot_logins or credentials.ALWAYS_BOT_LOGINS)}

    if repo and "/" in repo:
        try:
            owner, repo_name = repo.split("/", 1)
            query = """
            query($owner: String!, $repo: String!, $number: Int!) {
              repository(owner: $owner, name: $repo) {
                issue(number: $number) {
                  comments(last: 50) {
                    nodes {
                      author { login }
                      createdAt
                      reactions(first: 20) {
                        nodes {
                          content
                          user { login }
                          createdAt
                        }
                      }
                    }
                  }
                }
              }
            }
            """
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
                f"number={issue_number}",
            ]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout)
                comments = (
                    data.get("data", {})
                    .get("repository", {})
                    .get("issue", {})
                    .get("comments", {})
                    .get("nodes", [])
                )
                if isinstance(comments, list) and comments:
                    for comment_obj in reversed(comments):
                        if not isinstance(comment_obj, dict):
                            continue
                        author = comment_obj.get("author") or {}
                        login = author.get("login", "") if isinstance(author, dict) else ""
                        if login and not credentials.is_bot_login(login, known_bots=known_bots):
                            created_at = str(comment_obj.get("createdAt", ""))
                            norm_created = created_at.replace("-", "").replace(":", "").replace(" ", "")
                            if not norm_park_time or (norm_created and norm_created > norm_park_time):
                                return True, login

                        reactions = comment_obj.get("reactions") or {}
                        r_nodes = reactions.get("nodes", []) if isinstance(reactions, dict) else []
                        if isinstance(r_nodes, list):
                            for r in reversed(r_nodes):
                                if not isinstance(r, dict):
                                    continue
                                user = r.get("user") or {}
                                u_login = user.get("login", "") if isinstance(user, dict) else ""
                                if u_login and not credentials.is_bot_login(u_login, known_bots=known_bots):
                                    r_created = str(r.get("createdAt", ""))
                                    norm_r_created = r_created.replace("-", "").replace(":", "").replace(" ", "")
                                    if not norm_park_time or (norm_r_created and norm_r_created > norm_park_time):
                                        return True, u_login
        except Exception:
            pass

    try:
        cmd = ["gh", "issue", "view", str(issue_number), "--repo", repo, "--json", "comments"]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(res.stdout)
        comments = data.get("comments", [])
        if isinstance(comments, list) and comments:
            for comment_obj in reversed(comments):
                if not isinstance(comment_obj, dict):
                    continue
                author = comment_obj.get("author") or {}
                login = author.get("login", "") if isinstance(author, dict) else ""
                if login and not credentials.is_bot_login(login, known_bots=known_bots):
                    created_at = str(comment_obj.get("createdAt", "")) if isinstance(comment_obj, dict) else ""
                    norm_created = created_at.replace("-", "").replace(":", "").replace(" ", "")
                    if not norm_park_time or (norm_created and norm_created > norm_park_time):
                        return True, login

                reactions = comment_obj.get("reactions") or {}
                r_nodes = (
                    reactions.get("nodes", [])
                    if isinstance(reactions, dict)
                    else (reactions if isinstance(reactions, list) else [])
                )
                if isinstance(r_nodes, list):
                    for r in reversed(r_nodes):
                        if not isinstance(r, dict):
                            continue
                        user = r.get("user") or {}
                        u_login = user.get("login", "") if isinstance(user, dict) else ""
                        if u_login and not credentials.is_bot_login(u_login, known_bots=known_bots):
                            r_created = str(r.get("createdAt", "")) if isinstance(r, dict) else ""
                            norm_r_created = r_created.replace("-", "").replace(":", "").replace(" ", "")
                            if not norm_park_time or (norm_r_created and norm_r_created > norm_park_time):
                                return True, u_login
    except Exception:
        pass

    try:
        pr_cmd = ["gh", "pr", "view", str(issue_number), "--repo", repo, "--json", "reviews"]
        pr_res = subprocess.run(pr_cmd, capture_output=True, text=True)
        if pr_res.returncode == 0:
            pr_data = json.loads(pr_res.stdout)
            reviews = pr_data.get("reviews", [])
            for rev in reversed(reviews):
                author = rev.get("author", {}) if isinstance(rev, dict) else {}
                login = author.get("login", "") if isinstance(author, dict) else ""
                if credentials.is_bot_login(login, known_bots=known_bots):
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


def get_park_time(issue_number: str | int, state_dir: Path | None) -> str:
    if not state_dir:
        return ""
    last_ts = ""
    for filename, field in (("parked.jsonl", "parked_at"), ("runs.jsonl", "started")):
        log_file = state_dir / filename
        if not log_file.is_file():
            continue
        for line in log_file.read_text(encoding="utf-8", errors="ignore").splitlines():
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

    ts = output.now().strftime("%Y%m%dT%H%M%SZ")
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
    from agent_sessions.driver import agent_session_driver

    iss_num = str(issue_number)
    if outcome in ("parked", "failed", "no-gate"):
        row = {"issue": int(iss_num), "repo": repo, "parked_at": ts, "outcome": outcome, "reason": reason}
        with open(parked_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        agent_session_driver.park_label_add(iss_num, repo)
        if not quiet:
            say(f"  parked -- excluded from future selection unless --retry {iss_num}")
        notify_human(iss_num, f"{outcome}: {reason}", state_dir)
    elif outcome == "gate-human":
        row = {"issue": int(iss_num), "repo": repo, "parked_at": ts, "outcome": outcome, "reason": reason}
        with open(parked_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        agent_session_driver.park_label_add(iss_num, repo)
        say(f"  parked for human review -- excluded from future selection unless --retry {iss_num}")
        notify_human(iss_num, f"gate-human: {reason}", state_dir)
    elif outcome == "incomplete":
        row = {"issue": int(iss_num), "repo": repo, "parked_at": ts, "outcome": outcome, "reason": reason}
        with open(parked_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        say("  incomplete -- leaving unparked so the loop can re-evaluate later")
        agent_session_driver.park_label_remove(iss_num, repo)
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
