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
[{"number":7,"title":"issue carrying the label","body":"body\n\n## Tier: \`auto-ok\`\n","labels":[{"name":"$PARK_LABEL"}]},
 {"number":8,"title":"issue without the label","body":"body\n\n## Tier: \`auto-ok\`\n","labels":[{"name":"enhancement"}]}]
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
  #
  # The argv line was added for issue #39's C1 ("SHALL NOT invoke claude"). Without
  # it that assertion is VACUOUS: nothing would ever write a claude line, so a count
  # of zero would hold whether or not the behaviour exists. The `claude ` prefix
  # keeps these lines apart from the gh lines, so no existing assertion over
  # $ARGV_LOG can see them -- the gh needles ("issue list", "issue edit N",
  # "--add-label", "--remove-label") do not appear in a claude argv, and the two
  # cases that read the log with `hasnt`/`has_call` run --classify-only, which never
  # invokes claude at all. The log is a file, not a stream the driver captures, so
  # writing to it cannot perturb the stream-json contract either.
  cat > "$bin/claude" <<'STUB'
#!/usr/bin/env bash
printf 'claude %s\n' "$*" >> "$ARGV_LOG"
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

PARK_BIN="$TMPROOT/park-bin"; make_stubs "$PARK_BIN" ""

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

# ============================================================================
# FROZEN acceptance checks for issue #39 -- fetch_open_prs swallows failures.
#
#   https://github.com/lmorchard/agent-sessions/issues/39
#
# Appended 2026-07-31. Same rules as everything above: no replicas, no grepping
# the subject for a literal, every assertion over the runtime behaviour of the
# shipped driver run as a subprocess against stubs.
#
# Today `fetch_open_prs` is
#
#     gh pr list ... 2>/dev/null || echo '[]'
#
# so a failed query is indistinguishable from "no open PRs". These three cases
# are all expected to FAIL at freeze; that is the point.
# ============================================================================

# THE NEEDLE, chosen here and named once so the implementer has one string to
# emit and the checks have one string to look for. Short and meaning-bearing on
# purpose: a full sentence would be brittle, and a single common word ("failed",
# "error") already appears in today's output and would be vacuous. Nothing in the
# driver's current output contains this phrase -- verified by these checks
# failing at freeze.
QUERY_FAIL_NEEDLE="open-PR query failed"

# The distinctive text the stub writes to stderr. Deliberately unlike anything
# the driver says on its own, so C3 cannot be satisfied by the driver's own
# diagnostics -- only by gh's stderr actually reaching the driver's output.
GH_STDERR_NEEDLE="stub-gh: HTTP 503 from api.github.com while listing PRs"

# A gh stub variant whose `pr list` arm exits 1 with that stderr, and which
# answers every other read exactly as make_stubs' does. Overwrites only the `gh`
# file inside a case's own stub dir -- the same move C4 makes with pr-list.json.
make_gh_prlist_fails() { # $1 = a dir that make_stubs has already populated
  cat > "$1/gh" <<STUB
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "\$ARGV_LOG"
case "\$*" in
  "pr list"*)            printf '%s\n' "$GH_STDERR_NEEDLE" >&2; exit 1 ;;
  *"--json headRefOid"*) printf 'deadbeefcafe\n' ;;
  *"--json body"*)       cat "\$STUB_DIR/pr-body.txt" ;;
  "issue list"*)         cat "\$STUB_DIR/issue-list.json" ;;
  *)                     exit 0 ;;
esac
STUB
  chmod +x "$1/gh"
}

claude_calls() { # $1 = argv log -- how many times the claude stub ran
  grep -c '^claude ' "$1" 2>/dev/null || true
}

# --- #39 C1: a failed open-PR query stops selection before any spend --------
#
# CRITERION: IF the open-PR query fails, THEN the selection stage SHALL report
# the failure and exit non-zero, AND SHALL NOT invoke `claude`.
#
# NOT --dry-run: dry-run exits before the run loop, so "zero claude invocations"
# would hold there no matter what the driver does. This is a full run with
# selection live, which is the configuration in which today's driver treats the
# failed query as an empty PR list, finds #8 unblocked, and spends real money.
#
# The control run directly below is the non-vacuity proof for the zero-count
# assertion: same fixture, same flags, healthy `pr list` -- and the count is
# expected to be >= 1 there. If the claude stub ever stops logging, the control
# fails and the zero-count check is exposed as meaningless.

echo "#39 C1: a failed open-PR query is reported, exits non-zero, and spends nothing"

