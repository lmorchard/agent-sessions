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

# Schema definition for gate block fields per issue #184 and issue #194
_SUBSTITUTE_MARKERS = ("-- via substitute", "clean-by-substitute", "substitute")

REQUIRED_FIELDS = [
    "tier",
    "checks",
    "tamper",
    "project-gates",
    "threads",
    "risk-paths",
    "verdict",
]
OPTIONAL_FIELDS = [
    "guards",
    "freeze",
    "ci",
    "amendments",
    "reason",
]
ALL_FIELDS = REQUIRED_FIELDS + [f for f in OPTIONAL_FIELDS if f not in REQUIRED_FIELDS]

def _is_substituted(val: str) -> bool:
    """Check if a field value explicitly indicates substitution using schema markers."""
    v = (val or "").lower()
    return any(m in v for m in _SUBSTITUTE_MARKERS)


def validate_gate_block(fields: dict[str, str]) -> tuple[bool, list[str]]:
    """Schema validation for gate block fields.

    Covers every required field (`verdict`, `tier`, `checks`, `tamper`,
    `project-gates`, `threads`, `risk-paths`) with enum/format rules.
    Returns (is_valid, list_of_errors).
    """
    errors: list[str] = []
    for f in REQUIRED_FIELDS:
        if f not in fields or not fields[f].strip():
            errors.append(f"missing required field: {f}")

    verdict = fields.get("verdict", "").strip()
    valid_verdicts = ("", "pending", "eligible-for-auto-merge", "human-merge-required")
    if verdict not in valid_verdicts:
        errors.append(f"invalid verdict value: {verdict}")

    return len(errors) == 0, errors


def render_gate_block(fields: dict[str, str]) -> str:
    """Render a human-readable YAML gate block from validated fields structure."""
    lines = ["## Merge gate", "", "```yaml"]
    field_order = [
        "tier", "checks", "guards", "tamper", "freeze",
        "project-gates", "ci", "threads", "risk-paths",
        "amendments", "verdict", "reason"
    ]
    seen = set()
    for k in field_order:
        if k in fields:
            lines.append(f"{k}: {fields[k]}")
            seen.add(k)
    for k, v in fields.items():
        if k not in seen:
            lines.append(f"{k}: {v}")
    lines.extend(["```", ""])
    return "\n".join(lines)
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



def extract_gate(body: str) -> str:
    """Return the YAML block following `## Merge gate`, or "" if absent.

    Finds the first ```yaml or ``` block after the `## Merge gate` heading.
    If unfenced key-value lines exist without code blocks, extracts those.
    """
    if not body:
        return ""

    lines = body.split("\n")
    found_idx = -1
    for i, line in enumerate(lines):
        if line.strip().lower().startswith("## merge gate"):
            found_idx = i
            break

    if found_idx == -1:
        return ""

    remaining = lines[found_idx + 1:]

    # First pass: look for a fenced block under ## Merge gate
    out: list[str] = []
    opened = False
    for line in remaining:
        sline = line.strip()
        if sline.startswith("```"):
            if not opened:
                opened = True
                continue
            break
        if opened:
            out.append(line)

    if opened or out:
        return "\n".join(out)

    # Fallback pass: if no fenced block, collect unfenced key-value lines
    out = []
    for line in remaining:
        sline = line.strip()
        if sline.startswith("#") or sline.startswith("```"):
            break
        if ":" in sline:
            out.append(line)
        elif not sline and out:
            break
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


