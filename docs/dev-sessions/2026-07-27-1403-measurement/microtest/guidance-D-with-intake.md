The `intake` phase you are executing:

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
and stop; don't re-interview. (An issue that went `needs-review` for a *withheld decision* is the
exception, and needs no rule here: `acceptance-criteria.md`'s trigger 1 already names that case, and
5/5 control reps navigated it from the tier rules alone — see the micro-test in `docs/design.md`.)

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

---

The rules it reads for acceptance criteria:

# Acceptance criteria — the shared requirements engine

Read by `intake` and `triage`. The rules that turn a vague "desired end state" into criteria a
loop can grade itself against, and the tier that falls out of whether it can.

The shape of the work: write a criterion → pick its check → **validate that check** → sort
criteria from guards → derive the tier. The middle step is where most of the value is; a check
nobody validated is the failure mode this whole file exists to prevent.

## The one rule

**Every acceptance criterion names its own verifier.** A criterion is not done until it pairs
with a *runnable check* — a test, a lint/type gate, an assertion, an eval case, a grep. If the
only honest check is "a human looks and decides," it is not yet a criterion; it is a wish.

Prose "done" is human-graded → escalates. Checkable "done" is loop-graded → automatable. The
whole autonomy tier derives from this one distinction.

## Grammar — don't invent one

Write each criterion in **EARS** or **Given-When-Then**, then pair it with a check. Both force a
condition → observable-response shape that maps to an assertion. Full syntax and how to pick:
`references/criteria-grammar.md`.

```
- CRITERION: WHEN the input list is empty, the system SHALL return an empty result (not error).
  CHECK: `pytest tests/test_foo.py::test_empty_input` passes.
```

## Picking the check: escalate, don't jump to "human decides"

1. **Concrete example test** — a specific input → expected output assertion. Preferred.
2. **Property / invariant** — when no single example captures it, state an invariant the output
   must always satisfy ("result is non-decreasing", "no record loses its id") and check that. A
   real middle rung, not a cop-out.
3. **Human judgment** — only when 1 and 2 genuinely fail (subjective feel, aesthetic,
   product-call). Not a failure of the spec; it is the criterion *telling you* the issue belongs
   in `needs-review`.

## Two tests every check must pass

"Machine-checkable" is **necessary but not sufficient** — a green check from a bad oracle is
worse than no check. Before finalizing any criterion, put its check through both.

### 1. Does its oracle exist?

