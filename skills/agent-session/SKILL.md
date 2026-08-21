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
| `rethink` | `phases/rethink.md` | Retire a failed execution attempt, tombstone the old spec, and pivot back into `intake` to rethink the approach |
| `plan` | `phases/plan.md` | Freeze the acceptance checks, then plan vertical slices against current code |
| `execute` | `phases/execute.md` | Execute the plan; the criteria's checks are the gate, graded by a context that didn't write the code |
| `express` | `phases/express.md` | Consume a specified issue autonomously through PR; the tier sets the autonomy |
| `open_pr` | `phases/open_pr.md` | Self-review, push branch, open PR with pending verdict |
| `address_comments` | `phases/address_comments.md` | Address review comments on open PR |
| `fix_ci` | `phases/fix_ci.md` | Fix failing CI checks |
| `grade_gate` | `phases/grade_gate.md` | Derive merge gate verdict and update PR block |
| `fix_conflict` | `phases/fix_conflict.md` | Rebase a PR whose branch has diverged from its base and resolve the conflicts |
| `refine` | `phases/refine.md` | Rewrite a `needs-review` issue's criteria into automatable checks and upgrade it to `auto-ok`; leave it alone if it cannot |

The **producer/consumer seam** is the `agent-session:spec` label: `intake` and
`triage` produce issues carrying it; `plan`/`execute`/`express` refuse to run without it.

## The shared engine (in-dir references)

Two engines, front and back, each read by more than one mode. They live in `references/` so
no mode duplicates them (duplication drifts — a correctness bug, not just untidy). Modes read
them only on reaching the relevant step:

**Front half — making criteria checkable** (read by `intake`, `triage`):

| File | What it holds |
|---|---|
| `references/acceptance-criteria.md` | The core rules: every criterion names a runnable check; the two tests every check must pass (oracle exists / not satisfiable without the work); criteria vs. guards; tier derivation |
| `references/criteria-grammar.md` | EARS + Given-When-Then syntax reference (patterns, templates, how to pick) |
| `references/spec-template.md` | Spec skeleton + readiness checklist, gating on verifiability |

**Back half — keeping the checks trustworthy** (read by `plan`, `execute`, `open_pr`, `grade_gate`):

| File | What it holds |
|---|---|
| `references/frozen-checks.md` | The verification contract: the `checks.md` manifest, the freeze commit, the read-only rule, the independent verifier, the tamper diff, the amendment path |
| `references/session-setup.md` | Branch + worktree + session dir + marker/tier detection (shared by `plan` and `express`) |
| `references/plan-template.md` | `plan.md` skeleton — Phase 0 freeze, criteria-per-phase traceability |
| `references/pr-body-template.md` | PR body skeleton — per-criterion results + the `agent-session:gate` block |

**Either half:** `references/documentarian-prompt.md` (neutral framing for research subagents),
`references/github-projects.md` (optional board transitions).

## Shared conventions

- **Heavy modes fan out to subagents.** `triage` (scoring many issues) and the execution modes
  (reading/editing code) do the token-heavy work in *subagent* contexts and return compact
  results — working context stays in the subagent. See `superpowers:dispatching-parallel-agents`.
- **Explicit mode arguments.** `/agent-session <mode>` — the dispatcher never infers.
- **Verification before completion.** Never claim a criterion is checkable, a spec ready,
  or a phase done without having run the check and read the output. Evidence before claims.
- **Makefile-first.** Verification commands assume `make lint` / `make test` / `make check`.
  If the project lacks a target, run the native tool, say so, and offer to add the target
  rather than reconstructing the command in three phases.

## Out of scope

**The board-driver is not part of this skill.** The unattended burndown loop (pick next Ready
issue → run → tiered merge) is orchestration that *invokes* this skill repeatedly, each run a
fresh context. It lives above the skill as a script / GitHub Action. Nothing here merges a PR.

## The Ceremony Threshold (When NOT to use full modes)

Not every task needs the full `plan` → `execute` → `open_pr` ceremony with frozen checks and discrete phases.

**Small/Tactical (< 3 steps, bug fixes, single-file refactors):** Skip the heavy artifacts
(`plan.md`, the freeze commit, the tamper diff, the per-phase machinery). Keep state in-context
with the `todowrite` tool.

**What you do not skip is the oracle.** Before you change anything, write a `checks.md` naming at
least one runnable check — the exact command, and what its output has to say. One line is enough.
Then run it and watch it fail.

`checks.md` is the independent verifier's *entire input*, so leaving it out does not make the
verification lighter — it makes it impossible, and the gate then rests on CI, threads and tier
alone. **The frozen-check machinery is optional at this size; the check itself is not.** No freeze
commit, no tamper diff — just a named command, chosen before the work, that could have failed.

**Large/Architectural (new features, multi-session work, high ambiguity):** Use the full structured flow below, freezing checks and building vertical slices to ensure verifiable outcomes.

## When NOT to use this skill

- Feel-driven work (subjective visual/interaction feel a spec can't pin down) — prototype
  interactively instead, as `dev-session` does.
