# Documentarian subagent — negation rules

How to frame the codebase-research subagent in `intake` (blank-slate) and `triage`. The
goal is a *factual map of what exists*, not a proposal. A research agent that drifts toward
"here's how to fix it" contaminates the criteria step with a solution before the design
decisions are made.

## Rules for the dispatched subagent

Put these in the subagent's prompt:

- **Describe what exists; do NOT propose changes, fixes, or improvements.** Report current
  behavior only.
- **Ground every claim in `file:line` references.** "The loop aborts at `execute.js:184`",
  not "the loop probably aborts somewhere."
- **Answer ONLY the questions asked.** No editorializing, no "you could…", no roadmap.
- **Frame questions around existing components and flows, not the desired feature.** Ask
  "how does detection currently cause an abort?" not "how should back-off work?" — the
  subagent should map the current system, not design the new one.
- **If something doesn't exist, say so plainly** (e.g. "no cooldown timer exists; the only
  avoid-state is a one-cycle score penalty at `explore.js:19`"). A confirmed absence is as
  valuable as a presence — it's often what makes a criterion new work vs. already-done.

## Ask 3–5 neutral questions

Frame them as "how does X work today?" targeting the areas the requirement will touch.
Save findings to `research.md` (~300 lines max, prefer `file:line` over prose).

Two question types worth including when they apply (cheap at research time, expensive at
review time):

- **Oracle-existence.** For each thing the requirement will need to *check*, ask whether
  the measurement/test/harness that would verify it **exists today** — the metric, the
  fixture, the way to reproduce the scenario. This feeds the criteria step directly: a
  criterion whose oracle doesn't exist yet is `needs-review`, not `auto-ok` (see
  `acceptance-criteria.md` → "Three tests every check must pass").
- **Class-of-bug analogues / generic consumers.** When the task is "fix X for Y" or "add a
  new kind of Z", ask what *else* flows through the same code path (other call sites, a
  catch-all/`default:` branch, a registry that auto-picks up new entries). Surfacing these
  now costs one question; missing them ships wrong behavior that passes tests.
