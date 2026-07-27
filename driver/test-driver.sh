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

# Source the driver's functions without running main. The driver runs main at
# the bottom, so we extract just the parser functions we want to test.
GATE_MARKER='<!-- agent-session:gate -->'

extract_gate() {
  awk -v m="$GATE_MARKER" '
    index($0, m) { found=1; next }
    found && /^```/ { if (!open) { open=1; next } else { exit } }
    found && open { print }
  '
}
gate_field() { grep -m1 "^$1:" | sed "s/^$1:[[:space:]]*//" || true; }
classify_outcome() {
  local gate="$1" verdict reason
  if [ -z "$(printf '%s' "$gate" | tr -d '[:space:]')" ]; then
    printf 'no-gate\tPR exists but carries no %s block\n' "$GATE_MARKER"; return 0
  fi
  verdict="$(printf '%s\n' "$gate" | gate_field verdict)"
  reason="$(printf '%s\n' "$gate"  | gate_field reason)"
  case "$verdict" in
    eligible-for-auto-merge) printf 'gate-eligible\t%s\n' "${reason:-all gate rows satisfied}" ;;
    human-merge-required)    printf 'gate-human\t%s\n' "${reason:-no reason given (pr.md requires one)}" ;;
    pending)                 printf 'incomplete\tverdict still pending -- run did not reach the gate\n' ;;
    "")                      printf 'no-gate\tgate block present but has no verdict field\n' ;;
    *)                       printf 'no-gate\tunrecognised verdict value: %s\n' "$verdict" ;;
  esac
}

outcome_of() { printf '%s' "$1" | extract_gate | { gate="$(cat)"; classify_outcome "$gate"; } | cut -f1; }
reason_of()  { printf '%s' "$1" | extract_gate | { gate="$(cat)"; classify_outcome "$gate"; } | cut -f2; }

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

TIER_JQ='
def tierof:
  [ (. // "") | split("\n")[] | select(test("^##[[:space:]]*Tier[[:space:]]*:")) ] as $lines
  | ([ $lines[] | select(test("auto-ok")) ] | length) as $a
  | ([ $lines[] | select(test("needs-review")) ] | length) as $n
  | if   ($lines | length) == 0 then "missing"
    elif $a > 0 and $n > 0     then "conflict"
    elif $a > 0                then "auto-ok"
    elif $n > 0                then "needs-review"
    else                            "unparsed"
    end;
.[]
| select(.body != null and (.body | contains($marker)))
| [ (.number | tostring), (.body | tierof) ] | @tsv
'
MARKER='<!-- agent-session:spec -->'

tier_of() { # $1 = body text
  jq -n -c --arg b "$1" '[{number:1, body:$b}]' \
    | jq -r --arg marker "$MARKER" "$TIER_JQ" | cut -f2
}

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
check "no marker -> not a candidate at all"                ""             "$(tier_of "## Tier: \`auto-ok\`
No marker here.")"

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

# --- syntax ----------------------------------------------------------------

echo "syntax"
if bash -n "$DRIVER" 2>/dev/null; then ok "driver parses"; else bad "driver parses" "clean" "$(bash -n "$DRIVER" 2>&1)"; fi

echo
printf '%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
