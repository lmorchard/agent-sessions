# Spec template

Skeleton for a spec. Upgraded from `dev-session`'s: the "Desired end state" prose is
replaced by **Verifiable acceptance criteria**, and the readiness checklist now gates on
verifiability. Goal: enough detail that `plan` can produce a vertical-slice plan without
re-asking, AND that the loop can grade the result without a human.

````markdown
# [Feature Name] Spec

**Goal:** [One sentence. What does this enable, and for whom?]

**Source:** [Issue URL, ticket, or "user request from {date}"]

## Current state

[How the relevant area works today. Reference research with `file:line` pointers —
summarize the load-bearing facts, don't duplicate research.]

## Verifiable acceptance criteria

[The heart of the spec. Each criterion in EARS or Given-When-Then, each paired with a
runnable CHECK. See `acceptance-criteria.md`. If a criterion won't reduce to a check,
either escalate it to a property, drop it to "What we're NOT doing", or accept that it
forces tier = needs-review.]

- CRITERION: [WHEN … THE SYSTEM SHALL … | GIVEN … WHEN … THEN …]
  CHECK: [`command / test name / assertion` that proves it]
  VERIFIED DISCRIMINATING: [the failure observed when the check was run at intake]

## Regression guards

[What this work must not break. These pass *today* and must keep passing — existing suites,
golden/equivalence tests, coverage that mustn't be deleted to make a criterion go green. They
are not criteria (they can't fail at freeze) and they don't affect the tier. See
`acceptance-criteria.md` "Criteria vs. regression guards".]

- GUARD: [`command`] — [what it protects]. Passes today.

## Tier

[`auto-ok` or `needs-review`, derived per `acceptance-criteria.md` — every criterion
checkable AND no risk-gated path → auto-ok; else needs-review. State the reason.]

## Design decisions

- **Decision:** [chosen approach]
  - **Why:** [the constraint or trade-off that drove it]
  - **Rejected:** [alternative and why not]

## Patterns to follow

[Existing patterns to mirror, with `file:line` refs from research.]

## What we're NOT doing

[Explicit non-goals to lock scope. Name anything tempting this rules out — including
criteria that couldn't reduce to a check and were deferred rather than escalated.]

## Open questions

[Each entry pairs with a default answer (so plan/execute proceed under that assumption) OR
escalates as "blocks planning — needs decision". No bare questions.]
````

## Readiness checklist

The spec is ready iff:

1. **Every criterion names a check.** No criterion is bare prose. Each pairs with a
   concrete-test check, a property check, or is explicitly acknowledged as human-judgment
   (which forces `needs-review`). This is the upgrade — dev-session gated on placeholders;
   this gates on *verifiability*.
2. **Every criterion's check was run and observed to fail**, with the failure recorded. A check
   that passes today grades nothing. If it passes, it's a guard — move it, and find the
   criterion it was standing in for. **At least one criterion must discriminate**; a spec whose
   every check already passes has no acceptance criteria yet.
3. **Tier is derived and stated**, with its reason, per `acceptance-criteria.md`. Guards don't
   enter into it.
4. **Checks are freezable.** Each check is specific enough to write *before* implementation
   and not be weakened by it (names a test/command/assertion, not "tests should pass").
5. **Placeholder scan:** no "TBD"/"TODO"/vague requirements. Open questions each carry a
   default answer.
6. **Scope bounded:** "What we're NOT doing" present and concrete.
7. **No load-bearing ambiguity:** any requirement readable two ways is pinned to one.

If any criterion fails, re-open the interview (`intake`) — a spec that fails the gate can't
be filed as `auto-ok`, and filing it anyway defeats the purpose.

## Filing as a GitHub issue

`intake` lifts this into an issue body, prepends `<!-- agent-session:spec -->` (the resume
marker), applies the tier label, and keeps `file:line` refs verbatim (a snapshot; the
resumer re-researches if they drift). The **Verifiable acceptance criteria** and **Tier**
sections are what a downstream loop reads — never strip them.
