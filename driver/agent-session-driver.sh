#!/usr/bin/env bash
#
# agent-session board-driver
#
# Picks the next eligible issue, runs `agent-session express` on it via headless
# `claude -p`, classifies the outcome from the PR's gate block, and stops.
#
# It NEVER merges. `eligible-for-auto-merge` is a finding this script records.
#
# Design + rationale: docs/dev-sessions/2026-07-25-0926-board-driver/spec.md
#
# Deliberately host-agnostic: no $HOME assumptions, every path a flag, no
# interactive prompts, all mutable state under one --state-dir. The GitHub
# Actions host is meant to run this file unchanged.

set -euo pipefail

MARKER='<!-- agent-session:spec -->'
GATE_MARKER='<!-- agent-session:gate -->'

# Park state lives on the ISSUE, as a label, and this is the whole name of it.
#
# It used to live in ./.driver-state/parked.jsonl, which was wrong twice over: the
# file is append-only with no un-park record, so every entry it ever produced went
# stale the moment a later run succeeded (all three effective entries were), and it
# is a gitignored path relative to cwd, so a host change silently un-parked
# everything. A label is durable, scoped to the target repo -- parked.jsonl records
# no repo at all -- and visible on the issue, where a human decides whether to
# --retry. See issue #5, decision D2.
PARK_LABEL='driver-parked'

# --- defaults --------------------------------------------------------------

REPO=""
SKILL_DIR=""
REPO_PATH=""
ISSUE=""
MAX_ISSUES=1
MAX_BUDGET=10
RUN_TIMEOUT=5400
STATE_DIR="./.driver-state"
BOARD=""
DRY_RUN=0
ALLOW_NESTED=0
RETRY=""
CLASSIFY_ONLY=""
MODEL=""

# `dontAsk` denies non-allowlisted mutating commands but auto-allows commands it
# classifies read-only -- measured, see spec.md "Permissions". The allowlist is
# wide because `express` legitimately builds, writes code, dispatches subagents
# and opens a PR. What it buys is a floor, not a sandbox.
ALLOWED_TOOLS='Read,Write,Edit,Glob,Grep,Task,TodoWrite,BashOutput,KillShell,NotebookEdit,Bash(git:*),Bash(gh:*),Bash(make:*),Bash(uv:*),Bash(uvx:*),Bash(python:*),Bash(python3:*),Bash(pytest:*),Bash(ruff:*),Bash(npm:*),Bash(npx:*),Bash(node:*),Bash(mkdir:*),Bash(cp:*),Bash(mv:*),Bash(touch:*),Bash(ls:*),Bash(cat:*),Bash(grep:*),Bash(rg:*),Bash(jq:*),Bash(sed:*),Bash(awk:*),Bash(wc:*),Bash(head:*),Bash(tail:*),Bash(sort:*),Bash(uniq:*),Bash(cut:*),Bash(find:*),Bash(diff:*),Bash(echo:*),Bash(printf:*),Bash(pwd:*),Bash(cd:*),Bash(test:*),Bash(true:*),Bash(date:*),Bash(basename:*),Bash(dirname:*),Bash(realpath:*)'

# Deny rules take precedence over allow rules and match multi-word command
# prefixes -- measured. This is the mechanism behind "nothing merges"; the
# prompt says it once, and once is enough because the mechanism is here.
# Not airtight (prefix-matched, so `gh api` remains reachable). The airtight
# version is a PreToolUse hook, required before any UNWATCHED host.
DENIED_TOOLS='Bash(gh pr merge:*),Bash(gh pr merge *),Bash(git push --force:*),Bash(gh repo delete:*)'

# --- plumbing --------------------------------------------------------------

log()  { printf '%s  %s\n' "$(date -u +%H:%M:%SZ)" "$*" >&2; }
say()  { printf '%s\n' "$*"; }
die()  { printf 'error: %s\n' "$*" >&2; exit 2; }

usage() {
  cat <<'EOF'
agent-session-driver.sh --repo <owner/name> --skill-dir <path> --repo-path <path> [options]

  --repo <owner/name>     target repository (required)
  --skill-dir <path>      agent-session skill directory (required)
  --repo-path <path>      local checkout of the target repo; the run's cwd (required).
                          express creates its own worktree inside this.
  --issue <n>             skip selection, attempt exactly this issue
  --max-issues <n>        issues per invocation (default 1)
  --max-budget-usd <amt>  per-run ceiling (default 10)
  --timeout <seconds>     per-run wall clock (default 5400)
  --state-dir <path>      run history + per-run transcripts (default ./.driver-state).
                          Park state is NOT here: it is a label on the issue.
  --board <owner/number>  optional; advisory board-column reporting
  --model <name>          optional; passed to claude
  --dry-run               selection only; no claude invocation
  --allow-nested-skill-dir
                          proceed when --skill-dir resolves inside --repo-path.
                          The run cannot write skill files either way (see
                          DENIED_TOOLS), but the nesting is usually a typo, so it
                          must be opted into. Pointing the driver at its own repo
                          is the legitimate case the flag exists for.
  --retry <n>             ignore issue n's park label for this invocation
  --classify-only <n>     classify + record issue n from live PR state; no
                          claude invocation. Recovers the outcome of a run whose
                          driver died after the run itself finished.
  -h, --help              this text
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --repo)           REPO="${2:?}"; shift 2 ;;
    --skill-dir)      SKILL_DIR="${2:?}"; shift 2 ;;
    --repo-path)      REPO_PATH="${2:?}"; shift 2 ;;
    --issue)          ISSUE="${2:?}"; shift 2 ;;
    --max-issues)     MAX_ISSUES="${2:?}"; shift 2 ;;
    --max-budget-usd) MAX_BUDGET="${2:?}"; shift 2 ;;
    --timeout)        RUN_TIMEOUT="${2:?}"; shift 2 ;;
    --state-dir)      STATE_DIR="${2:?}"; shift 2 ;;
    --board)          BOARD="${2:?}"; shift 2 ;;
    --model)          MODEL="${2:?}"; shift 2 ;;
    --retry)          RETRY="${2:?}"; shift 2 ;;
    --classify-only)  CLASSIFY_ONLY="${2:?}"; shift 2 ;;
    --dry-run)        DRY_RUN=1; shift ;;
    --allow-nested-skill-dir) ALLOW_NESTED=1; shift ;;
    -h|--help)        usage; exit 0 ;;
    *)                die "unknown argument: $1 (try --help)" ;;
  esac
