#!/usr/bin/env python3
"""Gate-block parsing and outcome classification for the agent-session driver.

Why this exists as a Python module rather than bash functions
------------------------------------------------------------
`driver/test-driver.sh` used to hand-copy the driver's parsers in order to test
them -- because you cannot import a function out of a script that runs `main` at
the bottom, so copying was the path of least resistance. The copies drifted:
`classify_outcome` was 53 lines in the driver and 15 in the test, with zero
ci-staleness awareness. Given one identical gate block the two disagreed --

    shipped driver -> ci-stale       "rests on a commit that no longer ships"
    test-file copy -> gate-eligible  "all gate rows satisfied"

-- so the suite graded a replica that called a stale-CI PR eligible for
auto-merge exactly where the shipped code voided it. Under phase 3, "eligible"
means merge.

The fix is extraction, not rewriting. This module is importable, so its tests
exercise the shipping code and the divergence becomes unrepresentable rather
than merely discouraged. The behaviour below is a deliberate *faithful* port of
the bash, quirks included -- the goal is one implementation, not a better one.

Stdlib only, on purpose. The driver's header claims a GHA runner executes it
unchanged; pytest is a dev dependency of the *tests*, never of this file.
Verified by `python3 -I -S -c "import gate"`, which sees no site-packages.

Rule going forward: bash for orchestration (flags, process control, invoking
gh/git/claude), Python for parsing and classification.
"""

from __future__ import annotations

import argparse
import json
import re
import sys

GATE_MARKER = "<!-- agent-session:gate -->"
SPEC_MARKER = "<!-- agent-session:spec -->"

# A bare 7-40 char hex token anywhere in the ci row.
#
# Anchoring on a literal `@` made this check silently un-runnable once: #722's
# run wrote `ci: 2/2 pass (js-test, lint-and-test) on f42c0f1` -- a correct sha
# behind the word "on" instead of "@" -- so nothing matched, the sha came out
# empty, and staleness went UNCHECKED on a PR about to be called eligible. The
# sha happened to be current; nothing verified that. Match the token, not a
# delimiter the template cannot enforce.
_CI_SHA_RE = re.compile(r"\b[0-9a-f]{7,40}\b")

_TIER_HEADING_RE = re.compile(r"^##[ \t]*Tier[ \t]*:")

# Outcomes that mean "the run stopped without a gradeable verdict", and are
# therefore candidates for budget reclassification.
_NO_VERDICT_OUTCOMES = ("incomplete", "parked", "no-gate")


def extract_gate(body: str, marker: str = GATE_MARKER) -> str:
    """Return the fenced block that follows `marker`, or "" if absent.

    Port of the driver's awk: find the marker line, treat the next ``` as the
    opening fence, and stop at the following one.
    """
    found = False
    opened = False
    out: list[str] = []
    for line in (body or "").split("\n"):
        if not found:
            if marker in line:
                found = True
            continue
        if line.startswith("```"):
            if not opened:
                opened = True
                continue
            break
        if opened:
            out.append(line)
    return "\n".join(out)


def gate_field(gate: str, field: str) -> str:
    """First `field:` line's value, leading whitespace stripped. "" if absent.

    Port of `grep -m1 "^field:" | sed "s/^field:[[:space:]]*//"`.
    """
    prefix = f"{field}:"
    for line in (gate or "").split("\n"):
        if line.startswith(prefix):
            return line[len(prefix):].lstrip(" \t")
    return ""


def gate_fields(gate: str) -> dict[str, str]:
    """Every `key: value` line in the block, first occurrence winning."""
    fields: dict[str, str] = {}
    for line in (gate or "").split("\n"):
        m = re.match(r"^([A-Za-z0-9_-]+):(.*)$", line)
        if m and m.group(1) not in fields:
            fields[m.group(1)] = m.group(2).lstrip(" \t")
    return fields


def ci_sha(ci_row: str) -> str:
    """The sha a ci row claims to describe, or "" if it names none."""
    m = _CI_SHA_RE.search(ci_row or "")
    return m.group(0) if m else ""


def classify(gate: str, head_sha: str = "", marker: str = GATE_MARKER) -> dict:
    """Classify a gate block into an outcome + reason.

    Returns a dict with `outcome`, `reason`, `has_gate`, `fields`, `ci_sha`,
    `ci_stale` and `warnings`. Faithful port of the driver's classify_outcome.
    """
    result: dict = {
        "has_gate": bool((gate or "").strip()),
        # The raw block, so a caller that needs to record it (the driver writes
        # gate.yaml) does not have to parse the body a second time.
        "gate": gate or "",
        "fields": {},
        "outcome": "",
        "reason": "",
        "ci_sha": "",
        "ci_stale": False,
        "warnings": [],
    }

    if not result["has_gate"]:
        result["outcome"] = "no-gate"
        result["reason"] = f"PR exists but carries no {marker} block"
        return result

    result["fields"] = gate_fields(gate)
    verdict = gate_field(gate, "verdict")
    reason = gate_field(gate, "reason")

    # A CI result is a claim about a commit, and the gate block outlives the
    # commit. If the ci row records a sha that is not the current head, the row
    # describes something that no longer ships, so the verdict resting on it is
    # void. This is NOT re-deriving the gate: it asks whether the block still
    # refers to the PR in front of us.
    if head_sha:
        ci_row = gate_field(gate, "ci")
        sha = ci_sha(ci_row)
        result["ci_sha"] = sha
        if not sha and ci_row.strip() and ci_row != "no checks configured":
            # A null must never render as a positive: an unparseable sha also
            # yields "current", so say so rather than reading it as verified.
            result["warnings"].append(
                f"ci row carries no parseable sha ('{ci_row}') -- staleness "
                "UNCHECKED, not verified current. pr-body-template.md requires it."
            )
        if sha and not head_sha.startswith(sha):
            result["ci_stale"] = True
            result["outcome"] = "ci-stale"
            result["reason"] = (
                f"gate ci row was graded at {sha} but the head is now "
                f'{head_sha[:8]} -- verdict "{verdict}" rests on a commit that '
                "no longer ships"
            )
            return result

    if verdict == "eligible-for-auto-merge":
        result["outcome"] = "gate-eligible"
        result["reason"] = reason or "all gate rows satisfied"
    elif verdict == "human-merge-required":
        result["outcome"] = "gate-human"
        result["reason"] = reason or "no reason given (pr.md requires one)"
    elif verdict == "pending":
        # pr-body-template.md: pending means the run had not derived the
        # verdict. Not actionable.
        result["outcome"] = "incomplete"
        result["reason"] = "verdict still pending -- run did not reach the gate"
    elif verdict == "":
        result["outcome"] = "no-gate"
        result["reason"] = "gate block present but has no verdict field"
    else:
        result["outcome"] = "no-gate"
        result["reason"] = f"unrecognised verdict value: {verdict}"
    return result


