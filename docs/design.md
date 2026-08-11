# agent-sessions — design

**What the system is and why it has this shape.** Start here. Captured 2026-07-23 from the
originating brainstorm and kept current since; the reasoning trail is preserved so the *why*
survives.

Two companion files, split out of this one in move 6:

- **[findings.md](findings.md)** — the durable lessons: recurring defect classes, the evidence
  ledger, the instrument rules, and the verified command gotchas. **Read it second, and read it
  before writing any flag list or gate row.**
- **[build-log.md](archive/build-log.md)** — the chronological account of moves 1–5, **closed**. Read it for
  the incidents that produced the rules in `findings.md`, not for state; per-run provenance now lives
  in the driver's `runs.jsonl` (the path the driver logs at startup) and a move's account in its
  session `notes.md`.
- **[usage.md](usage.md)** — the operator's guide: commands, outcomes, run artifacts, recovery.
  Written for someone running the thing rather than changing it.

[prior-art.md](prior-art.md) has the external survey, [../README.md](../README.md) is the
plain-language introduction, and [orientation.md](orientation.md) is the newcomer's on-ramp —
the vocabulary this file assumes, plus what is and isn't proven.

## Origin

Burning down the [decafclaw](https://github.com/users/lmorchard/projects/6) project board
manually — pick issue → spec → plan → execute → PR → request Copilot review → address
comments → merge. Question: how to push more of that loop toward autonomy, escalating to
a human only for issues that actually need it.

## The one principle

**An agent is only as autonomous as its verifier is trustworthy.**

**Corollary (added from prior-art survey, see [prior-art.md](prior-art.md)):** trustworthy
means the *oracle itself* must be validated. "Criterion is machine-checkable" is necessary
but **not sufficient** — the check must also be *correct*, the verifier must be
**independent of the implementer**, and acceptance tests **frozen before implementation**
so the implementer can't weaken them (SWE-bench documents test-log misparsing; Anthropic
names self-verification bias). An untrustworthy green check is worse than no check.

(From Anthropic's ["Enabling Claude Code to work more autonomously"](https://www.anthropic.com/news/enabling-claude-code-to-work-more-autonomously)
and the long-running-agent research: if the agent can check its own work with a near-perfect
oracle, it can run; where the oracle is weak or missing, a human belongs.)

The manual loop already has **strong oracles in the middle** (`make check`, `make test`,
evals, Copilot review) and **weak oracles at the two ends**:
- front: *"is this issue well-specified enough to attempt unattended?"*
- back: *"is this PR safe to merge?"*

So: automate the strong-oracle middle; keep humans on the weak-oracle ends. The rest of
the design falls out of that.

## What to front-load (and what not to)

Ranked by leverage for autonomy:

1. **Verifiable acceptance criteria — the biggest lever.** A spec that says *what* to
   build defines the target; a spec that says *"done means X, and here's the check that
   proves it"* defines the **oracle**. That's what lets the loop grade itself. The
   criteria must resolve to something runnable (`test_x` passes, `make check` green, a new
   eval case), not prose a human eyeballs.
2. **Board triage / priorities** — powers *selection and throughput*, a different axis. It
   decides which issue the loop picks up and whether it's ready. Valuable, but it doesn't
   make any individual issue get built better.
3. **Pre-attached plans — weakest, mildly counterproductive.** A plan written at *filing*
   time is stale by *execution* time (the repo moved), and planning against live code is
   exactly what the model is good at doing fresh. **Generate the plan at execution time**
   (launch research subagents against current state, then compose) — don't freeze it at
   triage.

**Missing from the naive model:** the front-loaded metadata that specifically buys
autonomy is the **escalation signal**, not the plan. At triage, stamp: is this safe
unattended? (`auto-ok` vs `needs-review`), likely paths touched, rough size.

**Cost caveat:** front-loading only pays when the artifact is *reusable* (agent + Copilot
+ future-you read it) or *doubles as the verifier*. Small/mechanical issues should skip
the ceremony: one-line criterion, `auto-ok`, done. If speccing takes as long as doing,
you've moved the work earlier, not gained leverage.

## The reframe

**A good spec names its own verifier.** When you can write the acceptance criterion as a
check the loop can run, that issue is a candidate for the autonomous middle. When the only
honest test is "human decides," that's not a spec failure — it's the issue *telling you*
it belongs in `needs-review`. The criteria do double duty: power execution *and* sort
issues into autonomy tiers for free.

## The capability ladder (Claude Code, verified against docs 2026-07-23)

