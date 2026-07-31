# Frozen acceptance checks

**Source:** https://github.com/lmorchard/agent-sessions/issues/42
**Frozen at:** (recorded in the follow-up commit)
**Check files — read-only from Phase 1 onward:**
- `scripts/test_run_progress.py`

Criteria and CHECK text are copied **verbatim** from the issue body.

## C1

CRITERION: GIVEN a `stream.jsonl`, WHEN the progress reporter runs over it, THEN it SHALL report the
assistant-turn count, the tool-call tally, the most recent assistant text, and the latest
`total_cost_usd`.

CHECK: `uv run pytest scripts/test_run_progress.py` — a fixture stream in pytest's `tmp_path`
with 3 assistant records (one carrying two `tool_use` blocks) and one `result` with
`total_cost_usd: 1.5`, asserting the reporter returns `turns == 3`, a tally of
`{"Bash": 2, "Read": 1}`, the third record's text, and `1.5`.

AT FREEZE: fails — `ModuleNotFoundError: No module named 'run_progress'` at collection, pytest
**exit 2** (collection error, distinct from exit 5 "collected nothing"). Correct reason: the
reporter genuinely does not exist. Tests carrying C1: `test_reports_turns_tools_last_text_and_cost`,
`test_latest_result_record_supplies_the_cost`.

## C2

CRITERION: GIVEN a `stream.jsonl` whose final line is a partial write, WHEN the reporter runs, THEN it
SHALL report every complete record and SHALL NOT raise.

CHECK: same test file — a fixture truncated mid-record, asserting the reporter returns the
complete records and does not raise.

AT FREEZE: fails — same `ModuleNotFoundError` collection error, exit 2. Test carrying C2:
`test_partial_final_line_reports_every_complete_record`.

The criterion's *condition* was separately re-demonstrated against a real stream at plan time
(`.driver-state/runs/710-20260727T201852Z/stream.jsonl` truncated to 200000 bytes):

```
naive  [json.loads(l) for l in open(f)]  -> RAISED JSONDecodeError:
                                            Unterminated string starting at: line 1 column 131
tolerant per-line try/except             -> parsed 103, skipped 1
```

## C3

CRITERION: GIVEN a run directory whose `stream.jsonl` is absent or empty, WHEN the reporter runs, THEN
it SHALL say so explicitly and SHALL NOT report zero turns as though the run were idle.

CHECK: same test file — an empty fixture and a missing-file fixture, asserting a distinguishable
"not started" result rather than `turns == 0`.

AT FREEZE: fails — same `ModuleNotFoundError` collection error, exit 2. Tests carrying C3:
`test_empty_stream_is_not_started`, `test_missing_stream_is_not_started`. The C1 test asserts
`started is True` as the positive control, so the flag is shown to discriminate rather than being
constant-`False`.

## Guards

(Pass today; must keep passing. Not criteria — they can't fail at freeze.)

- **G1:** the reporter never writes to the run directory or the state directory.
  CHECK: snapshot `find "$STATE_DIR" -newer <marker>` before and after; empty. Passes trivially
  today (nothing exists), so it is a guard on the implementation rather than a discriminator.
- **G2:** `bash driver/test-driver.sh` — no assertion lost, newly skipped or newly failing.
  Invariant, not a count. Passed at freeze (see evidence below).
- **G3:** `make check` stays green and `python3 scripts/docs_check.py` exits 0. Passed at freeze.
- **G4:** `make driver-check` — the driver still has no executable merge path. Passed at freeze.

### Guard evidence at freeze (baseline, commit 60161bd)

- G2/G3/G4: `make check` — **all checks passed**. `driver-test` reported `21 passed, 0 failed`;
  `docs-check`, `assertion-lint`, `driver-check`, `skill-readonly` all green.
- G1: no reporter exists yet, so nothing can write. Re-run against the shipped reporter.

## Amendments

(Append-only. Empty unless an amendment was made.)

## Clarifications

(Append-only. A clarification changes no verdict at either tree.)

## Tamper verdict

(Recorded before the push.)