QF_SKILL="$TMPROOT/qfail-skill"; mkdir -p "$QF_SKILL/phases"; : > "$QF_SKILL/phases/express.md"
QF_REPOP="$TMPROOT/qfail-repo"; mkdir -p "$QF_REPOP"

QF_BIN="$TMPROOT/qfail-sel-bin"; make_stubs "$QF_BIN" "pending"
make_gh_prlist_fails "$QF_BIN"
QF_LOG="$TMPROOT/qfail-sel.log"; QF_SD="$TMPROOT/qfail-sel-state"
QF_OUT="$(run_driver "$QF_BIN" "$QF_LOG" --repo "$REPO" \
            --skill-dir "$QF_SKILL" --repo-path "$QF_REPOP" \
            --state-dir "$QF_SD" --max-budget-usd 10)"
QF_RC=$?   # must be read immediately: run_driver's last command IS the driver.

has "selection names the open-PR query failure" "$QUERY_FAIL_NEEDLE" "$QF_OUT"
if [ "$QF_RC" -ne 0 ]; then
  ok "  and exits non-zero"
else
  bad "  and exits non-zero" "a non-zero exit status" "$QF_RC"
fi
check "  and never invokes claude" "0" "$(claude_calls "$QF_LOG")"

# The control. Identical except that `pr list` works.
CTRL_BIN="$TMPROOT/qfail-ctrl-bin"; make_stubs "$CTRL_BIN" "pending"
CTRL_LOG="$TMPROOT/qfail-ctrl.log"; CTRL_SD="$TMPROOT/qfail-ctrl-state"
run_driver "$CTRL_BIN" "$CTRL_LOG" --repo "$REPO" \
  --skill-dir "$QF_SKILL" --repo-path "$QF_REPOP" \
  --state-dir "$CTRL_SD" --max-budget-usd 10 >/dev/null
CTRL_CALLS="$(claude_calls "$CTRL_LOG")"
if [ "${CTRL_CALLS:-0}" -ge 1 ]; then
  ok "  control: with a healthy query the same run DOES invoke claude"
else
  bad "  control: with a healthy query the same run DOES invoke claude" \
      "at least 1 logged claude call (else the zero-count check above is vacuous)" \
      "${CTRL_CALLS:-0}"
fi

# --- #39 C2/C3: a failed query at post-run discovery ------------------------
#
# C2 CRITERION: GIVEN the open-PR query fails during post-run PR discovery, WHEN
# the driver records the run's outcome, THEN the recorded reason SHALL name the
# query failure AND SHALL NOT be the `no PR opened` reason.
#
# C3 CRITERION: WHEN the open-PR query fails, THEN `gh`'s stderr SHALL appear in
# the driver's output.
#
# `--issue` bypasses selection entirely, so the ONLY `fetch_open_prs` call in
# this run is the post-run discovery one. That is what makes "fails only at
# discovery" true structurally rather than by stub bookkeeping, and it is also
# what makes C3 attributable: there is exactly one query, so the stderr can have
# come from nowhere else.

echo "#39 C2/C3: a failed query at discovery is recorded as such, and gh's stderr surfaces"

PD_BIN="$TMPROOT/qfail-disc-bin"; make_stubs "$PD_BIN" "pending"
make_gh_prlist_fails "$PD_BIN"
PD_LOG="$TMPROOT/qfail-disc.log"; PD_SD="$TMPROOT/qfail-disc-state"
PD_SKILL="$TMPROOT/qfail-disc-skill"; mkdir -p "$PD_SKILL/phases"; : > "$PD_SKILL/phases/express.md"
PD_REPOP="$TMPROOT/qfail-disc-repo"; mkdir -p "$PD_REPOP"
PD_OUT="$(run_driver "$PD_BIN" "$PD_LOG" --repo "$REPO" --issue "$ISSUE" \
            --skill-dir "$PD_SKILL" --repo-path "$PD_REPOP" \
            --state-dir "$PD_SD" --max-budget-usd 10)"

# The ledger row for this issue, newest last -- the same "current record, not the
# first appended" rule C4 above establishes.
PD_REASON="$(jq -r --arg n "$ISSUE" 'select(.issue == ($n|tonumber)) | .reason // empty' \
               "$PD_SD/runs.jsonl" 2>/dev/null | tail -1)"
[ -n "$PD_REASON" ] || PD_REASON="(no runs.jsonl row for #$ISSUE)"

has   "the recorded reason names the query failure" "$QUERY_FAIL_NEEDLE" "$PD_REASON"
hasnt "  and is not the no-PR-opened reason"        "no PR opened"       "$PD_REASON"
has   "gh's stderr reaches the driver's output"     "$GH_STDERR_NEEDLE"  "$PD_OUT"

