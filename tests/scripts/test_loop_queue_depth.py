"""Frozen acceptance checks for #261 H1 — `make loop ISSUES=n` reaches the driver.

    $ make -n loop ISSUES=7
    make run ISSUES=2                     <- swallowed
    $ make -n loop BUDGET=99
    ... --max-budget-usd 99               <- survived

`loop`'s recipe was `@$(MAKE) run ISSUES=$(or $(ISSUES_OVERRIDE),2)`. A recursive
command-line assignment beats the outer one, so the sub-make saw `ISSUES=2` whatever
the caller asked for. `make help` advertised *"ISSUES=n BUDGET=n override queue depth /
per-issue ceiling"* — true for BUDGET, false for ISSUES, **on the one target whose
entire purpose is queue depth.** The escape hatch, `ISSUES_OVERRIDE`, appeared exactly
once in the repo, undocumented and absent from `help`.

It is not cosmetic, because `BUDGET ?= 35` is *per issue*: a swallowed `ISSUES=5` is a
wrong-sized spend, not a wrong-sized queue. This is #71 recurring one variable over,
and `Makefile`'s comment above `run` has the lesson written directly above it.

**Why the existing suites do not cover it, which is the part worth freezing.**
`test_run_issue_flag.py` discovers targets by matching recipes that invoke `$(DRIVER)`;
`loop`'s recipe invokes `$(MAKE)`, so `loop` is never discovered — deliberately, per
that file's own docstring, to avoid grading `run` twice under another name. And
`test_dry_run_parity.py` explicitly *exempts* `--max-budget-usd` and `--max-issues`
from its targeting flags. So the **targeting** half of the run/dry-run quartet is well
protected and the **queue/budget** half was protected by nothing.

That is the finding: the quartet's duplication is not the bug, the uncovered slice is.
These checks take the uncovered slice and leave the discovery suites alone.

**They derive, they never restate.** Each assertion's left side is whatever
`make -n` prints today.
"""

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

#: `--max-issues N`, wherever it lands in the expanded recipe.
_MAX_ISSUES = re.compile(r"--max-issues\s+(\S+)")
_MAX_BUDGET = re.compile(r"--max-budget-usd\s+(\S+)")


def _plan(*overrides: str) -> str:
    proc = subprocess.run(
        ["make", "-n", "loop", *overrides],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout


def _flag(pattern: re.Pattern[str], plan: str) -> str:
    m = pattern.search(plan)
    assert m, f"`make -n loop` emitted no {pattern.pattern}; the recipe changed shape:\n{plan}"
    return m.group(1)


def test_loop_forwards_the_callers_queue_depth():
    """C1. The defect, stated as the invariant it violated."""
    assert _flag(_MAX_ISSUES, _plan("ISSUES=7")) == "7", (
        "`make loop ISSUES=7` reached the driver with a different queue depth. A "
        "recursive `$(MAKE) run ISSUES=...` assignment overrides the caller's."
    )


def test_loop_has_its_own_default_queue_depth():
    """C2, the control. C1 is satisfiable by forwarding `ISSUES` and nothing else.

    `loop` exists to be a *deeper* queue than `run`, so an unqualified `make loop` must
    still ask for more than one issue. Without this, dropping the default to `run`'s
    would pass C1 while making the target pointless.
    """
    plain = int(_flag(_MAX_ISSUES, _plan()))
    assert plain > 1, f"`make loop` with no override asks for {plain} issue(s)"


def test_loop_still_forwards_the_budget_it_always_forwarded():
    """C3. BUDGET was the half that worked; a fix to ISSUES must not cost it."""
    assert _flag(_MAX_BUDGET, _plan("BUDGET=99")) == "99"


@pytest.mark.parametrize("override", ["ISSUES=7", "BUDGET=99"])
def test_help_only_promises_overrides_that_arrive(override):
    """C4. `make help` advertised both; only one worked.

    A gate is worth little next to documentation that contradicts it, and this is the
    line that did: `help` named ISSUES and BUDGET together while one was swallowed.
    """
    var, value = override.split("=")
    help_text = subprocess.run(
        ["make", "help"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout
    if f"{var}=" not in help_text:
        pytest.skip(f"`make help` no longer advertises {var}=")
    plan = _plan(override)
    arrived = _flag(_MAX_ISSUES if var == "ISSUES" else _MAX_BUDGET, plan)
    assert arrived == value, f"`make help` promises {var}= and `make loop {override}` drops it"
