"""Frozen acceptance checks for issue #71 — every driver-invoking target honors ISSUE=.

`ISSUE=` was wired into `run-self` and not into `run`. No error, no warning: the
variable was simply unread, so `make run ISSUE=704` ran whatever selection picked.
It happened to pick #704, which is the worst outcome — the flag looked honored and
was not. Same family as #60, a make variable that reads as honored and isn't.

**These checks discover their own targets.** Naming `run` and `run-self` as a literal
pair would fix the instance and leave the mechanism: the defect *was* an asymmetry
between two hand-maintained recipes, and a hand-maintained list of them is the same
staleness shape (issue #50, and `findings.md` defect class 5). So C1 reads the
`Makefile`, finds every target whose recipe invokes `$(DRIVER)` without `--dry-run`,
and requires ISSUE= of each. Add a third such target and it is graded with no edit
here; wire it wrong and this fails.

**They derive, they never restate.** The flag each recipe emits is extracted by
running `make -n <target>` — the left side of every assertion is whatever the
`Makefile` actually says today, not a copy of it living in this file.

C2 is the control. Without it, C1 is satisfiable by hardcoding `--issue` into the
recipe unconditionally, which would pin every run to one issue forever.
"""

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = REPO_ROOT / "Makefile"

#: A recipe line belongs to the target named by the most recent target line.
_TARGET = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*)\s*:(?!=)")

#: `$(DRIVER)` *executed*, not merely named. `driver-check` and `skill-readonly` both
#: pass the driver's path to `grep`; they are readers, and ISSUE= means nothing to them.
#: Anchored at the start of the command so an argument position cannot match.
_INVOKES_DRIVER = re.compile(r"^\t\s*@?\s*(?:bash|sh)?\s*\$\(DRIVER\)")


def _driver_targets() -> list[str]:
    """Targets whose recipe really invokes the driver — dry-run variants excluded.

    Static read of the Makefile, deliberately: resolving these with `make -n` would
    recurse into `loop`'s sub-make and grade `run` a second time under another name.
    """
    targets: dict[str, list[str]] = {}
    current = None
    for line in MAKEFILE.read_text().splitlines():
        if line.startswith("\t"):
            if current:
                targets[current].append(line)
            continue
        m = _TARGET.match(line)
        current = m.group(1) if m else None
        if current:
            targets.setdefault(current, [])

    found = []
    for name, recipe in targets.items():
        if not any(_INVOKES_DRIVER.match(line) for line in recipe):
            continue
        if "--dry-run" in " ".join(recipe):
            continue
        found.append(name)
    return sorted(found)


def _emitted(target: str, *make_args: str) -> str:
    """The command line `target` would run, whitespace-normalised.

    `make -n` preserves the recipe's backslash continuations and leading tabs, so a
    naive substring match against the raw text is position-dependent.
    """
    proc = subprocess.run(
        ["make", "-n", target, *make_args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return " ".join(proc.stdout.split())


def test_discovery_is_not_vacuous():
    """The guard on C1 and C2: an empty target list would pass them both trivially.

    Not a criterion — it grades this file's own parser, not the Makefile. It is here
    because a regex that silently stops matching turns the two real checks green.
    """
    targets = _driver_targets()
    assert targets, f"no driver-invoking targets found in {MAKEFILE}; parser is broken"
    for expected in ("run", "run-self"):
        assert expected in targets, f"`{expected}` missing from discovered: {targets}"
    for reader in ("driver-check", "skill-readonly"):
        assert reader not in targets, (
            f"`{reader}` only greps the driver's path; discovery is over-matching and "
            "C1 will fail on a target ISSUE= has no meaning for"
        )


@pytest.mark.parametrize("target", _driver_targets())
def test_c1_issue_is_passed_through(target):
    """C1 — `make <target> ISSUE=n` passes `--issue n` to the driver."""
    assert "--issue 704" in _emitted(target, "ISSUE=704"), (
        f"`make {target} ISSUE=704` does not pass `--issue 704` to the driver. "
        "The variable reads as honored and is not; see issue #71."
    )


@pytest.mark.parametrize("target", _driver_targets())
def test_c2_unset_issue_changes_nothing(target):
    """C2 — an unset ISSUE emits no `--issue` at all.

    The control for C1: hardcoding `--issue` would satisfy C1 and pin every
    unattended run to a single issue.
    """
    assert "--issue" not in _emitted(target), (
        f"`make {target}` emits `--issue` with ISSUE unset, so selection is bypassed "
        "on every run."
    )
