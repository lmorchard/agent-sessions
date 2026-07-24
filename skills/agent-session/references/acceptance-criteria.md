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

Write each criterion in one of two established forms — **EARS** or **Given-When-Then** —
then pair it with a check. Both force a condition → observable-response shape that maps to
an assertion. Full syntax, patterns, and how to pick: `references/criteria-grammar.md`.

```
- CRITERION: WHEN the input list is empty, the system SHALL return an empty result (not error).
  CHECK: `pytest tests/test_foo.py::test_empty_input` passes.
```

## The check must be trustworthy (verifier fallibility)

"Machine-checkable" is **necessary but not sufficient** — the check must also be *correct*.
A green check from a bad oracle is worse than no check.

- **Verifier independent of implementer.** The check is authored/reviewed separately from
  the code that satisfies it (a separate subagent/context in execution).
- **Freeze the checks before implementation.** Written at intake; the implementer must not
  weaken them during execute.

## When a criterion won't reduce to a concrete check

Escalate in this order — don't jump straight to "human decides":

1. **Concrete example test** — a specific input → expected output assertion. Preferred.
2. **Property / invariant** — when no single example captures it, state an invariant the
   output must always satisfy ("result is non-decreasing", "no criterion loses its id")
   and check that. A real middle tier, not a cop-out.
3. **Human judgment** — only when 1 and 2 genuinely fail (subjective feel, aesthetic,
   product-call). This is not a failure of the spec; it is the criterion *telling you* the
   issue belongs in `needs-review`.

### The oracle must already exist

