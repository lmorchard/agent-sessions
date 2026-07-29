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

# --- a skill dir nested inside the target checkout -------------------------

echo "nested skill-dir: the flags must not be able to describe a self-editing run"

# The hosted run cd's into --repo-path and is granted --add-dir on --skill-dir.
# If the skill lives INSIDE the checkout, the run's own working tree contains the
# instructions grading it, and the Edit/Write deny rules assembled from SKILL_DIR
# are the only thing standing between the implementer and its own oracle. That
# configuration reads as entirely ordinary from the flags alone -- nothing about
# `--skill-dir ./skills/agent-session --repo-path .` looks wrong -- which is
# exactly why startup has to say so rather than leave it to the deny rules.
#
# Every case here invokes the SHIPPED driver as a subprocess, never a restatement
# of its validation. Any configuration that survives validation dies at the
# driver's required-command check: no network, no claude, no state dir. The exit
# status cannot discriminate -- the guarded and unguarded paths both exit 2 -- so
# every case asserts the stderr text instead.
#
# That stop-point is CONSTRUCTED, not inherited. This section used to pin
# PATH=/usr/bin:/bin and rely on gh not being installed there: true on the
# authoring host, guaranteed nowhere, and on a host carrying /usr/bin/gh these
# cases would sail past validation toward real GitHub calls and a state-dir write
# -- with no --dry-run and --max-issues defaulting to 1, that reaches a live
# claude invocation. So the harness now BUILDS the PATH (see NEST_BIN below):
# symlinks for exactly the commands the driver legitimately needs, and
# deliberately no gh. `gh` is first in the driver's own `for c in gh jq git` loop,
# so its absence is what every reached-validation case observes, and that absence
# is now a property of a directory this file created rather than of the host.

NEST_LITERAL='--skill-dir is inside --repo-path'
NEST_ROOT="$(cd "$(dirname "$DRIVER")/.." && pwd)"
NEST_SKILL="$NEST_ROOT/skills/agent-session"

# Its own temp dir rather than sharing $TMPD, so this section does not silently
# depend on sitting below the block that creates it. The trap names both; each is
# set long before EXIT fires.
NEST_TMP="$(mktemp -d)"
trap 'rm -rf "$TMPD" "$NEST_TMP"' EXIT

# The constructed PATH. Symlinks for the commands the driver legitimately reaches
# before (and at) its required-command loop, and NO gh.
#
# `date` is here because log() calls it at agent-session-driver.sh:64, and the
# containment warning goes through log(); without it the cases still assert
# correctly but every run prints `date: command not found` twice, which is noise a
# future reader would have to re-derive as harmless. jq/git/python3 are the rest
# of what the driver requires, so a case that reaches the loop fails on gh
# SPECIFICALLY rather than on whichever check happened to come first.
#
# bash is resolved HERE, against the ambient PATH, and invoked by absolute path
# below. The driver's `#!/usr/bin/env bash` shebang would otherwise be resolved
# against the constructed PATH and die with `env: bash: No such file or directory`
# before the script ran at all -- measured, not theorised.
NEST_BIN="$NEST_TMP/bin"
mkdir -p "$NEST_BIN"
NEST_BASH="$(command -v bash)"
if [ -z "$NEST_BASH" ]; then
  printf 'harness precondition: bash not found on PATH\n' >&2; exit 1
fi
for _c in date jq git python3; do
  _p="$(command -v "$_c")"
  if [ -z "$_p" ]; then
    printf 'harness precondition: %s not found on PATH (needed to build the hermetic bin dir)\n' "$_c" >&2
    exit 1
  fi
  ln -sf "$_p" "$NEST_BIN/$_c"
done
# The one thing that must NOT be there. Asserted rather than assumed, because the
# entire section's meaning depends on it and a stray symlink would make every
# reached-validation case proceed to a live run instead of stopping.
if [ -e "$NEST_BIN/gh" ]; then
  printf 'harness precondition: gh must not exist in the constructed bin dir\n' >&2; exit 1
fi

_nest_run() { # $1 = cwd, rest = driver args; sets NEST_ERR and NEST_RC
  local cwd="$1"; shift
  NEST_ERR="$( ( cd "$cwd" && PATH="$NEST_BIN" "$NEST_BASH" "$DRIVER" "$@" ) 2>&1 >/dev/null )"
  NEST_RC=$?
}

# Reduce the run to a short comparable token, but derive it from the real stderr
# with a literal substring match -- the assertion is on the message, not on a
# constant the harness made up.
_nest_warned()  { case "$NEST_ERR" in *"$NEST_LITERAL"*) printf 'warned\n' ;; *) printf 'no-warn\n' ;; esac; }
_nest_reached() { case "$NEST_ERR" in *'required command not found: gh'*) printf 'gh-check\n' ;;
                                      *) printf 'stopped-early\n' ;; esac; }
