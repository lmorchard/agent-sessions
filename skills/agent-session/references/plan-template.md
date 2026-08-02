# Plan template

Skeleton for `plan.md`. Adapted from `dev-session`'s: Phase 0 is the **check freeze**, and
every phase names the criteria it advances so coverage is checkable instead of asserted.

````markdown
# [Feature Name] Implementation Plan

**Goal:** [One sentence describing what this builds]

**Source issue:** [URL] — **Tier:** [`auto-ok` | `needs-review`] ([reason])

**Approach:** [2-3 sentences from spec.md's Design Decisions]

**Criteria:** C1 [one-line gist] · C2 [gist] · C3 [gist]
[Full text + checks live in `checks.md`. Ids are assigned there and referenced here.]

---

## Phase 0: Freeze the acceptance checks

Write `checks.md` and author the tests the checks name, per `references/frozen-checks.md`.
No implementation in this phase.

**Files:**
- Create: `{session-dir}/checks.md` — criteria + checks copied verbatim from the spec, ids assigned
- Create: `tests/exact/path/to/test_acceptance.ext` — the tests C1…Cn name

**Verification — automated:**
- [ ] Every criterion's check runs and **fails for the expected reason** (not an import error,
      not a typo'd path) — record the observed failure per criterion
- [ ] Every guard runs and **passes** — a guard already failing is a pre-existing break, and
      knowing that now is what keeps it from reading as your regression later
- [ ] Check-reviewer dispatched read-only, given `checks.md` and the repo but **not** this plan
      and not the criteria's rationale; `## Adjudication` in `checks.md` carries one disposition
      per check *and per guard*, including the ones it cleared
- [ ] Freeze commit made (it closes the review window); sha recorded in `checks.md`

---

## Phase 1: [Slice name]

[1-2 sentences: what this phase delivers end-to-end]

**Advances:** C1, C2 — [and, if partial: what remains for a later phase]

**Files:**
- Create: `exact/path/to/file.ext`
- Modify: `exact/path/to/existing.ext` — [what changes]
- Test: `tests/exact/path/to/test.ext` — [unit tests for this slice; NOT the frozen
  acceptance tests, which are read-only from Phase 1 onward]

**Key changes:**
- `functionName(param: Type): ReturnType` — new
- `NewType { field: Type }` — new type

```language
// Code snippet for any non-trivial new logic
```

**Verification — automated:**
- [ ] C1's check passes: `[the exact command from checks.md]`
- [ ] C2's check passes: `[the exact command from checks.md]`
- [ ] Guards still pass: `[each guard's command from checks.md]`
- [ ] `make lint` passes
- [ ] `make test` passes (no regression)

**Verification — manual:**
- [ ] [What to eyeball, expected behavior. For a human-judgment criterion, name the
      criterion id and what evidence the human is being asked to grade.]

---

## Phase 2: [Slice name]

[...]
````

## Notes on use

- **Phase 0 is not optional.** The freeze is what makes the later checks trustworthy. A plan
  whose first phase writes implementation code has no frozen oracle.
- **Criteria coverage is bidirectional.** Every `Cn` in `checks.md` appears in some phase's
  **Advances**, and every phase advances at least one criterion. A phase advancing nothing is
  either scope creep or a missing criterion — resolve which before executing.
- **Cite checks by their exact command.** "C1's check passes" with the command inline beats
  "tests pass" — the checkbox has to be tickable from evidence, not from an impression.
- **Checkboxes are the resume mechanism.** `execute` ticks them as it goes; after a context
  reset, read the plan, find the first unchecked item, pick up there.
- **Code blocks for any non-trivial new code.** Don't write "implement validation logic" —
  show the validation. An agent reading only `plan.md` + `checks.md` should be able to build it.
- **Repeat shared context across phases.** Phases get read out of order and after context
  resets. "Similar to phase 2" is not adequate.
- **One commit per phase** (`Phase N: <name>`) keeps phases independently revertable.
- **No placeholders.** "TBD", "add appropriate error handling" without showing how, "write
  tests for the above" without the tests, or references to types no phase defines — all plan
  failures.
