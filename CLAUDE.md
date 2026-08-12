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

- **An autonomy harness with a skill component.** The system's orchestration lives in `driver/`; the skill component lives at `skills/agent-session/` in *this repo* — it is NOT installed in `~/.claude/skills/`. Test it by running its phase files manually (dogfooding), not via a registered skill.
- **The reference skill it derives from** is at `~/.claude/skills/dev-session/` (phases +
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

`skills/agent-session/references/acceptance-criteria.md`'s **trigger 2** is project-configurable — it fires on *"anything
the project's CLAUDE.md marks off-limits."*

**The default is `needs-review`: anything not named drivable below is gated.** This is an allowlist,
not a denylist, and the direction is the whole point. Decided 2026-07-29 after the partition went
stale by omission **twice in two days** — once when the classifier moved into `driver/gate.py`, once
when `scripts/` was created (in the very commit that added the "ask what it just invalidated" section
below). Under a denylist, a directory nobody has classified reads as *drivable*, so the failure mode
of forgetting is that unreviewed work runs unattended, and a triage scanner has to guess by analogy.
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

- **`src/agent_sessions/driver/gate.py` — the oracle (and its gate block format), off-limits too.** As of 2026-07-28 this module is
  what classifies a run's outcome (`classify_pr_body`, called at `agent-session-driver.sh:485` and
  `:616`). **An issue whose work edits it is editing the code that grades its own run** — the
  implementer authoring its own oracle, one level removed from the skill. The gate block schema format and `gate.py` form one contract governed by this oracle rule. The `skills/**` rule does
  not cover it, and this line was added because the move-7 partition missed it: `driver/` was
  wholly drivable before the classifier moved there.

- **`src/agent_sessions/driver/router.py` and `src/agent_sessions/driver/reconciler.py` — the outcome routing and reactive reconciler**, extracted per issues #182 and #185 to replace the coarse gating of `driver/agent-session-driver.sh`. The modules hold the priority ladder, reactive event handlers, and skip/unpark decision logic, so gating them isolates the routing while freeing the rest of the driver orchestration.

- **`src/agent_sessions/driver/credentials.py` and `src/agent_sessions/driver/writes.py` — the credential split and the write
  manifest**, added per issue #191. These are not oracles; they are the *containment boundary*.
  `credentials.py` decides which token the agent's subprocess gets, and `writes.py` decides which
  GitHub writes the driver will spend its write token on. A run that edits either is editing the
  code that decides what a run of its kind is allowed to do — which is the trigger-2 standing
  default (auth/authorization, secrets) landing squarely on a named file. Gated for the same
  reason `.github/**` is: it defines the capability the checks run under, not the checks.

Plus the standing defaults trigger 2 already names: auth/authorization, secrets, data
migration/deletion, deploy/infra/CI config, dependency changes.

### What "the oracle" means — the narrow reading

Decided 2026-07-29, because the question kept recurring one detector at a time and each answer was
being re-derived by analogy. **Gated means the code decides whether *this run's own work* is
acceptable to merge.** That is the outcome classifier, and — since 2026-08-03 — the routing that
consumes its verdict. A test suite, a lint recipe or a doc-rot detector grades the *work*; only
`gate.py` and the driver's routing decide the *verdict*, and a verdict is what converts into an
automatic merge under phase 3.

So `src/agent_sessions/scripts/docs_check.py` is **drivable**, and so is a future check-linter, however detector-shaped
they look.

**The residual risk, named rather than gated away.** A run that edits `docs/` *and* `src/agent_sessions/scripts/docs_check.py` in one change
could weaken the detector that would have caught its own doc rot, and `make check` would still be
green. The broad reading would close that, but it would also sweep in `driver/test_driver.py`,
`driver/test_gate.py`, `driver/test_park_state.py` and the `Makefile` recipes — every one of which is
listed as drivable directly below, and whose drivability is the only reason this repo can dogfood
itself. The mitigations are the same ones already relied on: tests that import what ships, `make
check` in every PR, and a human at the merge gate. Revisit if a run ever actually does it.

### Drivable (the allowlist)

- **`driver/`, except `src/agent_sessions/driver/gate.py`, `src/agent_sessions/driver/router.py`, `src/agent_sessions/driver/reconciler.py`, `src/agent_sessions/driver/credentials.py`, and `src/agent_sessions/driver/writes.py`** — its tests (`driver/test_*.py`), fixtures (`driver/test-*.sh`), and driver orchestration (`agent_session_driver.py`, etc.). Note what this leaves: the oracle, the outcome routing, the reconciler and the containment boundary are off-limits, while the driver script and tests are drivable.
- **`docs/`** — including `findings.md` and session notes.
- **`Makefile`**.
- **`scripts/`** — `docs_check.py` and its tests, per the narrow reading above. Added 2026-07-29; it
  was unlisted from creation until then, which is what prompted the allowlist.

That partition is the only reason this repo can dogfood itself at all: skill-wording and oracle work
routes to a human, orchestration and doc work does not.

