# plan

Turn a spec with verifiable criteria into an implementation plan, and **freeze the acceptance
checks** before any code is written.

Reads `references/frozen-checks.md` (the verification contract) and
`references/plan-template.md` (the skeleton). The plan is generated against *current* code —
never frozen at filing time, because the repo moves and planning against live code is what the
model is good at.

## Inputs

- A GitHub issue carrying `<!-- agent-session:spec -->` with criteria + checks + tier
- `spec.md` in the session directory (populated by session setup)
- The relevant source files

## Outputs

- `checks.md` — the frozen manifest, criteria + checks verbatim, ids assigned, freeze sha
- The acceptance tests those checks name, committed as the freeze commit
- `plan.md` — vertical-slice phases, each naming the criteria it advances, with verification
  checkboxes citing checks by their exact command

## Process

1. **Session setup if not already done.** If there's no worktree and session directory for
   this issue, run `references/session-setup.md` first. It also reads the tier, which the plan
   records and `execute`/`pr` route on.

2. **Gate on the spec.** Verify `spec.md` against the **Readiness checklist** in
   `references/spec-template.md`. The load-bearing item: *every criterion names a check.* If
   any criterion is bare prose, or the Tier section is missing, **stop and route to
   `intake`** — planning against unverifiable criteria produces a run nothing can grade.

3. **Read the relevant source files.** Start from the `file:line` refs in the spec (a snapshot
   from intake — verify they still point where they claim; the repo has moved since) and extend
   only where the plan needs more detail. For a large surface, dispatch a research subagent per
   `references/documentarian-prompt.md` so the reading stays in its context, not this one.

4. **Confirm each check's oracle still exists.** Intake verified this at filing time; time has
   passed. For each check, confirm the command/test/fixture it names is real and runnable
   *now* — grep or run it, don't assume. If an oracle has disappeared, that criterion is back
   to `needs-review`; say so and surface it rather than positing a replacement.

5. **Freeze the checks — this is Phase 0 of the plan.** Follow `references/frozen-checks.md`:
   write `checks.md` with ids `C1…Cn`, dispatch a check-author subagent to write the tests, run
   each one, confirm it **fails for the expected reason**, commit, record the sha. No
   implementation code in this phase.

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
