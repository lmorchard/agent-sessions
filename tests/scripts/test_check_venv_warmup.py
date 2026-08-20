"""Frozen acceptance checks for #261 — `make check` populates the venv before it fans out.

**The defect, reproduced before it was fixed.** `check` runs `$(MAKE) -j check-parallel`,
and every job under that fan-out enters through `uv run`, which creates and populates
`.venv` on demand. On a cold checkout seven of them race to do it, and one loses:

    $ rm -rf .venv && make check
    error: Failed to install: ruff-0.16.2-py3-none-macosx_11_0_arm64.whl (ruff==0.16.2)
    make[1]: *** [commit-lint] Error 2
    make: *** [check] Error 2

Deterministic, and every fresh worktree hits it. What makes it worth a frozen check
rather than a one-line fix is the *shape* of the failure: the message names a wheel and
an install, so it reads as a network fault or a broken toolchain. Nothing points at make
parallelism, and the honest response to it — rerun, and it passes, because the venv is
warm now — trains the operator to treat `make check` as flaky. A gate you have learned
to rerun is not a gate.

**The check derives the ordering; it does not restate the recipe.** `make -n check`
expands the recursive sub-make too, so the whole plan is one ordered list of commands.
The invariant is positional: the first `uv` command in that plan must run *before* the
parallel fan-out, so that whatever it does to `.venv` has finished before anything
races for it. Change how the warm-up is spelled and this still holds; move it after the
fan-out, or delete it, and this fails.

C2 is the control. Without it C1 is satisfiable by a plan with no parallel fan-out at
all, or with a single consumer — neither of which is the thing being protected.
"""

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The recursive fan-out: `$(MAKE) -j check-parallel`, whatever path make resolves for itself.
_FANOUT = re.compile(r"\bmake\b.*\s-j\b.*\bcheck-parallel\b")

#: Any invocation of the project's package manager, warm-up or consumer.
_UV = re.compile(r"(?:^|\s|/)uv\s+(?P<subcommand>[a-z-]+)")


def _plan() -> list[str]:
    """The ordered command list `make check` would execute, sub-make included."""
    proc = subprocess.run(
        ["make", "-n", "check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in proc.stdout.splitlines() if line.strip()]


def _fanout_index(plan: list[str]) -> int:
    for i, line in enumerate(plan):
        if _FANOUT.search(line):
            return i
    raise AssertionError(
        "no `$(MAKE) -j check-parallel` line in `make -n check`; this check's premise is gone"
    )


def test_first_uv_command_runs_before_the_parallel_fanout():
    """C1. Nothing may reach `uv` for the first time from inside the fan-out.

    Whatever populates `.venv` has to have finished before the concurrent jobs start,
    so the plan's first `uv` invocation must sit above the sub-make line.
    """
    plan = _plan()
    fanout = _fanout_index(plan)

    uses = [(i, m.group("subcommand")) for i, line in enumerate(plan) if (m := _UV.search(line))]
    assert uses, "`make check` reaches `uv` nowhere; this check's premise is gone"

    first_index, first_subcommand = uses[0]
    assert first_index < fanout, (
        f"the plan's first `uv` command is `uv {first_subcommand}` at line {first_index + 1}, "
        f"inside or after the fan-out at line {fanout + 1}. On a cold .venv the concurrent "
        f"jobs will race to populate it and one will fail to install a wheel."
    )


def test_the_fanout_really_has_several_uv_consumers():
    """C2, the control. C1 only means something if the fan-out is concurrent and uv-hungry.

    Collapse `check` to a serial run, or down to one job, and C1 passes while protecting
    nothing — so require the condition that made the race possible to still be present.
    """
    plan = _plan()
    fanout = _fanout_index(plan)

    consumers = [
        line
        for line in plan[fanout + 1 :]
        if (m := _UV.search(line)) and m.group("subcommand") == "run"
    ]
    assert len(consumers) > 1, (
        f"only {len(consumers)} `uv run` job(s) after the fan-out; C1 is guarding a race "
        f"that no longer exists, and one of the two checks is now wrong about the Makefile"
    )