# ============================================================================
# FROZEN acceptance checks for issue #51 -- the live-orphan refusal also blocks
# --dry-run, which spends nothing.
#
#   https://github.com/lmorchard/agent-sessions/issues/51
#
# Appended 2026-08-01. Same rules as everything above: no replicas, no grepping
# the subject for a literal, every assertion over the runtime behaviour of the
# shipped driver run as a subprocess against stubs.
#
# Today the startup orphan check `die`s for EVERY invocation once it finds an
# inflight.json whose run dir holds a child.pid naming a live process. --dry-run
# invokes no claude, writes nothing to the state dir and creates no worktree, so
# the refusal costs a human an intervention and protects nothing. C1 is expected
# to FAIL at freeze; G1/G2 and the control are expected to PASS, and must keep
# passing -- the refusal must survive for the invocations that DO spend.
# ============================================================================

# The live process the fixture points at. Spawned here, killed below and again
# on EXIT: a borrowed pid ($$, 1, a literal) would make the fixture a lie or make
# it flaky, and either way C1 would test nothing.
sleep 300 &
ORPHAN_PID=$!
# Extend the existing cleanup rather than dropping it -- $TMPROOT must still go.
trap 'kill "$ORPHAN_PID" 2>/dev/null; rm -rf "$TMPROOT"' EXIT

# Deliberately NOT $ISSUE (7): the park-label fixtures are all about #7, and an
# orphan marker carrying the same number could be confused for one of them.
ORPHAN_ISSUE=99
ORPHAN_TS=20260801T000000Z

# The marker a driver that died between invoking and recording leaves behind:
# inflight.json plus the run dir's child.pid. Shape taken from what the driver
# writes at invoke time and reads at startup -- .run_dir out of the JSON, then
# child.pid inside it.
make_live_orphan() { # $1 = state dir, $2 = the pid to name
  local sd="$1" pid="$2" rundir
  rundir="$sd/runs/$ORPHAN_ISSUE-$ORPHAN_TS"
  mkdir -p "$rundir"
  printf '%s\n' "$pid" > "$rundir/child.pid"
  jq -n -c --arg issue "$ORPHAN_ISSUE" --arg ts "$ORPHAN_TS" --arg rundir "$rundir" \
     --arg url "https://github.com/$REPO/issues/$ORPHAN_ISSUE" \
     '{issue:($issue|tonumber), started:$ts, run_dir:$rundir, url:$url}' \
     > "$sd/inflight.json"
}

# --- #51 C1: --dry-run reports the orphan but does not refuse ---------------
#
# CRITERION: GIVEN a state dir whose inflight.json names a LIVE child pid, WHEN
# the driver is invoked with --dry-run, THEN it SHALL still print the orphan
# warning, complete selection, and exit 0.
#
# All three assertions matter together: an exit 0 that skipped the warning would
# hide a live orphan from the operator, and an exit 0 that skipped selection
# would make --dry-run useless in exactly the state it is being unblocked for.
#
# The control immediately below is the attributability proof: same fixture, same
# flags, child.pid deleted. It must PASS at freeze while these FAIL, which is
# what shows the exit 2 comes from the live-orphan marker and not from anything
# incidental to the fixture (the state dir, the inflight.json, the run dir).

echo "#51 C1: --dry-run reports a live orphan but does not refuse"

OR_BIN="$TMPROOT/orphan-dry-bin"; make_stubs "$OR_BIN" "pending"
OR_LOG="$TMPROOT/orphan-dry.log"; OR_SD="$TMPROOT/orphan-dry-state"
make_live_orphan "$OR_SD" "$ORPHAN_PID"
OR_OUT="$(run_driver "$OR_BIN" "$OR_LOG" --repo "$REPO" --dry-run --state-dir "$OR_SD")"
OR_RC=$?   # must be read immediately: run_driver's last command IS the driver.

check "dry-run exits 0 with a live orphan present" "0" "$OR_RC"
has   "  and still prints the orphan warning" "ORPHAN STILL RUNNING" "$OR_OUT"
has   "  and still completes selection"       "ELIGIBLE #8"          "$OR_OUT"

