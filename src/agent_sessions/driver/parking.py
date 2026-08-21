"""Issue parking, labels, attempt management, and human notification."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from agent_sessions.driver import credentials, output
from agent_sessions.driver.labels import (
    INTERACTIVE_LABEL,
    MERGE_READY_LABEL,
    PARK_LABEL,
)
from agent_sessions.driver.output import say


def run_label_manager(repo: str, *args: str) -> bool:
    """Invoke `label_manager` for one label operation. True if it succeeded.

    This block was written out five times in this module, and **four of the five
    discarded the failure entirely** with a bare `except Exception: pass`. That is why
    two real defects in `label_manager` -- a remove-list that errors when the repo has no
    such label, and a `get_current_labels` that returns `[]` on any exception -- were
    invisible from here for as long as they were: the driver could not have noticed
    either one.

    Returning a bool does not by itself fix that, but it moves the decision to the call
    site, where "ignore this failure" has to be written down rather than inherited from a
    copied `try`. Each caller below now says what it does and why.

    Still a subprocess rather than `label_manager.main(argv)`, which is importable.
    In-process would be tidier and is deliberately not done here: the harness fakes
    observe label operations at the `subprocess.run` boundary (`FakeGitHub.label_calls`),
    so moving the boundary would rewrite how the full-loop suite sees every label write --
    a change to the test architecture riding along inside a deduplication. Worth doing on
    its own, not as a side effect.
    """
    label_mgr = Path(__file__).parent.parent / "scripts" / "label_manager.py"
    cmd = [sys.executable, str(label_mgr)]
    if repo:
        cmd.extend(["--repo", repo])
    cmd.extend(args)
    try:
        subprocess.run(cmd, capture_output=True, check=True)
        return True
    except Exception:
        return False


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


def increment_attempts(issue_number: str | int, repo: str) -> None:
    count = get_attempts(issue_number, repo) + 1
    # Failure ignored: the counter is a loop breaker, and a run that cannot increment it
    # is still better off proceeding than aborting. The cost is a loop that runs one
    # attempt longer than intended, which the operator sees in the ledger.
    run_label_manager(repo, "attempt", "--issue", str(issue_number), "--count", str(count))


def decrement_attempts(issue_number: str | int, repo: str) -> None:
    count = get_attempts(issue_number, repo) - 1
    if count < 0:
        count = 0
    # Same reasoning as the increment: a stuck counter over-parks rather than under-parks.
    if count == 0:
        run_label_manager(repo, "clear-attempts", "--issue", str(issue_number))
    else:
        run_label_manager(repo, "attempt", "--issue", str(issue_number), "--count", str(count))


def park_label_add(issue_number: str | int, repo: str) -> None:
    if not run_label_manager(repo, "park", "--issue", str(issue_number)):
        say(f"  WARNING: could not add the {PARK_LABEL} label to #{issue_number} -- it stays selectable")


def park_label_remove(issue_number: str | int, repo: str) -> None:
    if not run_label_manager(repo, "unpark", "--issue", str(issue_number)):
        say(f"  WARNING: could not remove the {PARK_LABEL} label from #{issue_number} -- it stays parked")


#: The GraphQL query behind the reaction check. A 👍 on a comment does not move the
#: issue's `updatedAt`, so REST alone cannot see an approval that is only a reaction --
#: which is the shape a human approval most often takes.
_COMMENTS_AND_REACTIONS_QUERY = """
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


def _norm_ts(value: object) -> str:
    """GitHub's ISO-8601 flattened to the driver's own `20260810T120000Z` shape.

    Comparison is lexical on the flattened form, which works only because both sides
    are UTC and zero-padded. Written out four times before this; a fifth spelling that
    dropped one of the three characters would have made a comparison silently wrong in
    one branch and right in the others.
    """
    return str(value or "").replace("-", "").replace(":", "").replace(" ", "")


def _human_after_park(login: object, timestamp: object, known_bots: set[str], norm_park_time: str) -> str:
    """The login, if this is a person who acted after the park. Empty string otherwise.

    `is_bot_login` returns True for an empty login, so the truthiness check the comment
    branches wrote out separately is subsumed here rather than dropped -- see
    `tests/driver/test_has_new_human_comment.py`.
    """
    name = login if isinstance(login, str) else ""
    if credentials.is_bot_login(name, known_bots=known_bots):
        return ""
    if norm_park_time:
        norm = _norm_ts(timestamp)
        if not norm or norm <= norm_park_time:
            return ""
    return name


def _reaction_nodes(comment_obj: dict) -> list:
    """The reactions on one comment, under either shape the two sources produce.

    GraphQL returns `{"nodes": [...]}`. The REST branch also accepted a bare list, and
    that tolerance is kept and now applies to both -- a widening of a path GraphQL
    cannot reach, rather than the removal of one that REST might.
    """
    reactions = comment_obj.get("reactions") or {}
    if isinstance(reactions, dict):
        nodes = reactions.get("nodes", [])
    elif isinstance(reactions, list):
        nodes = reactions
    else:
        nodes = []
    return nodes if isinstance(nodes, list) else []


