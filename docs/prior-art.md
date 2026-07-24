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

## Unverified flags (confirm before relying)
OpenHands SWE-bench % and MAX_ITERATIONS default; all Devin/Sweep/Zencoder/Factory
capability claims; the autonomy-research percentage findings (~80% safeguarded / ~73%
human-in-loop / ~0.8% irreversible); Tessl beta status; any pricing/version/date. The two
Anthropic posts fetched directly (harness, autonomy) are solid; other Anthropic posts
cited from summaries are consistent but unfetched.