# The control. Its own state dir, so deleting the pid file cannot perturb the
# case above no matter what order these run in.
OC_LOG="$TMPROOT/orphan-ctrl.log"; OC_SD="$TMPROOT/orphan-ctrl-state"
make_live_orphan "$OC_SD" "$ORPHAN_PID"
rm -f "$OC_SD/runs/$ORPHAN_ISSUE-$ORPHAN_TS/child.pid"
run_driver "$OR_BIN" "$OC_LOG" --repo "$REPO" --dry-run --state-dir "$OC_SD" >/dev/null
OC_RC=$?
check "  control: with the pid file removed, dry-run exits 0" "0" "$OC_RC"

# --- #51 G1/G2: the refusal survives for the invocations that spend ---------
#
# G1: a real run against the SAME live-orphan fixture still exits non-zero and
# never invokes claude. This is the guard the whole refusal exists for -- two
# concurrent runs against one state dir, the second one spending money while the
# first is still live.
#
# G2: --classify-only still refuses too. It writes a ledger row and moves park
# labels for a run that is still in flight, so it is not a read-only invocation
# the way --dry-run is, and exempting it would be the obvious over-reach.
#
# The zero-claude-call assertion is non-vacuous for the same reason #39 C1's is,
# and by the same evidence: the claude stub logs its argv, and #39 C1's control
# above proves a healthy run of this shape DOES produce at least one such line.

echo "#51 G1/G2: run and --classify-only still refuse, and spend nothing"

OR_SKILL="$TMPROOT/orphan-skill"; mkdir -p "$OR_SKILL/phases"; : > "$OR_SKILL/phases/express.md"
OR_REPOP="$TMPROOT/orphan-repo"; mkdir -p "$OR_REPOP"

OG1_BIN="$TMPROOT/orphan-run-bin"; make_stubs "$OG1_BIN" "pending"
OG1_LOG="$TMPROOT/orphan-run.log"; OG1_SD="$TMPROOT/orphan-run-state"
make_live_orphan "$OG1_SD" "$ORPHAN_PID"
run_driver "$OG1_BIN" "$OG1_LOG" --repo "$REPO" \
  --skill-dir "$OR_SKILL" --repo-path "$OR_REPOP" \
  --state-dir "$OG1_SD" --max-budget-usd 10 >/dev/null 2>&1
OG1_RC=$?

if [ "$OG1_RC" -ne 0 ]; then
  ok "a real run still refuses while the orphan is live"
else
  bad "a real run still refuses while the orphan is live" "a non-zero exit status" "$OG1_RC"
fi
check "  and never invokes claude" "0" "$(claude_calls "$OG1_LOG")"

OG2_BIN="$TMPROOT/orphan-classify-bin"; make_stubs "$OG2_BIN" "pending"
OG2_LOG="$TMPROOT/orphan-classify.log"; OG2_SD="$TMPROOT/orphan-classify-state"
make_live_orphan "$OG2_SD" "$ORPHAN_PID"
run_driver "$OG2_BIN" "$OG2_LOG" --repo "$REPO" --classify-only "$ISSUE" \
  --state-dir "$OG2_SD" >/dev/null 2>&1
OG2_RC=$?

if [ "$OG2_RC" -ne 0 ]; then
  ok "--classify-only still refuses while the orphan is live"
else
  bad "--classify-only still refuses while the orphan is live" "a non-zero exit status" "$OG2_RC"
fi

# Done with the fixture's process. The EXIT trap kills it too, so an early exit
# above cannot leak it either.
kill "$ORPHAN_PID" 2>/dev/null
wait "$ORPHAN_PID" 2>/dev/null

# ============================================================================
# FROZEN acceptance checks for issue #58 -- "no session, no spend" is inferred
# from an ABSENT result record, so an extractor miss is recorded as a fact about
# the run.
#
#   https://github.com/lmorchard/agent-sessions/issues/58
#
# Appended 2026-08-03. Same rules as everything above: no replicas, no grepping
# the subject for a literal, every assertion over the runtime behaviour of the
# shipped driver run as a subprocess against stubs.
#
# Today the classifier is
#
#     elif [ "$rc" -ne 0 ] && [ -z "$session" ] && [ "${cost:-0}" = "0" ]; then
#       outcome="driver-fault"
#       reason="claude exited $rc before starting (no session, no spend) ..."
#
# and `session` / `cost` both come from `pick_result`, which emits NOTHING when
# the stream carries no `type=="result"` record. So "the extractor found nothing"
# is rendered as "the run never started and spent nothing" -- recorded live for a
# run that spent $10.93.
#
# C1 and C2 are expected to FAIL at freeze. G3 is expected to PASS and must KEEP
# passing: it is what stops C1 being satisfied by deleting the driver-fault
# branch, which is the cheap fix and would lose the distinction the branch was
# added for (a driver fault is fixed by editing the script; an escalation is not).
# ============================================================================