done

[ -n "$REPO" ] || die "--repo is required"
# --dry-run and --classify-only never invoke claude, so they need neither the
# skill nor a checkout.
if [ "$DRY_RUN" -eq 0 ] && [ -z "$CLASSIFY_ONLY" ]; then
  [ -n "$SKILL_DIR" ] || die "--skill-dir is required (omit only with --dry-run)"
  [ -n "$REPO_PATH" ] || die "--repo-path is required (omit only with --dry-run)"
  [ -d "$SKILL_DIR" ] || die "--skill-dir does not exist: $SKILL_DIR"
  [ -d "$REPO_PATH" ] || die "--repo-path does not exist: $REPO_PATH"
  [ -f "$SKILL_DIR/phases/express.md" ] || die "no phases/express.md under $SKILL_DIR"

  # Containment is a fact about RESOLVED paths, not about the argument strings --
  # `--skill-dir ./skills/agent-session --repo-path .` is the nested case and the
  # two strings share no prefix at all. abspath() below runs too late and only
  # prepends $PWD; it does not fold `.`/`..`. So resolve both here, with the shell
  # builtin rather than realpath, which is not in the required-command loop.
  #
  # CDPATH= because SKILL_DIR really can still be relative at this point, and a
  # relative `cd` with CDPATH set resolves against it AND echoes the destination,
  # which would corrupt the capture.
  #
  # This does NOT protect the skill files: DENIED_TOOLS is assembled from
  # SKILL_DIR unconditionally, so a nested run still cannot write them. What it
  # catches is a MISTYPED --skill-dir that silently aims the deny rules at paths
  # the run legitimately needs. Pointing the driver at its own repo is nested and
  # correct -- which is why this is an opt-in refusal and not a hard error.
  #
  # `-d` is not enough to guarantee the cd succeeds -- a directory without the
  # execute bit passes -d and cannot be entered. Without the `|| die` that would
  # abort under `set -e` with no message at all, which is the confusing failure
  # this whole check exists to replace.
  skill_real="$(CDPATH= cd -- "$SKILL_DIR" && pwd -P)" \
    || die "cannot resolve --skill-dir: $SKILL_DIR"
  repo_real="$(CDPATH= cd -- "$REPO_PATH" && pwd -P)" \
    || die "cannot resolve --repo-path: $REPO_PATH"
  # The root directory is the one resolved path that ALREADY ends in a separator,
  # so interpolating it below yields the pattern `//*` -- which matches no
  # ordinary absolute path. Every path then reads as outside `/`, and the guard
  # went silent on the one --repo-path that contains everything. Collapse that one
  # value to the empty string so the pattern is `/*`.
  #
  # A separate variable, not an assignment back onto repo_real, because the
  # warning below logs repo_real and `repo:  ` with nothing after it would be a
  # worse message than the one this fixes. Only `/` is ever touched, so the
  # /a/b-vs-/a/bc distinction the trailing slash buys is unaffected.
  repo_prefix="$repo_real"
  [ "$repo_prefix" = "/" ] && repo_prefix=""
  # The trailing slash on the subject is what makes this a PATH-prefix test
  # rather than a string one: without it, --repo-path /a/b matches /a/bc. It also
  # makes the degenerate equal case match, since `*` matches the empty string.
  case "$skill_real/" in
    "$repo_prefix"/*)
      log "WARNING: --skill-dir is inside --repo-path: the run's work product would be the instructions grading it"
      log "  skill: $skill_real"
      log "  repo:  $repo_real"
      [ "$ALLOW_NESTED" -eq 1 ] || \
        die "--skill-dir is inside --repo-path (pass --allow-nested-skill-dir to proceed)"
      ;;
  esac
fi

for c in gh jq git; do
  command -v "$c" >/dev/null || die "required command not found: $c"
done

# The gate parser is Python (see GATE_PY below for why). Plain `python3`, not
# `uv` -- gate.py imports only the standard library so this script stays
# portable to a GHA runner, as the header claims. `uv` is a test-time tool only.
PYTHON_BIN="${PYTHON_BIN:-python3}"
command -v "$PYTHON_BIN" >/dev/null || die "required command not found: $PYTHON_BIN"

# Every path must be absolute before we go any further. The invoke stage runs in
# a subshell that cd's to --repo-path, so a relative path resolved at startup
# silently points somewhere else by the time it is used -- which is exactly how
# the first real run died ("prompt.txt: No such file or directory"). Does not
# require the path to exist, so it works for --state-dir before mkdir.
abspath() {
  case "$1" in
    /*) printf '%s\n' "$1" ;;
    *)  printf '%s\n' "$PWD/${1#./}" ;;
  esac
}
STATE_DIR="$(abspath "$STATE_DIR")"
[ -n "$SKILL_DIR" ] && SKILL_DIR="$(abspath "$SKILL_DIR")"
[ -n "$REPO_PATH" ] && REPO_PATH="$(abspath "$REPO_PATH")"

# The hosted run may READ the skill but must never WRITE it. --add-dir grants
# access to the skill directory, which would otherwise let the run edit the very
# instructions grading it -- the implementer authoring its own oracle, which is
# the one thing this whole system exists to prevent.
#
# Absolute paths in permission rules take a `//` prefix, so a leading slash is
# added to the already-absolute SKILL_DIR. Measured: `Edit(/tmp/x/**)` does NOT
# block, `Edit(//tmp/x/**)` does, and the file was verified unchanged on disk.
if [ -n "$SKILL_DIR" ]; then
  DENIED_TOOLS="$DENIED_TOOLS,Edit(/$SKILL_DIR/**),Write(/$SKILL_DIR/**),NotebookEdit(/$SKILL_DIR/**)"
fi

TIMEOUT_CMD=""
if command -v timeout >/dev/null; then TIMEOUT_CMD="timeout"
elif command -v gtimeout >/dev/null; then TIMEOUT_CMD="gtimeout"
fi

mkdir -p "$STATE_DIR/runs"
RUNS_LOG="$STATE_DIR/runs.jsonl"
PARKED_LOG="$STATE_DIR/parked.jsonl"
touch "$RUNS_LOG" "$PARKED_LOG"

# --- stage: select ---------------------------------------------------------
#
# Eligible = open AND carries the marker AND anchored tier is auto-ok AND no
# open PR references it AND not parked.
#
# Emits one line per excluded candidate with its reason. A queue read that
# yields zero must say why, or "no eligible work" and "my query is broken"
# print identically.

# Reads the issues JSON on stdin -- the same payload select_issues already fetched,
# so the park list costs no extra API call and cannot disagree with the queue it
# filters.
#
# The name is load-bearing: the frozen check in driver/test-park-state.sh extracts
# THIS function by name with sed and runs it, so a rename fails the check closed
# rather than leaving it grading a copy. Do not mirror this logic in a test file.
parked_numbers() { # issues json on stdin -> one parked issue number per line
  jq -r --arg label "$PARK_LABEL" \
     '.[]? | select((.labels // []) | any(.name == $label)) | .number' 2>/dev/null | sort -u
}

# The label carries no reason, so the reason comes from the run history -- which is
# what runs.jsonl was always for, and the one part of the old design worth keeping:
# the ledger is history, the label is current state, and conflating those two is the
# bug this replaced.
#
# Best effort by design. On a fresh host the label is present and the history is
# not, and saying so beats printing an empty reason -- a blank reason is how "parked
# for a good reason" and "parked by a bug" come to look identical.
# --- park state: the writes ------------------------------------------------
#
# The label is the state. parked.jsonl is still appended, as HISTORY: every line it
# holds was true when it was written -- "at time T, issue N was parked with this
# reason" -- and the bug was never the file, it was reading that history as current
# state. Nothing reads it for selection now, and park_reason() reads runs.jsonl.
#
# One routine for both call sites. The parking case list used to be duplicated, at
# the normal path and again in --classify-only recovery, and the recovery copy is
# exactly how #656 acquired the stale record that made this issue. A fix that
# touched one site would have reproduced the bug it closed.

park_label_add() { # $1 = issue number
  # The label has to exist before it can be applied, and `gh label create` exits 1
  # when it already does (verified, not assumed) -- hence the discard. Never fatal:
  # losing a recorded outcome over a label write would be the worse failure. Never
  # silent either, because a failed add leaves the issue selectable, which is the
  # exact wrong-in-the-optimistic-direction this issue is about.
  gh label create "$PARK_LABEL" --repo "$REPO" --color FBCA04 \
     --description "the agent-session driver parked this issue" >/dev/null 2>&1 || true
  gh issue edit "$1" --repo "$REPO" --add-label "$PARK_LABEL" >/dev/null 2>&1 \
    || say "  WARNING: could not add the $PARK_LABEL label to #$1 -- it stays selectable"
}

park_label_remove() { # $1 = issue number
  # Unconditional: `--remove-label` on an issue that lacks the label exits 0 with no
  # error (verified), so reading the labels first would spend an API call to prevent
  # nothing.
  gh issue edit "$1" --repo "$REPO" --remove-label "$PARK_LABEL" >/dev/null 2>&1 \
    || say "  WARNING: could not remove the $PARK_LABEL label from #$1 -- it stays parked"
}

apply_park_state() { # $1 = issue, $2 = outcome, $3 = ts, $4 = reason
  case "$2" in
    parked|failed|incomplete|no-gate)
      # `repo` is recorded because this file is kept for auditing and one state dir
      # serves several repos -- runs.jsonl already mixes two. Its absence in the old
      # records is a defect this PR's own rationale cites against the file, so
      # continuing to omit it while quoting it would be incoherent. Nothing reads
      # this for selection either way.
      jq -n -c --arg issue "$1" --arg repo "$REPO" --arg ts "$3" \
               --arg outcome "$2" --arg reason "$4" \
        '{issue:($issue|tonumber), repo:$repo, parked_at:$ts, outcome:$outcome, reason:$reason}' \
        >> "$PARKED_LOG"
      park_label_add "$1"
      say "  parked -- excluded from future selection unless --retry $1"
      ;;
    gate-eligible|gate-human)
      # A verdict means the run got somewhere, so an earlier park no longer holds.
      # These are exactly the outcomes the driver already declines to park.
      park_label_remove "$1"
      ;;
  esac
  # budget-exhausted, driver-fault and ci-stale deliberately match neither arm.
  # Parking a budget problem hides a recoverable config fault behind a skip reason
  # on a perfectly good issue; un-parking on one would claim progress that did not
  # happen. Keeping budget-exhausted out of the first list is guard G3.
}

park_reason() { # $1 = issue number -> the latest recorded reason for it
  local r=""
  if [ -s "$RUNS_LOG" ]; then
    r="$(jq -r --arg n "$1" --arg repo "$REPO" \
         'select(.issue == ($n|tonumber) and .repo == $repo) | .reason // empty' \
         "$RUNS_LOG" 2>/dev/null | tail -1)"
  fi
  if [ -n "$r" ]; then
    printf '%s\n' "$r"
  else
    printf '%s\n' "carries the $PARK_LABEL label; no local run record on this host"
  fi
}


# Open PRs, once. An express PR carries "Closes #N"; a branch may also carry the
# number. Match on both rather than assuming which.
fetch_open_prs() {
  gh pr list --repo "$REPO" --state open --limit 200 \
     --json number,title,body,headRefName,url 2>/dev/null || echo '[]'
}

pr_for_issue() { # $1 = issue number, $2 = open-prs json
  printf '%s' "$2" | jq -r --arg n "$1" '
    .[] | select(
        ((.body  // "") | test("(^|[^0-9])#" + $n + "([^0-9]|$)"))
     or ((.title // "") | test("(^|[^0-9])#" + $n + "([^0-9]|$)"))
     or ((.headRefName // "") | test("(^|[^0-9])" + $n + "([^0-9]|$)"))
    ) | "\(.number)\t\(.url)"' | head -1
}

board_status() { # $1 = issue number; echoes column name or empty
  [ -n "$BOARD" ] || return 0
  printf '%s' "$BOARD_JSON" | jq -r --arg n "$1" \
    '.items[]? | select(.content.number == ($n|tonumber)) | .status // "no-status"' | head -1
}

BOARD_JSON='{"items":[]}'
load_board() {
  [ -n "$BOARD" ] || return 0
  local owner num
  owner="${BOARD%%/*}"; num="${BOARD##*/}"
  # --limit is load-bearing: gh project item-list silently truncates at 30, and
  # a truncated board is not an error -- it just describes a smaller board.
  BOARD_JSON="$(gh project item-list "$num" --owner "$owner" --format json --limit 500 2>/dev/null \
                || echo '{"items":[]}')"
  local n; n="$(printf '%s' "$BOARD_JSON" | jq '.items | length')"
  say "board $BOARD: read $n items (advisory only; does not gate)"
}

