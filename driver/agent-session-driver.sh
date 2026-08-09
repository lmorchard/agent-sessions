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
# Deliberately host-agnostic: every path a flag, no interactive prompts, all
# mutable state under one --state-dir. The GitHub Actions host is meant to run
# this file unchanged.
#
# The one host assumption, added deliberately for issue #27: with no --state-dir,
# the default is an XDG path, which consults $XDG_STATE_HOME and then $HOME. It
# used to be `./.driver-state` -- no $HOME, but also no repo component, so every
# repo on a host shared one state directory and one inflight.json. See the
# defaults block below. --state-dir remains an explicit override, so the flag is
# still the way to run with no $HOME at all.

set -euo pipefail

# Load environment variables from .env if present.
# This keeps secrets like GITHUB_TOKEN out of shell history and process lists.
if [[ -f ".env" ]]; then
  set -a
  source .env
  set +a
fi

# Park state lives on the ISSUE, as a label, and this is the whole name of it.
#
# It used to live in ./.driver-state/parked.jsonl, which was wrong twice over: the
# file is append-only with no un-park record, so every entry it ever produced went
# stale the moment a later run succeeded (all three effective entries were), and it
# is a gitignored path relative to cwd, so a host change silently un-parked
# everything. A label is durable, scoped to the target repo -- parked.jsonl records
# no repo at all -- and visible on the issue, where a human decides whether to
# --retry. See issue #5, decision D2.
PARK_LABEL='agent-session:needs-human'
INTERACTIVE_LABEL='agent-session:needs-human-interactive'
MERGE_READY_LABEL='agent-session:merge-ready'

# --- defaults --------------------------------------------------------------

REPO=""
SKILL_DIR=""
REPO_PATH=""
ISSUE=""
MAX_ISSUES=1
MAX_PHASE_ATTEMPTS=3
MAX_BUDGET=10
RUN_TIMEOUT=5400
# Empty means "not given", and the default is computed from --repo further down --
# it cannot be a literal here, because it depends on an argument not yet parsed.
#
# It used to be `./.driver-state`: one fixed relative path, no repo component. So
# every repository the driver was pointed at on a host shared one state directory,
# and therefore one inflight.json and one runs/ namespace. Two consequences, both
# hit for real rather than theorised (issue #27):
#
#   - a live run against decafclaw #657 refused a run against agent-sessions one
#     minute later, announcing the unrelated child as an unsupervised orphan;
#   - `--classify-only <n>` resolves runs/<issue>-<ts>/ by issue number and mtime,
#     so with two repos in one directory it can recover the wrong repo's run and
#     record its cost and session id against the other repo's issue. Every issue
#     number this repo uses collides with one of decafclaw's.
#
# The fix is the LAYOUT, not a comparison: one directory per repo means the orphan
# guard is per-repo because the marker it reads is, and --classify-only is
# unambiguous because each repo has its own runs/. No code anywhere compares two
# repos. If a change to this file finds itself doing that, this default regressed.
STATE_DIR=""
BOARD=""
DRY_RUN=0
ALLOW_NESTED=0
RETRY=""
CLASSIFY_ONLY=""
RESUMED_FROM=""
MODEL=""
HIGH_TIER_MODEL=""
LOW_TIER_MODEL=""
BACKEND=""

# `dontAsk` denies non-allowlisted mutating commands but auto-allows commands it
# classifies read-only -- measured, see spec.md "Permissions". The allowlist is
# wide because `express` legitimately builds, writes code, dispatches subagents
# and opens a PR. What it buys is a floor, not a sandbox.
ALLOWED_TOOLS='Read,Write,Edit,Glob,Grep,Task,TodoWrite,BashOutput,KillShell,NotebookEdit,Bash(*)'

# Deny rules take precedence over allow rules and match multi-word command
# prefixes -- measured. This is the mechanism behind "nothing merges"; the
# prompt says it once, and once is enough because the mechanism is here.
# Not airtight (prefix-matched, so `gh api` remains reachable). The airtight
# version is a PreToolUse hook, required before any UNWATCHED host.
DENIED_TOOLS='Bash(gh pr merge:*),Bash(gh pr merge *),Bash(git push --force:*),Bash(gh repo delete:*)'

# --- plumbing --------------------------------------------------------------

get_attempts() {
  local issue="$1"
  local phase="$2"
  local attempts_file="$STATE_DIR/attempts.tsv"
  if [ -f "$attempts_file" ]; then
    local c=$(awk -F '\t' -v key="$issue:$phase" '$1 == key {print $2; exit}' "$attempts_file")
    echo "${c:-0}"
  else
    echo "0"
  fi
}

increment_attempts() {
  local issue="$1"
  local phase="$2"
  local attempts_file="$STATE_DIR/attempts.tsv"
  local count=$(get_attempts "$issue" "$phase")
  count=$((count + 1))
  if [ -f "$attempts_file" ]; then
    awk -F '\t' -v key="$issue:$phase" -v count="$count" '
      BEGIN { found=0 }
      $1 == key { print $1 "\t" count; found=1; next }
      { print $0 }
      END { if (!found) print key "\t" count }
    ' "$attempts_file" > "$attempts_file.tmp"
    mv "$attempts_file.tmp" "$attempts_file"
  else
    printf '%s\t%s\n' "$issue:$phase" "$count" > "$attempts_file"
  fi
}

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
  --state-dir <path>      run history + per-run transcripts. Used exactly as given.
                          Default, when omitted, is ONE DIRECTORY PER REPO:
                            ${XDG_STATE_HOME:-$HOME/.local/state}/agent-session/<owner>-<name>/
                          so concurrent runs against different repos do not
                          collide. The resolved path is logged at startup.
                          Park state is NOT here: it is a label on the issue.
   --board <owner/number>  optional; advisory board-control reporting
   --backend <name>        agent backend: claude or opencode (default: claude)
   --model <name>          optional; passed to agent backend
  --dry-run               selection only; no agent invocation
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
   --resumed-from <path>   optional with --classify-only; path to resumed session result.json
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
    --backend)        BACKEND="${2:?}"; shift 2 ;;
    --model)          MODEL="${2:?}"; shift 2 ;;
    --high-tier-model) HIGH_TIER_MODEL="${2:?}"; shift 2 ;;
    --low-tier-model) LOW_TIER_MODEL="${2:?}"; shift 2 ;;
    --retry)          RETRY="${2:?}"; shift 2 ;;
    --classify-only)  CLASSIFY_ONLY="${2:?}"; shift 2 ;;
    --resumed-from)   RESUMED_FROM="${2:?}"; shift 2 ;;
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

  # An unattended run READS $SKILL_DIR and is graded by what it reads there. If that
  # directory has uncommitted edits to tracked files, the run is graded by text that
  # is in no commit: nothing in the PR, the ledger row or the gate block records what
  # it actually read, and the same invocation an hour later is a different run. This
  # happened -- the run on issue #23 found phases/express.md, phases/pr.md and
  # references/frozen-checks.md modified-but-uncommitted, where committed pr.md said
  # "Squash and open" and the working tree said "Push and open". That decides whether
  # the freeze commit survives to the gate, so it was not cosmetic. The run stopped
  # voluntarily and nothing in the system helped it. See issue #36.
  #
  # Refuse rather than warn: a warning in an unattended run is read by nobody until
  # after the money is spent, and unreviewed instructions produce output that looks
  # entirely normal. No escape-hatch flag either -- it would be reached for by reflex,
  # which is the trap --allow-nested-skill-dir's false-positive guards exist to
  # prevent. One can be added if it is ever actually wanted.
  #
  # AFTER the containment check on purpose: the nest cases in test-driver.sh that die
  # at containment point --skill-dir at this repo's own skill dir, so testing
  # cleanliness first would make their stop-point depend on the developer's working
  # tree -- the host-dependence the constructed PATH there exists to remove.
  #
  # Scoped to tracked files UNDER the skill dir, via the `-- .` pathspec:
  #   - not the whole repo, because this driver is routinely pointed at a checkout
  #     with unrelated work in flight (docs/, .driver-state/), and a check that
  #     refuses almost every real invocation gets disabled within a day;
  #   - --untracked-files=no, because a stray scratch file changes nothing about what
  #     the run is told to do, while a modified tracked file does. Narrower is better
  #     here; widen only with evidence.
  # Staged counts as dirty -- `git status` reports the index too, which is why this is
  # not `git diff`. Staged is still not committed and still not reviewed.
  #
  # $skill_real, not $SKILL_DIR: abspath() has not run yet (it is below), so
  # SKILL_DIR can still be relative, while skill_real was resolved with `pwd -P`
  # just above.
  #
  # The `if` is what keeps a null from rendering as a positive. `git status` prints
  # nothing on stdout in TWO different situations: a clean tree, and a SKILL_DIR in no
  # repository at all -- where it exits nonzero and writes "fatal: not a git
  # repository" to stderr. Treating that stderr as content would refuse every
  # unpacked-tarball skill dir, so only exit 0 counts as git having answered, and a
  # git that answered nothing means clean. `git` itself may still be missing here --
  # the required-command loop is below, not above -- and that case correctly lands as
  # "could not determine", proceeding to the loop that reports it properly.
  #
  # RESIDUAL RISK, stated rather than gated away: "git answered nothing" collapses
  # not-in-a-repo together with every OTHER nonzero exit -- an unreadable .git/index,
  # a corrupt repo, dubious-ownership. In those states a genuinely dirty skill dir
  # proceeds. That is the behaviour issue #36 asks for in as many words (G3: "a `git
  # status` that errors must not be read as 'dirty'"), and the alternative is worse
  # in the common case: distinguishing them means deciding what "in a repo" means
  # without being able to ask git, and getting it wrong refuses every legitimate
  # non-checkout skill dir. Found by the verifier's adversarial probe on this change,
  # by chmod 000 on .git/index; recorded here rather than fixed because narrowing it
  # is a decision about the criteria, not an implementation detail.
  skill_dirty=""
  if skill_status="$(CDPATH= cd -- "$skill_real" \
        && git status --porcelain --untracked-files=no -- . 2>/dev/null)"; then
    skill_dirty="$skill_status"
  fi
  if [ -n "$skill_dirty" ]; then
    log "ERROR: --skill-dir has uncommitted changes to tracked files: $skill_real"
    # Every modified path, not just the first: an operator told only "dirty" has to go
    # hunt for what changed. Paths are printed relative to the repository root, which
    # is what --porcelain guarantees; the line above supplies the absolute anchor.
    printf '%s\n' "$skill_dirty" | while IFS= read -r skill_dirty_line; do
      log "  $skill_dirty_line"
    done
    die "--skill-dir is not clean: an unattended run would be graded by instructions that are in no commit"
  fi