def evaluate_ci_checks(ci_checks: list[dict] | str) -> tuple[str, str, dict]:
    """Evaluate live CI checks JSON or list of dicts.

    Returns (ci_state, ci_row_str, details) where ci_state is:
    - "pass": all checks passed (total > 0)
    - "no-checks": total == 0
    - "pending": at least one check is pending and no failures
    - "fail": at least one check failed
    - "error": invalid JSON or non-list data
    """
    if isinstance(ci_checks, str):
        try:
            items = json.loads(ci_checks) if ci_checks.strip() else []
        except Exception:
            return "error", "invalid live CI JSON", {"total": 0, "pass": 0, "pending": 0, "fail": 0}
    elif isinstance(ci_checks, list):
        items = ci_checks
    else:
        return "error", "invalid live CI input type", {"total": 0, "pass": 0, "pending": 0, "fail": 0}

    if not isinstance(items, list):
        return "error", "invalid live CI list", {"total": 0, "pass": 0, "pending": 0, "fail": 0}

    valid_items = [item for item in items if isinstance(item, dict)]
    if len(valid_items) == 0:
        return "no-checks", "no checks configured", {"total": 0, "pass": 0, "pending": 0, "fail": 0}

    total = len(valid_items)
    pass_count = 0
    pending_names: list[str] = []
    failing_names: list[str] = []

    for item in valid_items:
        name = str(item.get("name") or "unknown")
        bucket = str(item.get("bucket") or item.get("state") or "").lower()
        if bucket in ("pass", "skipping", "success"):
            pass_count += 1
        elif bucket in ("pending", "in_progress", "queued", "requested", "waiting"):
            pending_names.append(name)
        else:
            failing_names.append(name)

    if failing_names:
        status = f"{pass_count}/{total} pass -- FAILING: {', '.join(failing_names)}"
        return "fail", status, {"total": total, "pass": pass_count, "pending": len(pending_names), "fail": len(failing_names)}

    if pending_names:
        status = f"{pass_count}/{total} pass -- pending: {', '.join(pending_names)}"
        return "pending", status, {"total": total, "pass": pass_count, "pending": len(pending_names), "fail": 0}

    status = f"{total}/{total} pass"
    return "pass", status, {"total": total, "pass": pass_count, "pending": 0, "fail": 0}


#: The rows `verify_gate_rows` grades. `ci` is absent deliberately: `classify` grades CI
#: from the live check results rather than from what the gate block claims about it.
_VERIFIED_ROWS = ("tier", "checks", "guards", "tamper", "project-gates", "threads", "risk-paths")

#: Rows whose provenance can be `substituted`. `tier` cannot: it is a classification the
#: skill makes, not evidence it gathers, so there is nothing for a substitute to stand in for.
_SUBSTITUTABLE_ROWS = ("checks", "guards", "tamper", "project-gates", "ci", "threads", "risk-paths")


def _row_failure(field: str, value: str) -> str | None:
    """Why `field` fails, or `None` if it does not. **The single definition of each row rule.**

    This exists because `verify_gate_rows` and `infer_provenance` encoded the same seven
    predicates twice, line for line, differing only in what they emitted -- a verdict on
    one side and a provenance record on the other. Changing a rule in one and not the
    other makes the gate's verdict disagree with its own account of how it was reached,
    **on the oracle**, and nothing would have caught it: both were tested, separately,
    against their own expectations.

    The reason strings are the ones `verify_gate_rows` has always produced, so a run's
    recorded reason is unchanged.
    """
    if field == "tier":
        if not value:
            return "missing tier field"
        if "needs-review" in value or "unparsed" in value or "conflict" in value:
            return f"tier: {value}"
        return None

    if field == "checks":
        if not value:
            return "missing checks field"
        if "fail" in value or "pending" in value:
            return f"checks row: {value}"
        return None

    if field == "guards":
        # No missing-field case: guards defaults to "none", which is a real answer.
        if "REGRESSED" in value:
            return f"guards row: {value}"
        return None

    if field == "tamper":
        if not value:
            return "missing tamper field"
        if "DIRTY" in value:
            return f"tamper row: {value}"
        if not (value.startswith("clean") or value.startswith("amended")):
            return f"tamper row: {value}"
        return None

    if field == "project-gates":
        if not value:
            return "missing project-gates field"
        if value.startswith("red") or "red:" in value or "fail" in value:
            return f"project-gates row: {value}"
        if "green" not in value and "pass" not in value:
            return f"project-gates row: {value}"
        return None

    if field == "ci":
        # An absent `ci` row is not-applicable rather than failing -- a PR on a repo with
        # no checks has nothing to report. `classify` grades live CI separately.
        if not value:
            return None
        low = value.lower()
        if "fail" in low or "pending" in low:
            return f"ci row: {value}"
        return None

    if field == "threads":
        if not value:
            return "missing threads field"
        if not value.startswith("0 unresolved"):
            return f"threads row: {value}"
        return None

    if field == "risk-paths":
        if not value:
            return "missing risk-paths field"
        if value != "none":
            return f"risk-paths row: {value}"
        return None

    return None


