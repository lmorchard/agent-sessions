"""Tests for scripts/docs_check.py.

These **import** the module rather than restating its logic — the same reason
`driver/test_gate.py` exists. The detector was mutation-tested by hand when it was
written (break a link, split a table, insert a stale count: each produced exactly
one failure), but **a hand mutation-test does not persist**, which is precisely the
gap issue #9 was about. These make it repeatable.

Each test builds a throwaway docs tree in `tmp_path` and points the module at it,
so nothing here depends on the repo's real documentation — a test that asserted
against the live docs would fail every time a doc legitimately changed.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import docs_check  # noqa: E402


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    """Point the checker at a scratch tree and reset its module-level accumulators."""
    monkeypatch.setattr(docs_check, "ROOT", tmp_path)
    docs_check.failures.clear()
    docs_check.skips.clear()
    return tmp_path


def write(root: Path, rel: str, body: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    return p


# --- links -----------------------------------------------------------------

def test_resolving_link_passes(isolate):
    write(isolate, "docs/a.md", "see [b](b.md)")
    write(isolate, "docs/b.md", "hi")
    docs_check.check_links()
    assert docs_check.failures == []


def test_dead_link_fails(isolate):
    write(isolate, "docs/a.md", "see [gone](nope.md)")
    docs_check.check_links()
    assert len(docs_check.failures) == 1
    assert "nope.md" in docs_check.failures[0]


def test_link_up_a_level_resolves(isolate):
    """The case that broke twice while relocating docs into archive/."""
    write(isolate, "docs/archive/a.md", "see [design](../design.md)")
    write(isolate, "docs/design.md", "hi")
    docs_check.check_links()
    assert docs_check.failures == []


def test_external_and_anchor_links_are_ignored(isolate):
    write(isolate, "docs/a.md",
          "[x](https://example.invalid/y) [m](mailto:a@b.c) [s](a.md#frag)")
    write(isolate, "docs/a.md", (isolate / "docs/a.md").read_text())
    docs_check.check_links()
    assert docs_check.failures == []


# --- tables ----------------------------------------------------------------

GOOD_TABLE = "| A | B |\n|---|---|\n| 1 | 2 |\n"


def test_well_formed_table_passes(isolate):
    write(isolate, "docs/a.md", GOOD_TABLE)
    docs_check.check_tables()
    assert docs_check.failures == []


def test_table_split_by_prose_fails(isolate):
    """The findings.md shape: prose between rows orphans the ones after it."""
    write(isolate, "docs/a.md", GOOD_TABLE + "\nInterrupting prose.\n\n| 3 | 4 |\n")
    docs_check.check_tables()
    assert len(docs_check.failures) == 1
    assert "header separator" in docs_check.failures[0]


def test_a_stray_blank_line_between_rows_fails(isolate):
    """The exact regression that survived two readings of the file."""
    write(isolate, "docs/a.md", GOOD_TABLE + "\n| 3 | 4 |\n")
    docs_check.check_tables()
    assert len(docs_check.failures) == 1


def test_pipes_inside_a_code_fence_are_not_a_table(isolate):
    write(isolate, "docs/a.md", "```\n| not | a | table |\n```\n")
    docs_check.check_tables()
    assert docs_check.failures == []


# --- derivable counts ------------------------------------------------------

def test_matching_count_passes(isolate, monkeypatch):
    monkeypatch.setattr(docs_check, "live_bash_assertions", lambda: 61)
    write(isolate, "docs/a.md", "the 61-assertion fixture suite")
    docs_check.check_counts()
    assert docs_check.failures == []


def test_stale_count_fails(isolate, monkeypatch):
    """The '49-assertion' class that sat stale in CLAUDE.md."""
    monkeypatch.setattr(docs_check, "live_bash_assertions", lambda: 61)
    write(isolate, "docs/a.md", "the 49-assertion fixture suite")
    docs_check.check_counts()
    assert len(docs_check.failures) == 1
    assert "49" in docs_check.failures[0] and "61" in docs_check.failures[0]


def test_frozen_dirs_are_exempt_from_freshness(isolate, monkeypatch):
    """archive/ and dev-sessions/ are historical records, not maintained claims."""
    monkeypatch.setattr(docs_check, "live_bash_assertions", lambda: 61)
    write(isolate, "docs/archive/old.md", "the 21-assertion fixture suite")
    write(isolate, "docs/dev-sessions/s/notes.md", "the 47-assertion fixture suite")
    docs_check.check_counts()
    assert docs_check.failures == []


def test_unavailable_suite_is_a_skip_not_a_pass(isolate, monkeypatch):
    """A null must never render as a positive — including in the checker itself."""
    monkeypatch.setattr(docs_check, "live_bash_assertions", lambda: None)
    write(isolate, "docs/a.md", "the 49-assertion fixture suite")
    docs_check.check_counts()
    assert docs_check.failures == []          # cannot judge, so does not fail...
    assert len(docs_check.skips) == 1         # ...but says so out loud
    assert "NOT verified" in docs_check.skips[0]