fi

for c in gh jq git; do
  command -v "$c" >/dev/null || die "required command not found: $c"
done

# The gate parser is Python (see GATE_PY below for why). Plain `python3`, not
# `uv` -- gate.py imports only the standard library so this script stays
# portable to a GHA runner, as the header claims. `uv` is a test-time tool only.
PYTHON_BIN="${PYTHON_BIN:-python3}"
command -v "$PYTHON_BIN" >/dev/null || die "required command not found: $PYTHON_BIN"
GH_QUERY_PY="$(cd "$(dirname "$0")" && pwd)/gh_query.py"
HOOK_SCRIPT="$(cd "$(dirname "$0")" && pwd)/merge-block-hook.sh"
HOOK_SETTINGS_TEMPLATE="$(cd "$(dirname "$0")" && pwd)/settings.json"

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
# The per-repo default, resolved HERE and not at the defaults block, because it
# depends on --repo. Three placement constraints, none of them stylistic:
#
#   1. AFTER the `for c in gh jq git` loop above. The nest section of
#      driver/test-driver.sh asserts that the FIRST LINE OF STDERR from a run with
#      a bad --skill-dir is that run's own error message. Anything logged earlier
#      becomes the first line and flips it, and that file is frozen for this
#      change.
#   2. BEFORE the mkdir below, obviously, but the mkdir also must not move up:
#      several cases assert that a run which dies in validation creates no state
#      directory at all.
#   3. The report goes through `log` (stderr), never `say` (stdout). Several cases
#      capture stdout ONLY and match a bare four-digit issue number anywhere in
#      it; a temp state-dir path is full of digits, so a stdout line there widens a
#      spurious-pass window in assertions this change may not edit. `log` is also
#      what this file already uses for diagnostics -- `say` is the report.
#
# `--repo` is validated non-empty far above, but non-empty is not enough now that
# REPO lands in a filesystem path. ${REPO//\//-} flattens owner/name to
# owner-name: one level deep, and GitHub's naming rules admit no other slash, so
# it cannot collide.
#
# Shape-validated because "it flattens slashes" is incidental protection, not a
# check. Measured on the unvalidated version: `--repo ../../../../tmp/ESCAPED`
# stayed inside the root (the slashes became dashes), but `--repo ..` produced the
# slug `..`, and abspath then resolved the state dir to the PARENT of
# agent-session/ -- runs.jsonl, parked.jsonl and runs/ were created one level
# outside the intended root. One level, not arbitrary traversal, and only reachable
# by typing a repo name that no `gh` call could satisfy -- but the fix is three
# lines and the alternative is relying on a substitution that was never meant to be
# a boundary. Raised by the Copilot review on PR #44.
case "$REPO" in
  */*/*) die "--repo must be owner/name, with exactly one '/': $REPO" ;;
  */*)   : ;;
  *)     die "--repo must be owner/name, with exactly one '/': $REPO" ;;
