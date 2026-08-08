# intake

Interview a request into a spec with **verifiable acceptance criteria** and a **tier
label**, then file (or update) the GitHub issue. This is the human-in-the-loop front end —
intent capture and criteria judgment are human work; everything downstream trusts what this
produces.

Reads the shared engine: `references/acceptance-criteria.md`, `references/criteria-grammar.md`,
`references/spec-template.md`, and reads `docs/agent-ledger.md` (if it exists) as a source of architectural continuity. Dispatches research per `references/documentarian-prompt.md`.

## Two entry modes

Determined by input, like `dev-session` brainstorm's blank-slate/refine split:

- **New request** (a prompt, or an empty/sketch issue) → develop a spec from scratch.
- **Existing issue** (URL given, issue has a body but no `agent-session:spec` label, or is under-specified) → *augment* it: read what's there, keep the author's
  intent, backfill the missing criteria + tier. This is the mode `triage` drives per issue.

If the issue already carries the label, it's already specified — confirm it still holds
and stop; don't re-interview. (An issue that went `needs-review` for a *withheld decision* is the
exception, and needs no rule here: `acceptance-criteria.md`'s trigger 1 already names that case, and
5/5 control reps navigated it from the tier rules alone — see the micro-test in `docs/design.md`.)

## Process

1. **Read the source thoroughly** (prompt or issue body).

2. **Codebase research substep** (skip only for changes so localized context is obvious).
   **Dispatch 3–5 parallel, read-only documentarian subagents** (`Explore`/`general-purpose` in parallel) framed per `references/documentarian-prompt.md` (describe what exists, cite `file:line`, answer only what's asked). Ask 3–5 *neutral* questions about how the relevant area works today — **including, for each thing the requirement will need to check, whether that oracle exists today** (the metric / test / harness / way to reproduce the scenario). This grounds step 4's criteria in reality and its tier in what's actually checkable, and keeps the token-heavy reading in the subagents' contexts, not here.

   **Synthesize the findings:** Before starting the interview, parse and merge the results from the parallel subagents. Propose a "Discovery Report" mapping out found oracles/files, and proactively propose 3–5 concrete, runnable checks directly to the user to reduce their cognitive load.

3. **Interview — clarify / probe / finish, one question at a time.** Ground every question in the synthesized research and the proposed checks. **Propose your best answer with its trade-off; ask to confirm or adjust** — never open-ended when you have a recommendation. Multiple-choice preferred. Keep proportional to complexity (2–4 questions for small issues).

4. **Reduce each requirement to a verifiable criterion** per `acceptance-criteria.md`. This
   is the load-bearing step and the interview's real job: for each thing the user wants,
   **propose the criterion in EARS/Given-When-Then AND propose its runnable check**, then
   have them ratify. When a criterion won't reduce to a concrete test, walk the escalation
   ladder aloud (property? else human-judgment?) so the user sees *why* it lands where it
   does. The standing follow-up whenever an answer stays vague: *"how would we actually
   know — what command or test proves that?"*

5. **Demonstrate that each criterion's condition fails today.** Not "assert that it does" — show
   it, with a command you actually ran, and record the output.

   **You are proving the behavior is absent, not running the final acceptance test.** That test
   often doesn't exist yet, and by design it isn't written until `plan`'s freeze phase — so use
   whatever runnable means demonstrates the gap *now*: a throwaway reproduction script, the
   output of an existing test, a `grep -c` with the wrong count, a one-line interpreter call.
   "The test node doesn't exist yet" (`no tests ran`) is **not** a demonstration — that's the same
   output a typo'd name gives, and it would be satisfied by an empty test body.

   Then apply the two tests in `acceptance-criteria.md` (oracle exists / not satisfiable without
   the work). A criterion that fails either is `needs-review`, not `auto-ok` — building a missing
   oracle can be its own `auto-ok` prerequisite.

6. **Sort criteria from guards.** A check that passes today is a **guard**, not a criterion — file
   it under Regression guards and keep looking for what this work makes newly true. Expect small
   cleanup and refactor issues to land as one criterion plus several guards; if *everything*
   passes today, you have no criteria yet. Run the guards too and confirm they pass now — one that
   already fails is a pre-existing break worth naming before anyone implements against it.

7. **Derive the tier** (`auto-ok` / `needs-review`) mechanically from the criteria + risk
   paths. State it and its reason; don't editorialize it upward or downward.

8. **Record the decisions the interview settled** in the spec's **Design decisions** section —
   each as decision / why / what was rejected. Any answer that changed which criteria apply is a
   decision, not a detail: the criteria below it are unreadable without it, and the next context
   (or the next `express` run) has no other way to learn why the obvious alternative was passed
   over. On the augment path this section goes into the **issue body** too. A decision recorded
   only in an issue *comment* is invisible to every downstream mode — they read the body through
   the marker and never read comments — so a comment is for provenance, never for the constraint.

9. **Write the spec** to the `spec-template.md` structure. Run the **readiness checklist**.
   Fix failures inline. Show the user the spec (goal, criteria+checks, tier, what-we're-NOT-
   doing) and get confirmation before filing.

10. **File or update the issue.**
   - *New:* `gh issue create` with body = spec; title from
     the Goal (<70 chars); apply the `agent-session:spec` label (`--add-label`); add to the board's Ready
     column if configured.
   - *Existing (augment):* `gh issue edit <n>` — add the `agent-session:spec` label (`--add-label`), add the spec sections. **Preserve the original author's text**; augment, don't overwrite
     intent.
   - **The `## Tier:` heading is the one section you replace rather than add.** A body with two
     `## Tier:` headings reads as a conflict and the issue is skipped — so when a decision revises a
     tier, edit the existing heading in place. Superseded *reasoning* can be kept, but only under a
     heading the anchor does not match (e.g. `### Original tier assessment (superseded)`). Format per
     `acceptance-criteria.md` → "The heading format is part of the contract".

11. **Report** the issue URL, the tier + reason, and the resume command.

## Escalation — stop and surface when

- A criterion the user insists on genuinely can't be made checkable → fine, but it forces
  `needs-review`; say so plainly rather than fudging a weak check to keep `auto-ok`.
- Research reveals the framing is wrong → re-anchor before writing criteria.
- The spec is really two specs → offer to split; each gets its own issue.