_nest_verdict() { printf '%s %s\n' "$(_nest_warned)" "$(_nest_reached)"; }
_nest_first()   { printf '%s\n' "${NEST_ERR%%$'\n'*}"; }
_nest_made()    { [ -d "$1" ] && printf 'created\n' || printf 'absent\n'; }

# C1. The skill directory of this very repo, inside this very repo.
_nest_run "$NEST_ROOT" --repo lmorchard/agent-sessions \
  --skill-dir "$NEST_SKILL" --repo-path "$NEST_ROOT" --state-dir "$NEST_TMP/s-nested"
check "nested --skill-dir warns with the literal message" "warned" "$(_nest_warned)"
check "  and exits 2"                                     "2"      "$NEST_RC"
check "  and does not create the state dir"               "absent" "$(_nest_made "$NEST_TMP/s-nested")"

# C2. The degenerate containment case: a directory contains itself.
_nest_run "$NEST_ROOT" --repo lmorchard/agent-sessions \
  --skill-dir "$NEST_SKILL" --repo-path "$NEST_SKILL" --state-dir "$NEST_TMP/s-same"
check "identical --skill-dir and --repo-path warn the same way" "warned" "$(_nest_warned)"

# C3. Containment is a fact about resolved paths, not about argument strings. A
# comparison done on the raw arguments passes both of these straight through.
_nest_run "$NEST_ROOT" --repo lmorchard/agent-sessions \
  --skill-dir ./skills/agent-session --repo-path . --state-dir "$NEST_TMP/s-rel"
check "relative paths still detect containment" "warned" "$(_nest_warned)"

_nest_run "$NEST_ROOT" --repo lmorchard/agent-sessions \
  --skill-dir "$NEST_ROOT/driver/../skills/agent-session" --repo-path "$NEST_ROOT" \
  --state-dir "$NEST_TMP/s-dotdot"
check ".. in the path still detects containment" "warned" "$(_nest_warned)"

# C4. The escape hatch still warns -- an operator who opts in should see what
# they opted into in the log, not a silent pass.
_nest_run "$NEST_ROOT" --repo lmorchard/agent-sessions --allow-nested-skill-dir \
  --skill-dir "$NEST_SKILL" --repo-path "$NEST_ROOT" --state-dir "$NEST_TMP/s-allow"
check "--allow-nested-skill-dir proceeds past validation" "gh-check" "$(_nest_reached)"
check "  and warns on the way through"                    "warned"   "$(_nest_warned)"

# The control probe. Not a criterion: it proves the message assertions above are
# real discriminators rather than a token the harness always prints.
_nest_run "$NEST_ROOT" --repo lmorchard/agent-sessions \
  --skill-dir /nope --repo-path "$NEST_ROOT" --state-dir "$NEST_TMP/s-nope"
check "a missing --skill-dir still reports its own error" \
  "error: --skill-dir does not exist: /nope" "$(_nest_first)"

# The three false-positive guards. These pass today and must keep passing: a
# containment check that refuses ordinary layouts is worse than none, because the
# operator learns to reach for --allow-nested-skill-dir by reflex.
_nest_run "$NEST_ROOT" --repo lmorchard/agent-sessions \
  --skill-dir "$NEST_SKILL" --repo-path "$NEST_ROOT/driver" --state-dir "$NEST_TMP/s-sibling"
check "a sibling directory is not containment" "no-warn gh-check" "$(_nest_verdict)"

# The "unrelated checkout" is constructed too. This named $HOME/devel/decafclaw,
# which exists on exactly one machine; anywhere else the driver died earlier at
# `--repo-path does not exist` and the case failed for a reason that has nothing
# to do with containment. It failed LOUDLY rather than passing vacuously -- the
# combined verdict is what saved it, since asserting only _nest_warned would have
# read `no-warn` from a run that never reached the containment check at all.
mkdir -p "$NEST_TMP/unrelated-checkout/skills"
_nest_run "$NEST_ROOT" --repo lmorchard/agent-sessions \
  --skill-dir "$NEST_SKILL" --repo-path "$NEST_TMP/unrelated-checkout" --state-dir "$NEST_TMP/s-other"
check "an unrelated checkout is not containment" "no-warn gh-check" "$(_nest_verdict)"

