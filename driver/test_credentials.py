"""Tests for the two-credential split (issue #191).

The property under test is capability, not cooperation: the environment handed to
the agent must not be able to write to GitHub, whatever the agent decides to run.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import credentials  # noqa: E402

READ = "ghp_read_only_token"
WRITE = "ghp_write_capable_token"
BOT = "lmorchard-agent"
HUMAN = "lmorchard"


def split_env(**extra):
    return {credentials.READ_TOKEN_VAR: READ, credentials.WRITE_TOKEN_VAR: WRITE, **extra}


# -- resolve ----------------------------------------------------------------


def test_resolve_reads_both_token_vars():
    creds = credentials.resolve(split_env())
    assert creds.read_token == READ
    assert creds.write_token == WRITE
    assert creds.split is True


def test_resolve_treats_a_missing_read_token_as_not_split():
    creds = credentials.resolve({credentials.WRITE_TOKEN_VAR: WRITE})
    assert creds.split is False


def test_resolve_treats_identical_tokens_as_not_split():
    creds = credentials.resolve({credentials.READ_TOKEN_VAR: READ, credentials.WRITE_TOKEN_VAR: READ})
    assert creds.split is False, "one credential wearing two names is one credential"


def test_a_read_token_with_no_write_token_is_not_split():
    """This used to count as the *best* arrangement, on the reasoning that a write
    token absent from the process cannot leak. That reasoning assumed the host
    keyring was an acceptable write identity. Under a dedicated account it is not:
    the absent token means the driver would write as whoever ran it."""
    creds = credentials.resolve({credentials.READ_TOKEN_VAR: READ})
    assert creds.split is False


# -- the agent's environment ------------------------------------------------


def test_agent_env_installs_the_read_token_for_gh():
    env = credentials.agent_env(split_env(), credentials.resolve(split_env()))
    assert env["GH_TOKEN"] == READ
    assert env["GITHUB_TOKEN"] == READ


def test_agent_env_carries_no_write_capable_credential():
    hostile = split_env(GH_TOKEN=WRITE, GITHUB_TOKEN=WRITE, GH_ENTERPRISE_TOKEN=WRITE)
    env = credentials.agent_env(hostile, credentials.resolve(hostile))
    assert WRITE not in env.values(), f"a write-capable token reached the agent: {env}"
    assert credentials.WRITE_TOKEN_VAR not in env


def test_agent_env_preserves_unrelated_variables():
    env = credentials.agent_env(split_env(PATH="/usr/bin", HOME="/home/x"), credentials.resolve(split_env()))
    assert env["PATH"] == "/usr/bin"
    assert env["HOME"] == "/home/x"


def test_agent_env_is_a_copy():
    base = split_env()
    credentials.agent_env(base, credentials.resolve(base))
    assert base[credentials.WRITE_TOKEN_VAR] == WRITE, "agent_env mutated the caller's environment"


def test_agent_env_with_no_read_token_hands_over_no_credential_at_all():
    """Fail closed. Passing the host's auth through was the pre-bot-account
    behaviour; under a dedicated agent account there is no credential the agent is
    entitled to except its own, so absence means absence, not inheritance."""
    base = {"GH_TOKEN": WRITE, "PATH": "/usr/bin"}
    env = credentials.agent_env(base, credentials.resolve(base))
    assert "GH_TOKEN" not in env
    assert WRITE not in env.values()
    assert env["PATH"] == "/usr/bin"


# -- the driver's own environment -------------------------------------------


def test_driver_env_installs_the_write_token():
    env = credentials.driver_env(split_env(), credentials.resolve(split_env()))
    assert env["GH_TOKEN"] == WRITE
    assert env["GITHUB_TOKEN"] == WRITE


def test_driver_env_invents_nothing_when_no_write_token_is_configured():
    """A configuration `config_error` refuses outright; asserted here so the function
    stays total, and so it cannot quietly promote the read token to the write slot."""
    base = {credentials.READ_TOKEN_VAR: READ, "GH_TOKEN": READ, "PATH": "/usr/bin"}
    env = credentials.driver_env(base, credentials.resolve(base))
    assert "GH_TOKEN" not in env


def test_driver_env_never_carries_the_read_token_as_the_active_credential():
    env = credentials.driver_env(split_env(GH_TOKEN=READ), credentials.resolve(split_env()))
    assert env["GH_TOKEN"] == WRITE


# -- the startup refusal ----------------------------------------------------
#
# There is no degraded mode. The driver runs under its own GitHub account or it does
# not run: a fallback to the host login is how a write ends up attributed to a human
# who did not make it, and a fallback reached by omission is the likeliest kind.


def test_a_full_configuration_is_accepted():
    assert credentials.config_error(credentials.resolve(split_env(**{credentials.LOGIN_VAR: BOT}))) == ""


def test_a_missing_read_token_is_refused():
    msg = credentials.config_error(credentials.resolve({credentials.WRITE_TOKEN_VAR: WRITE, credentials.LOGIN_VAR: BOT}))
    assert msg and credentials.READ_TOKEN_VAR in msg


def test_a_missing_write_token_is_refused_rather_than_inherited():
    msg = credentials.config_error(credentials.resolve({credentials.READ_TOKEN_VAR: READ, credentials.LOGIN_VAR: BOT}))
    assert msg and credentials.WRITE_TOKEN_VAR in msg
    assert "keyring" in msg or "host" in msg


def test_a_missing_expected_login_is_refused():
    """Without it nothing can be verified, and unverified is what we are leaving."""
    msg = credentials.config_error(credentials.resolve(split_env()))
    assert msg and credentials.LOGIN_VAR in msg


def test_one_credential_wearing_two_names_is_refused():
    creds = credentials.resolve({
        credentials.READ_TOKEN_VAR: READ,
        credentials.WRITE_TOKEN_VAR: READ,
        credentials.LOGIN_VAR: BOT,
    })
    msg = credentials.config_error(creds)
    assert msg and "identical" in msg.lower()


def test_no_refusal_leaks_a_token_value():
    for env in (
        {credentials.WRITE_TOKEN_VAR: WRITE},
        {credentials.READ_TOKEN_VAR: READ, credentials.WRITE_TOKEN_VAR: READ, credentials.LOGIN_VAR: BOT},
        {credentials.READ_TOKEN_VAR: READ},
    ):
        msg = credentials.config_error(credentials.resolve(env))
        assert READ not in msg and WRITE not in msg, f"the refusal printed a credential: {msg}"


# -- the identity assertion --------------------------------------------------


def full_creds():
    return credentials.resolve(split_env(**{credentials.LOGIN_VAR: BOT}))


def test_matching_identities_are_accepted():
    assert credentials.identity_error(full_creds(), read_login=BOT, write_login=BOT) == ""


def test_a_write_token_belonging_to_a_human_is_refused():
    msg = credentials.identity_error(full_creds(), read_login=BOT, write_login=HUMAN)
    assert msg
    assert HUMAN in msg and BOT in msg


def test_a_read_token_belonging_to_a_human_is_refused_too():
    """Reads are attributed too, and a personal PAT pasted into the read slot is the
    likeliest way the wrong account ends up in the loop."""
    msg = credentials.identity_error(full_creds(), read_login=HUMAN, write_login=BOT)
    assert msg and HUMAN in msg


def test_an_unresolvable_identity_is_refused_not_assumed():
    assert credentials.identity_error(full_creds(), read_login=BOT, write_login="")
    assert credentials.identity_error(full_creds(), read_login="", write_login=BOT)


def test_identity_comparison_ignores_case():
    assert credentials.identity_error(full_creds(), read_login=BOT.upper(), write_login=BOT) == ""


# -- the bot-login set (issue #183) ------------------------------------------


def test_the_drivers_own_login_counts_as_a_bot():
    """A PAT-backed account has no `[bot]` suffix, so nothing about the login itself
    says machine. Without this the driver's own park comment reads as a human reply
    and unparks the issue it just parked."""
    logins = credentials.bot_logins(full_creds())
    assert BOT in logins


def test_configured_extra_logins_are_included():
    creds = credentials.resolve(split_env(**{
        credentials.LOGIN_VAR: BOT,
        credentials.BOT_LOGINS_VAR: "dependabot[bot], renovate[bot]",
    }))
    logins = credentials.bot_logins(creds)
    assert "dependabot[bot]" in logins and "renovate[bot]" in logins


def test_github_actions_is_always_a_bot():
    logins = credentials.bot_logins(full_creds())
    assert "github-actions" in logins and "github-actions[bot]" in logins


def test_bot_logins_are_lowercased_for_comparison():
    creds = credentials.resolve(split_env(**{credentials.LOGIN_VAR: "LMorchard-Agent"}))
    assert "lmorchard-agent" in credentials.bot_logins(creds)


def test_a_human_login_is_not_in_the_set():
    assert HUMAN not in credentials.bot_logins(full_creds())


# -- the .env exposure check ------------------------------------------------


def test_write_token_in_a_dotenv_the_agent_can_read_is_an_error(tmp_path: Path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    msg = credentials.exposure_error({credentials.WRITE_TOKEN_VAR}, repo_path / ".env", repo_path)
    assert msg, "the write token sat in a file the agent has Read access to and nobody objected"
    assert not msg.startswith("error: "), "die() adds the prefix; two reads as a stutter"
    assert credentials.WRITE_TOKEN_VAR in msg


def test_any_write_capable_variable_in_a_readable_dotenv_is_an_error(tmp_path: Path):
    """The check is about *credentials*, not about one variable name. A `.env`
    carrying `GITHUB_TOKEN` exposes exactly as much as one carrying the driver's own
    variable -- and `GITHUB_TOKEN` is what a pre-#191 `.env` actually holds."""
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    for var in credentials.TOKEN_VARS:
        msg = credentials.exposure_error({var}, repo_path / ".env", repo_path)
        assert msg, f"{var} in a readable .env was not flagged"
        assert var in msg


