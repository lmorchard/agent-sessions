# Move 5 — measure the skill's unmeasured rules

Brief: [`docs/handoff-measurement.md`](../../archive/handoff-measurement.md).

## Goal

Stop adding rules to the skill and start measuring the ones already in it. Only three of the
skill's rules have measurements behind them; moves 4a–4c added roughly six more, all unmeasured.
This project has twice added a rule from a real failure and then measured it away as redundant.

## Definition of done (from the handoff)

1. The **discriminate rule** (`references/acceptance-criteria.md` § 2) micro-tested against a
   no-guidance control, 5+ reps per arm, with the result **acted on** — kept, trimmed, or cut.
2. **One clean two-issue driver loop**, both issues reaching real verdicts, no stale CI row.
3. `docs/design.md` updated; anything measured away actually **deleted**, not softened.

## Constraints carried in

- **Nothing merges.** `eligible-for-auto-merge` is a finding the driver reports, never an action.
- **Grep the skill for the concept before adding any rule of your own.** 2-for-2 record.
- Instrument rules, all learned the hard way: seal the fixture (subagents run *inside this repo*
  and will check whether your fixture is real); verdict labels must name **actions**, not intents;
  a result is evidence only once the instrument can produce the wrong answer; construct fixtures
  **from the code**, never from plausibility.
- `--max-budget-usd 25`. $12 is demonstrably too low.
- A clean no-guidance control is unreachable — the global CLAUDE.md leaks into every `claude -p`.
  Effects are **lower bounds**, and must be reported as such.

## Out of scope

The `PreToolUse` merge-block hook, the GHA host, phase 3 auto-merge, decafclaw's `.nvmrc` drift.

## What the side tasks were actually for

`#656` alone would have validated the fixed driver but consumed the only eligible issue, leaving
the two-issue loop needing two fresh intakes. One `intake` pass first turns both goals into a
single `--max-issues 2` run. That drove the decision to intake **#668** before running anything.
