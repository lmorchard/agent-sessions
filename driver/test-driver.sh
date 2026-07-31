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

# Count the driver's NON-COMMENT LINES containing a literal.
#
# Lines, not occurrences -- `grep -c` counts matching lines, and two hits on one
# line count once. Every expectation below was measured against the driver rather
# than reasoned about, so the numbers are right either way, but the distinction
# matters to anyone adding a case.
#
# The old spelling of these assertions was `grep -q '<literal>' "$DRIVER"`, which
# succeeds when the literal appears ANYWHERE -- including inside a comment.
# findings.md (defect class 5) calls that "a spelling check, not a test", and the
# warning against it sat in a comment in this very file for two days while eight
# instances shipped and a ninth was added. Comparing a COUNT is what fixes it:
# delete the code and the count drops, so the assertion flips; describe it in a
# comment and the line is stripped before counting, so it does not.
#
# `make assertion-lint` (scripts/assertion_lint.py) now fails the build if the
# `-q` form comes back. See issue #28.
#
# Whole-line comments only -- a trailing `# ...` is not stripped, because doing so
# would need a bash parser to avoid mangling a `#` inside a string. Every literal
# these guard occurs on a real code line, and the shape is enforced mechanically.
# `--` ends option parsing: without it a pattern starting with `-` would be read
# as a flag, and the helper would break on the one input it most needs to handle
# literally. No behaviour change for the current callers.
_code_hits()    { grep -v '^[[:space:]]*#' "$DRIVER" | grep -cF -- "$1"; }
_code_hits_re() { grep -v '^[[:space:]]*#' "$DRIVER" | grep -cE -- "$1"; }

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
check "driver resolves STATE_DIR to an absolute path" "1" \
  "$(_code_hits 'STATE_DIR="$(abspath "$STATE_DIR")"')"

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
# Both halves are load-bearing and are now asserted separately, so a failure says
# which one broke: the park list must EXIST (or the second assertion passes
# vacuously against a list that is simply gone), and it must NOT name
# budget-exhausted.
check "the park case list is present to be checked"     "1" \
  "$(_code_hits_re '^ *parked\|failed\|incomplete\|no-gate\)')"
check "budget-exhausted is excluded from the park list" "0" \
  "$(_code_hits_re '^ *parked\|failed\|incomplete\|no-gate\|budget-exhausted\)')"

# --- the driver takes its child down with it -------------------------------

echo "orphan: the in-flight child must not outlive its driver"

check "cleanup trap installed on EXIT/INT/TERM" "1" \
  "$(_code_hits 'trap cleanup EXIT INT TERM')"
check "cleanup terminates the in-flight child"  "1" \
  "$(_code_hits 'kill -TERM "$CHILD_PID"')"
# The trap cannot fire on SIGKILL or a host crash, so startup must detect a
# still-live orphan and refuse -- otherwise two runs mutate one repo at once.
check "startup refuses to run alongside a live orphan" "1" \
  "$(_code_hits 'refusing to start a second run while an orphan is live')"
# Two: the write in the invoke stage and the read in the orphan check. Both are
# needed -- recording the pid with nothing reading it detects no orphan.
check "child pid is recorded AND read back" "2" "$(_code_hits 'child.pid')"

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
check "the failed branch consults the stream before overruling the gate" "1" \
  "$(_code_hits 'rc" -ne 0 ] && ! has_success_result')"

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

# C5 (issue #11). The root directory contains everything, so it is the one
# --repo-path for which the answer is always "yes, nested" -- and it was the one
# the guard never detected. `pwd -P` in / returns `/`, the only resolved path that
# already ends in a slash, so appending another at agent-session-driver.sh:158
# built the pattern `//*`. That matches no ordinary absolute path, so every path
# read as OUTSIDE / and the warning never fired.
#
# Asserts the combined verdict, not the exit status: rc is 2 whether the guard
# fires (die after the warning) or not (die at the required-command loop), so the
# exit code cannot discriminate here. Only the message and the stop-point can,
# which is exactly the pair _nest_verdict reduces -- `warned` for the literal
# text, `stopped-early` for NOT having reached `required command not found: gh`.
#
# Safe to run only because NEST_BIN carries no gh: at the unfixed behaviour this
# case sails through validation, and on a PATH with a real gh that is a live
# driver run against a real issue. The constructed PATH is what makes this a
# validation probe instead.
_nest_run "$NEST_ROOT" --repo lmorchard/agent-sessions \
  --skill-dir "$NEST_SKILL" --repo-path / --state-dir "$NEST_TMP/s-root"
