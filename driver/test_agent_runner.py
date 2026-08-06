"""Tests for driver/agent_runner.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import agent_runner  # noqa: E402


def test_parse_result_stream_claude(tmp_path: Path):
    raw = tmp_path / "stream.jsonl"
    events = [
        {"type": "init", "session_id": "ses_123"},
        {"type": "result", "subtype": "success", "session_id": "ses_123", "total_cost_usd": 1.25, "result": "Done successfully"},
        {"type": "error_during_execution", "total_cost_usd": 0.0}
    ]
    raw.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")

    res = agent_runner.parse_result_stream("claude", raw)
    assert res["final"] == "Done successfully"
    assert res["total_cost_usd"] == 1.25
    assert res["session_id"] == "ses_123"
    assert res["cost_known"] is True


def test_parse_result_stream_opencode(tmp_path: Path):
    raw = tmp_path / "opencode.jsonl"
    events = [
        {"type": "step_start", "sessionID": "ses_opencode_999"},
        {"type": "text", "sessionID": "ses_opencode_999", "part": {"type": "text", "text": "Hello "}},
        {"type": "text", "sessionID": "ses_opencode_999", "part": {"type": "text", "text": "World!"}},
        {"type": "step_finish", "sessionID": "ses_opencode_999", "part": {"type": "step-finish", "reason": "stop", "cost": 0.0042}}
    ]
    raw.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")

    res = agent_runner.parse_result_stream("opencode", raw)
    assert res["final"] == "Hello World!"
    assert res["total_cost_usd"] == 0.0042
    assert res["session_id"] == "ses_opencode_999"
    assert res["cost_known"] is True


def test_stream_has_events(tmp_path: Path):
    raw = tmp_path / "empty.jsonl"
    raw.write_text("", encoding="utf-8")
    assert agent_runner.stream_has_events(raw) is False

    raw.write_text('{"type": "init"}\n', encoding="utf-8")
    assert agent_runner.stream_has_events(raw) is True


def test_has_success_result_claude(tmp_path: Path):
    raw = tmp_path / "stream.jsonl"
    raw.write_text(json.dumps({"type": "result", "subtype": "success", "is_error": False}) + "\n", encoding="utf-8")
    assert agent_runner.has_success_result("claude", raw) is True

    raw.write_text(json.dumps({"type": "result", "subtype": "failure", "is_error": True}) + "\n", encoding="utf-8")
    assert agent_runner.has_success_result("claude", raw) is False


def test_has_success_result_opencode(tmp_path: Path):
    raw = tmp_path / "opencode.jsonl"
    raw.write_text(json.dumps({"type": "step_finish", "part": {"reason": "stop"}}) + "\n", encoding="utf-8")
    assert agent_runner.has_success_result("opencode", raw) is True


def test_partial_trailing_line_handling(tmp_path: Path):
    raw = tmp_path / "stream.jsonl"
    raw.write_text('{"type": "init"}\n{"type": "result", "subtype": "success", "is_error": false}\n{"partial": "trun', encoding="utf-8")
    assert agent_runner.stream_has_events(raw) is True
    assert agent_runner.has_success_result("claude", raw) is True
