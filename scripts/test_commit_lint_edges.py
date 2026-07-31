"""Edge-case regressions for scripts/commit_lint.py -- issue #47.

Deliberately a **separate file** from `scripts/test_commit_lint.py`. That one is
the frozen acceptance check for criteria C1 and C2, authored before the detector
existed and read-only from Phase 1 onward; adding to it would be the implementer
editing its own oracle. These are the implementer's own slice tests, which is a
different thing and freely editable.

Every case below is a real defect an independent verifier found in the first
draft by attacking it, not a hypothetical. All three passed the frozen suite --
which is the point worth recording: a frozen check that discriminates is not the
same as a frozen check that is exhaustive, and the adversarial read is what
found the gap between them.

Two of the three were **false positives on legitimate commits**, which is the
failure this detector cannot afford. `findings.md` says it plainly: a false
positive trains the operator to wave the mechanism through. A detector that
reports a commit whose closing reference was perfectly ordinary gets switched
off, and then the real one goes through.

*(These fixtures contain literal closing keywords. Safe in a file -- GitHub
reads commit messages and PR bodies, not source. The issue numbers are
five-digit and do not exist.)*
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import commit_lint  # noqa: E402


# --- defect 1: a doubled backtick run was not recognised as quoting ----------

def test_a_double_backtick_span_is_reported():
    """``Closes #N`` quotes just as well as `Closes #N`, and GitHub ignores
    both. The first draft matched spans as `` `[^`]*` ``, so the *empty* span
    between each doubled pair matched and the keyword ended up between two
    spans rather than inside one -- a silent miss."""
    message = "subject\n\nthe payload is ``Closes #99101`` verbatim\n"
    assert commit_lint.scan_message(message) == [(3, "Closes #99101")]


@pytest.mark.parametrize("ticks", ["`", "``", "```", "````"])
def test_a_run_of_any_length_delimits_a_span(ticks):
    message = f"subject\n\nthe payload is {ticks}Closes #99102{ticks} verbatim\n"
    assert commit_lint.scan_message(message) == [(3, "Closes #99102")]


# --- defect 2: an inline triple-backtick span read as a fence opener --------

def test_a_triple_backtick_span_closed_on_the_same_line_is_reported():
    """```Closes #N``` is an inline span, not a fence: a fence delimiter's info
    string cannot contain backticks. The first draft read it as an opener,
    skipped the line unscanned, AND left fence state flipped."""
    message = "subject\n\n```Closes #99103``` is the fixture\n"
    assert commit_lint.scan_message(message) == [(3, "Closes #99103")]


def test_an_inline_triple_span_does_not_flip_fence_state():
    """The downstream half of defect 2, and the worse half: having mistaken the
    span for an opener, the detector treated the rest of the body as fenced and
    reported the commit's own genuine trailer while missing the quoted one."""
    message = (
        "subject\n\n```Closes #99103``` is the fixture\n\nCloses #99104\n"
    )
    assert commit_lint.scan_message(message) == [(3, "Closes #99103")]


def test_a_fence_openers_info_string_is_still_scanned():
    """The converse hole the stricter fence pattern could have opened: three
    backticks followed by a closing keyword and no further backticks IS a
    well-formed fence opener, and its info string is still literal text GitHub
    will act on."""
    message = "subject\n\n```Closes #99105\nsome payload\n```\n"
    assert commit_lint.scan_message(message) == [(3, "Closes #99105")]


# --- defect 3: an unclosed fence swallowed the commit's own trailer ---------

def test_an_unclosed_fence_does_not_report_a_genuine_trailer():
    """The most damaging of the three. Pasting a log after three backticks and
    not closing them is an ordinary thing to do; the first draft then treated
    every following line as fenced and reported the perfectly genuine
    `Closes #N` at the bottom."""
    message = "subject\n\n```\nsome log output\n\nCloses #99106\n"
    assert commit_lint.scan_message(message) == []


def test_a_closed_fence_still_reports_what_is_inside_it():
    """The guard on the fix above: making an unclosed fence inert must not make
    a closed one inert too."""
    message = "subject\n\n```\nCloses #99107\n```\n\nCloses #99108\n"
    assert commit_lint.scan_message(message) == [(4, "Closes #99107")]


# --- the same failure shape, in the inline case -----------------------------

def test_one_stray_backtick_does_not_quote_the_rest_of_the_line():
    """Parity's characteristic false positive, at line scope. An unpaired run
    opens nothing."""
    message = "subject\n\nCloses #99109 after touching `driver/gate.py\n"
    assert commit_lint.scan_message(message) == []


def test_a_genuine_trailer_survives_backticks_elsewhere_on_its_line():
    message = "subject\n\nCloses #99110 after touching `driver/gate.py`\n"
    assert commit_lint.scan_message(message) == []


def test_a_stray_backtick_does_not_leak_onto_a_later_line():
    """Line scoping, stated as a test rather than as a comment."""
    message = "subject\n\nan unclosed `span here\n\nCloses #99111\n"
    assert commit_lint.scan_message(message) == []


# --- documented non-features, pinned so a later widening is deliberate ------

def test_a_four_space_indented_block_is_not_treated_as_quoting():
    message = "subject\n\n    Closes #99112\n"
    assert commit_lint.scan_message(message) == []


def test_a_tilde_fence_is_not_treated_as_quoting():
    message = "subject\n\n~~~\nCloses #99113\n~~~\n"
    assert commit_lint.scan_message(message) == []
