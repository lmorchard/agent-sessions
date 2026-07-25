# intake

Interview a request into a spec with **verifiable acceptance criteria** and a **tier
label**, then file (or update) the GitHub issue. This is the human-in-the-loop front end —
intent capture and criteria judgment are human work; everything downstream trusts what this
produces.

Reads the shared engine: `references/acceptance-criteria.md`, `references/criteria-grammar.md`,
`references/spec-template.md`. Dispatches research per `references/documentarian-prompt.md`.

## Two entry modes

Determined by input, like `dev-session` brainstorm's blank-slate/refine split:

- **New request** (a prompt, or an empty/sketch issue) → develop a spec from scratch.
- **Existing issue** (URL given, issue has a body but no `<!-- agent-session:spec -->`
  marker, or is under-specified) → *augment* it: read what's there, keep the author's
  intent, backfill the missing criteria + tier. This is the mode `triage` drives per issue.

If the issue already carries the marker, it's already specified — confirm it still holds
and stop; don't re-interview.

**Exception — a withheld decision has since been made.** An issue can carry the marker and still
be unspecifiable: it went `needs-review` because it withheld a decision its criteria depend on, so
no criteria could be written for the undecided part. When that decision arrives, **re-run intake.**
That isn't re-interviewing a specified issue; it's the first pass that can produce criteria at all.
Interview only what the decision opens, keep what the earlier pass established, and re-derive the
tier — resolving a decision retires trigger 1, but a risk-gated path holds the tier where it is.

## Process

1. **Read the source thoroughly** (prompt or issue body).

2. **Codebase research substep** (skip only for changes so localized context is obvious).
   Dispatch a documentarian subagent (`Explore`/`general-purpose`) framed per
   `references/documentarian-prompt.md` (describe what exists, cite `file:line`, answer only
   what's asked). Ask 3–5 *neutral* questions about how the relevant area works today —
   **including, for each thing the requirement will need to check, whether that oracle
   exists today** (the metric / test / harness / way to reproduce the scenario). This
   grounds step 4's criteria in reality and its tier in what's actually checkable, and keeps
   the token-heavy reading in the subagent's context, not here.

3. **Interview — clarify / probe / finish, one question at a time.** Ground every question
   in the research. **Propose your best answer with its trade-off; ask to confirm or
   adjust** — never open-ended when you have a recommendation. Multiple-choice preferred.
   Keep proportional to complexity (2–4 questions for small issues).

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

   Then apply the three tests in `acceptance-criteria.md` (oracle exists / discriminates / not
   satisfiable without the work). A criterion that fails any of them is `needs-review`, not
   `auto-ok` — building a missing oracle can be its own `auto-ok` prerequisite.

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
   - *New:* `gh issue create` with body = `<!-- agent-session:spec -->` + spec; title from
     the Goal (<70 chars); apply the tier label (`--label`); add to the board's Ready
     column if configured.
   - *Existing (augment):* `gh issue edit <n>` — prepend the marker, replace/append the
     spec sections, apply the tier label. **Preserve the original author's text**; augment,
     don't overwrite intent.

11. **Report** the issue URL, the tier + reason, and the resume command.

## Escalation — stop and surface when

- A criterion the user insists on genuinely can't be made checkable → fine, but it forces
  `needs-review`; say so plainly rather than fudging a weak check to keep `auto-ok`.
- Research reveals the framing is wrong → re-anchor before writing criteria.
- The spec is really two specs → offer to split; each gets its own issue.
