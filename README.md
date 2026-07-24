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

## Status

Bootstrapping. See [docs/design.md](docs/design.md) for the full design captured from the
originating brainstorm (2026-07-23).
