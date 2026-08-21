"""Acceptance tests for scripts/guard_lint.py -- issue #68."""

from __future__ import annotations

import json

from agent_sessions.scripts import guard_lint


def test_pinned_count_guard_detected():
    text = "## Regression guards\n- GUARD: `make test` -> 3234 passed\n"
    matches = guard_lint.scan_text(text)
    assert len(matches) == 1
    assert matches[0][0] == 2
    assert "3234 passed" in matches[0][1]


def test_invariant_guard_clean():
    text = "## Regression guards\n- GUARD: `make test` -- no test lost, newly skipped, or newly failing.\n"
    matches = guard_lint.scan_text(text)
    assert matches == []


def test_json_scanning(monkeypatch, capsys):
    guard_lint.failures.clear()
    json_data = '[{"body": "## Regression guards\\n- 34 passed\\n"}]'
    monkeypatch.setattr("sys.stdin", type("Stdin", (), {"isatty": lambda *a, **kw: False, "read": lambda *a, **kw: json_data})())

    ret = guard_lint.main([])
    assert ret == 1
    captured = capsys.readouterr()
    assert "34 passed" in captured.out


# --- C10: a null must not render as a positive --------------------------------
#
# `make guard-lint` piped `gh issue list --json body` with no `--limit`, so `gh`
# returned its default 30 newest issues and the detector printed "no pinned test
# count guards found" -- a clean bill over an arbitrary slice of the backlog, in a
# repo whose whole thesis is that this must not happen. `guard_lint` had no way to
# know how many records it was handed, or how many it was denied.
#
# `board_audit.bounded_records` already solved this shape: pass the limit in, and
# raise *at* the limit rather than below it, because a full page is exactly when you
# cannot tell truncation from coincidence.


def _stdin(monkeypatch, payload: str):
    monkeypatch.setattr(
        "sys.stdin",
        type("Stdin", (), {"isatty": lambda *a, **kw: False, "read": lambda *a, **kw: payload})(),
    )


def test_a_full_page_of_records_fails_rather_than_reporting_clean(monkeypatch, capsys):
    """C1. At the limit, the detector cannot know what it did not see."""
    guard_lint.failures.clear()
    payload = json.dumps([{"number": n, "body": "clean"} for n in range(1, 6)])
    _stdin(monkeypatch, payload)
    monkeypatch.setattr("sys.argv", ["guard_lint", "--limit", "5"])

    ret = guard_lint.main()

    assert ret == 2, "a possibly-truncated scan is neither a pass nor a lint failure"
    out = capsys.readouterr().out
    assert "truncat" in out.lower()
    assert "no pinned test count guards" not in out


def test_a_partial_page_reports_how_many_bodies_it_scanned(monkeypatch, capsys):
    """C2. The count is what makes an empty scan legible as empty."""
    guard_lint.failures.clear()
    payload = json.dumps([{"number": n, "body": "clean"} for n in range(1, 4)])
    _stdin(monkeypatch, payload)
    monkeypatch.setattr("sys.argv", ["guard_lint", "--limit", "500"])

    ret = guard_lint.main()

    assert ret == 0
    assert "3" in capsys.readouterr().out


def test_an_empty_result_says_so_instead_of_passing_silently(monkeypatch, capsys):
    """C3. The exact shape C10 describes: nothing examined, reported as clean."""
    guard_lint.failures.clear()
    _stdin(monkeypatch, "[]")
    monkeypatch.setattr("sys.argv", ["guard_lint", "--limit", "500"])

    ret = guard_lint.main()

    out = capsys.readouterr().out
    assert ret == 0
    assert "0" in out, (
        "an empty scan must render as empty; 'no pinned test count guards found' "
        "over nothing is the null-as-positive this check exists for"
    )


def test_findings_are_labelled_with_the_real_issue_number(monkeypatch, capsys):
    """The old label was the array index, so `issue #1` meant "the newest issue"."""
    guard_lint.failures.clear()
    payload = json.dumps([{"number": 704, "body": "## Regression guards\n- 34 passed\n"}])
    _stdin(monkeypatch, payload)
    monkeypatch.setattr("sys.argv", ["guard_lint", "--limit", "500"])

    ret = guard_lint.main()

    assert ret == 1
    out = capsys.readouterr().out
    assert "#704" in out
    assert "#1" not in out
