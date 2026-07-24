# triage

Batch backlog-gardening: go back through a repo/board's existing issues, find the
under-specified ones, and augment them so they carry verifiable acceptance criteria + a
tier — turning a backlog of wishlist issues into a queue an autonomous loop can consume.

Reads the shared engine: `references/acceptance-criteria.md`, `references/spec-template.md`.
Reuses `phases/intake.md`'s *augment* logic per issue — same engine, batch-driven.

## Why subagents (the context lesson)

Reading and scoring dozens of issue bodies + their code context would flood the main
context. So the token-heavy work fans out to subagents that each work in their own context
and return only a compact result. The **human stays in the main loop** — subagents can't
interview you, so they do the part that needs no human (assess + *draft proposed*
criteria), and you do the part that does (ratify). See
`superpowers:dispatching-parallel-agents`.

## Process

1. **Scope the scan.** Confirm `gh` auth. Get the candidate set — `gh issue list` filtered
   by label/board column/query (e.g. all open, or the Backlog column). Confirm the scope
   with the user before fanning out (a scan of 200 issues is a lot of subagents).

2. **Fan out assessment (subagents, parallel).** One subagent per issue (batched to a sane
   concurrency). Each subagent, in its own context:
   - reads the issue body,
   - scores spec-completeness: does it have a clear goal? verifiable acceptance criteria?
     is it already marked with `<!-- agent-session:spec -->`?
   - if under-specified, does light codebase research and **drafts *proposed* criteria +
     checks + guards + a tier** per `acceptance-criteria.md` — a proposal, not a commitment,
   - **runs each proposed check** and records what it observed, so the ratify pass knows which
     proposals discriminate (fail today = criterion) and which don't (pass today = guard). A
     subagent that only *reads* code will propose plausible checks that grade nothing,
   - returns a COMPACT result only: `{issue, score, already_specified, proposed_criteria,
     proposed_guards, proposed_tier, observed_check_results, open_questions}`. Not the raw issue
     body or research dump.

   The main context now holds a scored list, not dozens of issue bodies.

   **Cap what a scanning subagent may run.** "Run each proposed check" and "fan out in parallel"
   collide: N agents each invoking the project's full suite will thrash the machine, and a
   parallel test runner (`pytest -n auto`, `cargo test`, `go test ./...`) already claims every
   core on its own. Tell each subagent explicitly: **targeted commands only** — a single test
   node, a `grep`/`rg`, a one-line interpreter call — and **never `make test` / `make check` /
   the full suite**. A criterion that can only honestly be checked by the full suite gets marked
   UNRUN and verified once, serially, during the ratify pass.

   This is a real limit on what a batch scan can conclude, so state it rather than letting UNRUN
   read as verified. Also give each subagent read-only tools where the harness allows it — a
   scanner has no business editing the repo it's scoring.

3. **Present the triage table** to the user: which issues are already fine, which are
   under-specified, and for each weak one the *proposed* criteria + tier. Let the user pick
   which to augment now (don't auto-edit the whole backlog).

4. **Ratify per issue (human, fast pass).** For each chosen issue, the proposal inverts the
   authoring effort: the user reacts to drafted criteria + checks rather than composing
   from a blank page. Most confirm quickly; some need a short `intake`-style back-and-forth
   on the open questions the subagent flagged. Where a criterion won't reduce to a check,
   apply the escalation ladder — it lands the issue in `needs-review`.

5. **Write back (augment in place).** For each ratified issue, run `intake` step 7's
   *existing-issue* path: `gh issue edit <n>` — prepend the marker, add the verifiable
   criteria + tier sections, apply the tier label, **preserving the original author's
   text**. Update the board if configured.

6. **Report** a summary: scanned N, already-specified M, augmented K (with tiers), left
   under-specified (and why — e.g. needs a design decision only the user can make).

## Escalation — stop and surface when

- An issue's intent is genuinely unclear (not just under-specified) → flag it for the user
  rather than inventing criteria for a goal you're guessing at.
- The scan surfaces duplicate/obsolete issues → note them; don't augment; suggest closing.
- A subagent can't tell what "done" would mean → that issue needs a human `intake`, not
  batch augmentation. Say so.
