"""Frozen acceptance checks for issue #50 — `make gate-test` must be a glob, not a census.

`gate-test` names its pytest arguments as a hand-maintained list of literal file
paths. `scripts/test_assertion_lint.py` was written, passed, and was never added to
that list, so it has never run under `make check`. A census that has to be edited
every time a test file is added will drift, silently, in exactly that direction.

These two checks grade the *outcome* — every file matching `driver/test_*.py` and
`scripts/test_*.py` runs under `make gate-test`, and a newly added one runs with no
`Makefile` edit — not any particular way of getting there.

Three things about how they are written, each of which this repo has been burned by:

**They derive, they never restate.** The recipe's arguments are extracted from the
`Makefile` at run time (`make -n gate-test`) and the recipe is *executed verbatim*.
A check that hardcoded the argument list would be asserting its own copy of the
recipe — `findings.md` defect class 5, "a spelling check, not a test". It is that
derivation that makes C1 non-vacuous even though its two sides look alike: the left
side is whatever the `Makefile` actually says today.

**They compare live measurements, never a literal total.** Any pinned count goes
stale the next time a test file is added, which is the very failure being fixed.

**This module lives in `scripts/` and so matches the glob it is asserting on.** C2
invokes `make gate-test` for real, and once the fix lands that inner run re-collects
this module — so C2 would re-enter itself without bound. `INNER_RUN_ENV` is set only
on that inner invocation and skips C2 there. It deliberately does **not** skip C1: C1
only *collects*, and collection imports a module without executing any test body, so
it cannot recurse. An outer `uv run pytest driver/test_*.py scripts/test_*.py -q`
must therefore report **0 skipped** — that is the signal the guard is not
over-applied.
"""

import os
import re
import secrets
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Set only on the `make gate-test` subprocess C2 spawns. Nothing else in the repo
#: sets or reads it; if you see it in an environment, a C2 run is in progress.
INNER_RUN_ENV = "AGENT_SESSIONS_GATE_TEST_WIRING_INNER_RUN"

#: The globs the criteria are written against.
TEST_FILE_GLOBS = ("driver/test_*.py", "scripts/test_*.py")

_NODE_ID = re.compile(r"^(?P<path>\S+\.py)::(?P<rest>\S.*)$")
_MAKE_NOISE = re.compile(r"^make(\[\d+\])?:")

_INNER = pytest.mark.skipif(
    os.environ.get(INNER_RUN_ENV) == "1",
    reason=(
        f"{INNER_RUN_ENV} is set: this is the inner `make gate-test` spawned by C2. "
        "Running C2 here would re-enter itself without bound."
    ),
)


# --- helpers ---------------------------------------------------------------


def _base_env() -> dict:
    """A copy of the environment with `make`'s recursion state removed.

    If the outer pytest was itself started by `make check`, `MAKEFLAGS` is set and
    every nested `make` announces itself with `make[1]:` lines and complains about
    an unavailable jobserver. Dropping it keeps the recipe we parse clean; the
    line filter in `_gate_test_recipe` covers the case anyway.
    """
    env = os.environ.copy()
    env.pop("MAKEFLAGS", None)
    env.pop("MFLAGS", None)
    env.pop("MAKELEVEL", None)
    return env


def _collect_env() -> dict:
    """Environment that turns any pytest run into a collection-only run.

    `PYTEST_ADDOPTS` is *appended to*, never overwritten — a developer or CI with it
    already set must not make this check fail for reasons unrelated to the wiring.
    (Note `pyproject.toml` also contributes `addopts = "-q"`.)
    """
    env = _base_env()
    existing = env.get("PYTEST_ADDOPTS", "")
    env["PYTEST_ADDOPTS"] = f"{existing} --collect-only".strip()
    return env


