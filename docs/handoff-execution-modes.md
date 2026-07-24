# Handoff: adapt the execution modes (move 1)

Task brief for a fresh context continuing `agent-session`. Read `CLAUDE.md` and
`docs/design.md` (build status + "the four gaps" + "the dev-session finding") first — this
doc is just the task and its guardrails.

## The task

Add the back-half execution modes to `skills/agent-session/`, adapted from
`~/.claude/skills/dev-session/phases/` (`plan.md`, `execute.md`, `pr.md`, `express.md`) +
`references/` (`plan-template.md`, `pr-body-template.md`). The front-of-funnel (`intake`,
`triage`, shared engine) is built and validated; the dispatcher in `SKILL.md` currently
marks these modes "pending — adapt from dev-session."

## What's the *delta* from dev-session (why this isn't a copy)

dev-session's execute/pr/express are close — adapt, don't reinvent. The specialization:

1. **Consume the verifiable-criteria spec.** These modes run against an issue carrying the
   `<!-- agent-session:spec -->` marker with EARS/Given-When-Then criteria that each name a
   CHECK. The criteria's **checks are the gate** — `execute` isn't done until every
   criterion's check passes (not "tests pass" in the abstract — *these* checks).
2. **Verifier independence + frozen checks.** The acceptance checks are authored at intake
   and **must not be weakened during execute** (an implementer editing its own oracle is the
   failure mode). dev-session already uses subagent-driven execution + two-stage review
   (spec-compliance then code-quality) — build on that so the check-author/verifier is a
   different context than the implementer. Freeze the checks before implementation.
3. **Tiered merge gate.** `pr`/`express` end at the gate: `needs-review` issues always stop
   for human merge; `auto-ok` issues *may* be eligible for auto-merge but only with all
   required checks green + no unresolved review threads. **The skill supports the gate; it
   does NOT implement the unattended auto-merge loop** — that's the board-driver, which lives
   above the skill and is out of scope here.
4. **Read the tier to set autonomy.** `express` should respect the tier: proceed
   autonomously through PR for `auto-ok`; for `needs-review`, surface to the human at the
   points the tier's reason implies.

## Guardrails

- **Skill-authoring calibration** (`CLAUDE.md`): scaffold the phase files structurally
  (adapting proven dev-session prose is fine, no pressure-test needed); **micro-test only
  genuinely novel behavior-shaping wording** (e.g. the "run the criteria's checks as the
  gate" instruction, or the merge-gate decision) against a no-guidance control, 5+ reps.
- **Do NOT build the board-driver** or any unattended auto-merge here. Skill supports the
  gate; orchestration is separate/later.
- Keep the dispatcher honest — update `SKILL.md`'s table as each mode lands.
- Commit per mode; update `docs/design.md` build-status when done.

## Definition of done for move 1

- `phases/plan.md`, `execute.md`, `pr.md`, `express.md` exist and are specialized per the
  delta above; `SKILL.md` dispatcher updated; any needed templates added to `references/`.
- Novel wording micro-tested where it exists.
- **Dogfood:** run one issue through `plan → execute → pr` stopping at the merge gate — e.g.
  the already-augmented starnet #129 (`auto-ok`), or a small decafclaw issue. Capture what
  the run surfaces (it will surface something — the front-of-funnel dogfood did).
- design.md build-status + journal updated.

## Launcher prompt (paste into a fresh Claude Code session in this repo)

> Continuing the `agent-session` skill in this repo (`~/devel/agent-sessions`). Read
> `CLAUDE.md`, `docs/design.md`, and `docs/handoff-execution-modes.md`, then adapt the
> execution modes (`plan`/`execute`/`express`/`pr`) from `~/.claude/skills/dev-session/`
> into `skills/agent-session/`, specialized per the handoff's delta (consume the
> verifiable-criteria spec, verifier-independence + frozen checks, tiered merge gate, read
> the tier for autonomy). Follow the skill-authoring calibration in CLAUDE.md. Don't build
> the board-driver. Start by proposing the adaptation plan before writing.