**What the driver may write to a target repo: anything the agent recorded in a validated write
manifest, and nothing else. Never a merge. Always under its own GitHub account.** Amended
2026-08-10 by #191, from the original metadata-only rule, and the amendment was put to the human
rather than discovered in a diff — as the rule itself demanded.

The original line read *"issue **metadata**, never issue or PR **content**"*, recorded 2026-07-29
when #5 turned the park record into a `driver-parked` label and the driver became a GitHub writer
for the first time. #191 inverted the situation it was written for. The agent now holds a
read-scoped credential and *cannot* write at all; every comment, label, issue body, branch push and
PR the loop depends on is performed by the driver, from a manifest the agent recorded. Holding the
metadata-only line would have meant the loop could no longer explain why it parked.

So the boundary moved from *what kind of thing* to *where it came from*:

- **The driver is a relay, not an author.** Content is still the agent's words — that trust model
  is unchanged. What changed is the capability: the agent can no longer spend it, and the driver
  will only spend it on a `kind` named in `writes.KINDS`, aimed at the configured repo and board.
- **Unknown kinds are rejected, and one bad entry voids the whole manifest.** A validator, not a
  pipe. `writes.py` is gated above for exactly this reason.
- **There is no kind that merges**, with or without `--auto`. That is now a property of the
  vocabulary rather than an instruction anybody has to follow.
- **Widening `KINDS` is still a decision to put to the human**, on the same terms the original line
  set: written down rather than inferred from what the driver happens to call today.

**And under whose name.** The driver holds two tokens on a machine user, and there is no fallback
to the host `gh` login: all three of `DRIVER_GH_LOGIN`, `AGENT_GH_READ_TOKEN` and
`DRIVER_GH_WRITE_TOKEN` are required, and both tokens are checked against a live `gh api user`
before anything is spent. The reason is the same one that motivates the allowlist above — *the
failure mode of forgetting must be inconvenient, not silent.* A fallback is reached by omission,
and its result is a commit or comment attributed to a person who did not make it. **Re-introducing
a fallback is a decision to put to the human**, on the same terms as widening `KINDS`.

**What is deliberately *not* contained, decided 2026-08-10.** Both tokens live in a git-ignored
`.env`, and the driver only refuses a credential in a file git would actually add. Hiding it better
buys nothing: the agent runs as the same uid with a shell, so it can read any file the driver can
and replay any command the driver runs. The split contains every ordinary path — the agent's
environment holds only the read token — and an agent that deliberately goes hunting for a second
credential is accepted risk, not a solved problem. **Do not re-tighten this by analogy**; the
answer is uid separation or a remote driver host (#3), and until one exists the mitigation is
GitHub-side: a narrowly scoped PAT with no `Workflows` permission, and branch protection on `main`.

That account's login is also load-bearing for #183: a PAT-backed machine user carries no `[bot]`
suffix, so `has_new_human_comment` cannot tell it from a person by inspection. It is told, via
`credentials.bot_logins`. **A future identity change — a GitHub App, a rename — must go through
that function, not around it**, or the driver starts unparking the issues it just parked.

One exception to "relay, not author", named so it is not mistaken for drift: `discussion_manager`
posts the driver's own start/finish notes to a Lab Notebook discussion. That is the driver
narrating its own run, not writing on the agent's behalf, and it predates #191. It stays outside
the manifest for the same reason it is not gated — a run log about a run is not a verdict about it.

**The residual risk this partition creates, named at the moment it was created.** Gating
`agent-session-driver.sh` while leaving `driver/test-driver.sh` drivable means **the routing is
protected and the fixtures protecting it are not**. A run cannot edit the parking case lists, but it
can weaken the assertions that would have caught someone else doing so, and `make driver-test` would
stay green. This is deliberate — the fixture suites are a large share of what makes this repo
dogfoodable, and defect class 1 has never once been an implementer sabotaging a test it was allowed
to touch. The mitigations are `make driver-check`, running watched, and a human at the merge gate.
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
- **A claim can be a world-state assertion even when phrased as a judgment.** E.g., "Not proven", "never been driven", or a bare repo count is just a count in disguise. Cite `make evidence` instead.
- **`make docs-check` enforces the checkable part** — dead links, tables split by prose, stale assertion counts, and judgment-phrased world-state claims. It is in `make check`. It found real defects on its first run, some of which had survived multiple readings.

A rule here is an exhortation, and this project is **3 for 3** on those measuring away
([findings.md](docs/findings.md) defect class 4). The detector is the load-bearing half; treat this
section as its rationale.

## When you change something, ask what it just invalidated

A distinct failure shape, and the audit pass does not catch it: **inherited** stale claims get caught
by re-verification, but a claim *you* falsify yourself, in the same session, by doing ordinary work,
has no trigger. This file said all of `driver/` was drivable; four hours later the classifier moved
into `driver/gate.py`, which made it false, and nobody noticed until it came up for an unrelated
reason.

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