def tier_of(body: str, marker: str = SPEC_MARKER) -> str:
    """Tier named by an issue body: auto-ok | needs-review | conflict | missing | unparsed.

    The `^## Tier:` anchor is load-bearing: #585's tier paragraph contains the
    string "needs-review" in prose, so an unanchored match reads both tiers and
    the issue looks ambiguous when it is not.

    `conflict` is deliberate rather than a fallback to the first heading. The
    contract is that the body is authoritative and disagreements are surfaced,
    not resolved -- and it fired for real when a re-tiering appended a second
    `## Tier:` heading instead of replacing the first.
    """
    if marker and marker not in (body or ""):
        return "missing"
    lines = [ln for ln in (body or "").split("\n") if _TIER_HEADING_RE.search(ln)]
    if not lines:
        return "missing"
    has_auto = any("auto-ok" in ln for ln in lines)
    has_review = any("needs-review" in ln for ln in lines)
    if has_auto and has_review:
        return "conflict"
    if has_auto:
        return "auto-ok"
    if has_review:
        return "needs-review"
    return "unparsed"


def tier_batch(issues: list, marker: str = SPEC_MARKER) -> list[tuple[str, str, str]]:
    """(number, tier, title) for every issue carrying `marker`. Others are dropped.

    Replaces the driver's inline `TIER_JQ` jq program. Dropping a marker-less
    issue is deliberate and is *not* the same as `missing`: an issue without the
    marker is not a candidate at all (nothing has specced it), whereas `missing`
    means specced but carrying no `## Tier:` line, which is a real defect worth
    reporting. Collapsing the two would hide the second.
    """
    rows: list[tuple[str, str, str]] = []
    for issue in issues or []:
        body = issue.get("body")
        if body is None or marker not in body:
            continue
        title = str(issue.get("title", "")).replace("\t", " ")
        rows.append((str(issue.get("number", "")), tier_of(body, marker=marker), title))
    return rows


def budget_reclass(outcome: str, cost: float, budget: float) -> str:
    """Reclassify a verdict-less outcome as budget-exhausted at >=95% spend.

    Budget exhaustion was invisible once: a run reported subtype=success,
    is_error=false, exit 0, no gate verdict, having spent $11.87 of $12. The
    driver could not tell "ran out of money" from "stopped for a designed
    escalation". Never parked -- parking hides a recoverable config problem
    behind a skip on a good issue -- and it stops the loop, because the next
    issue inherits the same too-small ceiling.
    """
    if outcome in _NO_VERDICT_OUTCOMES and budget > 0 and cost >= budget * 0.95:
        return "budget-exhausted"
    return outcome


def _main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("classify", help="PR body on stdin -> classification JSON")
    c.add_argument("--head-sha", default="")
    c.add_argument("--marker", default=GATE_MARKER)

    t = sub.add_parser("tier", help="issue body on stdin -> tier JSON")
    t.add_argument("--marker", default=SPEC_MARKER)

    tb = sub.add_parser(
        "tier-batch",
        help="gh issue list JSON array on stdin -> TSV of number/tier/title for "
             "marker-carrying issues only",
    )
    tb.add_argument("--marker", default=SPEC_MARKER)

    b = sub.add_parser("budget-reclass", help="reclassify an outcome by spend")
    b.add_argument("--outcome", required=True)
    b.add_argument("--cost", type=float, default=0.0)
    b.add_argument("--budget", type=float, default=0.0)

    args = p.parse_args(argv)

    if args.cmd == "classify":
        gate = extract_gate(sys.stdin.read(), marker=args.marker)
        out = classify(gate, head_sha=args.head_sha, marker=args.marker)
    elif args.cmd == "tier":
        out = {"tier": tier_of(sys.stdin.read(), marker=args.marker)}
    elif args.cmd == "tier-batch":
        # TSV, not JSON: this replaces a jq program whose output the driver's
        # selection loop already reads field-by-field with `cut`. Emitting the
        # same shape keeps the change to parsing only.
        for row in tier_batch(json.load(sys.stdin), marker=args.marker):
            sys.stdout.write("\t".join(row) + "\n")
        return 0
    else:
        out = {"outcome": budget_reclass(args.outcome, args.cost, args.budget)}

    json.dump(out, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
