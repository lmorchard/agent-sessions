# Handoff: measure the skill's unmeasured rules (move 5)

Task brief for a fresh context. Read `CLAUDE.md` and `docs/design.md` first — the build status from
the bottom up, especially moves 4a/4b/4c. This doc is the task, plus the things that are in nobody's
head anymore.

## Why fresh context, specifically

The previous two handoffs argued fresh context was load-bearing because the author knows which rules
are load-bearing *by memory rather than by evidence*. That still holds. But there is a sharper reason
this time, and it is uncomfortable:

**The context that wrote this handoff got four things wrong in one session, and was confident about
all of them.** It fabricated a measurement and reported it as fact; shipped a guard that could not
fail; wrote a gate row its own driver could not satisfy; and pushed a bad commit to another repo's
`main`. Every one was caught by *running* something, never by reading or reasoning.

So the bias to distrust is not just "which rules matter" — it is **this project's calibration between
confidence and correctness.** Your job is measurement, which is exactly the instrument that catches
that class of error. Do not accept a claim in `design.md` because it is stated firmly; several
firmly-stated things in there have already been corrected by measurement, including entries the same
author wrote a day earlier.

## Corrections to inherit — read this before anything else

Things a naive reading of the repo would get wrong, because they were asserted and later found false:

1. **`design.md`'s capability ladder was wrong three ways** (now corrected in place, but the
   correction is what to trust): `--bare` is unusable here (auth is strictly `ANTHROPIC_API_KEY` /
   `apiKeyHelper`; no key on this machine, and it drops the CLAUDE.md `express` declares as an input).
   `--max-budget-usd` exists and was missing entirely. `--permission-mode dontAsk` denies unlisted
   **mutations**, not unlisted commands — read-only commands are auto-allowed.
2. **A fabricated measurement reached a GitHub issue and was reported to the operator as fact.**
   decafclaw #710's body carried an intake "correction" built on `loop_breaker.last_signal()`, a
   method that does not exist, and a note length the code cannot produce. **Now retracted in place**
   with the reasoning. The lesson is the rule it broke: *construct fixtures from the code, never from
   plausibility.*
3. **`--allowedTools`, `--disallowedTools` and `--add-dir` are variadic**, so a positional prompt
   after them is swallowed. The driver passes prompts on **stdin**. Three earlier probes "worked" only
   by accident of flag ordering.
4. **Permission-rule paths need a `//` prefix when absolute.** `Edit(/abs/**)` does **not** block;
   `Edit(//abs/**)` does. Verified with file contents on disk, not the model's self-report.
5. **`gh pr checks --json state` returns `SUCCESS`, not `pass`** — the normalised field is `bucket`.
   A filter on `.state != "pass"` counts passing checks as failures.

## State

The skill is complete and all four routing paths have real-run evidence. Six PRs have gone through
it; five merged. The board-driver exists above the skill and needed **zero** skill changes, enforced
by `make skill-readonly`.

**Genuinely not yet proven:**

- **No loop has completed with two issues both reaching real verdicts.** Every multi-issue run so far
  exercised failure paths (budget exhaustion, a host crash, an orphaned child).
- **Phase 3 (conditional auto-merge)** — untouched, and gated on a `PreToolUse` merge-block hook.
- **The amendment path** — unexercised after six runs. Do not manufacture a case; it only fires when a
  frozen check is genuinely wrong.
- **Multi-phase `execute` with real implementer subagents** — every vehicle so far has been a tiny
  diff. decafclaw **#625** is the specced `needs-review` vehicle for this.

## The task: measure, don't add

**Only three of the skill's rules have measurements behind them** — the frozen-checks read-only rule,
the gameability rule, and `criteria-grammar.md`. Moves 4a–4c added roughly six more, all mechanical
corrections. The ratio is getting worse, and this project has already **added two rules from real
failures and then measured them away as redundant** (the goal-ambiguity tier trigger, the
withheld-decision exception). Both times the tell was the same: *the concept was already reachable
elsewhere in the skill, and the new rule restated it closer to where the failure was noticed.*

Ranked by value, with the discriminating question each needs:

