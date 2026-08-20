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

## Three tests every check must pass

"Machine-checkable" is **necessary but not sufficient** — a green check from a bad oracle is
worse than no check. Before finalizing any criterion, put its check through all three.

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

### 2. Does it discriminate?

**Run the check and confirm it fails on current behavior.** A check that already passes proves
nothing — it will still pass if the implementer changes nothing at all. Either the behavior is
already there (the issue is stale) or the check isn't testing the criterion.

Watch the near-miss: the *command* exists and runs, but can't reproduce the condition the
criterion is about. A benchmark invocation that omits the config where the problem appears will
report clean forever. The tell is a criterion phrased "SHALL produce zero X" whose command
produces zero X today.

### 3. Can it pass without the work being done?

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

Without this split, test 2 would reject legitimate checks. "The full suite stays green" and
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

**Trigger 1 — any criterion rests on human judgment**, or fails one of the three tests above (no
oracle, doesn't discriminate, satisfiable without the work).

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