ELIGIBLE=""

select_issues() {
  say "== select =="
  local issues_json total
  # `labels` is what carries the park state -- see PARK_LABEL. Requesting it here
  # rather than in a second query is why the park list costs no extra API call.
  issues_json="$(gh issue list --repo "$REPO" --state open --limit 500 \
                   --json number,title,body,labels 2>/dev/null || echo '[]')"
  total="$(printf '%s' "$issues_json" | jq 'length')"

  # tier-batch moved AHEAD of the count line, which used to print first. The count
  # line is where the marker-less issues get accounted for, and the complement
  # cannot be taken before the candidate list exists. It reads only issues_json,
  # so nothing below it was depended on.
  local candidates
  candidates="$(printf '%s' "$issues_json" | "$PYTHON_BIN" "$GATE_PY" tier-batch --marker "$MARKER")"

  # The marker-less set is the COMPLEMENT of what tier-batch emitted -- never a
  # second jq implementation of the marker test. A hand-copied predicate is the
  # drift this suite was already burned by once (test-driver.sh:19-25 used to
  # replicate extract_gate); the complement replicates nothing, so it cannot
  # disagree with the filter it is reporting on.
  local specced_nums markerless_nums markerless_list n_markerless m
  specced_nums="$(printf '%s' "$candidates" | cut -f1 | tr '\n' ' ')"
  # `. as $n` before the select is load-bearing, not a style choice: in
  # `index(f)`, f is evaluated against index's OWN input, so the tempting
  # `index(.)` searches the keep-list for itself, matches every time, and
  # silently yields an empty complement -- i.e. it reports "nothing missing"
  # no matter what. Binding the number first is what makes the test a test.
  markerless_nums="$(printf '%s' "$issues_json" | jq -r --arg keep "$specced_nums" '
      ($keep | split(" ") | map(select(length > 0))) as $k
      | .[] | .number | tostring | . as $n
      | select(($k | index($n)) == null)')"

  # No cap and no "+N more". A truncated list would reintroduce exactly the
  # failure this reporting exists to fix -- a null rendering as a positive -- one
  # level up. If the list is long enough to be unwieldy, that IS the message.
  n_markerless=0
  markerless_list=""
  for m in $markerless_nums; do
    n_markerless=$(( n_markerless + 1 ))
    markerless_list="${markerless_list:+$markerless_list, }#$m"
  done

  if [ "$n_markerless" -gt 0 ]; then
    say "repo $REPO: read $total open issues ($(( total - n_markerless )) carry the marker;" \
        "$n_markerless do not: $markerless_list -- run triage)"
  else
    say "repo $REPO: read $total open issues"
  fi
  [ "$total" -eq 500 ] && say "WARNING: hit the 500 limit; the queue read may be truncated"

  load_board
  local prs parked
  prs="$(fetch_open_prs)"
  parked="$(printf '%s' "$issues_json" | parked_numbers || true)"

  if [ -z "$candidates" ]; then
    say "no issues carry the marker -- nothing for this driver to consider."
    say "  (marker-carrying issues are produced by \`agent-session intake\` / \`triage\`)"
    return 0
  fi

  local n tier title col prline reason
  while IFS="$(printf '\t')" read -r n tier title; do
    [ -n "$n" ] || continue
    col="$(board_status "$n")"
    prline="$(pr_for_issue "$n" "$prs")"
    reason=""

    if   [ "$tier" = "needs-review" ]; then reason="tier: needs-review"
    elif [ "$tier" = "conflict" ];     then reason="tier: CONFLICT -- body names both tiers on Tier heading lines; surfacing rather than picking"
    elif [ "$tier" = "missing" ];      then reason="tier: no '## Tier:' line in body"
    elif [ "$tier" = "unparsed" ];     then reason="tier: '## Tier:' line present but names neither tier"
    elif [ -n "$prline" ];             then reason="already has an open PR: $(printf '%s' "$prline" | cut -f2)"
    elif printf '%s\n' "$parked" | grep -qx "$n" && [ "$RETRY" != "$n" ]; then
      reason="parked: $(park_reason "$n")"
    fi

    if [ -n "$reason" ]; then
      say "  SKIP    #$n  $reason"
      say "                ${title:0:70}"
    else
      say "  ELIGIBLE #$n  tier: auto-ok${col:+  |  board column: $col}"
      say "                ${title:0:70}"
      # The column is advisory. Say so where it disagrees, rather than resolving it.
      if [ -n "$col" ] && [ "$col" != "Ready" ]; then
        say "                note: board column is '$col', not 'Ready' -- not a gate, see spec.md Q2"
      fi
      ELIGIBLE="$ELIGIBLE $n"
    fi
  done <<EOF
$candidates
EOF

  ELIGIBLE="$(printf '%s' "$ELIGIBLE" | tr ' ' '\n' | grep -v '^$' || true)"
  local c; c="$(printf '%s' "$ELIGIBLE" | grep -c . || true)"
  say "eligible: ${c:-0}"
}