check "--repo-path / is containment, not a wildcard" "warned stopped-early" "$(_nest_verdict)"

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

# --- a partly-marked queue must still account for its unmarked issues -------
#
# tier-batch drops a marker-less issue before the reporting loop ever sees it, so
# the ONLY thing the select stage says about it today is the open-issue count it
# is silently included in. That is fine when nothing carries the marker -- the
# zero case has its own message -- and invisible when something does: the queue
# reads "eligible: 1" and the operator has no way to tell one marker-less issue
# from none. Same failure shape the SKIP-with-a-reason lines exist to prevent, one
# filter earlier.
#
# Both cases invoke the SHIPPED driver as a subprocess against an offline `gh`
# stub, like the query section above, and both read its STDOUT only. Stdout is
# where say() writes and stderr is where log() writes its `HH:MM:SSZ` timestamps
# -- and a timestamp is digits, which a needle looking for a bare issue number
# cannot tell from an issue number. Capturing 2>&1 here would make assertion (a)
# passable by the clock.

echo "select: a mixed queue must account for its marker-less issues"

M_TMP="$(mktemp -d)"
mkdir -p "$M_TMP/bin"

# The same field-list-honoring stub as the query section: it is the only stub
# shape under which what the driver asks for changes what it sees.
cat > "$M_TMP/bin/gh" <<'STUB'
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
chmod +x "$M_TMP/bin/gh"

_marker_run() { # serves $M_TMP/issues.json to one dry run -> the run's stdout
  # A fresh mktemp state dir per run, so neither case can read the other's state
  # (or a stale ./.driver-state from the repo it is invoked in). Under $M_TMP so
  # the section still cleans up after itself.
  local state; state="$(mktemp -d "$M_TMP/state.XXXXXX")"
  STUB_DIR="$M_TMP" PATH="$M_TMP/bin:$PATH" \
    bash "$DRIVER" --repo stub/repo --dry-run --state-dir "$state" 2>/dev/null
}

# The issue numbers are derived AT RUN TIME, which is the point: a literal in the
# driver's source cannot satisfy a needle it cannot know. Both are forced to four
# digits, and that is load-bearing rather than tidy -- for two numbers of equal
# length, "is a substring of" collapses to "is equal to", so rejecting the equal
# case is sufficient to guarantee neither number can be found inside the other.
# Without that, a 4-digit marker-less number sitting inside a 5-digit eligible one
# would satisfy (a) and fail (b) for reasons that have nothing to do with the
# driver.
M_WITH=$(( 1000 + RANDOM % 9000 ))
M_WITHOUT=$(( 1000 + RANDOM % 9000 ))
while [ "$M_WITHOUT" -eq "$M_WITH" ]; do M_WITHOUT=$(( 1000 + RANDOM % 9000 )); done

# Titles are deliberately digit-free. Every other number the select stage prints
# in a no-board dry run is single-digit (the open count, the eligible count), so a
# four-digit needle has nowhere else in this output to match by accident.
jq -n -c --arg m "$MARKER" --argjson a "$M_WITH" --argjson b "$M_WITHOUT" \
  '[{number:$a, title:"marked and tiered", body:($m + "\n\n## Tier: `auto-ok`\n"), labels:[]},
    {number:$b, title:"never went through intake", body:"An ordinary bug report.\n", labels:[]}]' \
  > "$M_TMP/issues.json"

M_OUT="$(_marker_run)"
_m_flat() { printf '%s' "$M_OUT" | tr '\n' '|' | cut -c1-240; }

