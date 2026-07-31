# Run-progress reader Implementation Plan

**Goal:** let an operator see that a run is progressing, while it is progressing, by digesting the
`stream.jsonl` the driver already writes.

**Source issue:** https://github.com/lmorchard/agent-sessions/issues/42 — **Tier:** `auto-ok`
(every criterion names specific assertions over fixture streams; the oracle is pytest, already wired
into `make gate-test`; the work lands in `scripts/` and the `Makefile`, both on CLAUDE.md's drivable
allowlist; nothing is written to GitHub).

**Approach:** a *reader*, not new instrumentation — the signal is already complete on disk, and
emitting progress from inside the run would let the run shape its own progress narrative. It lands as
`scripts/run_progress.py` (stdlib-only, so `python3` can run it the way `docs_check.py` is run) with a
`make watch` target, because tolerant JSON parsing plus a tally is a Python job and `scripts/` has the
cheapest available oracle.

**Criteria:** C1 report turns / tool tally / last assistant text / latest cost · C2 tolerate a
partial final line · C3 distinguish "not started" from "0 turns".
Full text + checks live in `checks.md`. Ids are assigned there and referenced here.

---

## Phase 0: Freeze the acceptance checks — DONE

Written per `references/frozen-checks.md`. No implementation in this phase.

**Files:**
- Create: `docs/dev-sessions/2026-07-31-1412-42-run-progress/checks.md` — criteria + checks copied
  verbatim from the issue, ids assigned
- Create: `scripts/test_run_progress.py` — the five tests C1…C3 name, authored by a subagent that was
  given the criteria and the measured record shape but **not** this plan

**Verification — automated:**
- [x] Every criterion's check runs and fails for the expected reason —
      `ModuleNotFoundError: No module named 'run_progress'` at collection, pytest **exit 2**
      (a collection error, distinct from exit 5 "collected nothing"). Recorded per criterion in
      `checks.md`.
- [x] Every guard runs and passes — `make check` green at `60161bd` (`driver-test` `21 passed,
      0 failed`; `driver-check`, `skill-readonly`, `docs-check`, `assertion-lint` all green).
- [x] Freeze commit made (`66aefa0`); sha recorded in `checks.md` in this follow-up commit.

---

## Phase 1: The reader — `scripts/run_progress.py`

The whole of C1, C2 and C3 in one module: parse a run directory's `stream.jsonl` tolerantly and
return a snapshot. This is the vertical slice — everything downstream (the CLI, `make watch`) is
presentation over this one function, and it is independently valuable because the frozen tests import
it directly.

**Advances:** C1, C2, C3 — completely. Phase 2 adds no new criterion coverage.

**Files:**
- Create: `scripts/run_progress.py`

**Key changes:**

- `@dataclass class Progress` — the snapshot the frozen tests destructure by attribute:
  `started: bool`, `turns: int`, `tools: Counter`, `last_text: str | None`,
  `cost_usd: float | None`, `skipped: int`, `records: int`, `duration_ms: int | None`,
  `is_error: bool | None`, `run_dir: Path`.
- `read_records(path: Path) -> tuple[list[dict], int]` — tolerant per-line parse; returns the
  complete records and the count of unparseable lines.
- `read_progress(run_dir: Path) -> Progress` — the frozen tests' entry point.

The load-bearing detail is C2's: a live `stream.jsonl` is *normally* truncated mid-record, because the
reader opens it between the writer's two `write()` calls. Measured at plan time against a real stream
truncated to 200000 bytes: naive `[json.loads(l) for l in open(f)]` raises `JSONDecodeError`, while a
per-line `try/except` parses 103 and skips 1.

```python
def read_records(path):
    """Parse every complete record; count the ones that aren't.

    A stream being appended to has a partial final line more often than not, so
    a reader that raises on it is a reader that dies exactly when it is wanted.
    """
    records, skipped = [], 0
    try:
        text = path.read_text(errors="replace")
    except FileNotFoundError:
        return [], 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except ValueError:
            skipped += 1
    return records, skipped
```

C3's shape, stated as the invariant the criterion asks for — `started` is `False` iff there are no
complete records, so "hasn't written anything yet" can never render as "idle at 0 turns":

```python
def read_progress(run_dir):
    records, skipped = read_records(Path(run_dir) / "stream.jsonl")
    turns = tools = last_text = cost = None  # filled below
    ...
    return Progress(started=bool(records), turns=turns, tools=tools, ...)
```

Per-record extraction, matching the shapes measured off a live stream:

- a turn is a record with `type == "assistant"`;
- `message.content` is a list of blocks; `{"type": "tool_use", "name": N}` increments `tools[N]`;
  `{"type": "text", "text": T}` updates `last_text` (**most recent text block**, not most recent
  record — the frozen C1 fixture's middle record has tool calls and no text, so the two differ);
- `cost_usd` is the **last** `type == "result"` record's `total_cost_usd`; real streams carry more
  than one, which is what "latest" in C1 is about. Same for `duration_ms` and `is_error`.

Every read is `.get()`-guarded: a record whose `message` is absent or whose `content` is a bare string
must not raise, for the same reason C2 exists.

**Verification — automated:**
- [ ] C1's check passes: `uv run pytest scripts/test_run_progress.py`
- [ ] C2's check passes: same command (`test_partial_final_line_reports_every_complete_record`)
- [ ] C3's check passes: same command (`test_empty_stream_is_not_started`,
      `test_missing_stream_is_not_started`)
