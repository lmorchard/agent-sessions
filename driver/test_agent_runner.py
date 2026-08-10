"""Tests for driver/agent_runner.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import agent_runner  # noqa: E402
import credentials  # noqa: E402


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


def test_run_agent_model_tiers(tmp_path: Path, monkeypatch):
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Hello", encoding="utf-8")
    raw = tmp_path / "stream.jsonl"
    stderr = tmp_path / "stderr.txt"

    captured_cmds = []

    class MockResult:
        returncode = 0

    def mock_run(cmd, *args, **kwargs):
        captured_cmds.append(cmd)
        return MockResult()

    monkeypatch.setattr("subprocess.run", mock_run)

    # Test high tier model default
    agent_runner.run_agent([
        "--backend", "claude",
        "--repo-path", str(tmp_path),
        "--skill-dir", str(tmp_path),
        "--prompt-file", str(prompt),
        "--raw-output", str(raw),
        "--stderr-output", str(stderr),
        "--high-tier-model", "claude-3-5-sonnet",
        "--low-tier-model", "claude-3-5-haiku",
        "--tier", "high"
    ])
    assert "--model" in captured_cmds[-1]
    assert captured_cmds[-1][captured_cmds[-1].index("--model") + 1] == "claude-3-5-sonnet"

    # Test low tier model
    agent_runner.run_agent([
        "--backend", "claude",
        "--repo-path", str(tmp_path),
        "--skill-dir", str(tmp_path),
        "--prompt-file", str(prompt),
        "--raw-output", str(raw),
        "--stderr-output", str(stderr),
        "--high-tier-model", "claude-3-5-sonnet",
        "--low-tier-model", "claude-3-5-haiku",
        "--tier", "low"
    ])
    assert "--model" in captured_cmds[-1]
    assert captured_cmds[-1][captured_cmds[-1].index("--model") + 1] == "claude-3-5-haiku"



def _run_and_capture_env(tmp_path: Path, monkeypatch, extra_argv=()):
    """Invoke `run_agent` against a stubbed `subprocess.run` and return the child env."""
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Hello", encoding="utf-8")
    captured = {}

    class MockResult:
        returncode = 0

    def mock_run(cmd, *args, **kwargs):
        captured["env"] = kwargs.get("env")
        return MockResult()

    monkeypatch.setattr("subprocess.run", mock_run)
    agent_runner.run_agent([
        "--backend", "claude",
        "--repo-path", str(tmp_path),
        "--skill-dir", str(tmp_path),
        "--prompt-file", str(prompt),
        "--raw-output", str(tmp_path / "stream.jsonl"),
        "--stderr-output", str(tmp_path / "stderr.txt"),
        *extra_argv,
    ])
    return captured["env"]


def test_agent_child_env_carries_the_read_token_only(tmp_path: Path, monkeypatch):
    """The containment property, at the one place it is actually applied (#191)."""
    monkeypatch.setenv(credentials.READ_TOKEN_VAR, "read-token")
    monkeypatch.setenv(credentials.WRITE_TOKEN_VAR, "write-token")
    monkeypatch.setenv("GH_TOKEN", "write-token")

    env = _run_and_capture_env(tmp_path, monkeypatch)

    assert env["GH_TOKEN"] == "read-token"
    assert env["GITHUB_TOKEN"] == "read-token"
    assert "write-token" not in env.values(), f"the agent got a write-capable credential: {env}"
    assert credentials.WRITE_TOKEN_VAR not in env


def test_agent_child_env_is_unchanged_when_no_read_token_is_configured(tmp_path: Path, monkeypatch):
    """Degraded mode still has to run; the driver warns about it at startup."""
    monkeypatch.delenv(credentials.READ_TOKEN_VAR, raising=False)
    monkeypatch.setenv("GH_TOKEN", "host-token")

    env = _run_and_capture_env(tmp_path, monkeypatch)

    assert env["GH_TOKEN"] == "host-token"


def test_writes_file_is_exported_to_the_agent(tmp_path: Path, monkeypatch):
    monkeypatch.delenv(credentials.READ_TOKEN_VAR, raising=False)
    writes_file = tmp_path / "runs" / "writes.jsonl"

    env = _run_and_capture_env(tmp_path, monkeypatch, ["--writes-file", str(writes_file)])

    assert env[agent_runner.WRITES_FILE_VAR] == str(writes_file.resolve())
