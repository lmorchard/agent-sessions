"""Acceptance tests for issue #50: `make gate-test` must run every test file.

    C1: WHEN `make gate-test` runs, THEN it SHALL collect every test file
    matching `driver/test_*.py` and `scripts/test_*.py`.

    C2: WHEN a new test file matching those globs is added, THEN `make
    gate-test` SHALL run it with no edit to the `Makefile`.

Written BEFORE the fix exists, so these grade the CRITERION and not one
particular way of meeting it. Nothing here names the recipe's current
arguments, and nothing here embeds an expected count -- both would be a
spelling check that goes stale the next time a test file is added, which is
*exactly the defect* issue #50 is about. Instead:

  * the recipe's command line is read back out of `make -n gate-test` at run
    time, and re-run with `--collect-only` forced in through `PYTEST_ADDOPTS`.
    Going through `PYTEST_ADDOPTS` rather than appending flags to the command
    means the recipe may be a literal file list, a shell glob, `$(wildcard)`,
    a bare `pytest` leaning on `testpaths`, or a wrapper script -- any of them
    is graded the same way;
  * the glob side is expanded by Python at run time and collected on its own;
  * the two live measurements are compared to each other.

So any recipe that genuinely runs everything matching those globs passes.

*(`--collect-only` does not execute anything, so C1 could not recurse. C2
does execute, and would: this module lives in `scripts/` and matches
`scripts/test_*.py`, so once the recipe honours the glob, the inner `make
gate-test` collects THIS module and re-invokes the recipe, unbounded. Hence
the module-level guard below -- every subprocess that can reach pytest is
marked as the inner run, and the inner run skips this module.)*
"""

import glob
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# The two globs the criteria are written in terms of.
GLOBS = ("driver/test_*.py", "scripts/test_*.py")

# Set on every subprocess that can reach pytest; read at import time to decide
# whether this module runs. It must NOT be set in an ordinary run -- `make
# check` and a human both expect these two tests to actually execute.
INNER = "AGENT_SESSION_GATE_TEST_INNER"

pytestmark = pytest.mark.skipif(
    bool(os.environ.get(INNER)),
    reason=(
        f"{INNER} is set: this is the inner `make gate-test` invoked BY this "
        "module. This module matches scripts/test_*.py, so running it here "
        "would re-invoke the recipe forever."
    ),
)

# A temporary file with an obviously-a-probe name, matching `scripts/test_*.py`
# so that a recipe honouring the glob picks it up. It fails on purpose.
PROBE = REPO_ROOT / "scripts" / "test_zz_probe_delete_me.py"
PROBE_BODY = '''\
"""TEMPORARY probe written by scripts/test_gate_test_wiring.py -- delete on sight.

It fails on purpose: its whole job is to make `make gate-test` exit non-zero
if, and only if, the recipe runs files matching `scripts/test_*.py`.
"""


def test_probe_fails_on_purpose():
    assert False, "probe file: present means `make gate-test` must fail"
'''

# `make -n`'s own chatter ("make: Entering directory ...") is never a command.
MAKE_NOISE = re.compile(r"^make(\[\d+\])?: ")

NODE_ID = re.compile(r"^(?P<file>\S+\.py)::(?P<rest>\S.*)$")
FILE_COUNT = re.compile(r"^(?P<file>\S+\.py): (?P<n>\d+)$")


def inner_env(**extra: str) -> dict:
    """os.environ plus the recursion marker, plus anything else asked for."""
    env = dict(os.environ)
    env[INNER] = "1"
    env.update(extra)
    return env


def run(argv=None, *, script=None, env=None, timeout=300):
    """Always from the repo root, so pytest's launch directory cannot matter."""
    cmd = ["bash", "-c", script] if script is not None else argv
    return subprocess.run(
        cmd, cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=timeout
    )


def make_n(target: str) -> str:
    """The recipe's command line, without running it. Never hardcoded here."""
    proc = run(["make", "-n", target], env=inner_env(), timeout=60)
    assert proc.returncode == 0, f"`make -n {target}` failed:\n{proc.stderr}"
    script = "\n".join(
        line for line in proc.stdout.splitlines()
        if line.strip() and not MAKE_NOISE.match(line)
    )
    assert script, f"`make -n {target}` printed no command:\n{proc.stdout!r}"
    return script