# --- stage: classify -------------------------------------------------------
#
# The exit code is NOT the oracle: `claude -p` exits 0 both when express
# completes and when it stops for a designed escalation. The oracle is the PR's
# gate block.

# Gate parsing and classification live in driver/gate.py, not here.
#
# They used to be bash functions, and driver/test-driver.sh hand-copied them to
# test them -- because you cannot import a function from a script that runs main
# at the bottom. The copies drifted: the test's classify_outcome was 15 lines to
# the driver's 53, with zero ci-staleness awareness, so given one identical gate
# block the driver returned `ci-stale` and the thing the suite tested returned
# `gate-eligible`. The suite graded a replica that called a stale-CI PR eligible
# for auto-merge exactly where the shipped code voided it.
#
# gate.py is importable, so its tests exercise what ships and the divergence is
# unrepresentable. It is stdlib-only on purpose -- invoked with plain `python3`,
# never `uv`, so this script stays portable to a GHA runner as the header claims.
# `uv` is only for running the tests.
#
# Rule: bash for orchestration, Python for parsing and classification.
GATE_PY="$(cd "$(dirname "$0")" && pwd)/gate.py"

GATE_JSON=""
GATE_BLOCK=""
classify_pr_body() { # $1 = PR body, $2 = head sha. Prints "outcome<TAB>reason".
  GATE_JSON="$("$PYTHON_BIN" "$GATE_PY" classify --head-sha "${2:-}" <<<"$1")"
  GATE_BLOCK="$(printf '%s' "$GATE_JSON" | jq -r '.gate')"
  # Warnings are the parser's "a null must never render as a positive" channel;
  # surface them here rather than letting them die inside the JSON.
  printf '%s' "$GATE_JSON" | jq -r '.warnings[]?' | while IFS= read -r w; do
    say "  WARNING: $w"
  done
  printf '%s' "$GATE_JSON" | jq -r '[.outcome, .reason] | @tsv'
}