# The liveness probe, first, and NOT one of the criterion's assertions. It is what
# distinguishes "the driver reached the reporting loop and said nothing about the
# marker-less issue" from "the stub served nothing / the driver died at
# validation" -- two states an absent needle looks identical from. A check that
# can fail for the wrong reason will later pass for the wrong reason.
#
# AMENDED (A1, see this session's checks.md). This was exact equality against the
# whole line, which pinned the very line the spec's design decision requires the
# work to change -- "a parenthetical appended to the existing `read N open issues`
# line ... Rejected: a separate line". No implementation could satisfy both, so the
# frozen set was self-contradictory rather than merely strict. Containment on the
# count preserves everything the probe was built to distinguish (served-two vs
# served-nothing vs died-at-validation) and stops it asserting a format the
# criterion deliberately does not constrain -- the same reasoning as (a) below.
case "$(printf '%s\n' "$M_OUT" | grep '^repo stub/repo:' || true)" in
  *"read 2 open issues"*)
    ok "probe: the stub served both issues to the select stage" ;;
  *)
    bad "probe: the stub served both issues to the select stage" \
        "a 'repo stub/repo:' line containing 'read 2 open issues'" "$(_m_flat)" ;;
esac

# (a) The number is reported at all. Deliberately the weakest possible needle --
# the bare number, no `#`, no surrounding wording -- because the criterion
# constrains that the issue is ACCOUNTED FOR, not how the line is worded. Pinning
# a format here would fail an implementation that is correct and phrased
# differently, and (b) is what stops the bare number from passing in the wrong
# role.
case "$M_OUT" in
  *"$M_WITHOUT"*) ok "(a) the marker-less issue number appears in select output" ;;
  *)              bad "(a) the marker-less issue number appears in select output" \
                      "$M_WITHOUT somewhere in stdout" "$(_m_flat)" ;;
esac

# (b) ...and is not reported as eligible. Asserted as "no line containing
# ELIGIBLE contains that number", not as "the string `ELIGIBLE #<n>` is absent":
# the latter is satisfiable by a change in spacing, which would let the driver
# announce a marker-less issue as eligible while this stayed green.
check "(b) no ELIGIBLE line names the marker-less issue" "" \
  "$(printf '%s\n' "$M_OUT" | grep 'ELIGIBLE' | grep -F "$M_WITHOUT" || true)"

# (c) ...and reporting it does not make it count. Matched as a whole line rather
# than as a substring, because the needle `eligible: 1` is a prefix of
# `eligible: 12`.
check "(c) the run still reports one eligible issue" "eligible: 1" \
  "$(printf '%s\n' "$M_OUT" | grep '^eligible:' || true)"

# --- G1: the zero-marker message survives whatever reports the partial case ---
#
# A guard, not a criterion: it passes today and must keep passing. The obvious way
# to implement the above is to move the marker-less accounting into the reporting
# loop -- which the zero-marker path returns before reaching, so the specific
# regression is that "no issues carry the marker" gets replaced by a bare list of
# skipped numbers and the queue-is-empty case stops being legible as such.

echo "select: the zero-marker message is not swallowed by partial reporting"

G_WITHOUT=$(( 1000 + RANDOM % 9000 ))
jq -n -c --argjson b "$G_WITHOUT" \
  '[{number:$b, title:"never went through intake", body:"An ordinary bug report.\n", labels:[]}]' \
  > "$M_TMP/issues.json"

G_OUT="$(_marker_run)"
case "$G_OUT" in
  *"no issues carry the marker"*) ok "G1 an all-marker-less queue still says no issues carry the marker" ;;
  *)                              bad "G1 an all-marker-less queue still says no issues carry the marker" \
                                      "no issues carry the marker" \
                                      "$(printf '%s' "$G_OUT" | tr '\n' '|' | cut -c1-240)" ;;
esac

rm -rf "$M_TMP"

# --- an open PR blocks an issue only when it actually CLOSES it -------------
#
# Selection asks "does an open PR already exist for #N" and answers it by looking
# for the number in the PR's body, title or branch name. Those are all proxies for
# the thing GitHub already knows authoritatively -- `closingIssuesReferences`, the
# linked-issue set a merge would actually close. A proxy that fires on any mention
# is wrong in the direction that costs the most: an issue nobody is working on
# reads as taken, and the driver silently stops picking it up. A triage PR that
# tabulates a dozen issue numbers in prose blocks every one of them, and nothing
# in the output says why the queue went quiet.
#
# Both cases invoke the SHIPPED driver as a subprocess against an offline `gh`
# stub -- not `grep -q "<literal>" "$DRIVER"`, which is a spelling check and passes
# on a comment. And the stub HONOURS the requested `--json` field list on BOTH
# `issue list` and `pr list`, which is the entire mechanism C2 turns on: a driver
# that does not ask for `closingIssuesReferences` cannot be served it, so the field
# is invisible to it exactly as it would be against real GitHub.
#
# Stdout only (2>/dev/null). log() writes `HH:MM:SSZ` timestamps to stderr, and a
# timestamp is digits -- capturing 2>&1 would let the clock satisfy a needle
# looking for an issue number.

