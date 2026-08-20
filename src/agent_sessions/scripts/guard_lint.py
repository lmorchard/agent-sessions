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

import argparse
import json
import re
import sys
from pathlib import Path

#: `gh issue list` defaults to 30. The Makefile passes this explicitly; the default here
#: matches `board_audit`'s so a hand invocation behaves the same way.
DEFAULT_LIMIT = 500

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


def _issue_label(item: object, index: int) -> str:
    """Prefer the real issue number. The old label was the array index, so `issue #1`
    meant "the newest issue in the page" -- unfindable, and misleading in the one
    direction that matters, since it reads like an issue number."""
    if isinstance(item, dict):
        number = item.get("number")
        if isinstance(number, int):
            return f"issue #{number}"
    return f"record {index + 1}"


def _body_of(item: object) -> str:
    if isinstance(item, dict):
        return str(item.get("body", "") or item.get("title", "") or "")
    if isinstance(item, str):
        return item
    return ""


def main(argv: list[str] | None = None) -> int:
    """Scan issue bodies or files, and say how many were examined.

    The count in the success line is the point, not decoration. Piping
    `gh issue list --json body` with no `--limit` gave the detector `gh`'s default 30
    newest issues, over which it printed "no pinned test count guards found" -- a clean
    bill over an arbitrary slice, indistinguishable from a clean bill over the backlog.
    A detector that cannot say what it examined cannot be trusted when it finds nothing.
    """
    global failures
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="Text files to scan; omit to read JSON on stdin")
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help="the record limit the caller asked its query for; a full page is treated as truncated",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    scanned = 0
    noun = "source"

    if args.paths:
        for path_str in args.paths:
            path = Path(path_str)
            if path.exists():
                lint_source(path.read_text(encoding="utf-8", errors="replace"), str(path))
                scanned += 1
    else:
        content = "" if sys.stdin.isatty() else sys.stdin.read()
        if content:
            noun = "issue body"
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                lint_source(content, "<stdin>")
                scanned = 1
                noun = "source"
            else:
                if isinstance(data, list):
                    # At the limit, not past it: a full page is exactly the case where
                    # truncation and coincidence are indistinguishable. Same rule as
                    # board_audit.bounded_records, for the same reason.
                    if len(data) >= args.limit:
                        print(
                            f"  FAIL  scan is potentially truncated at limit {args.limit}: "
                            f"{len(data)} record(s) returned. Raise --limit and the query's "
                            f"own limit; a clean result over an unknown slice is not a clean result."
                        )
                        return 2
                    for i, item in enumerate(data):
                        body = _body_of(item)
                        if body:
                            lint_source(body, _issue_label(item, i))
                        scanned += 1
                elif isinstance(data, dict):
                    body = _body_of(data)
                    if body:
                        lint_source(body, _issue_label(data, 0))
                    scanned = 1

    if failures:
        for f in failures:
            print(f"  FAIL  {f}")
        print(
            f"\nguard-lint: {len(failures)} pinned test count guard(s) found in {scanned} "
            f"{noun}(s). Use invariants instead of pinned counts (see issue #68)."
        )
        return 1

    print(f"guard-lint: no pinned test count guards in {scanned} {noun}(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
