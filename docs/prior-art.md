# Prior art

Survey run 2026-07-23. Sources are primary docs/papers where fetched; **[unverified]**
marks claims that came only from third-party search summaries (specific version numbers,
pricing, benchmark %, beta status) — leads to confirm, not facts. This discipline is
itself the thesis applied to research: an unverified confident claim is a weak oracle.

## TL;DR

Our design is **mostly well-trodden — adopt, don't reinvent.** The execution loop, tests-
as-oracle, spec+acceptance-criteria artifacts, the requirements-interview agent, and the
verification-loop discipline all have strong precedent. The genuinely novel seams are
narrow and worth focusing effort on. And there's one *correction* to our governing
principle (see "Verifier fallibility").

## Adopt (well-trodden — borrow the mechanism)

### Execution loop shape
Issue → research → plan → implement → test → PR → address review is shipped by several
tools. Nothing here is novel; borrow the guardrails others learned the hard way.

- **GitHub Copilot coding agent** — assign an *issue* to Copilot; runs in an ephemeral
  GitHub-Actions env (firewall on by default), decomposes the issue into a **checklist in
  the PR**, pushes commits, runs tests/linters, revises on review. **Can never merge its
  own work** — every PR is human-gated. This is the closest commercial analog to our
  execution half, and its hard no-self-merge boundary is a design precedent for our merge
  gate. Does *not* pull from a board — a human assigns each issue.
  <https://docs.github.com/copilot/concepts/agents/coding-agent/about-coding-agent>
- **OpenHands** (ex-OpenDevin) — closest open architectural analog: stateless Agent emits
  Actions, a Conversation loops over an append-only EventLog, a Docker Workspace executes.
  Borrow its **hard iteration/cost ceilings + stuck-detection** (repeated identical
  action/observation → break). MIT. <https://github.com/OpenHands/OpenHands>
  ( `MAX_ITERATIONS` default ~100, SWE-bench ~77% — **[unverified]** )
- **Devin / Jules / Cursor background agents / Open SWE** — all task-in / PR-out async
  loops; capability specifics **[unverified]**. <https://jules.google/> ·
  <https://cursor.com/blog/scaling-agents> ·
  <https://blog.langchain.com/introducing-open-swe-an-open-source-asynchronous-coding-agent/>
- **SWE-agent** — the Agent-Computer Interface insight: the *tool surface* the agent acts
  through is a first-class design lever (decafclaw already treats tool descriptions as a
  control surface). <https://arxiv.org/abs/2405.15793>

### Acceptance-criteria grammar — don't invent one
- **AWS Kiro** uses **EARS** notation: `WHEN [condition] THE SYSTEM SHALL [behavior]` —
  the most concrete machine-friendly criteria grammar in production tooling; maps cleanly
  condition→assertion. Three-file spec: `requirements.md` (EARS) / `design.md` /
  `tasks.md`. <https://kiro.dev/docs/specs/>
- **BDD / Gherkin** `Given-When-Then` — acceptance criteria as executable scenarios wired
  to a suite (Cucumber); explicitly "the definition of done," persisting as regression
  tests. <https://testquality.com/gherkin-user-stories-acceptance-criteria-guide/>
- **Decision for our intake half:** author criteria in **EARS or Given-When-Then** rather
  than inventing a format. Both are human-readable *and* map to a runnable check — exactly
  the "criterion names its own verifier" bridge.

### Spec-driven development tooling
- **GitHub Spec Kit** (`specify` CLI) — spec = user stories + acceptance criteria, frames
  criteria as enabling *automated verification*, orders tests contract→integration→e2e→unit
  (testability-first), has a "verify" phase. <https://github.com/github/spec-kit>
- **Tessl** (Podjarny) — specs capture "example cases that later become tests."
  <https://tessl.io/blog/how-tessls-products-pioneer-spec-driven-development/>