- [ ] The run collected 5 tests and exited 0 — **not** exit 5. Record the collected/passed count.
- [ ] Guards still pass: `make check`, `bash driver/test-driver.sh`, `make driver-check`,
      `python3 scripts/docs_check.py`

**Verification — manual:**
- None. Every criterion here is a runnable check; that is why the tier is `auto-ok`.

---

## Phase 2: The operator surface — CLI, `make watch`, and wiring the test into `make check`

The reader is useless to an operator until something calls it on a loop and prints a digest. This
phase adds no criterion coverage; it delivers the thing the issue actually asked for, and it puts the
frozen tests inside `make check` so they cannot silently stop running.

**Advances:** C1, C2, C3 — indirectly, by making them reachable from the command line. No new
criterion. (Phase 1 is where they are *graded*; this phase must not change their verdict, which the
tamper diff and a re-run confirm.)

**Files:**
- Modify: `scripts/run_progress.py` — add `format_progress()`, `find_latest_run()`, `main()`
- Modify: `Makefile` — add a `watch` target and its `help` line; add `scripts/test_run_progress.py`
  to the `gate-test` recipe

**Key changes:**

- `find_latest_run(state_dir: Path) -> Path | None` — newest child of `state_dir/runs` by mtime.
- `default_state_dir(repo: str) -> Path` — **must mirror the driver, not the spec's example path.**
  The spec quotes `.driver-state/runs/...`, which #27 superseded: `agent-session-driver.sh:347`
  now derives `${XDG_STATE_HOME:-$HOME/.local/state}/agent-session/${REPO//\//-}`. Reimplementing the
  spec's stale path would point `make watch` at a directory the driver no longer writes.
- `format_progress(p: Progress) -> str` — a fixed-width digest, no cursor control and no spinner
  (the spec rules out anything that assumes a terminal; these runs are backgrounded and read from a
  log). Not started renders as its own line, never as `0 turns`:

```
run 42-20260731T191200Z   not started -- no stream.jsonl yet
run 42-20260731T191200Z   turns 37   $4.21   4m12s
  tools  Bash 31  Read 22  Edit 9  Grep 4
  last   Now running the frozen acceptance tests against the new reader...
```

- `main()` — `argparse`: optional positional `RUNDIR`; `--state-dir DIR`; `--repo OWNER/NAME`;
  `--watch`; `--interval SECONDS` (default `10`, the spec's stated default). Resolution order:
  explicit `RUNDIR` → `--state-dir`'s newest run → `--repo`'s derived state dir's newest run.
  `--watch` re-reads and reprints on the interval; without it, one digest and exit.
- Elapsed time comes from the `result` record's `duration_ms` when present, else from the run
  directory's `NN-YYYYMMDDTHHMMSSZ` suffix — **never from file `ctime`**, which updates on every
  write and always reads ~0. The spec calls this out because it was got wrong once already.
- Makefile:

```make
# `run` / `run-self` print nothing between "== invoke #N ==" and the exit line;
# a 50-minute run was a black box with 2.4 MB of live signal on disk. This is a
# reader over that signal -- it never writes to the state dir. See issue #42.
# Pass REPO= to watch a different repo's runs, e.g. REPO=lmorchard/agent-sessions.
watch:
	@python3 scripts/run_progress.py --repo $(REPO) --watch --interval $(INTERVAL)
```

with `INTERVAL ?= 10` and a `help` line, and `gate-test` extended to
`uv run --quiet pytest driver/test_gate.py scripts/test_docs_check.py scripts/test_run_progress.py`.

**Scope discipline — deliberately NOT in this phase**, per the spec's "What we're NOT doing" and its
open questions: no `--follow` flag in the driver, no driver-side heartbeat, no change to what the
driver prints on completion, no TUI or spinner, no tail of the full stream.

**Verification — automated:**
- [ ] C1/C2/C3's check still passes after the additions: `uv run pytest
      scripts/test_run_progress.py`, 5 collected, exit 0
- [ ] `make gate-test` runs the new file (its collected count rises by 5)
- [ ] `make check` green
- [ ] G1, by its own command: snapshot the state dir with `find` before and after a
      `run_progress.py` invocation against a real run directory; the newer-than-marker set is empty
- [ ] `python3 scripts/run_progress.py <a real run dir>` prints a digest with a non-zero turn count
      (proves it works on a real 1 MB+ stream, not only on fixtures)
- [ ] `python3 scripts/run_progress.py <an empty temp dir>` prints the not-started line, not `0 turns`

**Verification — manual:**
- None required. The digest's exact wording is not a criterion, and the spec explicitly declines to
  make "feel" part of this issue.
