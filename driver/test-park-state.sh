#!/usr/bin/env bash
#
# FROZEN acceptance checks for issue #5 -- park state moves to a GitHub label.
#
#   https://github.com/lmorchard/agent-sessions/issues/5
#
# Read-only from Phase 1 onward. If a check here looks wrong, that is a STOP and
# an amendment (see skills/agent-session/references/frozen-checks.md), not an edit.
#
# Two properties this file is built for, both learned the hard way:
#
#   NO REPLICAS. C1 evaluates the real `parked_numbers` out of the shipped driver
#   with sed. A mirrored copy in a test file passes with the driver unchanged --
#   that is the defect #9 removed, and naming `parked_numbers` as the entry point
#   makes the extraction fail closed if it is ever renamed.
#
#   NO GREPPING THE SUBJECT FOR A LITERAL. C2/C3/C4 invoke the shipped driver as
#   a subprocess against stubbed `gh` and `claude`, so deleting the behaviour
#   flips them. `grep -q "<literal>" "$DRIVER"` is a spelling check, not a test.
#
# The stubs model GitHub and the CLI, so a stub bug and a missing behaviour look
# alike from the outside. That is what the harness-sanity section exists to rule
# out: it must PASS at freeze, which is what makes the C failures attributable.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
DRIVER="$HERE/agent-session-driver.sh"
PARK_LABEL="driver-parked"
REPO="stub/repo"
ISSUE=7

PASS=0
FAIL=0
ok()   { PASS=$((PASS+1)); printf '  ok    %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  FAIL  %s\n     expected: %s\n     actual:   %s\n' "$1" "$2" "$3"; }
check(){ [ "$2" = "$3" ] && ok "$1" || bad "$1" "$2" "$3"; }
has()  { # $1 = label, $2 = needle, $3 = haystack
  case "$3" in *"$2"*) ok "$1" ;; *) bad "$1" "contains: $2" "$(printf '%s' "$3" | tr '\n' '|' | cut -c1-300)" ;; esac
}
# CLARIFICATION, logged in checks.md (2026-07-29). One call line must carry BOTH
# needles. The original C2/C3 wording matched the flag, the label name and the issue
# number independently over the whole concatenated argv log, and `$PARK_LABEL` also
# appears in the `gh label create` line -- so "with the park label" was satisfiable by
# the create call, and `gh issue edit 7 --add-label wrong-label` plus
# `gh label create driver-parked` would have passed all three. Adjacent evidence, in
# the check meant to catch it. Order-tolerant on purpose: pinning flag order would
# make the check brittle, and a brittle check trains the operator to wave it through.
has_call() { # $1 = label, $2 = log file, $3 = needle A, $4 = needle B
  if awk -v a="$3" -v b="$4" 'index($0,a) && index($0,b) {f=1} END{exit !f}' "$2"; then
    ok "$1"
  else
    bad "$1" "one call containing: $3 + $4" "$(tr '\n' '|' < "$2" | cut -c1-200)"
  fi
}
hasnt(){ # $1 = label, $2 = needle, $3 = haystack
  case "$3" in *"$2"*) bad "$1" "does NOT contain: $2" "$(printf '%s' "$3" | tr '\n' '|' | cut -c1-300)" ;; *) ok "$1" ;; esac
}

TMPROOT="$(mktemp -d)"
trap 'rm -rf "$TMPROOT"' EXIT

# --- the fixtures ----------------------------------------------------------
#
# A gate block shaped like references/pr-body-template.md's example. `ci` is
# omitted deliberately: a `ci:` row with a sha the stub does not serve would
# classify `ci-stale`, which is neither a park nor an un-park outcome and would
# make C2/C3 test the wrong branch.

