
import os
import re
import signal
import subprocess

import pytest

from agent_sessions.scripts import docs_check

RISK_POLICY = """## Risk-gated paths (off-limits to unattended work)

The default is `needs-review`.

- **`src/agent_sessions/driver/agent_session_driver.py`** is gated.

### Drivable (the allowlist)

- **`docs/**`** is drivable.

## Governing principle
"""


@pytest.fixture
def policy_root(tmp_path, monkeypatch):
    monkeypatch.setattr(docs_check, "ROOT", tmp_path)
    docs_check.failures.clear()
    return tmp_path


def write_policy_doc(root, name, prefix, policy=RISK_POLICY):
    (root / name).write_text(f"{prefix}\n\n{policy}", encoding="utf-8")


def test_risk_policy_parity_ignores_instruction_text_outside_policy(policy_root):
    write_policy_doc(policy_root, "AGENTS.md", "Codex skills live in ~/.Codex/skills.")
    write_policy_doc(policy_root, "CLAUDE.md", "Claude skills live in ~/.claude/skills.")

    checker = getattr(docs_check, "check_risk_policy_parity", None)
    assert checker is not None, "docs-check has no AGENTS.md/CLAUDE.md risk-policy parity guard"
    checker()

    assert docs_check.failures == []


def test_risk_policy_parity_rejects_controlled_divergence(policy_root):
    write_policy_doc(policy_root, "AGENTS.md", "Codex instructions")
    write_policy_doc(
        policy_root,
        "CLAUDE.md",
        "Claude instructions",
        RISK_POLICY.replace("`docs/**`", "`documentation/**`"),
    )

    checker = getattr(docs_check, "check_risk_policy_parity", None)
    assert checker is not None, "docs-check has no AGENTS.md/CLAUDE.md risk-policy parity guard"
    checker()

    assert docs_check.failures == [
        "AGENTS.md and CLAUDE.md risk-path policies differ; keep the complete "
        "'Risk-gated paths' sections aligned"
    ]


# --- parity: AGENTS.md may point at CLAUDE.md instead of copying it ----------
#
# The two files were byte-identical, and the parity check enforced only the
# `Risk-gated paths` section. Everything outside it drifted -- a find-and-replace that
# rewrote a filesystem path, a second that invented a `Codex -p` flag the binary does
# not have in that sense, and one section where AGENTS.md silently lost a rule. The
# guarded part stayed in sync; the unguarded remainder did not, and there is no bound
# on how much unguarded remainder there will be.
#
# So a pointer is now an accepted shape. The checks below are about the ways a pointer
# can be wrong, which is the whole reason this needed teaching rather than relaxing.


POINTER = "# agent-sessions\n\nRead [CLAUDE.md](CLAUDE.md). It is the single instruction file.\n"


def test_parity_accepts_agents_md_as_a_pointer(policy_root):
    (policy_root / "AGENTS.md").write_text(POINTER, encoding="utf-8")
    write_policy_doc(policy_root, "CLAUDE.md", "Claude instructions")

    docs_check.check_risk_policy_parity()

    assert docs_check.failures == []


def test_parity_rejects_a_pointer_that_names_no_instruction_file(policy_root):
    """A short file is not a pointer just by being short."""
    (policy_root / "AGENTS.md").write_text("# agent-sessions\n\nSee the docs.\n", encoding="utf-8")
    write_policy_doc(policy_root, "CLAUDE.md", "Claude instructions")

    docs_check.check_risk_policy_parity()

    assert len(docs_check.failures) == 1
    assert "CLAUDE.md" in docs_check.failures[0]


def test_parity_rejects_a_pointer_whose_target_carries_no_policy(policy_root):
    """Pointing somewhere is worthless if the target has nothing to point at.

    This is the failure that would otherwise be silent: delete the risk section from
    CLAUDE.md and, with AGENTS.md reduced to a pointer, *neither* file would have one
    and the parity check would have nothing to compare and pass.
    """
    (policy_root / "AGENTS.md").write_text(POINTER, encoding="utf-8")
    (policy_root / "CLAUDE.md").write_text("# agent-sessions\n\nNo policy here.\n", encoding="utf-8")

    docs_check.check_risk_policy_parity()

    assert len(docs_check.failures) == 1
    assert "risk" in docs_check.failures[0].lower()


