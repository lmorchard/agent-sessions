"""Tests for driver/gate.py.

These **import** the module under test. That is the entire point of the file:
`driver/test-driver.sh` used to hand-copy the driver's parsers, the copies
drifted, and the suite ended up grading a replica that disagreed with what
shipped. No parsing or classification logic is defined here -- if a test needs
behaviour, it calls `gate`.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import gate  # noqa: E402


def body_with(
    ci_row,
    verdict="eligible-for-auto-merge",
    reason=None,
    checks="C1 pass",
    tamper="clean",
    project_gates="make check green",
    threads="0 unresolved",
    risk_paths="none",
):
    """Build a PR body shaped like pr-body-template.md emits."""
    lines = [
        "## Merge gate",
        "",
        gate.GATE_MARKER,
        "```yaml",
        "tier: auto-ok",
        f"checks: {checks}",
        f"tamper: {tamper}",
        f"project-gates: {project_gates}",
        f"threads: {threads}",
        f"risk-paths: {risk_paths}",
        f"verdict: {verdict}",
    ]
    if ci_row is not None:
        lines.append(f"ci: {ci_row}")
    if reason is not None:
        lines.append(f"reason: {reason}")
    lines += ["```", "", "trailing prose"]
    return "\n".join(lines)


# --- extraction ------------------------------------------------------------

def test_extract_gate_returns_block_contents():
    got = gate.extract_gate(body_with("2/2 pass @ abc1234"))
    assert "verdict: eligible-for-auto-merge" in got
    assert "trailing prose" not in got
    assert "## Merge gate" not in got


def test_extract_gate_absent_marker_is_empty():
    assert gate.extract_gate("no gate here\n```\nstuff\n```") == ""


def test_extract_gate_empty_marker_is_empty():
    """`extract_gate()` will behave incorrectly if called with an empty `marker`. Add guard."""
    assert gate.extract_gate("some\n\n```\nstuff\n```", marker="") == ""


def test_extract_gate_stops_at_closing_fence():
    assert "trailing prose" not in gate.extract_gate(body_with("2/2 pass"))


def test_gate_field_missing_is_empty_string():
    assert gate.gate_field(gate.extract_gate(body_with("2/2 pass")), "nope") == ""


def test_gate_field_strips_leading_whitespace_only():
    assert gate.gate_field("ci:    2/2 pass   ", "ci") == "2/2 pass   "


# --- ci staleness: the regression this module exists for --------------------

@pytest.mark.parametrize("ci_row,expected", [
    ("2/2 pass @ e8f0338", "e8f0338"),
    ("2/2 pass (js-test, lint-and-test) on f42c0f1", "f42c0f1"),
    ("1/2 pass @ 0d08b2d - pending: lint", "0d08b2d"),
    ("2/2 pass (js-test, lint-and-test)", ""),
    ("no checks configured", ""),
])
def test_ci_sha_finds_a_bare_token_not_a_delimiter(ci_row, expected):
    """#722 wrote the sha behind 'on' rather than '@'; anchoring on '@' no-oped."""
    assert gate.ci_sha(ci_row) == expected


def test_stale_ci_voids_the_verdict():
    """The named case. Mutating gate.py's {7,40} regex must break this."""
    g = gate.extract_gate(body_with("2/2 pass @ 0d08b2d"))
    r = gate.classify(g, head_sha="e8f03389abcdef")
    assert r["outcome"] == "ci-stale"
    assert r["ci_stale"] is True
    assert "no longer ships" in r["reason"]


def test_stale_ci_detected_when_sha_is_behind_the_word_on():
    g = gate.extract_gate(body_with("2/2 pass (js-test, lint-and-test) on f42c0f1"))
    assert gate.classify(g, head_sha="e8f03389abcdef")["outcome"] == "ci-stale"


def test_current_ci_sha_is_not_stale():
    g = gate.extract_gate(body_with("2/2 pass @ f42c0f1"))
    r = gate.classify(g, head_sha="f42c0f1aa422e3282c647f2a32947b76904abfb2")
    assert r["outcome"] == "gate-eligible"
    assert r["ci_stale"] is False


def test_unparseable_sha_warns_rather_than_reading_as_current():
    """A null must never render as a positive: no sha also yields 'current'."""
    g = gate.extract_gate(body_with("2/2 pass (js-test, lint-and-test)"))
    r = gate.classify(g, head_sha="e8f03389abcdef")
    assert r["outcome"] == "gate-eligible"
    assert any("UNCHECKED" in w for w in r["warnings"])