1. **Headless CLI** — `claude -p --allowedTools "..." --output-format json`.
   JSON output carries `total_cost_usd` + `session_id`; `--continue`/`--resume` chain
   sessions. [docs](https://code.claude.com/docs/en/headless)

   **This entry was wrong in three ways that would have produced a broken driver**, all corrected
   in move 3 against `claude --help` 2.1.220 and live runs. The verified specifics — `--bare`,
   `--max-budget-usd`, what `--permission-mode dontAsk` actually denies, deny-rule precedence and
   why it is what makes "nothing merges" a mechanism, and the variadic-flag trap that forces the
   prompt onto stdin — are canonical in
   [findings.md § Verified gotchas](findings.md#claude-code-cli). Read them before writing a flag
   list: several are the opposite of what the flag names suggest.
2. **GitHub Actions** (`anthropics/claude-code-action@v1`) — the "runs without my laptop"
   unlock. Auto-detects `@claude` mention mode vs `prompt:` automation mode; the prompt
   form runs on *any* event including `schedule:` cron. Vertex via Workload Identity
   Federation (matters for decafclaw's multi-provider setup). Separate
   [GitHub Code Review](https://code.claude.com/docs/en/code-review) posts reviews on every
   PR with no trigger. [docs](https://code.claude.com/docs/en/github-actions)
3. **Agent SDK** (Python/TS) — full programmatic loop w/ hooks + subagents. **Overkill for
   decafclaw**: it's *already* an agent runtime with its own hooks/subagents/workflow
   engine. Building a second orchestrator to drive the first is redundant.
4. **Hooks** — `PreToolUse` is the guardrail layer rather than the primary loop. Since #191 it is
   explicitly *defence in depth*, not the containment layer: the read-scoped credential is, and the
   hook stays so that a token which turns out to be over-scoped still meets a second refusal.

   **Unverified, flagged rather than fixed:** this entry used to assert a hook can hard-block *even
   under `bypassPermissions`*. That came from the same 2026-07-23 research pass whose own note below
   records that several of its specifics could not be verified, and it has **no entry in
   `findings.md`'s ledger** — unlike every other CLI fact the driver relies on. It is also not
   load-bearing for the current host, which runs `--permission-mode dontAsk`, not
   `bypassPermissions`. A triage scanner caught this being repeated as fact in issue #1. **Verify it
   before designing against it.**

Note on trusting research: the first-pass research subagent produced a wall of confident
detail; several specifics ("Claude Code Routines," a C-compiler blog's cost figures,
Pro/Max daily run limits, a specific CVE version) could **not** be verified and were
dropped. Distrust-and-verify is the same principle as the burndown loop, applied to the
research agent — its verifier (the human) has to be good, because unverified confident
output is exactly what weak oracles produce.

## Phased rollout (increasing autonomy, each reversible)

1. **Self-driving skill, local, human at the merge gate.** Package the manual loop as one
   command that runs spec → research → plan → execute → `make check && make test` → open
   PR with an `--allowedTools` allowlist, and *stops before merge*. Runs on-machine,
   watchable, interruptible. Lowest risk, highest immediate leverage.
2. **Scheduled GitHub Action opening draft PRs.** Same loop, no laptop required. Branch
   protection keeps merge human-gated. Second workflow triggered on Copilot review
   addresses comments.
3. **Conditional auto-merge (Not pursued).** See *Resolved decisions* below. The objective shifted from removing the human entirely to maximizing the attention ratio — the loop stops at the merge gate, and success is defined as only ever needing human attention for hard problems rather than mechanical failures.

**Safety:** avoid `--dangerously-skip-permissions` / `bypassPermissions`. Scoped
`--allowedTools` + `dontAsk` gets ~95% of the autonomy with a real floor under it.

## The two-skill system (the original sketch — architecture superseded)

**Read this for the reasoning, not the shape.** It shipped as **one skill with a multi-mode
dispatcher**, not two skills — see [What is built](#what-is-built), which explains why. The grilling
mapping below still describes how `intake` actually works, which is why the section is kept.


### intake skill (grilling-derived, human-in-loop)

Lives at the weak-oracle front end. Job: turn a wishlist stub into a spec whose criteria
are runnable checks, plus an escalation tier — and emit a filable issue.

Built on Matt Pocock's [grilling skill](https://github.com/mattpocock/skills/blob/main/skills/productivity/grilling/SKILL.md),
which is a near-perfect engine. Its mechanics map directly:

- **"Probe the environment for factual matters rather than asking"** = the
  research-subagents-then-plan instinct. The skill dispatches Explore/research agents to
  answer *factual* questions about the codebase (does this pattern exist? current shape?
  is there a test harness?) and spends the human's attention only on *decisions*.
- **"Provide your recommended answer alongside each question"** = kills the overhead risk.
  Inverts authoring effort: instead of "what are the acceptance criteria?" (blank page),
  the skill — having researched — *proposes* criteria as runnable checks and the human
  ratifies/corrects. Fast triage, not a dreaded form.
- **"One question at a time, walk the decision tree resolving dependencies"** = the spine:
  definition → scope boundaries → each criterion → (derived) tier.
- **"Don't act until shared understanding is confirmed"** = the human-in-loop gate.

What intake *adds* on top of grilling (the thin, opinionated layer):

1. **A fixed target schema** instead of open-ended "shared understanding" — driving toward
   *definition + verifiable criteria + escalation tier*; done when those slots are filled.
2. **Verifiability as the per-branch success test** — refuses to close a criterion while
   it's still a wish; its recommended answer is *always* a runnable check, and "how would
   you actually know?" is the standing follow-up.
3. **An output artifact** — emits the filable issue body + labels, tier *inferred* from
   whether every criterion resolved to a check (all checks → `auto-ok`; any "human decides"
   → `needs-review`).

Scope guardrail: intake is for **heavier issues only**. Small/mechanical ones skip it.

### execution skill (self-driving, autonomous middle)

Phase 1 above. Consumes a well-specified issue; runs the loop; stops at the merge gate.

### shared contract

The seam between intake's *output* and execution's *input*: the acceptance-criteria format
+ escalation labels. Design once, both read from it. (In the spirit of decafclaw's
"don't hand-maintain parallel field lists that rot in lockstep.")

## Finding (2026-07-23, later): dev-session already IS the producer/consumer core

Studied the existing `~/.claude/skills/dev-session` skill (SKILL.md + phases + references).
It already implements most of the two-skill system sketched above — not "similar to," but
*is* it. The sequel is therefore an **upgrade + orchestration layer**, not a reimplementation.

Already covered by dev-session:

| Sketched as "new" | Where it already lives |
|---|---|
| Producer/consumer split | `file` (produces spec-embedded issue) → `express` (autonomously consumes); `<!-- dev-session:spec -->` marker = the shared contract/seam |
| Research-then-plan-live | `brainstorm` documentarian substep → `research.md`; plan generated at `plan`/`express` time, never frozen at filing |
| Grilling-style interview | `brainstorm` step 3: propose best judgment + trade-offs, confirm/adjust, no open-ended Qs, multiple-choice preferred |
| Crude autonomy tier | `express` Phase 0 complexity check (pushes back on L/XL/ambiguous); feel-driven carve-out refuses autonomous execution of subjective visual work |
| Board transitions | Ready → In Progress → In Review via `references/github-projects.md` |
| Spec-readiness gate | Readiness checklist in `spec-template.md` |
| Scope proportional to complexity | `brainstorm` step 4 |

The genuine gaps — the ~20% that is actually new and high-leverage:

1. **Verifiable acceptance criteria as first-class (the core gap).** spec-template's
   "Desired end state" is *prose* (user-visible behavior, API surface); the Readiness
   checklist gates on placeholders / consistency / scope / ambiguity but **nothing requires
   each criterion to name a runnable check.** Upgrading spec-template + the readiness
   checklist to demand a runnable oracle per criterion (`test_x` passes, `make check`
   green, an eval case) is the highest-value change — and it's small. This is
   "a good spec names its own verifier" made concrete.
2. **A durable, verifiability-derived tier label** stamped at `file` time (not decided
   ad-hoc at `express` Phase 0), so a board/cron loop can *route* on it. The tier falls
   out of "did every criterion resolve to a check?" (all → `auto-ok`; any human-eyeball →
   `needs-review`).
3. **The merge gate.** `express` stops at PR-with-Copilot-addressed; merge is human.
   Conditional auto-merge by tier (all-green + no unresolved threads + `auto-ok`) is new.
4. **The board-level driver.** Nothing today *picks the next Ready issue and runs `express`
   unattended*, then advances. That orchestration (headless `claude -p` / scheduled GHA)
   is the actual "burndown loop" and sits *above* a per-issue skill.

Reframed build: (1)+(2) are **enhancements to dev-session** (spec-template, brainstorm,
readiness checklist, `file`). (3)+(4) live *above* a per-issue skill — the orchestration
bookends. So "standalone skill vs dev-session phase" resolves mostly toward *extend
dev-session*; the separate artifact is the driver + merge gate.

## A harness with a skill component

Worth stating plainly, because the docs have historically drifted toward describing only the skill. This repo
holds **a harness with a skill component inside it**, each with different responsibilities and correctness regimes. Conflating
them is what makes "is this a skill-authoring project?" feel like a confusing question:

|  | `skills/agent-session/` | `driver/` + `Makefile` |
|---|---|---|
| What it is | the skill component — a set of phase instructions, `dev-session` lineage | the harness — phase state machine, priority ladder, outcome classification, merge-gate oracle (`gate.py`), park state, distributed mutex, budget accounting, pluggable backends, run provenance |
| Made of | markdown | bash, plus a Python parser (`driver/gate.py`) |
| Its oracle | cheap classifier evals, micro-tests, and dogfooding | fixture tests and mutation testing |
| Who reads it | this system's harness | target repositories and CI environments |

They are deliberately separable: **the board-driver needed zero skill changes**, and
`make skill-readonly` enforces that a hosted run may read the skill but never write it. The
governing principle applies to both, but the *cost* of applying it differs by an order of
magnitude — a skill-wording oracle is a classifier eval or micro-test, while a driver oracle is a fixture test at
zero. That asymmetry drives most of the sequencing decisions in the roadmap.

This is a distinction to keep, not a project to rename.

## What is built

Decided: **single `agent-session` skill, multi-mode dispatcher** (dev-session lineage), not
separate skills. Rationale: sidesteps the unverified cross-skill file-sharing mechanism
entirely (all refs in-dir), and the dispatcher's lazy-load means modes never co-reside, so
adding modes doesn't confound the LLM mid-phase — the only confounding risk is at the entry
boundary, mitigated by explicit mode arguments + an ask-don't-guess dispatcher. Heavy modes
fan out to subagents; the board-driver stays *above* the skill as orchestration.

Built (orchestration), in `driver/`:
- `agent-session-driver.sh` — The **Wiggum Architecture reconciliation loop**. A stateless state machine that evaluates GitHub repository state (issues, PRs, review comments, CI status) and dispatches tightly-scoped, short-lived LLM agents. Uses GitHub labels (`agent-session:attempt-1..3`) and comments for zero-local-state queue control and async human-in-the-loop ratification.

Built (front-of-funnel), in `skills/agent-session/`:
- `SKILL.md` — dispatcher, context-management notes, conventions.
- `references/acceptance-criteria.md` — **the novel core**: every criterion names a runnable
  check; verifier-independence + freeze-before-implementation; concrete-test → property →
  human-judgment escalation ladder; **oracle-must-already-exist** rule; tier derivation
  (auto-ok/needs-review) + risk-gated-path override.
- `references/criteria-grammar.md` — EARS (five patterns, verified against Mavin) +
  Given-When-Then syntax reference.
- `references/spec-template.md` — criteria replace prose "desired end state"; readiness
  checklist gates on *verifiability*.
- `references/documentarian-prompt.md` — neutral negation rules for the research subagent
  (shared by intake + triage); includes the oracle-existence question.
- `phases/intake.md` — new + existing-issue (augment) modes; reduce each requirement to
  criterion+check; verify each check's oracle exists *now*; derive tier; file/update issue.
- `phases/triage.md` — batch backlog-gardening; subagents fan out to assess + draft proposed
  criteria, human ratifies in a fast pass, augment in place.

Built (back half, move 1), in `skills/agent-session/`:
- `references/frozen-checks.md` — **the back-half novel core**: the `checks.md` manifest
  (criteria copied verbatim, stable `C1…Cn` ids), the freeze commit, the read-only rule, the
  independent verifier subagent, the `git diff <freeze-sha>` tamper check, and the amendment
  path (stop → human-confirm → log → **downgrade the run to `needs-review`**).
- `phases/plan.md` — gates on verifiability, re-verifies oracles still exist, **Phase 0 is the
  freeze** (written before the rest of the plan), bidirectional criteria coverage in self-review.
- `phases/execute.md` — per-criterion checks by name as the gate; frozen files read-only to
  implementers; independent verifier + tamper diff, not self-report; evidence produced for
  human-judgment criteria.
- `phases/open_pr.md` — Initial PR push and review request.
- `phases/address_comments.md` — Agent specifically targeting unresolved review threads on an open PR.
- `phases/fix_ci.md` — Agent specifically targeting failing CI checks on an open PR.
- `phases/grade_gate.md` + `references/pr-body-template.md` — the **tiered merge gate**, derived by
  reading rows (all checks pass per the verifier + human-graded judgment criteria + clean
  tamper diff + green project gates + no unresolved threads + `auto-ok` + no risk-gated paths).
  Emits a machine-readable `<!-- agent-session:gate -->` block. **Never merges.**
- `phases/express.md` — Phase 0 checks *preconditions* (marker / readiness / size) instead of
  judging complexity by feel; a missing marker routes to `intake`. Tier decides only *where the
  run surfaces to a human*, not whether it runs.
- `references/session-setup.md`, `references/plan-template.md`, `references/github-projects.md`.

## Asynchronous GitHub-Native Interaction Model

The driver and skills operate as a stateless reconciliation loop over native GitHub primitives (labels, comments, PRs). Zero control state is stored in local runner files; all execution history and queue routing derive from live GitHub issue metadata.

### Label Vocabulary & Queue Control

- `agent-session:spec`: Issue carries verifiable EARS criteria & `## Tier`. Eligible for **P2: Execute**.
- `agent-session:needs-human`: Async human input required. The agent posted a comment on the issue/PR and parked. Excluded from headless selection.
- `agent-session:needs-human-interactive`: Requires an interactive CLI session (e.g. subjective aesthetic, layout, game feel). Excluded from headless selection.
- `agent-session:merge-ready`: PR passed `grade_gate`. Awaiting human merge or auto-merger. Excluded from driver loop.
- `agent-session:attempt-1` .. `attempt-3`: Stateless attempt counters on the issue. Replaces local `attempts.tsv`.

### Current-State Control Loop

The driver evaluates live GitHub state on every pass without historical diffing or local state files:

1. **Selection & Priority Ladder**:
   - **P1: Unblock**: Issues referencing open PRs needing comment resolution, CI fixes, or gate grading.
   - **P2: Execute**: Issues carrying `agent-session:spec` AND `auto-ok` tier AND no open PR AND no `needs-human`.
   - **P3: Groom**: Open issues lacking `agent-session:spec` AND lacking `needs-human`.
   - **P4: Escalate**: Issues reaching `agent-session:attempt-3`.

2. **Async Q&A via Issue Comments**:
   - When an agent needs input or spec ratification, it appends a top-level comment detailing its proposal or question.
   - The agent applies `agent-session:needs-human` and clears any `attempt-*` labels.
   - The human reviews asynchronously and appends a reply comment (e.g. "Approved" or feedback).
   - The human **removes `agent-session:needs-human`**.

3. **Stateless Resumption**:
   - When `agent-session:needs-human` is removed, the issue naturally becomes visible to the driver under **P3: Groom**.
   - The agent reads the full comment thread (`gh issue view <n> --comments`).
   - If approved: Applies `agent-session:spec` and updates the issue body.
   - If feedback given: Appends a new comment with updated criteria and re-applies `agent-session:needs-human`.

## Criteria vs. regression guards

The discriminate rule opened a gap: "the full suite stays green" and "output is byte-identical"
can never fail at freeze, so as criteria they're vacuous — yet they obviously want checking. Two
dogfoods hit it from opposite directions (the pure-refactor exemplar presenting a golden test as
a CRITERION; #638 landing as 1 criterion + 3 guards), so it was a hole, not a wording nit.

A **criterion** says what the work must *newly* make true (must fail now); a **guard** says what
it must not break (must pass now). Guards don't affect the tier. Wired through both engines and
every consumer — manifest section, spec slot, readiness item, per-phase verification, the
verifier's remit, and a `guards:` field in the gate block. They earn their place by catching one
specific cheat: **making a criterion go green by deleting the coverage that contradicted it**,
which leaves every criterion passing and the suite green, and only a guard notices.


## Current state

**Deliberately short.** The enumerable facts live where they cannot rot — the backlog on
[the board](https://github.com/users/lmorchard/projects/9), per-run provenance in the driver's
per-repo `runs.jsonl` (it logs the resolved state directory at startup; `./.driver-state/` is the
pre-#27 archive), a plain-language summary in
[../README.md](../README.md). This section carries only what none of those hold: what is proven, and
what is not.

*(The previous version was a dated snapshot and had gone three moves stale — it still said "seven
PRs, six merged." That is the failure mode a hand-maintained state block always has, so this one is
written to have less to be wrong about.)*

**What is proven and what is not.** Run `make evidence` to see the live report of which paths have been exercised, against which repositories, and with what outcomes. That report reads the driver's ledger and is the only authoritative source for what has actually run.

**The standing limit:** This project's own oracle is too expensive. At ~$50 and half a session per rule, the unmeasured rules will not all get measured. What remains in prose are the claims no command can print:
- **A human merges every PR by hand.** The gate reports `eligible-for-auto-merge` as a finding, but takes no action.
- **The verifier's local containment remains unresolved.** (See D2 in Resolved decisions).
- **`ci-stale` catches diverging PR heads.** (Verified live in #6, but not mechanically guaranteed across all edge cases without the ITIL precondition).

## Roadmap → it lives on the board now

**The backlog is not maintained here any more.** It is on [project 9](https://github.com/users/lmorchard/projects/9) as issues carrying
criteria, guards, a tier, and the check results that were actually run.

Move 7 moved it there because prose is a bad backlog, and this section proved the point twice: it was
reconciled at a **5-of-11 stale rate**, then rotted again within two days — one item was done, one had
been resolved, and the numbering had a gap where a removed item used to be.

| Theme | Issue |
|---|---|
| `PreToolUse` merge-block hook — **blocks phase 3** | [#1](https://github.com/lmorchard/agent-sessions/issues/1) |
| Adjacent-evidence sweep — **blocks phase 3** | [#2](https://github.com/lmorchard/agent-sessions/issues/2) |
| GHA host | [#3](https://github.com/lmorchard/agent-sessions/issues/3) |
| `parked.jsonl` — no un-park record, and per-machine | [#5](https://github.com/lmorchard/agent-sessions/issues/5) |
| `ci-stale` firing on a real PR | [#6](https://github.com/lmorchard/agent-sessions/issues/6) |
| Multi-phase `execute` (vehicle: decafclaw #625) | [#7](https://github.com/lmorchard/agent-sessions/issues/7) |
| Nothing validates the frozen checks before they lock | [#12](https://github.com/lmorchard/agent-sessions/issues/12) |
| Driver silently drops marker-less issues | [#13](https://github.com/lmorchard/agent-sessions/issues/13) |

**Not on the board, because it is another project's call:** decafclaw **#566** carries three open
questions for a human — a loop would have to pick the design rather than implement one.

What stays below is what a board cannot hold: an open *decision*, and two lists whose entire purpose
is to stop things being reopened or re-added.

### The open decision (Superseded)

*Superseded 2026-08-10 by Decision 1 (see Resolved decisions) — phase 3 is not pursued, dissolving this question. The reasoning below is preserved as load-bearing context.*

**Les's call: does the phase-3 gate list get a finite exit condition?** It has grown by roughly one gate per session —
first the CI hole, then the merge-block hook, then the amendment policy (**now settled**, see
Resolved decisions) and the sweep. Each addition has been a correct call individually. A finite
exit condition would be better than a list that grows as fast as it is worked. *Not* an argument to
rewrite the phased rollout, and note the premise is weaker than it looks: the PRs **do** land, by
hand and quickly.

Two inputs for that decision, both verified from primary sources in move 7
([prior-art.md](prior-art.md#leads-1-3--surveyed-and-verified-move-7-2026-07-28)):

- **ITIL supplies the finite exit condition this list lacks.** A "standard change" is pre-authorized
  on three conditions together: documented procedure, risk formally accepted **in advance**, and
  **prior runs have proven the outcome predictable.** The governance body pre-approves the
  *template*, not the instance. Our `auto-ok` is stamped **per issue** on its own criteria, so we
  have no notion of *"this class of change is safe because N instances landed cleanly"* — which is
  precisely an evidence-based stopping rule rather than a growing list of gates.
- **Renovate treats "up-to-date and green" as a *precondition* of automerging**, not as a validity
  check applied after a verdict is published. Our gate derives a verdict and *then* asks whether the
  commit still ships; theirs cannot reach the question. That ordering is cheap to adopt and would
  make one whole class of `ci-stale` unreachable.

### Declined, with reasons — do not reopen without new evidence

- **Driver resuming its own interrupted runs.** Needs a staleness policy for continuing against a
  moved `main`, and there is no evidence for one. `--classify-only` covers recovery.
- **Scoping `execute.md`'s unconditional `subagent-driven-development` invocation.** An
  `unless trivial` clause is exactly the nuance-on-a-winning-recipe this project's evidence says
  degrades a rule. Measure before touching.
- **`plan.md`'s "every phase advances at least one `Cn`"** flags Phase 0, which by the template's
  own design advances none. Verified still present (`plan.md:84`). A wording nit, agreed left.

### Dropped in this reconciliation — verified closed or unactionable

- ~~The wrong correction still sits in decafclaw #710's body.~~ **Resolved** — the retraction is in
  the body now, and names the fabrication as fabricated.
- ~~Board transitions silently no-op on decafclaw.~~ **Resolved** in move 2b: `github-projects.md`
  now locates the declaration by content and reports `board: not configured` when there is none.
- ~~Running the project gates dirties decafclaw's tree.~~ **Resolved** by decafclaw #717 — verified
  `npm ci` in decafclaw's `Makefile`. The generalisable hazard (a verification target running a
  command whose job is to mutate) is kept in `findings.md`.
- ~~A larger `intake` vehicle so multi-phase `execute` gets a real run.~~ **Duplicate** of item 7.
- ~~The standing evidence gap.~~ **Not a task** — it is a standing limit, recorded as one in
  [findings.md](findings.md#the-standing-limit-this-projects-own-oracle-is-too-expensive). At
  ~$50 and half a session per rule, the unmeasured rules will not all get measured, and listing
  them as work would imply otherwise.
- ~~An interactive-intake check of the empty-state observation.~~ **Dropped: the referent is gone.**
  The phrase survives nowhere else in the repo except an example branch name in
  `session-setup.md`. Nobody can act on it. A clean example of why prose is a bad backlog.

## Resolved decisions

Closed, but the *reasoning* is still load-bearing.

- **Phase 3 (conditional auto-merge) → not pursued.** Decided 2026-08-10 by Les: auto-merge is a blue-sky endpoint the system should probably never reach. Its value was never the merging — it was that *building the conditions* for it forces the verification apparatus to be real. The forcing function is the point, and it works whether or not the endpoint is ever reached.
  This resolves the open decision about a finite exit condition for the gate list by dissolving it. The list was only worrying because it grew toward a destination; as a forcing function it can stop wherever it stops.
  **What this does not license.** The verification apparatus is not now optional. Its justification shifts rather than weakening: under the new objective (below), a gate verdict that cannot be trusted means every park is potentially mechanical and a human must check anyway. Frozen checks, verifier independence and the tamper diff earn their place by making the judgment/mechanical distinction reliable.
- **The objective → reduce the questions requiring human attention to only the hardest problems.** Decided 2026-08-10 by Les, replacing conditional auto-merge as the thing the system is aiming at.
  Chosen partly because it is **measurable in a way auto-merge never was.** Auto-merge is a binary you either reach or do not, which is why the gate list could grow indefinitely with no way to say whether progress was happening. This objective has a metric, and the data is already being collected.
  Human attention arrives through parks, and parks divide in two. A **judgment park** means the run hit something only a human can decide — that is success. A **mechanical park** — loop breaker tripped, no PR opened, budget exhausted, driver fault, no gate block, stale CI — is a human interrupted by an operational failure rather than a hard problem. The ratio is the measure, computed by `make evidence` (#198).
  This gives the backlog an ordering principle it did not have: work that removes mechanical parks outranks work that adds capability, because a mechanical park spends the scarcest resource on the least valuable question.

- **Criteria grammar** → **EARS + Given-When-Then** (not invented); see `criteria-grammar.md`.
  Micro-tested and kept: the model knows *of* EARS but defaults nearly everything to `WHEN`.
- **Property middle tier** → done, in the escalation ladder.
- **dev-session edits vs. overlay** → a fresh single `agent-session` skill this repo owns.
- **Prior-art** → surveyed; see `prior-art.md`.
- **Verifier-independence mechanics** → `references/frozen-checks.md`: freeze commit, read-only
  frozen paths, a check-author subagent that never sees the implementation plan, a verifier
  subagent that never sees the plan or the rationale, and a `git diff <freeze-sha>` tamper check.
  The mechanical tamper diff is what turns the principle into a check; the read-only wording is
  micro-tested load-bearing.
- **Merge gate** → derived in `pr.md` by reading rows, reported as a verdict plus a
  machine-readable gate block, never acted on. `needs-review` is never eligible however green the
  checks.
- **Where the tier lives** → **the issue body's Tier section is authoritative** (it carries the
  reason); a label is a convenience index for querying. If they disagree, surface the conflict
  rather than picking one. This works today without labels existing in target repos.
- **Amendment policy — the cost** → amending is allowed but costly: stop, human-confirm, log in
  `checks.md`, and downgrade the run to `needs-review`. Keeps the loop unstuck on a typo'd check
  while making an amended oracle forfeit the autonomy it can no longer support.
- **Amendment policy — the trigger** → **decided 2026-07-27: re-run old and new wording against
  BOTH trees, the freeze commit AND the current implementation; any verdict change at either tree
  is an amendment.** The freeze tree alone is near-vacuous — at freeze the work does not exist, so
  almost any non-vacuous check fails there, *including a replacement shaped to fit the
  implementation*. Only the implementation tree detects an implementer influencing its own oracle;
  the freeze tree only confirms the replacement still has teeth. **Scope: this governs tamper rules
  too**, since a tamper rule is an oracle. A purely cosmetic rewording changes no verdict at either
  tree, so the cheap path survives for real typos.

  Two consequences, stated rather than buried. **#668 would have been an amendment**, not the
  clarification its run published — so PR #719 shipped at `eligible-for-auto-merge` when this
  policy says `needs-review`. It is merged and that was Les's call, so nothing needs undoing; it is
  recorded because the alternative is a policy whose first act is to quietly exonerate the case
  that motivated it. And the wording in `frozen-checks.md` is a **disambiguation of an existing
  rule, not new behaviour-shaping guidance** — it is therefore unmeasured, which is the right
  treatment for resolving an ambiguity but means it carries no behavioural evidence.
- **Board-driver: local `claude -p` vs scheduled GHA** → a category error. The driver is a script;
  local vs GHA is a *host*. Local is host #1. It filters on marker + anchored tier with the board
  column advisory, because the `Ready` column and the marker set had an **empty intersection** on
  decafclaw — gating on the intersection would report zero work forever. Disagreements are
  reported, not resolved. It **reads the `<!-- agent-session:gate -->` block rather than
  re-deriving the gate**, so the skill owns the verdict and the driver owns only the routing.
- **Should the merge gate read GitHub's check runs?** → **yes, via `gh pr checks`, reading
  `bucket` and never `state`.** A pending check makes the verdict `pending`, not
  `human-merge-required`: CI is the one *transient* row, so an unsettled check means the work is
  not gradeable yet, not that a human is needed.
- **Does the discriminate rule need micro-testing?** → yes, and the answer was to **cut the rule**.
  See [findings.md § 4](findings.md#4-add-then-measure-away--3-for-3) before touching this.
- **Subagent dispatch vs. the operator's Agent-tool policy** → **decided 2026-07-28: carve out
  read-only `Explore` dispatch in operator policy; the skill is unchanged.** The friction was never
  skill wording — `intake.md` and `triage.md` describe dispatch correctly and give the right
  rationale. Teaching the skill a policy-disabled fallback was rejected on this project's own base
  rate (3 for 3 on added rules measuring away), and measuring whether dispatch is load-bearing was
  rejected as mispriced against the standing oracle-cost limit. Move 7 step 4 settled it in
  practice: nine parallel scanners produced real findings with the main context clean.
  **Write-capable `execute` dispatch is a separate, narrower grant and is NOT covered** — and the
  grant must be asymmetric, because the verifier's value comes from being structurally unable to
  edit what it grades.

  **Settled 2026-08-01, and the framing above was wrong in one way worth keeping.** "Blocked on a
  grant" reads as a missing permission, and there was none: `Task` has been in the driver's
  `ALLOWED_TOOLS` all along, alongside `Write` and `Edit`. So the implementer half (**D1: yes,
  unattended runs may dispatch write-capable implementer subagents**) recorded an existing state
  rather than opening anything. What was actually missing was a *mechanism for the asymmetry* — one
  flat session-wide `--allowedTools` cannot say "implementers write, the verifier does not."

  **D2 — how the verifier's read-only-ness is enforced — was spiked, then decided for GitHub
  writes only (#191, 2026-08-10).** See
  [the spike](dev-sessions/2026-08-01-1932-verifier-containment/spike-verifier-containment.md).
  `--agents` honors an undocumented per-agent `tools` allowlist that yields an intersection rather
  than inheritance, which contains `Write`/`Edit` against a control. It does **not** contain a
  verifier that runs checks: `Bash(python3:*)` and `Bash(pytest:*)` are write primitives, and a
  cooperative run *looks* contained because the subagent declines rather than being denied.

  **What #191 settled: containment by credential, for the GitHub half, under a dedicated
  account.** A tool allowlist cannot
  contain an agent that has a shell, and a compliant agent is indistinguishable from a contained
  one — but a read-scoped token is refused by the API whatever the agent runs and however
  cooperative it is being. `driver/credentials.py` builds the agent's child environment with the
  read token and strips every write-capable one; `driver/writes.py` performs the run's comments,
  labels, branch push and PR from a schema-validated manifest, under the driver's write token.
  There is no manifest kind that merges.

  **And there is no degraded mode.** An earlier revision of this change let the driver fall back to
  the host `gh` keyring, with a loud warning. That was wrong for the reason the whole allowlist
  section above is written: a fallback is reached by *omission* — an unexported variable, a cron
  with a clean environment — and warnings scroll past. The driver now requires `DRIVER_GH_LOGIN`
  plus both tokens, verifies each token against a live `gh api user`, and refuses to start if
  either belongs to somebody else. It runs under its own account or it does not run.

  That also supplies #183's missing input. The driver's identity was previously whatever the host
  happened to be authenticated as, which is why `has_new_human_comment` could only guess by
  suffix; a PAT-backed machine user has no `[bot]` suffix, so the guess failed and the driver
  unparked the issues it had just parked. `credentials.bot_logins` now carries the configured
  login, which settles #183 criteria 1 and 2. Criteria 3 (a comment watermark relative to the park
  time) and 4 (attempt counters surviving an unpark) are untouched and the issue stays open.

  **What #191 did not settle**, and is still the spike's open question: the *local* half. The agent
  runs as the same uid as the driver, with a shell. So `Bash(python3:*)` is still a write primitive
  against the working tree, and — the sharper point — **every file the driver's operator can read,
  the agent can read too**: `~/.zshrc`, the user credentials file, the `gh` keyring. The driver's
  refusal to load a raw write token from a `.env` inside the agent's tree is hygiene against
  accidental commit and backup, not a wall; it is documented as such in `usage.md` rather than left
  to be inferred.

  The single asymmetry that does hold is incidental: macOS does not expose a process's environment
  through `ps`, even to its owner, so a token living only in the driver's environment is not
  readable that way. Verified 2026-08-10 against `ps eww` and `ps -E`. On Linux
  `/proc/<pid>/environ` is readable by the same uid and this does not hold, which is exactly why it
  is not load-bearing.

  **Decided 2026-08-10: deferred rather than solved.** Both tokens live in a git-ignored `.env`,
  and the driver refuses only a credential in a file git would actually add — a token one
  `git add -A` from publication is recoverable-from but not undoable, and that is the part that was
  ever real. An earlier revision refused any write credential inside the agent's tree; it was
  removed because it forbade the working configuration while buying nothing, which is the shape of
  a control that measures away rather than protects (findings.md defect class 4).

  So the honest statement is two claims, only one of them enforced: *the agent cannot act on GitHub
  as anyone but its own read-only self* — mechanism — and *a determined agent on this host could
  still find the driver's write token* — true, unmitigated. Closing the second needs a separate
  uid, a container, or a different machine (#3's GHA host would do it). The spike's proposal — give
  the verifier no `Bash` at all and have the parent run the manifest's named commands — narrows the
  verifier case specifically, and remains unbuilt.
- **Where park state lives** → **decided 2026-07-29 (#5): a `driver-parked` label on the issue.**
  This **revises D1 in part**, and the revision is the interesting half. Triage had settled D1 —
  derive the park list from the latest outcome per issue in `runs.jsonl` — and the handoff said not
  to re-litigate it. What reopened it was a different question: *where does the durable store live?*
  D1 answered correctness and left the store under `--state-dir`, so the durability criterion
  absorbed from #3 had **no named mechanism**, and `plan.md`'s rule is that a missing load-bearing
  decision is a stop, not a guess.

  What the label buys that the ledger could not: selection now consults **no local state at all**
  (marker, tier, open PRs, board column and the park bit are all GitHub); **repo scoping is
  structural**, where a ledger-derived list needed a filter, since `parked.jsonl` recorded no `repo`
  and `runs.jsonl` already mixes two; and a **GHA host needs nothing carried in or committed back**,
  where a tracked ledger would have meant a bot commit per run plus a race between concurrent runs.

  D1's objection — a second record type can drift — still holds in general, and is weaker for a
  mutable single bit than for an append-only log: the last-record-wins fragility that caused the bug
  cannot recur. The framing that survives, and the one the old design lacked: **the ledger is
  history, the label is current state**, and conflating those two *was* the bug. `runs.jsonl` still
  supplies the skip reason, which is the half of D1 that was right.

  Cost, paid knowingly: the write side came back (there is an un-park action again), and the driver
  became a GitHub **writer** for the first time. `CLAUDE.md` bounds that — issue metadata, never
  issue or PR content.
- **The amendment trigger's tree** → both trees; see the entry above.
- **Language split in `driver/`** → **bash for orchestration, Python for parsing and
  classification.** Orchestration means flags, process control, and invoking `gh`/`git`/`claude`;
  parsing and classification live in `driver/gate.py`. Decided in move 7 and it explicitly argues
  *against* rewriting the driver in Python: the defects it hit — `Edit(` matching inside
  `NotebookEdit(`, an `@`-anchored sha regex, `head -1` on a leading blank line — were
  **under-specified pattern matching, which recurs in any language.** The measured reason to act was
  different: `test-driver.sh` hand-copied the classifier and had already diverged, so the suite
  graded a replica. **`gate.py` must stay stdlib-only** so the driver remains portable to a runner
  that has no `uv`; pytest is a dev dependency of its *tests* only.
- **Board column vocabulary** → **read `gh project field-list`, never the doc.** The three actively
  managed boards use `Backlog / Ready / In progress / In review / Done`, which is what the skill
  transitions through; `gh project create` applies no template and yields a bare
  `Todo / In Progress / Done`, missing two of the three states the skill needs. This repo's board
  was renamed to match. Mechanics in [findings.md](findings.md#gh).

---

**Where to go next.** The backlog is on [the board](https://github.com/users/lmorchard/projects/9).
[findings.md](findings.md) has the durable lessons and the verified gotchas. [usage.md](usage.md) is
how to run any of it. Moves 1–5 are chronicled in [archive/build-log.md](archive/build-log.md); moves
6 onward in their session notes under [dev-sessions/](dev-sessions/).