echo "select: an open PR blocks an issue only when it closes it"

R_TMP="$(mktemp -d)"
mkdir -p "$R_TMP/bin"

cat > "$R_TMP/bin/gh" <<'STUB'
#!/usr/bin/env bash
fields=""; prev=""
for a in "$@"; do [ "$prev" = "--json" ] && fields="$a"; prev="$a"; done
_serve() { jq --arg f "$fields" \
             '[.[] | with_entries(select(.key as $k | ($f | split(",")) | index($k)))]' "$1"; }
case "$*" in
  "issue list"*) _serve "$STUB_DIR/issues.json" ;;
  "pr list"*)    _serve "$STUB_DIR/prs.json" ;;
  *)             exit 0 ;;
esac
STUB
chmod +x "$R_TMP/bin/gh"

_ref_run() { # serves $R_TMP/{issues,prs}.json to one dry run -> the run's stdout
  # A fresh state dir per run, so neither case can read the other's state (or a
  # stale ./.driver-state from wherever the suite was invoked). Under $R_TMP so the
  # section still cleans up after itself.
  local state; state="$(mktemp -d "$R_TMP/state.XXXXXX")"
  STUB_DIR="$R_TMP" PATH="$R_TMP/bin:$PATH" \
    bash "$DRIVER" --repo stub/repo --dry-run --state-dir "$state" 2>/dev/null
}

# The one issue under test, in both cases. Marker plus an `auto-ok` Tier heading,
# because selection drops a marker-less issue before the reporting loop and an
# untiered one skips for the wrong reason -- either would make the needles below
# absent for a reason that has nothing to do with PR matching. The title is
# deliberately digit-free: it is echoed on the line under every SKIP/ELIGIBLE, so a
# number in it would be a second place for `#11` to appear.
jq -n -c --arg m "$MARKER" \
  '[{number:11, title:"the issue a triage sweep merely mentioned",
     body:($m + "\n\n## Tier: `auto-ok`\n"), labels:[]}]' \
  > "$R_TMP/issues.json"

_ref_probe() { # $1 = label, $2 = the run's stdout
  # The liveness probe, asserted separately and NOT one of the criterion's
  # assertions. An absent needle and a driver that died at validation (or a stub
  # that served nothing) look identical from the outside, and a check that can fail
  # for the wrong reason will later pass for the wrong reason. Containment on the
  # count rather than equality on the whole line, so the probe does not pin a format
  # neither criterion constrains.
  case "$(printf '%s\n' "$2" | grep '^repo stub/repo:' || true)" in
    *"read 1 open issues"*) ok "probe: $1" ;;
    *)                      bad "probe: $1" "a 'repo stub/repo:' line containing 'read 1 open issues'" \
                                "$(printf '%s' "$2" | tr '\n' '|' | cut -c1-240)" ;;
  esac
}

# --- C1: a prose mention is not a link --------------------------------------
#
# PR 21 of this very repo, verbatim in shape: a triage sweep whose body tabulates
# the issues it triaged, whose branch is named after all three of them, and which
# closes NONE of them -- `closingIssuesReferences` is empty because no closing
# keyword appears anywhere. Every proxy the matcher has fires; the authoritative
# field says no.

jq -n -c '[{number:21, title:"triage sweep",
            body:"Triage results.\n\n| issue | tier |\n| --- | --- |\n| #11 | auto-ok |\n",
            headRefName:"docs/triage-11-12-13",
            url:"https://github.com/stub/repo/pull/21",
            closingIssuesReferences:[]}]' \
  > "$R_TMP/prs.json"

C1_OUT="$(_ref_run)"
_ref_probe "the stub served the issue to the select stage (C1 fixture)" "$C1_OUT"