def test_a_file_that_carries_its_own_policy_is_not_a_pointer(policy_root):
    """The half-migrated case, and the reason the pointer test is not just "links to".

    An AGENTS.md that links CLAUDE.md *and* keeps a copy of the policy is the exact
    state this change exists to prevent, because the copy is what drifts. Linking must
    not buy an exemption from parity.
    """
    write_policy_doc(
        policy_root,
        "AGENTS.md",
        "Codex instructions. Read [CLAUDE.md](CLAUDE.md) as well.",
        RISK_POLICY.replace("`docs/**`", "`documentation/**`"),
    )
    write_policy_doc(policy_root, "CLAUDE.md", "Claude instructions")

    docs_check.check_risk_policy_parity()

    assert len(docs_check.failures) == 1
    assert "differ" in docs_check.failures[0]


# --- check_world_state_claims: driven through the shipped function -----------
#
# This block used to reimplement `docs_check.check_world_state_claims` as a local
# `check_line()` and assert against the copy. `docs_check` was never called, so the
# newest doc-rot rule had zero coverage through shipping code -- `findings.md` defect
# class 1, instance 9, inside the doc-rot detector's own suite, and the residual risk
# CLAUDE.md names about leaving `tests/**` drivable.
#
# The copy had already drifted. Its repo-count pattern was `\b([a-z]+) repositories\b`
# where the shipped one is `\b(one|two|...|ten|\d+) repositories\b`, so
# "Runs against many repositories" was a failure in the test and a pass in production.
# It also carried an exemption the shipped code lacks and omitted two it has, and its
# 3-tuple predicate row kept alive a code path that is permanently dead in the shipped
# table -- which is 2-tuples throughout, making `cond = item[2:]` always empty. The
# mechanism existed only in the test.
#
# It also produced three of the four errors `mypy src tests` reports and `mypy src`
# hides, including `"str" not callable`.
#
# So: one doc under a patched ROOT, and the real function.


def write_doc(root, body: str, name: str = "docs/probe.md"):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def claims_in(root, body: str) -> list[str]:
    write_doc(root, body)
    docs_check.check_world_state_claims()
    return list(docs_check.failures)


@pytest.mark.parametrize(
    "line",
    [
        "This is not proven yet",
        "It has never been driven before",
        "Runs against two repositories",
        "We have seven PRs open",
    ],
)
def test_world_state_claims_are_flagged(policy_root, line):
    assert len(claims_in(policy_root, line + "\n")) == 1, (
        f"the shipped detector let this through: {line!r}"
    )


@pytest.mark.parametrize(
    ("line", "why"),
    [
        ("We have open PRs", "no count, so no claim"),
        ("As of 2026-08-10, it is not proven", "the dated-fact escape hatch"),
        ("The not proven list survived", "a line explaining the rule, not asserting state"),
    ],
)
def test_world_state_exemptions_hold(policy_root, line, why):
    assert claims_in(policy_root, line + "\n") == [], why


def test_the_repo_count_pattern_requires_a_count_word(policy_root):
    """Controlled divergence -- the exact line the deleted clone got wrong.

    The clone matched any lowercase word before "repositories", so it flagged this
    and the suite was green over a detector that does not. Pinned in the direction
    the shipped code actually behaves, so a future widening of the pattern shows up
    here as a decision rather than arriving silently.
    """
    assert claims_in(policy_root, "Runs against many repositories\n") == []


def test_a_flagged_claim_reports_its_file_and_line(policy_root):
    """The clone returned bare match text, so nothing pinned the citation format."""
    failures = claims_in(policy_root, "intro\n\nWe have seven PRs open\n")
    assert len(failures) == 1
    assert failures[0].startswith("docs/probe.md:3: seven PRs -- ")


