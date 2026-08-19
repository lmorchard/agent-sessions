# Filtered decafclaw triage — 2026-08-03 evening

Ran the filtered triage pass the evening handoff called for, and settled the routing-gate question
that had fired three times.

Counts here are dated on purpose (`CLAUDE.md`: *"If you must state a countable fact, date it"*).
Live sources: `make dry-run` for the queue, the decafclaw issue list for the rest.

## Outcome

**decafclaw's eligible count went 0 → 8.** That is the number this pass is judged by; "scanned 16,
augmented 2" is an activity report.

Getting there took two distinct moves, and **the second was worth three times the first**:

| Move | Cost | Eligible |
|---|---|---|
| Scan 16 issues, augment the ones already ready | 16 subagents | 0 → **2** |
| Ask Les six questions the scans had isolated | one conversation turn | 2 → **8** |

## The finding that generalises: the blocker is the withheld decision

Of 14 `needs-review` verdicts, **nine were the same shape** — the issue lists two or three options
and deliberately does not pick one. Not vagueness; these were well-researched issues that stopped
short of a decision, several of them saying so in as many words (#683: *"Not proposing one — that's
the work"*).

That shape is **one human answer from `auto-ok`**, and in six cases the scanner had already verified
that the post-decision check discriminates today. So:

- **Triage's most valuable output is not augmented issues. It is a list of decisions, each with the
  evidence already gathered and the consequence of each branch already priced.** The scanning is
  what makes the questions cheap to answer, but the questions are what move the queue.
- A triage pass that reports only "augmented K" is under-reporting itself. It should report the
  decision list too, because that is the part with the leverage.

The remaining five `needs-review` are genuinely gated and did not convert: #747 and #685 (trigger 2,
shell pre-approval and the deny-before-prompt authz gate), #693 (deletion, plus a model-behavior
oracle), #658 (test-coverage hard case — the work is the oracle), #335 (moves the authoritative
durable record).

## Four things only the fan-out could see

Each of these is invisible to a single-issue `intake`, and that is an argument for batch triage
independent of throughput:

1. **#695 and #702 are the same bug**, filed three hours apart the same day. #702 says "filing
   separately" — its author never saw #695. Closed #702, carrying its unique contribution (the
   intermittency data) into the close comment rather than losing it.
2. **#676, #695 and #693 are all blocked on one missing capability** — no `--reps`/per-case filter
   in the eval runner, so no K-of-N pass rate. Three scanners discovered it independently, none
   could see the others. Filed as #757, which is `auto-ok` on its own and unblocks all three.
3. **#650's headline work had already shipped** (#655, #663 — verified merged). Its title names a
   done thing.
4. **#662 was two unrelated halves**, and the deferred half was holding the ready half hostage.
   Split; part 1 is now #756.

## Verify-don't-assume, paid off five times

Every one of these would have produced a green check that graded nothing. All were found by a
scanner *running* something, not reading it — which is why the brief mandates running each proposed
check:

- **#747** — the obvious test *passes today and grades nothing*: pytest's `tmp_path` is pre-resolved
  (`_pytest/tmpdir.py:156`), so the resolved-vs-unresolved divergence the issue is about never
  occurs. The test needs a real symlinked skill root.
- **#755** — the obvious test *throws*: jsdom implements no `scrollIntoView`, so
  `vi.spyOn(Element.prototype, 'scrollIntoView')` fails outright, and an unguarded call inside
  Lit's `updated()` reddens all 22 existing tests. Classic shape: new criterion green, guard red.
- **#683** — the title's `97 / 40 / 58` is **config-dependent**. Re-running the same code locally
  gave `30 / 67`. A criterion pinning the literals would trip whenever someone adds a tool.
- **#335** — the issue's premise is **false against the code**. *"The index loader already handles
  multiple segments"* — it does not; `read_inbox()` reads only the live path and the read-state
  resolver *deliberately discards* archived ids. Verified empirically, not inferred.
- **#676** — *"4 failing cases"* is **unre-derivable**. Nothing persists tool-choice results, so the
  set cannot be known without paying for a run. Criteria must say "0 failing", never "these 4".

The pattern across all five: **a countable or quoted fact inside an issue body is exactly as
perishable as one inside a doc**, and `findings.md`'s documentation rule applies to issues too.
#335's and #650's premises were stale; #683's and #676's numbers were.

## What the filter did and didn't do

The handoff's filter (`#≥600` ∪ `bug`-labeled, minus the pre-fail regex) selected 32 → 23. Assessed
honestly:

- **The pre-fail regex earned its place.** It caught #601 on "Pick one", and #601 genuinely fails
  trigger 1 — its criteria reduce only to a keyword grep on a diagram caption.
- **It missed #335**, which is `#<600` and `enhancement`, so neither arm caught it. I added it back
  by hand on the handoff's recommendation. It came out `needs-review` anyway, so the miss cost
  nothing — but that is luck, not evidence the filter is sound.
- **Density held up.** Of the 16 scanned, the two that came out `auto-ok` unassisted were both in
  the file-and-test-naming tier, as `findings.md` predicted.

## Decision recorded: the driver's outcome routing is now gated

Les gated `driver/agent-session-driver.sh`, joining `driver/gate.py`. Committed separately on
`gate/driver-outcome-routing` with the three claims it invalidated corrected in the same commit —
the narrow reading's *"and nothing else"*, the allowlist line, and the closing paragraph that named
the routing as an accepted residual risk.

The reasoning worth keeping: **a revisit trigger that keeps firing and never converts is a deferral,
not a trigger.** It fired on #39, on #58, and would have on #82.

The partition now creates a new residual risk, named in `CLAUDE.md` at the moment it was created
rather than discovered later: the driver's *fixtures* stay drivable while the driver does not, so a
run can weaken the assertions protecting routing it cannot itself edit.

## Loose ends

- **PR #81 has since merged**, so the operational figures above are no longer parked — the durable
  half is promoted into `findings.md`'s operational figures in this same branch. What stays here is
  the per-issue narrative, which is provenance rather than a lesson.
- The locked worktree at `.claude/worktrees/docs+orientation-repo-detail` is still present.
