# Handoff: build the board-driver (move 3) — DONE, kept as a record

> **Move 3 is complete.** This brief is now a record of what it asked for, not a task. The driver is
> at `driver/agent-session-driver.sh`; the outcome is in
> [design.md](../design.md)'s move-3 section and
> [dev-sessions/2026-07-25-0926-board-driver/](dev-sessions/2026-07-25-0926-board-driver/).
>
> **How the brief held up.** Its central bet paid off again: fresh context was load-bearing, and for
> the reason it claimed. Four of its five "don't rediscover these" constraints were confirmed live
> (the re-verification tax, the 1-in-8 conversion, the gate block as interface, squash unreachability
> stayed untested). Two of its premises were **wrong in ways that mattered**, and both were caught by
> checking rather than trusting:
>
> - **"#585 — the remaining `auto-ok` issue, already… ready"** meant *spec*-ready. On the board #585
>   was in **Backlog**, and the `Ready` column's three issues carry no marker at all. That empty
>   intersection is what forced Q2's answer.
> - **`design.md`'s capability ladder was wrong about `--bare`** (unusable without an API key, and it
>   drops the CLAUDE.md `express` needs) and **incomplete about `dontAsk`** (denies unlisted
>   *mutations*; auto-allows read-only commands). It also missed `--max-budget-usd` entirely.
>
> The brief's guardrails all held: nothing merged, no phase file was edited (mechanically enforced by
> `make skill-untouched`), and the one new rule was checked against the added-then-measured-away
> pattern before being kept.
>
> **The finding it could not have anticipated**, and the top item for move 4: the merge gate can
> report `eligible-for-auto-merge` while GitHub's required CI is still `pending`, because
> `project-gates` records a local `make check` and cites no check runs.

Task brief for a fresh context. Read `CLAUDE.md` and `docs/design.md` first — especially the build
status from the bottom up (the micro-test, move 2b, move 2, the consolidation pass). This doc is the
task, its constraints, and the things that are in nobody's head anymore.

## Why a fresh context specifically

Not hygiene. The driver's whole job is to **decide what to trust about the skill from outside it**,
and the context that built the skill is the worst-positioned reader of that question — it knows which
rules are load-bearing by memory rather than by evidence, which is exactly the bias the driver must
not inherit. `design.md` is the priming document and it is current.

Corollary while you work: if you find yourself confident about a skill behaviour that isn't written
in `skills/agent-session/` or measured in `design.md`, that's memory you don't have. Check it.

## State

The skill at `skills/agent-session/` is complete and has real-run evidence for **every mode and all
four routing paths**:

| Path | Evidence |
|---|---|
| `intake` (augment) | starnet #129, decafclaw #638, #649 |
| `triage` (batch) | 8 decafclaw issues, 0/17 proposed criteria passed today |
| `plan` → `execute` → `pr` | decafclaw #638 → PR #659 (merged) |
| `express`, `auto-ok`, → `eligible-for-auto-merge` | decafclaw #586 → PR #665 (merged) |
| `express`, `needs-review`, → `human-merge-required` | decafclaw #649 → PR #686 (merged) |

**Only the amendment path is unexercised**, and it resists deliberate testing: it fires only when a
frozen check is genuinely wrong, which is a bug you don't get to schedule. #649 came close — a frozen
check constrained a denial message and complying rather than amending was correct — so it stayed
untested for the right reason. Don't manufacture a case for it.

## The task

**Build the board-driver: the unattended loop that picks the next Ready issue, runs `express` on it,
and stops at the gate.** It lives *above* the skill — orchestration that invokes the skill, each run
a fresh context. Nothing in `skills/agent-session/` should need to change for it to work; if you find
yourself editing a phase file to make the driver possible, that's a signal the boundary is wrong.

