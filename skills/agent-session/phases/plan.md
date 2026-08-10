# plan

Turn a spec with verifiable criteria into an implementation plan, and **freeze the acceptance
checks** before any code is written.

Reads `references/frozen-checks.md` (the verification contract) and
`references/plan-template.md` (the skeleton). The plan is generated against *current* code —
never frozen at filing time, because the repo moves and planning against live code is what the
model is good at.

## Inputs

- A GitHub issue carrying the `agent-session:spec` label with criteria + checks + tier
- `spec.md` in the session directory (populated by session setup)
- The relevant source files

## Outputs

- `checks.md` — the frozen manifest, criteria + checks verbatim, ids assigned, freeze sha
- The acceptance tests those checks name, committed as the freeze commit
- `plan.md` — vertical-slice phases, each naming the criteria it advances, with verification
  checkboxes citing checks by their exact command

## Process

0. **Check Ceremony Threshold:** If this is a small, tactical task (bug fix, < 3 steps), **skip `plan.md` and `checks.md` entirely**. Proceed directly to implementing the fix in-context (or use the `todowrite` tool) and move to the `pr` phase once tests pass. Only proceed with the steps below for large, architectural, or multi-session tasks.

1. **Session setup if not already done.** If there's no worktree and session directory for
   this issue, run `references/session-setup.md` first. It also reads the tier, which the plan
   records and `execute`/`pr` route on.

2. **Gate on the spec.** Verify `spec.md` against the **Readiness checklist** in
   `references/spec-template.md`. The load-bearing item: *every criterion names a check.* If
   any criterion is bare prose, or the Tier section is missing, **stop and route to
   `intake`** — planning against unverifiable criteria produces a run nothing can grade.

   Use the checklist's *augmented existing issue* variant when `spec.md` came from an issue
   augmented in place rather than one written to the template; missing template sections aren't
   failures there, missing criteria still are.

3. **Read the relevant source files.** Start from the `file:line` refs in the spec (a snapshot
   from intake — verify they still point where they claim; the repo has moved since) and extend
   only where the plan needs more detail. For a large surface, dispatch a research subagent per
   `references/documentarian-prompt.md` so the reading stays in its context, not this one.

4. **Re-confirm the spec's own evidence still holds.** Intake demonstrated each criterion's
   condition failing, using whatever was runnable *at filing time* — a repro script, an existing
   test's output, a grep count. Time has passed and the repo has moved, so re-run those
   demonstrations. This is not the acceptance tests (step 5 writes those); it's checking that the
   gap the issue describes is still there.
   - A criterion whose condition no longer holds → the behavior arrived, or it was a guard
     misfiled as a criterion. Surface it; don't posit a replacement.
   - A guard that now fails → a pre-existing break. Surface it *before* implementing, or you'll
     mistake it for your own regression at the gate.
   - An oracle that has disappeared → that criterion is back to `needs-review`.

5. **Freeze the checks — this is Phase 0 of the plan.** Now the acceptance tests get *authored*,
   which is why step 4 couldn't have run them. Follow `references/frozen-checks.md`: write
   `checks.md` with ids `C1…Cn`, dispatch a check-author subagent to write the tests, run each
   one, confirm it **fails for the expected reason**, dispatch a read-only **check-reviewer**
   subagent and record one disposition per check **and per guard** under `## Adjudication`, then
   commit and record the sha in a follow-up commit. No implementation code in this phase.

   The reviewer runs *before* the freeze commit, and is given `checks.md` and the repo but never
   this plan or the criteria's rationale. It is the last point at which a weak check is cheap to
   fix: after the commit the read-only rule governs and the same fix costs an amendment and the
   tier. Don't write the rest of the plan first and review the checks on the way past.

   Do this before writing the rest of the plan, not after. A check authored after the
   implementation approach is settled tends to test the approach instead of the criterion.

6. **Vertical slices.** Break the work into phases that each cross all relevant layers (data,
   logic, interface, tests) for one piece of end-to-end functionality — not a horizontal
   "all migrations, then all handlers." Earlier slices establish foundations later ones build
   on; if slice N fails, slices 1..N-1 should still be independently valuable.

7. **Map each slice to criteria.** Every phase names which `Cn` it advances. This is the
   traceability that makes coverage checkable in step 10 instead of asserted.

8. **TDD by default** for each slice's own unit tests: failing test first, then the code.
   Document opt-outs explicitly (pure refactor, docs, scaffolding without behavior). Note that
   the frozen acceptance tests already exist from Phase 0 — a slice's unit tests are additional
   and editable; the frozen ones are not.

9. **Write `plan.md`** to `references/plan-template.md`. Scope discipline: only what the spec
   describes. No drive-by refactoring, no "while we're here" cleanup even where the code is
   obviously messy — note those separately for a future session. No placeholders ("TBD", "add
   appropriate error handling" without showing how, references to types no phase defines).

10. **Plan self-review:**
    - **Criteria coverage, both directions.** Every `Cn` in `checks.md` appears in some phase's
      **Advances**; every phase advances at least one `Cn`. A criterion no phase advances is a
      hole; a phase advancing nothing is scope creep or a missing criterion — resolve which.
    - **Checks cited by command.** Each phase's automated checkboxes name the exact command
      from `checks.md`, not "tests pass."
    - **Placeholder scan** per step 9.
    - **Type consistency.** Do signatures and names in later phases match what earlier phases
      defined? `clearLayers()` in phase 3 and `clearFullLayers()` in phase 7 is a bug.

    Fix issues inline. Present findings before human review — interactive: wait for approval;
    `express`: fix and continue.

## When to go back

- Spec fails the readiness gate, or a criterion's oracle no longer exists → `intake`.
- A check passes at freeze → the behavior already exists; surface it. The issue may be stale,
  or the check may not test its criterion.
- Writing the plan reveals a missing load-bearing decision → stop and surface it. Don't guess;
  the spec's Open questions were supposed to carry defaults for exactly this.
- A phase can't be a vertical slice because it genuinely depends on infrastructure that
  doesn't exist → surface before writing more.

When stopping or surfacing due to any of the above:
1. **Post a top-level comment on the GitHub issue** using `gh issue comment <issue_number> --body "<text>"` explaining plainly what needs a decision, why, and what choices exist.
2. **Apply the parking label** using `python3 scripts/label_manager.py park --issue <issue_number>`.
3. Stop and report the parked outcome.
