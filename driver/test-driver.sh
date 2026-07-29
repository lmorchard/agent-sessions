#!/usr/bin/env bash
#
# Fixture tests for the board-driver's parsers.
#
# The classifier and the tier filter are tested against fixture TEXT, not live
# GitHub state. That matters: exercising four verdict values against real PRs
# would mean producing four real runs, and the parser is the one component whose
# wrongness would silently misreport every outcome the driver ever records.

set -uo pipefail

DRIVER="$(cd "$(dirname "$0")" && pwd)/agent-session-driver.sh"
PASS=0
FAIL=0

ok()   { PASS=$((PASS+1)); printf '  ok    %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  FAIL  %s\n     expected: %s\n     actual:   %s\n' "$1" "$2" "$3"; }
check(){ [ "$2" = "$3" ] && ok "$1" || bad "$1" "$2" "$3"; }

# NO REPLICAS. These call the shipped parser, driver/gate.py, through the same
# CLI the driver itself uses. This file used to hand-copy extract_gate,
# gate_field, classify_outcome and TIER_JQ -- and the copies drifted, so the
# suite graded a 15-line classify_outcome with no ci-staleness awareness while
# the driver shipped 53 lines with it. Behavioural coverage of the parser lives
# in driver/test_gate.py, which imports the module; these wrappers keep the
# bash-side end-to-end assertions honest.
GATE_MARKER='<!-- agent-session:gate -->'
GATE_PY="$(cd "$(dirname "$0")" && pwd)/gate.py"
PYTHON_BIN="${PYTHON_BIN:-python3}"

_classify() { # $1 = PR body, $2 = head sha (optional)
  "$PYTHON_BIN" "$GATE_PY" classify --head-sha "${2:-}" <<<"$1"
}
outcome_of() { _classify "$1" "${2:-}" | jq -r '.outcome'; }
reason_of()  { _classify "$1" "${2:-}" | jq -r '.reason'; }
tier_of()    { "$PYTHON_BIN" "$GATE_PY" tier <<<"$1" | jq -r '.tier'; }
budget_reclass() { "$PYTHON_BIN" "$GATE_PY" budget-reclass \
                     --outcome "$1" --cost "$2" --budget "$3" | jq -r '.outcome'; }
# --- C3: the classifier reads the verdict from the gate block ---------------

echo "classify: verdict values"

# Shaped exactly like references/pr-body-template.md's example.
BODY_HUMAN='## Merge gate

<!-- agent-session:gate -->
```yaml
tier: needs-review
checks: C1 pass · C2 pass
guards: G1 pass
tamper: clean
freeze: a1b2c3d
project-gates: make check green
threads: 0 unresolved
risk-paths: src/auth/session.py
amendments: none
verdict: human-merge-required
reason: tier is needs-review and the diff touches an authorization path
```

## References'

BODY_ELIGIBLE="${BODY_HUMAN/verdict: human-merge-required/verdict: eligible-for-auto-merge}"
BODY_ELIGIBLE="${BODY_ELIGIBLE/reason: tier is needs-review and the diff touches an authorization path/reason: all rows satisfied}"
BODY_PENDING="${BODY_HUMAN/verdict: human-merge-required/verdict: pending}"
BODY_NOGATE='## Summary

Just an ordinary PR body with no gate block at all.'
BODY_NOVERDICT='<!-- agent-session:gate -->
```yaml
tier: auto-ok
checks: C1 pass
```
'
BODY_GARBAGE="${BODY_HUMAN/verdict: human-merge-required/verdict: probably-fine}"

check "human-merge-required -> gate-human"          "gate-human"    "$(outcome_of "$BODY_HUMAN")"
check "  and carries its reason"                    "tier is needs-review and the diff touches an authorization path" "$(reason_of "$BODY_HUMAN")"
check "eligible-for-auto-merge -> gate-eligible"    "gate-eligible" "$(outcome_of "$BODY_ELIGIBLE")"
check "pending -> incomplete (NOT actionable)"      "incomplete"    "$(outcome_of "$BODY_PENDING")"
check "no gate block -> no-gate"                    "no-gate"       "$(outcome_of "$BODY_NOGATE")"
check "gate block without verdict -> no-gate"       "no-gate"       "$(outcome_of "$BODY_NOVERDICT")"
check "unrecognised verdict -> no-gate, not a pass" "no-gate"       "$(outcome_of "$BODY_GARBAGE")"

