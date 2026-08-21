"""Control for the autouse git-config isolation in `tests/conftest.py`.

Same reasoning as `test_state_isolation.py`: a fixture that neutralises an environment
is only worth having if something proves the neutralisation reaches the `git` the code
actually runs. Otherwise it is an assertion about the suite rather than a check on it.

The defect it was written for: six suites build a throwaway repo with `git init`, four
of them set only `user.name`/`user.email`, and every other global setting still applied.
`commit.gpgsign = true` is an ordinary setting -- the default on some managed images --
and with it set, eight tests fail as `subprocess.CalledProcessError` from a `git commit`
inside a fixture. Which reads as the code under test being broken.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True
    ).stdout.strip()


def test_the_operators_global_git_config_is_not_visible(tmp_path: Path):
    """The global config is a stub the fixture wrote, so the operator's keys are gone.

    Asserted by the keys that bite rather than by the file's path, because the fixture
    is allowed to change how it neutralises them and this check should survive that.
    """
    assert Path(os.environ["GIT_CONFIG_GLOBAL"]).name == "gitconfig-stub"
    repo = tmp_path / "probe"
    repo.mkdir()
    _git("init", "-b", "main", cwd=repo)

    # `--global` reads only the global file, which is now /dev/null. `git config --get`
    # exits 1 for a missing key, so a raising call here is the passing case.
    for key in ("commit.gpgsign", "core.hooksPath", "user.signingkey"):
        result = subprocess.run(
            ["git", "config", "--global", "--get", key],
            cwd=str(repo), capture_output=True, text=True,
        )
        assert result.returncode != 0, f"global {key} is still visible: {result.stdout!r}"


def test_a_committing_fixture_works_with_no_repo_level_identity(tmp_path: Path):
    """The environment supplies an identity, so a fixture that forgets one still commits.

    Two of the six `git init` fixtures set `user.name`/`user.email` and the rest relied
    on whatever the machine had. With the operator's global config cut away that
    reliance would break, so the fixture writes a stub global config carrying an
    identity -- and this is the check that it is sufficient.
    """
    repo = tmp_path / "identity"
    repo.mkdir()
    _git("init", "-b", "main", cwd=repo)
    (repo / "f.txt").write_text("x", encoding="utf-8")
    _git("add", "f.txt", cwd=repo)
    _git("commit", "-m", "no repo-level user.email anywhere", cwd=repo)

    assert _git("log", "-1", "--format=%an <%ae>", cwd=repo) == (
        "agent-sessions tests <tests@example.invalid>"
    )


def test_repo_level_identity_still_wins(tmp_path: Path):
    """Control. The suites that *do* set their own identity must keep it.

    `git config user.email` at repo level beats the environment; if that ordering ever
    inverted, six fixtures would silently start committing as someone else and the
    suites asserting on authorship would grade the wrong name.
    """
    repo = tmp_path / "override"
    repo.mkdir()
    _git("init", "-b", "main", cwd=repo)
    _git("config", "user.name", "Test", cwd=repo)
    _git("config", "user.email", "test@example.com", cwd=repo)
    (repo / "f.txt").write_text("x", encoding="utf-8")
    _git("add", "f.txt", cwd=repo)
    _git("commit", "-m", "repo-level identity", cwd=repo)

    assert _git("log", "-1", "--format=%an <%ae>", cwd=repo) == "Test <test@example.com>"
