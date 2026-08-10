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
import shlex
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

#: Read-scoped credential handed to the agent. Safe to keep in `.env`.
READ_TOKEN_VAR = "AGENT_GH_READ_TOKEN"

#: Write-capable credential the driver uses for the manifest. Must NOT live in a
#: file inside the agent's repo path -- see `exposure_error`.
WRITE_TOKEN_VAR = "DRIVER_GH_WRITE_TOKEN"

#: The GitHub login both tokens must resolve to. Required, and checked against a live
#: `gh api user`: without it the driver can only assume whose account it is spending,
#: and "assumed" is exactly what this module exists to stop.
LOGIN_VAR = "DRIVER_GH_LOGIN"

#: Suffix for supplying a token by command rather than by value. `<VAR>_CMD` is run
#: and its stdout used, so the secret can live in a keychain while only the command
#: lives in configuration -- out of shell history, out of plaintext, and durable.
CMD_SUFFIX = "_CMD"

#: Where the operator's own credentials file lives, if they use one. Outside any
#: repo, so it survives a clone and cannot be committed by accident.
CONFIG_FILE_VAR = "DRIVER_CREDENTIALS_FILE"

#: Comma-separated extra logins to treat as machines when deciding whether a comment
#: is a human reply. Configuration rather than a constant, because the writing
#: identity varies by deployment -- see issue #183.
BOT_LOGINS_VAR = "DRIVER_BOT_LOGINS"

#: Always machines, whatever else is configured.
ALWAYS_BOT_LOGINS = frozenset({"github-actions", "github-actions[bot]", "agent-session"})

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
    login: str = ""
    extra_bot_logins: tuple[str, ...] = ()
    #: Problems resolving a `<VAR>_CMD`. Surfaced by `config_error`; never the output.
    errors: tuple[str, ...] = ()

    @property
    def split(self) -> bool:
        """True when the agent's credential is not the one the driver writes with."""
        return bool(self.read_token) and bool(self.write_token) and self.read_token != self.write_token


def _from_command(spec: str, runner) -> tuple[str, str]:
    """Run a `<VAR>_CMD` and return (token, error). Never both."""
    try:
        argv = shlex.split(spec)
    except ValueError as e:
        return "", f"could not parse the command: {e}"
    if not argv:
        return "", "the command is empty"
    try:
        # No shell: a config file is not a code-execution surface, and the commands
        # this exists for (`security`, `op read`, `pass`) need none.
        res = runner(argv, capture_output=True, text=True)
    except Exception as e:  # noqa: BLE001 -- every failure has the same answer here
        return "", f"the command could not be run: {type(e).__name__}"
    if res.returncode != 0:
        return "", f"the command exited {res.returncode}: {(res.stderr or '').strip()[:200]}"
    token = (res.stdout or "").strip()
    if not token:
        return "", "the command printed nothing"
    return token, ""


def resolve(env: dict[str, str] | None = None, runner=None) -> Credentials:
    src = os.environ if env is None else env
    if runner is None:
        runner = subprocess.run

    tokens = {}
    errors = []
    for var in (READ_TOKEN_VAR, WRITE_TOKEN_VAR):
        literal = (src.get(var) or "").strip()
        if literal:
            # An explicit value wins, so one run can override the keychain without
            # anybody editing a config file.
            tokens[var] = literal
            continue
        spec = (src.get(var + CMD_SUFFIX) or "").strip()
        if not spec:
            tokens[var] = ""
            continue
        token, error = _from_command(spec, runner)
        tokens[var] = token
        if error:
            errors.append(f"{var}{CMD_SUFFIX}: {error}")

    extras = [p.strip() for p in (src.get(BOT_LOGINS_VAR) or "").split(",")]
    return Credentials(
        read_token=tokens[READ_TOKEN_VAR],
        write_token=tokens[WRITE_TOKEN_VAR],
        login=(src.get(LOGIN_VAR) or "").strip(),
        extra_bot_logins=tuple(p for p in extras if p),
        errors=tuple(errors),
    )


def user_config_path(env: dict[str, str] | None = None) -> Path:
    """The operator's credentials file: XDG first, then `~/.config`."""
    src = os.environ if env is None else env
    explicit = (src.get(CONFIG_FILE_VAR) or "").strip()
    if explicit:
        return Path(explicit)
    base = (src.get("XDG_CONFIG_HOME") or "").strip() or str(Path(src.get("HOME") or "~") / ".config")
    return Path(base) / "agent-session" / "credentials.env"


def file_mode_error(path: Path | str) -> str:
    """Non-empty when a credentials file is readable by anyone but its owner."""
    p = Path(path)
    try:
        mode = p.stat().st_mode
    except OSError:
        return ""
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        return f"{p} is readable beyond its owner (mode {oct(stat.S_IMODE(mode))}). Run: chmod 0600 {p}"
    return ""


