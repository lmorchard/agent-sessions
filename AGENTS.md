# agent-sessions — conventions

A sequel to the `dev-session` skill, up-leveled for autonomy. `dev-session` structures
*building one thing*; `agent-session` front-loads the inputs an autonomous loop needs so the
middle can run unattended, with a human only at the ends where judgment lives.

**Read [docs/design.md](docs/design.md) first** — the design, current state, and roadmap. Then
**[docs/findings.md](docs/findings.md)** — the durable lessons: recurring defect classes, the
evidence ledger, the instrument rules, and the verified command gotchas. **Read the gotchas before
writing any flag list, gate row or `gh` query**; several are the opposite of what the flag names
suggest. [docs/build-log.md](docs/archive/build-log.md) is the chronology — provenance only, nothing reads
it to decide. [docs/prior-art.md](docs/prior-art.md) has the external survey. This file is
conventions + gotchas only.

## What this is (and isn't)

- **An autonomy harness with a skill component.** The system's orchestration lives in
  `src/agent_sessions/driver/`; `driver/agent-session-driver.sh` is a compatibility launcher. The
  skill component lives at `skills/agent-session/` in *this repo* — it is NOT installed in
  `~/.Codex/skills/`. Test it by running its phase files manually (dogfooding), not via a
  registered skill.
- **The reference skill it derives from** is at `~/.Codex/skills/dev-session/` (phases +
  references). Adapt from it; don't edit it.

## Project board

<https://github.com/users/lmorchard/projects/9> — the `agent-sessions` backlog. Status column
options, read from `gh project field-list 9 --owner lmorchard` and authoritative over this line:

- `ready: Ready`
- `in_progress: In progress`
- `in_review: In review`
- `done: Done`

(plus `Backlog` ahead of `Ready`.) Matches boards 6/7/8 exactly, as of 2026-07-28 — it was created
by `gh project create`, which applies no template, so it started on the bare `Todo` / `In Progress`
/ `Done` default and was renamed. **Read the field list anyway; don't trust this line.**

## Risk-gated paths (off-limits to unattended work)

`skills/agent-session/references/acceptance-criteria.md`'s **trigger 2** is
project-configurable — it fires on anything the project's instruction file marks off-limits.

**The default is `needs-review`: anything not named drivable below is gated.** This is an allowlist,
not a denylist, and the direction is the whole point. Decided 2026-07-29 after the partition went
stale by omission **twice in two days** — once when the classifier moved into the then-current
`driver/gate.py` on 2026-07-29, and once when `scripts/` was created (in the very commit that added
the "ask what it just invalidated" section below). The 2026-08-09 Python conversion later superseded
that classifier path. Under a denylist, a directory nobody has classified reads as *drivable*, so
the failure mode of forgetting is that unreviewed work runs unattended, and a triage scanner has to
guess by analogy.
Under an allowlist, forgetting is merely inconvenient: new code routes to a human until someone says
otherwise. **A path this file does not mention is not a question to resolve by analogy — it is
`needs-review` until listed.**

For this repo, the gated paths worth calling out by name, because the *reason* is what generalizes:

- **`.github/**` — CI workflow definitions.** Gated because they define the environment the checks run in.
- **`skills/**` — any issue whose work would edit a skill file is `needs-review`**, however cleanly
  its criteria reduce to runnable checks. The reason is structural, not stylistic: here the
  implementer's work product *is* the instructions grading it, which is the single failure this
  whole system exists to prevent. `make skill-readonly` enforces the same boundary for a *hosted*
  run; this line is its **intake-time counterpart**, and it takes effect without any skill file
  being touched.

- **`src/agent_sessions/driver/gate.py` — the oracle, and therefore off-limits too.** This module
  parses the merge-gate block and classifies a run's outcome; the coordinator calls `gate.classify`
  at both recovery and normal-run classification. **An issue whose work edits it is editing the code
  that grades its own run** — the implementer is authoring its own oracle, one level removed from
  the skill. The `skills/**` rule does
  not cover it, and this line was added because the move-7 partition missed it: `driver/` was
  wholly drivable before the classifier moved there.