pr_body() { # $1 = verdict
  cat <<EOF
Closes #$ISSUE

## Merge gate

<!-- agent-session:gate -->
\`\`\`yaml
tier: auto-ok
checks: C1 pass
guards: G1 pass
tamper: clean
verdict: $1
reason: fixture
\`\`\`
EOF
}

# One open PR, referencing the issue the way an express PR does.
PR_LIST_JSON='[{"number":42,"title":"stub pr","body":"Closes #7","headRefName":"fix/7-stub","url":"https://github.com/stub/repo/pull/42"}]'

# An issue list as `gh issue list --json number,title,body,labels` returns it:
# #7 carries the park label, #8 does not. Both carry the marker and an auto-ok
# tier, so tier-batch keeps them and only the label can explain a difference.
issue_list_json() { cat <<EOF
[{"number":7,"title":"issue carrying the label","body":"<!-- agent-session:spec -->\nbody\n\n## Tier: \`auto-ok\`\n","labels":[{"name":"$PARK_LABEL"}]},
 {"number":8,"title":"issue without the label","body":"<!-- agent-session:spec -->\nbody\n\n## Tier: \`auto-ok\`\n","labels":[{"name":"enhancement"}]}]
EOF
}

# `gh` stub. Logs every invocation, answers the five reads the driver makes, and
# exits 0 for everything else -- including the label writes, which are the point:
# the assertions read them out of the argv log.
make_stubs() { # $1 = dir to hold the stubs, $2 = verdict for the PR body
  local bin="$1" verdict="$2"
  mkdir -p "$bin"
  pr_body "$verdict"   > "$bin/pr-body.txt"
  issue_list_json      > "$bin/issue-list.json"
  printf '%s' "$PR_LIST_JSON" > "$bin/pr-list.json"

  cat > "$bin/gh" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$ARGV_LOG"
case "$*" in
  "pr list"*)            cat "$STUB_DIR/pr-list.json" ;;
  *"--json headRefOid"*) printf 'deadbeefcafe\n' ;;
  *"--json body"*)       cat "$STUB_DIR/pr-body.txt" ;;
  "issue list"*)         cat "$STUB_DIR/issue-list.json" ;;
  *)                     exit 0 ;;
esac
STUB

  # `claude -p` writes a stream-json to stdout. One successful result record is
  # all the driver reads: pick_result takes the max-cost record, has_success_result
  # looks for subtype=success, and the gate verdict comes from the PR, not here.
  cat > "$bin/claude" <<'STUB'
#!/usr/bin/env bash
cat >/dev/null
printf '%s\n' '{"type":"result","subtype":"success","is_error":false,"total_cost_usd":0.5,"session_id":"stub-session","result":"stub run finished"}'
STUB

  chmod +x "$bin/gh" "$bin/claude"
}

# One driver invocation against the stubs. Prints the driver's own output; the
# argv log lands in $ARGV_LOG for the caller to read.
run_driver() { # $1 = stub dir, $2 = argv log, $3... = driver args
  local bin="$1" log="$2"; shift 2
  : > "$log"
  ARGV_LOG="$log" STUB_DIR="$bin" PATH="$bin:$PATH" \
    bash "$DRIVER" "$@" 2>&1
}

# --- harness sanity: MUST PASS AT FREEZE ------------------------------------
#
# Without this section a stub typo is indistinguishable from the absent
# behaviour, and every C below would "fail for the right reason" while actually
# failing on a broken fixture.

echo "harness sanity (must pass at freeze -- makes the C failures attributable)"

SANE_BIN="$TMPROOT/sane-bin"; SANE_LOG="$TMPROOT/sane.log"; SANE_SD="$TMPROOT/sane-state"
make_stubs "$SANE_BIN" "pending"
SANE_OUT="$(run_driver "$SANE_BIN" "$SANE_LOG" --repo "$REPO" --dry-run --state-dir "$SANE_SD")"
has "the gh stub serves the issue list"       "read 2 open issues" "$SANE_OUT"
has "  and both issues reach tier filtering"  "#8"                 "$SANE_OUT"
has "the driver logged a gh issue list call"  "issue list"         "$(cat "$SANE_LOG")"

SANE_CO="$(run_driver "$SANE_BIN" "$SANE_LOG" --repo "$REPO" --classify-only "$ISSUE" --state-dir "$SANE_SD")"
has "the gh stub serves the PR and its gate"  "outcome  incomplete" "$SANE_CO"
has "  and the ledger row was written"        "\"issue\":7"         "$(cat "$SANE_SD/runs.jsonl" 2>/dev/null || echo MISSING)"

SANE_RUN_SD="$TMPROOT/sane-run-state"
SANE_SKILL="$TMPROOT/sane-skill"; mkdir -p "$SANE_SKILL/phases"; : > "$SANE_SKILL/phases/express.md"
SANE_REPOP="$TMPROOT/sane-repo"; mkdir -p "$SANE_REPOP"
SANE_INVOKE="$(run_driver "$SANE_BIN" "$SANE_LOG" --repo "$REPO" --issue "$ISSUE" \
                 --skill-dir "$SANE_SKILL" --repo-path "$SANE_REPOP" \
                 --state-dir "$SANE_RUN_SD" --max-budget-usd 10)"
has "the claude stub stands in for a real run" "cost \$0.5"          "$SANE_INVOKE"
has "  and the normal path reaches an outcome" "outcome  incomplete" "$SANE_INVOKE"

# --- C1: the read side reads labels ----------------------------------------
#
# CRITERION: GIVEN an issue list in which issue N carries the park label and
# issue M does not, WHEN selection computes the park list, THEN N SHALL appear in
# it and M SHALL NOT.

echo "C1: parked_numbers derives the park list from the park label"

# The real function, evaluated out of the shipped driver. Not a copy.
eval "$(sed -n '/^parked_numbers()/,/^}/p' "$DRIVER")"
if ! declare -f parked_numbers >/dev/null; then
  bad "extract the real parked_numbers from the driver" "a function named parked_numbers" "not found (renamed?)"
else
  # PARKED_LOG is set to a path that does not exist for one reason only: the
  # pre-change function reads it under `set -u`, so leaving it unset makes this
  # check die on an unbound variable instead of reporting an empty park list.
  # An empty park list is the finding; a bash error is a broken check.
  C1_OUT="$(issue_list_json | PARKED_LOG="$TMPROOT/no-such-parked.jsonl" parked_numbers 2>&1 | tr '\n' ' ' | sed 's/ *$//')"
  check "the labeled issue is parked, the unlabeled one is not" "7" "$C1_OUT"
fi

# --- C2: the write side parks, on BOTH paths -------------------------------
#
# CRITERION: WHEN a run's outcome is one of parked|failed|incomplete|no-gate, THE
# DRIVER SHALL add the park label to that issue, on the normal path AND on the
# --classify-only recovery path.
#
# Both, because the parking case list is duplicated and #656's stale record came
# from the recovery path -- a fix that only touches the normal path reproduces
# the bug it is closing.

echo "C2: a parking outcome adds the label -- normal path and recovery path"

PARK_BIN="$TMPROOT/park-bin"; make_stubs "$PARK_BIN" "pending"

CO_LOG="$TMPROOT/park-classify.log"; CO_SD="$TMPROOT/park-classify-state"
run_driver "$PARK_BIN" "$CO_LOG" --repo "$REPO" --classify-only "$ISSUE" --state-dir "$CO_SD" >/dev/null
CO_ARGV="$(cat "$CO_LOG")"
has_call "recovery path: labels the right issue with the park label, in one call" \
         "$CO_LOG" "issue edit $ISSUE" "--add-label $PARK_LABEL"

RUN_LOG="$TMPROOT/park-run.log"; RUN_SD="$TMPROOT/park-run-state"
RUN_SKILL="$TMPROOT/park-skill"; mkdir -p "$RUN_SKILL/phases"; : > "$RUN_SKILL/phases/express.md"
RUN_REPOP="$TMPROOT/park-repo"; mkdir -p "$RUN_REPOP"
run_driver "$PARK_BIN" "$RUN_LOG" --repo "$REPO" --issue "$ISSUE" \
  --skill-dir "$RUN_SKILL" --repo-path "$RUN_REPOP" --state-dir "$RUN_SD" \
  --max-budget-usd 10 >/dev/null
RUN_ARGV="$(cat "$RUN_LOG")"
has_call "normal path: labels the right issue with the park label, in one call" \
         "$RUN_LOG" "issue edit $ISSUE" "--add-label $PARK_LABEL"

# --- C3: a gate verdict un-parks -------------------------------------------
#
# CRITERION: WHEN a run's outcome is gate-eligible or gate-human, THE DRIVER
# SHALL remove the park label from that issue.

echo "C3: a gate outcome removes the label"

for verdict_pair in "eligible-for-auto-merge:gate-eligible" "human-merge-required:gate-human"; do
  verdict="${verdict_pair%%:*}"; expected="${verdict_pair##*:}"
  UP_BIN="$TMPROOT/unpark-bin-$expected"; make_stubs "$UP_BIN" "$verdict"
  UP_LOG="$TMPROOT/unpark-$expected.log"; UP_SD="$TMPROOT/unpark-state-$expected"
  UP_OUT="$(run_driver "$UP_BIN" "$UP_LOG" --repo "$REPO" --classify-only "$ISSUE" --state-dir "$UP_SD")"
  UP_ARGV="$(cat "$UP_LOG")"
  has  "$expected: the outcome is what the gate said" "outcome  $expected" "$UP_OUT"
  has_call "  removes the park label from the right issue, in one call" \
           "$UP_LOG" "issue edit $ISSUE" "--remove-label $PARK_LABEL"
  hasnt "  and never adds it"                         "--add-label"        "$UP_ARGV"
done

# --- C4: durability, and --retry still overrides ---------------------------
#
# CRITERION: GIVEN issue N carrying the park label, WHEN selection runs with
# --state-dir pointing at an empty directory, THEN N SHALL be reported as skipped
# with the park reason, AND --retry N SHALL report it eligible in the same
# configuration.
#
# This is the criterion inherited from #3: park state that survives a host
# change. An empty state dir IS a fresh host, as far as selection can tell.

echo "C4: park state survives an empty state dir; --retry still un-parks for one run"

DUR_BIN="$TMPROOT/dur-bin"; make_stubs "$DUR_BIN" "pending"
# NO open PRs in this fixture, and that is load-bearing. With the shared PR
# fixture in place, #7 was skipped as "already has an open PR" and this criterion
# passed while proving nothing about the label -- a row satisfied by evidence
# adjacent to what it names, which is this project's most-repeated defect. With
# the PR list empty, the label is the only thing that can produce a SKIP.
printf '%s' '[]' > "$DUR_BIN/pr-list.json"
DUR_LOG="$TMPROOT/dur.log"
DUR_SD="$TMPROOT/dur-state-empty"; mkdir -p "$DUR_SD"
DUR_OUT="$(run_driver "$DUR_BIN" "$DUR_LOG" --repo "$REPO" --dry-run --state-dir "$DUR_SD")"
# One needle covering both the skip and its reason field. Split across two
# assertions, "parked" alone was satisfied by the fixture ISSUE TITLE -- the same
# adjacent-evidence defect as the PR-list one above, found the same way.
has "fresh host: the labeled issue is skipped, with a reason" "SKIP    #7  parked" "$DUR_OUT"
has "  while the unlabeled issue stays eligible"             "ELIGIBLE #8"        "$DUR_OUT"

RETRY_SD="$TMPROOT/dur-state-retry"; mkdir -p "$RETRY_SD"
RETRY_OUT="$(run_driver "$DUR_BIN" "$DUR_LOG" --repo "$REPO" --dry-run --state-dir "$RETRY_SD" --retry "$ISSUE")"
has "--retry makes the parked issue eligible again"  "ELIGIBLE #7"  "$RETRY_OUT"

# The absorbed G6: the skip reason must cite the CURRENT record, not the first
# one appended. Seeded with two ledger rows for #7, oldest first.
SEED_SD="$TMPROOT/dur-state-seeded"; mkdir -p "$SEED_SD"
cat > "$SEED_SD/runs.jsonl" <<'LEDGER'
{"issue":7,"repo":"stub/repo","outcome":"failed","reason":"first appended reason","cost_usd":1}
{"issue":7,"repo":"stub/repo","outcome":"incomplete","reason":"current reason","cost_usd":2}
LEDGER
SEED_OUT="$(run_driver "$DUR_BIN" "$DUR_LOG" --repo "$REPO" --dry-run --state-dir "$SEED_SD")"
has  "the skip reason cites the latest ledger row"   "current reason"        "$SEED_OUT"
hasnt "  and not the first appended one"             "first appended reason" "$SEED_OUT"

# --- report ----------------------------------------------------------------

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
