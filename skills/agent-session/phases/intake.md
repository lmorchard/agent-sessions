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

## Process

1. **Read the source thoroughly** (prompt or issue body). Confirm `gh` auth if a URL is
   given (`gh repo view`).

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
   **Before finalizing each criterion, run its check.** The command / test / fixture / harness
   it names must be real today *and* must **fail on current behavior** — a check that already
   passes will still pass if nothing gets built. Actually run it and record the failure; don't
   infer either property from a table in the issue or from the command merely existing. Then
   apply `acceptance-criteria.md`: an oracle that must first be built, or one that can't
   reproduce the condition the criterion is about, makes the criterion `needs-review`, not
   `auto-ok` (building the oracle can be its own `auto-ok` prerequisite).

   **A check that passes today is a guard, not a criterion** — file it under Regression guards
   and keep looking for what this work makes newly true. Expect small cleanup and refactor issues
   to land as one criterion plus several guards; if *everything* passes today, you have no
   criteria yet. Run the guards too, and confirm they pass now — a guard that already fails is a
   pre-existing break worth naming before anyone implements against it.

5. **Derive the tier** (`auto-ok` / `needs-review`) mechanically from the criteria + risk
   paths. State it and its reason; don't editorialize it upward or downward.

6. **Write the spec** to the `spec-template.md` structure. Run the **readiness checklist**.
   Fix failures inline. Show the user the spec (goal, criteria+checks, tier, what-we're-NOT-
   doing) and get confirmation before filing.

7. **File or update the issue.**
   - *New:* `gh issue create` with body = `<!-- agent-session:spec -->` + spec; title from
     the Goal (<70 chars); apply the tier label (`--label`); add to the board's Ready
     column if configured.
   - *Existing (augment):* `gh issue edit <n>` — prepend the marker, replace/append the
     spec sections, apply the tier label. **Preserve the original author's text**; augment,
     don't overwrite intent.

8. **Report** the issue URL, the tier + reason, and the resume command.

## Escalation — stop and surface when

- A criterion the user insists on genuinely can't be made checkable → fine, but it forces
  `needs-review`; say so plainly rather than fudging a weak check to keep `auto-ok`.
- Research reveals the framing is wrong → re-anchor before writing criteria.
- The spec is really two specs → offer to split; each gets its own issue.