# --- is_shim: the guard against a partition naming a facade -------------------
#
# `check_partition`'s `is_shim` guard exists so the risk partition cannot name a
# re-export facade in place of the implementation it hides -- gating a facade reads
# as protection and provides none. It missed the live instance it was written for:
# `src/agent_sessions/driver/agent_session_driver.py` is a pure facade whose own
# docstring opens "Defines nothing itself", and the old predicate (a marker string,
# or fewer than 30 lines mentioning `from agent_sessions`) matched neither half of
# it. The file carries no marker and runs past 150 lines.
#
# Length was never the property that mattered. These checks pin the property that
# does -- defining nothing of its own -- against real files on both sides of the
# line, plus tmp_path divergences for the two ways the predicate could go wrong.

DRIVER_PKG = docs_check.ROOT / "src" / "agent_sessions" / "driver"


def test_is_shim_flags_a_facade_that_defines_nothing():
    """The live instance the guard was written for and did not catch."""
    facade = DRIVER_PKG / "agent_session_driver.py"
    assert facade.is_file(), f"{facade} is gone; this check's subject no longer exists"
    assert docs_check.is_shim(facade), (
        "agent_session_driver.py re-exports and defines nothing, so the partition "
        "naming it names a facade -- is_shim has to say so"
    )


@pytest.mark.parametrize("name", ["lifecycle.py", "gate.py", "router.py", "writes.py"])
def test_is_shim_leaves_real_implementations_alone(name):
    """The control. These are the modules the partition should be naming."""
    module = DRIVER_PKG / name
    assert module.is_file(), f"{module} is gone; this check's subject no longer exists"
    assert not docs_check.is_shim(module)


def test_is_shim_ignores_a_module_that_defines_nothing_and_imports_nothing(tmp_path):
    """Controlled divergence on the "defines nothing" half.

    A constants module has no functions and no classes either. Flagging it would
    make the guard reject a legitimately gated policy file, so both halves of the
    predicate are load-bearing and this proves it.
    """
    constants = tmp_path / "constants.py"
    constants.write_text('PARK_LABEL = "agent-session:needs-human"\nTTL = 600\n')
    assert not docs_check.is_shim(constants)


def test_is_shim_flags_a_star_reexport(tmp_path):
    barrel = tmp_path / "barrel.py"
    barrel.write_text("from agent_sessions.driver.lifecycle import *  # noqa: F403\n")
    assert docs_check.is_shim(barrel)


def test_is_shim_ignores_a_module_that_imports_and_defines_its_own_code(tmp_path):
    """Controlled divergence on the "imports names" half.

    Most real modules import. The distinguishing property is whether anything
    originates here, so one definition is enough to make a file not a facade.
    """
    real = tmp_path / "real.py"
    real.write_text(
        "from agent_sessions.driver.output import say\n"
        "\n"
        "def announce(msg):\n"
        "    say(msg)\n"
    )
    assert not docs_check.is_shim(real)


def test_is_shim_ignores_a_non_python_file(tmp_path):
    """`driver/agent-session-driver.sh` is named in the partition and is not parseable."""
    launcher = tmp_path / "launcher.sh"
    launcher.write_text('#!/usr/bin/env bash\nexec python -m agent_sessions.driver "$@"\n')
    assert not docs_check.is_shim(launcher)


# --- check_partition: a facade may be named, but not on its own ---------------

FACADE_POLICY = """## Risk-gated paths (off-limits to unattended work)

The default is `needs-review`.

{bullets}

### Drivable (the allowlist)

- **`docs/`** is drivable.

## Governing principle
"""