# A stream can carry MORE THAN ONE result message: a successful one, then a
# spurious `error_during_execution` with cost 0 and turns 0 (seen on a resumed
# session). `tail -1` therefore picks the wrong record and reports $0 spent --
# observed recovering #710, whose real cost was $4.41. Cost is cumulative within
# a session, so the record with the highest total_cost_usd is the true one.
pick_result() { # $1 = stream.jsonl path
  jq -sc '[.[] | select(.type=="result")]
          | if length == 0 then empty
            else (max_by(.total_cost_usd // 0)) end' "$1" 2>/dev/null || true
}

# The same spurious trailing record ALSO poisons the exit code, and the fix above
# only covered cost. Observed on #656: `subtype=success` with the full merge-gate
# verdict, then `error_during_execution`, and `claude -p` exited 1 -- so a run that
# had opened a PR and published `eligible-for-auto-merge` was recorded `failed`,
# parked, and stopped the loop.
#
# Deciding "did the run finish?" from the exit code contradicts this file's own
# doctrine two stanzas down: THE EXIT CODE IS NOT THE ORACLE, the gate block is.
# That comment only ever described the rc=0 case; the rc!=0 branch bypassed the
# oracle entirely. So: if the stream carries a successful result at all, the run
# reached an end state and the gate gets to speak, whatever the exit code says.
has_success_result() { # $1 = stream.jsonl path
  jq -se 'any(.[]; .type=="result" and .subtype=="success" and (.is_error != true))' \
     "$1" >/dev/null 2>&1
}

# --- stage: invoke ---------------------------------------------------------

build_prompt() { # $1 = issue url
  cat <<EOF
You are running unattended, invoked by the agent-session board-driver.

Read $SKILL_DIR/SKILL.md, then read $SKILL_DIR/phases/express.md and follow it
exactly for this issue:

  $1

The skill is not installed as a registered skill. Its files live at $SKILL_DIR and
you must read them from there by absolute path.

Stop at the merge gate and report the verdict. Do not merge the PR and do not enable
auto-merge.

There is no human watching this run. If express directs you to stop and surface
something, stop and state plainly what needs a decision and why. Do not substitute
your own judgment for the decision just because nobody is here to answer: a parked
issue is a normal, expected outcome for this driver, and an unattended guess is not.
EOF
}

run_issue() { # $1 = issue number
  local n="$1" url ts rundir raw prompt rc=0
  url="https://github.com/$REPO/issues/$n"
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  rundir="$STATE_DIR/runs/$n-$ts"
  mkdir -p "$rundir"
  raw="$rundir/stream.jsonl"
  prompt="$(build_prompt "$url")"
  printf '%s\n' "$prompt" > "$rundir/prompt.txt"

  say ""
  say "== invoke #$n =="
  say "  issue    $url"
  say "  cwd      $REPO_PATH"
  say "  budget   \$$MAX_BUDGET   timeout ${RUN_TIMEOUT}s"
  say "  run dir  $rundir"

  # In-flight marker, written BEFORE the invocation and removed after the
  # outcome is recorded. If the driver itself dies mid-run -- killed, laptop
  # slept, SIGTERM -- this file is the only evidence the run happened, because
  # everything else is written after classification. Observed the hard way: a
  # killed driver left a $9.44 completed run, an open PR, and an empty runs.jsonl.
  jq -n -c --arg issue "$n" --arg ts "$ts" --arg rundir "$rundir" --arg url "$url" \
    '{issue:($issue|tonumber), started:$ts, run_dir:$rundir, url:$url}' \
    > "$STATE_DIR/inflight.json"

  # The prompt goes in on STDIN, never as a positional argument.
  # --allowedTools, --disallowedTools and --add-dir are all variadic
  # (<tools...>, <directories...>), so a trailing positional prompt is silently
  # consumed as another value for whichever variadic option came last, and the
  # run dies with "Input must be provided either through stdin or as a prompt
  # argument". Measured, not theorised.
  local -a cmd
  cmd=(claude -p
       --output-format stream-json --verbose
       --permission-mode dontAsk
       --allowedTools "$ALLOWED_TOOLS"
       --disallowedTools "$DENIED_TOOLS"
       --max-budget-usd "$MAX_BUDGET"
       --add-dir "$SKILL_DIR")
  [ -n "$MODEL" ] && cmd+=(--model "$MODEL")

  local main_before
  main_before="$(git -C "$REPO_PATH" rev-parse main 2>/dev/null || echo unknown)"

  # Run in the background and hold the pid, so the EXIT trap can kill the child.
  # Without this the child outlives its driver: a VSCode crash took the driver
  # down and `claude -p` was reparented to init (PPID 1), still spending and
  # still mutating the repo with nothing supervising it. Observed, not theorised.
  set +e
  if [ -n "$TIMEOUT_CMD" ]; then
    ( cd "$REPO_PATH" && exec "$TIMEOUT_CMD" "$RUN_TIMEOUT" "${cmd[@]}" < "$rundir/prompt.txt" ) \
      > "$raw" 2>"$rundir/stderr.txt" &
  else
    say "  NOTE: no timeout/gtimeout found; running unbounded (budget still caps cost)"
    ( cd "$REPO_PATH" && exec "${cmd[@]}" < "$rundir/prompt.txt" ) > "$raw" 2>"$rundir/stderr.txt" &
  fi
  CHILD_PID=$!
  printf '%s\n' "$CHILD_PID" > "$rundir/child.pid"
  wait "$CHILD_PID"
  rc=$?
  CHILD_PID=""
  set -e

  local main_after
  main_after="$(git -C "$REPO_PATH" rev-parse main 2>/dev/null || echo unknown)"
  if [ "$main_before" != "$main_after" ]; then
    say "  WARNING: $REPO_PATH main moved during the run: $main_before -> $main_after"
  fi

  # The result message carries the final text, cost and session id.
  local result final cost session
  result="$(pick_result "$raw")"
  final="$(printf '%s' "$result"  | jq -r '.result // ""' 2>/dev/null || true)"
  cost="$(printf '%s' "$result"   | jq -r '.total_cost_usd // 0' 2>/dev/null || echo 0)"
  session="$(printf '%s' "$result"| jq -r '.session_id // ""' 2>/dev/null || true)"
  printf '%s' "$final" > "$rundir/final.txt"

  # Denials are greppable, in three measured phrasings: the rule-specific
  # "with command <cmd> has been denied", the generic don't-ask-mode form, and the
  # path-rule form ("denied by your permission settings") that Edit/Write deny
  # rules produce. A PreToolUse hook would add a fourth -- if that lands, teach
  # this pattern its wording, or the count silently undercounts.
  local denials
  denials="$(grep -oE '(Permission to use [^"]*has been denied[^"]*|[^"]*denied by your permission settings[^"]*)' \
             "$raw" 2>/dev/null | sort -u || true)"
  if [ -n "$denials" ]; then
    printf '%s\n' "$denials" > "$rundir/denials.txt"
    say "  DENIALS ($(printf '%s\n' "$denials" | grep -c .)) -- see $rundir/denials.txt"
    printf '%s\n' "$denials" | sed 's/^/    /' >&2
  fi

  say "  exit $rc   cost \$$cost   session ${session:-none}"

  # --- classify ---
  local outcome reason prline prnum prurl gate
  if [ "$rc" -eq 124 ]; then
    outcome="failed"; reason="timed out after ${RUN_TIMEOUT}s"
  elif [ "$rc" -ne 0 ] && [ -z "$session" ] && [ "${cost:-0}" = "0" ]; then
    # No session id and no spend means the invocation never reached the model, so
    # this is the DRIVER being broken, not the run failing. Worth separating: a
    # driver fault is fixed by editing this script, an escalation is not, and the
    # first #585 attempt spent $0 dying on a bad path while looking like a normal
    # failed run. Never park it -- parking would hide the driver's own bug behind
    # a skip reason on a perfectly good issue.
    outcome="driver-fault"
    reason="claude exited $rc before starting (no session, no spend) -- see $rundir/stderr.txt"
  elif [ "$rc" -ne 0 ] && ! has_success_result "$raw"; then
    outcome="failed"; reason="claude exited $rc"
  else
    # rc != 0 with a successful result in the stream is the spurious-trailing-record
    # case. Say so out loud rather than swallowing it -- the exit code is still a real
    # signal that something went wrong after the run finished.
    if [ "$rc" -ne 0 ]; then
      say "  NOTE: claude exited $rc but the stream carries a successful result;"
      say "        classifying from the gate block, not the exit code."
    fi
    prline="$(pr_for_issue "$n" "$(fetch_open_prs)")"
    if [ -z "$prline" ]; then
      outcome="parked"
      reason="no PR opened; run's own account: $(printf '%s' "$final" | tr '\n' ' ' | cut -c1-400)"
    else
      prnum="$(printf '%s' "$prline" | cut -f1)"
      prurl="$(printf '%s' "$prline" | cut -f2)"
      _body="$(gh pr view "$prnum" --repo "$REPO" --json body -q .body 2>/dev/null || true)"
      GATE_HEAD_SHA="$(gh pr view "$prnum" --repo "$REPO" --json headRefOid -q .headRefOid 2>/dev/null || true)"
      IFS="$(printf '\t')" read -r outcome reason <<EOF
$(classify_pr_body "$_body" "$GATE_HEAD_SHA")
EOF
      printf '%s\n' "$GATE_BLOCK" > "$rundir/gate.yaml"
    fi
  fi

  # Budget exhaustion exits 0 with subtype=success and is_error=false, so it is
  # otherwise indistinguishable from a designed escalation stop -- both land as
  # `incomplete` with no gate verdict. They need opposite responses: a designed
  # stop wants a human, an exhausted budget wants more budget. Measured: #710
  # spent $11.87 of $12 and stopped mid-review-cycle reporting success.
  if [ "$outcome" = "incomplete" ] || [ "$outcome" = "parked" ] || [ "$outcome" = "no-gate" ]; then
    if awk -v c="${cost:-0}" -v b="$MAX_BUDGET" 'BEGIN{exit !(b>0 && c >= b*0.95)}'; then
      outcome="budget-exhausted"
      reason="spent \$$cost of \$$MAX_BUDGET (>=95%) and never reached the gate -- raise --max-budget-usd and re-run, this is not an escalation"
    fi
  fi

  say "  outcome  $outcome"
  say "  reason   $reason"
  [ -n "${prurl:-}" ] && say "  pr       $prurl"

  # --- record ---
  jq -n -c \
    --arg issue "$n" --arg repo "$REPO" --arg ts "$ts" \
    --arg outcome "$outcome" --arg reason "$reason" \
    --arg pr "${prurl:-}" --arg session "$session" \
    --arg rundir "$rundir" --argjson rc "$rc" --argjson cost "${cost:-0}" \
    '{issue:($issue|tonumber), repo:$repo, started:$ts, exit:$rc, cost_usd:$cost,
      session_id:$session, outcome:$outcome, reason:$reason, pr:$pr, run_dir:$rundir}' \
    >> "$RUNS_LOG"

  apply_park_state "$n" "$outcome" "$ts" "$reason"

  # The outcome is recorded, so the in-flight marker has done its job.
  rm -f "$STATE_DIR/inflight.json"

  TOTAL_COST="$(awk -v a="$TOTAL_COST" -v b="${cost:-0}" 'BEGIN{printf "%.4f", a+b}')"
  ATTEMPTED=$((ATTEMPTED + 1))
  printf '%s|%s|%s|%s\n' "$n" "$outcome" "$reason" "${prurl:-}" >> "$SUMMARY_TMP"

  # A run that produced nothing classifiable means the driver's own assumptions
  # are off. Stop rather than spend the next budget on the same misunderstanding.
  if [ "$outcome" = "failed" ] || [ "$outcome" = "driver-fault" ] || [ "$outcome" = "budget-exhausted" ]; then
    say ""
    say "stopping the loop: $outcome means an assumption is wrong, and retrying spends money on it."
    say "  (budget-exhausted is a config problem, not an escalation -- the next issue would"
    say "   get the same too-small ceiling. Observed: #710 exhausted \$12, then #656 started"
    say "   with \$12 and also never reached its gate.)"
    return 1
  fi
  return 0
}

# --- main ------------------------------------------------------------------

TOTAL_COST=0
ATTEMPTED=0
CHILD_PID=""
GATE_HEAD_SHA=""
SUMMARY_TMP="$(mktemp)"

# Take the in-flight run down with us. `timeout` forwards TERM to claude, so a
# TERM to the timeout pid is enough for the graceful cases (Ctrl-C, SIGTERM,
# normal exit). It is NOT enough for a SIGKILL of the driver or a host crash --
# no trap runs then -- which is why startup also checks for a live orphan.
cleanup() {
  if [ -n "$CHILD_PID" ] && kill -0 "$CHILD_PID" 2>/dev/null; then
    say "cleanup: terminating in-flight run (pid $CHILD_PID)"
    kill -TERM "$CHILD_PID" 2>/dev/null || true
  fi
  rm -f "$SUMMARY_TMP"
}
trap cleanup EXIT INT TERM

# A leftover in-flight marker means a previous driver died between invoking and
# recording. Say so loudly: the run may have completed and cost real money, and
# nothing about runs.jsonl would reveal it.
if [ -f "$STATE_DIR/inflight.json" ]; then
  say "WARNING: a previous run died before recording its outcome:"
  jq -r '"  issue #\(.issue)  started \(.started)  run dir \(.run_dir)"' "$STATE_DIR/inflight.json" 2>/dev/null || true
  # The trap cannot fire on SIGKILL or a host crash, so the child may STILL BE
  # RUNNING -- reparented to init, unsupervised, and spending. Distinguish that
  # from a finished-but-unrecorded run: they need opposite actions.
  _ipid="$(cat "$(jq -r '.run_dir' "$STATE_DIR/inflight.json" 2>/dev/null)/child.pid" 2>/dev/null || true)"
  if [ -n "$_ipid" ] && kill -0 "$_ipid" 2>/dev/null; then
    say "  ORPHAN STILL RUNNING (pid $_ipid, reparented) -- it is unsupervised and still spending."
    say "  Let it finish, then:  --classify-only $(jq -r '.issue' "$STATE_DIR/inflight.json" 2>/dev/null)"
    say "  Or kill it:           kill -TERM $_ipid"
    die "refusing to start a second run while an orphan is live"
  fi
  say "  recover it with:  --classify-only $(jq -r '.issue' "$STATE_DIR/inflight.json" 2>/dev/null)"
  say ""
fi

# --classify-only: recover an outcome from live state, no invocation. The run dir
# (if one is findable) supplies cost and session id; the PR supplies the verdict.
if [ -n "$CLASSIFY_ONLY" ]; then
  n="$CLASSIFY_ONLY"
  say "== classify-only #$n =="
  rundir="$(ls -td "$STATE_DIR/runs/$n-"* 2>/dev/null | head -1 || true)"
  cost=0; session=""; rc=0; ts="$(date -u +%Y%m%dT%H%M%SZ)"
  if [ -n "$rundir" ] && [ -f "$rundir/stream.jsonl" ]; then
    say "  run dir  $rundir"
    result="$(pick_result "$rundir/stream.jsonl")"
    cost="$(printf '%s' "$result"    | jq -r '.total_cost_usd // 0' 2>/dev/null || echo 0)"
    session="$(printf '%s' "$result" | jq -r '.session_id // ""' 2>/dev/null || true)"
    ts="$(basename "$rundir" | sed "s/^$n-//")"
    say "  recovered from stream: cost \$$cost  session ${session:-none}"
  else
    say "  no run dir found for #$n; classifying from the PR alone"
    rundir="(none)"
  fi

  prline="$(pr_for_issue "$n" "$(fetch_open_prs)")"
  if [ -z "$prline" ]; then
    outcome="parked"; reason="no open PR found for #$n"
    prurl=""
  else
    prnum="$(printf '%s' "$prline" | cut -f1)"
    prurl="$(printf '%s' "$prline" | cut -f2)"
    _body="$(gh pr view "$prnum" --repo "$REPO" --json body -q .body 2>/dev/null || true)"
    GATE_HEAD_SHA="$(gh pr view "$prnum" --repo "$REPO" --json headRefOid -q .headRefOid 2>/dev/null || true)"
    IFS="$(printf '\t')" read -r outcome reason <<EOF
$(classify_pr_body "$_body" "$GATE_HEAD_SHA")
EOF
    [ "$rundir" != "(none)" ] && printf '%s\n' "$GATE_BLOCK" > "$rundir/gate.yaml"
  fi

  say "  outcome  $outcome"
  say "  reason   $reason"
  [ -n "$prurl" ] && say "  pr       $prurl"

  jq -n -c \
    --arg issue "$n" --arg repo "$REPO" --arg ts "$ts" \
    --arg outcome "$outcome" --arg reason "$reason" \
    --arg pr "$prurl" --arg session "$session" \
    --arg rundir "$rundir" --argjson rc "$rc" --argjson cost "${cost:-0}" \
    '{issue:($issue|tonumber), repo:$repo, started:$ts, exit:$rc, cost_usd:$cost,
      session_id:$session, outcome:$outcome, reason:$reason, pr:$pr, run_dir:$rundir,
      recovered:true}' \
    >> "$RUNS_LOG"

  apply_park_state "$n" "$outcome" "$ts" "$reason"

  rm -f "$STATE_DIR/inflight.json"
  say ""
  say "recorded to $RUNS_LOG. Nothing was merged."
  exit 0
