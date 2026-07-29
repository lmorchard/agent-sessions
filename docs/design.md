# agent-sessions — design

**What the system is and why it has this shape.** Start here. Captured 2026-07-23 from the
originating brainstorm and kept current since; the reasoning trail is preserved so the *why*
survives.

Two companion files, split out of this one in move 6:

- **[findings.md](findings.md)** — the durable lessons: recurring defect classes, the evidence
  ledger, the instrument rules, and the verified command gotchas. **Read it second, and read it
  before writing any flag list or gate row.**
- **[build-log.md](build-log.md)** — the chronological account of moves 1–5. Provenance only;
  nothing reads it to make a decision.
- **[usage.md](usage.md)** — the operator's guide: commands, outcomes, run artifacts, recovery.
  Written for someone running the thing rather than changing it.

[prior-art.md](prior-art.md) has the external survey, and [../README.md](../README.md) is the
plain-language introduction.

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
4. **Hooks** — `PreToolUse` can hard-block even under `bypassPermissions`; guardrails, not
   the primary loop.

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
3. **Conditional auto-merge.** Only `auto-ok` issues with all-green checks + no unresolved
   review threads. auth/data/deploy/`.github`/new-deps stay human-gated (aligns with the
   standing never-deploy-without-permission rule). Start conservative: auto-merge nothing
   until Phase 2 has earned trust.

**Safety:** avoid `--dangerously-skip-permissions` / `bypassPermissions`. Scoped
`--allowedTools` + `dontAsk` gets ~95% of the autonomy with a real floor under it.

## The two-skill system

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

## Two products in one repo

Worth stating plainly, because the docs have drifted toward describing only the first. This repo
holds **two artifacts with different audiences and different correctness regimes**, and conflating
them is what makes "is this a skill-authoring project?" feel like a confusing question:

|  | `skills/agent-session/` | `driver/` + `Makefile` |
|---|---|---|
| What it is | the reusable artifact — a Claude Code skill, `dev-session` lineage | this repo's autonomy infrastructure, the unattended burndown loop |
| Roughly | ~1,880 lines of markdown | ~1,100 lines of bash |
| Its oracle | micro-tests and dogfooding | fixture tests and mutation testing |
| Who reads it | any project that installs the skill | only this repo |

They are deliberately separable: **the board-driver needed zero skill changes**, and
`make skill-readonly` enforces that a hosted run may read the skill but never write it. The
governing principle applies to both, but the *cost* of applying it differs by an order of
magnitude — a skill-wording oracle is a micro-test at ~$50, a driver oracle is a fixture test at
zero. That asymmetry drives most of the sequencing decisions in the roadmap.

This is a distinction to keep, not a project to rename.

## What is built

Decided: **single `agent-session` skill, multi-mode dispatcher** (dev-session lineage), not
separate skills. Rationale: sidesteps the unverified cross-skill file-sharing mechanism
entirely (all refs in-dir), and the dispatcher's lazy-load means modes never co-reside, so
adding modes doesn't confound the LLM mid-phase — the only confounding risk is at the entry
boundary, mitigated by explicit mode arguments + an ask-don't-guess dispatcher. Heavy modes
fan out to subagents; the board-driver stays *above* the skill as orchestration.

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
- `phases/pr.md` + `references/pr-body-template.md` — the **tiered merge gate**, derived by
  reading rows (all checks pass per the verifier + human-graded judgment criteria + clean
  tamper diff + green project gates + no unresolved threads + `auto-ok` + no risk-gated paths).
  Emits a machine-readable `<!-- agent-session:gate -->` block. **Never merges.**
- `phases/express.md` — Phase 0 checks *preconditions* (marker / readiness / size) instead of
  judging complexity by feel; a missing marker routes to `intake`. Tier decides only *where the
  run surfaces to a human*, not whether it runs.
- `references/session-setup.md`, `references/plan-template.md`, `references/github-projects.md`.

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


## Current state (2026-07-27, end of move 5)

**The skill is complete and all four routing paths have real-run evidence.**

| Path | Evidence |
|---|---|
| `auto-ok` → `eligible-for-auto-merge` | #586 → PR #665 · #585 → PR #699 · #710 → PR #714 · #668 → PR #719 · #656 → PR #722 |
| `auto-ok` → `human-merge-required` | #638 → PR #659 (unresolved threads it must not self-resolve) |
| `needs-review` → `human-merge-required` | #649 → PR #686 (risk-gated diff, surfaced exactly once) |
| Designed stop before the gate | starnet #129, halted at Phase 0 on a vacuous criterion |

**Seven PRs have gone through the skill, and six are merged** — #659, #665, #686, #699, #714 and
#719, every one merged by Les, by hand, usually within hours of the run. Only #722 is still open.
*(Earlier handoffs said "eight PRs, nothing merged." Both halves are stale; the count could only be
reconciled to seven, and the merges are real.)*

That matters more than a bookkeeping correction: **the loop lands work.** What has not been
automated is the merge *click*, not the outcome. Phase 3 buys the click.