# THE NEEDLE for C2, chosen here and named once so the implementer has one string
# to emit and the check has one string to look for. Two words, meaning-bearing:
# a full sentence would be brittle, and a single common word ("unknown", "cost")
# either already appears in today's output or would match by accident. Verified
# absent from the driver source and from every reason it can currently write
# (`grep -niE 'undetermin' driver/` finds nothing) -- and confirmed absent from
# the runtime output by C2 failing at freeze.
COST_UNKNOWN_NEEDLE="cost undetermined"

# The claim the reason must stop making. This is the literal substring today's
# driver-fault reason carries, which is what makes its absence meaningful --
# but only alongside the positive needle above, which is why C2 asserts both.
# A `hasnt` on its own would be satisfied by any rewording, including a wrong one.
NO_SPEND_CLAIM="no spend"

# The nonzero status both #58 stubs exit with. Named once so the two fixtures
# differ in exactly ONE thing -- whether the stream carries events -- and the
# difference between C1's outcome and G3's cannot be attributed to the exit code.
NORESULT_EXIT=3

# The cost G4's result record carries. The figure from the live incident, on
# purpose: #58 was recorded as "no spend" for a run that spent this much.
KNOWN_COST=10.93

# A `claude` stub that emits real events and then dies WITHOUT a result record:
# the truncated-stream shape, which is what a killed or disconnected run leaves
# behind. Overwrites only the `claude` file inside a case's own stub dir -- the
# same move make_gh_prlist_fails makes with `gh`. The argv line is kept so
# claude_calls can prove the stub ran.
#
# NO `system`/`init` RECORD, deliberately, and this is the load-bearing detail.
# A first draft carried one for realism. It made the fixture differ from G3's in
# TWO respects -- the stream has events (the criterion's GIVEN) and a session_id
# exists somewhere in the stream (not the criterion) -- so "scan the whole stream
# for any session_id" would green C1, keep G3 green, and be unconstrained by any
# assertion here, while a stream with events and no init record still classified
# driver-fault. That is the criterion's own GIVEN left broken by a fix the checks
# accepted. Two assistant events and nothing else: events are the only variable.
make_claude_no_result() { # $1 = a dir that make_stubs has already populated
  cat > "$1/claude" <<STUB
#!/usr/bin/env bash
printf 'claude %s\n' "\$*" >> "\$ARGV_LOG"
cat >/dev/null
printf '%s\n' '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"stub run started"}]}}'
printf '%s\n' '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"stub run still going"}]}}'
exit $NORESULT_EXIT
STUB
  chmod +x "$1/claude"
}

# The G4 stub: make_claude_no_result's stream PLUS a result record that carries a
# real cost. Nonzero exit, non-empty session, no SUCCESS result -- so this lands
# in the `failed` branch, and the cost was never in doubt.
make_claude_cost_known() { # $1 = a dir that make_stubs has already populated
  cat > "$1/claude" <<STUB
#!/usr/bin/env bash
printf 'claude %s\n' "\$*" >> "\$ARGV_LOG"
cat >/dev/null
printf '%s\n' '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"stub run started"}]}}'
printf '%s\n' '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"stub run still going"}]}}'
printf '%s\n' '{"type":"result","subtype":"error_during_execution","is_error":true,"total_cost_usd":$KNOWN_COST,"session_id":"stub-errored-session","result":"boom"}'
exit $NORESULT_EXIT
STUB
  chmod +x "$1/claude"
}

# A `claude` stub for the genuine never-started case: nothing on stdout at all,
# so the captured stream is zero bytes, and a nonzero exit. This is the run the
# driver-fault branch exists for.
make_claude_never_starts() { # $1 = a dir that make_stubs has already populated
  cat > "$1/claude" <<STUB
#!/usr/bin/env bash
printf 'claude %s\n' "\$*" >> "\$ARGV_LOG"
cat >/dev/null
exit $NORESULT_EXIT
STUB
  chmod +x "$1/claude"
}

# --- #58 C1/C2: a truncated stream is not a never-started run ---------------
#
# C1 CRITERION: GIVEN a run whose `stream.jsonl` contains events but no parseable
# `result` record, WHEN the driver classifies a nonzero exit, THEN it SHALL NOT
# classify the run `driver-fault`.
#
# C2 CRITERION: WHEN the cost of a run cannot be determined, THEN the recorded
# reason SHALL say so, and SHALL NOT assert that the run did not spend.
#
# One fixture, both criteria: they are two halves of the same misreading, and
# splitting the fixture would let a fix satisfy one shape of stream and not the
# other.
#
# `--issue` bypasses selection, so this is the classification path and nothing
# else. The four attributability assertions immediately below MUST PASS at
# freeze; they are what makes the C failures mean "the driver did the wrong
# thing" rather than "the stub is broken". Specifically they rule out, in order:
# a stub that never ran, an empty ledger, an empty stream (which would be G3's
# fixture, not this one), and a stream that accidentally carries a result record
# (which would route to a different branch entirely).

