"""A dry run must target what the real run would target.

`dry-run-self` passed neither `--repo-path` nor `--skill-dir`, so it fell back to
`REPO_PATH` from the environment — `~/devel/decafclaw` — while `run-self` passed
`--repo-path $(CURDIR)`. The two targets therefore inspected *different working
trees*, which is the one thing a dry run must not do: its whole job is to answer
"what would the real run do?" and it was answering for somewhere else.

Same family as #71 (`ISSUE=` honored by `run-self` and silently not by `run`) and
#60: a pair of hand-maintained recipes drifting apart with no error, only a wrong
answer that looks right.

Following `test_run_issue_flag.py` on both counts:

**These checks discover their own pairs.** A target named `dry-run<suffix>` is
graded against `run<suffix>`. Add `dry-run-staging` and it is graded with no edit
here.

**They derive, they never restate.** Both sides come from `make -n`, so the
assertion compares what the Makefile says today against what it says today — never
against a copy of it living in this file.
"""

import re
import shlex
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = REPO_ROOT / "Makefile"

_TARGET = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*)\s*:(?!=)")

#: Flags that decide *what* a pass looks at. A dry run may legitimately differ on
#: how much it would spend (`--max-budget-usd`) or how many issues it would take
#: (`--max-issues`); it may not differ on which repo, tree, skill or board.
TARGETING_FLAGS = ("--repo", "--board", "--skill-dir", "--repo-path")

#: Valueless flags that still change what is inspected.
TARGETING_SWITCHES = ("--allow-nested-skill-dir",)


def _targets() -> list[str]:
    return [m.group(1) for line in MAKEFILE.read_text().splitlines() if (m := _TARGET.match(line))]


def dry_run_pairs() -> list[tuple[str, str]]:
    """(dry, real) for every `dry-run*` target that has a `run*` counterpart."""
    names = set(_targets())
    pairs = []
    for name in sorted(names):
        if not name.startswith("dry-run"):
            continue
        counterpart = "run" + name[len("dry-run") :]
        if counterpart in names:
            pairs.append((name, counterpart))
    return pairs


def _expanded(target: str) -> list[str]:
    res = subprocess.run(
        ["make", "--no-print-directory", "-n", target],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"`make -n {target}` failed:\n{res.stderr}"
    # `make -n` echoes the recipe with its line continuations intact; rejoin them so
    # a multi-line invocation is one command again.
    stdout = res.stdout.replace("\\\n", " ")
    for line in stdout.splitlines():
        if "$(DRIVER)" in line or "agent-session-driver" in line or "/driver/" in line:
            return shlex.split(line.lstrip("@").strip())
    raise AssertionError(f"no driver invocation found in `make -n {target}`:\n{stdout}")


def _flags(argv: list[str]) -> dict[str, str]:
    out = {}
    for flag in TARGETING_FLAGS:
        if flag in argv:
            out[flag] = argv[argv.index(flag) + 1]
    for switch in TARGETING_SWITCHES:
        if switch in argv:
            out[switch] = "present"
    return out


def test_there_is_at_least_one_pair_to_grade():
    assert dry_run_pairs(), "no dry-run/run pairs found; this suite would pass vacuously"


@pytest.mark.parametrize("dry,real", dry_run_pairs(), ids=lambda v: v)
def test_a_dry_run_targets_what_the_real_run_targets(dry: str, real: str):
    dry_flags = _flags(_expanded(dry))
    real_flags = _flags(_expanded(real))

    assert dry_flags == real_flags, (
        f"`make {dry}` and `make {real}` disagree about what they operate on, so the dry run "
        f"answers 'what would happen?' for the wrong target.\n"
        f"  {dry}:  {dry_flags}\n"
        f"  {real}: {real_flags}"
    )


@pytest.mark.parametrize("dry,real", dry_run_pairs(), ids=lambda v: v)
def test_the_dry_run_is_actually_dry_and_the_real_one_is_not(dry: str, real: str):
    """The control. Without it, parity is satisfiable by making both sides dry, or
    both sides live — the second of which would spend money from `make dry-run`."""
    assert "--dry-run" in _expanded(dry)
    assert "--dry-run" not in _expanded(real)
