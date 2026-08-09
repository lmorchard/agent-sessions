#!/usr/bin/env python3
"""Detect pinned test count guards in issue bodies or text files.

Why this exists
---------------
A guard stating a pinned test count (e.g., "34 passed") rots silently when
codebase tests are added or removed. `findings.md` and issue #68 establish
that invariants ("no test lost, newly skipped, or newly failing") should be
used instead of pinned numbers.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Matches bare test counts like "3234 passed", "34 failed", "49 skipped", "100 tests", or reversed.
PINNED_COUNT = re.compile(
    r'\b(?:\d+\s+(?:passed|failed|skipped|tests)|(?:passed|failed|skipped|tests)\s+\d+)\b',
    re.IGNORECASE,
)

failures: list[str] = []


def scan_text(text: str) -> list[tuple[int, str]]:
    """Scan text for lines containing pinned test counts."""
    results = []
    lines = text.splitlines()
    in_guards = False
    for lineno, line in enumerate(lines, start=1):
        lower = line.lower()
        if "regression guards" in lower or "## guards" in lower:
            in_guards = True
            continue
        elif line.startswith("## ") and in_guards:
            in_guards = False

        if in_guards and PINNED_COUNT.search(line):
            results.append((lineno, line))
    return results


def lint_source(text: str, source: str) -> None:
    for lineno, line in scan_text(text):
        failures.append(f"{source}:{lineno}: pinned test count guard: {line.strip()}")


def main() -> int:
    global failures
    inputs = sys.argv[1:]

    content = ""
    if inputs:
        for path_str in inputs:
            path = Path(path_str)
            if path.exists():
                text = path.read_text(encoding="utf-8", errors="replace")
                lint_source(text, str(path))
    else:
        if not sys.stdin.isatty():
            content = sys.stdin.read()

    if content:
        try:
            data = json.loads(content)
            if isinstance(data, list):
                for i, item in enumerate(data):
                    body = ""
                    if isinstance(item, dict):
                        body = item.get("body", "") or item.get("title", "")
                    elif isinstance(item, str):
                        body = item
                    if body:
                        lint_source(body, f"issue #{i+1}")
            elif isinstance(data, dict):
                body = data.get("body", "")
                if body:
                    lint_source(body, "issue")
        except json.JSONDecodeError:
            lint_source(content, "<stdin>")

    if failures:
        for f in failures:
            print(f"  FAIL  {f}")
        print(f"\nguard-lint: {len(failures)} pinned test count guard(s) found. Use invariants instead of pinned counts (see issue #68).")
        return 1

    print("guard-lint: no pinned test count guards found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
