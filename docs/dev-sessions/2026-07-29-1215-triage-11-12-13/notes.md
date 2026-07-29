# triage pass over #11, #12, #13 — 2026-07-29

**What this was.** A dogfood of `skills/agent-session/phases/triage.md`, run by reading the phase file
rather than as a registered skill. Scope was fixed in advance: the three issues the driver could not
see. Three read-only `Explore` scanners fanned out, one per issue, each drafting proposed criteria +
guards + a tier and **running every check it proposed** under a targeted-commands-only cap.

## Outcome

| Issue | Before | After | Eligible now? |
|---|---|---|---|
| #11 | no marker, no tier | split → #11 `auto-ok` (follow-up 1 only), **#18** `needs-review` (follow-ups 2+3) | #11 yes |
| #12 | no marker, no tier | `needs-review`, **no criteria proposed** — deliberately | no, honestly skipped |
| #13 | marker *quoted only*, no tier | `auto-ok` | yes |

Filed as side findings, both deliberately left untriaged: **#19** (the marker substring hazard),
**#20** (`scripts/` unclassified in the risk-gated partition).

`make dry-run-self` after write-back: `eligible: 3` — #6 (pre-existing), #11, #13.

## What the scanners got that a read would not have

- **The task premise was wrong for #13.** Its body *quotes* `<!-- agent-session:spec -->` in its
  opening sentence, and `gate.py:225` tests membership with a bare substring, so #13 was never
  invisible — it had been printing `SKIP #13 tier: no '## Tier:' line`. Only #11 and #12 were. Filed
  as #19.
- **#11's own severity claim was too strong.** Its follow-up 3 says the host-specific guard "would
  assert the wrong thing." It would not: `_nest_verdict` asserts a *combined* verdict, so on another
  host the case fails loudly (`no-warn stopped-early`). Had it asserted only `_nest_warned`, it *would*
  have passed vacuously. The combined verdict is what saved it.
- **#12's option 2 is not the obviously-checkable option it looks like.** Its headline linter rule —
  "a check that greps a source file for a literal" — fires on 4 of the 6 criteria in this repo's own
  `2026-07-27-1708-board-dogfood/checks.md`, and 3 of those were *correct*. C6 is the one that caught
  the classifier divergence. So the rule needs a human call on where "mention" ends and "anchored
  structural grep" begins.
- **One criterion was correctly refused.** #12's only option-independent candidate passes today, on
  `frozen-checks.md:207`, a sentence about amendments. Tightening it to a literal produces the
  spelling-check proxy that #12's own defect table indicts. The scanner proposed none rather than
  fudge it.
- **One check was correctly left unrun.** #18's hermeticity criterion cannot safely be run before the
  fix: putting `gh` on `PATH` is exactly what lets the nest cases sail past validation at `:168` into
  a real `claude` invocation, since no nest case passes `--dry-run`. Marked UNRUN with the reason
  named, not silently.

## Still open after this pass

**Three more markerless issues exist and were out of scope: #15, #16, #17.** They print nothing in
`make dry-run-self` right now — #13's bug, reproducing live in the same output that was run to verify
this pass. 14 issues read, 11 lines printed. Plus the two newly filed, #19 and #20, which want a
scanner pass alongside them.

## Method notes

- Verbatim preservation was verified **by substring against a pre-edit snapshot** (`/tmp/triage-snap/`),
  not by eye, for all three edits. Tier parsing was verified by piping each live body through
  `driver/gate.py tier`, and the `## Tier:` heading count asserted as exactly 1 per body.
- `gh project item-add --format json` **did** return non-empty ids here, unlike the `item-list`-after-add
  path `findings.md` warns about. Ids were still re-read and checked non-empty before `item-edit`.
- No repo file changed during the pass itself; the whole product was GitHub state.
