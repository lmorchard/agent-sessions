# agent-sessions

A sequel to the `dev-sessions` skill, up-leveled.

`dev-sessions` structures the work of **building one thing**. `agent-sessions`
structures the work so the **building runs itself** — front-loading the inputs an
autonomous agent loop needs, so the tedious middle (spec → research → plan → execute →
PR) can run with a human only at the ends where judgment actually lives.

## The governing principle

> **An agent is only as autonomous as its verifier is trustworthy.**

Wherever the loop can check its own work against a real oracle (`make test`, a lint gate,
an eval, a specific assertion), it can run unattended. Wherever the only honest check is
"a human looks at it and decides," that's where a human belongs. The whole system is
organized around that line.

## The two-skill system

A matched **producer / consumer** pair sitting at opposite ends of the loop:

| Skill | End of loop | Role |
|-------|-------------|------|
| **intake** (grilling-derived) | weak-oracle *front* | Human-in-loop. Manufactures the scarce input: verifiable acceptance criteria + escalation tier. Emits a filable issue. |
| **execution** (self-driving) | strong-oracle *middle* | Autonomous. Consumes a well-specified issue; runs spec → research → plan → execute → PR, stopping at the merge gate. |

Between them sits the **board** — a triaged queue of ready, tiered issues — and after
them, a **tiered merge gate** (auto-merge only what's `auto-ok` and all-green; everything
touching auth/data/deploy/deps stays human-gated).

The two skills share a **contract**: the acceptance-criteria format and escalation labels.
Design it once; both sides read from it, or it drifts.

## Reality check (2026-07-23)

The existing `dev-session` skill **already implements the producer/consumer core** above —
`file` produces a spec-embedded issue, `express` autonomously consumes it, with a research
substep, a recommended-answer interview, board transitions, and a crude autonomy tier all
present. So this repo is not a reimplementation. It's an **upgrade + orchestration layer**.
The genuinely new, high-leverage parts:

1. **Verifiable acceptance criteria as first-class** — make each criterion name a runnable
   check (the "spec names its own verifier" upgrade to the spec template + readiness gate).
2. **A durable, verifiability-derived tier label** stamped at filing time, so a loop can route on it.
3. **A conditional merge gate** (auto-merge only `auto-ok` + all-green + no unresolved threads).
4. **A board-level driver** that picks the next Ready issue and runs the loop unattended.

(1)+(2) extend `dev-session`; (3)+(4) sit above it. See [docs/design.md](docs/design.md).

## Status

Scaffolding the **`agent-session`** skill (`skills/agent-session/`) — one skill, multi-mode
dispatcher (dev-session lineage), shared in-dir reference "engine," heavy modes fan out to
subagents, board-driver lives above as orchestration.

- **Built + validated:** `intake` (spec a new/existing issue → verifiable criteria + tier) —
  micro-tested *and* dogfooded end-to-end on a real issue. `triage` (batch-augment via
  subagent fan-out) — built, not yet dogfooded. Shared engine: `acceptance-criteria.md`,
  `criteria-grammar.md`, `spec-template.md`, `documentarian-prompt.md`.
- **Pending:** execution modes (`plan`/`execute`/`express`/`pr`, adapted from dev-session)
  + tiered merge gate, then the board-driver.

See [docs/design.md](docs/design.md) (design + build log) and [docs/prior-art.md](docs/prior-art.md).