def parse_collection(proc) -> tuple[set, dict]:
    """(node ids, per-file counts) out of a `--collect-only` run.

    Two output shapes are accepted, because the recipe's own verbosity is not
    ours to control: one node id per line (`-q`, which this repo's ini sets),
    and the `path: N` summary (`-qq`, if a recipe passes its own `-q` on top).
    A collection that did not exit clean is an error, not an empty set -- a
    zero must never render as a passing measurement.
    """
    assert proc.returncode == 0, (
        "collection itself failed, so there is no measurement to compare:\n"
        f"exit {proc.returncode}\n{proc.stdout}\n{proc.stderr}"
    )
    ids, counts = set(), {}
    for line in proc.stdout.splitlines():
        line = line.strip()
        if m := NODE_ID.match(line):
            path = rel(m.group("file"))
            ids.add(f"{path}::{m.group('rest')}")
            counts[path] = counts.get(path, 0) + 1
        elif m := FILE_COUNT.match(line):
            counts[rel(m.group("file"))] = int(m.group("n"))
    assert counts, (
        "no collected tests could be parsed out of the run -- the output shape "
        f"is not one this test knows how to read:\n{proc.stdout}\n{proc.stderr}"
    )
    return ids, counts


def rel(path: str) -> str:
    """Node ids are rootdir-relative already; normalise anyway, cheaply."""
    p = Path(path)
    return str(p.relative_to(REPO_ROOT)) if p.is_absolute() else path


def total(counts: dict) -> int:
    return sum(counts.values())


def describe(label, counts: dict, other: dict) -> str:
    missing = {f: n for f, n in counts.items() if f not in other}
    body = "\n".join(f"      {f} ({n} tests)" for f, n in sorted(missing.items()))
    return f"    {label}:\n{body or '      (none)'}"


# --- C1: the recipe collects everything the globs match ----------------------

def test_gate_test_collects_every_globbed_test():
    recipe_script = make_n("gate-test")
    recipe = run(
        script=recipe_script, env=inner_env(PYTEST_ADDOPTS="--collect-only")
    )
    _recipe_ids, recipe_counts = parse_collection(recipe)

    globbed = sorted(
        f for pattern in GLOBS for f in glob.glob(pattern, root_dir=REPO_ROOT)
    )
    assert globbed, f"the globs {GLOBS} matched no files at all -- broken scope"
    glob_run = run(
        [sys.executable, "-m", "pytest", *globbed],
        env=inner_env(PYTEST_ADDOPTS="--collect-only"),
    )
    _glob_ids, glob_counts = parse_collection(glob_run)

    assert total(recipe_counts) == total(glob_counts), (
        "`make gate-test` does not collect every test file matching the globs.\n"
        f"  recipe (`make -n gate-test`): {total(recipe_counts)} tests\n"
        f"  globs {GLOBS}: {total(glob_counts)} tests\n"
        + describe("matched by the globs but NOT run by the recipe",
                   glob_counts, recipe_counts) + "\n"
        + describe("run by the recipe but NOT matched by the globs",
                   recipe_counts, glob_counts) + "\n"
        f"  the recipe, as `make -n` prints it:\n    {recipe_script}"
    )


# --- C2: a new test file runs without a Makefile edit ------------------------

@pytest.fixture
def probe():
    """Write the probe; remove it in a `finally` so nothing is left behind on
    an assertion failure, an error, or a KeyboardInterrupt. `missing_ok` so a
    test that already removed it -- or a previous crashed run -- is fine."""
    try:
        PROBE.write_text(PROBE_BODY)
        yield PROBE
    finally:
        PROBE.unlink(missing_ok=True)


def test_a_new_test_file_is_run_without_a_makefile_edit(probe):
    """Both arms run the SAME unmodified Makefile; only the probe file moves.

    The assertion is on exit status, not on stdout -- what `make check` acts
    on is the status, and a recipe is free to print whatever it likes.
    """
    makefile = (REPO_ROOT / "Makefile").read_bytes()

    with_probe = run(["make", "gate-test"], env=inner_env())
    assert with_probe.returncode != 0, (
        f"a new test file ({probe.relative_to(REPO_ROOT)}) matching "
        f"{GLOBS[1]!r} fails on purpose, yet `make gate-test` exited 0 -- so "
        "the recipe never ran it, and adding a test file still requires a "
        f"Makefile edit.\n{with_probe.stdout}\n{with_probe.stderr}"
    )

    probe.unlink()
    without_probe = run(["make", "gate-test"], env=inner_env())
    assert without_probe.returncode == 0, (
        "with the probe removed `make gate-test` should be green again; the "
        "non-zero exit above has to come from the probe, not from a suite that "
        f"was already red.\n{without_probe.stdout}\n{without_probe.stderr}"
    )

    assert (REPO_ROOT / "Makefile").read_bytes() == makefile, (
        "the Makefile changed between the two arms -- C2 is about a new test "
        "file needing NO Makefile edit, so this test proves nothing if it edits it"
    )
