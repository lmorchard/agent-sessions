# Frozen acceptance checks

**Source:** https://github.com/lmorchard/agent-sessions/issues/27
**Frozen at:** 0ad6881 (2026-07-31)
**Check files — read-only from Phase 1 onward:**
- `driver/test-driver.sh`

Criteria and CHECK text below are copied **verbatim** from the issue body. The `file:line`
refs inside them are intake-time snapshots and have since moved; the resolved current
locations are noted under each, and no CHECK command depends on a line number.

## C1

CRITERION: GIVEN a live in-flight marker for repo A, WHEN the driver starts against repo B,
THEN it SHALL NOT refuse, and SHALL NOT report an orphan.

CHECK: a new case in `driver/test-driver.sh` using the offline `gh`-stub + `--dry-run` pattern at
`:456-487` — write a marker for `lmorchard/decafclaw` whose `child.pid` is a live process, invoke
`--repo lmorchard/agent-sessions --dry-run`, and assert the output contains neither
`refusing to start a second run` nor `ORPHAN STILL RUNNING`.

Ref note: the `gh`-stub + `--dry-run` pattern named as `:456-487` now lives at
`driver/test-driver.sh:840-869` (the issue-query section) and `:1041-1062` (the closing-refs
section); `:456-487` is today the nest fixture builder. The pattern, not the line range, is
what the check names.

AT FREEZE: fails — the driver printed
`ORPHAN STILL RUNNING (pid <n>, reparented) -- it is unsupervised and still spending.`
and died with `error: refusing to start a second run while an orphan is live` (exit 2), with
the marker naming decafclaw and the invocation naming agent-sessions. Correct reason: the
behaviour is genuinely absent. Independently reproduced against the shipped driver by
`probe-01-orphan-crossrepo.py` in this session directory.

## C2

CRITERION: WHEN no `--state-dir` is given, the driver SHALL resolve its state directory to
`${XDG_STATE_HOME:-$HOME/.local/state}/agent-session/<owner>-<name>/` for the requested repo, and
SHALL report the resolved path.

CHECK: a case setting `XDG_STATE_HOME` to a temp dir, invoking `--dry-run` with the `gh` stub and
**no** `--state-dir`, asserting that `$XDG_STATE_HOME/agent-session/lmorchard-agent-sessions/`
exists afterwards and that the resolved path appears in the output.

AT FREEZE: fails — `XDG per-repo dir exists: False`, `resolved path appears in output: False`,
and for contrast `./.driver-state created in cwd: True`. Correct reason, and specifically **not**
the compounded one the issue filed this criterion UNRUN for: the run reached the select stage and
exited 0, so no orphan guard was involved. The issue's stated precondition ("once no run is in
flight") was obtained by running from a fresh temp cwd — the pre-change default is
`./.driver-state`, relative to cwd — rather than by waiting for the live run to end. Recorded by
`probe-03-c2-default-state-dir.py` in this session directory.

## C3

CRITERION: GIVEN run directories for the same issue number under two different repos, WHEN
`--classify-only <n>` runs against one repo, THEN it SHALL resolve a run directory belonging to that
repo.

CHECK: a case creating `<state>/lmorchard-decafclaw/runs/4-<ts1>/` and
`<state>/lmorchard-agent-sessions/runs/4-<ts2>/`, then asserting `--classify-only 4` against each
repo resolves the matching one.

AT FREEZE: fails — invoking the shipped driver `--classify-only 4` against
`lmorchard/decafclaw` and against `lmorchard/agent-sessions`, over a state dir holding
`runs/4-20260728T000000Z` and `runs/4-20260729T013605Z`, printed the **same**
`run dir  .../runs/4-20260729T013605Z` line both times (newest wins), with nothing in the path
naming a repo. Correct reason. Recorded by `probe-02-classify-only-ambiguous.py`, which invokes
the driver itself rather than the lookup expression copied out of it — the issue explicitly flags
the intake-time replica probe as not being evidence about the driver (`findings.md` class 1
instance 9).

## Guards

