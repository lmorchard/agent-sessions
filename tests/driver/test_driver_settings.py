"""The PreToolUse merge-block hook, graded through the code that installs it.

What the previous version of this file got wrong, recorded because the shape recurs.
It had three tests and none of them touched the shipping install path:

- one asserted the string `--settings` appeared in `lifecycle.py`'s *source text* -- a
  presence-grep in Python clothing, which a comment would satisfy. `assertion-lint` does
  not catch that shape: it looks for the shell idiom, not a Python `in` against a file's
  text. (Phrased without quoting that idiom on purpose -- the detector matches the
  literal and cannot tell a mention from an instance, the same reason CLAUDE.md spells a
  count as `N`. This docstring tripped it on the first run.)
- one loaded `driver/settings.json` by literal repo-relative path and checked its shape,
  grading the *asset*;
- one shelled out to `jq` to do the substitution itself and asserted the result, which
  asserts that jq's assignment operator works. The shipping code renders with
  `json.loads`/`json.dumps`.

So all three passed for the whole period during which `lifecycle.preflight` was looking
for the template beside itself in `src/agent_sessions/driver/`, where it had never
lived, silently skipping the render and handing the backend `--settings <missing path>`.

The rule this file now follows: assert on what `preflight` produced, not on what the
template says or on what a reimplementation of the render would say.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agent_sessions.driver import lifecycle


def _preflight(tmp_path: Path, monkeypatch, state_dir: Path) -> lifecycle.RunContext:
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
        "--state-dir", str(state_dir),
        "--dry-run",
    ])


def test_preflight_writes_a_settings_file_that_installs_the_hook(tmp_path: Path, monkeypatch) -> None:
    """The whole point: a real run's state dir carries an installed, runnable hook."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    ctx = _preflight(tmp_path, monkeypatch, state_dir)

    assert ctx.hook_settings_file.is_file(), (
        f"preflight did not write {ctx.hook_settings_file}; the hook is not installed and "
        "--settings points at nothing"
    )

    rendered = json.loads(ctx.hook_settings_file.read_text(encoding="utf-8"))
    hooks = rendered.get("hooks", {}).get("PreToolUse", [])
    assert hooks, "rendered settings define no PreToolUse hook"
    assert hooks[0].get("tool_name") == "Bash", "the PreToolUse hook does not target Bash"

    command = hooks[0].get("command", "")
    assert command, "the rendered hook has no command"
    assert Path(command).is_file(), f"the rendered hook command does not exist: {command}"
    assert os.access(command, os.X_OK), f"the rendered hook command is not executable: {command}"


def test_the_hook_assets_resolve_from_the_module_that_loads_them(tmp_path: Path, monkeypatch) -> None:
    """Guards the specific regression: assets found relative to the loading module.

    Resolving them any other way -- a repo-relative literal, a walk up to a project root
    -- is what broke, because the package moved and the assets did not. Asserting the
    rendered command lands inside the package directory pins the property rather than the
    path, so it survives the next move.
    """
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    ctx = _preflight(tmp_path, monkeypatch, state_dir)
    rendered = json.loads(ctx.hook_settings_file.read_text(encoding="utf-8"))
    command = Path(rendered["hooks"]["PreToolUse"][0]["command"]).resolve()

    package_dir = Path(lifecycle.__file__).resolve().parent
    assert command.is_relative_to(package_dir), (
        f"the hook script resolved to {command}, outside the package at {package_dir}; "
        "an installed wheel would not ship it"
    )


def test_a_missing_template_is_fatal_rather_than_silently_skipped(tmp_path: Path, monkeypatch) -> None:
    """The control, and the reason the bug survived: this used to fail open.

    `if template.is_file():` meant a missing asset produced no hook, no error, and a
    green `make check`. A safety control that skips itself when its asset is absent is
    worse than one that is simply missing, because nothing reports the difference. So
    the absence must stop the run.
    """
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    monkeypatch.setattr(lifecycle, "hook_template_path", lambda: tmp_path / "absent.json")

    with pytest.raises(SystemExit) as exc:
        _preflight(tmp_path, monkeypatch, state_dir)
    assert exc.value.code == 2