esac
case "$REPO" in
  .|..|*/.|*/..|./*|../*) die "--repo may not contain a path component of . or ..: $REPO" ;;
esac
if [ -z "$STATE_DIR" ]; then
  # Checked rather than left to fail: with both unset the path would begin
  # `/.local/state`, and the only symptom would be an obscure `mkdir` failure
  # aborting under `set -e` with no indication that a missing HOME caused it.
  if [ -z "${XDG_STATE_HOME:-}" ] && [ -z "${HOME:-}" ]; then
    die "no --state-dir given and neither XDG_STATE_HOME nor HOME is set; pass --state-dir"
  fi
  STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/agent-session/${REPO//\//-}"
fi
STATE_DIR="$(abspath "$STATE_DIR")"
[ -n "$SKILL_DIR" ] && SKILL_DIR="$(abspath "$SKILL_DIR")"
[ -n "$REPO_PATH" ] && REPO_PATH="$(abspath "$REPO_PATH")"

# Said out loud because it is no longer self-evident. `./.driver-state` was
# visible in the checkout you ran from; an XDG path is not, and an operator who
# cannot tell which directory a run read cannot tell a fresh host from a wrong
# --state-dir. One line, and the driver already logs comparable detail per run.
log "state dir  $STATE_DIR"

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
HOOK_SETTINGS_FILE="$STATE_DIR/settings.json"
jq --arg script "$HOOK_SCRIPT" '.hooks.PreToolUse[0].command = $script' "$HOOK_SETTINGS_TEMPLATE" > "$HOOK_SETTINGS_FILE"

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
  jq -r --arg label "$PARK_LABEL" --arg interactive "$INTERACTIVE_LABEL" \
     '.[]? | select((.labels // []) | any(.name == $label or .name == $interactive)) | .number' 2>/dev/null | sort -u
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


notify_human() { # $1 = issue, $2 = reason
  local issue="$1"
  local reason="$2"
  local ts="$(date -u +%Y%m%dT%H%M%SZ)"
  
  if [ -d "$STATE_DIR" ]; then
    echo "[$ts] Issue #$issue escalated: $reason" >> "$STATE_DIR/inbox.md"
  fi
  
  if [ -n "${NTFY_TOPIC:-}" ]; then
    curl -s -d "Agent Session: Issue #$issue escalated: $reason" "ntfy.sh/${NTFY_TOPIC:-}" >/dev/null || true
  fi
  
  if [ -n "${EMAIL_ALERTS:-}" ]; then
    echo "Agent Session: Issue #$issue escalated: $reason" | mail -s "Agent Escalation: #$issue" "${EMAIL_ALERTS:-}" || true
  fi
}

apply_park_state() { # $1 = issue, $2 = outcome, $3 = ts, $4 = reason
  case "$2" in
    parked|failed|no-gate)
      jq -n -c --arg issue "$1" --arg repo "$REPO" --arg ts "$3" \
               --arg outcome "$2" --arg reason "$4" \
        '{issue:($issue|tonumber), repo:$repo, parked_at:$ts, outcome:$outcome, reason:$reason}' \
        >> "$PARKED_LOG"
      park_label_add "$1"
      say "  parked -- excluded from future selection unless --retry $1"
      notify_human "$1" "$2: $4"
      ;;
    incomplete)
      jq -n -c --arg issue "$1" --arg repo "$REPO" --arg ts "$3" \
               --arg outcome "$2" --arg reason "$4" \
        '{issue:($issue|tonumber), repo:$repo, parked_at:$ts, outcome:$outcome, reason:$reason}' \
        >> "$PARKED_LOG"
      say "  incomplete -- leaving unparked so the loop can re-evaluate later"
      park_label_remove "$1"
      ;;
    gate-eligible)
      # A verdict means the run got somewhere, so an earlier park no longer holds.
      park_label_remove "$1"
      # Apply merge-ready label to prevent infinite grade_gate loops
      gh label create "$MERGE_READY_LABEL" --repo "$REPO" --color 2E8A16 --description "Issue is eligible for auto-merge, waiting for human or auto-merge script" >/dev/null 2>&1 || true
      gh issue edit "$1" --repo "$REPO" --add-label "$MERGE_READY_LABEL" >/dev/null 2>&1 || true
      notify_human "$1" "gate-eligible: $4"
      ;;
    gate-human)
      park_label_remove "$1"
      notify_human "$1" "gate-human: $4"
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


# Open PRs, once. `closingIssuesReferences` is what GitHub itself considers a
# link -- the issues a merge would actually close -- and it rides along on the
# list query for free. No second call, no `gh pr view`.
#
# NO `2>/dev/null || echo '[]'`, which is how this ended until #39. That turned
# every failure -- auth, network, rate limit, a `gh` too old to know
# `closingIssuesReferences` -- into a byte-identical "there are no open PRs",
# with gh's explanation thrown away. A null rendering as a positive: findings.md
# class 2, and the callers below read that null as "nothing blocks".
#
# So this function no longer decides anything. It propagates gh's stderr and gh's
# exit status, and the two kinds of caller take OPPOSITE trades on them, because
# their costs are asymmetric in opposite directions:
#
#   select_issues  REFUSES.  The failure precedes all spend, and selection's
#                  whole job is deciding which issues lack a PR. Without the
#                  list that decision is a guess wearing an answer's clothes,
#                  and guessing wrong costs a duplicate $5-20 run.
#   discovery      DEGRADES, distinguishably. The money is already spent and a
#                  PR may already be open, so refusing would destroy the only
#                  record of it. It records that it could not ask, instead of
#                  recording "no PR opened" about a PR it never looked for.
#
# Deliberately NO --json field-list fallback. `pr_blocking_issue` reads
# `closingIssuesReferences`, so a response served without that field matches
# nothing -- exactly as an empty list does. A fallback would not repair
# selection, and would leave the defect in place behind a change that looks
# like a fix.
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
  local candidates_json markerless_json total
  candidates_json="$(gh issue list --repo "$REPO" --state open --limit 500 \
                   --search "label:agent-session:spec -label:agent-session:merge-ready type:issue state:open" \
                   --json number,title,body,labels 2>/dev/null || echo '[]')"
  markerless_json="$(gh issue list --repo "$REPO" --state open --limit 500 \
                   --search "-label:agent-session:spec type:issue state:open" \
                   --json number,title,body,labels 2>/dev/null || echo '[]')"
  local candidates_count
  candidates_count="$(printf '%s' "$candidates_json" | jq 'length')"
  local n_markerless
  n_markerless="$(printf '%s' "$markerless_json" | jq 'length')"
  total=$(( candidates_count + n_markerless ))

  local candidates
  candidates="$(printf '%s' "$candidates_json" | "$PYTHON_BIN" "$GATE_PY" tier-batch)"

  local specced_nums markerless_nums markerless_list n_markerless m
  markerless_nums="$(printf '%s' "$markerless_json" | jq -r '.[].number')"

  local p1_unblock=""
  local p2_execute=""
  local p3_groom=""
  local p4_escalate=""

  n_markerless=0
  markerless_list=""
  for m in $markerless_nums; do
    n_markerless=$(( n_markerless + 1 ))
    markerless_list="${markerless_list:+$markerless_list, }#$m"

    local is_parked=0
    local parked_reason=""
    if printf '%s\n' "${parked:-}" | grep -qx "$m" && [ "${RETRY:-}" != "$m" ]; then
      is_parked=1
      parked_reason="parked: $(park_reason "$m")"
    fi

    if [ "$is_parked" -eq 1 ]; then
      p4_escalate="${p4_escalate}${m}:escalate "
      say "  SKIP    #$m  $parked_reason"
      say "  ELIGIBLE #$m  escalate (Priority 4: Escalate)"
    else
      local phase="triage"
      local attempts=$(get_attempts "$m" "$phase")
      if [ "${attempts:-0}" -ge "${MAX_PHASE_ATTEMPTS:-3}" ]; then
        local reason="MAX_PHASE_ATTEMPTS ($MAX_PHASE_ATTEMPTS) reached for phase $phase"
        apply_park_state "$m" "parked" "$(date -u +%Y%m%dT%H%M%SZ)" "parked by loop breaker: $reason"
        p4_escalate="${p4_escalate}${m}:escalate "
        say "  SKIP    #$m  $reason"
        say "  ELIGIBLE #$m  escalate (Priority 4: Escalate)"
      else
        p3_groom="${p3_groom}${m}:triage "
        say "  ELIGIBLE #$m  triage (Priority 3: Groom)"
      fi
    fi
  done

  if [ "$n_markerless" -gt 0 ]; then
    say "repo $REPO: read $total open issues ($(( total - n_markerless )) carry the label;" \
        "$n_markerless do not: $markerless_list -- run triage)"
  else
    say "repo $REPO: read $total open issues"
  fi
  [ "$total" -eq 500 ] && say "WARNING: hit the 500 limit; the queue read may be truncated"

  rm -f "$STATE_DIR/columns.tsv"
  touch "$STATE_DIR/columns.tsv"
  load_board
  local prs parked
  prs="$("$PYTHON_BIN" "$GH_QUERY_PY" fetch-open-prs --repo "$REPO")" || die "open-PR query failed -- cannot tell which issues already have open PRs, so selection would be a guess. Refusing to select. (gh's own error is above.)"
  # Fetch all issues for park lookup
  local issues_json="$(gh issue list --repo "$REPO" --state open --limit 500 --json number,title,body,labels 2>/dev/null || echo '[]')"
  parked="$(printf '%s' "$issues_json" | parked_numbers || true)"

  local n tier title col prline mention reason
  if [ -n "$candidates" ]; then
    while IFS="$(printf '\t')" read -r n tier title; do
      [ -n "$n" ] || continue
      col="$(board_status "$n")"
      printf '%s\t%s\n' "$n" "${col:-}" >> "$STATE_DIR/columns.tsv"
      prline="$(printf '%s' "$prs" | "$PYTHON_BIN" "$GH_QUERY_PY" pr-blocking-issue "$n")"
      mention=""
      [ -z "$prline" ] && mention="$(printf '%s' "$prs" | "$PYTHON_BIN" "$GH_QUERY_PY" pr-for-issue "$n")"
      
      local is_parked=0
      local parked_reason=""
      if printf '%s\n' "$parked" | grep -qx "$n" && [ "$RETRY" != "$n" ]; then
        is_parked=1
        parked_reason="parked: $(park_reason "$n")"
      fi

      local is_invalid_tier=0
      local tier_reason=""
      if [ "$tier" = "conflict" ] || [ "$tier" = "missing" ] || [ "$tier" = "unparsed" ]; then
        is_invalid_tier=1
        tier_reason="tier is invalid ($tier)"
      fi

      phase="execute"
      reason=""

      if [ -n "$prline" ]; then
        prnum="$(printf '%s' "$prline" | cut -f1)"
        owner_repo="${REPO//\// }"
        owner=$(echo $owner_repo | awk '{print $1}')
        repo_name=$(echo $owner_repo | awk '{print $2}')
        
        threads_json=$(gh api graphql -f query='query($owner:String!,$repo:String!,$pr:Int!){repository(owner:$owner,name:$repo){pullRequest(number:$pr){reviewThreads(first:100){nodes{isResolved}}}}}' -F owner="$owner" -F repo="$repo_name" -F pr="$prnum" 2>/dev/null || echo "{}")
        unresolved=$(printf '%s' "$threads_json" | jq '[.data.repository.pullRequest.reviewThreads.nodes[]?|select(.isResolved==false)]|length' 2>/dev/null || echo "0")
        if [ "$unresolved" -gt 0 ]; then
          phase="address_comments"
        else
          local checks_out failed pending
          if checks_out=$(gh pr checks "$prnum" --repo "$REPO" --json name,bucket 2>&1); then
            failed=$(printf '%s' "$checks_out" | jq '[.[]|select(.bucket!="pass" and .bucket!="skipping" and .bucket!="pending")]|length' 2>/dev/null || echo "0")
            pending=$(printf '%s' "$checks_out" | jq '[.[]|select(.bucket=="pending")]|length' 2>/dev/null || echo "0")
            if [ "$failed" -gt 0 ]; then
              phase="fix_ci"
            elif [ "$pending" -gt 0 ]; then
              reason="PR #$prnum CI is still pending; waiting..."
            else
              local pr_reviews=$(gh pr view "$prnum" --repo "$REPO" --json reviewRequests,reviews 2>/dev/null || echo "{}")
              local requested=$(printf '%s' "$pr_reviews" | jq '.reviewRequests | length' 2>/dev/null || echo "0")
              local reviewed=$(printf '%s' "$pr_reviews" | jq '.reviews | length' 2>/dev/null || echo "0")
              if [ "$requested" -eq 0 ] && [ "$reviewed" -eq 0 ]; then
                phase="request_review"
              else
                phase="grade_gate"
              fi
            fi
          else
            phase="grade_gate"
          fi
        fi

        if [ -n "$reason" ]; then
          say "  SKIP    #$n  $reason"
        else
          if [ "$is_parked" -eq 1 ] && [ "$phase" = "grade_gate" ]; then
            reason="$parked_reason"
            p4_escalate="${p4_escalate}${n}:escalate "
            say "  SKIP    #$n  $reason"
            say "  ELIGIBLE #$n  escalate (Priority 4: Escalate)"
          else
            local attempts=$(get_attempts "$n" "$phase")
            if [ "$attempts" -ge "$MAX_PHASE_ATTEMPTS" ]; then
              reason="MAX_PHASE_ATTEMPTS ($MAX_PHASE_ATTEMPTS) reached for phase $phase"
              apply_park_state "$n" "parked" "$(date -u +%Y%m%dT%H%M%SZ)" "parked by loop breaker: $reason"
              p4_escalate="${p4_escalate}${n}:escalate "
              say "  SKIP    #$n  $reason"
              say "  ELIGIBLE #$n  escalate (Priority 4: Escalate)"
            else
              p1_unblock="${p1_unblock}${n}:${phase} "
              say "  ELIGIBLE #$n  tier: auto-ok (Priority 1: Unblock - $phase)"
              [ "$is_parked" -eq 1 ] && say "  NOTE    #$n  Bypassing park state ($parked_reason) to perform Unblock phase: $phase"
            fi
          fi
        fi
      else
        if [ "$is_parked" -eq 1 ]; then
          reason="$parked_reason"
          p4_escalate="${p4_escalate}${n}:escalate "
          say "  SKIP    #$n  $reason"
          say "  ELIGIBLE #$n  escalate (Priority 4: Escalate)"
        elif [ "$is_invalid_tier" -eq 1 ]; then
          reason="$tier_reason"
          p4_escalate="${p4_escalate}${n}:escalate "
          say "  SKIP    #$n  $reason"
          say "  ELIGIBLE #$n  escalate (Priority 4: Escalate)"
        elif [ "$tier" = "needs-review" ]; then
          phase="refine"
          local attempts=$(get_attempts "$n" "$phase")
          if [ "$attempts" -ge "$MAX_PHASE_ATTEMPTS" ]; then
            reason="MAX_PHASE_ATTEMPTS ($MAX_PHASE_ATTEMPTS) reached for phase $phase"
            apply_park_state "$n" "parked" "$(date -u +%Y%m%dT%H%M%SZ)" "parked by loop breaker: $reason"
            p4_escalate="${p4_escalate}${n}:escalate "
            say "  SKIP    #$n  $reason"
            say "  ELIGIBLE #$n  escalate (Priority 4: Escalate)"
          else
            p3_groom="${p3_groom}${n}:${phase} "
            say "  ELIGIBLE #$n  tier: needs-review (Priority 3: Groom - $phase)"
          fi
        elif [ "$tier" = "auto-ok" ]; then
          phase="execute"
          local attempts=$(get_attempts "$n" "$phase")
          if [ "$attempts" -ge "$MAX_PHASE_ATTEMPTS" ]; then
            reason="MAX_PHASE_ATTEMPTS ($MAX_PHASE_ATTEMPTS) reached for phase $phase"
            apply_park_state "$n" "parked" "$(date -u +%Y%m%dT%H%M%SZ)" "parked by loop breaker: $reason"
            p4_escalate="${p4_escalate}${n}:escalate "
            say "  SKIP    #$n  $reason"
            say "  ELIGIBLE #$n  escalate (Priority 4: Escalate)"
          else
            p2_execute="${p2_execute}${n}:${phase} "
            say "  ELIGIBLE #$n  tier: auto-ok (Priority 2: Execute - $phase)"
          fi
        fi
      fi
    done <<INNER_EOF
$candidates
INNER_EOF
  fi

  p1_unblock="$(echo "$p1_unblock" | tr -s ' ' '\n' | grep -v '^$' || true)"
  p2_execute="$(echo "$p2_execute" | tr -s ' ' '\n' | grep -v '^$' || true)"
  p3_groom="$(echo "$p3_groom" | tr -s ' ' '\n' | grep -v '^$' || true)"
  p4_escalate="$(echo "$p4_escalate" | tr -s ' ' '\n' | grep -v '^$' || true)"

  ELIGIBLE=""
  if [ -n "$p1_unblock" ]; then
    ELIGIBLE="$(echo "$p1_unblock" | head -n 1)"
  elif [ -n "$p2_execute" ]; then
    ELIGIBLE="$(echo "$p2_execute" | head -n 1)"
  elif [ -n "$p3_groom" ]; then
    ELIGIBLE="$(echo "$p3_groom" | head -n 1)"
  elif [ -n "$p4_escalate" ]; then
    ELIGIBLE="$(echo "$p4_escalate" | head -n 1)"
  fi

  local c=0
  if [ -n "$ELIGIBLE" ]; then
    c=1
  fi
  say "eligible: ${c} ($ELIGIBLE)"
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
AGENT_RUNNER_PY="$(cd "$(dirname "$0")" && pwd)/agent_runner.py"

GATE_JSON=""
GATE_BLOCK=""
classify_pr_body() { # $1 = PR body, $2 = head sha, $3 = ci checks json. Prints "outcome<TAB>reason".
  # Clear both FIRST. The callers now read these globals rather than this
  # function's stdout, so a failed classify must not leave the PREVIOUS issue's
  # verdict standing in them -- under --max-issues 2 that would record issue A's
  # outcome against issue B, which is the same class of defect as #32 itself.
  GATE_JSON=""
  GATE_BLOCK=""
  local extra_args=()
  if [ -n "${3:-}" ]; then
    extra_args=(--ci-checks "$3")
  fi
  GATE_JSON="$("$PYTHON_BIN" "$GATE_PY" classify --head-sha "${2:-}" ${extra_args[@]+"${extra_args[@]}"} <<<"$1")"
  GATE_BLOCK="$(printf '%s' "$GATE_JSON" | jq -r '.gate')"
  # Warnings are the parser's "a null must never render as a positive" channel;
  # surface them here rather than letting them die inside the JSON.
  #
  # `log`, never `say`: this function's stdout IS its return value (see the header
  # comment), and `say` writes to stdout while `log` and `die` redirect to stderr.
  # A `say` here put the warning on line 1 of the return value, and the callers'
  # `read -r` takes only the first line -- so the warning became the outcome and
  # the real outcome was discarded unread. That destroyed the record of a $16.69
  # run on decafclaw #657, and --classify-only reproduced it. See issue #32.
  printf '%s' "$GATE_JSON" | jq -r '.warnings[]?' | while IFS= read -r w; do
    log "  WARNING: $w"
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
  local runner="${AGENT_RUNNER_PY:-$(cd "$(dirname "$0")" && pwd)/agent_runner.py}"
  "$PYTHON_BIN" "$runner" has-success --backend "${BACKEND:-claude}" --raw-output "$1"
}

# The driver-fault branch needs POSITIVE evidence that the invocation never reached
# the model, not merely the absence of an extractable cost. A stream with events in
# it is a run that started, whatever pick_result could make of it: on #50 a stream
# carrying 95 turns and $10.93 was recorded as `cost_usd: 0, no spend` because the
# result record had not been flushed when the driver read it. An effectively empty
# stream is the never-started shape, and it is the only one that branch may claim.
#
# `-s` answers the zero-byte case without depending on jq's behaviour on empty
# input. Unparseable garbage makes jq exit non-zero and so reads as "no events" --
# the conservative direction, since it preserves today's classification for a case
# nobody has evidence about rather than silently reclassifying it. See issue #58.
#
# So a false answer means "no READABLE events", which is not the same as "the file
# is empty" -- and the reason string below says the former for exactly that reason.
# Claiming an empty stream about a truncated one would be this issue's own defect
# in miniature: an assertion the driver is not in a position to make.
stream_has_events() { # $1 = stream.jsonl path
  local runner="${AGENT_RUNNER_PY:-$(cd "$(dirname "$0")" && pwd)/agent_runner.py}"
  [ -s "$1" ] || return 1
  "$PYTHON_BIN" "$runner" has-events --raw-output "$1"
}

# --- stage: invoke ---------------------------------------------------------

build_prompt() { # $1 = issue url, $2 = phase
  local phase="$2"
  local phase_file="phases/express.md"
  if [ "$phase" != "execute" ]; then
    phase_file="phases/$phase.md"
  fi
  cat <<EOF
You are running unattended, invoked by the agent-session board-driver.

Read $SKILL_DIR/SKILL.md, then read $SKILL_DIR/$phase_file and follow it
exactly for this issue:

  $1

The skill is not installed as a registered skill. Its files live at $SKILL_DIR and
you must read them from there by absolute path.

Stop at the merge gate and report the verdict. Do not merge the PR and do not enable
auto-merge.

There is no human watching this run. If the phase directs you to stop and surface
something, stop and state plainly what needs a decision and why. Do not substitute
your own judgment for the decision just because nobody is here to answer: a parked
issue is a normal, expected outcome for this driver, and an unattended guess is not.
EOF
}

run_issue() { # $1 = issue number
  increment_attempts "$1" "${2:-execute}"
  local n="$1" phase="${2:-execute}" url ts rundir raw prompt rc=0
  local pre_run_col=""
  if [ -f "$STATE_DIR/columns.tsv" ]; then
    pre_run_col="$(awk -F '\t' -v n="$n" '$1 == n {print $2; exit}' "$STATE_DIR/columns.tsv")"
  fi
  if [ -z "$pre_run_col" ] && [ -n "$BOARD" ]; then
    pre_run_col="$(board_status "$n")"
  fi
  url="https://github.com/$REPO/issues/$n"
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  rundir="$STATE_DIR/runs/$n-$ts"
  mkdir -p "$rundir"
  raw="$rundir/stream.jsonl"
  prompt="$(build_prompt "$url" "$phase")"
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
  local main_before
  main_before="$(git -C "$REPO_PATH" rev-parse main 2>/dev/null || echo unknown)"

  # Run in the background and hold the pid, so the EXIT trap can kill the child.
  # Without this the child outlives its driver: a VSCode crash took the driver
  # down and the agent runner was reparented to init (PPID 1), still spending and
  # still mutating the repo with nothing supervising it. Observed, not theorised.
  set +e
  if [ -n "$TIMEOUT_CMD" ]; then
    ( cd "$REPO_PATH" && \
        HIGH_TIER_MODEL="${HIGH_TIER_MODEL:-}" \
        LOW_TIER_MODEL="${LOW_TIER_MODEL:-}" \
        exec "$TIMEOUT_CMD" "$RUN_TIMEOUT" "$PYTHON_BIN" "$AGENT_RUNNER_PY" run \
        --backend "${BACKEND:-claude}" \
        --repo-path "$REPO_PATH" \
        --skill-dir "$SKILL_DIR" \
        --prompt-file "$rundir/prompt.txt" \
        --raw-output "$raw" \
        --stderr-output "$rundir/stderr.txt" \
        --max-budget "$MAX_BUDGET" \
        --timeout "$RUN_TIMEOUT" \
        ${MODEL:+--model "$MODEL"} \
        ${HIGH_TIER_MODEL:+--high-tier-model "$HIGH_TIER_MODEL"} \
        ${LOW_TIER_MODEL:+--low-tier-model "$LOW_TIER_MODEL"} \
        --allowed-tools "$ALLOWED_TOOLS" \
        --disallowed-tools "$DENIED_TOOLS" \
        --settings "$HOOK_SETTINGS_FILE" ) \
      &
  else
    say "  NOTE: no timeout/gtimeout found; running unbounded (budget still caps cost)"
    ( cd "$REPO_PATH" && \
        HIGH_TIER_MODEL="${HIGH_TIER_MODEL:-}" \
        LOW_TIER_MODEL="${LOW_TIER_MODEL:-}" \
        exec "$PYTHON_BIN" "$AGENT_RUNNER_PY" run \
        --backend "${BACKEND:-claude}" \
        --repo-path "$REPO_PATH" \
        --skill-dir "$SKILL_DIR" \
        --prompt-file "$rundir/prompt.txt" \
        --raw-output "$raw" \
        --stderr-output "$rundir/stderr.txt" \
        --max-budget "$MAX_BUDGET" \
        --timeout "$RUN_TIMEOUT" \
        ${MODEL:+--model "$MODEL"} \
        ${HIGH_TIER_MODEL:+--high-tier-model "$HIGH_TIER_MODEL"} \
        ${LOW_TIER_MODEL:+--low-tier-model "$LOW_TIER_MODEL"} \
        --allowed-tools "$ALLOWED_TOOLS" \
        --disallowed-tools "$DENIED_TOOLS" \
        --settings "$HOOK_SETTINGS_FILE" ) &
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
  "$PYTHON_BIN" "$AGENT_RUNNER_PY" parse \
    --backend "${BACKEND:-claude}" \
    --raw-output "$raw" \
    --output-json "$rundir/parsed.json"

  local final cost session cost_known=0
  final="$("$PYTHON_BIN" -c "import json, sys; print(json.load(open(sys.argv[1]))['final'])" "$rundir/parsed.json")"
  cost="$("$PYTHON_BIN" -c "import json, sys; print(json.load(open(sys.argv[1]))['total_cost_usd'])" "$rundir/parsed.json")"
  session="$("$PYTHON_BIN" -c "import json, sys; print(json.load(open(sys.argv[1]))['session_id'])" "$rundir/parsed.json")"
  "$PYTHON_BIN" -c "import json, sys; sys.exit(0 if json.load(open(sys.argv[1]))['cost_known'] else 1)" "$rundir/parsed.json" && cost_known=1

  # If cost is undetermined on a nonzero exit, wait briefly for any pending flush and try again (Issue #82)
  if [ "$cost_known" -eq 0 ] && [ "$rc" -ne 0 ]; then
    say "  cost undetermined on exit $rc; waiting 1s for stream flush..."
    sleep 1
    "$PYTHON_BIN" "$AGENT_RUNNER_PY" parse \
      --backend "${BACKEND:-claude}" \
      --raw-output "$raw" \
      --output-json "$rundir/parsed.json"
    final="$("$PYTHON_BIN" -c "import json, sys; print(json.load(open(sys.argv[1]))['final'])" "$rundir/parsed.json" 2>/dev/null || echo "$final")"
    cost="$("$PYTHON_BIN" -c "import json, sys; print(json.load(open(sys.argv[1]))['total_cost_usd'])" "$rundir/parsed.json" 2>/dev/null || echo "$cost")"
    session="$("$PYTHON_BIN" -c "import json, sys; print(json.load(open(sys.argv[1]))['session_id'])" "$rundir/parsed.json" 2>/dev/null || echo "$session")"
    "$PYTHON_BIN" -c "import json, sys; sys.exit(0 if json.load(open(sys.argv[1]))['cost_known'] else 1)" "$rundir/parsed.json" 2>/dev/null && cost_known=1
  fi

  printf '%s' "$final" > "$rundir/final.txt"

  # Denials are greppable, in three measured phrasings: the rule-specific
  # "with command <cmd> has been denied", the generic don't-ask-mode form, and the
  # path-rule form ("denied by your permission settings") that Edit/Write deny
  # rules produce. A PreToolUse hook would add a fourth -- if that lands, teach
  # this pattern its wording, or the count silently undercounts.
  local denials
  denials="$(grep -oE '(Permission to use [^"]*has been denied[^"]*|[^"]*denied by your permission settings[^"]*|The PreToolUse hook rejected[^"]*)' \
             "$raw" 2>/dev/null || true)"
  if [ -n "$denials" ]; then
    printf '%s\n' "$denials" > "$rundir/denials.txt"
    say "  DENIALS ($(printf '%s\n' "$denials" | grep -c .)) -- see $rundir/denials.txt"
    printf '%s\n' "$denials" | sort -u | sed 's/^/    /' >&2
  fi

  say "  exit $rc   cost \$$cost   session ${session:-none}"

  # --- classify ---
  local outcome reason prline prnum prurl gate
  if [ "$rc" -eq 124 ]; then
    outcome="failed"; reason="timed out after ${RUN_TIMEOUT}s"
  elif [ "$rc" -ne 0 ] && [ -z "$session" ] && { [ "${cost:-0}" = "0" ] || [ "${cost:-0}" = "0.0" ]; } \
       && ! stream_has_events "$raw"; then
    # No readable events, no session id and no spend means the invocation never
    # reached the model, so this is the DRIVER being broken, not the run failing.
    # Worth separating: a driver fault is fixed by editing this script, an
    # escalation is not, and the first #585 attempt spent $0 dying on a bad path
    # while looking like a normal failed run. Never park it -- parking would hide
    # the driver's own bug behind a skip reason on a perfectly good issue.
    #
    # The stream conjunct is what keeps that separation honest. Without it the
    # branch inferred "never started" from two empty variables, so an extractor
    # miss on a real run was recorded as a fact ABOUT the run -- $10.93 logged as
    # $0 on #50. See issue #58.
    #
    # "no readable events" rather than "empty stream": a truncated or garbled
    # stream is non-empty and still lands here, so the stronger wording would be
    # an assertion the driver has not earned. Same discipline the branch itself
    # is being taught.
    outcome="driver-fault"
    reason="${BACKEND:-claude} exited $rc before starting (no readable events, no session, no spend) -- see $rundir/stderr.txt"
  elif [ "$rc" -ne 0 ] && ! has_success_result "$raw"; then
    outcome="failed"
    if [ "$cost_known" -eq 1 ]; then
      reason="${BACKEND:-claude} exited $rc"
    else
      # The run started and did not finish, and the driver cannot say what it
      # cost. Say that, rather than letting the ledger's `cost_usd: 0` stand as a
      # claim -- a missing row prompts someone to go looking, a confident zero
      # does not.
      reason="${BACKEND:-claude} exited $rc; cost undetermined (no result record in the stream) -- see $rundir/stderr.txt"
    fi
  else
    # rc != 0 with a successful result in the stream is the spurious-trailing-record
    # case. Say so out loud rather than swallowing it -- the exit code is still a real
    # signal that something went wrong after the run finished.
    if [ "$rc" -ne 0 ]; then
      say "  NOTE: ${BACKEND:-claude} exited $rc but the stream carries a successful result;"
      say "        classifying from the gate block, not the exit code."
    fi
    # DEGRADE, distinguishably -- the opposite trade from selection, on purpose.
    # This run already cost money and may already have opened a PR, so refusing
    # here would throw away the only record of it. What must not happen is
    # recording `no PR opened` about a PR the driver never managed to look for:
    # that is a wrong ledger row, not a wasted stage.
    #
    # Split across two statements rather than nested in one `$( )`: command
    # substitution discards the inner exit status, which is how the failure went
    # unnoticed here in the first place. See issue #39.
    local prs_json pr_query_failed=0
    prs_json="$("$PYTHON_BIN" "$GH_QUERY_PY" fetch-open-prs --repo "$REPO")" || pr_query_failed=1
    prline=""
    if [ "$pr_query_failed" -eq 0 ]; then
      prline="$(printf '%s' "$prs_json" | "$PYTHON_BIN" "$GH_QUERY_PY" pr-for-issue "$n")"
    fi
    if [ -z "$prline" ]; then
      outcome="parked"
      if [ "$pr_query_failed" -eq 1 ]; then
        reason="open-PR query failed; cannot tell whether a PR was opened. run's own account: $(printf '%s' "$final" | tr '\n' ' ' | cut -c1-400)"
      else
        reason="no PR opened; run's own account: $(printf '%s' "$final" | tr '\n' ' ' | cut -c1-400)"
      fi
    else
      prnum="$(printf '%s' "$prline" | cut -f1)"
      prurl="$(printf '%s' "$prline" | cut -f2)"
      _body="$(gh pr view "$prnum" --repo "$REPO" --json body -q .body 2>/dev/null || true)"
      GATE_HEAD_SHA="$(gh pr view "$prnum" --repo "$REPO" --json headRefOid -q .headRefOid 2>/dev/null || true)"
      _checks_out=""
      _checks_rc=0
      _checks_out="$(gh pr checks "$prnum" --repo "$REPO" --json name,bucket 2>&1)" || _checks_rc=$?
      if [ "$_checks_rc" -eq 0 ]; then
        _ci_checks="$_checks_out"
      elif case "$_checks_out" in *"no checks reported"*|*"no required checks reported"*) true ;; *) false ;; esac; then
        _ci_checks="[]"
      else
        _ci_checks=""
      fi
      # Read the JSON, not the stdout line. Two reasons, both learned on #657:
      #
      #   1. Parsing stdout means anything else written there corrupts the value.
      #      Phase 1 moved the one offender to stderr; this removes the shared
      #      channel, so the next diagnostic added inside cannot re-break it.
      #   2. NOT `$(classify_pr_body ...)`: command substitution forks, so the
      #      GATE_JSON and GATE_BLOCK the function assigns were being set in a
      #      subshell and lost. That is why every gate.yaml this driver has ever
      #      written is empty. Calling it plainly keeps both.
      #
      # The stdout contract stays honoured (see the function's comment); it is
      # just not what these callers read. See issue #32.
      #
      # `|| true` preserves the pre-change failure mode exactly. Inside `$( )` a
      # classifier crash was invisible to `set -e` and left outcome empty; as a
      # plain command it would abort the driver instead, which on the recovery
      # path means dying without recording anything -- #32's own shape.
      classify_pr_body "$_body" "$GATE_HEAD_SHA" "$_ci_checks" >/dev/null || true
      outcome="$(printf '%s' "$GATE_JSON" | jq -r '.outcome')"
      reason="$(printf '%s' "$GATE_JSON" | jq -r '.reason')"
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
  local provenance
  provenance="{}"
  if [ -n "${GATE_JSON:-}" ]; then
    provenance="$(printf '%s' "$GATE_JSON" | jq -c '.provenance // {}' 2>/dev/null || echo '{}')"
  fi
  [ -n "${provenance:-}" ] || provenance='{}'

  jq -n -c \
    --arg issue "$n" --arg repo "$REPO" --arg ts "$ts" \
    --arg outcome "$outcome" --arg reason "$reason" \
    --arg pr "${prurl:-}" --arg session "$session" \
    --arg rundir "$rundir" --argjson rc "$rc" --argjson cost "${cost:-0}" \
    --arg board_column "${pre_run_col:-}" \
    --argjson provenance "$provenance" \
    '{issue:($issue|tonumber), repo:$repo, started:$ts, exit:$rc, cost_usd:$cost,
      session_id:$session, outcome:$outcome, reason:$reason, pr:$pr, run_dir:$rundir, board_column:$board_column, provenance:$provenance}' \
    >> "$RUNS_LOG"

  apply_park_state "$n" "$outcome" "$ts" "$reason"

  case "$outcome" in
    parked|failed|incomplete|no-gate|budget-exhausted|driver-fault)
      if [ -n "$BOARD" ] && [ -n "${pre_run_col:-}" ] && [ "$pre_run_col" != "no-status" ]; then
        local owner num
        owner="${BOARD%%/*}"; num="${BOARD##*/}"
        local item_id project_id field_id option_id
        item_id="$(printf '%s' "$BOARD_JSON" | jq -r --arg n "$n" '.items[]? | select(.content.number == ($n|tonumber)) | .id // empty' 2>/dev/null || true)"
        if [ -n "$item_id" ]; then
          project_id="$(gh project view "$num" --owner "$owner" --format json --jq '.id' 2>/dev/null || true)"
          local fields_json
          fields_json="$(gh project field-list "$num" --owner "$owner" --format json 2>/dev/null || echo '[]')"
          field_id="$(printf '%s' "$fields_json" | jq -r '.[]? | select(.name == "Status") | .id // empty' 2>/dev/null || true)"
          option_id="$(printf '%s' "$fields_json" | jq -r --arg col "$pre_run_col" '.[]? | select(.name == "Status") | .options[]? | select(.name == $col) | .id // empty' 2>/dev/null || true)"
          if [ -n "$project_id" ] && [ -n "$field_id" ] && [ -n "$option_id" ]; then
            gh project item-edit \
              --project-id "$project_id" \
              --id "$item_id" \
              --field-id "$field_id" \
              --single-select-option-id "$option_id" >/dev/null 2>&1 \
              && say "  board: restored #$n column to $pre_run_col" \
              || say "  WARNING: could not restore #$n column to $pre_run_col"
          fi
        fi
      fi
      ;;
  esac

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
    # The refusal exists because two concurrent runs cannot share one inflight.json,
    # and because the orphan is still spending. The property that matters is
    # therefore "THIS invocation can spend or mutate", not "a run is in progress" --
    # and --dry-run invokes no claude, writes nothing to the state dir and creates
    # no worktree. Refusing it protects nothing while costing the operator the one
    # measurement findings.md tells them to take while a run is live: the
    # before/after eligible count around a triage pass. Issue #51.
    #
    # The warning above still prints under --dry-run, deliberately. It is the
    # useful half, and suppressing it would hide a genuinely dead run from the
    # command someone is most likely to reach for while poking at state.
    #
    # NOT --classify-only, also deliberately. That path derives an outcome from a
    # run's live state and writes both a ledger row and park labels; a live run's
    # state is still moving, so the advice two lines up is to wait, not a door to
    # open early.
    if [ "$DRY_RUN" -eq 0 ]; then
      die "refusing to start a second run while an orphan is live"
    fi
    say ""
  else
    # Reachable only when the orphan is NOT live. `die` used to guarantee that;
    # now that --dry-run falls through, the `else` is what preserves it. Printing
    # "recover it with --classify-only" under a live orphan would advise exactly
    # the action the branch above tells the operator to wait on.
    say "  recover it with:  --classify-only $(jq -r '.issue' "$STATE_DIR/inflight.json" 2>/dev/null)"
    say ""
  fi
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
    "$PYTHON_BIN" "$AGENT_RUNNER_PY" parse \
      --backend "${BACKEND:-claude}" \
      --raw-output "$rundir/stream.jsonl" \
      --output-json "$rundir/parsed.json"
    cost="$("$PYTHON_BIN" -c "import json, sys; print(json.load(open(sys.argv[1]))['total_cost_usd'])" "$rundir/parsed.json" 2>/dev/null || echo 0)"
    session="$("$PYTHON_BIN" -c "import json, sys; print(json.load(open(sys.argv[1]))['session_id'])" "$rundir/parsed.json" 2>/dev/null || true)"
    ts="$(basename "$rundir" | sed "s/^$n-//")"
    say "  recovered from stream: cost \$$cost  session ${session:-none}"
  else
    say "  no run dir found for #$n; classifying from the PR alone"
    rundir="(none)"
  fi

  if [ -n "$RESUMED_FROM" ] && [ -f "$RESUMED_FROM" ]; then
    resumed_cost="$("$PYTHON_BIN" -c "import json, sys; print(json.load(open(sys.argv[1])).get('total_cost_usd', 0))" "$RESUMED_FROM" 2>/dev/null || echo 0)"
    resumed_session="$("$PYTHON_BIN" -c "import json, sys; print(json.load(open(sys.argv[1])).get('session_id', ''))" "$RESUMED_FROM" 2>/dev/null || true)"
    if [ -n "$resumed_cost" ]; then
      cost="$resumed_cost"
    fi
    if [ -n "$resumed_session" ]; then
      session="$resumed_session"
    fi
    say "  resumed-from $RESUMED_FROM: cost \$$cost  session ${session:-none}"
  fi

  # Same degrade-distinguishably fix as the run path above, and for the reason
  # its own comment block gives a few lines down: fixing one of these two call
  # sites and not the other is findings.md class 1, "fixed the cost field, never
  # generalised". --classify-only is the documented recovery path for an
  # unrecorded outcome, so a wrong reason here is a wrong reason in exactly the
  # place someone is looking to find out what happened. Issue #39.
  _prs_json=""; _pr_query_failed=0
  _prs_json="$("$PYTHON_BIN" "$GH_QUERY_PY" fetch-open-prs --repo "$REPO" --state all)" || _pr_query_failed=1
  prline=""
  if [ "$_pr_query_failed" -eq 0 ]; then
    prline="$(printf '%s' "$_prs_json" | "$PYTHON_BIN" "$GH_QUERY_PY" pr-for-issue "$n")"
  fi
  if [ -z "$prline" ]; then
    outcome="parked"
    if [ "$_pr_query_failed" -eq 1 ]; then
      reason="open-PR query failed; cannot tell whether #$n has an open PR"
    else
      reason="no open PR found for #$n"
    fi
    prurl=""
  else
    prnum="$(printf '%s' "$prline" | cut -f1)"
    prurl="$(printf '%s' "$prline" | cut -f2)"
    _body="$(gh pr view "$prnum" --repo "$REPO" --json body -q .body 2>/dev/null || true)"
    GATE_HEAD_SHA="$(gh pr view "$prnum" --repo "$REPO" --json headRefOid -q .headRefOid 2>/dev/null || true)"
    _checks_out=""
    _checks_rc=0
    _checks_out="$(gh pr checks "$prnum" --repo "$REPO" --json name,bucket 2>&1)" || _checks_rc=$?
    if [ "$_checks_rc" -eq 0 ]; then
      _ci_checks="$_checks_out"
    elif case "$_checks_out" in *"no checks reported"*|*"no required checks reported"*) true ;; *) false ;; esac; then
      _ci_checks="[]"
    else
      _ci_checks=""
    fi
    # Same read as the run path above, for the same reasons -- and this is the
    # call site that MATTERS most: --classify-only is the documented recovery path
    # for an unrecorded outcome, and on #657 it reproduced the same corruption it
    # exists to repair. A fix at one call site and not the other is findings.md
    # class 1's "fixed the cost field, never generalised". See issue #32.
    # `|| true` for the same reason as the run path: never abort where the whole
    # point of this code path is to get an outcome recorded.
    classify_pr_body "$_body" "$GATE_HEAD_SHA" "$_ci_checks" >/dev/null || true
    outcome="$(printf '%s' "$GATE_JSON" | jq -r '.outcome')"
    reason="$(printf '%s' "$GATE_JSON" | jq -r '.reason')"
    [ "$rundir" != "(none)" ] && printf '%s\n' "$GATE_BLOCK" > "$rundir/gate.yaml"
  fi

  say "  outcome  $outcome"
  say "  reason   $reason"
  [ -n "$prurl" ] && say "  pr       $prurl"

  provenance="{}"
  if [ -n "${GATE_JSON:-}" ]; then
    provenance="$(printf '%s' "$GATE_JSON" | jq -c '.provenance // {}' 2>/dev/null || echo '{}')"
  fi
  [ -n "${provenance:-}" ] || provenance='{}'

  _jq_args=(
    --arg issue "$n" --arg repo "$REPO" --arg ts "$ts"
    --arg outcome "$outcome" --arg reason "$reason"
    --arg pr "$prurl" --arg session "$session"
    --arg rundir "$rundir" --argjson rc "$rc" --argjson cost "${cost:-0}"
    --argjson provenance "$provenance"
  )
  if [ -n "$RESUMED_FROM" ]; then
    _jq_args+=(--arg resumed_from "$RESUMED_FROM")
    _extra='{resumed: true, resumed_from: $resumed_from}'
  else
    _extra='{}'
  fi

  jq -n -c \
    "${_jq_args[@]}" \
    "{issue:(\$issue|tonumber), repo:\$repo, started:\$ts, exit:\$rc, cost_usd:\$cost,
       session_id:\$session, outcome:\$outcome, reason:\$reason, pr:\$pr, run_dir:\$rundir,
       recovered:true, provenance:\$provenance} + $_extra" \
    >> "$RUNS_LOG"

  if [ -n "$prline" ]; then
    apply_park_state "$n" "$outcome" "$ts" "$reason"
  fi

  rm -f "$STATE_DIR/inflight.json"
  say ""
  say "recorded to $RUNS_LOG. Nothing was merged."
  exit 0