It **must not merge anything.** `eligible-for-auto-merge` is a finding the gate reports; acting on it
is a separate, later decision (phase 3 in `design.md`'s rollout).

## Open design questions — these are the actual work

1. **Local `claude -p` loop vs scheduled GHA.** Unresolved, and the answer probably differs for the
   first ten runs (watchable, interruptible, on your machine) versus steady state (no laptop
   required). `design.md`'s capability ladder has the verified specifics: `--bare`,
   `--permission-mode dontAsk`, `--output-format json` carrying `total_cost_usd` + `session_id`.
   **Avoid `--dangerously-skip-permissions` / `bypassPermissions`** — scoped `--allowedTools` plus
   `dontAsk` was the agreed floor.
2. **How it reads and filters the queue.** The board is now declared machine-readably in decafclaw's
   `CLAUDE.md` (owner `lmorchard`, project 6, `Status`, and the exact column names — note `In
   progress` / `In review`, lowercase). Tier lives in the **issue body's Tier section**, which is
   authoritative; a label is only a convenience index and decafclaw has no tier labels at all.
3. **What it does with each verdict.** `human-merge-required` → leave it and move on? Notify? Stop the
   loop? A driver that keeps going accumulates open PRs; one that stops on the first one barely runs.
4. **Failure and cost ceilings.** What happens when `express` stops mid-run for an escalation the
   driver can't answer (an amendment, a check that passes at freeze, a spec that fails readiness)?
   Those are *designed* stops, so they'll happen — the driver needs a "park it and move on" path, not
   a retry.

## Constraints that came out of real runs — don't rediscover these

- **The re-verification tax is real.** `origin/main` moved **three times** during the single #649 run,
  once into the exact function under change. Each move forced a rebase, a freeze-sha re-anchor, and a
  full re-verify. A driver needs a policy for "upstream landed mid-run" beyond retrying, and should
  expect wall-clock per issue to exceed the work itself on an active repo.
- **`gh` writes post as the repo owner's account.** PR #686 shows a "review by lmorchard" that is the
  agent's own thread reply. **No gate row may rest on "a human reviewed this"** — it is
  self-satisfiable in this setup. If the driver ever needs to distinguish human from agent activity,
  that needs a mechanism that doesn't exist yet.
- **Conversion rate is roughly 1-in-8.** The `triage` batch scored 8 issues and produced 3 `auto-ok`,
  of which only **one** was genuinely ready. Queue length is not throughput; expect most Ready issues
  to bounce back to `intake`.
- **The gate block is the interface.** Read `<!-- agent-session:gate -->` from the PR body rather than
  re-deriving the gate. Vocabulary is in `references/pr-body-template.md`. Two values matter to a
  machine reader: `verdict: pending` means the run hasn't derived it yet (do not act), and
  `tamper: clean-by-substitute` means the mechanism was unavailable rather than passing.
- **Squash makes the freeze commit unreachable.** Post-squash it's a dangling local object, not on
  origin, not an ancestor of the branch — verified. The pre-squash verdict recorded in `checks.md` is
  the only durable evidence, so a driver auditing a merged PR must read that, not re-run a diff.

## First vehicle

**decafclaw #585** — the remaining `auto-ok` issue, already carrying marker + criteria + guards +
tier. Small, and the point of the first run is the *driver*, not the work.

Not #685 (child-agent stall): it carries three candidate approaches, so it needs a decision and would
land `needs-review` — the wrong shape for testing an unattended path.

## Guardrails

- **Nothing merges.** Not with `gh pr merge`, not with `--auto`.
- **Don't edit the skill to suit the driver** without saying why; the boundary is a decision, not an
  accident.
- **Skill-authoring calibration still applies** if you touch skill wording: micro-test novel
  behaviour-shaping wording against a no-guidance control, 5+ reps, read every match by hand. And note
  the standing result — **two rules have now been added from real failures and then measured away**
  (the goal-ambiguity tier trigger, the withheld-decision exception). Both restated something already
  reachable elsewhere in the skill. Check for that before adding.
- **Seal any micro-test fixture.** Subagents run inside this repo and *will* read its docs to check
  whether your fixture is real — one did. State that the provided text is the complete ground truth
  and no tools are to be used, and make verdict labels name actions rather than intents.
- Commit per logical step; update `design.md` build status; capture findings in Les's journal
  (`~/Documents/Obsidian/main/journals/`).

## Definition of done for move 3

- A driver that picks one Ready `auto-ok` issue, runs the skill end to end unattended, and reports the
  gate verdict without merging.
- Run against #585 for real, with an honest account of where it needed a human anyway.
- The four open questions above answered *in writing*, not just in code.
- `design.md` + journal updated.

## Launcher prompt

> Continuing the `agent-session` skill in this repo (`~/devel/agent-sessions`). Read `CLAUDE.md`,
> `docs/design.md`, and `docs/handoff-board-driver.md`, then build the board-driver — the unattended
> loop that picks the next Ready issue, runs `express`, and stops at the gate. It lives above the
> skill; don't edit phase files to accommodate it without saying why. Nothing merges. First vehicle is
> decafclaw #585. Answer the four open design questions in writing as you go, and follow the
> skill-authoring calibration in `CLAUDE.md` if you touch any skill wording — note that two rules have
> already been added from real failures and then measured away, so check whether a new rule restates
> something already reachable before adding it.
