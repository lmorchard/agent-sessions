# agent-sessions — conventions

A sequel to the `dev-session` skill, up-leveled for autonomy. `dev-session` structures
*building one thing*; `agent-session` front-loads the inputs an autonomous loop needs so the
middle can run unattended, with a human only at the ends where judgment lives.

**Read [docs/design.md](docs/design.md) first** — it's the source of truth for state
(build status, decisions, open questions). [docs/prior-art.md](docs/prior-art.md) has the
external survey. This file is conventions + gotchas only.

## What this is (and isn't)

- **Claude Code skill authoring**, `dev-session` lineage. The skill lives at
  `skills/agent-session/` in *this repo* — it is NOT installed in `~/.claude/skills/`. Test
  it by running its phase files manually (dogfooding), not via a registered skill.
- **The reference skill it derives from** is at `~/.claude/skills/dev-session/` (phases +
  references). Adapt from it; don't edit it.

## Governing principle

**An agent is only as autonomous as its verifier is trustworthy** — and *trustworthy* means
the oracle itself must exist and be correct (independent of the implementer, frozen before
implementation). Every mode moves a weak-oracle "a human decides" toward a strong-oracle
"a check proves it," or routes the work honestly (`needs-review`) when it can't.

## Skill architecture (decided)

- **One skill, multi-mode dispatcher** (not separate skills). The dispatcher reads ONLY the
  matching phase file — modes never co-reside, so adding modes costs no context and can't
  confound mid-phase. Explicit mode args; ask-don't-guess on ambiguity.
- **Shared engine in `references/`** (in-dir, so no cross-skill file-sharing problem):
  `acceptance-criteria.md` (the rules), `criteria-grammar.md` (EARS / Given-When-Then),
  `spec-template.md`, `documentarian-prompt.md`. Both `intake` and `triage` read them.
- **Heavy modes fan out to subagents** for working-context isolation (triage's batch scan;
  execution's per-phase work). Working context stays in the subagent, not the main loop.
- **The board-driver is NOT part of the skill.** The unattended burndown loop (pick Ready
  issue → run → tiered merge) is orchestration that *invokes* the skill, each run a fresh
  context. It lives above the skill (headless `claude -p` / GHA). Don't build it into a mode.

## Criteria + tier (the core contract)

- Every acceptance criterion **names a runnable check** (test / lint / assertion / eval).
  Escalation ladder: concrete test → property/invariant → human judgment.
- **Oracle-must-already-exist:** a criterion whose check needs a fixture/corpus/harness
  that must first be *built* is `needs-review`, not `auto-ok`. Verify oracles exist *now*
  (grep/run) before finalizing a criterion — don't assume.
- **Tier derives mechanically:** every criterion checkable AND no risk-gated path →
  `auto-ok`; any human-judgment criterion OR risk-gated path → `needs-review`. Risk-gated:
  auth, secrets, data migration/deletion, deploy/infra/CI, dependency changes.

## Working conventions

- **Skill-authoring discipline** (`superpowers:writing-skills`): this is a workflow/reference
  skill derived from a proven one — scaffold structurally without pressure-scenario TDD, but
  **micro-test any novel behavior-shaping wording** against a no-guidance control (5+ reps,
  read every flagged match by hand; variance is the metric). **Don't add nuance clauses** to
  a winning recipe — they degrade it consistent→noisy. **Dogfood after building** (run a real
  case; the dogfood catches what review + micro-tests can't).
- **gh CLI** for GitHub reads/writes; confirm auth before writing. When augmenting an issue,
  **preserve the author's text verbatim** (concatenate, don't regenerate).
- **Verify, don't assume** — this project's recurring theme. Check a claim (grep/run/read)
  before acting on it, including your own memory of the code/docs.
- Commit per logical step; keep changes small; update `docs/design.md` build-status when
  state changes; capture findings in Les's journal (`~/Documents/Obsidian/main/journals/`).
- Address the user as **Les**; push back on questionable approaches; smallest reasonable
  changes over cleverness.
