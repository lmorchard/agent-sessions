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

- **G1** — `make driver-test`: `112 passed, 0 failed`. `make park-test`: all 22 pre-existing
  assertions pass, none lost or skipped (the 6 failures in that run are the new C1–C3 only).
- **G2** — `make assertion-lint`: `no presence-grep assertions in 2 file(s) matching
  driver/test-*.sh`.
- **G3** — the 22 pre-existing park assertions pass unchanged, including the whole
  harness-sanity section. That section passing is what makes the new failures attributable.

Also green at freeze, though not named as guards: `make driver-check`, `make docs-check`.

**One shared-helper change at freeze, called out because it touches an existing fixture.** The
`claude` stub in `make_stubs` gained one line: `printf 'claude %s\n' "$*" >> "$ARGV_LOG"`. Without
it C1's zero-invocations clause is vacuous. Safe because the `claude ` prefix is disjoint from every
gh needle any existing assertion uses (`issue list`, `issue edit N`, `--add-label`,
`--remove-label`), the two cases that read `$ARGV_LOG` with `hasnt`/`has_call` run `--classify-only`
(which never invokes claude), and it writes to a file rather than the stream the driver parses.
Empirically: all 22 pre-existing assertions still pass.

## Tamper rule for this run

`git diff <freeze-sha> -- driver/test-park-state.sh` must be empty from Phase 1 onward. No line
may change what any frozen check asserts — no case body, assertion, or helper the new cases
depend on. There is no sanctioned edit to this file after the freeze commit.

## Amendments

(Append-only. Empty unless an amendment was made.)
