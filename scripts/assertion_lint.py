#!/usr/bin/env python3
"""Detect presence-grep assertions in the bash fixture suites.

Why this exists
---------------
An assertion of the form::

    if grep -q 'trap cleanup EXIT INT TERM' "$DRIVER"; then
      ok "cleanup trap installed on EXIT/INT/TERM"

passes if the literal appears **anywhere** in the driver -- including inside a
comment. `findings.md` (defect class 5) calls that *"a spelling check, not a
test"*: it grades the spelling of the subject rather than its behaviour, and a
comment describing the behaviour satisfies it just as well as the behaviour.

Eight of them shipped in `driver/test-driver.sh`, and the warning against them
sat **in a comment** at `test-driver.sh:177-179` and `test-park-state.sh:19` --
next to the thing it warned about, for two days, without preventing it. That is
this project's most-repeated lesson: an exhortation measures away, a detector
does not (`findings.md` defect class 4, and CLAUDE.md's rationale for
`docs_check.py`). So this is a detector.

The rule
--------
A line is reported iff it lies in a file matching `SCOPE` and `grep -q`,
`grep -qE` or `grep -qF` appears on it with **no `#` earlier on the line**.

`-q` is the whole tell. It discards the match and yields only an exit status, so
the assertion can mean nothing except "the literal is present somewhere". `-c`
produces a *number*, and a number gets compared against an expectation -- delete
the code being counted and the comparison flips. That is why::

    ACTUAL="$(grep -cE '^parked_numbers\\(\\)' "$DRIVER")"
    check "the driver still defines its helper" "1" "$ACTUAL"

is fine and the `-q` form is not. The fix for a presence-grep is to convert it to
one of those, or better, to assert the behaviour through the shipped code.

Two deliberate non-features, both for the same reason -- a false positive trains
the operator to wave the mechanism through (`findings.md`):

  * **The grep's target is not inspected.** Matching on `-q` alone is mechanical;
    deciding what a grep "really means" from its operand is the precision problem
    that got issue #12's general check-linter declined on measured data.
  * **No carve-out for `grep -q` reading stdin** (`| grep -q`, `<<<`), even though
    grepping captured *output* is a legitimate behavioural assertion. Measured on
    this branch: neither suite contains one. An untested exception would be
    speculation and a standing bypass; `grep -c ... = 1` covers the case if it
    ever arises, and widening the rule is a human's call.

Scope
-----
`driver/test-*.sh` only. The `Makefile`'s own `grep -qF` guards are excluded on
purpose: `skill-readonly` asserts that a deny rule is *literally present* in the
driver, so there presence IS the property being tested -- unlike a test suite,
where a presence-grep stands in for behaviour. Flagging it would be a false
positive. Widening the scope is a separate call for a human, not a drift to
discover in a diff (issue #28, first design decision).

Stdlib only, to match `docs_check.py` and stay portable to a GHA runner.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: The linted files, as a glob relative to ROOT. See "Scope" above.
SCOPE = "driver/test-*.sh"

#: `grep -q`, `-qE` or `-qF` with no `#` earlier on the line. `[^#]*` cannot
#: consume a `#`, so a commented-out grep can never match -- that false positive
#: is the one that caught issue #28's own author while measuring the defect.
PRESENCE_GREP = re.compile(r"^[^#]*\bgrep\s+-q[EF]?\b")

failures: list[str] = []


def scan_file(path: Path) -> list[tuple[int, str]]:
    """Every presence-grep assertion in one file.

    Returns `(1-based line number, the source line minus its trailing newline)`
    for each offending line, in file order.

    Takes an explicit path and deliberately does **not** consult `ROOT`, so a
    caller can scan a real repo file while `ROOT` points somewhere else.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    return [
        (n, line)
        for n, line in enumerate(text.splitlines(), start=1)
        if PRESENCE_GREP.search(line)
    ]


def lint_files() -> None:
    """Scan every in-scope file under `ROOT`, appending to `failures`."""
    for path in sorted(ROOT.glob(SCOPE)):
        rel = path.relative_to(ROOT)
        for lineno, line in scan_file(path):
            failures.append(f"{rel}:{lineno}: presence-grep assertion: {line.strip()}")


def main() -> int:
    lint_files()

    scanned = sorted(p.relative_to(ROOT) for p in ROOT.glob(SCOPE))
    if not scanned:
        # A null must not render as a positive -- this project's most-repeated
        # lesson. Zero files scanned is a broken scope, not a clean bill.
        print(f"FAIL: assertion-lint matched no files for scope {SCOPE!r}")
        return 1

    for f in failures:
        print(f"  FAIL  {f}")

    if failures:
        print(
            f"\nassertion-lint: {len(failures)} presence-grep assertion(s). "
            f"These pass when the literal appears in a COMMENT -- a spelling check, "
            f"not a test. Compare a `grep -c` count against an expectation, or "
            f"assert the behaviour through the shipped code. See issue #28."
        )
        return 1

    print(
        f"assertion-lint: no presence-grep assertions in "
        f"{len(scanned)} file(s) matching {SCOPE}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