echo "#58 C1/C2: a stream with events but no result record is not a never-started run"

NRS_BIN="$TMPROOT/noresult-bin"; make_stubs "$NRS_BIN" "pending"
make_claude_no_result "$NRS_BIN"
NRS_LOG="$TMPROOT/noresult.log"; NRS_SD="$TMPROOT/noresult-state"
NRS_SKILL="$TMPROOT/noresult-skill"; mkdir -p "$NRS_SKILL/phases"; : > "$NRS_SKILL/phases/express.md"
NRS_REPOP="$TMPROOT/noresult-repo"; mkdir -p "$NRS_REPOP"
NRS_OUT="$(run_driver "$NRS_BIN" "$NRS_LOG" --repo "$REPO" --issue "$ISSUE" \
             --skill-dir "$NRS_SKILL" --repo-path "$NRS_REPOP" \
             --state-dir "$NRS_SD" --max-budget-usd 10)"

# The ledger row for this issue, newest last -- the same "current record, not the
# first appended" rule C4 above establishes.
NRS_ROW="$(jq -rc --arg n "$ISSUE" 'select(.issue == ($n|tonumber))' \
             "$NRS_SD/runs.jsonl" 2>/dev/null | tail -1)"
NRS_OUTCOME="$(printf '%s' "$NRS_ROW" | jq -r '.outcome // empty' 2>/dev/null || true)"
NRS_REASON="$(printf '%s' "$NRS_ROW"  | jq -r '.reason  // empty' 2>/dev/null || true)"
NRS_RUNDIR="$(printf '%s' "$NRS_ROW"  | jq -r '.run_dir // empty' 2>/dev/null || true)"
[ -n "$NRS_OUTCOME" ] || NRS_OUTCOME="(no runs.jsonl row for #$ISSUE)"
[ -n "$NRS_REASON" ]  || NRS_REASON="(no runs.jsonl row for #$ISSUE)"
NRS_STREAM="${NRS_RUNDIR:-/nonexistent}/stream.jsonl"
NRS_EVENTS="$(jq -s 'length' "$NRS_STREAM" 2>/dev/null || echo 0)"
NRS_RESULTS="$(jq -s '[.[] | select(.type=="result")] | length' "$NRS_STREAM" 2>/dev/null || echo -1)"

NRS_CALLS="$(claude_calls "$NRS_LOG")"
if [ "${NRS_CALLS:-0}" -ge 1 ]; then
  ok "attributability: the fixture really invoked the claude stub"
else
  bad "attributability: the fixture really invoked the claude stub" \
      "at least 1 logged claude call" "${NRS_CALLS:-0}"
fi
if [ -n "$NRS_ROW" ]; then
  ok "  and the run really wrote a ledger row for #$ISSUE"
else
  bad "  and the run really wrote a ledger row for #$ISSUE" \
      "a runs.jsonl row" "$(cat "$NRS_SD/runs.jsonl" 2>/dev/null || echo MISSING)"
fi
# Pinned to the exact record count, not `>= 1`. The fixture is deterministic, and
# an exact count is what stops a session-bearing `system`/`init` line creeping
# back in and re-introducing the second variable the stub's comment warns about.
check "  and the captured stream carries exactly the fixture's 2 events" "2" "${NRS_EVENTS:-0}"
check "  and really carries no result record" "0" "$NRS_RESULTS"

hasnt "C1: the run is NOT classified driver-fault" "driver-fault" "$NRS_OUTCOME"
has   "C2: the recorded reason names the cost as undetermined" \
      "$COST_UNKNOWN_NEEDLE" "$NRS_REASON"
hasnt "C2:   and does not claim the run did not spend" \
      "$NO_SPEND_CLAIM" "$NRS_REASON"

# --- #58 G3: a genuine never-started run is STILL driver-fault --------------
#
# GUARD: an empty stream, no session and no cost is still `driver-fault`.
#
# This must PASS at freeze and keep passing. Without it, C1 is satisfied by
# deleting the driver-fault branch -- which is the cheap fix, and would throw
# away the one distinction the branch was added for. The fixture differs from
# C1/C2's in exactly one respect: the stub writes nothing to stdout. Same exit
# status, same gh stub, same flags.

