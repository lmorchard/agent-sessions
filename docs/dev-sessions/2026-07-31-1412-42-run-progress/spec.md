<!-- agent-session:spec -->

**Goal:** let an operator see that a run is progressing, while it is progressing. Today a run is a
black box from the moment it starts until it ends.

**Source:** Les, 2026-07-31, mid-burndown: *"this process is very light on progress indications."*
Issue: https://github.com/lmorchard/agent-sessions/issues/42

## Current state — measured on a real run

The #28 run, from its own artifacts:

| | |
|---|---|
| duration | **50 minutes** |
| `stream.jsonl` written | **2388 KB**, 1156 records, 355 assistant turns |
| operator-visible progress lines during that time | **0** |

Everything the driver prints between starting and finishing:

```
== invoke #28 ==
  issue    https://github.com/lmorchard/agent-sessions/issues/28
  cwd      /Users/lorchard/devel/agent-sessions
  budget   $25   timeout 5400s
  run dir  .../.driver-state/runs/28-20260731T164741Z
  DENIALS (4) -- see .../denials.txt          <- printed AFTER the run ends
  exit 0   cost $19.92...
```

`grep -cE 'watch|follow|tail' Makefile` → **0**; there is no `watch` or `follow` target and no
`--follow` flag.

**The data was there the whole time.** `claude -p --output-format stream-json` writes the stream live,
and every useful signal is already in it — `type=="assistant"` records for turns and `tool_use` names,
`type=="result"` for `total_cost_usd`, and the assistant `text` blocks say what the run believes it is
doing. Nothing needs to be captured that isn't already on disk. **The gap is presentation, not
instrumentation**, which is what makes this small.

## Verifiable acceptance criteria

- **C1.** GIVEN a `stream.jsonl`, WHEN the progress reporter runs over it, THEN it SHALL report the
  assistant-turn count, the tool-call tally, the most recent assistant text, and the latest
  `total_cost_usd`.
  **CHECK:** `uv run pytest scripts/test_run_progress.py` — a fixture stream in pytest's `tmp_path`
  with 3 assistant records (one carrying two `tool_use` blocks) and one `result` with
  `total_cost_usd: 1.5`, asserting the reporter returns `turns == 3`, a tally of
  `{"Bash": 2, "Read": 1}`, the third record's text, and `1.5`. The criterion names the assertions, so
  the check grades content rather than existence — `acceptance-criteria.md`'s "the work IS the oracle"
  hard case.
  **DEMONSTRATED FAILING:** no such module exists, **and** the real demonstration is the table above —
  a 50-minute run with 2388 KB of live signal and zero progress output. `no tests ran` is deliberately
  *not* offered as the demonstration, per `acceptance-criteria.md`'s named-but-absent row.
  **ORACLE EXISTS NOW:** `scripts/test_docs_check.py:19-36` is the pattern to copy — it imports the
  module under test, builds throwaway trees in `tmp_path`, and is already run by `Makefile:50`.

- **C2.** GIVEN a `stream.jsonl` whose final line is a partial write, WHEN the reporter runs, THEN it
  SHALL report every complete record and SHALL NOT raise.
  **CHECK:** same test file — a fixture truncated mid-record, asserting the reporter returns the
  complete records and does not raise.
  **DEMONSTRATED FAILING, and this is the one that matters:** a live stream's last line is *normally*
  a partial write, so the obvious implementation is wrong in the common case. Truncating a real
  `stream.jsonl` at 200000 bytes and reading it the naive way:
  ```
  naive  [json.loads(l) for l in open(f)]  -> RAISED JSONDecodeError:
                                              Unterminated string starting at line 1 column 7071
  tolerant per-line try/except             -> parsed 102, skipped 1 incomplete
  ```
  Any reporter that dies the moment you point it at a running job is worse than none.

- **C3.** GIVEN a run directory whose `stream.jsonl` is absent or empty, WHEN the reporter runs, THEN
  it SHALL say so explicitly and SHALL NOT report zero turns as though the run were idle.
  **CHECK:** same test file — an empty fixture and a missing-file fixture, asserting a distinguishable
  "not started" result rather than `turns == 0`.
  **DEMONSTRATED FAILING:** no reporter exists. **Why it is a criterion and not a nicety:** `0 turns,
  $0.00` and "the run has not written anything yet" are the same display and opposite situations — one
  is a hang worth killing, the other is a normal first few seconds. That is `docs/findings.md` defect
  class 2, *a null must never render as a positive*, which this repo has now hit six times; writing
  the sixth-instance shape into a new file on purpose would be careless.