def _gate_test_recipe() -> str:
    """The shell text `make gate-test` would run, read out of the Makefile itself."""
    proc = subprocess.run(
        ["make", "-n", "--no-print-directory", "gate-test"],
        cwd=REPO_ROOT,
        env=_base_env(),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        pytest.fail(
            "could not read the gate-test recipe: `make -n gate-test` exited "
            f"{proc.returncode}\n--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
        )
    lines = [
        line
        for line in proc.stdout.splitlines()
        if line.strip() and not _MAKE_NOISE.match(line.strip())
    ]
    if lines and lines[0].lstrip().startswith("@"):
        lines[0] = lines[0].lstrip()[1:]
    recipe = "\n".join(lines)
    if not recipe.strip():
        pytest.fail(
            "parsed an empty gate-test recipe out of `make -n gate-test`; refusing to "
            f"compare empty sets.\n--- raw stdout ---\n{proc.stdout!r}"
        )
    return recipe


def _run_collection(argv: list[str], label: str) -> set[str]:
    """Run a collection-only pytest and return its node ids.

    Exit 5 is pytest's "collected nothing", which must read as a failed check and
    never as a pass. Any other non-zero status means collection itself broke.
    """
    proc = subprocess.run(
        argv, cwd=REPO_ROOT, env=_collect_env(), capture_output=True, text=True
    )
    if proc.returncode == 5:
        pytest.fail(
            f"{label} collected NO tests (pytest exit 5). "
            f"'no tests ran' is a failed check, not a pass.\n"
            f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
        )
    if proc.returncode != 0:
        pytest.fail(
            f"{label} failed to collect (exit {proc.returncode}).\n"
            f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
        )
    ids = _node_ids(proc.stdout)
    if not ids:
        pytest.fail(
            f"{label} exited 0 but produced no parsable node ids.\n"
            f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
        )
    return ids


def _node_ids(stdout: str) -> set[str]:
    """Node ids out of `--collect-only -q` output, normalised to repo-relative paths.

    The two sides may name their files differently (relative, absolute, or not at
    all if the recipe leans on `testpaths`). Normalising the path half means the
    comparison is about *which tests run*, not about how they were spelled.
    """
    ids = set()
    for line in stdout.splitlines():
        m = _NODE_ID.match(line.strip())
        if not m:
            continue
        path = Path(m.group("path"))
        if path.is_absolute():
            try:
                path = path.relative_to(REPO_ROOT)
            except ValueError:
                pass
        ids.add(f"{path.as_posix()}::{m.group('rest')}")
    return ids


def _glob_matched_files() -> list[str]:
    files = []
    for glob in TEST_FILE_GLOBS:
        parent, pattern = glob.split("/", 1)
        files.extend(sorted(p for p in (REPO_ROOT / parent).glob(pattern)))
    return [str(p.relative_to(REPO_ROOT)) for p in files]


def _make_gate_test() -> subprocess.CompletedProcess:
    """Invoke `make gate-test` for real, flagged so this module skips C2 inside it."""
    env = _base_env()
    env[INNER_RUN_ENV] = "1"
    return subprocess.run(
        ["make", "--no-print-directory", "gate-test"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


#: A test file that is guaranteed to fail if — and only if — it gets collected.
PROBE_SOURCE = '''"""TRANSIENT probe file written by scripts/test_gate_test_wiring.py (issue #50, C2).

It is deleted in a `finally`. If you are reading this in a committed tree, a run was
killed mid-test: delete it. It is not part of the suite.
"""


def test_gate_test_wiring_probe_is_expected_to_fail():
    raise AssertionError(
        "gate-test wiring probe: collected as intended, and failing on purpose"
    )
'''


# --- C1 --------------------------------------------------------------------


def test_gate_test_collects_every_glob_matched_test_file():
    """C1. `make gate-test` collects every `driver/test_*.py` and `scripts/test_*.py`.

    Both sides are measured live in this run: the left from the recipe the Makefile
    actually holds right now, the right from the globs the criterion names. No total
    is pinned, so adding a test file cannot make this go stale.
    """
    recipe = _gate_test_recipe()
    recipe_ids = _run_collection(
        ["bash", "-e", "-o", "pipefail", "-c", recipe],
        f"the gate-test recipe ({recipe!r})",
    )

    glob_files = _glob_matched_files()
    assert glob_files, (
        f"no files matched {TEST_FILE_GLOBS} under {REPO_ROOT}; the check cannot "
        "compare against an empty reference"
    )
    glob_ids = _run_collection(
        ["uv", "run", "--quiet", "pytest", *glob_files],
        f"the globs {TEST_FILE_GLOBS}",
    )

    missing = sorted(glob_ids - recipe_ids)
    extra = sorted(recipe_ids - glob_ids)
    assert not missing and not extra, (
        "`make gate-test` does not run the same tests as "
        f"{' '.join(TEST_FILE_GLOBS)}.\n"
        f"recipe under test: {recipe!r}\n"
        f"collected by recipe: {len(recipe_ids)}   collected by globs: {len(glob_ids)}\n"
        f"MISSING from gate-test ({len(missing)}): {missing}\n"
        f"EXTRA in gate-test ({len(extra)}): {extra}"
    )


# --- C2 --------------------------------------------------------------------


@_INNER
def test_new_test_file_runs_under_gate_test_with_no_makefile_edit():
    """C2. A new `scripts/test_*.py` runs under `make gate-test` with no Makefile edit.

    The probe is process-unique: a fixed name would let two concurrent runs in this
    working tree race, one deleting the other's probe between the two arms. It is
    removed in a `finally`, with `missing_ok=True` so the mid-test removal and the
    teardown removal cannot collide.
    """
    makefile = REPO_ROOT / "Makefile"
    makefile_before = makefile.read_bytes()

    probe = (
        REPO_ROOT
        / "scripts"
        / f"test_zz_gate_wiring_probe_{os.getpid()}_{secrets.token_hex(4)}.py"
    )
    try:
        probe.write_text(PROBE_SOURCE)

        with_probe = _make_gate_test()
        combined = with_probe.stdout + with_probe.stderr
        assert with_probe.returncode != 0, (
            f"`make gate-test` exited 0 with a failing test file at {probe.name} in "
            "place, so it never collected it. Adding a test file must not require a "
            f"Makefile edit.\n--- output ---\n{combined}"
        )
        assert probe.name in combined, (
            f"`make gate-test` exited {with_probe.returncode}, but {probe.name} is "
            "nowhere in its output — so the non-zero status came from something other "
            "than the new test file, and this proves nothing about the wiring.\n"
            f"--- output ---\n{combined}"
        )

        probe.unlink(missing_ok=True)

        without_probe = _make_gate_test()
        assert without_probe.returncode == 0, (
            "`make gate-test` failed with the probe removed, so the non-zero result "
            "above cannot be attributed to the probe.\n"
            f"--- stdout ---\n{without_probe.stdout}\n"
            f"--- stderr ---\n{without_probe.stderr}"
        )
    finally:
        probe.unlink(missing_ok=True)

    assert makefile.read_bytes() == makefile_before, (
        "the Makefile changed during this test; C2 requires the new test file to be "
        "picked up with NO Makefile edit"
    )