def _package_with_facade(root):
    """A minimal src-layout package holding one facade and the module it re-exports."""
    pkg = root / "src" / "agent_sessions" / "driver"
    pkg.mkdir(parents=True)
    (pkg / "lifecycle.py").write_text("def classify_and_record(ctx):\n    return ctx\n")
    (pkg / "facade.py").write_text(
        "from agent_sessions.driver.lifecycle import classify_and_record\n"
        '\n__all__ = ["classify_and_record"]\n'
    )
    (root / "docs").mkdir()


def test_partition_rejects_a_facade_named_without_its_implementation(policy_root):
    """Controlled divergence: the facade alone is the defect the guard is for."""
    _package_with_facade(policy_root)
    (policy_root / "CLAUDE.md").write_text(
        FACADE_POLICY.format(
            bullets="- **`src/agent_sessions/driver/facade.py`** is gated."
        ),
        encoding="utf-8",
    )

    docs_check.check_partition()

    assert len(docs_check.failures) == 1
    assert "facade.py" in docs_check.failures[0]
    assert "lifecycle.py" in docs_check.failures[0], (
        "the failure should name the implementation the partition is missing, "
        "not just complain that a facade was named"
    )


def test_partition_accepts_a_facade_named_alongside_its_implementation(policy_root):
    """A facade can be gated for its own reason once the implementation is gated too.

    An entry point is worth gating even after it thins out -- becoming thin does not
    silently widen the partition. What the guard is protecting against is the facade
    standing in *for* the implementation, so naming both is not the defect.
    """
    _package_with_facade(policy_root)
    (policy_root / "CLAUDE.md").write_text(
        FACADE_POLICY.format(
            bullets=(
                "- **`src/agent_sessions/driver/lifecycle.py`** holds the routing.\n"
                "- **`src/agent_sessions/driver/facade.py`** is the entry point.\n"
            )
        ),
        encoding="utf-8",
    )

    docs_check.check_partition()

    assert docs_check.failures == []


def test_partition_accepts_a_multi_source_facade_when_one_source_is_named(policy_root):
    """*Any*, not *all* -- and this is the check that pins the difference.

    The real facade re-exports from five modules. Demanding a bullet for each would
    fill the partition with entries carrying no reason, and buy nothing: unlisted paths
    are `needs-review` by default, so their absence exposes nothing. One named source
    is enough to prove the facade is not being substituted for the implementation.
    """
    pkg = policy_root / "src" / "agent_sessions" / "driver"
    pkg.mkdir(parents=True)
    (pkg / "lifecycle.py").write_text("def classify_and_record(ctx):\n    return ctx\n")
    (pkg / "locks.py").write_text("def acquire_lock(n):\n    return n\n")
    (pkg / "board.py").write_text("def move(n):\n    return n\n")
    (pkg / "facade.py").write_text(
        "from agent_sessions.driver.lifecycle import classify_and_record\n"
        "from agent_sessions.driver.locks import acquire_lock\n"
        "from agent_sessions.driver.board import move\n"
    )
    (policy_root / "docs").mkdir()
    (policy_root / "CLAUDE.md").write_text(
        FACADE_POLICY.format(
            bullets=(
                "- **`src/agent_sessions/driver/lifecycle.py`** holds the routing.\n"
                "- **`src/agent_sessions/driver/facade.py`** is the entry point.\n"
            )
        ),
        encoding="utf-8",
    )

    docs_check.check_partition()

    assert docs_check.failures == []


# --- issue #249: the assertion-count probe must run, and must say which of three
#     things happened -------------------------------------------------------------
#
# The probe had two independent path bugs, either of which alone kept it permanently
# skipping. It passed literal glob strings to `subprocess.run`, which never invokes a
# shell, so pytest saw `*` as a filename and exited 4; and its second argument still
# named `scripts/test_*.py`, which #257/#258 emptied of tests. `returncode not in
# (0, 5)` then turned both into `None`, and `None` prints as a skip.
#
# Three outcomes have to stay distinguishable, because the failure that hid here for
# months was two of them collapsing into one:
#
#   1. the probe could not run              -> `None`  -> an explicit skip line
#   2. the probe ran and found no claims    -> a count -> the disclosed-zero line
#   3. the probe ran and a claim disagrees  -> a count -> a failure
#
# Outcome 2 is what the maintained docs currently produce, and it is the correct
# result rather than an unfinished one: every `N assertions` string in the repo lives
# under `FROZEN`. So these tests grade the probe, not the count.