(Pass today; must keep passing. Not criteria — they can't fail at freeze.)

- **G1:** `make driver-test` — no assertion lost, newly skipped, or newly failing. Stated as an
  invariant, not a count. Passed at freeze: `97 passed, 0 failed` (the count is recorded as
  evidence the suite had teeth, not as the assertion).
- **G2:** `make driver-check` — the driver still has no executable merge path. Passed at freeze:
  `driver-check: no executable merge path in driver/agent-session-driver.sh`.
- **G3:** The existing `./.driver-state/` is not modified or deleted by the change or by the
  migration. Passed at freeze: fingerprint recorded by `probe-04-g3-fingerprint.py`, which
  hashes every file under `.driver-state/` in the MAIN checkout excluding this run's own live
  bookkeeping (`inflight.json`, `runs/27-*`, and rows the running driver appends to
  `runs.jsonl`) — that bookkeeping is written by the driver supervising this session, not by the
  change, and G3 is scoped to "by the change or by the migration".
- **G4:** `.driver-state/` stays in `.gitignore`. Passed at freeze: present at `.gitignore:6`.
- **G5 (project gate):** `make check` — green at freeze, all targets.

## Amendments

(Append-only. Empty unless an amendment was made.)

**No amendment.** No CRITERION line, CHECK command, or guard command has changed since the freeze,
and `driver/test-driver.sh` — the only check file, and the whole oracle — is byte-identical to
`0ad6881`.

### Clarification C-1, logged: `probe-01` and `probe-02` were extended after the freeze

Raised by the independent verifier, recorded here rather than left in a subagent report, because it
concerns evidence this file cites.

**What happened.** At freeze, `probe-01` and `probe-02` exercised only one spelling of "repo A is
live": both runs pointed at a single **explicit** `--state-dir`. That is the spelling the issue used
at intake, and it fails before the change. It is also a scenario the change deliberately does *not*
alter — `--state-dir X` still means exactly X, so two runs sharing one directory share one
`inflight.json` and still collide. During Phase 1 both probes were extended to run a second form
with **no** `--state-dir`, which is what the criteria actually assert and what `make run` /
`make run-self` actually invoke.

**Why this is a clarification and not an amendment.** The test in `frozen-checks.md` is whether any
verdict changes at either tree. Nothing does:

- The probes are **not check files.** `Check files` names `driver/test-driver.sh` alone, and that
  file's `#27` cases — the oracle — already used the no-`--state-dir` form *at freeze*, where they
  failed. C1's and C3's teeth were established there, not by the probes.
- No criterion, check, or guard command changed, so no verdict at the freeze tree or the
  implementation tree turns on the edit.
- The extension only **added** a scenario. The original form A is retained verbatim as a negative
  control, and it is load-bearing: if form A ever stopped refusing, the fix would have bought C1 by
  making the orphan guard permissive, which the issue's "What we're NOT doing" forbids.

So: no tier change. Recorded because a cited freeze record was edited afterwards, and a reader
comparing `probe-01` against its freeze version deserves to find the reason here rather than
reconstruct it.

**The honest residual, stated plainly.** As *originally gathered*, C1's `AT FREEZE` corroboration
rested on a scenario the change does not alter. The `AT FREEZE` text above is accurate about what was
observed, and the frozen case is what graded the work — but the probe was weaker corroboration at
freeze than its wording implies. Flagged for the human at the gate.

### Post-review round, human-adjudicated by Les 2026-07-31 — three threads, all fixed

The Copilot review **arrived after this run published its gate block.** The row read
`threads: 0 unresolved — BY SUBSTITUTE: 0 reviews and 0 review comments exist, so no thread can; the
requested review timed out`, and that substitute was true when written and false minutes later. It is
`docs/findings.md` defect class 2 in the gate itself: *no review has arrived yet* is not *no
unresolved threads*. The run's verdict was `human-merge-required` anyway, so nothing was at risk —
but a run that had reached `eligible-for-auto-merge` on the same substitute would have been eligible
on the strength of a review nobody had read. Tracked separately.

**Thread 3 — `driver/agent-session-driver.sh`: `--repo` was not shape-validated, and it now lands in a
filesystem path.** The only genuine defect of the three, and one this change introduced: `REPO` had
never been part of a path before. Measured before fixing, rather than argued:

| `--repo` value | before | after |
|---|---|---|
| `../../../../tmp/ESCAPED` | slug `..-..-..-..-tmp-ESCAPED`, stayed inside the root | rejected |
| `..` | slug `..` → **state dir resolved to the PARENT of `agent-session/`**; `runs.jsonl`, `parked.jsonl` and `runs/` created one level outside the intended root | rejected |
| `owner/name/extra` | slug `owner-name-extra`, confined but wrong | rejected |
| `lmorchard/agent-sessions` | correct | correct |

So the exposure was **one level, not arbitrary traversal** — `${REPO//\//-}` eats the separators, which
is incidental protection rather than a boundary. Now shape-validated: exactly one `/`, and no `.` or
`..` path component. Seven malformed values rejected, the legitimate one unaffected, and nothing is
created outside `$XDG_STATE_HOME/agent-session/` any more.

**Threads 1 and 2 — hardcoded `/Users/lorchard/...` in `probe-04-g3-fingerprint.py` and
`migrate-ledger.py`.** Both now derive the main checkout from
`git rev-parse --path-format=absolute --git-common-dir`, with an `AGENT_SESSION_ARCHIVE` override.
`--git-common-dir` and not `--git-dir` is the point: inside a linked worktree only the common dir
points at the main checkout, and `.driver-state/` is gitignored so it exists only there.

Worth recording that probe-04's *comment already claimed* the value was "resolved from the worktree's
git commondir rather than hardcoded" while the next line hardcoded it, leaving `WORKTREE` computed and
unused. Same shape as `driver/test-driver.sh`'s old *"Source the driver's functions"* comment, which
described a fix that was never made — `findings.md` class 5, a comment asserting what the code does
not do.

**Not an amendment, and not a clarification either.** `driver/test-driver.sh` is this run's only check
file and it is untouched by this round — `git diff <freeze-sha> -- driver/test-driver.sh` stays as the
tamper check and stays clean. The probe scripts are *evidence recorders*, not CHECK mechanisms: C1, C2
and C3 all name cases in `test-driver.sh`. So no frozen oracle moved, no verdict changed at either
tree, and **this run keeps its tier.** Recorded here because the files were touched after the freeze,
not because a check was.

Verified after the round: `bash driver/test-driver.sh` → 112 passed, 0 failed; `make check` green;
`probe-04` → `G3 PASS: all 100 fingerprinted files byte-identical`; both scripts run from a linked
worktree and under the env override. Threads resolved on the grounds `pr.md` requires — each was
fixed, not waved through.

## Resolution of one spec ambiguity, recorded before the freeze

The spec says "`--state-dir` keeps working as an explicit override" without saying whether, after
the change, `--state-dir X` means *state lives in X* (unchanged) or *state lives in `X/<slug>`*.
C3's fixture wording (`<state>/lmorchard-decafclaw/...`) reads both ways.

**Resolved: `--state-dir X` keeps meaning exactly X. Only the default gains the XDG per-repo path,
and `<state>` in C3 is the `agent-session` root under `XDG_STATE_HOME`.**

The reason is mechanical rather than stylistic: `driver/test-park-state.sh` is the **frozen**
acceptance-check file for issue #5 and is read-only. At `:275-282` it writes a two-row ledger to
`$SEED_SD/runs.jsonl` and invokes the driver with `--state-dir "$SEED_SD"`, asserting the skip
reason cites the newer row. Under the `X/<slug>` reading the driver would look for
`$SEED_SD/stub-repo/runs.jsonl`, find nothing, fall back to "no local run record on this host",
and flip two frozen assertions — repairable only by editing another issue's frozen oracle, which
`frozen-checks.md` makes a STOP rather than an edit.

The chosen reading also preserves what the spec's "What we're NOT doing" requires: two runs given
the same explicit `--state-dir` and the same repo still collide at the orphan guard, so the
same-repo refusal is intact and C1 is not satisfied by making the guard permissive.

## Tamper rule for this run

`driver/test-driver.sh` is the only check file, and the implementation has no reason to touch it,
so the primary tamper check applies unmodified:

    git diff <freeze-sha> -- driver/test-driver.sh

Must be empty. Stated as an invariant: **no line in that diff may change what any frozen check
asserts.** Paired with the behavioural guard G1, which is what actually catches a weakened oracle.

### Tamper verdict, recorded before pushing: `clean`

`git diff 0ad6881 -- driver/test-driver.sh` → **empty** (0 lines). Bare `clean`, not
`clean-by-substitute`: the criteria are test cases in a real check file, so the primary mechanism
applies directly and no substitute was needed.

`git diff 0ad6881 -- <session-dir>/checks.md` is non-empty, as the invariant predicts — the freeze
procedure writes the sha in a follow-up commit. Every difference is a sanctioned append: the
`Frozen at` sha, this verdict, and clarification C-1. **No CRITERION line, CHECK command, or guard
command differs from the freeze version.**

Independently confirmed by the verifier subagent, which also audited the criteria and CHECK text
against issue #27 codepoint by codepoint (for lookalike punctuation) and found them byte-faithful.

The freeze commit is an ancestor of the pushed head (`git merge-base --is-ancestor 0ad6881 HEAD`),
so a reviewer can re-run both diffs rather than taking this record on trust.
