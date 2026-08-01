# Frozen acceptance checks

**Source:** https://github.com/lmorchard/agent-sessions/issues/39
**Frozen at:** `cc45871` (2026-07-31)
**Check files — read-only from Phase 1 onward:**
- `driver/test-park-state.sh`

Criteria and CHECK text below are copied **verbatim** from the issue body. The `AT FREEZE`
lines are this run's observations and are the only thing added.

*Note on the check file:* `driver/test-park-state.sh` is already the frozen check file for
issue #5. This run appends three new cases to it at Phase 0 and then treats the whole file as
read-only, exactly as #5's run did. The existing #5 cases are guards for this run (G3 covers
them), so weakening one to make a new case pass would be caught in both directions.

## C1

CRITERION: IF the open-PR query fails, THEN the selection stage SHALL report the failure and exit
non-zero, AND SHALL NOT invoke `claude`.

CHECK: a new case in `driver/test-park-state.sh` whose `gh` stub exits 1 on `pr list` while
serving the issue list normally — assert the driver's output names the query failure, its exit
status is non-zero, and the argv log records **zero** `claude` invocations. Run by `make park-test`.
**The zero-invocations clause is the load-bearing half**: an implementation that prints a warning
and proceeds satisfies "reports the failure" and still spends $5–20 on duplicate work.