# The hermeticity guard. Two honest limitations, both worth stating in place.
#
# 1. It does NOT discriminate against the form it replaced -- with PATH pinned to
#    /usr/bin:/bin the old code also ignored an ambient gh. What it catches is the
#    plausible FUTURE regression: making the constructed dir a PREFIX
#    (PATH="$NEST_BIN:$PATH") rather than the whole PATH, which reads as harmless
#    and silently restores host-dependence.
#
# 2. It is NOT mutation-tested, deliberately, and this is the interesting part.
#    Applying that mutation makes the harness non-hermetic BY DEFINITION, so on any
#    host with a real gh -- including the authoring one -- the nest cases stop being
#    validation probes and become live driver runs. Attempted once: it selected a
#    real issue and created a worktree before it was killed. Verifying this guard by
#    mutation therefore requires doing the exact thing the guard exists to prevent.
#    Do not "just try it" to confirm it works.
#
#    The design property IS demonstrable, just not from inside this suite: run the
#    driver with PATH=<dir containing a stubbed gh>:/usr/bin:/bin and it passes
#    validation, passes the required-command loop, writes the state dir and enters
#    the select stage -- which is what the old pinned PATH would have done on a host
#    carrying /usr/bin/gh. Recorded in the PR for issue #18 rather than automated,
#    because automating it means keeping a live-run trigger in the suite.
mkdir -p "$NEST_TMP/ambient"
printf '#!/bin/bash\nexit 0\n' > "$NEST_TMP/ambient/gh"
chmod +x "$NEST_TMP/ambient/gh"
_nest_saved_path="$PATH"
PATH="$NEST_TMP/ambient:$PATH"
_nest_run "$NEST_ROOT" --repo lmorchard/agent-sessions --allow-nested-skill-dir \
  --skill-dir "$NEST_SKILL" --repo-path "$NEST_ROOT" --state-dir "$NEST_TMP/s-ambient"
PATH="$_nest_saved_path"
check "an ambient gh cannot reach the driver" "warned gh-check" "$(_nest_verdict)"
check "  and no state dir is created"         "absent"          "$(_nest_made "$NEST_TMP/s-ambient")"

# /a/bc is a string prefix match against /a/b and a path prefix match against
# neither. This is what catches a naive [[ $SKILL_DIR == $REPO_PATH* ]].
mkdir -p "$NEST_TMP/a/b" "$NEST_TMP/a/bc/phases"
: > "$NEST_TMP/a/bc/phases/express.md"
_nest_run "$NEST_ROOT" --repo lmorchard/agent-sessions \
  --skill-dir "$NEST_TMP/a/bc" --repo-path "$NEST_TMP/a/b" --state-dir "$NEST_TMP/s-prefix"
check "a string prefix that is not a path prefix is not containment" "no-warn gh-check" "$(_nest_verdict)"

# --- the issue query must actually request the labels it filters on --------
#
# Slice coverage, added because mutation testing found the FROZEN checks blind to
# this one: driver/test-park-state.sh serves a fixed issue-list fixture, so dropping
# `labels` from the driver's --json list left all 27 of its assertions green while
# the park list would have gone permanently empty in production. Not an amendment --
# the frozen checks are incomplete here, not wrong, so the coverage goes in the
# editable suite instead of being edited into the oracle.
#
# The stub below HONORS the requested field list, which is the whole point: it is
# the only way a missing --json field can change what the driver sees.

echo "issue query: the park filter's field must be requested, not assumed"

Q_TMP="$(mktemp -d)"
mkdir -p "$Q_TMP/bin"
cat > "$Q_TMP/issues.json" <<'JSON'
[{"number":7,"title":"labeled","body":"<!-- agent-session:spec -->\n\n## Tier: `auto-ok`\n","labels":[{"name":"driver-parked"}]}]
JSON
cat > "$Q_TMP/bin/gh" <<'STUB'
#!/usr/bin/env bash
fields=""; prev=""
for a in "$@"; do [ "$prev" = "--json" ] && fields="$a"; prev="$a"; done
case "$*" in
  "issue list"*) jq --arg f "$fields" \
                    '[.[] | with_entries(select(.key as $k | ($f | split(",")) | index($k)))]' \
                    "$STUB_DIR/issues.json" ;;
  "pr list"*)    printf '%s' '[]' ;;
  *)             exit 0 ;;
esac
STUB
chmod +x "$Q_TMP/bin/gh"
Q_OUT="$(STUB_DIR="$Q_TMP" PATH="$Q_TMP/bin:$PATH" \
         bash "$DRIVER" --repo stub/repo --dry-run --state-dir "$Q_TMP/state" 2>&1)"
# The needle carries the REASON, not just the skip. `SKIP    #7` alone is
# satisfiable by any skip -- a broken marker or tier parse would skip #7 too, and
# this test would stay green through the regression it exists to catch. Same
# adjacent-evidence defect the frozen file's C4 needle was tightened for; found
# here by the PR reviewer, after I fixed it one file over and missed this one.
case "$Q_OUT" in
  *"SKIP    #7  parked"*) ok "a labeled issue is skipped AS PARKED when the query asks for labels" ;;
  *)                      bad "a labeled issue is skipped AS PARKED when the query asks for labels" \
                              "SKIP    #7  parked" "$(printf '%s' "$Q_OUT" | tr '\n' '|' | cut -c1-240)" ;;
esac
rm -rf "$Q_TMP"

# --- syntax ----------------------------------------------------------------

echo "syntax"
if bash -n "$DRIVER" 2>/dev/null; then ok "driver parses"; else bad "driver parses" "clean" "$(bash -n "$DRIVER" 2>&1)"; fi

echo
printf '%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
