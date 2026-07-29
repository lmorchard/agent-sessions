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

## Second pass, same session — #15, #16, #17, #19, #20

Five more markerless issues (three pre-existing and out of the first pass's scope, two filed by it).
Five scanners, same cap. **All five derived `needs-review`**, but for materially different reasons, and
two carry genuinely good criteria.

| Issue | Criterion? | Why `needs-review` | Outcome |
|---|---|---|---|
| #15 heading format unspecified | yes — shipped template through shipped parser | trigger 2 only (`skills/**`) | augmented |
| #16 revised tier must replace | **none honest** | trigger 2 + trigger 1 | augmented, no criteria |
| #17 triage reports activity | none honest | trigger 2 + trigger 1 | **reframed to #22, closed** |
| #19 marker is a bare substring | yes — fails with a real `AssertionError` | trigger 2 only (`gate.py`) | augmented |
| #20 `scripts/` unclassified | **none honest** | trigger 1 (fails test 2) | augmented, scope reframed |

What the scanners established that a read would not have:

- **#15's own proposed fix is insufficient.** Measured on the shipped parser: template as shipped →
  `missing`; colon added → `unparsed`; bracketed placeholder → `conflict`; concrete token → `auto-ok`.
  The real requirement is two-part, and the issue names only the colon.
- **#17 should not be built as filed, and was not.** Its own body flagged the risk and told us its grep
  was too narrow. Widened, the concept is reachable four places — including that same file's purpose
  sentence (`triage.md:5`) and the same step it wanted to amend (`triage.md:70`, "with tiers"). Its
  suggested mechanism also crossed `SKILL.md:74` ("the board-driver is not part of this skill").
  Reframed to #22 (a `docs/` note) and closed. **My own reframe argument overclaimed** — I said the docs
  route "has a real oracle"; it does not, and #22 records that correction and is tiered accordingly.
- **#19's regression fear is empirically absent.** All 13 genuine markers across 18 issues of history
  sit alone on line 1; anchoring changes exactly two verdicts, both corrections. But anchoring does
  *not* close the fenced-block case, so that is a real fork, deferred explicitly. Also found:
  `extract_gate` has the identical substring bug on PR bodies — pulled into scope so it isn't the
  "fixed one field, never generalised" pattern again.
- **#20's real answer is a different question.** `scripts/docs_check.py` was created in commit
  `3675986` — *the same commit that added `CLAUDE.md`'s "ask what it just invalidated" section*. The
  rule and its first violation shipped together. The enumeration has rotted by omission twice in two
  days, so the issue was reframed to **state a default for unlisted paths**, the only version that
  cannot go stale by omission. `CLAUDE.md`, `README.md` and `pyproject.toml` are also unclassified.
- **Both #15's and #16's scanners independently said don't merge them**, contradicting #16's own body.
  Fusing a gradable half with an ungradable half is defect class 1; they are sequenced instead.

## A defect found by verifying, not by auditing — #23

`make dry-run-self` after the second pass showed `eligible` dropping 3 → 1, with #11 and #13 reporting
`already has an open PR: #21` — **PR #21 being this session's own docs PR, which implements neither.**

`pr_for_issue` (`agent-session-driver.sh:324-332`) matches a bare `#N` anywhere in an open PR's body,
title **or branch name**, while the function's own comment says an express PR carries `Closes #N`.
`gh pr view 21 --json closingIssuesReferences` → `[]`: GitHub links it to nothing. Filed as **#23** and
recorded as class 1 instance 10.

Two corrections the scanner made to the finding as I first stated it, both of which change the fix:

1. **PR #21's branch is `docs/triage-11-12-13`**, so the branch arm fires independently — which refutes
   the compromise a reader reaches for first (`closingIssuesReferences` OR branch-name still skips #11).
2. **The frozen fixture at `test-park-state.sh:89` pins the loose behaviour** for the two post-run
   discovery call sites, whose stub ignores the requested field list. So this is a
   selection-vs-discovery split, not a one-line `jq` swap — and a closing-refs-only fix would be a STOP
   against a read-only frozen check.

`closingIssuesReferences` is available on the list query the driver already makes, so there is no
API-cost argument against fixing it properly.

## State at end of session

14 open issues, **all 14 now print a line** in `make dry-run-self` — the marker-less silence is gone,
which was #13's whole complaint. `eligible: 1` (#6), because #23 is currently masking #11 and #13;
merging or closing PR #21 clears that, since the query is `--state open`.

## Method notes

- Verbatim preservation was verified **by substring against a pre-edit snapshot** (`/tmp/triage-snap/`),
  not by eye, for all three edits. Tier parsing was verified by piping each live body through
  `driver/gate.py tier`, and the `## Tier:` heading count asserted as exactly 1 per body.
- `gh project item-add --format json` **did** return non-empty ids here, unlike the `item-list`-after-add
  path `findings.md` warns about. Ids were still re-read and checked non-empty before `item-edit`.
- Verbatim preservation and single-`## Tier:`-heading checks were applied to all eight edited bodies,
  not just the first three.
- **Nine issues triaged, two defects found, and neither was found by reading.** #23 came out of running
  the verification command; the #13 premise correction and #15's insufficient-fix correction came out of
  scanners running checks. The one error *I* made unaided — overclaiming that the #22 reframe "has a real
  oracle" — was caught by writing the issue body out rather than by any mechanism, which is the weakest
  link in the set and worth noting as such.
- No repo file changed during the triage passes themselves; the whole product was GitHub state.