The test / fixture / eval set / corpus the check names must be present *now*. A check depending
on an oracle that must first be **built** (a labeled relevance corpus, a golden eval set, a
benchmark that doesn't exist) is **not reduced** — `needs-review` until that oracle exists and
has been reviewed independently of the implementer. Positing a fixture you'd have to author does
not make a criterion checkable today, and building it can be its own `auto-ok` issue.

The line is *whose judgment*, not *whether a file exists yet*. "A unit test asserting the scoring
pass emits no proposal for an occupied node" doesn't exist yet either, but the criterion says
exactly what to assert and the harness is there — ordinary test-first work, and the freeze phase
writes it. "A corpus labeled by relevance" needs someone to *decide* what relevant means while
building it. Ask: **does authoring this check settle a question the criterion left open?** If
yes, `needs-review`.

### 2. Can it pass without the work being done?

A check can discriminate — fail today, pass tomorrow — and still grade nothing:

| Criterion | Check | Satisfied by |
|---|---|---|
| "a test covering X exists" | `pytest ...::test_x` | `def test_x(): pass` |
| "the doc explains Y" | `grep -E "separate\|distinct"` | typing the word "separate" |
| anything named-but-absent | `no tests ran` | the same output a typo'd node name gives |

Ask what the *cheapest* way to make the check green is. If that isn't the work, it's a proxy —
either strengthen it (assert the specific behavior, not the presence of a name or keyword) or
accept that the real oracle is a human read and let the tier say so.

**Test-coverage issues are the hard case: the work *is* the oracle.** When the deliverable is a
test, the freeze/implement split degenerates — the freeze phase would write the test and leave
nothing to implement, so the implementer authors the very thing that grades it. Either the
criterion names the specific assertions the test must make (so the check grades content, not
existence), or it's `needs-review` and a human confirms the test asserts something real.

Downstream, `references/frozen-checks.md` keeps these checks trustworthy *during* execution —
frozen before implementation, read-only to the implementer, graded by a separate context.

## Criteria vs. regression guards

Not every check worth running is a criterion:

- A **criterion** says what this work must *newly* make true. It must discriminate — fail now,
  pass when done.
- A **guard** says what this work must not *break*. It passes now and must keep passing:
  existing suites, golden/equivalence tests, "the test being exempted still runs."

"The full suite stays green" and
"output is byte-identical" can never fail at freeze, so as *criteria* they're vacuous — as
*guards* they're exactly right. Demoting one isn't a downgrade; it's filing it where it works.

**Small cleanup and refactor issues are often one criterion and several guards.** If every check
you've written passes today, you have a list of guards and no criterion yet — go back and ask
what this work makes newly true.

**State a guard as an invariant, not a pinned number.** "`make test` → 3234 passed" goes stale the
moment upstream adds a test, and then trips for a reason that isn't a regression. Write what must
stay true: *no test lost, newly skipped, or newly failing.*

Guards don't affect the tier; they grade nothing new.

## Tier derivation

Not a separate judgment — it falls out of the criteria. **`auto-ok`** when neither trigger below
fires; **`needs-review`** when either does.

**Trigger 1 — any criterion rests on human judgment**, or fails one of the two tests above (no
oracle, satisfiable without the work).

This covers the issue that *withholds a decision* its criteria depend on — "remove it, or document
it?", "decide with data first", an architecture call with no existing wiring point. The useful
question there: **does the choice change which criteria apply?** If no, it's implementation style
and irrelevant to the tier ("delete the guard, or use `conversations_root()`" — same greps either
way). If yes, the loop would have to pick the goal rather than implement it, so some criterion is
unresolved and this trigger fires. Resolving the decision converts the issue — one question to a
human, and it can drop to `auto-ok`.

**Trigger 2 — the issue touches a risk-gated path**, regardless of how well it verifies
(project-configurable; sensible defaults): authentication/authorization, secrets/credentials,
data migration or deletion, deploy/infra/CI config, dependency additions/upgrades, anything the
project's CLAUDE.md marks off-limits. A perfectly-tested auth change still deserves human eyes.

Write the resulting tier into the issue body with its reason. A tier label is a convenience index
for querying; the body is authoritative.

## Examples

**The full reduction** — wish → criteria → tier. *"Make the export button handle big datasets
better."*
```
- CRITERION: WHEN a user exports a dataset over 10k rows THE SYSTEM SHALL stream the file
  without loading all rows into memory at once.
  CHECK: `pytest tests/test_export.py::test_large_export_is_streamed` (asserts peak RSS stays
  under threshold via the memory-probe fixture) passes.

- CRITERION: GIVEN an export in progress WHEN the user navigates away THEN the server SHALL
  cancel the export within 2s and free its buffers.
  CHECK: `pytest tests/test_export.py::test_export_cancels_on_disconnect` passes.

- CRITERION: the export button's spinner should "feel responsive."
  CHECK: none — subjective.
```
**Tier:** `needs-review` (trigger 2 — the third criterion won't reduce). Drop it to "What we're
NOT doing" or prototype it interactively, and the issue becomes `auto-ok`.

**Property rung** — no single input captures "done", so check an invariant:
```
- CRITERION: the deduplication pass SHALL NOT drop or merge two records with distinct ids.
  CHECK (property): hypothesis test `test_dedup_preserves_distinct_ids` — for any generated list
  of records, every distinct id in the input appears in the output.
```

**Pure refactor** — the obvious criterion ("behavior unchanged", via a golden test) is really a
*guard*: it passes before and after. The discriminating criterion is **structural** — the thing
the refactor is actually *for*:
```
- CRITERION: token classification SHALL live only in `Lexer.classify()` — no other module SHALL
  re-implement it.
  CHECK: `rg -l TOKEN_PATTERNS src/ | wc -l` returns 1. (Returns 3 today — discriminates.)

- GUARD: `pytest tests/test_parser_golden.py` (golden-file diff) passes and the full suite stays
  green — output byte-identical to pre-refactor. Passes today; must keep passing.
```

**Unwanted behavior (EARS `IF/THEN`)** — error paths are criteria too:
```
- CRITERION: IF the upload exceeds the size limit, THEN the API SHALL reject it with 413 and
  SHALL NOT write a partial file.
  CHECK: `pytest tests/test_upload.py::test_oversize_rejected_no_partial` passes.
```