A check counts as "reduced" only if its oracle exists *now* — the test / fixture / eval set
/ labeled corpus it names is already present, or is trivially writable against current
behavior. A criterion whose check depends on an oracle that must first be **built** (a
labeled relevance corpus, a golden eval set, a benchmark that doesn't exist yet) is **not
reduced** — it is `needs-review` until that oracle exists and has been reviewed
independently of the implementer.

Reason: an unbuilt oracle is an untrustworthy one, and deciding "what counts as correct"
while building it (e.g. which results get labeled "relevant") is the human judgment being
*deferred*, not eliminated — the premature-confidence trap. Positing a fixture you'd have
to author does not make a criterion checkable today.

The line is *whose judgment*, not *whether a file exists yet*. "A unit test asserting the
scoring pass emits no proposal for an occupied node" doesn't exist yet either, but the
criterion already says exactly what to assert and the test harness is there — that's ordinary
test-first work, and the freeze phase writes it. "A corpus of queries labeled by relevance"
needs someone to *decide* what relevant means while building it. Ask: **does authoring this
check settle a question the criterion left open?** If yes, `needs-review`.

Building the oracle can be its own `auto-ok` issue; the criterion that depends on it stays
`needs-review` until it exists.

### The oracle must also discriminate

Existing is not enough — **run the check and confirm it fails on current behavior.** A check
that already passes proves nothing about the work: it will still pass if the implementer
changes nothing at all. Either the behavior is already there (the issue is stale) or the check
isn't testing the criterion.

Watch for the near-miss: the *command* exists and runs, but it can't reproduce the condition
the criterion is about. A census/benchmark invocation that omits the placement or config where
the problem actually appears will report a clean result forever. The tell is a criterion phrased
as "SHALL produce zero X" whose command produces zero X today.

So: for each criterion, run its check and record the observed failure. If it passes now, the
criterion is not reduced — `needs-review` until there's a command that discriminates, or the
criterion is rewritten around one. Evidence from a past run (a table in the issue, a number
someone remembers) is not a substitute for running it: the repo has moved, and the invocation
that produced that table may not be the one you wrote down.

### The check must not be satisfiable without the work

Third test, after *exists* and *discriminates*: **can this check pass without the work being
done?** A check can discriminate — fail today, pass tomorrow — and still grade nothing. Three
shapes seen in the wild:

| Criterion | Check | Satisfied by |
|---|---|---|
| "a test covering X exists" | `pytest ...::test_x` | `def test_x(): pass` |
| "the doc explains Y" | `grep -E "separate\|distinct"` | typing the word "separate" |
| anything named-but-absent | `no tests ran` | the same output a typo'd node name gives |

Ask what the *cheapest* way to make the check green is. If that's not the work, the check is a
proxy — name it as one, and either strengthen it (assert the specific behaviour, not the
presence of a name or a keyword) or accept that the real oracle is a human read.

**Test-coverage issues are the hard case: the work *is* the oracle.** When the deliverable is a
test, the freeze/implement split degenerates — the freeze phase would write the test and leave
nothing to implement, so the implementer authors the very thing that grades it. Either the
criterion names the specific assertions the test must make (so the check grades content, not
existence), or it's `needs-review` and a human confirms the test asserts something real.

## Criteria vs. regression guards

Not every check worth running is a criterion. Sort them:

- A **criterion** says what this work must *newly* make true. It has to discriminate — fail
  now, pass when done.
- A **guard** says what this work must not *break*. It passes now and must keep passing:
  existing suites, golden/equivalence tests, "the test being exempted still runs."

Without this split the discriminate rule would reject legitimate checks. "The full suite stays
green" and "output is byte-identical" can never fail at freeze, so as *criteria* they're
vacuous — as *guards* they're exactly right. Demoting one isn't a downgrade; it's filing it
where it works.

Practical consequence: **small cleanup and refactor issues are often one criterion and several
guards.** If every check you've written passes today, you have a list of guards and no
criterion yet — go back and ask what this work makes newly true.

Guards don't affect the tier. Tier derives from the criteria and the risk-gated paths; a guard
grades nothing new, so it has no bearing on autonomy.

## Tier derivation

The escalation tier is not a separate judgment — it falls out of the criteria:

- **`auto-ok`** — *every* criterion reduced to a concrete-test or property check, AND the
  issue touches no risk-gated path (below). Safe for the autonomous loop to attempt and
  (per the merge gate) auto-merge.
- **`needs-review`** — *any* criterion rests on human judgment, OR the issue touches a
  risk-gated path. A human stays in the loop.

**A third trigger: the issue withholds a decision its criteria depend on.** Empirically the most
common one — in an 8-issue triage of a real backlog, *all five* `needs-review` calls were driven
by this, none by the risk-gated list acting alone. The issue asks a question ("remove it, or
document it?"), lists remediation options without choosing, says "decide with data first", or
needs an architecture decision with no existing wiring point. Every individual criterion may be
perfectly checkable; what's undecided is *which set applies*.

The test is **does the choice change which criteria apply?**

- **No** → implementation style, irrelevant to the tier. "Delete the guard, or replace it with
  `conversations_root()`" — both satisfy the same greps. Stays `auto-ok`.
- **Yes** → the loop would have to *pick the goal* rather than implement it. "Remove the
  function" and "keep it with a docstring" have different criteria. `needs-review`.

This is upstream of criteria verifiability, so check it first: a perfectly checkable criterion
set for a goal nobody chose is a confident answer to the wrong question. Resolving the decision
converts the issue — one question to a human, and it can drop to `auto-ok`.

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

## More examples

**Property tier** — no single input captures "done", so check an invariant instead of an
example (the escalation rung that's easiest to skip past into "human decides"):
```
- CRITERION: the deduplication pass SHALL NOT drop or merge two records with distinct ids.
  CHECK (property): hypothesis test `test_dedup_preserves_distinct_ids` — for any generated
  list of records, every distinct id in the input appears in the output.
```

**Pure refactor** — the obvious criterion ("behavior unchanged", via a golden test) is really a
*guard*: it passes before and after, so it can't tell done from untouched. The discriminating
criterion is **structural** — the thing the refactor is actually *for*:
```
- CRITERION: token classification SHALL live only in `Lexer.classify()` — no other module
  SHALL re-implement it.
  CHECK: `rg -l TOKEN_PATTERNS src/ | wc -l` returns 1. (Returns 3 today — discriminates.)

- GUARD: `pytest tests/test_parser_golden.py` (golden-file diff) passes and the full suite
  stays green — output byte-identical to pre-refactor. Passes today; must keep passing.
```

**Unwanted-behavior (EARS `IF/THEN`)** — error paths are criteria too:
```
- CRITERION: IF the upload exceeds the size limit, THEN the API SHALL reject it with 413
  and SHALL NOT write a partial file.
  CHECK: `pytest tests/test_upload.py::test_oversize_rejected_no_partial` passes.
```
