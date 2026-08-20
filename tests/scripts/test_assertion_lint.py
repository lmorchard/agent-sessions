"""Acceptance test for the shipping assertion linter -- issue #28's CRITERION C2.

    GIVEN a bash fixture whose assertion is `grep -q 'literal' "$F"`, WHEN the
    detector runs over it, THEN it SHALL report that line; AND GIVEN a fixture
    whose assertion compares `grep -cE '^literal\\(\\)' "$F"` against an expected
    count, it SHALL NOT report it; AND GIVEN `driver/test_park_state.py` it SHALL
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

Shape copied from `scripts/test_docs_check.py`: it **imports** the shipping module
rather than restating its logic (a test that re-implements the detector grades a
replica -- the defect issue #9 removed), and each test builds a throwaway suite in
pytest's `tmp_path` so nothing depends on the repo's real fixture files.

With one deliberate exception. The third conjunct names a **real file**, and that
is the point of it: `driver/test_park_state.py` has zero presence-grep assertions
today, so it is a negative fixture that a detector flagging everything cannot
pass -- unlike a synthetic clean file, which it could. That test reads the live
repo path on purpose. It is unaffected by the autouse `isolate` fixture because
`scan_file` takes an explicit path and does not consult `ROOT`.
"""

from pathlib import Path

import pytest

from agent_sessions.scripts import assertion_lint

REPO_ROOT = Path(__file__).resolve().parents[2]


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

# The defect, as it appeared in the former Bash driver fixture suite. The
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

# Historical `-qE` and `-qF` variants. C1's frozen check is written
# `grep -q[EF]?`, so they are the same defect class, not a different one.
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
# probe also matched the historical comment describing the trap. Inert content
# is not an assertion.
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
    f = write(isolate, "tests/driver/test_example.py", PRESENCE_GREP)
    assert assertion_lint.scan_file(f) == [(PRESENCE_GREP_LINE, PRESENCE_GREP_TEXT)]


def test_every_presence_grep_variant_is_reported(isolate):
    """-qE and -qF are the same defect, and every offending line is reported."""
    f = write(isolate, "tests/driver/test_example.py", PRESENCE_GREP_VARIANTS)
    assert [n for n, _ in assertion_lint.scan_file(f)] == [3, 4, 9]


# --- conjunct 2: a count comparison is not reported -------------------------

def test_count_comparison_is_not_reported(isolate):
    f = write(isolate, "tests/driver/test_example.py", COUNT_COMPARISON)
    assert assertion_lint.scan_file(f) == []


# --- conjunct 3: the real tests/driver/test_park_state.py is clean ----------------

def test_real_park_state_suite_reports_nothing():
    """Deliberately the live file, not a copy: a detector that flags everything
    passes a synthetic clean fixture, and this one it cannot."""
    target = REPO_ROOT / "tests" / "driver" / "test_park_state.py"
    assert target.exists(), f"negative fixture is missing: {target}"
    assert assertion_lint.scan_file(target) == []


# --- the false positive that bit the issue's own author ---------------------

def test_a_comment_describing_a_presence_grep_is_not_reported(isolate):
    f = write(isolate, "tests/driver/test_example.py", COMMENT_ONLY)
    assert assertion_lint.scan_file(f) == []


# --- scope: tests/driver/test_*.py, and the Makefile is out of it -----------------

def test_lint_files_reports_the_offending_file_and_line(isolate):
    write(isolate, "tests/driver/test_example.py", PRESENCE_GREP)
    assertion_lint.lint_files()
    assert len(assertion_lint.failures) == 1
    assert "tests/driver/test_example.py" in assertion_lint.failures[0]
    assert str(PRESENCE_GREP_LINE) in assertion_lint.failures[0]


def test_files_outside_the_declared_scope_are_not_linted(isolate):
    """Scope is `tests/driver/test_*.py`; non-test files remain outside it."""
    write(isolate, "Makefile", PRESENCE_GREP)
    write(isolate, "driver/agent-session-driver.sh", PRESENCE_GREP)
    assertion_lint.lint_files()
    assert assertion_lint.failures == []