case "$C1_OUT" in
  *"ELIGIBLE #11"*) ok "C1(a) an issue merely mentioned by an open PR is still eligible" ;;
  *)                bad "C1(a) an issue merely mentioned by an open PR is still eligible" \
                        "ELIGIBLE #11" "$(printf '%s' "$C1_OUT" | tr '\n' '|' | cut -c1-240)" ;;
esac

# Asserted as "no line carrying the open-PR reason names #11", not as "the exact
# string `SKIP    #11  already has an open PR` is absent". The latter is satisfiable
# by a change in spacing, which would green this check while the driver went on
# blocking the issue. Same reasoning as (b) in the mixed-queue node above.
check "C1(b) no open-PR skip line names the merely-mentioned issue" "" \
  "$(printf '%s\n' "$C1_OUT" | grep 'already has an open PR' | grep -F '#11' || true)"

# ...and being eligible has to COUNT, not just print. Matched as a whole line
# because the needle `eligible: 1` is a prefix of `eligible: 12`.
check "C1(c) the run reports one eligible issue" "eligible: 1" \
  "$(printf '%s\n' "$C1_OUT" | grep '^eligible:' || true)"

# --- C2: the closing reference must be requested to be seen -----------------
#
# The mirror image, and the only shape that can distinguish "asks for the field"
# from "happens to be right". This PR carries the number NOWHERE a proxy can reach
# it -- not the body, not the title, not the branch -- and links the issue only via
# `closingIssuesReferences`. The stub filters on the requested `--json` list, so a
# driver that does not name the field is served a PR with no link at all and has
# nothing to match on. Passing this is therefore evidence about the QUERY, which is
# what the criterion is about; no second API call is involved either way.

jq -n -c '[{number:22, title:"an ordinary fix",
            body:"Fixes the thing.\n",
            headRefName:"chore/no-numbers-in-here",
            url:"https://github.com/stub/repo/pull/22",
            closingIssuesReferences:[{"number":11}]}]' \
  > "$R_TMP/prs.json"

C2_OUT="$(_ref_run)"
_ref_probe "the stub served the issue to the select stage (C2 fixture)" "$C2_OUT"

# The needle carries the REASON, not just the shape. `SKIP    #11` alone is
# satisfiable by any skip -- a broken marker or tier parse would skip #11 too, and
# this would stay green through the regression it exists to catch.
case "$C2_OUT" in
  *"SKIP    #11  already has an open PR"*)
    ok "C2(a) a PR linked only by closingIssuesReferences blocks the issue" ;;
  *)
    bad "C2(a) a PR linked only by closingIssuesReferences blocks the issue" \
        "SKIP    #11  already has an open PR" "$(printf '%s' "$C2_OUT" | tr '\n' '|' | cut -c1-240)" ;;
esac

check "C2(b) no ELIGIBLE line names the linked issue" "" \
  "$(printf '%s\n' "$C2_OUT" | grep 'ELIGIBLE' | grep -F '#11' || true)"

# --- G1/G2: the proxies stay, for PRs GitHub has not linked -----------------
#
# Guards, not criteria: these pass today and must keep passing. They exist because
# `pr_for_issue` has TWO callers wanting opposite error directions. The selection
# gate wants precision -- a wrong match there silently hides eligible work, which is
# what C1/C2 above are about. Post-run PR DISCOVERY wants recall: it runs against a
# PR the driver may have just opened badly, and a miss there reports `parked: no PR
# opened` about a PR that exists.
#
# So the guards pin the discovery direction while C1/C2 tighten the selection one,
# and tripping a guard means a fix meant for selection was over-applied. The fixture
# is the FROZEN one at driver/test-park-state.sh:89 -- `Closes #7`, branch
# `fix/7-stub`, and NO `closingIssuesReferences` key at all, because that suite's
# stub serves a fixed payload and ignores the requested field list. A discovery site
# that consulted the link alone would resolve it to nothing and flip that suite's
# cases to `parked`. test-park-state.sh is frozen and read-only, so that is a STOP,
# not an edit.
#
# Read out of the frozen file rather than copied, for the same reason the function
# below is: a copy is a second source of truth that nothing keeps honest.

echo "guard: body/branch matching still works where GitHub records no link"

FROZEN="$(dirname "$DRIVER")/test-park-state.sh"
eval "$(sed -n '/^PR_LIST_JSON=/p' "$FROZEN")"
eval "$(sed -n '/^pr_for_issue()/,/^}/p' "$DRIVER")"

