---
name: agent-session
description: "Use when turning a GitHub issue or request into a spec with verifiable, machine-checkable acceptance criteria; when triaging or augmenting a backlog of under-specified issues so an autonomous loop can consume them; or when running a semi-autonomous issue → spec → PR loop where 'done' must be checkable by a test, lint, or assertion. Triggers: /agent-session, its mode names (intake/triage/plan/execute/express/pr), picking up a project-board issue that lacks acceptance criteria."
---

# Agent Session

A sequel to `dev-session`, up-leveled for autonomy. `dev-session` structures *building
one thing*; `agent-session` front-loads the inputs an autonomous loop needs so the middle
can run unattended, keeping a human only at the ends where judgment lives.

**Governing principle:** *an agent is only as autonomous as its verifier is trustworthy.*
Every mode below exists to move a weak-oracle "a human decides" into a strong-oracle "a
check proves it" — or to route the work honestly when it can't.

## Dispatcher

Parse the first argument and read ONLY the matching phase file. Ignore the others. Do not
guess the mode from fuzzy language — if the argument is missing or ambiguous, STOP and ask
which mode, or assess the current session state and suggest one.

| Argument | Phase file | Purpose |
|---|---|---|
| `intake` | `phases/intake.md` | Interview a new request *or* existing issue → spec with verifiable acceptance criteria → file/update the issue with a tier label |
| `triage` | `phases/triage.md` | Batch: scan a repo/board for under-specified issues, score them (subagent fan-out), propose criteria, augment the weak ones |
| `plan` | *(pending — adapt from `dev-session` plan)* | Implementation plan from the spec, generated against current code |
| `execute` | *(pending — adapt from `dev-session` execute)* | Execute the plan; verifier kept independent of implementer |
| `express` | *(pending — adapt from `dev-session` express)* | Interactive intake → autonomous through PR |
| `pr` | *(pending — adapt from `dev-session` pr)* | Self-review, squash, push, PR, review cycle; tiered merge gate |

The execution modes are being adapted from `dev-session` and are not yet specialized here;
until they land, run the corresponding `dev-session` phase.

## The shared engine (in-dir references)

Both `intake` and `triage` run the *same* requirements engine. It lives in `references/`
so neither mode duplicates it (duplication drifts — a correctness bug, not just untidy).
Each mode reads these only when it reaches an interview/criteria step:

| File | What it holds |
|---|---|
| `references/acceptance-criteria.md` | The core: every criterion names a runnable check; EARS / Given-When-Then grammar; verifier-independence; tier derivation |
| `references/spec-template.md` | Spec skeleton + readiness checklist, upgraded to require verifiable criteria |

## Context management (the reason for this structure)

- **The dispatcher is a lazy-loader.** Only one phase file is ever in context. Modes never
  co-reside, so their instructions cannot bleed into each other — the same laziness that
  saves tokens also prevents cross-mode confusion.
- **Heavy modes fan out to subagents.** `triage` (reading/scoring many issues) and the
  execution modes (reading/editing code) do the token-heavy work in *subagent* contexts
  and return only compact results. Working context stays in the subagent, not the main
  loop. See `superpowers:dispatching-parallel-agents`.
- **The board-driver is NOT part of this skill.** The unattended burndown loop (pick next
  Ready issue → run → tiered merge) is orchestration that *invokes* this skill repeatedly,
  each invocation a fresh context. It lives above the skill as a script / GitHub Action.

## Shared conventions

- **gh CLI** for all GitHub reads/writes. Confirm auth with `gh repo view` before writing.
- **Explicit mode arguments.** `/agent-session <mode>` — the dispatcher never infers.
- **Verification before completion.** Never claim a criterion is checkable, a spec ready,
  or a phase done without having run the check and read the output. Evidence before claims.
- **Tier label is durable.** Derived at intake/triage time (see `acceptance-criteria.md`)
  and written onto the issue, so a downstream loop can route on it.

## When NOT to use

- One-line tweaks / doc fixes where a spec costs more than the change.
- Feel-driven work (subjective visual/interaction feel a spec can't pin down) — prototype
  interactively instead, as `dev-session` does.
