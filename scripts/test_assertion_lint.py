"""Acceptance test for scripts/assertion_lint.py -- issue #28's CRITERION C2.

    GIVEN a bash fixture whose assertion is `grep -q 'literal' "$F"`, WHEN the
    detector runs over it, THEN it SHALL report that line; AND GIVEN a fixture
    whose assertion compares `grep -cE '^literal\\(\\)' "$F"` against an expected
    count, it SHALL NOT report it; AND GIVEN `driver/test-park-state.sh` it SHALL
    report nothing.

Written BEFORE the detector exists, so it is the interface definition rather than
a description of an implementation. The module under test must provide:

    ROOT: Path                                  -- repo root, monkeypatchable
    failures: list[str]                         -- module-level accumulator
    scan_file(path: Path) -> list[tuple[int, str]]
        every presence-grep assertion in one file, as (1-based line number,
        the source line with its trailing newline stripped and nothing else
        removed -- leading whitespace preserved)
    lint_files() -> None                        -- walk ROOT's in-scope files,
                                                   append to `failures`

Shape copied from `scripts/test_docs_check.py`: it **imports** the module rather
than restating its logic (a test that re-implements the detector grades a
replica -- the defect issue #9 removed), and each test builds a throwaway suite
in pytest's `tmp_path` so nothing depends on the repo's real fixture files.

With one deliberate exception. The third conjunct names a **real file**, and that
is the point of it: `driver/test-park-state.sh` has zero presence-grep assertions
today, so it is a negative fixture that a detector flagging everything cannot
pass -- unlike a synthetic clean file, which it could. That test reads the live
repo path on purpose. It is unaffected by the autouse `isolate` fixture because
`scan_file` takes an explicit path and does not consult `ROOT`.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from agent_sessions.scripts import assertion_lint

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    """Point the linter at a scratch tree and reset its module-level accumulator."""
    monkeypatch.setattr(assertion_lint, "ROOT", tmp_path)
    assertion_lint.failures.clear()
    return tmp_path


def write(root: Path, rel: str, body: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    return p


# --- fixtures, shaped like the real suites ---------------------------------
#
# Raw strings throughout: these carry bash backslash escapes (`\|`, `\(`) that
# Python would otherwise read as its own.

# The defect, as it actually appears at driver/test-driver.sh:255-259. The
# assertion passes if the literal appears anywhere in the driver -- including in
# a comment -- which findings.md calls "a spelling check, not a test".
PRESENCE_GREP = r"""#!/usr/bin/env bash
HERE="$(cd "$(dirname "$0")" && pwd)"
DRIVER="$HERE/agent-session-driver.sh"

if grep -q 'trap cleanup EXIT INT TERM' "$DRIVER"; then
  ok "cleanup trap installed on EXIT/INT/TERM"
else
  bad "cleanup trap" "trap cleanup EXIT INT TERM" "absent"
fi
"""
PRESENCE_GREP_LINE = 5
PRESENCE_GREP_TEXT = """if grep -q 'trap cleanup EXIT INT TERM' "$DRIVER"; then"""

# The `-qE` pair from driver/test-driver.sh:244-245, plus the `-qF` spelling the
# Makefile uses. C1's frozen check is written `grep -q[EF]?`, so the variants are
# the same defect class, not a different one.
PRESENCE_GREP_VARIANTS = r"""#!/usr/bin/env bash
DRIVER="$HERE/agent-session-driver.sh"
if grep -qE '^ *parked\|failed\|incomplete\|no-gate\)' "$DRIVER" && \
   ! grep -qE '^ *parked\|failed\|incomplete\|no-gate\|budget-exhausted\)' "$DRIVER"; then
  ok "budget-exhausted is excluded from the park list"
else
  bad "budget-exhausted park status" "excluded" "included"
fi
grep -qF 'refusing to start a second run while an orphan is live' "$DRIVER" \
  && ok "live-orphan guard" || bad "live-orphan guard" "startup refuses" "absent"
