"""PR review thread checks, CI status, write manifest execution, and prompt construction."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import requests

from agent_sessions.driver import agent_runner, output, writes

say = output.say


def get_pr_unresolved_threads_text(repo: str, pr_num: str | int, token: str) -> str:
    parts = repo.split("/")
    if len(parts) != 2:
        return ""
    owner, repo_name = parts
    query = """query($owner:String!,$repo:String!,$pr:Int!){
      repository(owner:$owner,name:$repo){
        pullRequest(number:$pr){
          reviewThreads(first:100){
            nodes{
              isResolved
              comments(first: 50){
                nodes{
                  author { login }
                  body
                  path
                  line
                }
              }
            }
          }
        }
      }
    }"""
    try:
        req_res = requests.post(
            "https://api.github.com/graphql",
            json={
                "query": query,
                "variables": {
                    "owner": owner,
                    "repo": repo_name,
                    "pr": int(pr_num) if str(pr_num).isdigit() else pr_num
                }
            },
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=10,
        )
        req_res.raise_for_status()
        data = req_res.json()
        nodes = (
            data.get("data", {})
            .get("repository", {})
            .get("pullRequest", {})
            .get("reviewThreads", {})
            .get("nodes", [])
        )

        text = ""
        unresolved_threads = [t for t in nodes if isinstance(t, dict) and not t.get("isResolved")]
        for i, thread in enumerate(unresolved_threads[-10:]):
            comments = thread.get("comments", {}).get("nodes", [])
            if comments:
                first_c = comments[0]
                path = first_c.get("path", "unknown")
                line = first_c.get("line", "unknown")
                text += f"Unresolved Review Thread #{i+1} on {path} line {line}:\n"
                for c in comments[-5:]:
                    author = c.get("author", {}).get("login", "unknown") if c.get("author") else "unknown"
                    body = c.get("body", "")
                    if len(body) > 500:
                        body = body[:500] + "... [truncated]"
                    text += f"  - {author}: {body}\n"
                text += "\n"
        return text
    except Exception:
        return ""


def check_pr_unresolved_threads(repo: str, pr_num: str | int, token: str) -> int:
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
        req_res = requests.post(
            "https://api.github.com/graphql",
            json={
                "query": query,
                "variables": {
                    "owner": owner,
                    "repo": repo_name,
                    "pr": int(pr_num) if str(pr_num).isdigit() else pr_num
                }
            },
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=10,
        )
        req_res.raise_for_status()
        data = req_res.json()
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


def perform_writes(writes_file: Path, repo: str, repo_path: Path, rundir: Path, board: str = "") -> dict:
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
    if result["ok"]:
        return ""
    if result["errors"]:
        return f"write manifest rejected ({len(result['errors'])} error(s)): {result['errors'][0]}"
    failed = [r for r in result["results"] if r.get("status") == "failed"]
    if failed:
        return f"write failed at {failed[0].get('kind')}: {(failed[0].get('stderr') or '').strip()[:200]}"
    return "write manifest did not fully apply"


def build_prompt(url_or_number: str | int, phase: str, skill_dir: Path, writes_file: Path | str = "", extra_context: str = "") -> str:
    if str(url_or_number).startswith("http"):
        url = str(url_or_number)
    else:
        url = f"issue #{url_or_number}"

    phase_file = "phases/express.md" if phase == "execute" else f"phases/{phase}.md"
    comments_note = ""
    if phase in ("triage", "refine"):
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