def _scan_comments(comments: object, known_bots: set[str], norm_park_time: str) -> tuple[bool, str]:
    """Newest-first walk of comments and their reactions, for the first human.

    One implementation for both sources. The GraphQL and REST payloads differ in how
    they are *fetched*, not in their shape once fetched, and the previous two copies had
    already begun to drift on the reaction case.
    """
    if not isinstance(comments, list):
        return False, ""
    for comment_obj in reversed(comments):
        if not isinstance(comment_obj, dict):
            continue
        author = comment_obj.get("author") or {}
        login = author.get("login", "") if isinstance(author, dict) else ""
        actor = _human_after_park(login, comment_obj.get("createdAt"), known_bots, norm_park_time)
        if actor:
            return True, actor

        for r in reversed(_reaction_nodes(comment_obj)):
            if not isinstance(r, dict):
                continue
            user = r.get("user") or {}
            u_login = user.get("login", "") if isinstance(user, dict) else ""
            reactor = _human_after_park(u_login, r.get("createdAt"), known_bots, norm_park_time)
            if reactor:
                return True, reactor
    return False, ""


def _graphql_comments(issue_number: str | int, repo: str) -> object:
    """Comment nodes from the GraphQL query, or `[]` if it could not answer."""
    owner, repo_name = repo.split("/", 1)
    cmd = [
        "gh", "api", "graphql",
        "-f", f"query={_COMMENTS_AND_REACTIONS_QUERY}",
        "-F", f"owner={owner}",
        "-F", f"repo={repo_name}",
        "-F", f"number={issue_number}",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 or not res.stdout.strip():
        return []
    data = json.loads(res.stdout)
    return (
        data.get("data", {})
        .get("repository", {})
        .get("issue", {})
        .get("comments", {})
        .get("nodes", [])
    )


def has_new_human_comment(
    issue_number: str | int,
    repo: str,
    bot_logins: frozenset[str] | set[str] | None = None,
    park_time: str = "",
    issue_updated_at: str = "",
) -> tuple[bool, str]:
    """True, and who, if a person has acted on this issue since it was parked.

    Three sources in priority order, each stopping the search once it says yes:
    the GraphQL comment+reaction query, `gh issue view --json comments`, and
    `gh pr view --json reviews`. Every one is wrapped in `except Exception` and falls
    through on failure, because a parked issue nobody can query should stay parked
    rather than crash the pass.

    The three used to be written out in full, twice for the comment scan. The
    per-branch code is now only the *fetch*; the scan is shared.
    """
    norm_park_time = _norm_ts(park_time) if park_time else ""
    known_bots = {name.lower() for name in (bot_logins or credentials.ALWAYS_BOT_LOGINS)}

    if repo and "/" in repo:
        try:
            found, who = _scan_comments(_graphql_comments(issue_number, repo), known_bots, norm_park_time)
            if found:
                return True, who
        except Exception:
            pass

    try:
        cmd = ["gh", "issue", "view", str(issue_number), "--repo", repo, "--json", "comments"]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        found, who = _scan_comments(json.loads(res.stdout).get("comments", []), known_bots, norm_park_time)
        if found:
            return True, who
    except Exception:
        pass

    try:
        pr_cmd = ["gh", "pr", "view", str(issue_number), "--repo", repo, "--json", "reviews"]
        pr_res = subprocess.run(pr_cmd, capture_output=True, text=True)
        if pr_res.returncode == 0:
            for rev in reversed(json.loads(pr_res.stdout).get("reviews", [])):
                author = rev.get("author", {}) if isinstance(rev, dict) else {}
                login = author.get("login", "") if isinstance(author, dict) else ""
                if credentials.is_bot_login(login, known_bots=known_bots):
                    continue
                # Deliberately not `_human_after_park`. That rejects a missing
                # timestamp when a park time is set; this accepts one, and the two
                # have disagreed since before the split. Pinned in
                # `test_a_review_with_no_timestamp_counts_while_a_comment_with_none_does_not`
                # and left for #261 to decide, because reconciling them here would
                # change what the driver does to a real PR inside a deduplication.
                if norm_park_time:
                    norm_created = _norm_ts(rev.get("submittedAt", "") if isinstance(rev, dict) else "")
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
        if not run_label_manager(repo, "merge-ready", "--issue", iss_num):
            say(f"  WARNING: could not add the {MERGE_READY_LABEL} label to #{iss_num} -- "
                f"the verdict is in the PR body and the ledger regardless")
        notify_human(iss_num, f"gate-eligible: {reason}", state_dir)