"""

# A count comparison, the second conjunct's shape: the grep produces a value that
# is checked against an expectation, so deleting the thing counted flips the
# assertion. Not a presence check.
COUNT_COMPARISON = r"""#!/usr/bin/env bash
DRIVER="$HERE/agent-session-driver.sh"
EXPECTED_HELPERS=3
ACTUAL="$(grep -cE '^parked_numbers\(\)|^has_success_result\(\)|^abspath\(\)' "$DRIVER")"
check "the driver still defines its three helpers" "$EXPECTED_HELPERS" "$ACTUAL"
"""

# The false positive that caught the author of issue #28 during intake: a first
# probe returned 9 because it matched the *comment* at test-driver.sh:177 that
# describes the trap. Inert content is not an assertion.
COMMENT_ONLY = r"""#!/usr/bin/env bash
# These two used to be `grep -q "<literal>" "$DRIVER"` -- which passes if the
# string appears anywhere, comments included. findings.md calls that "a spelling
# check, not a test". Now they assert behaviour through the shipped parser.
DRIVER="$HERE/agent-session-driver.sh"
check "unparseable sha warns instead of reading as current" "1" "$(_warn_count "$CI_ROW")"
  # NO GREPPING THE SUBJECT FOR A LITERAL:
  #   grep -q 'trap cleanup EXIT INT TERM' "$DRIVER"
"""


# --- conjunct 1: the presence grep is reported ------------------------------

def test_presence_grep_assertion_is_reported(isolate):
    f = write(isolate, "driver/test_example.py", PRESENCE_GREP)
    assert assertion_lint.scan_file(f) == [(PRESENCE_GREP_LINE, PRESENCE_GREP_TEXT)]


def test_every_presence_grep_variant_is_reported(isolate):
    """-qE and -qF are the same defect, and every offending line is reported."""
    f = write(isolate, "driver/test_example.py", PRESENCE_GREP_VARIANTS)
    assert [n for n, _ in assertion_lint.scan_file(f)] == [3, 4, 9]


# --- conjunct 2: a count comparison is not reported -------------------------

def test_count_comparison_is_not_reported(isolate):
    f = write(isolate, "driver/test_example.py", COUNT_COMPARISON)
    assert assertion_lint.scan_file(f) == []


# --- conjunct 3: the real driver/test-park-state.sh is clean ----------------

def test_real_park_state_suite_reports_nothing():
    """Deliberately the live file, not a copy: a detector that flags everything
    passes a synthetic clean fixture, and this one it cannot."""
    target = REPO_ROOT / "driver" / "test_park_state.py"
    assert target.exists(), f"negative fixture is missing: {target}"
    assert assertion_lint.scan_file(target) == []


# --- the false positive that bit the issue's own author ---------------------

def test_a_comment_describing_a_presence_grep_is_not_reported(isolate):
    f = write(isolate, "driver/test_example.py", COMMENT_ONLY)
    assert assertion_lint.scan_file(f) == []


# --- scope: driver/test_*.py, and the Makefile is out of it -----------------

def test_lint_files_reports_the_offending_file_and_line(isolate):
    write(isolate, "driver/test_example.py", PRESENCE_GREP)
    assertion_lint.lint_files()
    assert len(assertion_lint.failures) == 1
    assert "driver/test_example.py" in assertion_lint.failures[0]
    assert str(PRESENCE_GREP_LINE) in assertion_lint.failures[0]


def test_files_outside_the_declared_scope_are_not_linted(isolate):
    """Scope is `driver/test-*.sh`. The Makefile's `grep -qF` presence checks are
    legitimate -- `skill-readonly` asserts a deny rule is literally present, so
    presence IS the property -- and flagging them would be a false positive."""
    write(isolate, "Makefile", PRESENCE_GREP)
    write(isolate, "driver/agent-session-driver.sh", PRESENCE_GREP)
    assertion_lint.lint_files()
    assert assertion_lint.failures == []