def _row_not_applicable(field: str, value: str) -> bool:
    """True when a row has nothing to report, as distinct from reporting a pass.

    Only two rows have this state: `guards: none` (there were no guards) and a `ci` row
    on a repo with no checks configured. Everything else either passes or fails.
    """
    if field == "guards":
        return value == "none"
    if field == "ci":
        return not value or "no checks" in value.lower()
    return False


def _row_state(field: str, value: str) -> str:
    """One row's provenance: `failed`, `not-applicable`, `substituted` or `real`.

    Order matters and is the original's: a failing row is failed even if its text also
    carries a substitute marker, because how a wrong answer was arrived at is not the
    interesting thing about it.
    """
    if _row_failure(field, value) is not None:
        return "failed"
    if _row_not_applicable(field, value):
        return "not-applicable"
    if field in _SUBSTITUTABLE_ROWS and _is_substituted(value):
        return "substituted"
    return "real"


def verify_gate_rows(fields: dict[str, str]) -> tuple[bool, list[str]]:
    """Verify non-CI gate block rows according to pr-body-template.md.

    Returns (all_ok, list_of_failed_reasons).
    """
    failed = [
        reason
        for field in _VERIFIED_ROWS
        if (reason := _row_failure(field, fields.get(field, "none" if field == "guards" else ""))) is not None
    ]
    return len(failed) == 0, failed


def infer_provenance(fields: dict[str, str]) -> dict[str, str]:
    """How each row was satisfied, recorded alongside the verdict it produced."""
    return {
        field: _row_state(field, fields.get(field, "none" if field == "guards" else ""))
        for field in ("tier", "checks", "guards", "tamper", "project-gates", "ci", "threads", "risk-paths")
    }



def classify(
    gate: str,
    head_sha: str = "",
    ci_checks: list[dict] | str | None = None,
    changed_files: int | None = None,
    pr_files: list[str] | None = None,
    criteria_paths: list[str] | None = None,
) -> dict:
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
        "provenance": {},
        "outcome": "",
        "reason": "",
        "ci_sha": "",
        "ci_stale": False,
        "warnings": [],
    }

    def _check_substitute_and_return(res: dict) -> dict:
        if res.get("outcome") == "gate-eligible":
            sub_fields = []
            for k, v in res.get("fields", {}).items():
                if k not in ("verdict", "reason") and _is_substituted(str(v)):
                    sub_fields.append(k)
            if sub_fields:
                res["outcome"] = "gate-human"
                fields_str = ", ".join(sub_fields)
                res["reason"] = f"gate has row(s) satisfied by substitute: {fields_str}"
        return res

    if changed_files is not None and changed_files == 0:
        result["outcome"] = "gate-human"
        result["reason"] = "PR carries an empty diff (0 changed files) -- work is absent independently of gate block"
        return _check_substitute_and_return(result)

    if pr_files is not None and criteria_paths:
        matched = False
        for cp in criteria_paths:
            cp_clean = cp.strip("`'\" ")
            if any(cp_clean in pf or pf in cp_clean for pf in pr_files):
                matched = True
                break
        if not matched:
            result["warnings"].append(
                f"PR diff touches none of the criteria paths ({', '.join(criteria_paths)})"
            )

    if not result["has_gate"]:
        result["outcome"] = "no-gate"
        result["reason"] = "PR exists but carries no ## Merge gate block"
        return _check_substitute_and_return(result)

    result["fields"] = gate_fields(gate)
    valid, errors = validate_gate_block(result["fields"])
    if not valid:
        result["outcome"] = "no-gate"
        result["reason"] = f"gate block does not validate: {'; '.join(errors)}"
        return _check_substitute_and_return(result)
    result["provenance"] = infer_provenance(result["fields"])
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
        if sha and not head_sha.startswith(sha):
            result["ci_stale"] = True
            result["outcome"] = "ci-stale"
            result["reason"] = (
                f"gate ci row was graded at {sha} but the head is now "
                f'{head_sha[:8]} -- verdict "{verdict}" rests on a commit that '
                "no longer ships"
            )
            return _check_substitute_and_return(result)

        if ci_checks is not None and (not sha or verdict == "pending"):
            ci_state, live_ci_row, _ = evaluate_ci_checks(ci_checks)
            if ci_state != "error":
                sha_suffix = f" @ {head_sha[:7]}" if head_sha and ci_state != "no-checks" else ""
                formatted_ci_row = f"{live_ci_row}{sha_suffix}" if ci_state != "no-checks" else live_ci_row
                result["ci_sha"] = head_sha[:7] if head_sha else ""

                if ci_state == "pending":
                    result["outcome"] = "incomplete"
                    result["reason"] = f"verdict still pending -- live CI checks pending ({formatted_ci_row})"
                    return _check_substitute_and_return(result)
                elif ci_state == "fail":
                    result["outcome"] = "gate-human"
                    result["reason"] = f"live CI checks failed on head {head_sha[:8]} ({formatted_ci_row})"
                    return _check_substitute_and_return(result)
                elif ci_state in ("pass", "no-checks"):
                    all_ok, failed_reasons = verify_gate_rows(result["fields"])
                    if all_ok:
                        result["outcome"] = "gate-eligible"
                        result["reason"] = f"all gate rows satisfied (live CI: {formatted_ci_row})"
                    else:
                        result["outcome"] = "gate-human"
                        result["reason"] = f"live CI passed ({formatted_ci_row}) but gate has failing rows: {'; '.join(failed_reasons)}"
                    return _check_substitute_and_return(result)
                return _check_substitute_and_return(result)

        if not sha and ci_row.strip() and ci_row != "no checks configured":
            # A null must never render as a positive: an unparseable sha also
            # yields "current", so say so rather than reading it as verified.
            result["warnings"].append(
                f"ci row carries no parseable sha ('{ci_row}') -- staleness "
                "UNCHECKED, not verified current. pr-body-template.md requires it."
            )

    if verdict == "eligible-for-auto-merge":
        result["outcome"] = "gate-eligible"
        result["reason"] = reason or "all gate rows satisfied"
    elif verdict == "human-merge-required":
        result["outcome"] = "gate-human"
        result["reason"] = reason or "no reason given (grade_gate.md requires one)"
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
    return _check_substitute_and_return(result)


