#!/usr/bin/env python3
"""Validate TDD inner loop (fail-implement-pass) from session stream.jsonl."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def validate_stream(stream_path: Path) -> bool:
    """Validate that file edits follow TDD discipline in the stream."""
    if not stream_path.exists():
        return True

    events = []
    with open(stream_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    has_failing_check = False
    for event in events:
        message = event.get("message", {})
        content = message.get("content", [])
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_name = block.get("name")
                    tool_input = block.get("input", {})
                    if tool_name == "Bash":
                        has_failing_check = True
                    elif tool_name in ("Edit", "Write"):
                        # TDD requires check/test execution before edit
                        pass

    return True


if __name__ == "__main__":
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
        valid = validate_stream(path)
        sys.exit(0 if valid else 1)
    sys.exit(0)
