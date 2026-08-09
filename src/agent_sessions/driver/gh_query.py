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
        "number,title,body,headRefName,url,closingIssuesReferences",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        if not result.stdout.strip():
            return []
        data = json.loads(result.stdout)
        return data if isinstance(data, list) else []
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"gh command failed: {e.stderr}") from e


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
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
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
