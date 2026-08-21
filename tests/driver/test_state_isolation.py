"""Control for the autouse state-dir isolation in `tests/conftest.py`.

A fixture that redirects a path is only worth having if something proves the redirect
takes effect through the code under test. Otherwise it is an assertion about the suite
rather than a check on it -- and the defect it was written for went unnoticed for weeks
precisely because nothing looked.

The specific leak: `lifecycle.preflight` derives its state directory from
`$XDG_STATE_HOME` (falling back to `$HOME/.local/state`) plus
`agent-session/<repo-with-dashes>`, so the fixture repo `owner/repo` resolved to a real
directory in the operator's home and accumulated roughly nine hundred run directories.
"""

from __future__ import annotations

import json
from pathlib import Path

from agent_sessions.driver import lifecycle


def _preflight_without_explicit_state_dir(tmp_path: Path, monkeypatch) -> lifecycle.RunContext:
    """Drive preflight the way the leaking tests did: no --state-dir at all."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir(exist_ok=True)
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir(exist_ok=True)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AGENT_GH_READ_TOKEN", "read-token")
    monkeypatch.setenv("DRIVER_GH_WRITE_TOKEN", "write-token")
    monkeypatch.setenv("DRIVER_GH_LOGIN", "agent-session-bot")

    class Result:
        stdout = json.dumps([])
        returncode = 0

    def fake_run(cmd, *args, **kwargs):
        if [str(c) for c in cmd][:3] == ["gh", "api", "user"]:
            class Login:
                stdout = "agent-session-bot\n"
                returncode = 0
            return Login()
        return Result()

    monkeypatch.setattr("subprocess.run", fake_run)

    return lifecycle.preflight([
        "--repo", "owner/repo",
        "--repo-path", str(repo_dir),
        "--skill-dir", str(skill_dir),
        "--dry-run",
    ])


def test_the_default_state_dir_lands_inside_tmp_path(tmp_path: Path, monkeypatch, isolate_state_dir: Path) -> None:
    ctx = _preflight_without_explicit_state_dir(tmp_path, monkeypatch)

    assert ctx.state_dir.is_relative_to(tmp_path), (
        f"state dir escaped tmp_path: {ctx.state_dir}. The autouse isolate_state_dir "
        "fixture in tests/conftest.py is not taking effect, and this suite is writing "
        "into the operator's real home directory."
    )
    assert ctx.state_dir.is_relative_to(isolate_state_dir)
    assert ctx.state_dir.name == "owner-repo", "the per-repo suffix should still be derived"


def test_the_isolation_is_what_moves_it_not_the_repo_name(tmp_path: Path, monkeypatch) -> None:
    """The polarity check: unset the pin and the same call resolves somewhere real.

    Without this, the test above would pass just as well if `preflight` had stopped
    deriving a state dir at all.
    """
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "fake-home"))

    ctx = _preflight_without_explicit_state_dir(tmp_path, monkeypatch)

    assert ctx.state_dir == (tmp_path / "fake-home" / ".local" / "state" / "agent-session" / "owner-repo").resolve(), (
        "with XDG_STATE_HOME unset, preflight should fall back to $HOME/.local/state -- "
        "which is exactly the path that leaked when nothing pinned either variable"
    )