1. **The discriminate rule** (`acceptance-criteria.md`: a check must fail today). Written from a
   dogfood failure, never tested as *wording*. Its intake-side sibling (oracle-must-exist) needed a
   micro-test to land, so this plausibly does too. **Fixture:** an issue whose obvious check passes
   today (the `pytest -W error::DeprecationWarning` shape from #638 is real and ideal). Control should
   stamp it `auto-ok`; treatment should catch the vacuity.
2. **The `bucket`-not-`state` and `--watch`-only rules** just added to `pr.md`. These are *commands*,
   so they need no wording test — but they do need a **dogfood**: the next run must reach a real
   verdict without a stale CI row. That is measurement by use, not by micro-test.
3. **`ci` carrying its sha.** New mechanism, untested end to end. The driver's `ci-stale` outcome has
   fixture tests but has never fired on a real PR.
4. **The tamper substitutes** (`clean-by-substitute` and its three stand-ins). Written from reasoning
   in move 2, never measured.

**Before adding any rule of your own:** grep the skill for the concept first. If it already exists
somewhere a mode reads, the addition will probably measure away. That check has a 2-for-2 record.

## Method, as practised here — the instrument rules were learned the hard way

- **Control vs treatment, 5+ reps per arm, read every flagged match by hand.** Variance is the metric.
- **Seal the fixture.** Subagents run *inside this repo* and will read its docs to check whether your
  fixture is real — one did. State that the provided text is the complete ground truth and that no
  tools are to be used.
- **Verdict labels must name actions, not intents.** A `STOP`/`PROCEED` pair once made a correct
  answer look wrong, because "confirm it still holds and then stop" fits neither label. Use
  action-named labels (`VERIFY-ONLY` / `RE-INTAKE`).
- **A result is only evidence once the instrument can fail.** Two fixtures were discarded in move 1
  for being non-discriminating. Prove your fixture can produce the wrong answer before trusting the
  right one.
- **A clean no-guidance control is unreachable on this machine** — the global CLAUDE.md leaks into
  every `claude -p` run (e.g. "no weakening test assertions"). Effects measured here are **lower
  bounds**. Say so.
- **"I wrote a guard" is not evidence.** Mutate the thing it guards and watch it fail. Three guards
  written in this project could not fail when first written, including two written minutes after
  re-reading the warning about exactly that.

## Constraints from real runs — don't rediscover these

- **The re-verification tax is structural.** `origin/main` moved during essentially every run; each
  landing invalidates the freeze sha and forces rebase + re-anchor + re-verify. Budget wall-clock
  accordingly.
- **Budget:** $12/issue is **not enough**. Runs have cost $4.41–$11.87 each, and one exhausted $12
  mid-review-cycle. Use ~$25.
- **A resume triggers context compaction before its first useful turn.** Resuming a 116-turn session
  spent real time compacting. Resumes are cheap in dollars, not free in latency.
- **A stream can carry more than one `result` message** — a successful one, then a spurious
  `error_during_execution` with cost 0. Take the max cost, not the last record.
- **`gh project item-list` silently truncates at 30.** Always pass an explicit high `--limit` and
  print the count read.
- **Board state is not reconciled after a crash.** decafclaw #656 is sitting at `In progress` with no
  branch or PR because a killed run moved it and nothing moved it back.
- **`gh` writes post as the repo owner**, so no gate row may rest on "a human reviewed this."

## The recurring defect class — the most useful thing to know

Six instances now of **a gate row satisfied by evidence adjacent to what it names**: `tamper: clean`
hiding an absent diff; `threads` citing a nonexistent command; `project-gates` meaning "the author's
laptop"; `project-gates` satisfied by substitute because `make check` could not run; `ci: 2/2 pass`
describing a commit that was no longer the head; and `G3`'s import guard blind to a capability
arriving as an object.

The countermeasure that keeps working is **not better wording** — it is making the value *carry what
it describes*, so substitution or staleness is mechanically visible (`clean-by-substitute`,
`ci: … @ <sha>`). Prefer that shape over an instruction whenever you can.

## Definition of done for move 5

- The discriminate rule micro-tested, with the result acted on (kept, trimmed, or cut) and recorded.
- One clean two-issue driver loop, both issues reaching real verdicts, no stale CI row.
- `design.md` updated; anything measured away actually deleted, not softened.

## Not in scope

- The `PreToolUse` merge-block hook and the GHA host. Both are real and both want their own session;
  the hook is a hard precondition for any *unwatched* host.
- Phase 3 auto-merge. Needs the hook plus at least one clean loop as evidence.
- decafclaw's `.nvmrc` drift (pins node 22; local runs 26). Filed context lives in #716/#717.

## Launcher prompt

> Continuing the `agent-session` skill in this repo (`~/devel/agent-sessions`). Read `CLAUDE.md`,
> `docs/design.md`, and `docs/handoff-measurement.md` — start with the handoff's **"Corrections to
> inherit"** section, because five things a naive read of the repo would pick up were asserted and
> later found false, including a fabricated measurement that reached a GitHub issue.
>
> The task is **move 5: measure the skill's unmeasured rules rather than adding more.** Only three of
> them have measurements behind them, and this project has twice added a rule from a real failure and
> then measured it away as redundant. Start with the **discriminate rule** in
> `references/acceptance-criteria.md`: micro-test it against a no-guidance control, 5+ reps per arm,
> and act on the result — including cutting it if it doesn't earn its place. Before adding any rule of
> your own, grep the skill for the concept first; that check has a 2-for-2 record.
>
> Two concrete side tasks. **decafclaw #656** is `auto-ok` and eligible — run the driver on it to
> validate the fixed driver end to end (`--max-budget-usd 25`; $12 is demonstrably too low). And the
> **two-issue loop has still never run**, because it needs two eligible `auto-ok` issues at once, which
> needs an `intake` pass on something new.
>
> **Nothing merges.** `eligible-for-auto-merge` is a finding the gate reports, not an action the driver
> takes. Follow the skill-authoring calibration in `CLAUDE.md`, and respect the handoff's instrument
> rules: seal any fixture, name verdict labels after actions rather than intents, and prove a fixture
> can produce the wrong answer before trusting the right one.
