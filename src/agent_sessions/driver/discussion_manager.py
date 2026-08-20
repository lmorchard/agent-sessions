#!/usr/bin/env python3
"""Discussion manager for agent-sessions Lab Notebook.

Handles category creation, locating or creating daily discussion threads,
and posting start-of-work / finish-run comments via GitHub CLI (`gh`).
"""

from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys
from pathlib import Path


def run_gh(args: list[str]) -> tuple[int, str, str]:
    """Execute gh command and return (returncode, stdout, stderr)."""
    try:
        res = subprocess.run(
            ["gh"] + args,
            capture_output=True,
            text=True,
        )
        return res.returncode, res.stdout, res.stderr
    except Exception as e:
        return 1, "", str(e)


def check_category(repo: str, category_name: str = "Lab Notebook") -> bool:
    """Check if discussion category exists on GitHub repo using GraphQL API."""
    if not repo or "/" not in repo:
        return False
    owner, repo_name = repo.split("/", 1)

    query = """
    query($owner: String!, $repo: String!) {
      repository(owner: $owner, name: $repo) {
        discussionCategories(first: 50) {
          nodes { name }
        }
      }
    }
    """
    rc, stdout, stderr = run_gh(
        [
            "api",
            "graphql",
            "-f",
            f"query={query}",
            "-f",
            f"owner={owner}",
            "-f",
            f"repo={repo_name}",
        ]
    )
    if rc == 0 and stdout.strip():
        try:
            data = json.loads(stdout)
            nodes = data.get("data", {}).get("repository", {}).get("discussionCategories", {}).get("nodes", [])
            names = [n.get("name") for n in nodes if isinstance(n, dict)]
            if category_name in names:
                return True
        except Exception:
            pass

    print(
        f"    WARNING: discussion category '{category_name}' is absent from {repo}. "
        "Discussion categories must be created by hand in GitHub web settings (Settings -> Discussions).",
        file=sys.stderr,
    )
    return False


def ensure_category(repo: str, category_name: str = "Lab Notebook") -> bool:
    """Report whether the discussion category exists. It cannot create one.

    Named `ensure_` from when it tried to, via `createDiscussionCategory` -- which is not
    a mutation in GitHub's GraphQL schema, so it failed on every call until #211. Categories
    are created by hand in repository settings and have no API representation at all.

    The name is kept because the CLI subcommand and `scripts/bootstrap-repo.sh` both use it;
    the docstring calling it a "deprecated alias" was wrong in the other direction, since
    this is the supported entry point. It also took an `emoji` argument that no caller
    passed and nothing read -- a leftover from the creating version.
    """
    return check_category(repo, category_name)


def get_or_create_daily_discussion(repo: str, category_name: str = "Lab Notebook") -> str:
    """Find today's daily discussion thread URL or create it."""
    if not repo:
        return ""

    today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    title = f"Lab Notebook: {today}"
    body = f"Agent run log and narratives for {today}."

    # List discussions in category
    rc, stdout, _ = run_gh(["discussion", "list", "--repo", repo, "--category", category_name, "--json", "title,url"])
    if rc == 0 and stdout.strip():
        try:
            data = json.loads(stdout)
            discussions = data if isinstance(data, list) else data.get("discussions", [])
            for d in discussions:
                if isinstance(d, dict) and d.get("title") == title and d.get("url"):
                    return str(d["url"])
        except Exception:
            pass

    # Create if not found
    rc, stdout, _ = run_gh(["discussion", "create", "--repo", repo, "--category", category_name, "--title", title, "--body", body])
    if rc == 0 and stdout.strip():
        return stdout.strip().splitlines()[-1]

    return ""


def post_start(repo: str, issue: str, phase: str, budget: str, rundir: str) -> bool:
    """Post start-of-work comment to daily discussion."""
    disc_url = get_or_create_daily_discussion(repo)
    if not disc_url:
        return False

    issue_url = f"https://github.com/{repo}/issues/{issue}"
    comment_body = f"""### Starting Work: Issue #{issue} ({phase})
- **Issue**: {issue_url}
- **Phase**: {phase}
- **Budget**: ${budget}
- **Run Dir**: `{rundir}`"""

    rc, _, _ = run_gh(["discussion", "comment", disc_url, "--repo", repo, "--body", comment_body])
    return rc == 0


def post_finish(
    repo: str,
    issue: str,
    phase: str,
    outcome: str,
    cost: str,
    session: str,
    prurl: str,
    reason: str,
    rundir: str,
) -> bool:
    """Post finish-run comment with final.txt narrative to daily discussion."""
    disc_url = get_or_create_daily_discussion(repo)
    if not disc_url:
        return False

    final_text = ""
    if rundir:
        final_file = Path(rundir) / "final.txt"
        if final_file.is_file():
            final_text = final_file.read_text(encoding="utf-8", errors="ignore").strip()

    comment_body = f"""### Run: Issue #{issue} ({phase})
- **Outcome**: {outcome}
- **Cost**: ${cost}
- **Session**: {session or 'none'}
- **PR**: {prurl or 'none'}
- **Reason**: {reason}

#### Agent Narrative (`final.txt`)

{final_text or '(no narrative)'}"""

    rc, _, _ = run_gh(["discussion", "comment", disc_url, "--repo", repo, "--body", comment_body])
    return rc == 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Discussion manager for agent-session Lab Notebook")
    sub = p.add_subparsers(dest="cmd", required=True)

    c_ensure = sub.add_parser("ensure-category")
    c_ensure.add_argument("--repo", required=True)
    c_ensure.add_argument("--category", default="Lab Notebook")

    c_start = sub.add_parser("post-start")
    c_start.add_argument("--repo", required=True)
    c_start.add_argument("--issue", required=True)
    c_start.add_argument("--phase", required=True)
    c_start.add_argument("--budget", default="10")
    c_start.add_argument("--rundir", default="")

    c_finish = sub.add_parser("post-finish")
    c_finish.add_argument("--repo", required=True)
    c_finish.add_argument("--issue", required=True)
    c_finish.add_argument("--phase", required=True)
    c_finish.add_argument("--outcome", required=True)
    c_finish.add_argument("--cost", default="0")
    c_finish.add_argument("--session", default="none")
    c_finish.add_argument("--prurl", default="none")
    c_finish.add_argument("--reason", default="")
    c_finish.add_argument("--rundir", default="")

    args = p.parse_args(argv)

    if args.cmd == "ensure-category":
        ok = ensure_category(args.repo, args.category)
        return 0 if ok else 1
    elif args.cmd == "post-start":
        post_start(args.repo, args.issue, args.phase, args.budget, args.rundir)
        return 0
    elif args.cmd == "post-finish":
        post_finish(
            args.repo,
            args.issue,
            args.phase,
            args.outcome,
            args.cost,
            args.session,
            args.prurl,
            args.reason,
            args.rundir,
        )
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
