# Acceptance criteria — the shared requirements engine

Read by `intake` and `triage`. This is the core of the skill: the rules that turn a vague
"desired end state" into criteria a loop can grade itself against, and the tier that falls
out of whether it can.

## The one rule

**Every acceptance criterion names its own verifier.** A criterion is not done until it
pairs with a *runnable check* — a test, a lint/type gate, an assertion, an eval case, a
grep. If the only honest check is "a human looks and decides," it is not yet a criterion;
it is a wish (see "When a criterion won't reduce").

Prose "done" is human-graded → escalates. Checkable "done" is loop-graded → automatable.
The whole autonomy tier derives from this one distinction.

## Grammar — don't invent one

Write each criterion in one of two established forms (pick per criterion; both map cleanly
condition → assertion and are human-readable *and* machine-checkable):

- **EARS** (from AWS Kiro): `WHEN <condition> THE SYSTEM SHALL <observable behavior>.`
  Good for event/state-triggered behavior.
- **Given-When-Then** (Gherkin/BDD): `GIVEN <context> WHEN <action> THEN <observable
  outcome>.` Good for scenario/flow behavior.

Each criterion then adds its check:

```
- CRITERION: WHEN the input list is empty THE SYSTEM SHALL return an empty result (not error).
  CHECK: `pytest tests/test_foo.py::test_empty_input` passes.
```

## The check must be trustworthy (verifier fallibility)

"Machine-checkable" is **necessary but not sufficient** — the check must also be *correct*.
A green check from a bad oracle is worse than no check (SWE-bench documents test-log
misparsing; the "same agent that wrote the patch is biased toward accepting it").

- **Verifier independent of implementer.** The check is authored/reviewed separately from
  the code that satisfies it (a separate subagent/context in execution).
- **Freeze the checks before implementation.** Acceptance checks are written at intake and
  must not be weakened during execute — an implementer editing its own oracle is the
  failure mode this rule exists to block.

## When a criterion won't reduce to a concrete check

Escalate in this order — don't jump straight to "human decides":

1. **Concrete example test** — a specific input → expected output assertion. Preferred.
2. **Property / invariant** — when no single example captures it, state an invariant the
   output must always satisfy ("result is non-decreasing", "no criterion loses its id")
   and check that. A real middle tier, not a cop-out.
3. **Human judgment** — only when 1 and 2 genuinely fail (subjective feel, aesthetic,
   product-call). This is not a failure of the spec; it is the criterion *telling you* the
   issue belongs in `needs-review`.

## Tier derivation

The escalation tier is not a separate judgment — it falls out of the criteria:

- **`auto-ok`** — *every* criterion reduced to a concrete-test or property check, AND the
  issue touches no risk-gated path (below). Safe for the autonomous loop to attempt and
  (per the merge gate) auto-merge.
- **`needs-review`** — *any* criterion rests on human judgment, OR the issue touches a
  risk-gated path. A human stays in the loop.

**Risk-gated paths force `needs-review` regardless of verifiability** (project-configurable;
sensible defaults): authentication/authorization, secrets/credentials, data migrations or
deletion, deploy/infra/CI config, dependency additions/upgrades, anything the project's
CLAUDE.md marks off-limits. Verifiability is necessary for autonomy, not sufficient — a
perfectly-tested auth change still deserves human eyes.

Write the resulting tier onto the issue as a label so a downstream loop can route on it.

## Worked example

**Wish (as filed):** "Make the export button handle big datasets better."

**Reduced criteria:**
```
- CRITERION: WHEN a user exports a dataset over 10k rows THE SYSTEM SHALL stream the file
  without loading all rows into memory at once.
  CHECK: `pytest tests/test_export.py::test_large_export_is_streamed` (asserts peak RSS
  stays under threshold via the memory-probe fixture) passes.

- CRITERION: GIVEN an export in progress WHEN the user navigates away THEN the server SHALL
  cancel the export within 2s and free its buffers.
  CHECK: `pytest tests/test_export.py::test_export_cancels_on_disconnect` passes.

- CRITERION: the export button's spinner should "feel responsive."
  CHECK: none — subjective. → this criterion forces tier = needs-review, OR is dropped to
  "What we're NOT doing" and handled in an interactive prototype.
```
**Tier:** `needs-review` (the third criterion won't reduce). Drop or prototype it, and the
issue becomes `auto-ok`.