#: Set on the `make gate-test` this module spawns as concurrent load. Without it, that
#: inner run would reach this module again and spawn its own load, without bound.
CONCURRENCY_INNER_RUN_ENV = "AGENT_SESSIONS_DOCS_CHECK_CONCURRENCY_INNER_RUN"

_GLOB_ARG = re.compile(r"\btests/\S*test_\*\.py")

_inner = pytest.mark.skipif(
    os.environ.get(CONCURRENCY_INNER_RUN_ENV) == "1",
    reason=f"{CONCURRENCY_INNER_RUN_ENV} is set: this is the inner load run.",
)


@pytest.fixture
def clean_skips():
    """`docs_check` accumulates into module-level lists; don't inherit another test's."""
    docs_check.failures.clear()
    docs_check.skips.clear()
    yield
    docs_check.failures.clear()
    docs_check.skips.clear()


def _load_env() -> dict:
    """Environment for a nested `make gate-test` used purely as concurrent load."""
    env = os.environ.copy()
    for var in ("MAKEFLAGS", "MFLAGS", "MAKELEVEL"):
        env.pop(var, None)
    env[CONCURRENCY_INNER_RUN_ENV] = "1"
    # The wiring suite's own guard. Its C2 writes a probe test file into the working
    # tree, and this load gets killed mid-run -- so leaving C2 enabled would risk
    # abandoning that file in `tests/scripts/`, where every later run would collect it.
    env["AGENT_SESSIONS_GATE_TEST_WIRING_INNER_RUN"] = "1"
    return env


def _kill_group(load: subprocess.Popen) -> None:
    """Tear down the concurrent load without ever raising.

    This runs in a `finally`, so an exception here would *replace* the assertion the
    test exists to make -- a real failure would surface as a `ProcessLookupError` from
    cleanup. Every step is therefore best-effort, including the `SIGKILL` escalation:
    the process can exit between `wait()` timing out and the signal being sent, and the
    group can already be reaped, both of which are the outcome being asked for anyway.
    """
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(os.getpgid(load.pid), sig)
        except (ProcessLookupError, PermissionError, OSError):
            pass
        try:
            load.wait(timeout=30)
            return
        except subprocess.TimeoutExpired:
            continue


def test_the_probe_globs_match_the_gate_test_recipe():
    """Derived from the Makefile, never restated -- that equality is what broke.

    The probe's second argument outlived the directory it named because nothing
    compared the two. Reading the recipe at run time means the next move of the suite
    fails here loudly instead of degrading the probe into a silent skip.
    """
    proc = subprocess.run(
        ["make", "-n", "--no-print-directory", "gate-test"],
        cwd=docs_check.ROOT,
        env=_load_env(),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"`make -n gate-test` exited {proc.returncode}: {proc.stderr}"

    recipe_globs = set(_GLOB_ARG.findall(proc.stdout))
    assert recipe_globs, f"parsed no test globs out of the gate-test recipe:\n{proc.stdout}"
    assert recipe_globs == set(docs_check.GATE_TEST_GLOBS), (
        "docs_check.GATE_TEST_GLOBS has drifted from the `make gate-test` recipe; the "
        f"recipe runs {sorted(recipe_globs)}, the probe measures "
        f"{sorted(docs_check.GATE_TEST_GLOBS)}"
    )


def test_gate_test_files_hands_pytest_real_paths():
    paths = docs_check.gate_test_files()

    assert paths, "the gate-test globs matched no files"
    assert not [p for p in paths if "*" in p], (
        f"an unexpanded glob would reach pytest as a literal filename: {paths}"
    )
    assert all((docs_check.ROOT / p).is_file() for p in paths)
    for prefix in ("tests/driver/", "tests/scripts/"):
        assert any(p.startswith(prefix) for p in paths), f"no files from {prefix}"


def test_gate_test_files_is_empty_when_a_real_repo_matches_nothing(tmp_path, monkeypatch):
    """A repo git can read, with no test files in it -- not the no-repo case below.

    Kept distinct on purpose: both return `[]`, and if this one leaned on tmp_path not
    being a git checkout it would pass for the wrong reason and stop grading the glob.
    """
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "readme.md").write_text("no tests here\n", encoding="utf-8")
    subprocess.run(["git", "add", "docs"], cwd=tmp_path, check=True, capture_output=True)
    monkeypatch.setattr(docs_check, "ROOT", tmp_path)

    assert docs_check.gate_test_files() == []