**The board-driver runs.** `driver/agent-session-driver.sh` — five stages (`select` → `invoke` →
`classify` → `record` → `report`), host-agnostic by construction (no `$HOME` assumptions, every
path a flag, all state under one `--state-dir`). It needed **zero** skill changes, and that is
enforced rather than asserted by `make skill-readonly`. The multi-issue loop has run for real
(`--max-issues 2` over #668 and #656, $22.96).

**Nothing merges by machine.** Both terminal verdicts mean *park the PR and move on*; only budgets
and failures stop the loop. `eligible-for-auto-merge` is a finding, not an instruction.

**Genuinely not yet proven:**

- **Phase 3 (conditional auto-merge)** — untouched, and gated on three things (see the roadmap).
- **`ci-stale` has never fired on a real PR.** Fixture tests only — verified against `runs.jsonl`,
  which contains no `ci-stale` outcome.
- **Multi-phase `execute` with real implementer subagents.** Every run so far has been small: #586
  was two greps on a 4-line diff, #585 a 4-line deletion. They tested the *chain* and the *driver*,
  not the *work*. decafclaw **#625** is the specced `needs-review` vehicle and has never been driven.

## Roadmap

Reconciled against the repo on 2026-07-27. Every entry below was re-verified, not copied — the
previous list had a **5-of-11 stale rate**, and this pass found four more. What was dropped and why
is at the end, because "this was checked and closed" is the part that rots invisibly.

### Blocking phase 3 (conditional auto-merge)

1. **The `PreToolUse` merge-block hook.** Verified absent — the driver only *references* it
   (`agent-session-driver.sh:47`, `:488`). A hard precondition for any **unwatched** host, because
   deny rules are prefix-matched and `gh api` stays reachable. Rider: the denial detector greps the
   permission layer's phrasing only, so a hook block would go **uncounted** — teach it when the
   hook lands.
2. **The adjacent-evidence sweep.** Nine instances of "a gate row satisfied by evidence adjacent
   to what it names," and only the ninth was found by looking rather than by an unattended run
   stumbling into it. See
   [findings.md § 1](findings.md#1-a-row-satisfied-by-evidence-adjacent-to-what-it-names--open-gap).
   Phase 3 converts each remaining one into an automatic merge.

**Open decision (Les's): the shape of this list.** It has grown by roughly one gate per session —
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

### Hosting

4. **The GHA host, and a durable park mechanism that survives a host change.** Verified: no
   `.github/` exists in this repo, and the park list is `./.driver-state/parked.jsonl` — relative
   to cwd, therefore per-machine.
5. ~~**A guard against `--repo-path` containing `--skill-dir`.**~~ **DONE** — issue #4, move 8.
   Landed as a *warning plus an opt-in refusal*, not the absolute refusal this entry assumed:
   triage found that `SKILL := $(CURDIR)/skills/agent-session`, so pointing the driver at **this**
   repo — the drivable `driver/`/`docs/`/`Makefile` work — *is* the nested configuration, and an
   absolute refusal would have foreclosed it. The self-modification hazard this entry names was
   already covered by `DENIED_TOOLS`, which is assembled from `SKILL_DIR` unconditionally; what the
   guard actually buys is fail-fast on a **typo**. Mutation-testability is structural: the eleven
   new cases invoke the shipped driver as a subprocess, so deleting the guard flips them.

   **Consequence for dogfooding:** driving *this* repo now requires `--allow-nested-skill-dir`.
   No shipped `make` target is affected — `run` defaults `REPO_PATH` to decafclaw, and `dry-run`
   passes no skill dir at all — but a hand-assembled self-run needs the flag.

### Driver state correctness

6. **`parked.jsonl` lies, and about more issues than previously recorded.** It is append-only with
   no un-park record. Verified live: stale `parked` entries exist for **#585 (twice), #710 and
   #656** — all four later reached `gate-eligible` in `runs.jsonl`. Moot in practice today (#585
   and #710 are closed; #656 has an open PR, so selection skips it anyway), but any future
   selection logic that trusts the park list is reading a state file that is wrong about four
   issues.

### Evidence gaps

7. **A real multi-phase `execute` run.** Vehicle: decafclaw **#625** — verified open, tier
   `needs-review` by trigger 2, four criteria and four guards, never driven.
8. **`ci-stale` firing on a real PR.**
9. **A decision on decafclaw #566.** Verified still open and still carrying three explicit open
   questions for the human; a loop would have to pick the design rather than implement one.

### Policy to settle

10. **The Agent-tool deviation.** `intake.md` step 2 and `triage.md` step 2 both dispatch
    subagents; the operator's standing instruction forbids the Agent tool unless asked, so research
    runs inline and the token-heavy reading lands in the main context — the exact cost the step
    exists to avoid. Taken as a named deviation three times now (moves 4b, 5, and this session).
    **This is a standing property of how the skill runs here, not an incident.** Decide it
    deliberately rather than re-discovering it mid-run.

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
  edit what it grades. Roadmap item 7 (#625) stays blocked on it.
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

**Next: move 7** — put this roadmap on a GitHub board and dogfood the skill's front half on it.
Brief in [handoff-restructure.md](archive/handoff-restructure.md). Board **yes**, board-driver **not yet**:
`make skill-readonly` makes this the one repo the driver must not run in, because here the
implementer's work product *is* the skill. The partition is already available through trigger 2 —
mark `skills/` risk-gated in `CLAUDE.md` and skill issues tier themselves `needs-review` without
touching a skill file. The `driver/` half stays drivable, and the gate-parser extraction is its
first real issue.