# --- the same defect, in the language this repo now writes tests in -----------
#
# The `grep -q` rule above guards an idiom that no longer occurs. The Bash fixture
# suites it was written for were deleted by the 2026-08-09 conversion, and measured on
# this branch there is **not one occurrence anywhere under `tests/`** outside this
# file's own fixtures -- nor can there be, because Python tests do not shell out to
# grep. A detector reporting a clean bill over a defect class that cannot reach it is
# `findings.md` defect class 6, inside a detector.
#
# The class itself did not go away; it changed shape:
#
#     assert "some literal" in SOME_CHECKED_IN_FILE.read_text()
#
# which passes when the literal appears in a comment, exactly as the grep did. Two live
# instances existed when this was written, both introduced during #261's own audit --
# by the session auditing for them, hours apart.
#
# **Two stages, and the first is what makes it usable.** X1 proposed tracing the
# assertion's right-hand side back to a `read_text()` call; measured, that flagged ten
# assertions of which one was real, because assertions on *generated* output -- a prompt
# a run wrote, a rendered diagram -- look identical. Filtering by whether the module
# reads a **checked-in** artifact first drops every one of those in a single move.

SOURCE_ASSERTION = '''
from pathlib import Path


def test_the_recipe_uses_the_flag():
    text = (REPO_ROOT / "Makefile").read_text()
    assert "--dist loadgroup" in text
'''

GENERATED_OUTPUT_ASSERTION = '''
import subprocess


def test_the_plan_carries_the_flag(tmp_path):
    out = subprocess.run(["make", "-n", "check"], capture_output=True, text=True).stdout
    assert "--dist loadgroup" in out
'''

FIXTURE_STRING = '''
SAMPLE = """
def test_something():
    assert "--dist loadgroup" in text
"""


def test_the_detector_reports_it():
    assert scan(SAMPLE) == [3]
'''


def test_a_literal_asserted_against_checked_in_text_is_reported(isolate):
    """C1. The live shape, and the one that had two instances."""
    f = write(isolate, "tests/scripts/test_example.py", SOURCE_ASSERTION)
    found = assertion_lint.scan_source_assertions(f)

    # Line derived from the fixture rather than counted by hand -- a hardcoded number
    # here is the same staleness trap the rest of this audit has been removing.
    expected = SOURCE_ASSERTION.split("\n").index('    assert "--dist loadgroup" in text') + 1
    assert [n for n, _ in found] == [expected], found
    assert found[0][1] == "'--dist loadgroup' in text"


def test_the_same_assertion_against_generated_output_is_not_reported(isolate):
    """C2. Stage one is the whole reason this is usable rather than noisy.

    Asserting that a command's output contains a string is an ordinary behavioural
    assertion. Without this filter the rule flags nine of those for every real
    instance, which is the measurement that sent X1 back to Les.
    """
    f = write(isolate, "tests/scripts/test_example.py", GENERATED_OUTPUT_ASSERTION)
    assert assertion_lint.scan_source_assertions(f) == []


def test_an_assertion_inside_a_fixture_string_is_not_reported(isolate):
    """C3. Why this rule needs no narrowed glob, where the `grep -q` rule did.

    `commit_lint.py` records that `assertion_lint` "had to solve the same self-matching
    problem by narrowing its glob" -- a detector whose fixtures contain the very idiom it
    matches cannot scan its own suite. That is a property of *textual* matching. An AST
    rule sees a fixture as a string constant and a real assertion as an `Assert` node, so
    it can scan every test file in the repo, including this one.
    """
    f = write(isolate, "tests/scripts/test_example.py", FIXTURE_STRING)
    assert assertion_lint.scan_source_assertions(f) == []


def test_a_non_literal_membership_test_is_not_reported(isolate):
    """C4. `assert name in text` is not a spelling check; the name could be anything."""
    body = SOURCE_ASSERTION.replace(
        'assert "--dist loadgroup" in text', "flag = compute()\n    assert flag in text"
    )
    f = write(isolate, "tests/scripts/test_example.py", body)
    assert assertion_lint.scan_source_assertions(f) == []


def test_the_live_suites_carry_no_source_text_assertion():
    """C5. The negative fixture, against the real tree rather than a synthetic one.

    A detector that flags everything passes a synthetic clean file; it cannot pass this.
    Two instances existed when the rule was written and were fixed with it.
    """
    offenders = []
    for pattern in assertion_lint.SOURCE_ASSERTION_SCOPE:
        for path in sorted(REPO_ROOT.glob(pattern)):
            for lineno, text in assertion_lint.scan_source_assertions(path):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {text}")
    assert not offenders, "\n".join(offenders)
