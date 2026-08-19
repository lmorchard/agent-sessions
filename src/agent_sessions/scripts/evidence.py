#!/usr/bin/env python3
"""Report runner for agent-sessions evidence over runs.jsonl.

Satisfies issue #198.

Where it reads from, and why that matters more than it looks. This module used to
hardcode `Path(".driver-state")`, which #27 superseded: the driver writes to
`${XDG_STATE_HOME:-$HOME/.local/state}/agent-session/<repo-with-dashes>/`. So the report
was rendering a cold archive -- 38 rows, last written 2026-08-06, none of them carrying
the `phase` field that is this report's primary grouping key, which is why every PHASE
cell printed `unknown`.

That is worse than an ordinary stale path. `docs_check.check_world_state_claims` fails
any bare count in the documentation with "use `make evidence` instead", and `design.md`
and `orientation.md` both cite this command as the only authoritative source for what has
actually run. The doc-rot detector's prescribed remedy was reporting dead data.

Discovery now defaults to every per-repo ledger under the live state root, and the
derivation is imported from `run_progress` rather than reimplemented -- a third copy of
that expression is how the second one went wrong.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, DefaultDict

from agent_sessions.scripts.run_progress import default_state_dir


def is_judgment_park(outcome: str, reason: str) -> bool:
    if outcome == "gate-human":
        return True
    if outcome == "parked":
        # Reason starts with "parked by agent during <phase>:" for intentional escalations.
        if "parked by agent during" in reason:
            return True
        return False
    return False


def is_mechanical_park(outcome: str, reason: str) -> bool:
    if outcome in ("failed", "driver-fault", "budget-exhausted", "no-gate", "ci-stale", "incomplete"):
        return True
    if outcome == "parked" and not is_judgment_park(outcome, reason):
        return True
    return False


def state_root() -> Path:
    """The directory holding one subdirectory per repo the driver has run against."""
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "agent-session"


def discover_ledgers(state_dir: str = "", repo: str = "") -> list[Path]:
    """Every `runs.jsonl` this invocation should read, most specific option winning."""
    if state_dir:
        return [Path(state_dir).expanduser() / "runs.jsonl"]
    if repo:
        return [default_state_dir(repo) / "runs.jsonl"]
    root = state_root()
    if not root.is_dir():
        return []
    return sorted(
        child / "runs.jsonl" for child in root.iterdir() if (child / "runs.jsonl").is_file()
    )


def read_ledger(path: Path) -> tuple[list[dict[str, Any]], int]:
    """Rows plus a count of lines that did not parse.

    The skip count is returned rather than discarded. A partial final line is normal --
    the driver appends as it goes -- but a report that silently drops rows cannot be
    distinguished from one that had fewer runs to report, and this project's rule is that
    a null must not render as a positive.
    """
    rows: list[dict[str, Any]] = []
    skipped = 0
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                continue
            if isinstance(parsed, dict):
                rows.append(parsed)
            else:
                skipped += 1
    return rows, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument(
        "--state-dir", default="", help="read one explicit state directory's runs.jsonl"
    )
    parser.add_argument(
        "--repo", default="", help="read one repo's ledger, e.g. owner/name"
    )
    args = parser.parse_args(argv)

    ledgers = discover_ledgers(args.state_dir, args.repo)
    if not ledgers:
        where = args.state_dir or args.repo or str(state_root())
        print(f"No runs.jsonl found under {where}")
        print("The driver writes to ${XDG_STATE_HOME:-$HOME/.local/state}/agent-session/<owner>-<repo>/.")
        return 1

    runs: list[dict[str, Any]] = []
    skipped_total = 0
    for ledger in ledgers:
        rows, skipped = read_ledger(ledger)
        runs.extend(rows)
        skipped_total += skipped
        print(f"read {len(rows):>5} row(s) from {ledger}")
    print()

    # Grouping by (phase, repo, outcome) -> {"count": n, "first": ts, "last": ts}
    groups: DefaultDict[tuple[str, str, str], dict[str, Any]] = defaultdict(lambda: {"count": 0, "first": "", "last": ""})

    judgment_count = 0
    mechanical_count = 0

    for row in runs:
        phase = row.get("phase", "unknown")
        repo = row.get("repo", "unknown")
        outcome = row.get("outcome", "unknown")
        reason = row.get("reason", "")
        ts = row.get("started", "")

        key = (phase, repo, outcome)
        groups[key]["count"] += 1

        if not groups[key]["first"] or ts < groups[key]["first"]:
            groups[key]["first"] = ts
        if not groups[key]["last"] or ts > groups[key]["last"]:
            groups[key]["last"] = ts

        if is_judgment_park(outcome, reason):
            judgment_count += 1
        elif is_mechanical_park(outcome, reason):
            mechanical_count += 1

    print(f"{'PHASE':<20} {'REPO':<30} {'OUTCOME':<25} {'COUNT':<6} {'FIRST':<20} {'LAST':<20}")
    print("-" * 125)
    for (phase, repo, outcome), data in sorted(groups.items()):
        count = data["count"]
        first = data["first"]
        last = data["last"]
        print(f"{phase:<20} {repo:<30} {outcome:<25} {count:<6} {first:<20} {last:<20}")

    print("\n--- RATIOS ---")
    print(f"Judgment Parks:   {judgment_count}")
    print(f"Mechanical Parks: {mechanical_count}")
    if mechanical_count > 0:
        ratio = judgment_count / mechanical_count
        print(f"Ratio (J/M):      {ratio:.2f}")
    else:
        print(f"Ratio (J/M):      {judgment_count} / 0")

    print(f"\nTotal runs:       {len(runs)}")
    if skipped_total:
        print(f"Unparsed lines:   {skipped_total} (reported, not silently dropped)")

    return 0

if __name__ == "__main__":
    sys.exit(main())
