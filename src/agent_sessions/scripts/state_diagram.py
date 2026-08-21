#!/usr/bin/env python3
"""Programmatic Mermaid state diagram generator for agent-sessions Issue & PR state flow.

Why this exists:
----------------
Docs should not state facts or state transition models that can be programmatically derived from
live source code. This module programmatically generates the Mermaid diagram of issue & PR states,
reading the one constant it names -- the park label -- from `driver/labels.py`, its owner, so
a rename reaches the README. The `reconciler` and `gate` calls the diagram shows are node
labels, not live reads; grep this file before believing otherwise.

It can update `README.md` or check `README.md` for drift as part of `docs-check`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agent_sessions.driver import labels

ROOT = Path(__file__).resolve().parents[3]

MARKER_BEGIN = "<!-- BEGIN ISSUE_PR_STATE_DIAGRAM -->"
MARKER_END = "<!-- END ISSUE_PR_STATE_DIAGRAM -->"


def generate_diagram() -> str:
    """Generate the Mermaid flowchart for issue & PR states from source code constants."""
    park_lbl = labels.PARK_LABEL

    diagram = f"""flowchart TD
    subgraph Backlog ["1. Issue Selection & Intake"]
        OpenIssue["Open Issue"] --> HasSpec{{"Has spec marker?"}}
        HasSpec -- No --> PhaseTriage["triage phase (P3: Groom)"]
        PhaseTriage --> StampedSpec["Stamp spec marker & Tier"]

        HasSpec -- Yes --> CheckTier{{"Check Tier (gate.tier_of)"}}
        CheckTier -- auto-ok --> PhaseExecute["execute phase (P2: Execute)"]
        CheckTier -- needs-review --> PhaseRefine["refine phase (P3: Groom)"]
        CheckTier -- conflict / invalid --> SkipTier["Skip (Invalid Tier)"]

        StampedSpec --> HasSpec
    end

    subgraph Working ["2. PR Reconciler & Phases"]
        PhaseExecute --> OpenPR["Open PR with Merge Gate"]
        PhaseRefine --> HumanSpecReview["Human Spec Review"]

        OpenPR --> PRReconcile{{"reconciler.handle_pr_reconcile()"}}
        PRReconcile -- Conflict --> PhaseFixConflict["fix_conflict phase (P1: Unblock)"]
        PRReconcile -- Threads / Changes --> PhaseAddressComments["address_comments phase (P1: Unblock)"]
        PRReconcile -- CI Fail --> PhaseFixCI["fix_ci phase (P1: Unblock)"]
        PRReconcile -- CI Pending --> WaitCI["wait_ci (Skip / Wait)"]
        PRReconcile -- Review Pending --> WaitReview["wait_review (Skip / Wait)"]
        PRReconcile -- No Reviews --> PhaseReqReview["request_review phase (P1: Unblock)"]
        PRReconcile -- Clean & Ready --> PhaseGradeGate["grade_gate phase (P1: Unblock)"]
    end

    subgraph Gate ["3. Gate Classification & Verdicts"]
        PhaseGradeGate --> GateClassify{{"gate.classify()"}}
        GateClassify -- All Rows Pass --> GateEligible["gate-eligible (auto-merge eligible)"]
        GateClassify -- Human Action Required --> GateHuman["gate-human (human-merge-required)"]
        GateClassify -- Head Moved --> CIStale["ci-stale (Stale CI SHA)"]
        GateClassify -- Pending --> Incomplete["incomplete (Wait)"]
        GateClassify -- Max Attempts / Error --> Parked["Parked ({park_lbl})"]

        GateEligible --> HumanMerge["Human Merge (Main)"]
    end

    subgraph ParkRecovery ["4. Park & Recovery"]
        Parked --> HumanComment{{"New Human Comment?"}}
        HumanComment -- Yes --> Unpark["Unpark (Remove {park_lbl})"]
        Unpark --> HasSpec
    end

    classDef eligible fill:#d4edda,stroke:#28a745,color:#155724;
    classDef human fill:#fff3cd,stroke:#ffc107,color:#856404;
    classDef parked fill:#f8d7da,stroke:#dc3545,color:#721c24;

    class GateEligible eligible;
    class GateHuman,HumanMerge,HumanSpecReview human;
    class Parked parked;"""
    return diagram.strip()


def extract_diagram_block(content: str) -> str | None:
    """Extract content between MARKER_BEGIN and MARKER_END from content string."""
    if MARKER_BEGIN not in content or MARKER_END not in content:
        return None
    start = content.find(MARKER_BEGIN) + len(MARKER_BEGIN)
    end = content.find(MARKER_END)
    return content[start:end]


def update_readme(readme_path: Path) -> bool:
    """Update readme_path in-place with generated diagram block."""
    if not readme_path.exists():
        return False
    content = readme_path.read_text(encoding="utf-8")
    if MARKER_BEGIN not in content or MARKER_END not in content:
        return False

    diagram = generate_diagram()
    new_block = f"\n\n```mermaid\n{diagram}\n```\n\n"

    start_idx = content.find(MARKER_BEGIN) + len(MARKER_BEGIN)
    end_idx = content.find(MARKER_END)

    updated = content[:start_idx] + new_block + content[end_idx:]
    readme_path.write_text(updated, encoding="utf-8")
    return True


def check_readme(readme_path: Path) -> bool:
    """Check if the diagram block in readme_path matches generated diagram."""
    if not readme_path.exists():
        return False
    content = readme_path.read_text(encoding="utf-8")
    block = extract_diagram_block(content)
    if block is None:
        return False

    diagram = generate_diagram()
    expected_block = f"\n\n```mermaid\n{diagram}\n```\n\n"
    return block == expected_block


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="State diagram generator & checker")
    parser.add_argument("--check", action="store_true", help="Check README.md diagram matches generator")
    parser.add_argument("--update", action="store_true", help="Update README.md with generated diagram")
    parser.add_argument("--readme", type=Path, default=ROOT / "README.md", help="Path to README.md")
    args = parser.parse_args(argv)

    if args.check:
        if check_readme(args.readme):
            print("state-diagram: README.md state diagram is up to date.")
            return 0
        else:
            print("FAIL: README.md state diagram is out of sync with generator (run with --update to fix)")
            return 1

    if args.update:
        if update_readme(args.readme):
            print("state-diagram: Updated README.md state diagram.")
            return 0
        else:
            print(f"FAIL: Markers {MARKER_BEGIN} / {MARKER_END} not found in {args.readme}")
            return 1

    # Default: print generated diagram to stdout
    print(generate_diagram())
    return 0


if __name__ == "__main__":
    sys.exit(main())