- All three make verifiability *rhetorically* first-class ("specs become tests") but **do
  not mechanically reject a criterion lacking a runnable check.** That gate is where our
  intake half is stricter (see Novel #2).

### Requirements-interview agents (the "grilling" pattern)
Active academic subfield — our intake half is well-grounded.
- **LLMREI** — automating elicitation interviews; LLMs can conduct them but need human
  help on domain-specific complexity (→ argues for an escalation tier).
  <https://arxiv.org/html/2507.02564v1>
- **Follow-up question generation** — LLM follow-ups guided by a framework of *common
  interviewer mistakes* beat human-authored ones. Borrow: prompt the interviewer with an
  anti-pattern checklist. <https://arxiv.org/abs/2507.02858>
- **ReqElicitGym** — classifies interviewer actions as **clarify / probe / finish** — a
  clean state machine for the intake loop. <https://arxiv.org/html/2602.18306>

### Verification-loop discipline (Anthropic, fetched + verified)
- **"Effective harnesses for long-running agents"** — recommends a **feature-list JSON**,
  each feature with discrete steps + explicit pass/fail; names the central failure mode
  (**agents mark features done prematurely**); mandates self-verification; states **"it is
  unacceptable to remove or edit tests."** That's our machine-checkable criteria in-harness,
  plus the guardrail against an agent gaming its own verifier.
  <https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents>
- **"Measuring AI agent autonomy in practice"** (fetched) — rejects discrete L0–L5 for a
  continuous 1–10 scale; classifies by **autonomy level, environmental impact,
  reversibility, safeguards, human oversight**. Key line: *"autonomy is not a fixed
  property of a model or system but an emergent characteristic of a deployment."* Adds a
  dimension we hadn't: **route on reversibility, not just verifiability.**
  <https://www.anthropic.com/research/measuring-agent-autonomy>
- **"Building Effective Agents"** — workflow (code orchestrates) vs agent (model chooses);
  our execution loop should be **workflow-shaped** (code drives stages, LLM is a
  constrained worker) — aligns with decafclaw's own `workflow/` thesis. **[not fetched]**

## Novel / underserved (our differentiators — spend effort here)

1. **Verifiability as the routing function for autonomy.** Everyone rhetorically links
   tests to done-ness; Anthropic tiers by risk/reversibility. Nobody found makes *"can
   every acceptance criterion be mechanically checked?"* the explicit gate deciding
   safe-to-automate vs. needs-review. That coupling is the crisp, defensible core of our
   thesis, and appears unclaimed.
2. **Mechanically-enforced verifiable criteria at intake.** Spec Kit / Kiro / Tessl aspire
   to it; none *reject* a criterion without a runnable oracle. Our readiness gate refusing
   "no criterion without a check" is a real sharpening.
3. ~~**Autonomous board consumption.** No shipping tool self-selects work off a backlog —
   all require per-task human assignment (Copilot: human assigns each issue).~~
   **FALSE as of 2026-07-27 — corrected, see "Complete-system comparison" below.** OpenAI's
   **Symphony** watches a task board and picks up new work unprompted, and hobbyist Claude Code
   loops do the same. **Narrowed claim that survives:** board consumption *gated by a
   verifiability tier decided at intake* — Symphony and the rest review **after** the fact, so
   nothing found routes work by whether it can be checked *before* the work starts. Still the
   riskiest, least-explored piece, and still where our escalation gating matters most.
4. **The two halves as one closed system.** Interview-agent research and execution-agent
   products exist separately; wiring the intake grill's output (verifiable criteria +
   escalation label) directly into the execution loop's autonomy gate is an end-to-end
   integration nobody in this survey ships.

## Verifier fallibility — a correction to the governing principle