fi

if [ -n "$ISSUE" ]; then
  say "== select (single issue: #$ISSUE) =="
  ELIGIBLE="$ISSUE"
  say "  eligibility check bypassed by --issue"
else
  select_issues
fi

if [ "$DRY_RUN" -eq 1 ]; then
  say ""
  say "dry run -- no claude invocation."
  exit 0
fi

if [ -z "$ELIGIBLE" ]; then
  say ""
  say "== report =="
  say "nothing eligible; no runs attempted. Reasons are listed above."
  exit 0
fi

for n in $ELIGIBLE; do
  if [ "$ATTEMPTED" -ge "$MAX_ISSUES" ]; then
    say ""
    say "reached --max-issues $MAX_ISSUES; stopping with issues still eligible."
    break
  fi
  run_issue "$n" || break
done

say ""
say "== report =="
say "attempted $ATTEMPTED issue(s), total cost \$$TOTAL_COST"
while IFS='|' read -r n outcome reason prurl; do
  [ -n "$n" ] || continue
  say "  #$n  $outcome"
  say "        $reason"
  [ -n "$prurl" ] && say "        $prurl"
done < "$SUMMARY_TMP"
say ""
say "Nothing was merged. eligible-for-auto-merge is a finding, not an action --"
say "acting on it is a separate decision (phase 3 of docs/design.md's rollout)."
say "State: $STATE_DIR"
