#!/usr/bin/env python3
"""The two-credential split: a read-scoped token for the agent, write for the driver.

Tool allowlists cannot contain an agent that has a shell, and a cooperative agent
looks exactly like a contained one. Credentials can: an agent holding a read-only
token cannot merge, cannot rewrite an issue body and cannot force-push, whatever
it decides to run. This module owns the two tokens and the two environments built
from them.

Stdlib only, importable and testable with pytest.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

#: Read-scoped credential handed to the agent. Safe to keep in `.env`.
READ_TOKEN_VAR = "AGENT_GH_READ_TOKEN"

#: Write-capable credential the driver uses for the manifest. Must NOT live in a
#: file inside the agent's repo path -- see `exposure_error`.
WRITE_TOKEN_VAR = "DRIVER_GH_WRITE_TOKEN"

#: Every variable `gh` and the git credential helper will accept as a credential.
#: All of them are removed from the child environment before the read token goes in,
#: so an inherited write token cannot survive by wearing a different name.
TOKEN_VARS = (
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "GH_ENTERPRISE_TOKEN",
    "GITHUB_ENTERPRISE_TOKEN",
    WRITE_TOKEN_VAR,
)

#: Variables the read token is installed into for the child.
AGENT_TOKEN_VARS = ("GH_TOKEN", "GITHUB_TOKEN")


@dataclass(frozen=True)
class Credentials:
    read_token: str = ""
    write_token: str = ""

    @property
    def split(self) -> bool:
        """True when the agent gets a credential the driver's writes do not use.

        A read token with no write token counts: the driver falls back to the host
        keyring, so there is no write token in the process to leak at all.
        """
        return bool(self.read_token) and self.read_token != self.write_token


def resolve(env: dict[str, str] | None = None) -> Credentials:
    src = os.environ if env is None else env
    return Credentials(
        read_token=(src.get(READ_TOKEN_VAR) or "").strip(),
        write_token=(src.get(WRITE_TOKEN_VAR) or "").strip(),
    )


def agent_env(env: dict[str, str], creds: Credentials) -> dict[str, str]:
    """The environment the agent subprocess runs in.

    With no read token configured there is nothing to install, and scrubbing
    `GH_TOKEN` would break the inherited host auth the loop still depends on. That
    case is the degraded one `warning` shouts about; it is not silently maimed here.
    """
    child = dict(env)
    if not creds.read_token:
        return child
    for var in TOKEN_VARS:
        child.pop(var, None)
    for var in AGENT_TOKEN_VARS:
        child[var] = creds.read_token
    return child


def driver_env(env: dict[str, str], creds: Credentials) -> dict[str, str]:
    """The environment the driver's own `gh` and `git` calls run in.

    No write token configured means the host keyring is the credential, so nothing
    is invented here.
    """
    parent = dict(env)
    if not creds.write_token:
        for var in AGENT_TOKEN_VARS:
            if parent.get(var) and parent[var] == creds.read_token:
                # The read token must never be the driver's active credential.
                parent.pop(var, None)
        return parent
    for var in AGENT_TOKEN_VARS:
        parent[var] = creds.write_token
    return parent


def apply_driver_env(creds: Credentials, env: dict[str, str] | None = None) -> None:
    """Install the write credential into this process, so every `gh` and `git`
    subprocess the driver spawns inherits it. The agent's child is built by
    `agent_env`, which strips it back out again."""
    target = os.environ if env is None else env
    desired = driver_env(dict(target), creds)
    for var in AGENT_TOKEN_VARS:
        if var in desired:
            target[var] = desired[var]
        else:
            target.pop(var, None)


def warning(creds: Credentials) -> str:
    """The loud startup line for a run that is not actually contained.

    Never includes a token value: this string goes to stdout and into run logs.
    """
    if creds.split:
        return ""
    if creds.read_token and creds.read_token == creds.write_token:
        return (
            f"WARNING: {READ_TOKEN_VAR} and {WRITE_TOKEN_VAR} are identical, so the agent "
            "holds the driver's write-capable credential. Containment is prompt wording only."
        )
    return (
        f"WARNING: no {READ_TOKEN_VAR} is configured, so the agent inherits this host's "
        "write-capable GitHub authentication. It can comment, label, push and merge "
        "regardless of what the prompt or the PreToolUse hook say. Set "
        f"{READ_TOKEN_VAR} to a read-scoped token to contain it."
    )


def remote_warning(remote_url: str) -> str:
    """Non-empty when `git push` will not go through the token at all.

    `GH_TOKEN` only reaches git via the `gh` credential helper, which only fires for
    HTTPS remotes. On an SSH remote the host's key authenticates the push, the read
    token is irrelevant, and the agent can push branches directly -- so the split
    contains the GitHub API but not git. Say so rather than imply otherwise.
    """
    url = (remote_url or "").strip()
    if not url or url.startswith("https://"):
        return ""
    return (
        f"WARNING: origin is {url}, an SSH remote. The credential split does not cover "
        "`git push`: SSH authenticates with this host's key, not with the read token, so the "
        "agent can push branches even though it cannot reach the GitHub API. Use an HTTPS "
        "remote to contain pushes too."
    )


def exposure_error(loaded_keys: set[str], env_file: Path | str, repo_path: Path | str) -> str:
    """Non-empty when the write token was read from a file the agent can read.

    The whole split collapses if the write credential sits in a `.env` inside the
    tree the agent holds `Read` and `Bash` over -- it just opens the file. Fail
    closed rather than ship theatre.
    """
    exposed = sorted(loaded_keys & set(TOKEN_VARS))
    if not exposed:
        return ""
    try:
        resolved_env = Path(env_file).resolve()
        resolved_repo = Path(repo_path).resolve()
        resolved_env.relative_to(resolved_repo)
    except (ValueError, OSError):
        return ""
    return (
        f"error: {', '.join(exposed)} loaded from {resolved_env}, which is inside the "
        f"agent's repo path ({resolved_repo}). The agent can read that file, so the "
        "write credential is not contained. Export these in the driver's environment "
        f"instead, and keep only {READ_TOKEN_VAR} in .env."
    )