def agent_env(env: dict[str, str], creds: Credentials) -> dict[str, str]:
    """The environment the agent subprocess runs in.

    Fails closed. With no read token configured the child gets no credential at all
    rather than inheriting the host's: under a dedicated agent account there is no
    credential the agent is entitled to except its own. The driver refuses to start
    in that configuration anyway; this is the same policy one layer down, for the
    runner invoked on its own.
    """
    child = dict(env)
    for var in TOKEN_VARS:
        child.pop(var, None)
    if not creds.read_token:
        return child
    for var in AGENT_TOKEN_VARS:
        child[var] = creds.read_token
    return child


def driver_env(env: dict[str, str], creds: Credentials) -> dict[str, str]:
    """The environment the driver's own `gh` and `git` calls run in.

    No write token configured is a configuration the driver refuses (`config_error`),
    so this only strips the read token back out rather than inventing anything.
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


def config_error(creds: Credentials) -> str:
    """Non-empty when the driver must refuse to start.

    There is no degraded mode and no fallback to the host `gh` login. The driver
    runs under its own GitHub account or it does not run -- because a fallback is
    reached by omission (an unexported variable, a cron with a clean environment),
    and the result is a write attributed to a human who did not make it.

    Never includes a token value: this string goes to stderr and into run logs.
    """
    if creds.errors:
        return "could not resolve a credential. " + "; ".join(creds.errors)

    missing = []
    if not creds.read_token:
        missing.append(f"{READ_TOKEN_VAR} (the agent's read-scoped token)")
    if not creds.write_token:
        missing.append(f"{WRITE_TOKEN_VAR} (the driver's write token; there is no fallback to the host gh keyring)")
    if not creds.login:
        missing.append(f"{LOGIN_VAR} (the account both tokens must belong to)")
    if missing:
        return "the driver needs its own GitHub account. Missing: " + "; ".join(missing)

    if creds.read_token == creds.write_token:
        return (
            f"{READ_TOKEN_VAR} and {WRITE_TOKEN_VAR} are identical, so the agent holds the "
            "driver's write-capable credential. Issue two separate tokens on the same account -- "
            "one read-only, one write."
        )
    return ""


def identity_error(creds: Credentials, read_login: str, write_login: str) -> str:
    """Non-empty when a token does not belong to the account it was supposed to.

    `read_login` and `write_login` come from a live `gh api user` under each token.
    An empty one means the lookup failed, which is refused rather than assumed: an
    unverifiable identity is the thing this check exists to rule out.
    """
    expected = creds.login.strip().lower()
    problems = []
    for name, var, actual in (
        ("read", READ_TOKEN_VAR, read_login),
        ("write", WRITE_TOKEN_VAR, write_login),
    ):
        resolved = (actual or "").strip().lower()
        if not resolved:
            problems.append(f"could not resolve the account behind {var}")
        elif resolved != expected:
            problems.append(f"{var} belongs to {actual.strip()!r}, not {creds.login!r}")
    if not problems:
        return ""
    return (
        f"the driver's credentials do not belong to {creds.login!r}. "
        + "; ".join(problems)
        + f". Set {LOGIN_VAR} to the account you meant, or issue the tokens on that account. "
        "The driver will not write to GitHub as somebody it cannot identify."
    )


def bot_logins(creds: Credentials) -> frozenset[str]:
    """Logins whose comments are the machine talking to itself (issue #183).

    The driver's own login has to be in here. A PAT-backed account carries no
    `[bot]` suffix, so nothing about the name says machine -- and without it the
    driver's park explanation reads as a human reply and unparks the issue it just
    parked, resetting the attempt counters on the way.
    """
    logins = {name.lower() for name in ALWAYS_BOT_LOGINS}
    if creds.login:
        logins.add(creds.login.strip().lower())
        logins.add(f"{creds.login.strip().lower()}[bot]")
    logins.update(name.strip().lower() for name in creds.extra_bot_logins if name.strip())
    return frozenset(logins)


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


def exposure_error(
    loaded_keys: set[str], env_file: Path | str, repo_path: Path | str, git_ignored: bool = True
) -> str:
    """Non-empty when a write credential sits in a file that could be committed.

    **Not a containment check.** Decided 2026-08-10: the agent runs as the same uid
    with a shell, so anything the driver can read non-interactively it can read too,
    and a keychain command is one it can simply replay. Where the token lives is a
    hygiene question, not a security one, and this function was briefly written as
    though it were the latter -- refusing any write credential in a file inside the
    agent's tree, which forbade the convenient configuration while buying nothing.

    What survives is the part that was always real: a token in a *tracked* file is
    one `git add -A` from being published, and that is recoverable-from but not
    undoable. So the refusal now fires on exactly that case, and a `.gitignore`d
    `.env` beside the driver is fine.
    """
    if git_ignored:
        return ""
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
        f"{', '.join(exposed)} loaded from {resolved_env}, which is inside "
        f"{resolved_repo} "
        "and is not git-ignored -- one `git add -A` from being published. Add the file "
        "to .gitignore, or move these out of it."
    )
