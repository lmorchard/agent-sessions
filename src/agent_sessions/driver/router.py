#!/usr/bin/env python3
"""Pure phase-selection router for the agent-session driver.

Why this exists:
----------------
Extracts the driver's complex selection logic (Priority ladder P1-P4, tier checks,
PR state inspection, park state handling, loop breakers) into a pure, importable,
testable module that takes plain data in and returns decision candidates, logs,
and actions out, performing zero I/O.
"""

from __future__ import annotations

from typing import Any

PARK_LABEL = "agent-session:needs-human"
MERGE_READY_LABEL = "agent-session:merge-ready"


def select(
    open_issues: list[dict[str, Any]],
    open_prs: list[dict[str, Any]],
    board_items: list[dict[str, Any]] | None = None,
    parked_nums: set[str] | None = None,
    park_reasons: dict[str, str] | None = None,
    attempts_map: dict[str, int] | None = None,
    human_comments_map: dict[str, tuple[bool, str]] | None = None,
    pr_details_map: dict[str, dict[str, Any]] | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Select eligible candidates and generate log messages and actions mechanically.

    Takes only plain data and returns a dict with:
      - `candidates`: list of (issue_number, phase) tuples ordered by priority ladder
      - `messages`: list of log strings (simulating say() output)
      - `unpark_actions`: list of issue numbers to unpark
      - `park_actions`: list of (issue_number, reason) tuples to park
      - `total_issues`: int count of open issues
      - `markerless_count`: int
      - `candidates_count`: int
    """
    board_items = board_items or []
    parked_nums = parked_nums or set()
    park_reasons = park_reasons or {}
    attempts_map = attempts_map or {}
    human_comments_map = human_comments_map or {}
    pr_details_map = pr_details_map or {}
    config = config or {}

    repo = config.get("repo", "owner/repo")
    all_issues = config.get("all_issues", False)
    max_phase_attempts = config.get("max_phase_attempts", 3)
    retry = str(config.get("retry", ""))
    issue_override = str(config.get("issue", ""))

    messages: list[str] = []
    unpark_actions: list[str] = []
    park_actions: list[tuple[str, str]] = []

    # Helper functions local or imported
    from agent_sessions.driver import gate, gh_query, reconciler

    board_nums = set()
    for item in board_items:
        st = item.get("status", "")
        prio = item.get("priority", "")
        if st == "Ready" or prio in ("P0", "P1"):
            content = item.get("content", {})
            if isinstance(content, dict) and "number" in content:
                board_nums.add(str(content["number"]))

    total_issues = len(open_issues)

    if not all_issues:
        filtered_issues = []
        for iss in open_issues:
            num_str = str(iss.get("number"))
            labels = [l.get("name", "") for l in iss.get("labels", []) if isinstance(l, dict)]
            has_priority_label = any(p_lbl in labels for p_lbl in ("P0", "P1", "P2", "P3", "P4", "P5"))
            if num_str in board_nums or has_priority_label:
                filtered_issues.append(iss)
    else:
        filtered_issues = open_issues

    def is_specced(iss: dict) -> bool:
        labels = [l.get("name", "") for l in iss.get("labels", []) if isinstance(l, dict)]
        if "agent-session:spec" in labels:
            return True
        body = iss.get("body", "") or ""
        return "<!-- agent-session:spec -->" in body

    candidates_json = [
        iss
        for iss in filtered_issues
        if is_specced(iss)
        and not any(
            isinstance(l, dict) and l.get("name") == MERGE_READY_LABEL
            for l in iss.get("labels", [])
        )
    ]
    markerless_json = [iss for iss in filtered_issues if not is_specced(iss)]

    p1_unblock: list[tuple[str, str]] = []
    p2_execute: list[tuple[str, str]] = []
    p3_groom: list[tuple[str, str]] = []
    p4_escalate: list[tuple[str, str]] = []

    # Process markerless issues
    markerless_list = []
    for m_iss in markerless_json:
        m = str(m_iss.get("number"))
        markerless_list.append(f"#{m}")
        if m in parked_nums and m != retry:
            has_human, human_login = human_comments_map.get(m, (False, ""))
            if has_human:
                messages.append(f"  UNPARK  #{m}  new comment from @{human_login} detected -- removing {PARK_LABEL}")
                unpark_actions.append(m)
            else:
                reason = park_reasons.get(m, "")
                messages.append(f"  SKIP    #{m}  parked: {reason}")
                continue
        else:
            phase = "triage"
            attempts = attempts_map.get(m, 0)
            if attempts >= max_phase_attempts:
                reason = f"MAX_PHASE_ATTEMPTS ({max_phase_attempts}) reached for phase {phase}"
                park_actions.append((m, reason))
                messages.append(f"  parked -- excluded from future selection unless --retry {m}")
                messages.append(f"  SKIP    #{m}  {reason}")
            else:
                p3_groom.append((m, phase))
                messages.append(f"  ELIGIBLE #{m}  triage (Priority 3: Groom)")

    if markerless_json:
        messages.append(f"repo {repo}: read {total_issues} open issues ({len(candidates_json)} carry the label; {len(markerless_json)} do not: {', '.join(markerless_list)} -- run triage)")
    else:
        messages.append(f"repo {repo}: read {total_issues} open issues")

    # Process specced candidates
    for c_iss in candidates_json:
        n = str(c_iss.get("number"))
        body = c_iss.get("body", "")
        tier = gate.tier_of(body)

        is_parked = n in parked_nums and n != retry
        if is_parked:
            has_human, human_login = human_comments_map.get(n, (False, ""))
            if has_human:
                messages.append(f"  UNPARK  #{n}  new comment from @{human_login} detected -- removing {PARK_LABEL}")
                unpark_actions.append(n)
                is_parked = False
        parked_r = park_reasons.get(n, "") if is_parked else ""

        is_invalid_tier = tier in ("conflict", "missing", "unparsed")
        tier_r = f"tier is invalid ({tier})"

        prline = gh_query.pr_blocking_issue(n, open_prs)
        if prline:
            prnum = prline.split("\t")[0]
            pr_data = pr_details_map.get(prnum, {})
            pr_evt = reconciler.PollingAdapter.synthesize_pr_event(n, prnum, pr_data)
            dec = reconciler.handle_pr_reconcile(pr_evt)
            if dec.action == "skip":
                messages.append(f"  SKIP    #{n}  {dec.reason}")
                continue
            phase = dec.phase

            attempts = attempts_map.get(n, 0)
            if attempts >= max_phase_attempts:
                reason = f"MAX_PHASE_ATTEMPTS ({max_phase_attempts}) reached for phase {phase}"
                park_actions.append((n, reason))
                messages.append(f"  parked -- excluded from future selection unless --retry {n}")
                messages.append(f"  SKIP    #{n}  {reason}")
            else:
                if is_parked and phase == "grade_gate":
                    messages.append(f"  SKIP    #{n}  parked: {parked_r} (waiting for human review/changes, not re-grading)")
                else:
                    p1_unblock.append((n, phase))
                    messages.append(f"  ELIGIBLE #{n}  tier: auto-ok (Priority 1: Unblock - {phase})")
                    if is_parked:
                        messages.append(f"  NOTE    #{n}  Bypassing park state (parked: {parked_r}) to perform Unblock phase: {phase}")
        else:
            if is_parked:
                messages.append(f"  SKIP    #{n}  parked: {parked_r}")
            elif is_invalid_tier:
                messages.append(f"  SKIP    #{n}  {tier_r}")
            elif tier == "needs-review":
                phase = "refine"
                attempts = attempts_map.get(n, 0)
                if attempts >= max_phase_attempts:
                    reason = f"MAX_PHASE_ATTEMPTS ({max_phase_attempts}) reached for phase {phase}"
                    park_actions.append((n, reason))
                    messages.append(f"  parked -- excluded from future selection unless --retry {n}")
                    messages.append(f"  SKIP    #{n}  {reason}")
                else:
                    p3_groom.append((n, phase))
                    messages.append(f"  ELIGIBLE #{n}  tier: needs-review (Priority 3: Groom - {phase})")
            elif tier == "auto-ok":
                phase = "execute"
                attempts = attempts_map.get(n, 0)
                if attempts >= max_phase_attempts:
                    reason = f"MAX_PHASE_ATTEMPTS ({max_phase_attempts}) reached for phase {phase}"
                    park_actions.append((n, reason))
                    messages.append(f"  parked -- excluded from future selection unless --retry {n}")
                    messages.append(f"  SKIP    #{n}  {reason}")
                else:
                    p2_execute.append((n, phase))
                    messages.append(f"  ELIGIBLE #{n}  tier: auto-ok (Priority 2: Execute - {phase})")

    all_candidates: list[tuple[str, str]] = p1_unblock + p2_execute + p3_groom + p4_escalate

    # Single issue override
    if issue_override:
        messages.append(f"== select (single issue: #{issue_override}) ==")
        phase = "execute"
        prline = gh_query.pr_for_issue(issue_override, open_prs)
        if prline:
            prnum = prline.split("\t")[0]
            pr_data = pr_details_map.get(prnum, {})
            pr_evt = reconciler.PollingAdapter.synthesize_pr_event(issue_override, prnum, pr_data)
            dec = reconciler.handle_pr_reconcile(pr_evt)
            phase = dec.phase

        if phase == "wait_ci":
            messages.append(f"PR for #{issue_override} CI is still pending; waiting...")
            all_candidates = []
        else:
            messages.append("  eligibility check bypassed by --issue")
            all_candidates = [(issue_override, phase)]

    return {
        "candidates": all_candidates,
        "messages": messages,
        "unpark_actions": unpark_actions,
        "park_actions": park_actions,
        "total_issues": total_issues,
        "markerless_count": len(markerless_json),
        "candidates_count": len(candidates_json),
    }
