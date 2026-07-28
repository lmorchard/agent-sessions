# Move 7 — put the roadmap on a board, dogfood the front half

Brief: [handoff-restructure.md](../../handoff-restructure.md) § "Move 7". Input: the reconciled
roadmap in [design.md](../../design.md#roadmap), produced by move 6.

## The shape

**Board yes, board-driver not yet.** This repo's backlog is prose in a diary — the
under-specified-wishlist state the skill exists to fix, which is awkward for *this* repo to be in.
But pointing the driver here means the implementer's work product **is** the skill, and
`make skill-readonly` exists to prevent exactly that. So: dogfood `intake`/`triage` (the front
half), not `express` (the back half).

## Success condition — what makes this evidence rather than ceremony

The test is whether it produces evidence the project cannot otherwise get. Two candidates, both
real:

1. **`triage`'s second corpus.** One dogfood to date (8 decafclaw issues) — the thinnest real-run
   evidence of any mode. ~10 reconciled roadmap items is a genuine second sample.
2. **The host-agnosticism claim.** `agent-session-driver.sh`'s header asserts *"deliberately
   host-agnostic: no `$HOME` assumptions, every path a flag"* and **nothing has ever checked it** —
   one repo, one board, ever. `make dry-run` against a second board tests selection for free.

If neither is being served, this is filing cabinets and should be called that.

## Standing constraints

- **Expect a heavy `needs-review` skew, and do not fight it.** The oracle for skill wording is a
  micro-test at ~$50 and half a session ([findings.md](../../findings.md)). Do not fudge criteria
  to make skill issues look `auto-ok`; an honest `needs-review` beats a checkable-looking proxy,
  and this is precisely the repo that would be tempted.
- **Nothing merges.** Unchanged.
- **The driver does not run against this repo** in this move.

## Sequencing

1. ~~Finish the split (move 6).~~ **Done** — the reconciled roadmap is the input.
2. Add `skills/` to CLAUDE.md's risk-gated paths; **verify with one `intake`** that the tier falls
   out mechanically rather than being argued into place.
3. Create the board; file the roadmap as issues **from the reconciled list only**.
4. `triage` pass — the second corpus.
5. `make dry-run` against this repo/board. Selection only, no invocation.
6. Extract the gate parser. **Hand-run, not driver-run**, until the editing-a-running-script
   hazard is checked.
7. Chase `prior-art.md`'s unverified leads 1–3.
8. Reconsider the driver here.

## Open decisions (gating later steps)

- **The Agent-tool deviation** (step 4). `triage` step 2 fans out to subagents; the operator's
  standing instruction forbids the Agent tool unless asked. Taken as a named deviation three times
  now. The brief says decide it deliberately rather than discovering it mid-run.
- **Which roadmap items become issues** (step 3), and at what granularity.

## Not in scope

Phase 3 auto-merge. Running the driver against this repo. Rewriting the driver in Python — the
brief argues against it explicitly; the fix is extraction, not rewrite.
