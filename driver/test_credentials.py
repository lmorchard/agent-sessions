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


def test_a_read_token_with_no_write_token_is_split():
    """The recommended config: read token in .env, write side left to the host keyring.

    There is no write token to leak, which is the strongest arrangement, so this
    must not be reported as degraded.
    """
    creds = credentials.resolve({credentials.READ_TOKEN_VAR: READ})
    assert creds.split is True


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


def test_degraded_agent_env_is_left_exactly_as_today():
    """With no read token there is nothing to install, and scrubbing GH_TOKEN would
    break the inherited host auth the driver still runs on. Warn, do not maim."""
    base = {"GH_TOKEN": WRITE, "PATH": "/usr/bin"}
    env = credentials.agent_env(base, credentials.resolve(base))
    assert env == base


# -- the driver's own environment -------------------------------------------


def test_driver_env_installs_the_write_token():
    env = credentials.driver_env(split_env(), credentials.resolve(split_env()))
    assert env["GH_TOKEN"] == WRITE
    assert env["GITHUB_TOKEN"] == WRITE


def test_driver_env_leaves_host_auth_alone_when_no_write_token_is_configured():
    base = {credentials.READ_TOKEN_VAR: READ, "PATH": "/usr/bin"}
    env = credentials.driver_env(base, credentials.resolve(base))
    assert "GH_TOKEN" not in env, "invented a credential where the host keyring was the answer"


def test_driver_env_never_carries_the_read_token_as_the_active_credential():
    env = credentials.driver_env(split_env(GH_TOKEN=READ), credentials.resolve(split_env()))
    assert env["GH_TOKEN"] == WRITE


# -- the startup warning ----------------------------------------------------


def test_no_warning_when_the_credentials_are_split():
    assert credentials.warning(credentials.resolve(split_env())) == ""


def test_warning_names_the_variable_to_set_when_no_read_token_exists():
    msg = credentials.warning(credentials.resolve({credentials.WRITE_TOKEN_VAR: WRITE}))
    assert msg, "the driver handed the agent write access and said nothing"
    assert credentials.READ_TOKEN_VAR in msg


def test_warning_when_one_credential_wears_two_names():
    msg = credentials.warning(credentials.resolve({credentials.READ_TOKEN_VAR: READ, credentials.WRITE_TOKEN_VAR: READ}))
    assert msg
    assert "identical" in msg.lower()


def test_no_warning_leaks_a_token_value():
    for env in ({credentials.WRITE_TOKEN_VAR: WRITE}, {credentials.READ_TOKEN_VAR: READ, credentials.WRITE_TOKEN_VAR: READ}):
        msg = credentials.warning(credentials.resolve(env))
        assert READ not in msg and WRITE not in msg, f"the warning printed a credential: {msg}"


# -- the .env exposure check ------------------------------------------------


def test_write_token_in_a_dotenv_the_agent_can_read_is_an_error(tmp_path: Path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    msg = credentials.exposure_error({credentials.WRITE_TOKEN_VAR}, repo_path / ".env", repo_path)
    assert msg, "the write token sat in a file the agent has Read access to and nobody objected"
    assert credentials.WRITE_TOKEN_VAR in msg


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
