# The live-orphan refusal also blocks --dry-run, which spends nothing

**Source:** https://github.com/lmorchard/agent-sessions/issues/51

The driver's live-orphan refusal also blocks `--dry-run`, which invokes no `claude` and spends
nothing.

Observed 2026-07-31 while a run on #47 was in flight:

```
$ make dry-run-self
WARNING: a previous run died before recording its outcome:
  issue #47  started 20260731T231127Z  run dir .../runs/47-20260731T231127Z
  ORPHAN STILL RUNNING (pid 98242, reparented) -- it is unsupervised and still spending.
error: refusing to start a second run while an orphan is live
make: *** [dry-run-self] Error 2
```

The run was healthy, not orphaned — it was launched in the background and reparented, which the
guard cannot distinguish from a host crash. That part is arguably fine. The problem is the scope of
the refusal.

## Why it matters

**It blocks the measurement `findings.md` mandates, exactly when you need it.** The operating rule for
judging a triage pass is:

> Judge a `triage` pass by the eligible count it produced, not by the issues it touched. Run the
> selection path (`make dry-run` / `make dry-run-self`) before and after and compare; **report it even
> when the answer is zero**.

A triage pass and a run routinely overlap — triaging the backlog while a run burns down an item is the
normal shape of a burndown session. For the whole 26 minutes of the #47 run, the prescribed
before/after comparison was unavailable, so the eligible count for #39's triage could not be reported
until the run finished.

## Why the refusal is right for `run` and wrong for `--dry-run`

The guard exists because two concurrent runs cannot share one `inflight.json`, and because a live
orphan is still spending money and mutating the repo. Neither applies to `--dry-run`:

- it makes no `claude` invocation, so it cannot spend and cannot collide on a budget;
- it writes nothing to the state dir (the same property `make watch` relies on);
- it creates no worktree and mutates no tree.

It reads GitHub and prints. The refusal is protecting nothing.

## Suggested shape (not a decision — needs intake)

Let the orphan check still *report* under `--dry-run` — the warning is useful, and suppressing it
would hide a genuinely dead run — but not refuse. The distinction to encode is **"this invocation can
spend or mutate"**, not "a run is in progress".

The discriminating check: with a fake live `inflight.json` in the state dir, `--dry-run` exits 0 and
prints the selection table, while a real `run` still exits non-zero. The `make_stubs` /
`run_driver` harness in `driver/test-park-state.sh` already builds exactly this situation — its C4
block writes state-dir fixtures and asserts on driver output — so the oracle is present.

~~Not triaged: no spec marker, so the board-driver will skip it until it goes through intake.~~

**Triaged 2026-08-01** — the marker now leads this body and the criteria are below.

---

## Verifiable acceptance criteria

- **C1.** GIVEN a state dir whose `inflight.json` names a **live** child pid, WHEN the driver is
  invoked with `--dry-run`, THEN it SHALL still print the orphan warning, complete selection, and
  exit 0.
  **CHECK:** a new case in `driver/test-park-state.sh` — a fixture state dir holding `inflight.json`
  and `runs/<n>/child.pid` with a live pid; assert exit status 0, the orphan warning present in the
  output, and at least one selection line printed.
  **DEMONSTRATED FAILING 2026-08-01**, with a control, both against a throwaway `--state-dir`:

  ```
  live orphan pid present:  --dry-run exit 2, 0 selection lines
  pid file removed:         --dry-run exit 0, "eligible: 1"
  ```

  The control is the load-bearing half — it shows the exit-2 is caused by the orphan marker and not by
  something incidental to the fixture.
  **ORACLE EXISTS NOW:** `make_stubs` and `run_driver` in `driver/test-park-state.sh` already build
  stub `gh`/`claude` binaries on a pinned `PATH` and already write state-dir fixtures (its C4 block
  does exactly this). Nothing to build.

## Regression guards

- **G1.** A real `run` against the same live-orphan fixture still exits non-zero **and never invokes
  `claude`**. **CHECK:** a park-test case asserting the argv log records zero `claude` invocations.
  **This is the guard that stops the fix being a deletion** — the cheapest way to green C1 is to
  remove the refusal, which would also silently re-open the two-concurrent-runs hazard the refusal
  exists for. Passes today.
- **G2.** `--classify-only` behaviour is unchanged: it still refuses while the orphan is live. Passes
  today, and see the decision below for why this is deliberate rather than an oversight.
- **G3.** The existing park cases pass unchanged — no case lost, newly skipped or renamed.
  **CHECK:** `make park-test`. Passes today (28 assertions as of 2026-08-01; the invariant is "none
  lost", not the number).

## Tier: auto-ok

**Trigger 1 does not fire.** C1 is an exit status plus two output assertions in an existing bash
fixture harness, demonstrated failing today with a control.

**Trigger 2 does not fire.** The work lands in `driver/agent-session-driver.sh` and
`driver/test-park-state.sh`, both drivable. Not `driver/gate.py`. The refusal being changed is a
startup precondition, not outcome classification or routing.

## Design decisions

- **Decision:** exempt `--dry-run` from the refusal; do **not** exempt `--classify-only`.
  - **Why:** the property that justifies the exemption is *"this invocation cannot spend or mutate"*,
    not *"a run is in progress"*. `--dry-run` makes no `claude` invocation, writes nothing to the
    state dir, and creates no worktree. `--classify-only` is different in kind: it derives an outcome
    from a run's live state, and a live run's state is still moving — the driver's own message already
    says *"Let it finish, then: `--classify-only N`"*, which is advice to wait, not a path it should
    open early.
  - **Rejected:** exempting both, which would let a run be classified while it is still writing the
    thing being classified.
- **Decision:** keep printing the warning under `--dry-run`.
  - **Why:** the warning is the useful half. Suppressing it would hide a genuinely dead run from the
    one command an operator is most likely to reach for while poking at state.

## What we're NOT doing

- **Changing how a live orphan is detected.** The reparented-pid check is what it is; the reason
  `--dry-run` hit this at all is that a backgrounded run is indistinguishable from a crashed one, and
  that is a separate question.
- **Making the refusal configurable.** A flag to override a safety refusal is how the refusal stops
  meaning anything.