def test_exposure_error_names_every_offending_variable(tmp_path: Path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    msg = credentials.exposure_error(
        {"GITHUB_TOKEN", credentials.WRITE_TOKEN_VAR, credentials.READ_TOKEN_VAR, "REPO"},
        repo_path / ".env",
        repo_path,
    )
    assert "GITHUB_TOKEN" in msg and credentials.WRITE_TOKEN_VAR in msg
    assert "REPO," not in msg and credentials.READ_TOKEN_VAR not in msg.split("keep only")[0]


def test_read_token_in_a_dotenv_the_agent_can_read_is_fine(tmp_path: Path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    assert credentials.exposure_error({credentials.READ_TOKEN_VAR}, repo_path / ".env", repo_path) == ""


def test_write_token_in_a_dotenv_outside_the_repo_is_fine(tmp_path: Path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    elsewhere = tmp_path / "driver-home" / ".env"
    assert credentials.exposure_error({credentials.WRITE_TOKEN_VAR}, elsewhere, repo_path) == ""


def test_exposure_error_does_not_print_the_token(tmp_path: Path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    msg = credentials.exposure_error({credentials.WRITE_TOKEN_VAR}, repo_path / ".env", repo_path)
    assert WRITE not in msg


# -- the git remote gap ------------------------------------------------------


def test_an_ssh_remote_is_flagged_as_outside_the_split():
    """`GH_TOKEN` reaches git only through the gh credential helper, which only fires
    for HTTPS. On SSH the host key pushes and the read token is irrelevant."""
    msg = credentials.remote_warning("git@github.com:owner/repo.git\n")
    assert msg and "git push" in msg


def test_an_https_remote_is_covered():
    assert credentials.remote_warning("https://github.com/owner/repo.git\n") == ""


def test_an_unknown_remote_is_not_claimed_to_be_covered():
    assert credentials.remote_warning("ssh://git@github.com/owner/repo.git") != ""


def test_no_remote_is_silent():
    assert credentials.remote_warning("") == ""
