#!/usr/bin/env python3
"""Discussion manager for agent-sessions Lab Notebook.

Handles category creation, locating or creating daily discussion threads,
and posting start-of-work / finish-run comments via GitHub CLI (`gh`).
Stdlib only, importable and testable.
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


def ensure_category(repo: str, category_name: str = "Lab Notebook", emoji: str = "📓") -> bool:
    """Ensure discussion category exists using GraphQL API."""
    if not repo:
        return False
    # Get repo ID
    rc, stdout, _ = run_gh(["repo", "view", repo, "--json", "id", "--jq", ".id"])
    if rc != 0 or not stdout.strip():
        return False
    repo_id = stdout.strip()

    mutation = """
    mutation($repositoryId: ID!, $name: String!, $emoji: String!) {
      createDiscussionCategory(input: { repositoryId: $repositoryId, name: $name, emoji: $emoji }) {
        discussionCategory { id name }
      }
    }
    """
    rc, stdout, stderr = run_gh(
        [
            "api",
            "graphql",
            "-F",
            f"repositoryId={repo_id}",
            "-f",
            f"query={mutation}",
            "-f",
            f"name={category_name}",
            "-f",
            f"emoji={emoji}",
        ]
    )
    if rc == 0:
        print(f"    Created '{category_name}' discussion category")
        return True
    elif "already exists" in stderr.lower() or "already exists" in stdout.lower():
        print(f"    (Discussion category '{category_name}' already exists)")
        return True
    else:
        print(f"    WARNING: could not create discussion category '{category_name}': {stderr.strip()}", file=sys.stderr)
        return False


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
```
{final_text or '(no narrative)'}
```"""

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