def test_no_checks_configured_does_not_warn():
    g = gate.extract_gate(body_with("no checks configured"))
    assert gate.classify(g, head_sha="e8f03389abcdef")["warnings"] == []


def test_no_head_sha_skips_staleness_entirely():
    g = gate.extract_gate(body_with("2/2 pass @ 0d08b2d"))
    assert gate.classify(g, head_sha="")["outcome"] == "gate-eligible"


# --- verdict vocabulary ----------------------------------------------------

@pytest.mark.parametrize("verdict,outcome", [
    ("eligible-for-auto-merge", "gate-eligible"),
    ("human-merge-required", "gate-human"),
    ("pending", "incomplete"),
    ("", "no-gate"),
    ("weird-new-value", "no-gate"),
])
def test_verdict_maps_to_outcome(verdict, outcome):
    g = gate.extract_gate(body_with("2/2 pass", verdict=verdict))
    assert gate.classify(g)["outcome"] == outcome


def test_missing_gate_block_is_no_gate():
    r = gate.classify(gate.extract_gate("a PR body with no gate"))
    assert r["outcome"] == "no-gate"
    assert r["has_gate"] is False
    assert gate.GATE_MARKER in r["reason"]


def test_reason_defaults_are_supplied():
    g = gate.extract_gate(body_with("2/2 pass", verdict="human-merge-required"))
    assert "pr.md requires one" in gate.classify(g)["reason"]


def test_explicit_reason_wins_over_the_default():
    g = gate.extract_gate(body_with("2/2 pass", reason="tier is needs-review"))
    assert gate.classify(g)["reason"] == "tier is needs-review"


# --- tier extraction ------------------------------------------------------

def _issue(*tier_lines):
    return "\n".join([gate.SPEC_MARKER, "", "prose", *tier_lines])


@pytest.mark.parametrize("lines,expected", [
    (["## Tier: `auto-ok`"], "auto-ok"),
    (["## Tier: `needs-review`"], "needs-review"),
    (["## Tier: undecided"], "unparsed"),
    ([], "missing"),
    (["## Tier: `needs-review`", "## Tier: `auto-ok` (revised)"], "conflict"),
])
def test_tier_of(lines, expected):
    assert gate.tier_of(_issue(*lines)) == expected


def test_tier_anchor_ignores_the_phrase_in_prose():
    """#585's tier paragraph says 'needs-review' in prose; unanchored reads both."""
    body = _issue("## Tier: `auto-ok`") + "\n\nThis is not needs-review because ..."
    assert gate.tier_of(body) == "auto-ok"


def test_no_marker_is_missing():
    assert gate.tier_of("## Tier: `auto-ok`\nno marker") == "missing"


def test_shipped_spec_template_parses_through_the_shipped_parser():
    """The template the skill tells authors to copy must be readable by the parser.

    It was not: `spec-template.md` shipped a bare `## Tier` heading, which the
    `^## Tier:` anchor does not match, so `tier_of` returned "missing" for the
    very shape the skill prescribes. A grep for the heading string would not have
    caught it -- adding only the colon yields "unparsed", and a
    `[auto-ok | needs-review]` placeholder yields "conflict". Only routing the
    shipped artifact through the shipped parser distinguishes those.

    `marker=""` is deliberate: with the default marker this passes on the
    spec-marker string appearing in the template's *prose*, which is evidence
    adjacent to what the check names. This asserts the tier anchor alone.
    """
    template = (
        Path(__file__).parent.parent
        / "skills/agent-session/references/spec-template.md"
    ).read_text()
    assert gate.tier_of(template, marker="") in ("auto-ok", "needs-review")


# --- budget reclassification ----------------------------------------------

@pytest.mark.parametrize("outcome,cost,budget,expected", [
    ("incomplete", 11.87, 12.0, "budget-exhausted"),
    ("no-gate", 11.87, 12.0, "budget-exhausted"),
    ("incomplete", 4.41, 12.0, "incomplete"),
    ("gate-eligible", 11.99, 12.0, "gate-eligible"),
    ("incomplete", 11.87, 0.0, "incomplete"),
])
def test_budget_reclass(outcome, cost, budget, expected):
    assert gate.budget_reclass(outcome, cost, budget) == expected


# --- the CLI the driver actually calls ------------------------------------