- **`src/agent_sessions/driver/agent_session_driver.py` — the current home of the outcome
  *routing*.** Les gated that responsibility on 2026-08-03 while it still lived in the Bash driver;
  the 2026-08-09 conversion moved it into the coordinator without changing the decision. The
  coordinator holds the parking case lists and the budget-reclassification thresholds, so a run
  could in principle edit them to flatter its own record. This was previously named as an accepted
  residual risk with the note *"revisit if a run ever touches that routing."* **That clause has now fired
  three times** — on #39, on #58, and it would fire again on [#82](https://github.com/lmorchard/agent-sessions/issues/82)
  — and PR #78's gate block escalated it in writing rather than resolving it. A revisit trigger that
  keeps firing and never converts is not a trigger; it is a deferral. So it converted.

  **The cost is stated, because it is real and it is the reason this was a human's call.** Path
  granularity cannot express *"this file except its classification path,"* so gating the routing
  gates the whole coordinator — the largest single piece of orchestration in the repo, and the
  thing most likely to need work. Driver changes now route to a human. If that proves too coarse,
  the fix is to extract the outcome routing into its own module the way `gate.py` was extracted,
  and gate *that*; **it is not to quietly widen the allowlist back.**

- **`driver/agent-session-driver.sh` — the compatibility launcher.** Since the 2026-08-09 Python
  conversion it only enters the packaged coordinator. It remains gated because the allowlist has
  never explicitly reclassified it as drivable; becoming thin does not silently widen the
  partition.

Plus the standing defaults trigger 2 already names: auth/authorization, secrets, data
migration/deletion, deploy/infra/CI config, dependency changes.

### What "the oracle" means — the narrow reading

Decided 2026-07-29, because the question kept recurring one detector at a time and each answer was
being re-derived by analogy. **Gated means the code decides whether *this run's own work* is
acceptable to merge.** That is the outcome classifier, and — since 2026-08-03 — the routing that
consumes its verdict. A test suite, a lint recipe or a doc-rot detector grades the *work*; only
`src/agent_sessions/driver/gate.py` and the coordinator's outcome routing decide how the driver
classifies and records the result.

`src/agent_sessions/scripts/docs_check.py` grades documentation rather than the run's verdict, but
it remains `needs-review` because it is an unlisted shipping `src/**` path. Its root-level test,
`scripts/test_docs_check.py`, is drivable. The same distinction applies to other shipping detectors
under `src/agent_sessions/scripts/` and their root-level tests under `scripts/`.

**The residual risk, named rather than gated away.** Drivable harness tests can weaken the
assertions that protect gated shipping code. The broad reading would close that, but it would also
sweep in `tests/driver/test_driver.py`, `tests/driver/test_gate.py`, `tests/driver/test_park_state.py`, root-level
detector tests, and the `Makefile` recipes — all needed for this repo to dogfood itself. The
mitigations are tests that import what ships, `make check` in every PR, and a human at the merge
gate. Revisit if an unattended run ever weakens a test to admit its own change.

### Drivable (the allowlist)

- **`tests/**` and `driver/**`, except `driver/agent-session-driver.sh`** — compatibility assets, fixtures, and
  the `tests/driver/test_*.py` harness tests. Note what this leaves: the tests are drivable, while the
  launcher and every unlisted `src/**` implementation path remain `needs-review`.
- **`docs/`** — including `findings.md` and session notes.
- **`Makefile`**.
- **`scripts/**`** — root-level tests and support assets, including
  `scripts/test_docs_check.py`. This does not include the shipping implementations under
  `src/agent_sessions/scripts/`, which remain gated by default. Added 2026-07-29; it was unlisted
  from creation until then, which is what prompted the allowlist.

No `src/**` path is implicitly drivable. The two Python paths named above explain why they are
especially sensitive; every other unlisted package path receives the same `needs-review` default
without requiring an analogy.

That partition is the only reason this repo can dogfood itself at all: skill-wording, oracle, and
shipping-driver work routes to a human; harness-test and doc work does not.

**Agent-requested writes use the validated manifest allowlist in
`src/agent_sessions/driver/writes.py`.** `writes.KINDS` covers issue comments, bodies, and creation;
label changes and creation; branch pushes; PR creation and edits; and project-item additions and
edits. It has no merge kind. The coordinator separately owns fixed operational writes for queue
labels, board status, distributed lock refs, and Lab Notebook run reports; those do not come from
the agent's manifest. The narrower 2026-07-29 policy allowed issue metadata only; #191's
credential-containment decision superseded it on 2026-08-10 by moving agent-requested writes behind
the schema. **Widening `writes.KINDS` or the coordinator's operational-write surface is a decision
to put to the human, not a drift to discover in a diff.**

