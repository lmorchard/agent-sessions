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

None.

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