def _scratch_suite(root):
    """A throwaway repo shaped like this one's test layout, with one file left untracked.

    `isolate_git_config` in `tests/conftest.py` already supplies an identity and cuts the
    operator's global config out, so `git init` here needs no further setup. Nothing is
    committed: `git ls-files` reads the index, so staging is enough to make a file
    tracked, and skipping the commit keeps this fast.
    """
    for d in ("tests/driver", "tests/scripts"):
        (root / d).mkdir(parents=True)
    tracked = root / "tests" / "driver" / "test_real.py"
    tracked.write_text("def test_x():\n    assert True\n", encoding="utf-8")
    (root / "tests" / "scripts" / "test_also_real.py").write_text(
        "def test_y():\n    assert True\n", encoding="utf-8"
    )
    subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "add", "tests"], cwd=root, check=True, capture_output=True)

    # Written *after* `git add`, so it is untracked -- the shape of C2's transient probe.
    untracked = root / "tests" / "scripts" / "test_zz_gate_wiring_probe_1234_abcd.py"
    untracked.write_text("def test_z():\n    assert False\n", encoding="utf-8")
    return untracked


def test_gate_test_files_excludes_an_untracked_file(tmp_path, monkeypatch):
    """The parallel race, at the unit where it is decidable.

    `tests/scripts/test_gate_test_wiring.py`'s C2 writes a real
    `test_zz_gate_wiring_probe_*.py` into `tests/scripts/` and deletes it again, while
    `make check` runs `gate-test` and `docs-check` at the same time. A filesystem glob
    returns that file, C2 removes it, and the name this probe hands pytest no longer
    exists -- exit 4, `None`, and #249's skip is back intermittently.

    Asserted through *untracked-ness* rather than the probe's filename. The wiring suite
    already matches the literal `test_zz_gate_wiring_probe` in two places, and
    `findings.md` defect class 2 instance 9 is this repo paying for a name list twice in
    one day. A future transient with a different name is covered here without being
    named; `_scratch_suite` uses C2's spelling only so the case is recognisable.
    """
    untracked = _scratch_suite(tmp_path)
    monkeypatch.setattr(docs_check, "ROOT", tmp_path)

    files = docs_check.gate_test_files()

    assert files == ["tests/driver/test_real.py", "tests/scripts/test_also_real.py"], (
        "gate_test_files() should return the tracked suite, sorted"
    )
    assert untracked.is_file(), "the fixture should still be on disk -- exclusion is the point"


def test_gate_test_files_excludes_a_tracked_file_deleted_from_disk(tmp_path, monkeypatch):
    """`git ls-files` lists the index, so a staged-then-deleted path is still tracked.

    Handing pytest a filename that is not there is the same exit 4 the untracked probe
    causes, reached from the opposite direction.
    """
    _scratch_suite(tmp_path)
    monkeypatch.setattr(docs_check, "ROOT", tmp_path)
    (tmp_path / "tests" / "driver" / "test_real.py").unlink()

    assert docs_check.gate_test_files() == ["tests/scripts/test_also_real.py"]


