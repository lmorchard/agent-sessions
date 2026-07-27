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
3. **Autonomous board consumption.** No shipping tool self-selects work off a backlog —
   all require per-task human assignment (Copilot: human assigns each issue). This is the
   riskiest, least-explored piece — where our escalation gating matters most, and where
   we'll do original design.
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

## Leads not yet surveyed (added 2026-07-27, move 5) — ALL UNVERIFIED

Everything above was surveyed when this project was a **skill**. It has since grown a harness, a
machine-readable merge gate, and a measurement practice, and those have prior art nobody went
looking for. Each lead below is paired with the **specific unsolved problem** it might answer —
that pairing is the only reason to chase any of them.

**None of this was fetched.** It is model recall at the end of a long session, in a repo whose
central lesson is that confident recall is unreliable. The root URLs are high-confidence; the
*claims about what they contain* are exactly where to expect error. Treat these as search terms,
not findings.

### 1. Claim-binding — the recurring defect class already has a literature
**in-toto** <https://in-toto.io/> · **SLSA** <https://slsa.dev/>

Supply-chain attestation formats exist to make a claim *bound to the digest of the thing it
describes*, on the theory that an unbound claim is merely a nearby assertion. **That is the
adjacent-evidence defect class** ([findings.md § 1](findings.md#1-a-row-satisfied-by-evidence-adjacent-to-what-it-names--open-gap),
nine instances as of move 6) — `tamper: clean` hiding an absent diff, `ci: 2/2 pass` describing a
commit that no longer ships. `ci: … @ <sha>` is a hand-rolled mini-attestation, and
"make the value carry what it describes" was independently rediscovered here.

*Chase first:* whether the `agent-session:gate` block should **be** an attestation rather than
resemble one, and whether their threat model already enumerates the substitution/staleness
failures this project keeps finding one run at a time. Highest-value lead of the four.

*Partially validated already:* **Bernstein** (see the comparison section above) ships signed
lineage plus an HMAC-chained audit log a reviewer can verify **offline without rerunning it** — the
attestation idea, in this exact domain, today. Read that before designing anything.

### 2. Instruction evaluation — the measurement cost limit
**DSPy** <https://github.com/stanfordnlp/dspy> · **promptfoo** <https://promptfoo.dev/>

Move 5 cost ~$50 and half a session to ablate **one** section of instruction text, hand-rolled
from `claude -p` + `jq` + bash. About six of the skill's rules remain unmeasured, and that price
is the standing reason they may stay that way. DSPy's premise — treat prompt text as parameters
optimised against a metric rather than prose to be argued about — is the automated form of what
move 5 did by hand; eval harnesses like promptfoo target the run-N-variants-and-compare loop
directly.

*Chase first:* whether either can drive a **control-vs-treatment ablation with per-rep outputs
readable by hand**, since reading every rep is where all of move 5's value came from — a harness
that only reports aggregate scores would have concluded the opposite of the truth.

### 3. Change classification and bot-merge policy — phase 3
**ITIL "standard change"** (no single canonical URL) · **Renovate** <https://docs.renovatebot.com/>

`auto-ok` / `needs-review` is structurally the decades-old **standard vs. normal change**
distinction: a standard change is pre-approved because it is low-risk, repeatable and
well-understood, and bypasses the review board *by policy*. Separately, Renovate and Dependabot
are the shipping, narrow, **successful** version of unattended PR generation with conditional
auto-merge — they have a real policy language for "when may a bot merge?"

*Chase first:* Renovate's automerge configuration surface. Phase 3 has now receded three times and
its gate list grows by roughly one per session; someone has already had to design this decision
surface for a constrained domain, and the shape of what they chose to make configurable is the
useful part.

### 4. Mutation testing — a name for a practice already in use
**PIT** <https://pitest.org/> · **Stryker** <https://stryker-mutator.io/>

*"Mutate the thing the guard guards and watch it fail"* — arrived at here after three guards
shipped unable to fail — is test adequacy via mutation, and it has tooling and vocabulary. Lowest
value of the four, because the practice is already habitual; worth it only for the vocabulary and
for whatever the literature says about **where mutation testing misleads**.

## Unverified flags (confirm before relying)
**The entire "Leads not yet surveyed" section above** — recalled, never fetched.
OpenHands SWE-bench % and MAX_ITERATIONS default; all Devin/Sweep/Zencoder/Factory
capability claims; the autonomy-research percentage findings (~80% safeguarded / ~73%
human-in-loop / ~0.8% irreversible); Tessl beta status; any pricing/version/date. The two
Anthropic posts fetched directly (harness, autonomy) are solid; other Anthropic posts
cited from summaries are consistent but unfetched.
