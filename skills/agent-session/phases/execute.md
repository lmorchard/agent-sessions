# execute

Execute the plan phase by phase. **Done means every criterion's check passes** — verified by a
context that didn't write the code.

Reads `references/frozen-checks.md` — the read-only rule, the verifier, the tamper check, and
the amendment path all live there.

## Inputs

- `plan.md` — primary working document
- `checks.md` — the frozen manifest; the definition of done
- `spec.md` — for grounding
- The files each phase references

## Outputs

- Code changes implemented per phase, one commit per phase (`Phase N: <name>`)
- `plan.md` with ticked `- [x]` checkboxes, each ticked from observed output
- An independent verifier report: per-criterion pass/fail + the tamper diff
- Evidence collected for any human-judgment criterion
- `notes.md` entries for anything surfaced (adaptations, amendments, deferrals)

## Preferred mode: subagent-driven

If `superpowers:subagent-driven-development` is available, invoke it — a fresh subagent per
phase with two-stage review (spec compliance, then code quality), context isolated per task.
Fall back to inline only when the skill is unavailable or the user asks for inline.

**When dispatching any implementer subagent, state the frozen check files by path and that they
are read-only.** A subagent that doesn't know a file is frozen will treat a failing assertion
in it as ordinary test maintenance. Tell it that a failing frozen check is a report-back, not a
fix-up.

## Process

0. **Check Ceremony Threshold:** If this is a small, tactical task (bug fix, < 3 steps), **skip `execute`'s heavy phased structure entirely**. Just implement the fix and jump to `pr`. Only proceed with the steps below for large, architectural, or multi-session tasks that have a `plan.md`.

**TDD Inner Loop (Fail-Implement-Pass):** For each micro-task, enforce strict fail-implement-pass TDD inner loop discipline. Before writing implementation code, run the failing check and observe failure. Then implement, run the check again to confirm pass, and tick the micro-task checkbox.

**Parallel Swarm & Tiered Model Routing:** For independent micro-tasks defined in parallel groups:
1. **Prepare Prompt Files:** Prior to dispatch, write a dedicated prompt file for each subagent (e.g. `runs/task_1_prompt.txt`, `runs/task_2_prompt.txt`). Each prompt specifies:
   - Target file(s) and micro-task description.
   - The exact check/test command to run first to observe failure (TDD inner loop).
   - Frozen check file rules (read-only).

2. **Execute Deterministic Swarm Orchestration:** Invoke `scripts/run_swarm.py` with the task prompt files:
```bash
python3 scripts/run_swarm.py runs/task_1_prompt.txt runs/task_2_prompt.txt
```
Or specify a JSON tasks manifest file (`runs/swarm_tasks.json`) if custom task checks or stream outputs are configured:
```bash
python3 scripts/run_swarm.py --tasks-file runs/swarm_tasks.json
```
The deterministic runner (`scripts/run_swarm.py`) concurrently dispatches parallel `implementer` subagents via `agent_runner.py --tier low` (enforcing low-tier model execution like Claude 3.5 Haiku while reserving the high-tier model for intake, planning, and verification), monitors process PIDs, checks exit codes, validates TDD stream compliance (`scripts/validate_tdd.py`), and reports aggregated pass/fail results without an LLM Commander. Ensure parallel groups contain strictly independent files or functions to avoid git merge conflicts.