def _run(args, stdin):
    r = subprocess.run([sys.executable, str(Path(__file__).parent / "gate.py"), *args],
                       input=stdin, capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def test_cli_classify_emits_normalised_json():
    out = _run(["classify", "--head-sha", "e8f03389"], body_with("2/2 pass @ 0d08b2d"))
    assert out["outcome"] == "ci-stale"
    assert out["fields"]["tier"] == "auto-ok"


def test_cli_tier():
    assert _run(["tier"], _issue("## Tier: `auto-ok`"))["tier"] == "auto-ok"


def test_cli_budget_reclass():
    out = _run(["budget-reclass", "--outcome", "incomplete",
                "--cost", "11.87", "--budget", "12"], "")
    assert out["outcome"] == "budget-exhausted"


def test_module_imports_without_site_packages():
    """C5: gate.py must stay stdlib-only so the driver remains portable."""
    d = Path(__file__).parent
    subprocess.run([sys.executable, "-I", "-S", "-c",
                    f"import sys; sys.path.insert(0, {str(d)!r}); import gate"],
                   check=True, capture_output=True)


# --- selection: tier-batch (replaces the driver's inline TIER_JQ) -----------

def test_tier_batch_drops_marker_less_issues():
    """Dropped is not the same as `missing`, and collapsing them would hide a defect."""
    rows = gate.tier_batch([{"number": 1, "title": "t", "body": "## Tier: `auto-ok`"}])
    assert rows == []


def test_tier_batch_reports_missing_for_specced_issue_with_no_heading():
    rows = gate.tier_batch([{"number": 7, "title": "t", "body": gate.SPEC_MARKER}])
    assert rows == [("7", "missing", "t")]


def test_tier_batch_tabs_in_titles_are_neutralised():
    """The driver reads these rows with `cut -f`, so an embedded tab would shift fields."""
    rows = gate.tier_batch(
        [{"number": 3, "title": "a\tb", "body": gate.SPEC_MARKER + "\n## Tier: `auto-ok`"}])
    assert rows == [("3", "auto-ok", "a b")]


def test_tier_batch_null_body_is_skipped_not_crashed():
    assert gate.tier_batch([{"number": 1, "title": "t", "body": None}]) == []


def test_tier_batch_surfaces_conflict_rather_than_picking():
    body = gate.SPEC_MARKER + "\n## Tier: `needs-review`\n## Tier: `auto-ok` (revised)"
    assert gate.tier_batch([{"number": 5, "title": "t", "body": body}])[0][1] == "conflict"


# --- issue #19: marker line-anchoring tests -------------------------------

def test_inline_code_span_spec_marker_does_not_count_as_spec_marker():
    """#19 C1: spec marker in inline code span must not trigger tier_batch or tier_of."""
    quoting_body = (
        "An issue quoting `<!-- agent-session:spec -->` inline in prose\n\n"
        "## Tier: `auto-ok`"
    )
    bare_body = (
        f"{gate.SPEC_MARKER}\n\n"
        "An issue with bare marker\n\n"
        "## Tier: `auto-ok`"
    )
    # (a) tier_batch on a code-span-only body returns []
    assert gate.tier_batch([{"number": 1, "title": "t", "body": quoting_body}]) == []
    # (b) tier_of on the same body returns "missing"
    assert gate.tier_of(quoting_body) == "missing"
    # (c) positive control: bare marker body emits row with tier
    assert gate.tier_batch([{"number": 2, "title": "t2", "body": bare_body}]) == [
        ("2", "auto-ok", "t2")
    ]


def test_inline_code_span_gate_marker_does_not_extract_gate():
    """#19 C2: gate marker in inline code span must not extract a gate block."""
    quoting_pr_body = (
        "PR body quoting `<!-- agent-session:gate -->` inline\n"
        "```yaml\n"
        "verdict: eligible-for-auto-merge\n"
        "```"
    )
    bare_pr_body = body_with("2/2 pass @ abc1234")

    # (a) extract_gate on code-span-only PR body returns empty string
    assert gate.extract_gate(quoting_pr_body) == ""
    # (b) positive control: real gate block is extracted
    assert "verdict: eligible-for-auto-merge" in gate.extract_gate(bare_pr_body)


def test_corpus_bodies_snapshot_verdicts():
    """#19 GUARD: snapshot corpus bodies whose marker sits alone on line 1 keep exact verdicts."""
    corpus = [
        (f"{gate.SPEC_MARKER}\n## Tier: `auto-ok`", "auto-ok"),
        (f"{gate.SPEC_MARKER}\n## Tier: `needs-review`", "needs-review"),
        (f"{gate.SPEC_MARKER}\n## Tier: undecided", "unparsed"),
        (f"{gate.SPEC_MARKER}\nno tier heading", "missing"),
        (f"{gate.SPEC_MARKER}\n## Tier: `needs-review`\n## Tier: `auto-ok` (revised)", "conflict"),
    ]
    for body, expected in corpus:
        assert gate.tier_of(body) == expected


# --- issue #30: live CI grading for pending/unparseable verdicts -----------

def test_evaluate_ci_checks_distinguishes_four_states():
    """#30 C2: evaluate_ci_checks distinguishes pass, no-checks, pending, fail."""
    # 1. pass
    state, status, details = gate.evaluate_ci_checks([
        {"name": "c1", "bucket": "pass"},
        {"name": "c2", "bucket": "pass"},
    ])
    assert state == "pass"
    assert status == "2/2 pass"
    assert details["total"] == 2

    # 2. no checks configured
    state, status, details = gate.evaluate_ci_checks([])
    assert state == "no-checks"
    assert status == "no checks configured"
    assert details["total"] == 0

    # 3. pending
    state, status, details = gate.evaluate_ci_checks([
        {"name": "c1", "bucket": "pass"},
        {"name": "c2", "bucket": "pending"},
    ])
    assert state == "pending"
    assert "pending: c2" in status
    assert details["pending"] == 1

    # 4. fail
    state, status, details = gate.evaluate_ci_checks([
        {"name": "c1", "bucket": "fail"},
    ])
    assert state == "fail"
    assert "FAILING: c1" in status
    assert details["fail"] == 1


def test_classify_pending_verdict_with_live_ci_passed():
    """#30 C1: unparseable sha + live CI pass -> no warning, outcome gate-eligible."""
    body = body_with("not yet graded", verdict="pending")
    g = gate.extract_gate(body)
    ci_checks = [{"name": "c1", "bucket": "pass"}, {"name": "c2", "bucket": "pass"}]
    r = gate.classify(g, head_sha="abc123456789", ci_checks=ci_checks)

    assert r["outcome"] == "gate-eligible"
    assert r["warnings"] == []
    assert "2/2 pass @ abc1234" in r["reason"]
    assert "abc1234" in r["reason"]


def test_classify_pending_verdict_three_outcomes_for_three_ci_states():
    """#30 C2: three live CI states -> three outcomes for pending verdict."""
    body = body_with("not yet graded", verdict="pending")
    g = gate.extract_gate(body)
    head_sha = "abc123456789"

    # 1. CI passed -> gate-eligible
    r_pass = gate.classify(g, head_sha=head_sha, ci_checks=[{"name": "c1", "bucket": "pass"}])
    assert r_pass["outcome"] == "gate-eligible"
    assert "no checks configured" not in r_pass["reason"]

    # 2. No checks configured -> gate-eligible with "no checks configured" in reason
    r_nochecks = gate.classify(g, head_sha=head_sha, ci_checks=[])
    assert r_nochecks["outcome"] == "gate-eligible"
    assert "no checks configured" in r_nochecks["reason"]

    # 3. Checks pending -> incomplete
    r_pending = gate.classify(g, head_sha=head_sha, ci_checks=[{"name": "c1", "bucket": "pending"}])
    assert r_pending["outcome"] == "incomplete"
    assert "checks pending" in r_pending["reason"]


def test_classify_pending_verdict_live_ci_failing():
    """#30 C2: live CI failing -> gate-human."""
    body = body_with("not yet graded", verdict="pending")
    g = gate.extract_gate(body)
    r = gate.classify(g, head_sha="abc123456789", ci_checks=[{"name": "c1", "bucket": "fail"}])
    assert r["outcome"] == "gate-human"
    assert "FAILING: c1" in r["reason"]


def test_evaluate_ci_checks_handles_invalid_json_and_non_dicts():
    """Copilot feedback: invalid JSON/types should return error state, not false positive."""
    # Invalid JSON string -> error
    state, msg, _ = gate.evaluate_ci_checks("{invalid json")
    assert state == "error"
    assert "invalid" in msg

    # Non-list input -> error
    state, msg, _ = gate.evaluate_ci_checks({"not": "a list"})
    assert state == "error"

    # List with non-dict elements -> filters valid items, total is valid items only
    state, status, details = gate.evaluate_ci_checks([
        "invalid element",
        {"name": "c1", "bucket": "pass"},
    ])
    assert state == "pass"
    assert details["total"] == 1
    assert status == "1/1 pass"


def test_classify_live_ci_pass_verifies_all_gate_rows():
    """Copilot feedback: live CI pass must still verify project-gates, threads, tamper, etc."""
    # 1. Failing project-gates -> gate-human
    body_red_gates = body_with("not yet graded", verdict="pending", project_gates="red: test failed")
    r1 = gate.classify(gate.extract_gate(body_red_gates), head_sha="abc123456789", ci_checks=[{"name": "c1", "bucket": "pass"}])
    assert r1["outcome"] == "gate-human"
    assert "project-gates row" in r1["reason"]

    # 2. Failing threads -> gate-human
    body_unresolved = body_with("not yet graded", verdict="pending", threads="2 unresolved")
    r2 = gate.classify(gate.extract_gate(body_unresolved), head_sha="abc123456789", ci_checks=[{"name": "c1", "bucket": "pass"}])
    assert r2["outcome"] == "gate-human"
    assert "threads row" in r2["reason"]

    # 3. Failing risk-paths -> gate-human
    body_risk = body_with("not yet graded", verdict="pending", risk_paths="driver/gate.py")
    r3 = gate.classify(gate.extract_gate(body_risk), head_sha="abc123456789", ci_checks=[{"name": "c1", "bucket": "pass"}])
    assert r3["outcome"] == "gate-human"
    assert "risk-paths row" in r3["reason"]


def test_infer_provenance_states():
    """#83: test infer_provenance returns correct states for different row formats."""
    # Real / passed states
    fields_real = {
        "tier": "auto-ok",
        "checks": "C1 pass · C2 pass",
        "guards": "G1 pass",
        "tamper": "clean",
        "project-gates": "make check green",
        "ci": "2/2 pass @ abc1234",
        "threads": "0 unresolved",
        "risk-paths": "none"
    }
    p_real = gate.infer_provenance(fields_real)
    assert p_real["tier"] == "real"
    assert p_real["checks"] == "real"
    assert p_real["guards"] == "real"
    assert p_real["tamper"] == "real"
    assert p_real["project-gates"] == "real"
    assert p_real["ci"] == "real"
    assert p_real["threads"] == "real"
    assert p_real["risk-paths"] == "real"

    # Substituted states
    fields_sub = {
        "tier": "auto-ok",
        "checks": "C1 pass -- via substitute",
        "guards": "none",
        "tamper": "clean-by-substitute -- basis",
        "project-gates": "make check green",
        "ci": "no checks configured",
        "threads": "0 unresolved -- via substitute",
        "risk-paths": "none"
    }
    p_sub = gate.infer_provenance(fields_sub)
    assert p_sub["checks"] == "substituted"
    assert p_sub["guards"] == "not-applicable"
    assert p_sub["tamper"] == "substituted"
    assert p_sub["ci"] == "not-applicable"
    assert p_sub["threads"] == "substituted"

    # Failed states
    fields_fail = {
        "tier": "needs-review",
        "checks": "C1 fail",
        "guards": "G1 REGRESSED",
        "tamper": "DIRTY",
        "project-gates": "red: test failed",
        "ci": "1/2 pass @ abc1234 -- FAILING: test",
        "threads": "2 unresolved",
        "risk-paths": "driver/gate.py"
    }
    p_fail = gate.infer_provenance(fields_fail)
    assert p_fail["tier"] == "failed"
    assert p_fail["checks"] == "failed"
    assert p_fail["guards"] == "failed"
    assert p_fail["tamper"] == "failed"
    assert p_fail["project-gates"] == "failed"
    assert p_fail["ci"] == "failed"
    assert p_fail["threads"] == "failed"
    assert p_fail["risk-paths"] == "failed"


def test_classify_includes_provenance():
    """#83: classify returns a dictionary with parsed provenance data."""
    body = body_with("2/2 pass @ e8f0338", threads="0 unresolved -- via substitute")
    g = gate.extract_gate(body)
    r = gate.classify(g, head_sha="e8f03389abcdef")
    assert "provenance" in r
    assert r["provenance"]["threads"] == "substituted"
    assert r["provenance"]["ci"] == "real"
    assert r["provenance"]["guards"] == "not-applicable"




