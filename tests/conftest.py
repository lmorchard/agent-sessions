"""Shared test fixtures.

The autouse fixture below exists because the suites were not hermetic. `lifecycle`
derives its state directory from `$XDG_STATE_HOME`, falling back to `$HOME/.local/state`,
then appends `agent-session/<repo-with-dashes>`. The fixture repo is `owner/repo`, so
every test that drove the driver without passing `--state-dir` wrote to a real path in
the operator's home directory:

    ~/.local/state/agent-session/owner-repo/    ~900 run dirs, ~1700 ledger rows

alongside `inbox.md`, `parked.jsonl` and `workspaces/`. Three consequences, in order of
how much they matter:

1. `make evidence` reads a per-repo `runs.jsonl`. Point it at the live state root -- which
   is the fix for it reading a superseded archive -- and those fabricated rows become
   "evidence" about runs that never happened.
2. Tests could read state a previous run left behind, which is order-dependence that
   nothing would report.
3. Unbounded growth in `$HOME` from running `make check`.

Some suites already redirected individually (`tests/scripts/test_run_progress.py`,
`tests/driver/test_driver.py` via `--state-dir`). Doing it once here means a new test
cannot forget.

Only `XDG_STATE_HOME` is pinned, not `HOME`. `credentials.user_config_path` reads `HOME`
for the operator's real config, and repointing that would change what the credential
tests exercise; the state directory is the thing that leaked.

The fixture's own control lives in `tests/driver/test_state_isolation.py`, which asserts
the driver's default resolution actually lands inside tmp_path. Without that, this file
would be an assertion that something is true rather than a check that it is.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_sessions.driver import locks


@pytest.fixture(autouse=True)
def isolate_state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the driver's default state directory inside this test's tmp_path.

    Autouse and function-scoped: every test gets its own, and a test that wants a
    specific location still overrides it by setting the variable or passing --state-dir.
    """
    state_root = tmp_path / "xdg-state"
    state_root.mkdir(exist_ok=True)
    monkeypatch.setenv("XDG_STATE_HOME", str(state_root))
    return state_root


@pytest.fixture(autouse=True)
def isolate_git_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Cut the operator's git configuration out of every `git` the suites run.

    Six suites build a throwaway repo with `git init`, and only two of them set
    `user.name`/`user.email` on it. Everything else in `git config --global` still
    applied. On a machine with `commit.gpgsign = true` -- an ordinary setting, and the
    default on some managed images -- eight tests fail:

        ERROR tests/driver/test_workspace.py::test_ensure_workspace_creates_worktree...
        ERROR tests/driver/test_workspace_driver_integration.py::...
        subprocess.CalledProcessError

    Reproduced by pointing `GIT_CONFIG_GLOBAL` at a two-line config, which is how that
    count was arrived at rather than estimated. The failure mode is what makes it worth
    a fixture: it arrives as `CalledProcessError` from a `git commit` a *fixture* ran,
    so it reads as the code under test being broken. `commit.gpgsign` and
    `core.hooksPath` are the two that bite; there is no point enumerating them.

    Done at the environment layer, because that is the only one that reaches a `git` the
    *code under test* invokes, and that subprocesses the tests spawn inherit -- including
    the inner `make gate-test` in test_gate_test_wiring.py.

    **Why a stub config file and not `GIT_CONFIG_GLOBAL=/dev/null` plus `GIT_AUTHOR_*`.**
    That was the first attempt, and `test_repo_level_identity_still_wins` rejected it:
    `GIT_AUTHOR_NAME` and `GIT_COMMITTER_NAME` outrank *repo-level* config, so supplying
    the identity through the environment would silently re-author the commits in the two
    fixtures that set their own -- passing suites, wrong authorship, and nothing to say
    so. A global config file sits below repo config in git's precedence, which is the
    ordering the fixtures were written against. It provides an identity for the four
    fixtures that never set one, and yields to the two that do.
    """
    config = tmp_path / "gitconfig-stub"
    config.write_text(
        "[user]\n"
        "\tname = agent-sessions tests\n"
        "\temail = tests@example.invalid\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for var in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
        monkeypatch.delenv(var, raising=False)
    return config


@pytest.fixture(autouse=True)
def clear_git_lock_global() -> Iterator[None]:
    """Clear `locks.CURRENT_LOCK_ISSUE` after every test, so no atexit push escapes.

    The driver registers an atexit hook that pushes a ref deletion for whatever issue
    this global names. In production that is correct: a run holds its lock for the life
    of the process and releases it on exit. The harness, though, calls `main()`
    in-process many times without the interpreter exiting -- so the global stays set,
    and the hook eventually fires at *pytest* shutdown, long after any monkeypatched
    `subprocess.run` has been restored. The push then escapes the test that caused it
    and lands wherever the working tree points. Today that is survivable only because
    the tmp_path repos have no `origin`.

    Note what this fixture deliberately does *not* do. An earlier version asserted the
    global was already `None` on teardown, and it failed immediately on the full-loop
    passes -- correctly, because a pass that acquires a lock and returns really does end
    holding it. That is the driver's designed behaviour, not a defect, so asserting
    against it would have been asserting that the driver releases something it is built
    to keep. The reset is the part that removes the harm; there is nothing here to
    assert that would not either be vacuous or wrong.

    The predecessor of this fixture was `monkeypatch.setattr(agent_session_driver,
    "CURRENT_LOCK_ISSUE", None)` inside the full-loop harness, with a comment claiming
    it prevented exactly this. It could not: that module binds a copy of the value at
    import, while `locks` mutates its own global through `global`.
    """
    yield
    locks.CURRENT_LOCK_ISSUE = None
