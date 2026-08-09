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

    bash_tool_ids: set[str] = set()
    has_failing_check = False

    for event in events:
        content = []
        if isinstance(event, dict):
            if "message" in event and isinstance(event["message"], dict):
                content = event["message"].get("content", [])
            elif "content" in event:
                content = event.get("content", [])

        if not isinstance(content, list):
            continue

        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")

            if block_type == "tool_use":
                tool_name = block.get("name")
                tool_id = block.get("id")
                if tool_name == "Bash":
                    if tool_id:
                        bash_tool_ids.add(tool_id)
                    if block.get("is_error") is True or block.get("status") == "error":
                        has_failing_check = True
                elif tool_name in ("Edit", "Write"):
                    if not has_failing_check:
                        return False

            elif block_type == "tool_result":
                tool_use_id = block.get("tool_use_id")
                is_error = block.get("is_error", False)
                status = block.get("status")
                content_str = str(block.get("content", ""))

                if tool_use_id in bash_tool_ids:
                    if is_error or status == "error" or "FAILED" in content_str or "FAIL" in content_str:
                        has_failing_check = True

    return True


if __name__ == "__main__":
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
        valid = validate_stream(path)
        sys.exit(0 if valid else 1)
    sys.exit(0)