echo "#58 G3: a genuine never-started run is still driver-fault"

NST_BIN="$TMPROOT/nostart-bin"; make_stubs "$NST_BIN" "pending"
make_claude_never_starts "$NST_BIN"
NST_LOG="$TMPROOT/nostart.log"; NST_SD="$TMPROOT/nostart-state"
NST_SKILL="$TMPROOT/nostart-skill"; mkdir -p "$NST_SKILL/phases"; : > "$NST_SKILL/phases/express.md"
NST_REPOP="$TMPROOT/nostart-repo"; mkdir -p "$NST_REPOP"
run_driver "$NST_BIN" "$NST_LOG" --repo "$REPO" --issue "$ISSUE" \
  --skill-dir "$NST_SKILL" --repo-path "$NST_REPOP" \
  --state-dir "$NST_SD" --max-budget-usd 10 >/dev/null 2>&1

NST_ROW="$(jq -rc --arg n "$ISSUE" 'select(.issue == ($n|tonumber))' \
             "$NST_SD/runs.jsonl" 2>/dev/null | tail -1)"
NST_OUTCOME="$(printf '%s' "$NST_ROW" | jq -r '.outcome // empty' 2>/dev/null || true)"
NST_RUNDIR="$(printf '%s' "$NST_ROW" | jq -r '.run_dir // empty' 2>/dev/null || true)"
[ -n "$NST_OUTCOME" ] || NST_OUTCOME="(no runs.jsonl row for #$ISSUE)"
NST_STREAM="${NST_RUNDIR:-/nonexistent}/stream.jsonl"
NST_BYTES="$(wc -c < "$NST_STREAM" 2>/dev/null | tr -d ' ' || echo -1)"

# The fixture self-check, for the same reason C1/C2 has one: a zero-byte stream
# is the whole premise, and a stub that failed to run would produce one too.
check "attributability: the never-started fixture's stream is zero bytes" "0" "${NST_BYTES:-missing}"
NST_CALLS="$(claude_calls "$NST_LOG")"
if [ "${NST_CALLS:-0}" -ge 1 ]; then
  ok "  and the claude stub really ran (so the zero bytes are its output, not its absence)"
else
  bad "  and the claude stub really ran (so the zero bytes are its output, not its absence)" \
      "at least 1 logged claude call" "${NST_CALLS:-0}"
fi

check "G3: the never-started run is still classified driver-fault" "driver-fault" "$NST_OUTCOME"

# --- #58 G4: the needle is CONDITIONAL, not decoration ----------------------
#
# GUARD: WHEN the cost of a run IS determinable, the reason SHALL NOT claim it is
# undetermined.
#
# This is C2's negative control, and without it C2 is satisfiable by emitting
# $COST_UNKNOWN_NEEDLE unconditionally -- append it to the `failed` branch's
# reason and both C2 assertions green with the driver never asking whether the
# cost was determinable. That manufactures #58 inverted: a run whose result
# record says $10.93 gets cost_usd 10.93 in the ledger with "cost undetermined"
# in the reason beside it. A false fact about the run, which is the class this
# issue exists to close.
#
# The fixture differs from C1/C2's in exactly one respect: a trailing result
# record. Nonzero exit and no SUCCESS result, so it lands in the `failed` branch.
#
# --max-budget-usd 100, NOT 10, and the reason matters: at $10.93 of $10 this run
# is over budget. The budget reclassification at agent-session-driver.sh:970 only
# rewrites incomplete/parked/no-gate, so `failed` is safe today -- but depending
# on that is a hidden coupling to a case list #58 is not touching, and a check
# that breaks when an unrelated list grows is a check that trains people to wave
# it through. A ceiling the fixture cannot reach removes the coupling entirely.

echo "#58 G4: a determinable cost is not reported as undetermined"

CK_BIN="$TMPROOT/costknown-bin"; make_stubs "$CK_BIN" "pending"
make_claude_cost_known "$CK_BIN"
CK_LOG="$TMPROOT/costknown.log"; CK_SD="$TMPROOT/costknown-state"
CK_SKILL="$TMPROOT/costknown-skill"; mkdir -p "$CK_SKILL/phases"; : > "$CK_SKILL/phases/express.md"
CK_REPOP="$TMPROOT/costknown-repo"; mkdir -p "$CK_REPOP"
run_driver "$CK_BIN" "$CK_LOG" --repo "$REPO" --issue "$ISSUE" \
  --skill-dir "$CK_SKILL" --repo-path "$CK_REPOP" \
  --state-dir "$CK_SD" --max-budget-usd 100 >/dev/null 2>&1