## Regression guards

- **G1.** The reporter never writes to the run directory or the state directory. It is a reader, and a
  watcher that mutates the thing it watches would corrupt the record the driver depends on.
  **CHECK:** snapshot `find "$STATE_DIR" -newer <marker>` before and after; empty. Passes trivially
  today (nothing exists), so it is a guard on the implementation rather than a discriminator.
- **G2.** The driver's own behaviour and output are unchanged when nothing is watching. This is
  additive; `make run` / `make run-self` must not gain a new failure mode.
  **CHECK:** `bash driver/test-driver.sh` — no assertion lost, newly skipped or newly failing.
  Invariant, not a count. Passes today.
- **G3.** `make check` stays green and `python3 scripts/docs_check.py` exits 0. Passes today.
- **G4.** `make driver-check` — the driver still has no executable merge path. Passes today.

## Tier: `auto-ok`

**Trigger 1 does not fire.** Every criterion names specific assertions over fixture streams; the
oracle is pytest, already wired into `Makefile:50`, with two in-repo precedents
(`scripts/test_docs_check.py`, and `scripts/test_assertion_lint.py` from #28). C2's failure mode was
reproduced against a real stream rather than reasoned about.

**Trigger 2 does not fire.** The work lands in `scripts/` and `Makefile`, both on `CLAUDE.md`'s
drivable allowlist, plus optionally a `--follow` flag in `driver/agent-session-driver.sh` (also
drivable). Not `driver/gate.py`, not `skills/**`. No auth, secrets, data migration/deletion,
deploy/infra/CI config or dependency change. **It writes nothing to GitHub at all.**

## Design decisions

- **Decision:** a reader over `stream.jsonl`, not new instrumentation in the driver.
  - **Why:** the signal is already on disk and complete. Adding emission points inside the run would
    couple the driver to the skill's phase structure and give the run a way to shape its own progress
    narrative — a small version of the implementer authoring its own oracle.
  - **Rejected:** having the skill emit progress markers the driver greps for.

- **Decision:** land it as `scripts/run_progress.py` with a `make watch` target, not as a shell loop
  inside the driver.
  - **Why:** it needs tolerant JSON parsing and a tally, which is a Python job; and `scripts/` has the
    cheapest available oracle — two working precedents that import the module and use `tmp_path`.
    A bash version would end up tested by the presence-grep shape #28 exists to remove.
  - **Rejected:** a `tail -f | jq` recipe. Fine as a one-liner, untestable as a deliverable.

- **Decision:** default to the newest run directory when none is given.
  - **Why:** the common case is "the run I just started," and requiring the operator to paste a
    timestamped path is most of the friction this issue is about.

## What we're NOT doing

- **Live-streaming the run's full output.** The stream is 2.4 MB for one run; the deliverable is a
  digest, not a tail.
- **Changing what the driver prints on completion.** The end-of-run summary is fine; the gap is the
  middle.
- **A TUI, a spinner, or anything that assumes a terminal.** These runs are backgrounded and their
  output is read from a log after the fact as often as live.
- **Making the driver poll and print by itself.** See Open questions — it is the more useful shape and
  a bigger change, so it is deliberately separable.

## Open questions

- **Should `--follow` also make the driver print a heartbeat itself**, so an unwatched background run
  leaves progress in its own log rather than requiring a second process? **Default:** ship the reader
  and `make watch` first; add the flag only if the reader proves useful, since the reader is what the
  flag would have to call anyway.
- **What cadence should `make watch` poll at?** **Default:** every 10 seconds. Cheap — it stats one
  file — and the underlying turns arrive far slower than that.
- **Should it report elapsed time?** Yes, but **not from file `ctime`** — that updates on every write
  and always reads ~0, which I got wrong while investigating this. Use the `result` record's
  `duration_ms`, or the run directory's timestamped name.
