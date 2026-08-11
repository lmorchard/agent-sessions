#!/usr/bin/env python3
"""Report runner for agent-sessions evidence over runs.jsonl.

Satisfies issue #198.
"""

import json
import sys
from pathlib import Path
from collections import defaultdict


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


def main() -> int:
    state_dir = Path(".driver-state")
    runs_log = state_dir / "runs.jsonl"
    
    if not runs_log.is_file():
        print("No runs.jsonl found in .driver-state/")
        return 1

    runs = []
    with open(runs_log, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                runs.append(json.loads(line))
            except json.JSONDecodeError:
                pass # tolerate partial final line

    # Grouping by (phase, repo, outcome) -> {"count": n, "first": ts, "last": ts}
    groups = defaultdict(lambda: {"count": 0, "first": "", "last": ""})
    
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
        
    return 0

if __name__ == "__main__":
    sys.exit(main())
