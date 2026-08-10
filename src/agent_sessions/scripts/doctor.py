#!/usr/bin/env python3
"""Credential preflight for the board-driver: `make doctor`.

Setting up the first machine-user account failed three times on 2026-08-10, and
every symptom pointed away from the cause. This module encodes what each probe is
actually worth:

- **`GET /repos` reports `"push": true` for a token that cannot write anything.**
  That field is the *collaborator role*, not the token's permission set. Never used
  here as evidence, and there is a test asserting it is not consulted.
- **A write probe against a nonexistent issue returns 404, not 403**, because the
  existence check runs before the permission check. It cannot discriminate. The
  probe used instead is creating a label that already exists: 422 (a no-op) when
  permitted, 403 when not, and nothing is written either way.
- **A fine-grained PAT can only reach repos owned by its resource owner.** A machine
  user that owns no repositories therefore reaches nothing private, whatever its
  "All repositories" setting says and whoever invited it as a collaborator. Public
  repos read fine, which is what made this look like a permissions problem for an
  hour. `_repo_remedy` is where that distinction is written down.

Stdlib only, importable and testable with pytest.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from agent_sessions.driver import credentials  # noqa: E402

#: ProjectsV2 has no REST representation; this is how the driver reads a board too.
_PROJECT_QUERY = "query($o:String!,$n:Int!){user(login:$o){projectV2(number:$n){title}}}"

#: `fail` stops the preflight; `warn` and `skip` do not. A skip is a probe that could
#: not be run honestly -- never rendered as a pass.
SEVERITY = {"pass": " ok ", "fail": "FAIL", "warn": "warn", "skip": "skip"}


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""
    remedy: str = ""


@dataclass
class _Probe:
    """A token, and what we learned about it."""

    label: str
    token: str
    login: str = ""
    error: str = ""
    checks: list = field(default_factory=list)


def _gh(runner, argv: list[str], token: str):
    env = dict(os.environ)
    env["GH_TOKEN"] = token
    env["GITHUB_TOKEN"] = token
    return runner(["gh", *argv], capture_output=True, text=True, env=env)


def _message(res) -> str:
    text = ((getattr(res, "stderr", "") or "") + " " + (getattr(res, "stdout", "") or "")).strip()
    return " ".join(text.split())[:160]


def _repo_remedy(repo: str, login: str) -> str:
    owner = repo.split("/")[0]
    if owner.lower() == login.lower():
        return (
            f"The token's resource owner ({login}) does own {repo}, so this is a repository "
            "selection: edit the PAT and add it under Repository access."
        )
    return (
        f"A fine-grained PAT owned by {login} cannot reach a private repository owned by {owner}, "
        "whatever its Repository access says and however it was invited as a collaborator -- a "
        f"fine-grained token only reaches repos owned by its resource owner, and {login} does not "
        f"own {repo}. There is no setting in the UI for this. Either move the repo into an "
        f"organization that {login} is a *member* of and re-issue the PATs with the organization "
        "as resource owner, or switch to a GitHub App installed on the repo, or make the repo "
        "public. See docs/usage.md."
    )


def _probe_write(runner, token: str, repo: str, label: str):
    """Try to create a label that already exists.

    422 means permitted and nothing happened; 403 means refused. Returns
    ("permitted" | "refused" | "unknown", message).
    """
    res = _gh(runner, ["api", "-X", "POST", f"repos/{repo}/labels", "-f", f"name={label}", "-f", "color=ededed"], token)
    text = _message(res)
    if "403" in text or "not accessible" in text.lower():
        return "refused", text
    if "422" in text or "already_exists" in text or getattr(res, "returncode", 1) == 0:
        return "permitted", text
    return "unknown", text


def _existing_label(runner, token: str, repo: str) -> str:
    res = _gh(runner, ["api", f"repos/{repo}/labels", "--jq", ".[].name"], token)
    if getattr(res, "returncode", 1) != 0:
        return ""
    for line in (getattr(res, "stdout", "") or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def remote_check(remote_url: str) -> Check:
    warning = credentials.remote_warning(remote_url)
    if not warning:
        return Check("origin remote", "pass", "https -- pushes go through the token")
    return Check(
        "origin remote",
        "warn",
        "ssh -- `git push` authenticates with this host's key, not the token",
        "Switch origin to https to bring pushes inside the credential split.",
    )


def check_all(environ: dict, runner, *, repo: str, repo_path: str, board: str = "") -> list[Check]:
    """Every check, in the order an operator hits them."""
    creds = credentials.resolve(environ, runner=runner)

    problem = credentials.config_error(creds)
    if problem:
        # Nothing below can mean anything yet, and probing GitHub with a
        # configuration we have already rejected only produces confusing output.
        return [Check("credentials configured", "fail", problem, "See .env.example.")]

    checks = [Check("credentials configured", "pass", f"expecting account {creds.login}")]

    probes = [_Probe("read", creds.read_token), _Probe("write", creds.write_token)]

    for probe in probes:
        res = _gh(runner, ["api", "user", "--jq", ".login"], probe.token)
        if getattr(res, "returncode", 1) != 0:
            probe.error = _message(res)
            checks.append(
                Check(
                    f"{probe.label} token identity",
                    "fail",
                    probe.error,
                    "The token is invalid, revoked or expired. Re-issue it.",
                )
            )
            continue
        probe.login = (getattr(res, "stdout", "") or "").strip()
        if probe.login.lower() != creds.login.lower():
            checks.append(
                Check(
                    f"{probe.label} token identity",
                    "fail",
                    f"belongs to {probe.login}, not {creds.login}",
                    f"Re-issue the token on {creds.login}, or correct DRIVER_GH_LOGIN.",
                )
            )
            continue
        checks.append(Check(f"{probe.label} token identity", "pass", probe.login))

    usable = [p for p in probes if p.login and not p.error]

    for probe in usable:
        res = _gh(runner, ["api", f"repos/{repo}", "--jq", ".full_name"], probe.token)
        if getattr(res, "returncode", 1) != 0:
            probe.error = _message(res)
            checks.append(
                Check(
                    f"{probe.label} token sees the repo",
                    "fail",
                    f"{repo}: {probe.error}",
                    _repo_remedy(repo, probe.login),
                )
            )
        else:
            checks.append(Check(f"{probe.label} token sees the repo", "pass", repo))

    visible = [p for p in usable if not p.error]
    label = _existing_label(runner, visible[0].token, repo) if visible else ""

    expected = {"read": "refused", "write": "permitted"}
    for probe in visible:
        name = f"{probe.label} token {'cannot write' if probe.label == 'read' else 'can write'}"
        if not label:
            checks.append(
                Check(
                    name,
                    "skip",
                    f"{repo} has no labels, and the only write probe that changes nothing needs one",
                    "Add any label to the repo and re-run, or accept this as unverified.",
                )
            )
            continue
        verdict, text = _probe_write(runner, probe.token, repo, label)
        if verdict == "unknown":
            checks.append(Check(name, "skip", f"could not tell: {text}"))
        elif verdict == expected[probe.label]:
            checks.append(Check(name, "pass", "refused (403)" if verdict == "refused" else "permitted (422 no-op)"))
        elif probe.label == "read":
            checks.append(
                Check(
                    name,
                    "fail",
                    "this token CAN write -- the agent is not contained",
                    "Re-issue it with Contents, Issues and Pull requests at Read only.",
                )
            )
        else:
            checks.append(
                Check(
                    name,
                    "fail",
                    "this token cannot write, so every manifest write will fail",
                    "Re-issue it with Contents, Issues and Pull requests at Read and write. "
                    "Note that `GET /repos` reporting push:true is the collaborator role, not "
                    "this token's permissions.",
                )
            )

    writer = next((p for p in visible if p.label == "write"), None)
    if board and writer:
        # ProjectsV2 is GraphQL-only -- there is no REST endpoint, and probing one
        # returns a 404 that reads like a permissions problem. Ask the way the driver
        # asks.
        owner, _, number = board.partition("/")
        res = _gh(
            runner,
            ["api", "graphql", "-f", f"query={_PROJECT_QUERY}", "-F", f"o={owner}", "-F", f"n={number}"],
            writer.token,
        )
        text = _message(res)
        if getattr(res, "returncode", 1) == 0 and "NOT_FOUND" not in text and '"errors"' not in text:
            checks.append(Check("board readable", "pass", board))
        else:
            checks.append(
                Check(
                    "board readable",
                    "warn",
                    f"{board}: not visible to the write token",
                    f"Selection falls back to labels without it. A classic PAT needs the `project` "
                    f"scope (or `read:project`); a fine-grained PAT cannot reach a project owned by "
                    f"{owner} at all unless {owner} is its resource owner.",
                )
            )

    try:
        res = runner(
            ["git", "-C", str(repo_path), "remote", "get-url", "origin"], capture_output=True, text=True
        )
        if getattr(res, "returncode", 1) == 0:
            checks.append(remote_check(getattr(res, "stdout", "") or ""))
    except Exception:
        pass

    return checks


def exit_code(checks: list[Check]) -> int:
    return 1 if any(c.status == "fail" for c in checks) else 0


def render(checks: list[Check]) -> str:
    width = max((len(c.name) for c in checks), default=0)
    lines = []
    for check in checks:
        lines.append(f"  [{SEVERITY.get(check.status, '????')}]  {check.name.ljust(width)}  {check.detail}")
        if check.remedy and check.status in ("fail", "warn"):
            for para in check.remedy.split("\n"):
                lines.append(f"           -> {para}")
    failed = sum(1 for c in checks if c.status == "fail")
    skipped = sum(1 for c in checks if c.status == "skip")
    lines.append("")
    if failed:
        lines.append(f"doctor: {failed} check(s) failed. The driver will not run correctly.")
    elif skipped:
        lines.append(f"doctor: no failures, {skipped} check(s) could not be run (skip is not a pass).")
    else:
        lines.append("doctor: all checks passed.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the driver's GitHub credentials")
    parser.add_argument("--repo", default=os.environ.get("REPO") or "")
    parser.add_argument("--repo-path", default=os.environ.get("REPO_PATH") or ".")
    parser.add_argument("--board", default=os.environ.get("BOARD") or "")
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args(argv)

    path = Path(args.env_file)
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

    repo = args.repo
    if not repo:
        print("doctor: no --repo (or REPO in .env) to check against", file=sys.stderr)
        return 2

    print(f"doctor: checking credentials against {repo}\n")
    checks = check_all(dict(os.environ), subprocess.run, repo=repo, repo_path=args.repo_path, board=args.board)
    print(render(checks))
    return exit_code(checks)


if __name__ == "__main__":
    sys.exit(main())