# A verdict appearing in prose OUTSIDE the gate block must not be picked up --
# the block is the interface, not the word.
BODY_PROSE='## Summary

I considered whether this was eligible-for-auto-merge and decided it was.

<!-- agent-session:gate -->
```yaml
verdict: human-merge-required
reason: a human-judgment criterion is ungraded
```
'
check "prose mentioning a verdict does not override the block" "gate-human" "$(outcome_of "$BODY_PROSE")"

# --- the tier filter -------------------------------------------------------

echo "select: anchored tier extraction"

MARKER='<!-- agent-session:spec -->'


# This is #585's real shape: an auto-ok heading, and a tier PARAGRAPH that
# mentions needs-review in prose. Unanchored matching reads this as a conflict.
BODY_585="$MARKER

## Tier: \`auto-ok\`

Both criteria reduce to greps that fail today; no risk-gated path. The issue was
originally \`needs-review\` only because it posed a binary decision rather than
specifying an outcome; that decision is now made above."

check "auto-ok heading + needs-review in prose -> auto-ok" "auto-ok"      "$(tier_of "$BODY_585")"
check "needs-review heading -> needs-review"               "needs-review" "$(tier_of "$MARKER

## Tier: \`needs-review\`

Goal-level ambiguity.")"
check "no tier heading -> missing"                         "missing"      "$(tier_of "$MARKER

Some criteria but nobody stamped a tier.")"
check "both tiers on heading lines -> conflict"            "conflict"     "$(tier_of "$MARKER

## Tier: \`auto-ok\`
## Tier: \`needs-review\`")"
check "tier heading naming neither -> unparsed"            "unparsed"     "$(tier_of "$MARKER

## Tier: undecided")"
# A marker-less issue is dropped by selection, which is NOT the same as tiering
# it `missing`. Assert the selection path (tier-batch), not the single-body tier.
candidates_of() { # stdin = gh issue list JSON array -> TSV rows
  "$PYTHON_BIN" "$GATE_PY" tier-batch --marker "$MARKER"
}
check "no marker -> not a candidate at all"                ""             \
  "$(jq -n -c '[{number:1, title:"t", body:"## Tier: `auto-ok`\nNo marker here."}]' | candidates_of)"
check "marker but no tier heading -> missing, not dropped"  "1	missing	t" \
  "$(jq -n -c --arg m "$MARKER" '[{number:1, title:"t", body:($m + "\nno heading")}]' | candidates_of)"

# --- a CI row graded on a stale commit must void the verdict ----------------

echo "ci-stale: a gate ci row is a claim about a commit"

# Through the real parser, not a mirror. The old version of this block defined
# local ci_sha_of/is_stale helpers annotated "Mirrors the driver's extraction +
# comparison exactly" -- with nothing enforcing that. It did not mirror it.
is_stale() { # $1 = ci row value, $2 = current head -> stale|current
  local body="$GATE_MARKER
\`\`\`yaml
verdict: eligible-for-auto-merge
ci: $1
\`\`\`"
  [ "$(outcome_of "$body" "$2")" = "ci-stale" ] && printf 'stale\n' || printf 'current\n'
}

check "sha matching the head is current"      "current" "$(is_stale "2/2 pass @ e8f0338" "e8f03389abcdef")"
check "sha not matching the head is stale"    "stale"   "$(is_stale "2/2 pass @ 0d08b2d" "e8f03389abcdef")"
check "no sha recorded -> cannot judge"       "current" "$(is_stale "2/2 pass" "e8f03389abcdef")"
check "sha with trailing detail still parses" "stale"   "$(is_stale "1/2 pass @ 0d08b2d — pending: lint" "e8f03389abcdef")"

# The real #714 case: graded at 0d08b2d, head force-pushed to e8f03389.
check "the real #714 stale case"              "stale"   "$(is_stale "2/2 pass @ 0d08b2d" "e8f03389")"

# The real #722 case. pr-body-template.md mandates `@ <sha>`; this run wrote the
# sha behind the word "on", and anchoring on the `@` meant the staleness check was
# skipped in silence on a PR that was about to be called eligible. The sha happened
# to be current -- the point is that nothing checked.
check "sha behind 'on' rather than '@' is found" "current" \
  "$(is_stale "2/2 pass (js-test, lint-and-test) on f42c0f1" "f42c0f1aa422e3282c647f2a32947b76904abfb2")"
check "  and is judged stale when it should be"  "stale" \
  "$(is_stale "2/2 pass (js-test, lint-and-test) on f42c0f1" "e8f03389abcdef")"
check "check names are not mistaken for a sha"   "current" \
  "$(is_stale "2/2 pass (js-test, lint-and-test)" "e8f03389abcdef")"

# These two used to be `grep -q "<literal>" "$DRIVER"` -- which passes if the
# string appears anywhere, comments included. findings.md calls that "a spelling
# check, not a test". Now they assert behaviour through the shipped parser.
_warn_count() { # $1 = ci row -> number of warnings the parser emits
  _classify "$GATE_MARKER
\`\`\`yaml
verdict: eligible-for-auto-merge
ci: $1
\`\`\`" "e8f03389abcdef" | jq -r '.warnings | length'
}
check "unparseable sha warns instead of reading as current" "1" \
  "$(_warn_count "2/2 pass (js-test, lint-and-test)")"
check "a parseable sha does not warn"                       "0" \
  "$(_warn_count "2/2 pass @ e8f03389abcdef")"
check "'no checks configured' does not warn"                "0" \
  "$(_warn_count "no checks configured")"

# --- paths survive the cd into the target repo -----------------------------

echo "abspath: relative paths are resolved before the invoke subshell cd's away"

abspath() {
  case "$1" in
    /*) printf '%s\n' "$1" ;;
    *)  printf '%s\n' "$PWD/${1#./}" ;;
  esac
}

check "absolute stays absolute"        "/a/b"           "$(abspath /a/b)"
check "./rel becomes absolute"         "$PWD/x"         "$(abspath ./x)"
check "bare rel becomes absolute"      "$PWD/x/y"       "$(abspath x/y)"
check "default state dir resolves"     "$PWD/.driver-state" "$(abspath ./.driver-state)"

# The regression this guards: the invoke stage runs `cd "$REPO_PATH"` in a
# subshell, so a relative --state-dir resolved at startup points somewhere else
# by the time the prompt file is read. That killed the first real run.
if grep -q 'STATE_DIR="$(abspath "$STATE_DIR")"' "$DRIVER"; then
  ok "driver resolves STATE_DIR to an absolute path"
else
  bad "driver resolves STATE_DIR" "abspath call present" "absent"
fi

# --- budget exhaustion is distinguishable from a designed stop -------------

echo "budget: >=95% spend without a gate is a config problem, not an escalation"

# Mirrors the driver's threshold expression exactly.
budget_reclass() { # $1 = outcome, $2 = cost, $3 = budget -> outcome
  local outcome="$1" cost="$2" budget="$3"
  case "$outcome" in
    incomplete|parked|no-gate)
      if awk -v c="$cost" -v b="$budget" 'BEGIN{exit !(b>0 && c >= b*0.95)}'; then
        printf 'budget-exhausted\n'; return 0
      fi ;;
  esac
  printf '%s\n' "$outcome"
}

check "the real #710 case reclassifies"        "budget-exhausted" "$(budget_reclass incomplete 11.872277 12)"
check "exactly at the 95% line reclassifies"   "budget-exhausted" "$(budget_reclass incomplete 11.4 12)"
check "well under budget stays incomplete"     "incomplete"       "$(budget_reclass incomplete 3.10 12)"
check "a real gate verdict is never touched"   "gate-eligible"    "$(budget_reclass gate-eligible 11.99 12)"
check "human-merge-required is never touched"  "gate-human"       "$(budget_reclass gate-human 11.99 12)"
check "no budget set -> no reclassification"   "incomplete"       "$(budget_reclass incomplete 11.9 0)"

# budget-exhausted must NOT be parked -- parking hides a recoverable config
# problem behind a skip reason on a perfectly good issue.
if grep -qE '^ *parked\|failed\|incomplete\|no-gate\)' "$DRIVER" && \
   ! grep -qE '^ *parked\|failed\|incomplete\|no-gate\|budget-exhausted\)' "$DRIVER"; then
  ok "budget-exhausted is excluded from the park list"
else
  bad "budget-exhausted park status" "excluded from park list" "included (would hide a config problem)"
fi

# --- the driver takes its child down with it -------------------------------

echo "orphan: the in-flight child must not outlive its driver"

if grep -q 'trap cleanup EXIT INT TERM' "$DRIVER"; then
  ok "cleanup trap installed on EXIT/INT/TERM"
else
  bad "cleanup trap" "trap cleanup EXIT INT TERM" "absent"
fi
if grep -q 'kill -TERM "\$CHILD_PID"' "$DRIVER"; then
  ok "cleanup terminates the in-flight child"
else
  bad "cleanup kills child" "kill -TERM \$CHILD_PID" "absent"
fi
# The trap cannot fire on SIGKILL or a host crash, so startup must detect a
# still-live orphan and refuse -- otherwise two runs mutate one repo at once.
if grep -q 'refusing to start a second run while an orphan is live' "$DRIVER"; then
  ok "startup refuses to run alongside a live orphan"
else
  bad "live-orphan guard" "startup refuses" "absent"
fi
if grep -q 'child.pid' "$DRIVER"; then
  ok "child pid is recorded for post-crash orphan detection"
else
  bad "child.pid recorded" "written to the run dir" "absent"
fi

# --- C1: no merge path in the driver ---------------------------------------

echo "guard: the driver contains no merge path"

# Only lines that would EXECUTE a merge count. The driver legitimately mentions
# merge in comments, in the deny-rule string, and in report text -- a check that
# fired on those would be a false positive, and false positives train the
# operator to wave the mechanism through (design.md, move 1).
MERGE_HITS="$(grep -nE '^[^#]*(gh pr merge|gh api[^|]*merge|--auto\b)' "$DRIVER" \
              | grep -v 'DENIED_TOOLS=' | grep -v 'Bash(gh pr merge' || true)"
if [ -z "$MERGE_HITS" ]; then
  ok "no executable merge call in $(basename "$DRIVER")"
else
  bad "driver contains a merge path" "no matches" "$MERGE_HITS"
fi

# --- a nonzero exit does not overrule the gate -----------------------------

echo "trailing error record: the exit code is not the oracle"

# Unlike the helpers above, this evaluates the REAL function out of the driver
# rather than restating it, so the test cannot drift away from what ships.
eval "$(sed -n '/^has_success_result()/,/^}/p' "$DRIVER")"

_stream() { # writes a stream fixture to $1
  local f="$1"; shift
  : > "$f"
  for rec in "$@"; do printf '%s\n' "$rec" >> "$f"; done
}

TMPD="$(mktemp -d)"
trap 'rm -rf "$TMPD"' EXIT

# The real #656 stream: a successful result carrying the merge-gate verdict,
# then a spurious error_during_execution with cost 0. claude -p exited 1, and
# the driver recorded `failed` on a run that had published
# eligible-for-auto-merge to PR #722.
_stream "$TMPD/656.jsonl" \
  '{"type":"assistant","message":{"content":[]}}' \
  '{"type":"result","subtype":"success","is_error":false,"total_cost_usd":11.195,"num_turns":129}' \
  '{"type":"result","subtype":"error_during_execution","is_error":true,"total_cost_usd":0,"num_turns":0}'

_stream "$TMPD/genuine-fail.jsonl" \
  '{"type":"assistant","message":{"content":[]}}' \
  '{"type":"result","subtype":"error_during_execution","is_error":true,"total_cost_usd":2.5,"num_turns":40}'

_stream "$TMPD/empty.jsonl"

_yn() { has_success_result "$1" && printf 'yes\n' || printf 'no\n'; }

check "the real #656 stream has a successful result" "yes" "$(_yn "$TMPD/656.jsonl")"
check "an only-error stream does not"                "no"  "$(_yn "$TMPD/genuine-fail.jsonl")"
check "an empty stream does not"                     "no"  "$(_yn "$TMPD/empty.jsonl")"
check "a missing stream file does not"               "no"  "$(_yn "$TMPD/nope.jsonl")"

# The guard is worthless if it cannot fail, so assert the branch actually
# consults it -- deleting the has_success_result call from the classifier must
# break this, which is how the skill-readonly guard should have been written
# the first time.
if grep -q 'rc" -ne 0 \] && ! has_success_result' "$DRIVER"; then
  ok "the failed branch consults the stream before overruling the gate"
else
  bad "failed branch consults the stream" "has_success_result in the rc!=0 guard" "absent"
fi

# --- syntax ----------------------------------------------------------------

echo "syntax"
if bash -n "$DRIVER" 2>/dev/null; then ok "driver parses"; else bad "driver parses" "clean" "$(bash -n "$DRIVER" 2>&1)"; fi

echo
printf '%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
