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

1. **Scope the scan.** Get the candidate set — `gh issue list` filtered
   by label/board column/query (e.g. all open, or the Backlog column). Confirm the scope
   with the user before fanning out (a scan of 200 issues is a lot of subagents).

2. **Fan out assessment (subagents, parallel).** One subagent per issue (batched to a sane
   concurrency). Each subagent, in its own context:
   - reads the issue body,
   - scores spec-completeness: does it have a clear goal? verifiable acceptance criteria? is it already marked with the `agent-session:spec` label?
   - **Evaluates baseline detail:** Is the issue detailed enough to even attempt drafting criteria? If it is just a vague title (e.g. "Fix login") or a one-liner lacking necessary context, the subagent flags it as `insufficient_detail` and skips drafting criteria.
   - if under-specified but actionable, does light codebase research and **drafts *proposed* criteria +
     checks + guards + a tier** per `acceptance-criteria.md` — a proposal, not a commitment,
   - **runs each proposed check** and records what it observed, so the ratify pass knows which
     proposals discriminate (fail today = criterion) and which don't (pass today = guard). A
     subagent that only *reads* code will propose plausible checks that grade nothing,
   - **is told not to fudge a weak check to keep `auto-ok`.** `intake` carries this rule; a
     scanning subagent needs it too, or it will go proxy-hunting in good faith — greping for a
     keyword to "verify" a doc is accurate, or asserting a test exists to "verify" it covers
     something. An honest `needs-review` beats a checkable-looking proxy. Include the
     satisfiable-without-the-work test from `acceptance-criteria.md` in the subagent's brief,
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

3. **Headless proposal (Async ratify pass).** Because you are running autonomously, there is no user to pick from a table interactively. Instead, for the issue you scanned:
   - **If flagged as `insufficient_detail`:** Record a comment asking the human for the missing context — say in it that the issue lacks baseline detail, since that is the signal — and record a `label` entry adding `agent-session:needs-human`. Stop execution.
   - **Otherwise (Criteria drafted):** Record your proposed EARS criteria, checks, and tier as a new top-level comment on the GitHub issue — an `issue_comment` entry in the write manifest (`references/write-manifest.md`). Never edit past comments in place.
   - Record a `label` entry adding `agent-session:needs-human` so the human knows they need to review it.
   - Do NOT apply the `agent-session:spec` label yet, because the human hasn't ratified the criteria.
   - Stop execution here. Do not edit the issue body yet.

   - In your comment, explicitly ask the human to react with 👍 or reply with 'Approved' if this spec looks good, or to provide any corrections.

4. **Follow-up pass (Reading human replies & reactions).** The human has left feedback, approved the proposal in the issue comments, or added a 👍 (THUMBS_UP / +1) reaction to the proposal comment. This information has been pre-fetched and provided in your context.
   - If they explicitly approved the spec, reacted with 👍 to the proposal comment, or ratified the risk-gated decisions (e.g., 👍 reaction, "Approved", "Looks good", "Dependencies are fine"), synthesize their approval into the spec and upgrade the tier label to `agent-session:auto-ok`. Proceed to Step 5.
   - If they provided corrections, synthesize them into an updated spec. If the spec is now complete and all risk-gated items are approved, set the tier to `agent-session:auto-ok` and proceed to Step 5.
   - If the spec STILL needs human input after synthesizing their corrections, record a new top-level `issue_comment` asking for further clarification (never edit past comments in place), RE-APPLY the `agent-session:needs-human` label with a `label` entry, and stop.

5. **Write back (augment in place).** For each ratified issue, run `intake`'s file-or-update step.
   Record a `label` entry adding `agent-session:spec` AND the appropriate tier label (`agent-session:auto-ok` or `agent-session:needs-review`).
   Then the *existing-issue* path: an `issue_body` entry carrying the full new body — the verifiable criteria + tier sections added, **preserving the original author's text**. Update the board if configured, with `project_item_edit`. Where the ratify pass settled a decision, carry `intake`'s Design-decisions step with it — the body, not a comment; comments are invisible to every downstream mode.

   **The `## Tier:` heading is replaced, never added twice.** An issue that already carries one — and
   a re-tiered issue always does — gets that heading edited in place. Two `## Tier:` headings read as
   a conflict and the issue is skipped, silently from the author's side. Keep superseded reasoning
   only under a heading the anchor does not match. Format per `acceptance-criteria.md` → "The heading
   format is part of the contract".

   **Verify the body you are about to record rather than trusting it:** the driver applies your
   `issue_body` entry after your run ends, so you cannot re-read the result. Check the string you
   are writing into the entry — that the author's original text survives as a substring, and that
   exactly one `## Tier:` heading remains. Both failures are invisible by eye on a long body.

6. **Report** a summary: scanned N, already-specified M, augmented K (with tiers), left
   under-specified (and why — e.g. needs a design decision only the user can make).

## Escalation — stop and surface when

Every escalation below is two manifest entries — an `issue_comment` and a `label` — never a
`gh` command. See `references/write-manifest.md`.

**Emit a `label_create` entry for any label before the `label` entry that applies it**, exactly as
`intake.md` does. `writes.py` applies every label on one entry in a **single** GitHub edit with no
ensure-exists step, and that edit errors outright when the repository has no such label — so on a
target repo seeing its first run, the whole entry fails, `write-manifest.md`'s all-or-nothing rule
stops the rest of the manifest, and **the issue is never parked**. It then
stays selectable and the loop picks it again. `label_manager` is the source of the colours; a
`label_create` entry that disagrees with it just makes the label look wrong.

- An issue's intent is genuinely unclear or lacking baseline detail (not just under-specified) → record a new top-level comment explaining the ambiguity, record the `agent-session:needs-human` label, and stop.
- The scan surfaces duplicate/obsolete issues → record a new top-level comment suggesting closure (never edit past comments in place), record the `agent-session:needs-human` label, and stop.
- An issue requires subjective visual/aesthetic iteration (like layout density, game feel, or UI design) → record the `agent-session:needs-human-interactive` label instead of `agent-session:needs-human`. Either one parks the issue, so "instead" is safe here; this one additionally says a person at a keyboard is required, because it cannot be handled asynchronously.
- A subagent can't tell what "done" would mean → record a new top-level comment asking the human for direction (never edit past comments in place), record the `agent-session:needs-human` label, and stop.