CK_ROW="$(jq -rc --arg n "$ISSUE" 'select(.issue == ($n|tonumber))' \
            "$CK_SD/runs.jsonl" 2>/dev/null | tail -1)"
CK_REASON="$(printf '%s' "$CK_ROW"  | jq -r '.reason   // empty' 2>/dev/null || true)"
CK_COST="$(printf '%s' "$CK_ROW"    | jq -r '.cost_usd // empty' 2>/dev/null || true)"
CK_RUNDIR="$(printf '%s' "$CK_ROW"  | jq -r '.run_dir  // empty' 2>/dev/null || true)"
[ -n "$CK_REASON" ] || CK_REASON="(no runs.jsonl row for #$ISSUE)"
CK_STREAM="${CK_RUNDIR:-/nonexistent}/stream.jsonl"
CK_RESULTS="$(jq -s '[.[] | select(.type=="result")] | length' "$CK_STREAM" 2>/dev/null || echo -1)"

# Attributability: this fixture's whole premise is that a result record is
# present and its cost reached the ledger. Both are asserted, so a `hasnt` that
# held because the run never happened would be caught here instead.
check "attributability: the cost-known fixture's stream carries one result record" "1" "$CK_RESULTS"
check "  and its cost really reached the ledger" "$KNOWN_COST" "${CK_COST:-missing}"

hasnt "G4: a run whose cost IS determinable is not reported as undetermined" \
      "$COST_UNKNOWN_NEEDLE" "$CK_REASON"

# --- #82: Close the flush race (recover the cost inline) ---------------------
#
# C1 CRITERION: GIVEN a run whose cost is undetermined at exit time because of a stream flush race,
# WHEN the driver waits briefly and re-parses, THEN it SHALL recover the cost and session id.

echo "#82: Close the flush race (recover the cost inline)"

DEL_BIN="$TMPROOT/delayed-bin"; make_stubs "$DEL_BIN" "pending"

# Define the delayed-cost stub
cat > "$DEL_BIN/claude" <<'STUB'
#!/usr/bin/env bash
printf 'claude %s\n' "$*" >> "$ARGV_LOG"
cat >/dev/null
printf '%s\n' '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"stub delayed started"}]}}'
printf '%s\n' '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"stub delayed still going"}]}}'

if [ -n "$DEL_SD_ENV" ]; then
  RUNDIR="$(ls -td "$DEL_SD_ENV/runs/"*-* 2>/dev/null | head -1 || true)"
  if [ -n "$RUNDIR" ] && [ -d "$RUNDIR" ]; then
    (sleep 0.2 && printf '{"type":"result","subtype":"error_during_execution","is_error":true,"total_cost_usd":10.93,"session_id":"delayed-session","result":"boom"}\n' >> "$RUNDIR/stream.jsonl") &
  fi
fi

exit 3
STUB
chmod +x "$DEL_BIN/claude"

DEL_LOG="$TMPROOT/delayed.log"; DEL_SD="$TMPROOT/delayed-state"
DEL_SKILL="$TMPROOT/delayed-skill"; mkdir -p "$DEL_SKILL/phases"; : > "$DEL_SKILL/phases/express.md"
DEL_REPOP="$TMPROOT/delayed-repo"; mkdir -p "$DEL_REPOP"

export DEL_SD_ENV="$DEL_SD"

DEL_OUT="$(run_driver "$DEL_BIN" "$DEL_LOG" --repo "$REPO" --issue "$ISSUE" \
             --skill-dir "$DEL_SKILL" --repo-path "$DEL_REPOP" \
             --state-dir "$DEL_SD" --max-budget-usd 100)"

# Verify that the ledger row recorded the recovered cost and session id!
DEL_ROW="$(jq -rc --arg n "$ISSUE" 'select(.issue == ($n|tonumber))' \
             "$DEL_SD/runs.jsonl" 2>/dev/null | tail -1)"
DEL_COST="$(printf '%s' "$DEL_ROW" | jq -r '.cost_usd // empty' 2>/dev/null || true)"
DEL_SESSION="$(printf '%s' "$DEL_ROW" | jq -r '.session_id // empty' 2>/dev/null || true)"

check "#82 C1: the cost really reached the ledger after delayed flush" "10.93" "$DEL_COST"
check "  and its session id was recovered" "delayed-session" "$DEL_SESSION"

unset DEL_SD_ENV

# --- report ----------------------------------------------------------------

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
