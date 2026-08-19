"""Acceptance tests for scripts/guard_lint.py -- issue #68."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from agent_sessions.scripts import guard_lint  # noqa: E402


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

    ret = guard_lint.main()
    assert ret == 1
    captured = capsys.readouterr()
    assert "34 passed" in captured.out