1. **Load and review.** Read `plan.md`, `checks.md`, and `spec.md`. Confirm the freeze commit
   exists (`checks.md`'s `Frozen at` sha resolves) — if it doesn't, Phase 0 never happened;
   go back to `plan`. Check existing checkboxes and resume from the first unchecked phase.

2. **For each phase:**
   - Read every file the phase references before changing anything.
   - **Test-first** for the phase's own unit tests: write them, watch them fail, then implement.
     The frozen acceptance tests already exist from Phase 0 — you're making them pass, not
     writing them.
   - Implement per the plan's intent. If the codebase has diverged in a way the plan didn't
     anticipate, **surface the mismatch** rather than silently improvising.
   - **Run each check the phase advances, by name, and read its output.** Use the exact command
     from `checks.md` — `pytest tests/test_export.py::test_large_export_is_streamed`, not `make
     test`. Then run the **guards** from `checks.md` and `make lint` / `make typecheck` / `make check`
     for regressions. Run project linters (`ruff check`, `eslint`, `npm run lint`) and typecheckers
     (`pyright`, `tsc`) locally before committing to prevent CI lint/type failures. A guard or linter that
     flips pass→fail is a regression you just caused; fix it before moving on, and never by weakening the guard.
   - Tick `- [ ]` → `- [x]` only after reading the actual output of that specific command.
     Never from an impression that it should pass.
   - **A failing frozen check means the implementation is wrong.** Fix the code. Do not edit,
     relax, skip, xfail, or narrow the check. If the check genuinely fails to test its own
     criterion, that's a **STOP** — follow the amendment path in
     `references/frozen-checks.md` (surface it, get confirmation, log it, tier drops to
     `needs-review`). Never resolve it inline.
   - **Pre-commit `git status`.** Confirm every file the phase meant to touch is staged and nothing
     unexpected is — an unstaged rename lands a stale file while the working tree still tests green.
   - Commit as one commit (`Phase N: <name>`) — keeps phases independently revertable.
   - Manual verification items: interactive mode waits for confirmation; `express` collects the
     evidence and defers the human pause per its tier rules.

3. **Collect evidence for human-judgment criteria.** For each criterion in `checks.md` with no
   check, produce the `EVIDENCE TO PRESENT` it names (the recording, the sample output, the
   before/after). This is what a human grades at the gate — a criterion whose evidence was
   never produced is not "pending review," it's unverified.

4. **Independent verification (the gate).** Once all phases are done, dispatch a **verifier
   subagent** with a fresh context per `references/frozen-checks.md`: give it `checks.md` and
   the repo, and nothing else — not the plan, not your notes, not any account of why a failure
   might be acceptable. It runs every check *and every guard* by name, reports observed output
   and pass/fail for each, and runs the tamper diff.

   Then confirm the gate per `references/frozen-checks.md`: every check passed per *its* report,
   the tamper diff is empty (or fully explained by logged amendments), and the project's own
   gates are green. Aggregate green is not the gate.

5. **Scope discipline.** Only what the plan describes. Don't refactor adjacent code, however
   messy. Note anything worth fixing in `notes.md` for a future session.

6. **Do not push.** `pr` handles remote.

## When to skip

- No `plan.md`, or no freeze commit → run `plan` first; don't improvise.
- A single trivial edit → skip the *phase machinery* (per-phase commits, slice unit tests, a
  subagent per phase) and make the edit directly. **Step 4's independent verification is not part
  of what you skip**, and neither are the guards. A one-line diff is the case where self-reporting
  feels most obviously harmless, which is why it's the case where the habit forms. Most issues an
  unattended loop picks up are this size.

## Resuming after context reset

- **Verify the working directory.** `pwd` — confirm you're inside the session's worktree (whatever location the project uses; see
  `references/session-setup.md`). Running tests or commits from the main checkout hits the wrong
  branch.
- Read `plan.md` (ticked boxes = done) and `checks.md` (the definition of done).
- **Re-run the last completed phase's checks.** Trust completed work only after fresh evidence.
  Also re-run the tamper diff — a reset is exactly when an unlogged check edit goes unnoticed.
- Pick up from the first unchecked item.

## When to go back

Small plan/codebase mismatches: adapt, continue, note the adaptation. Fundamental problems —
wrong API, missing dependency, structurally wrong approach — stop and re-open `plan`, or
`intake` if the spec itself is wrong. Don't paper over a bad foundation with on-the-fly
rewrites; the frozen checks will fail honestly and you'll be tempted to blame them.