**The residual risk this partition creates, named at the moment it was created.** Gating the Python
coordinator while leaving `tests/driver/test_*.py` drivable means **the routing is protected and the
fixtures protecting it are not**. A run cannot edit the parking case lists, but it
can weaken the assertions that would have caught someone else doing so, and `make driver-test` would
stay green. This is deliberate — the fixture suites are a large share of what makes this repo
dogfoodable, and defect class 1 has never once been an implementer sabotaging a test it was allowed
to touch. `make driver-check` currently inspects only the compatibility launcher; issue #248 owns
the shipping-Python gap. The present mitigations are running watched and a human at the merge gate.
**Do not resolve a future case by analogy to this line**; the allowlist above is the answer.

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
  context. It lives above the skill (headless `Codex -p` / GHA). Don't build it into a mode.

## Criteria + tier (the core contract)

- Every acceptance criterion **names a runnable check** (test / lint / assertion / eval).
  Escalation ladder: concrete test → property/invariant → human judgment.
- **Oracle-must-already-exist:** a criterion whose check needs a fixture/corpus/harness
  that must first be *built* is `needs-review`, not `auto-ok`. Verify oracles exist *now*
  (grep/run) before finalizing a criterion — don't assume.
- **Tier derives mechanically:** every criterion checkable AND no risk-gated path →
  `auto-ok`; any human-judgment criterion OR risk-gated path → `needs-review`. Risk-gated:
  auth, secrets, data migration/deletion, deploy/infra/CI, dependency changes.

## Documentation: no doc states a fact a command can print

Every documentation defect this project has hit was **a fact derivable from a live source, or prose
duplicating one.** Never a judgment, never a rule — `findings.md`'s rules are as true as the day they
were written; its *counts* drifted. So:

- **Cite the command, not the number.** "the fixture suite (`make driver-test`)", not "the
  `N`-assertion fixture suite" — that exact claim, with a real number in it, sat stale in this file
  until `docs-check` caught it. *(Written with `N` on purpose: a literal number here would trip the
  detector, which matches literals and cannot tell a claim from an example. See below.)*
- **Don't restate a live source in prose.** `design.md`'s roadmap duplicated the board and rotted
  within two days; prose above a table restated the table and contradicted it within the hour.
- **When a count *is* the argument, keep it next to its evidence.** `findings.md`'s "nine instances"
  is the argument (the class is not converging), and the table beneath it makes the count countable.
  That shape is fine. Prose asserting a count *away* from its table is not.
- **If you must state a countable fact, date it.** A dated fact stops being wrong and becomes
  history — *"as of 2026-07-29: eight PRs, all merged"* is honest a year later in a way the bare
  number is not.
- **`make docs-check` enforces the checkable part** — dead links, tables split by prose, and
  assertion counts that no longer match the suite. It is in `make check`. It found two real defects
  on its first run, one of which had survived two readings.

A rule here is an exhortation, and this project is **3 for 3** on those measuring away
([findings.md](docs/findings.md) defect class 4). The detector is the load-bearing half; treat this
section as its rationale.

## When you change something, ask what it just invalidated

A distinct failure shape, and the audit pass does not catch it: **inherited** stale claims get caught
by re-verification, but a claim *you* falsify yourself, in the same session, by doing ordinary work,
has no trigger. This file said all of `driver/` was drivable; four hours later, on 2026-07-29, the
classifier moved into the then-current `driver/gate.py`, which made it false, and nobody noticed
until it came up for an unrelated reason. The 2026-08-09 conversion superseded that path with
`src/agent_sessions/driver/gate.py`; the lesson remains the same.

So when you move or add something oracle-bearing, check the two lists that describe the partition:
**Risk-gated paths** above, and `design.md`'s architecture sections. Moving code that grades a run is
the specific move that invalidates them.

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
- Commit per logical step; keep changes small; capture findings in Les's journal
  (`~/Documents/Obsidian/main/journals/`).
- **Do not hand-maintain a state section.** An earlier version of this line said to update
  `design.md`'s build-status whenever state changed — and that instruction is what produced a
  Current-state block three moves stale, still claiming "seven PRs, six merged" when it was eight
  and all merged. State lives where it cannot rot: the **board** for work items, `runs.jsonl` for
  per-run provenance, the **README** for the one-paragraph summary. `design.md` carries only what
  none of those hold.
- Address the user as **Les**; push back on questionable approaches; smallest reasonable
  changes over cleverness.
