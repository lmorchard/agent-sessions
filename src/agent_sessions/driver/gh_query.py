#!/usr/bin/env python3
"""GitHub CLI queries for the agent-session driver.

Extracted from bash to provide type safety and distinguish a failed query
from an empty result (a null must never render as a positive).
"""

import argparse
import json
import re
import subprocess
import sys


def check_rate_limit(env: dict | None = None) -> tuple[int, int, int]:
    """Check remaining GraphQL rate limit points.
    Returns (remaining, limit, reset_epoch).
    """
    try:
        cmd = ["gh", "api", "rate_limit"]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True, env=env)
        data = json.loads(res.stdout)
        graphql = data.get("resources", {}).get("graphql", {})
        remaining = int(graphql.get("remaining", 5000))
        limit = int(graphql.get("limit", 5000))
        reset = int(graphql.get("reset", 0))
        return remaining, limit, reset
    except Exception:
        return 5000, 5000, 0


def fetch_prs(repo: str, state: str = "open") -> list[dict]:
    """Fetch PRs from GitHub for the given repo."""
    cmd = [
        "gh",
        "pr",
        "list",
        "--repo",
        repo,
        "--state",
        state,
        "--limit",
        "200",
        "--json",
        "number,title,body,headRefName,url,closingIssuesReferences,mergeStateStatus,mergeable,reviewDecision,reviewRequests,reviews,statusCheckRollup",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        if not result.stdout.strip():
            return []
        data = json.loads(result.stdout)
        return data if isinstance(data, list) else []
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"gh command failed: {e.stderr}") from e


def fetch_unresolved_threads_for_all_prs(repo: str) -> dict[str, int]:
    """Fetch counts of unresolved review threads for all open PRs in a single GraphQL query.
    Returns mapping of pr_number (str) -> unresolved_thread_count (int).
    """
    if not repo or "/" not in repo:
        return {}
    owner, repo_name = repo.split("/", 1)
    query = """
    query($owner: String!, $repo: String!) {
      repository(owner: $owner, name: $repo) {
        pullRequests(first: 100, states: OPEN) {
          nodes {
            number
            reviewThreads(first: 50) {
              nodes { isResolved }
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
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(res.stdout)
        prs = (
            data.get("data", {})
            .get("repository", {})
            .get("pullRequests", {})
            .get("nodes", [])
        )
        counts = {}
        for pr in prs:
            if not isinstance(pr, dict):
                continue
            pr_num = str(pr.get("number"))
            threads = pr.get("reviewThreads", {}).get("nodes", [])
            unresolved = sum(1 for t in threads if isinstance(t, dict) and not t.get("isResolved"))
            counts[pr_num] = unresolved
        return counts
    except Exception:
        return {}


def parse_pr_ci_status(pr: dict) -> tuple[int, int]:
    """Parse (failed_count, pending_count) directly from PR dict statusCheckRollup."""
    rollup = pr.get("statusCheckRollup") or []
    if not isinstance(rollup, list):
        return 0, 0
    failed = 0
    pending = 0
    for c in rollup:
        if not isinstance(c, dict):
            continue
        typename = c.get("__typename")
        if typename == "CheckRun":
            st = c.get("status")
            conc = c.get("conclusion")
            if st in ("IN_PROGRESS", "QUEUED", "REQUESTED", "WAITING", "PENDING"):
                pending += 1
            elif conc not in ("SUCCESS", "SKIPPED", "NEUTRAL", "PASS"):
                failed += 1
        elif typename == "StatusContext":
            state = c.get("state")
            if state in ("PENDING", "EXPECTED"):
                pending += 1
            elif state not in ("SUCCESS",):
                failed += 1
    return failed, pending


def parse_pr_reviews(pr: dict) -> tuple[int, int, str]:
    """Parse (requested_count, reviewed_count, reviewDecision) directly from PR dict."""
    req_list = pr.get("reviewRequests") or []
    rev_list = pr.get("reviews") or []
    decision = pr.get("reviewDecision") or ""
    req = len(req_list) if isinstance(req_list, list) else 0
    rev = len(rev_list) if isinstance(rev_list, list) else 0
    return req, rev, str(decision)


def fetch_open_prs(repo: str) -> list[dict]:
    """Fetch open PRs from GitHub for the given repo."""
    return fetch_prs(repo, state="open")


def pr_blocking_issue(issue_number: str, open_prs: list[dict]) -> str | None:
    """Find a PR blocking the issue (strict matcher for selection)."""
    for pr in open_prs:
        refs = pr.get("closingIssuesReferences")
        if refs is None:
            refs = []
        for ref in refs:
            if str(ref.get("number")) == str(issue_number):
                return f"{pr.get('number')}\t{pr.get('url')}"
    return None


def pr_for_issue(issue_number: str, open_prs: list[dict]) -> str | None:
    """Find a PR for the issue (loose matcher for discovery)."""
    pattern_with_hash = re.compile(rf"(^|[^0-9])#{issue_number}([^0-9]|$)")
    pattern_no_hash = re.compile(rf"(^|[^0-9]){issue_number}([^0-9]|$)")

    for pr in open_prs:
        body = pr.get("body") or ""
        title = pr.get("title") or ""
        head = pr.get("headRefName") or ""

        if (
            pattern_with_hash.search(body)
            or pattern_with_hash.search(title)
            or pattern_no_hash.search(head)
        ):
            return f"{pr.get('number')}\t{pr.get('url')}"
    return None


def _main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch-open-prs", help="Fetch PRs for a repo")
    f.add_argument("--repo", required=True)
    f.add_argument("--state", default="open", help="PR state (open, closed, merged, all)")

    pb = sub.add_parser("pr-blocking-issue", help="Strict match for selection")
    pb.add_argument("issue")

    pf = sub.add_parser("pr-for-issue", help="Loose match for discovery")
    pf.add_argument("issue")

    args = p.parse_args(argv)

    if args.cmd == "fetch-open-prs":
        try:
            prs = fetch_prs(args.repo, state=args.state)
            json.dump(prs, sys.stdout)
            sys.stdout.write("\n")
        except Exception as e:
            sys.stderr.write(f"{e}\n")
            return 1
    elif args.cmd == "pr-blocking-issue":
        prs = json.load(sys.stdin)
        res = pr_blocking_issue(args.issue, prs)
        if res:
            sys.stdout.write(res + "\n")
    elif args.cmd == "pr-for-issue":
        prs = json.load(sys.stdin)
        res = pr_for_issue(args.issue, prs)
        if res:
            sys.stdout.write(res + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(_main())
