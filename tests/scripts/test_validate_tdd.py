from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from agent_sessions.scripts.validate_tdd import validate_stream


def test_validate_tdd_success(tmp_path: Path) -> None:
    stream = tmp_path / "stream.jsonl"
    event1 = {
        "type": "message",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "pytest"}}
            ],
        },
    }
    event2 = {
        "type": "message",
        "message": {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "t1", "is_error": True, "content": "1 failed"}
            ],
        },
    }
    event3 = {
        "type": "message",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "t2", "name": "Edit", "input": {"file_path": "foo.py"}}
            ],
        },
    }
    stream.write_text(
        json.dumps(event1) + "\n" + json.dumps(event2) + "\n" + json.dumps(event3) + "\n",
        encoding="utf-8",
    )
    assert validate_stream(stream) is True


def test_validate_tdd_fails_no_failing_check(tmp_path: Path) -> None:
    stream = tmp_path / "stream.jsonl"
    event1 = {
        "type": "message",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": "foo.py"}}
            ],
        },
    }
    stream.write_text(json.dumps(event1) + "\n", encoding="utf-8")
    assert validate_stream(stream) is False


def test_validate_tdd_fails_bash_passed(tmp_path: Path) -> None:
    stream = tmp_path / "stream.jsonl"
    event1 = {
        "type": "message",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "pytest"}}
            ],
        },
    }
    event2 = {
        "type": "message",
        "message": {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "t1", "is_error": False, "content": "1 passed"}
            ],
        },
    }
    event3 = {
        "type": "message",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "t2", "name": "Edit", "input": {"file_path": "foo.py"}}
            ],
        },
    }
    stream.write_text(
        json.dumps(event1) + "\n" + json.dumps(event2) + "\n" + json.dumps(event3) + "\n",
        encoding="utf-8",
    )
    assert validate_stream(stream) is False


def test_validate_tdd_nonexistent_stream(tmp_path: Path) -> None:
    stream = tmp_path / "nonexistent.jsonl"
    assert validate_stream(stream) is True