fi

if [ -n "$ISSUE" ]; then
  say "== select (single issue: #$ISSUE) =="
  phase="execute"
  if prs="$("$PYTHON_BIN" "$GH_QUERY_PY" fetch-open-prs --repo "$REPO")"; then
    prline="$(printf '%s' "$prs" | "$PYTHON_BIN" "$GH_QUERY_PY" pr-for-issue "$ISSUE")"
    if [ -n "$prline" ]; then
      prnum="$(printf '%s' "$prline" | cut -f1)"
      owner_repo="${REPO//\// }"
      owner=$(echo $owner_repo | awk '{print $1}')
      repo_name=$(echo $owner_repo | awk '{print $2}')
      
      threads_json=$(gh api graphql -f query='query($owner:String!,$repo:String!,$pr:Int!){repository(owner:$owner,name:$repo){pullRequest(number:$pr){reviewThreads(first:100){nodes{isResolved}}}}}' -F owner="$owner" -F repo="$repo_name" -F pr="$prnum" 2>/dev/null || echo "{}")
      unresolved=$(printf '%s' "$threads_json" | jq '[.data.repository.pullRequest.reviewThreads.nodes[]?|select(.isResolved==false)]|length' 2>/dev/null || echo "0")
      unresolved=${unresolved:-0}
      if [ "$unresolved" -gt 0 ]; then
        phase="address_comments"
      else
        checks_out=""
        failed=0
        pending=0
        if checks_out=$(gh pr checks "$prnum" --repo "$REPO" --json name,bucket 2>&1); then
          failed=$(printf '%s' "$checks_out" | jq '[.[]|select(.bucket!="pass" and .bucket!="skipping" and .bucket!="pending")]|length' 2>/dev/null || echo "0")
          failed=${failed:-0}
          pending=$(printf '%s' "$checks_out" | jq '[.[]|select(.bucket=="pending")]|length' 2>/dev/null || echo "0")
          pending=${pending:-0}
          if [ "$failed" -gt 0 ]; then
            phase="fix_ci"
          elif [ "$pending" -gt 0 ]; then
            phase="wait_ci"
          else
            phase="grade_gate"
          fi
        else
          phase="grade_gate"
        fi
      fi
    fi
  fi
  if [ "$phase" != "wait_ci" ]; then
    ELIGIBLE="$ISSUE:$phase"
  else
    ELIGIBLE=""
    say "PR for #$ISSUE CI is still pending; waiting..."
  fi
  say "  eligibility check bypassed by --issue"
  load_board
  rm -f "$STATE_DIR/columns.tsv"
  touch "$STATE_DIR/columns.tsv"
  col="$(board_status "$ISSUE")"
  printf '%s\t%s\n' "$ISSUE" "${col:-}" >> "$STATE_DIR/columns.tsv"
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

for item in $ELIGIBLE; do
  n="${item%%:*}"
  phase="${item##*:}"
  if [ "$ATTEMPTED" -ge "$MAX_ISSUES" ]; then
    say ""
    say "reached --max-issues $MAX_ISSUES; stopping with issues still eligible."
    break
  fi
  run_issue "$n" "$phase" || break
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