if [ -z "${PR_LIST_JSON:-}" ]; then
  bad "extract the frozen PR fixture" "PR_LIST_JSON from $FROZEN" "not found (moved or renamed?)"
elif ! declare -f pr_for_issue >/dev/null; then
  # Fails closed on a rename. A silent skip here would retire both guards without
  # anyone deciding to.
  bad "extract the real pr_for_issue from the driver" "a function named pr_for_issue" "not found (renamed?)"
else
  check "G1 the frozen 'Closes #7' PR is still matched to #7" \
    "$(printf '42\thttps://github.com/stub/repo/pull/42')" "$(pr_for_issue 7 "$PR_LIST_JSON")"
  check "G2 and #8, which that PR does not mention, is still unmatched" \
    "" "$(pr_for_issue 8 "$PR_LIST_JSON")"
fi

rm -rf "$R_TMP"

# --- #32: a warning must not overwrite the outcome it warns about -----------
#
#   https://github.com/lmorchard/agent-sessions/issues/32
#
# FROZEN acceptance checks. Read-only from Phase 1 onward: if a check here looks
# wrong, that is a STOP and an amendment (see
# skills/agent-session/references/frozen-checks.md), not an edit.
#
# The defect: `classify_pr_body` documents itself as "Prints outcome<TAB>reason"
# -- its stdout IS its return value -- and then writes warnings to that same
# stdout via `say`, which unlike `log` and `die` does not redirect to stderr.
# Both call sites read it with `read -r`, which consumes only the FIRST line, so
# a warning line becomes the outcome and the real value is discarded unread.
# Hit for real: the decafclaw #657 ledger row, a $16.69 run whose outcome field
# holds the warning text and whose reason is empty.
#
# NO REPLICAS: C1 and G1 evaluate the shipped `classify_pr_body`, `say` and `log`
# out of the driver with sed, and C2 invokes the shipped driver as a subprocess.
# Naming the function as the extraction entry point makes a rename fail closed.

echo "#32: a classifier warning must not overwrite the outcome"