NEEDLE: the check asserts on the substring `open-PR query failed`. Chosen by the check-author and
recorded here because it is what the implementation must emit. Rejected `failed` / `error` as
vacuous (both already in the driver's vocabulary) and a full sentence as brittle.

AT FREEZE: **fails, 3 assertions**, with the driver's real output quoted:
- *selection names the open-PR query failure* — actual: `== select == | repo stub/repo: read 2
  open issues | SKIP #7 parked: … | ELIGIBLE #8 tier: …`. The needle is absent.
- *and exits non-zero* — actual: `0`.
- *and never invokes claude* — expected `0`, actual `1`.

Attributable: the fixture works. The issue list was served (`read 2 open issues`), tier filtering
ran (`#8` reached it), and the run completed. The failure is the driver treating the failed query
as an empty PR list, finding #8 unblocked, and spending a run.

NON-VACUITY of the zero-count clause: the check-author added argv logging to the `claude` stub
(the stub previously logged nothing, so a count of zero would have held unconditionally) and
appended a **control** case — same fixture, same flags, healthy `pr list`. The control **passes at
freeze** (`control: with a healthy query the same run DOES invoke claude`), which is what makes the
zero on the failing-query case mean something. If the stub ever stops logging, the control goes red
and exposes the zero-count check rather than letting it pass silently.

## C2

CRITERION: GIVEN the open-PR query fails during post-run PR discovery, WHEN the driver records the
run's outcome, THEN the recorded reason SHALL name the query failure AND SHALL NOT be the
`no PR opened` reason.

CHECK: a case whose stub fails `pr list` only at discovery — assert the `runs.jsonl` row's
`reason` names the query failure and is not the `no PR opened` string. Run by `make park-test`.

AT FREEZE: **fails, 2 assertions** (both directions, as the criterion requires):
- *the recorded reason names the query failure* — actual: `no PR opened; run's own account: stub
  run finished`. The needle is absent.
- *and is not the no-PR-opened reason* — actual: the same string, which contains `no PR opened`.

Attributable: a real `runs.jsonl` row was written and read back with `jq`, and its `reason` is
verbatim the string the criterion forbids. The fixture uses `--issue 7`, which bypasses selection,
so the only `fetch_open_prs` call in the run is the post-run discovery one at `:882` — "fails only
at discovery" is structural here, not stub bookkeeping.

## C3

CRITERION: WHEN the open-PR query fails, THEN `gh`'s stderr SHALL appear in the driver's output.

CHECK: the same fixture — assert the stub's distinctive stderr text appears in the captured
driver output. Run by `make park-test`. This asserts *runtime output*, not the presence of a
literal in the driver's source, so it is a test rather than a spelling check.

NEEDLE: the stub writes `stub-gh: HTTP 503 from api.github.com while listing PRs` to stderr.
Deliberately unlike anything the driver says on its own, so the check cannot be satisfied by a
driver diagnostic that merely mentions the query — only by `gh`'s stderr actually reaching the
output.

AT FREEZE: **fails, 1 assertion** — the needle is absent from the captured output.

Attributable: `run_driver` already merges stderr into stdout (`2>&1`), and the captured output
shows the run reached `== invoke #7 ==`, so the capture works. `fetch_open_prs`'s `2>/dev/null` is
what eats it. Same single-query fixture as C2, so the stderr could have come from nowhere else.

## Guards

(Pass today; must keep passing. Not criteria — they can't fail at freeze.)

- **G1.** The two matchers stay split, with their opposite error directions intact: a PR whose
  `closingIssuesReferences` names the issue still blocks selection, and the loose discovery matcher
  still matches a bare `#N`. CHECK: `make driver-test` and `make park-test` — no case lost, newly
  skipped, or newly failing.
- **G2.** `make assertion-lint` stays green — no new case may assert by grepping the driver for a
  literal. CHECK: `make check` exits 0.
- **G3.** On the success path nothing changes: `fetch_open_prs` still emits the parsed PR list and
  the existing park cases still pass unchanged. CHECK: `make park-test`.

**Guards at freeze — all three PASS, run and read individually (2026-07-31):**

- **G1** — `make driver-test`: `112 passed, 0 failed`. `make park-test`: all 21 pre-existing
  assertions pass, none lost or skipped (the 6 failures in that run are the new C1–C3 only).
- **G2** — `make assertion-lint`: `no presence-grep assertions in 2 file(s) matching
  driver/test-*.sh`.
- **G3** — the 21 pre-existing park assertions pass unchanged, including the whole
  harness-sanity section. That section passing is what makes the new failures attributable.

Also green at freeze, though not named as guards: `make driver-check`, `make docs-check`.

**One shared-helper change at freeze, called out because it touches an existing fixture.** The
`claude` stub in `make_stubs` gained one line: `printf 'claude %s\n' "$*" >> "$ARGV_LOG"`. Without
it C1's zero-invocations clause is vacuous. Safe because the `claude ` prefix is disjoint from every
gh needle any existing assertion uses (`issue list`, `issue edit N`, `--add-label`,
`--remove-label`), the two cases that read `$ARGV_LOG` with `hasnt`/`has_call` run `--classify-only`
(which never invokes claude), and it writes to a file rather than the stream the driver parses.
Empirically: all 21 pre-existing assertions still pass.

## Tamper rule for this run

`git diff <freeze-sha> -- driver/test-park-state.sh` must be empty from Phase 1 onward. No line
may change what any frozen check asserts — no case body, assertion, or helper the new cases
depend on. There is no sanctioned edit to this file after the freeze commit.

## Verification result (2026-07-31, independent verifier, fresh context)

Given only this manifest and the repo — not the plan, not the notes, no account of why any
failure might be acceptable.

- **C1** pass, 4/4 including the control · **C2** pass, 2/2 both directions · **C3** pass
- **G1** pass — `make driver-test` 112/0 (plus pytest 104), `make park-test` 28/0, no case lost,
  skipped or renamed · **G2** pass · **G3** pass, harness-sanity section 7/7
- **Tamper:** `git diff cc45871 -- driver/test-park-state.sh` → no output. **clean** (a real
  diff, not clean-by-substitute: `Check files` is non-empty here).
- `git diff cc45871 --stat` shows only `checks.md` (one line, the sha), `plan.md`, and
  `driver/agent-session-driver.sh`. No Makefile, script, or other test file touched.
- The freeze commit's own edit to the check file was **purely additive** — verified by
  `git diff 7cdd4a5 HEAD -- driver/test-park-state.sh | grep -E "^-"` returning only the diff
  header. Zero pre-existing lines deleted or modified.
- `make check`: `all checks passed`.

**Adversarial question 1 — is "never invokes claude" vacuous?** No, and the control is a real
guard rather than a claim. The only writer of a `^claude ` line is the stub's logging line; the
control runs the same fixture and flags with a healthy `pr list` and asserts `>= 1`, and it passes.
Remove the logging line and C1's zero-count would pass silently while the control would fail with
`at least 1 logged claude call (else the zero-count check above is vacuous)` — the vacuity
condition *is* the control's failure condition. Also: `run_driver` does `: > "$log"`, and a missing
log would yield an empty string, which `check "0" ""` treats as failure rather than pass.
*Verifier's own caveat, carried rather than dropped:* it could not build a mutant empirically —
bash was restricted in this session — so this rests on the control passing (observed) plus reading
the coupling in the source, not on an executed mutation.

**Adversarial question 2 — could C3 pass on a driver diagnostic instead of gh's real stderr?** No.
The needle originates only in the stub's `pr list` arm, and
`grep -n "stub-gh\|HTTP 503\|api.github.com" driver/agent-session-driver.sh` returns no matches, so
the driver cannot produce the string from its own vocabulary. The fixture uses `--issue`, so there
is exactly one query and one possible origin. Nuance the verifier stated: the check proves gh's
stderr *is not suppressed*, not that the driver labels or frames it — which is exactly what the
criterion says, so the check is faithful to it.

## Clarifications

(Logged per `frozen-checks.md`. A clarification changes no verdict at either tree; an amendment
would, and would cost the tier.)

- **2026-07-31 — the pre-existing park assertion count was recorded as 22; it is 21.** Found by
  the independent verifier. The baseline run at session start was `21 passed, 0 failed`; the freeze
  run was `22 passed, 6 failed` (28 total), so the new block adds **7** assertions, of which 6
  failed at freeze and one — the control — passed. The 22nd passing assertion at freeze *was* the
  new control, miscounted as pre-existing.

  **Why this is a clarification and not an amendment:** the number lived in the recorded evidence
  under `Guards at freeze`, never in a CHECK command. G1 and G3 are `make driver-test` /
  `make park-test` with the invariant "no case lost, newly skipped, or newly failing" — deliberately
  stated as an invariant rather than a count, for exactly this reason. Re-running the old and new
  wording against both the freeze tree and the current implementation changes no verdict at either.
  No tier change.

  The freeze commit message (`cc45871`) carries the same wrong number. History is immutable and
  rewriting it would collapse the tamper baseline, so it is corrected here and in the PR body
  rather than amended in place.

## Amendments

(Append-only. Empty unless an amendment was made.)

None. No frozen check was edited, relaxed, skipped, or narrowed after `cc45871`.