The single most-repeated caution, from two independent directions:
- **SWE-bench** uses tests as the oracle (FAIL_TO_PASS ∧ PASS_TO_PASS, prose never
  eyeballed) — the canonical precedent for our thesis. *But* the literature documents
  **test-log mis-parsing → wrong pass/fail annotations** ("Rigorous Evaluation of Coding
  Agents on SWE-Bench," ACL 2025, <https://aclanthology.org/2025.acl-long.189.pdf>).
- Anthropic's verification-loop work names **self-verification bias**: *"the same agent
  that produced a patch is naturally biased toward accepting it."*

**Correction:** "only as autonomous as its verifier is trustworthy" must extend to
*validating the oracle itself.* "Criterion is machine-checkable" is **necessary but not
sufficient** — the check must also be *correct*, and the verifier should be **independent
of the implementer** (separate agent/context), with acceptance tests **frozen before
implementation** so the implementer can't weaken them (mirrors SWE-bench's frozen
`test_patch` and Anthropic's "unacceptable to edit tests"). An untrustworthy green check
is worse than no check.

## Property-based middle tier
When a criterion can't become a concrete example test, a **property/invariant** may still
make it machine-checkable — a tier between "concrete test" and "escalate to human."
Property-Generated Solver: a Tester agent derives properties from the spec, compiles them
to executable checks, feeds failures back. <https://arxiv.org/abs/2506.18315>

## Complete-system comparison (2026-07-27, move 5) — FETCHED, not recalled

The original survey looked for tools doing *aspects* of this. This pass looked for whole systems.
**Four were fetched and read** (Spec Kitty, Bernstein, Symphony via InfoQ, Galarza's loop); the
listicle summaries around them were not trusted, and one turned out wrong — see the caution at the
end.

### The closest four

**Symphony** (OpenAI, ~May 2026) — <https://github.com/openai/symphony>, a `SPEC.md` standard plus
an Elixir reference implementation, explicitly *"not positioned as a standalone product."*
**It self-selects:** *"continuously watches the task board and ensures that every active task has
an agent running in the loop until it's done. If new work appears, Symphony picks it up."*
No verifiability tier, no frozen checks; *"once a task is complete, a human is responsible for
reviewing the output"* — review is **post-hoc**, not a routing decision made in advance.

**Spec Kitty** — <https://github.com/Priivacy-ai/spec-kitty>. Closest **artifact shape** of
anything found: specs, plans, work packages, acceptance criteria, review state and merge decisions
all kept in-repo, agents in isolated worktrees, kanban dashboard. Workflow is
`spec -> plan -> tasks -> next -> review -> accept -> merge`. But `spec-kitty next --agent <agent>
--mission <slug>` is **operator-invoked** — no self-selection — and the docs do not show criteria
deriving runnable checks, a verifiability tier, or a frozen-check/independent-verifier split.

**Bernstein** — <https://github.com/sipyourdrink-ltd/bernstein>. The most interesting one, and it
made the same structural bet this project did: **no model in the coordination loop** (deterministic
orchestrator, one LLM call then plain Python), per-task git worktrees, parallel runs that replay
byte-identically. It also ships **signed lineage plus an opt-in HMAC-chained audit log** that
*"someone who did not run it can check offline, without rerunning it."* That is the attestation
idea from lead 1 below, **already shipping in this exact domain**.
Where it differs: its "janitor" verifies **generic gates** — *"tests pass, files exist, lint clean,
types correct"* — not per-task acceptance criteria fixed in advance. Goals are human-supplied
(`bernstein -g "fix the failing test"`), not drawn from a tracker.

**Damian Galarza's Linear-driven loop** — <https://www.damiangalarza.com/posts/2026-02-13-linear-agent-loop/>.
The closest analog to *our board-driver specifically*: takes the highest-priority Todo, falls back
to the backlog, implements, spawns **separate reviewer subagents** that *"evaluate the diff against
the issue requirements"*, opens a PR. No tier system. **Does not merge** — *"I still review every
pull request before merging."*
**Steal his failure modes, both of which we will hit:** stale PRs accumulating merge conflicts as
features land (our re-verification tax, independently rediscovered), and difficulty applying human
feedback. His fix is a `bin/pr_check` that **prioritises PRs needing revision before starting new
work** — a queue policy our driver does not have and probably needs.

### What this does to the four stated differentiators

- **#1 verifiability as the routing function** — still looks **unclaimed**. Nothing found makes
  "can every criterion be mechanically checked?" the gate deciding autonomous vs. human. Symphony,
  Spec Kitty and Galarza all review *after* the fact; Bernstein verifies generically.
- **#2 criteria rejected without a runnable oracle** — still looks unclaimed.
- **#3 autonomous board consumption** — **NO LONGER TRUE AS WRITTEN.** The survey said *"no
  shipping tool self-selects work off a backlog."* Symphony does, and hobbyist Claude Code loops do
  too. **Narrow the claim** to: board consumption *gated by a verifiability tier decided at intake*.
- **#4 the two halves as one closed system** — still the honest differentiator, now the main one.

Also worth correcting an emerging worry: **nobody found auto-merges.** Galarza reviews every PR,
Spec Kitty's merge is a deliberate step, Symphony ends in human review. Being eight PRs deep with
nothing merged is **where the field is**, not where this project is behind.

### Caution — the listicles were wrong at least once

Search summaries and SEO round-ups (augmentcode.com and similar) claimed Bernstein *"uses
spec-driven verification where a living artifact constrains what agents can produce and a verifier
checks compliance before merge."* **Fetching the repo did not support that** — the janitor is
generic gates. Not fetched and therefore not repeated here: OpenSpec's star counts and three-phase
state machine, Composio AO's autonomous PR lifecycle, Kiro's 2026 SMT-solver requirements analysis,
SpecRoute. Each is a lead, not a fact.

## Leads 1-3 — SURVEYED AND VERIFIED (move 7, 2026-07-28)

Fetched primary sources. **Two of the three recorded claims did not survive**, which is the point of
fetching. What each lead was paired with — a specific unsolved problem — is kept, and answered.

Lead 4 (PIT / Stryker, mutation testing) remains unfetched and was ranked lowest value; the practice
is already habitual here.

### 1. Claim-binding — mechanism CONFIRMED, the valuable half REFUTED

Sources: [SLSA provenance v1.0](https://slsa.dev/spec/v1.0/provenance) ·
[SLSA threats v1.0](https://slsa.dev/spec/v1.0/threats)

**Confirmed:** provenance binds a claim to what it describes via in-toto's **`subject`** field
carrying a **`digest`** (`sha256`, `sha512`, `gitCommit`). Threat **(F) "Tamper with artifact after
CI/CD"** is mitigated by requiring *"the provenance's `subject` matches the hash of the package."*
So the mechanical idea is real and standardised.

**Refuted — and this was the hoped-for payoff.** The recorded lead asked *"whether their threat model
already enumerates the substitution/staleness failures this project keeps finding one run at a
time."* **It does not.** Checked both the provenance spec and the dedicated threats page:

- an attestation **applied to a different artifact than the one it describes** — not modelled; the
  spec assumes the verifier applies it correctly,
- **staleness**, where provenance correctly describes a commit that is no longer what ships — not
  covered,
- **verification satisfied by adjacent-but-different evidence** — not enumerated as a threat.

The model is **build-artifact-centric**; ours is a **verification-time** problem, and the standards
push it onto "the consumer." **So this project is not behind a literature here.** The sweep (#2)
cannot crib a threat list; it has to enumerate its own.

**What does transfer, and it is actionable.** `subject` + `digest` validates the shape we
independently reached with `ci: … @ <sha>`: *make the value carry the digest of what it describes.*
Generalised, that is a question the sweep should ask of **every** row, not just `ci` — and one
answer is already visible. **`project-gates` records a local `make check` and names no commit at
all**, so it is an unbound claim of exactly the shape the `ci` row used to be. Candidate instance
for #2.

### 2. Instruction evaluation — promptfoo CONFIRMED with a trap; DSPy is the wrong tool

Sources: [promptfoo CLI](https://www.promptfoo.dev/docs/usage/command-line/) ·
[promptfoo configuration](https://www.promptfoo.dev/docs/configuration/parameters/) ·
[DSPy](https://dspy.ai/)

**promptfoo confirmed fit for purpose.** `--repeat <number>` ("Number of times to run each test")
gives reps per case; multiple `prompts:` entries against one test set give control-vs-treatment;
`-o` exports `jsonl`/`json`/`csv`, so **per-rep raw outputs survive for reading by hand** — the one
requirement move 5 could not do without. It could plausibly replace this project's hand-rolled
`claude -p` + `jq` + bash harness.

**The trap, and it would have invalidated the study silently.** *promptfoo caches LLM responses by
default.* `--repeat 15` without `--no-cache` returns **identical cached results** — so a study whose
metric **is variance** would report zero variance and every arm would look perfectly consistent.
That is this project's "a null must never render as a positive," one level up: the instrument's
default setting destroys the measurement while appearing to work. Move 5's entire value was in the
8/15-vs-15/15 spread. Related: `PROMPTFOO_STRIP_RESPONSE_OUTPUT` discards model outputs from
results — a second way to lose exactly what must be read.

*(Documented, not yet run here. If promptfoo is adopted, verify the cache behaviour empirically
first — same discipline as every other claim in this file.)*

**DSPy refuted as the wrong instrument.** Its premise is *"Program, don't prompt"* — express tasks as
structured signatures and let it *"tune your prompts automatically until quality converges,"*
demonstrated by aggregate movement (0.41 → 0.63 F1). It optimises toward a score; it is not an
ablation tool that preserves per-example outputs for human reading. **A tally-only reading of move
5's study would have concluded the opposite of the truth**, so an optimiser that reports convergence
is precisely the wrong shape for this project's question.

### 3. Change classification and bot-merge policy — CONFIRMED, and it sharpens our own design

Sources: [Renovate configuration options](https://docs.renovatebot.com/configuration-options/) ·
ITIL 4 change enablement (see Sources below)

**Renovate's policy surface is real**: `automerge`, `automergeType` (`branch`/`pr`/`pr-comment`),
`automergeStrategy`, `automergeSchedule`, `minimumReleaseAge`, `ignoreTests`, `platformAutomerge`,
and `packageRules` for scoping.

**The single most transferable line found in this whole survey:** *"Renovate only automerges branches
which are **up-to-date and green**."* Up-to-date is exactly our `ci-stale` guard — and they treat it
as a **precondition of automerging**, not as a post-hoc validity check on a verdict already
published. Our gate derives a verdict and *then* asks whether the commit still ships. Theirs cannot
reach the question. Worth weighing for phase 3.

Also notable: `minimumReleaseAge` is a deliberate **wait before acting** expressed as policy rather
than a poll — compare move 4c, where "wait for CI to settle" had to become `gh pr checks --watch`
because every polling mechanism was denied.

**Partly refuted:** there is **no pre-approved-low-risk-category concept**. Renovate scopes automerge
through `packageRules` on the *nature* of the change (minor/patch yes, major no), not via a durable
per-item label.

**And ITIL sharpens a real weakness in our tiering.** A standard change is low-risk, repeatable and
**pre-authorized**, requiring three things together: the procedure is fully documented, the risk is
**formally accepted in advance**, and **prior runs have proven the outcome predictable**. Crucially,
**the governance body pre-approves the *template*, not the instance.**

Our `auto-ok` is stamped **per issue**, by intake, on that issue's own criteria. We have no notion of
*"this kind of change is auto-ok because N prior instances of it landed cleanly."* That gap matters
for the open phase-3 decision in `design.md`: ITIL's answer to *when may this be automatic* is
**"when prior runs have proven the outcome predictable"** — a finite, evidence-based exit condition,
which is exactly what a gate list that grows by one per session lacks.

## Unverified flags (confirm before relying)
~~The entire "Leads not yet surveyed" section above — recalled, never fetched.~~ →
**Leads 1-3 fetched and verified in move 7** (two claims refuted; see above). **Lead 4 (PIT /
Stryker) was never fetched** and remains recall. promptfoo's caching behaviour is documented but
not empirically confirmed here.
OpenHands SWE-bench % and MAX_ITERATIONS default; all Devin/Sweep/Zencoder/Factory
capability claims; the autonomy-research percentage findings (~80% safeguarded / ~73%
human-in-loop / ~0.8% irreversible); Tessl beta status; any pricing/version/date. The two
Anthropic posts fetched directly (harness, autonomy) are solid; other Anthropic posts
cited from summaries are consistent but unfetched.