def test_gate_test_files_is_empty_outside_a_git_repository(tmp_path, monkeypatch):
    """No repo, no answer -- and `live_bash_assertions()` turns that into a skip.

    Honest rather than convenient: a probe that cannot find the committed suite must not
    report a count for whatever files happen to be lying around.
    """
    (tmp_path / "tests" / "driver").mkdir(parents=True)
    (tmp_path / "tests" / "driver" / "test_real.py").write_text("def test_x():\n    pass\n")
    monkeypatch.setattr(docs_check, "ROOT", tmp_path)

    assert docs_check.gate_test_files() == []


def test_the_probe_reports_none_when_the_globs_collect_nothing(tmp_path, monkeypatch):
    """The third state, pinned: an argv collecting nothing is a skip, not a zero.

    Before the fix this reached pytest and came back exit 5, which the old
    `not in (0, 5)` guard waved through to a `None` produced two lines later by the
    count regex finding nothing -- the same `None` a crash produces. It still returns
    `None`, deliberately; what must not happen is it returning `0` and having
    `check_counts` grade real claims against an empty suite.
    """
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    monkeypatch.setattr(docs_check, "ROOT", tmp_path)

    assert docs_check.live_bash_assertions() is None


def test_the_probe_returns_a_count():
    actual = docs_check.live_bash_assertions()

    assert actual is not None, (
        "live_bash_assertions() returned None: the assertion-count check is skipping, "
        "which is issue #249's defect"
    )
    assert actual > 0


@_inner
def test_the_probe_returns_a_count_while_gate_test_runs():
    """`make check` runs `docs-check` and `gate-test` in parallel; so does this.

    Concurrency turned out not to be the cause -- the two path bugs reproduce under the
    standalone target too -- but it is the condition the defect was observed in, so it
    stays covered. The load is killed as soon as the probe answers; the property is the
    overlap, not the full suite.
    """
    load = subprocess.Popen(
        ["make", "gate-test"],
        cwd=docs_check.ROOT,
        env=_load_env(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        actual = docs_check.live_bash_assertions()
        still_running = load.poll() is None
    finally:
        _kill_group(load)

    assert still_running, (
        "the concurrent `make gate-test` had already exited when the probe returned, "
        "so this run did not actually test the overlap"
    )
    assert actual is not None, (
        "live_bash_assertions() returned None while gate-test was running: the "
        "assertion-count check skips under the parallel gate"
    )
    assert actual > 0


def test_check_counts_does_not_skip(clean_skips, capsys):
    """C2/C3's property, at the unit the criteria name.

    `make check` and `make docs-check` both reduce to this: after `check_counts`, there
    is no assertion-count entry in `skips`. What is printed instead is the disclosed
    zero, and that distinction is asserted rather than assumed -- silence here would be
    indistinguishable from a pass.
    """
    docs_check.check_counts()

    assert not [s for s in docs_check.skips if "assertion counts" in s], (
        f"the assertion-count skip is back: {docs_check.skips}"
    )
    assert docs_check.failures == []
    assert "no assertion-count claims found to check" in capsys.readouterr().out, (
        "every `N assertions` claim in the repo is frozen, so the probe should say so "
        "out loud rather than print nothing"
    )


def test_the_only_assertion_count_claims_are_frozen():
    """Why the check above expects a disclosed zero, kept honest rather than asserted.

    If someone writes a maintained `N assertions` claim, `check_counts` starts grading
    it and the test above stops describing what happens. This says so at that moment,
    instead of leaving a stale comment behind.
    """
    pattern = re.compile(r"\b(\d+)[\s-]assertions?\b")
    live = [
        f"{p.relative_to(docs_check.ROOT)}:{n}"
        for p in docs_check.md_files()
        if not docs_check.is_frozen(p)
        for n, line in enumerate(p.read_text().split("\n"), 1)
        if pattern.search(line)
    ]

    assert live == [], (
        "a maintained doc now states an assertion count, so `check_counts` grades it "
        f"rather than reporting the disclosed zero: {live}"
    )