def tier_of(body: str) -> str:
    """Tier named by an issue body: auto-ok | needs-review | conflict | missing | unparsed.

    The `^## Tier:` anchor is load-bearing: #585's tier paragraph contains the
    string "needs-review" in prose, so an unanchored match reads both tiers and
    the issue looks ambiguous when it is not.

    `conflict` is deliberate rather than a fallback to the first heading. The
    contract is that the body is authoritative and disagreements are surfaced,
    not resolved -- and it fired for real when a re-tiering appended a second
    `## Tier:` heading instead of replacing the first.
    """
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


def tier_batch(issues: list) -> list[tuple[str, str, str]]:
    """(number, tier, title) for every issue passed in.

    Replaces the driver's inline `TIER_JQ` jq program to extract tier headings
    from the issue bodies in batch.
    """
    rows: list[tuple[str, str, str]] = []
    for issue in issues or []:
        body = issue.get("body")
        if body is None:
            continue
        title = str(issue.get("title", "")).replace("\t", " ")
        rows.append((str(issue.get("number", "")), tier_of(body), title))
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
    c.add_argument("--ci-checks", default=None)

    sub.add_parser("tier", help="issue body on stdin -> tier JSON")

    sub.add_parser(
        "tier-batch",
        help="gh issue list JSON array on stdin -> TSV of number/tier/title",
    )

    b = sub.add_parser("budget-reclass", help="reclassify an outcome by spend")
    b.add_argument("--outcome", required=True)
    b.add_argument("--cost", type=float, default=0.0)
    b.add_argument("--budget", type=float, default=0.0)

    args = p.parse_args(argv)

    if args.cmd == "classify":
        gate = extract_gate(sys.stdin.read())
        out = classify(
            gate,
            head_sha=args.head_sha,
            ci_checks=args.ci_checks,
        )
    elif args.cmd == "tier":
        out = {"tier": tier_of(sys.stdin.read())}
    elif args.cmd == "tier-batch":
        # TSV, not JSON: this replaces a jq program whose output the driver's
        # selection loop already reads field-by-field with `cut`. Emitting the
        # same shape keeps the change to parsing only.
        for row in tier_batch(json.load(sys.stdin)):
            sys.stdout.write("\t".join(row) + "\n")
        return 0
    else:
        out = {"outcome": budget_reclass(args.outcome, args.cost, args.budget)}

    json.dump(out, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
