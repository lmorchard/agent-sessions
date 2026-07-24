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
| `plan` | `phases/plan.md` | Freeze the acceptance checks, then plan vertical slices against current code |
| `execute` | `phases/execute.md` | Execute the plan; the criteria's checks are the gate, graded by a context that didn't write the code |
| `express` | `phases/express.md` | Consume a specified issue autonomously through PR; the tier sets the autonomy |
| `pr` | `phases/pr.md` | Self-review, squash, push, PR, review cycle, then stop at the tiered merge gate |

The **producer/consumer seam** is the `<!-- agent-session:spec -->` marker: `intake` and
`triage` produce issues carrying it; `plan`/`execute`/`express` refuse to run without it.

## The shared engine (in-dir references)

Two engines, front and back, each read by more than one mode. They live in `references/` so
no mode duplicates them (duplication drifts — a correctness bug, not just untidy). Modes read
them only on reaching the relevant step:

**Front half — making criteria checkable** (read by `intake`, `triage`):

| File | What it holds |
|---|---|
| `references/acceptance-criteria.md` | The core rules: every criterion names a runnable check; oracle-must-already-exist; concrete-test → property → human-judgment ladder; tier derivation + risk-gated paths |
| `references/criteria-grammar.md` | EARS + Given-When-Then syntax reference (patterns, templates, how to pick) |
| `references/spec-template.md` | Spec skeleton + readiness checklist, gating on verifiability |

**Back half — keeping the checks trustworthy** (read by `plan`, `execute`, `pr`):

| File | What it holds |
|---|---|
| `references/frozen-checks.md` | The verification contract: the `checks.md` manifest, the freeze commit, the read-only rule, the independent verifier, the tamper diff, the amendment path |
| `references/session-setup.md` | Branch + worktree + session dir + marker/tier detection (shared by `plan` and `express`) |
| `references/plan-template.md` | `plan.md` skeleton — Phase 0 freeze, criteria-per-phase traceability |
| `references/pr-body-template.md` | PR body skeleton — per-criterion results + the `agent-session:gate` block |

**Either half:** `references/documentarian-prompt.md` (neutral framing for research subagents),
`references/github-projects.md` (optional board transitions).

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
- **Tier is durable, and the issue body owns it.** Derived at intake/triage time (see
  `acceptance-criteria.md`) and written into the spec's Tier section *with its reason*. A tier
  label on the issue is a convenience index for querying — if the two disagree, surface the
  conflict rather than picking one.
- **Makefile-first.** Verification commands assume `make lint` / `make test` / `make check`.
  If the project lacks a target, run the native tool, say so, and offer to add the target
  rather than reconstructing the command in three phases.
- **The skill never merges.** No `gh pr merge`, with or without `--auto`. `pr` derives and
  reports the merge-gate verdict; acting on it belongs to a human or the board-driver.

## When NOT to use

- One-line tweaks / doc fixes where a spec costs more than the change.
- Feel-driven work (subjective visual/interaction feel a spec can't pin down) — prototype
  interactively instead, as `dev-session` does.
