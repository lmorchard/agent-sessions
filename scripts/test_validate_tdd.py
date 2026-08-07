from __future__ import annotations

import json
from pathlib import Path
import pytest
from validate_tdd import validate_stream


def test_validate_tdd_basic(tmp_path: Path) -> None:
    stream = tmp_path / "stream.jsonl"
    event1 = {
        "type": "message",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "name": "Bash", "input": {"command": "pytest"}}
            ],
        },
    }
    event2 = {
        "type": "message",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "name": "Edit", "input": {"file_path": "foo.py"}}
            ],
        },
    }
    stream.write_text(json.dumps(event1) + "\n" + json.dumps(event2) + "\n", encoding="utf-8")
    assert validate_stream(stream) is True