# The fixture the issue names: an unparseable `ci` sha (so the warning fires) and
# a non-empty head sha (so the staleness branch is entered at all). `reason` is
# set in the block, so the expected value is the block's own text rather than
# gate.py's default.
C32_SHA="deadbeefcafe"
C32_BODY="$GATE_MARKER
\`\`\`yaml
tier: auto-ok
checks: C1 pass
guards: G1 pass
tamper: clean
ci: not yet graded
threads: 0 unresolved
verdict: eligible-for-auto-merge
reason: all rows satisfied
\`\`\`"

# The correct answer, from the shipped parser. Not an assertion about #32 -- a
# probe that makes the C1 failure attributable: if gate.py stopped producing
# gate-eligible here, C1 would fail for a reason that has nothing to do with the
# channel bug, and this line says which.
check "probe: gate.py itself classifies the fixture gate-eligible" \
  "gate-eligible" "$(outcome_of "$C32_BODY" "$C32_SHA")"
check "probe: and reports exactly one warning on it" \
  "1" "$(_classify "$C32_BODY" "$C32_SHA" | jq -r '.warnings | length')"

# The shipped output helpers, extracted rather than copied: whichever channel the
# driver's `say` writes to is the channel these checks see. `die` comes along
# because it is defined on the same shape and a future classify path may call it.
eval "$(sed -n '/^log()/p;/^say()/p' "$DRIVER")"
eval "$(sed -n '/^classify_pr_body()/,/^}/p' "$DRIVER")"

if ! declare -f classify_pr_body >/dev/null; then
  bad "extract the real classify_pr_body from the driver" \
      "a function named classify_pr_body" "not found (renamed?)"
elif ! declare -f say >/dev/null || ! declare -f log >/dev/null; then
  bad "extract the real say/log from the driver" \
      "functions named say and log" "not found (renamed?)"
else
  GATE_JSON=""
  GATE_BLOCK=""

  # C1. Read the way the function documents itself and both call sites read it:
  # stdout only, first line, tab-split. Deliberately NOT pinned to one repair --
  # a fix that leaves the warning on stdout still leaves the function violating
  # the contract in its own comment, which is the defect.
  C32_STDOUT="$(classify_pr_body "$C32_BODY" "$C32_SHA" 2>/dev/null)"
  IFS="$(printf '\t')" read -r c32_outcome c32_reason <<EOF
$C32_STDOUT
EOF
  check "#32 C1 the value channel carries the outcome, not the warning" \
    "gate-eligible" "$c32_outcome"
  check "#32 C1 and carries the reason with it" \
    "all rows satisfied" "$c32_reason"

  # G1. The warning must survive the fix. The cheapest way to green C1 is to
  # delete the `say` line, which trades a corrupted record for a missing one --
  # and silences a "a null must never render as a positive" warning, which is the
  # thing the warning channel exists for. Combined stdout+stderr, because the
  # point is that the OPERATOR still sees it, not which fd it arrives on.
  C32_BOTH="$(classify_pr_body "$C32_BODY" "$C32_SHA" 2>&1)"
  case "$C32_BOTH" in
    *"ci row carries no parseable sha"*)
      ok "#32 G1 the warning is still visible to the operator" ;;
    *)
      bad "#32 G1 the warning is still visible to the operator" \
          "output containing: ci row carries no parseable sha" \
          "$(printf '%s' "$C32_BOTH" | tr '\n' '|' | cut -c1-300)" ;;
  esac
fi

# C2. The SECOND call site, end to end. `--classify-only` is the documented
# recovery path for an unrecorded outcome, and on #657 it reproduced the same
# corruption (the ledger's third row carries `recovered: true` and the warning
# text). A fix at one call site and not the other is findings.md class 1's
# "fixed the cost field, never generalised".
#
# Self-contained stubs rather than reuse of test-park-state.sh's: that file is
# another issue's frozen check file, and its fixture omits the `ci` row on
# purpose. Same shape, honouring the requested --json field list.

C32_TMP="$(mktemp -d)"
C32_BIN="$C32_TMP/bin"; mkdir -p "$C32_BIN"
printf '%s\n' "$C32_BODY" > "$C32_BIN/pr-body.txt"
printf '%s' '[{"number":42,"title":"stub pr","body":"Closes #7","headRefName":"fix/7-stub",
  "url":"https://github.com/stub/repo/pull/42","closingIssuesReferences":[{"number":7}]}]' \
  > "$C32_BIN/pr-list.json"

cat > "$C32_BIN/gh" <<'STUB'
#!/usr/bin/env bash
case "$*" in
  "pr list"*)            cat "$STUB_DIR/pr-list.json" ;;
  *"--json headRefOid"*) printf '%s\n' "$STUB_HEAD_SHA" ;;
  *"--json body"*)       cat "$STUB_DIR/pr-body.txt" ;;
  *)                     exit 0 ;;
esac
STUB
chmod +x "$C32_BIN/gh"

C32_SD="$C32_TMP/state"
C32_OUT="$(STUB_DIR="$C32_BIN" STUB_HEAD_SHA="$C32_SHA" PATH="$C32_BIN:$PATH" \
             bash "$DRIVER" --repo stub/repo --classify-only 7 --state-dir "$C32_SD" 2>&1)"
C32_ROW="$(tail -1 "$C32_SD/runs.jsonl" 2>/dev/null || true)"

# The probe first, for the same reason as above: an absent row and a driver that
# died at validation look identical to the assertion below, and only this tells
# them apart.
if [ -z "$C32_ROW" ]; then
  bad "probe: --classify-only appended a ledger row" \
      "a json row in $C32_SD/runs.jsonl" \
      "$(printf '%s' "$C32_OUT" | tr '\n' '|' | cut -c1-300)"
else
  ok "probe: --classify-only appended a ledger row"
  C32_ROW_OUTCOME="$(printf '%s' "$C32_ROW" | jq -r '.outcome')"
  case "$C32_ROW_OUTCOME" in
    gate-eligible|gate-human|ci-stale|incomplete|parked|failed|no-gate|budget-exhausted)
      ok "#32 C2 the recovery path records a known outcome value" ;;
    *)
      bad "#32 C2 the recovery path records a known outcome value" \
          "one of gate-eligible|gate-human|ci-stale|incomplete|parked|failed|no-gate|budget-exhausted" \
          "[$C32_ROW_OUTCOME]" ;;
  esac
fi

rm -rf "$C32_TMP"

# --- #32 coda: NOT FROZEN ----------------------------------------------------
#
# Everything above this line in the #32 section is frozen. This block is not: it
# covers a second latent defect the #32 fix repairs incidentally, discovered
# during implementation and therefore after the freeze closed. Kept separate so
# the tamper diff over the frozen assertions stays reviewable -- this block
# changes no frozen fixture, helper or assertion.
#
# The defect: both call sites read the classifier through `$(classify_pr_body ...)`.
# Command substitution forks, so the GATE_BLOCK the function assigns landed in a
# subshell and never reached the caller -- and the next line writes it to
# `$rundir/gate.yaml`. Every gate.yaml this driver has written is therefore a
# single blank line, verified across this repo's own .driver-state/runs. Reading
# the JSON fields instead of the stdout line requires calling the function in the
# current shell, which repairs it.

echo "#32 coda (not frozen): gate.yaml records the block, not a blank line"

D32_TMP="$(mktemp -d)"
D32_BIN="$D32_TMP/bin"; mkdir -p "$D32_BIN"
printf '%s\n' "$C32_BODY" > "$D32_BIN/pr-body.txt"
printf '%s' '[{"number":42,"title":"stub pr","body":"Closes #7","headRefName":"fix/7-stub",
  "url":"https://github.com/stub/repo/pull/42","closingIssuesReferences":[{"number":7}]}]' \
  > "$D32_BIN/pr-list.json"
cat > "$D32_BIN/gh" <<'STUB'
#!/usr/bin/env bash
case "$*" in
  "pr list"*)            cat "$STUB_DIR/pr-list.json" ;;
  *"--json headRefOid"*) printf '%s\n' "$STUB_HEAD_SHA" ;;
  *"--json body"*)       cat "$STUB_DIR/pr-body.txt" ;;
  *)                     exit 0 ;;
esac
STUB
chmod +x "$D32_BIN/gh"

# A run dir with a stream: the recovery path only writes gate.yaml when it finds
# one, so without this the write is never reached and the check passes vacuously.
D32_SD="$D32_TMP/state"
D32_RUNDIR="$D32_SD/runs/7-20260731T000000Z"
mkdir -p "$D32_RUNDIR"
printf '%s\n' '{"type":"result","subtype":"success","is_error":false,"total_cost_usd":0.5,"session_id":"stub","result":"done"}' \
  > "$D32_RUNDIR/stream.jsonl"

D32_OUT="$(STUB_DIR="$D32_BIN" STUB_HEAD_SHA="$C32_SHA" PATH="$D32_BIN:$PATH" \
             bash "$DRIVER" --repo stub/repo --classify-only 7 --state-dir "$D32_SD" 2>&1)"

case "$D32_OUT" in
  *"run dir  $D32_RUNDIR"*) ok "probe: the recovery path found the run dir" ;;
  *) bad "probe: the recovery path found the run dir" "a 'run dir' line naming $D32_RUNDIR" \
         "$(printf '%s' "$D32_OUT" | tr '\n' '|' | cut -c1-300)" ;;
esac

# `verdict:` rather than mere non-emptiness: a stray newline is non-empty too, and
# that is exactly the value the bug wrote.
# A count, not `grep -q`: same reason as _code_hits above. A missing file yields
# no output and a nonzero status, so the substitution is empty and the default
# makes it 0 -- this fails closed rather than erroring.
D32_VERDICT_HITS="$(grep -c '^verdict: eligible-for-auto-merge$' "$D32_RUNDIR/gate.yaml" 2>/dev/null || true)"
if [ "${D32_VERDICT_HITS:-0}" -eq 1 ]; then
  ok "gate.yaml carries the gate block"
else
  bad "gate.yaml carries the gate block" "exactly one 'verdict: eligible-for-auto-merge' line" \
      "${D32_VERDICT_HITS:-0} in [$(tr '\n' '|' < "$D32_RUNDIR/gate.yaml" 2>/dev/null || echo MISSING)]"
fi

rm -rf "$D32_TMP"

# --- syntax ----------------------------------------------------------------

echo "syntax"
if bash -n "$DRIVER" 2>/dev/null; then ok "driver parses"; else bad "driver parses" "clean" "$(bash -n "$DRIVER" 2>&1)"; fi

echo
printf '%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
