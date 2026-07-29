# agent-sessions — findings

**The durable, still-governing lessons.** If you are picking this project up cold, read
[design.md](design.md) then this file, and stop there. The chronology in
[build-log.md](build-log.md) is provenance; nothing here requires reading it.

This file exists because the diary grew: every move produced lessons that outlived their run, and
they had nowhere to live except the narrative that produced them. **A lesson belongs here the
moment it would change what a future session does.** When you add one, state the rule, count the
instances, and link the build-log entries that are the evidence.

Two things this file is not. It is not a rules list for the skill — rules that shape agent
behaviour belong in `skills/agent-session/`, and this project's evidence says most of them do not
earn their place there (see [the evidence ledger](#the-evidence-ledger)). And it is not a summary
of the build log — it carries only what still governs.

---

## Recurring defect classes

Six patterns this project has hit more than once. Each has cost real money to rediscover.

### 1. A row satisfied by evidence *adjacent* to what it names — OPEN GAP

The dominant defect class, and the one the merge gate exists to prevent. A gate row, guard, or
check cites a specific mechanism; something *near* that mechanism supplies the answer; the row
reports true. Nothing lies, and the row means nothing.

**This is an open, actionable gap — not a retrospective.** Nine instances, and the class is **not
converging**: they are still being found one unattended run at a time, and move 5 alone produced
two. Worse, move 5's exit-code defect was *the same bug move 4c had fixed one field over, hours
earlier* — the fix was applied to the cost field and never generalised to the exit code. Fixing
instances one at a time is losing to the rate at which they arrive.

**The sweep that has never been done:** enumerate every gate row, guard and manifest check, and for
each one ask *"what could satisfy this that is not the thing it names?"* Instances 1–8 below were
each found by an unattended run stumbling into it; **none was found by looking.** Until that sweep
happens, the honest position is that the gate has an unknown number of these left, and phase 3
turns each remaining one into an automatic merge.

**Instance 9 is the one to sit with**, because it is the defect class *inside the mechanism meant
to catch it* — and it was found by looking, which is the argument for the sweep.

| # | Instance | Where |
|---|---|---|
| 1 | The gate cited `gh pr view <n> --json reviewThreads` — not a valid field. It errors and prints the field list, which reads like "no threads." | move 2 (#586) |
| 2 | The tamper mechanism is vacuous when criteria are commands rather than test files: nothing to diff, and the `clean` verdict could not be distinguished from *nothing-to-compare*. | move 2 (#586) |
| 3 | `checks.md` — for command-based criteria, the *entire* oracle — sat outside its own tamper baseline. | move 2 (#586) |
| 4 | `project-gates` recorded a *local* `make check` and cited no GitHub check runs, so the gate read `eligible-for-auto-merge` while CI was `pending` and `mergeStateStatus` was `UNSTABLE`. | move 3 (#699) |
| 5 | `gh pr checks --required` on a repo with no required checks: a row built on it either errors or passes vacuously. | move 4a |
| 6 | Import-boundary guard G3 stays green while the boundary it protects is gone — a capability that arrives as an *object* imports nothing. C4 was added to assert what G3 structurally cannot see. | move 4b (#625) |
| 7 | Three independent unattended runs reported `project-gates` satisfied **by substitute**, having run `make check`'s four steps natively because `make check` itself was unpassable. | move 4c |
| 8 | `amendments: none` was true only under one of two readings of the amendment policy. **Closed 2026-07-27** — the policy now names both trees, and under it #668 was an amendment. | move 5 (#668) |
| 9 | **The driver's test suite tests a replica of the classifier, not the classifier.** `test-driver.sh` hand-copies driver logic — one helper is annotated *"Mirrors the driver's extraction + comparison exactly"* with nothing enforcing that — and it has **already diverged**: `classify_outcome` is 53 lines in the driver and 15 in the copy, with **zero `ci-stale` awareness** in the copy. | verified 2026-07-27 |

**The tell:** the row names a command, and the evidence offered is not that command's output.
**The fix, every time:** make the row cite a command that is actually run, and make its failure
mode distinguishable from its success mode.

**Instance 9 is the live one**, and it is the worst of the nine. Verified by running both
classifiers over one identical gate block (`ci: 2/2 pass @ 0d08b2d`, head `e8f03389abcdef`):

```
shipped driver  -> ci-stale       "verdict rests on a commit that no longer ships"
test-file copy  -> gate-eligible  "all gate rows satisfied"
```

**The suite's classifier calls a stale-CI PR eligible for auto-merge exactly where the shipped
driver voids it.** So move 5's record that the ci-sha fix was "mutation-tested" does not hold for
the classifier path — mutating the driver's real regex leaves `driver-test` green, because the
behavioural assertions run against the test file's own mirror. Under phase 3, "eligible" means
merge.

### 2. A null must never render as a positive

Four instances, and it keeps arriving through a different door.

1. **`clean` vs `clean-by-substitute`** — the tamper vocabulary had no way to say *there was
   nothing to diff*, so a null rendered as a pass (move 2).
2. **`gh project item-list` truncates at 30** with no error. On a 185-item board the first queue
   read described a smaller board (move 3).
3. **Zero CI checks** — an empty check list means nothing failed, which is not everything passing.
   The row now reports `total` and the gate block has a `no checks configured` value (move 4a).
4. **The CI staleness check silently became a no-op.** It anchored sha extraction on a literal
   `@`; the real gate line used no delimiter, so nothing matched and staleness went unchecked on a
   PR about to be called eligible (move 5). **First time it was the verifier itself that became a
   null rather than a value.**

### 3. Brittle absolutes encoding relative invariants

Three instances, all guards. A guard pins a number or a sha; the real invariant is relative;
upstream moves; the guard trips while the property it protects still holds.

1. `#638` G1 pinned `3234 passed, 2 skipped`; a rebase made it `3265`. The property — *nothing
   lost, newly skipped, or newly failing* — held.
2. `#649` G6 went 130→140 and the suite 3425→3436 as upstream tests landed. The relative form
   earned itself twice in one run.
3. Move 3's G2 pinned a sha where the invariant is *"`main` is only ever fast-forwarded, never
   rewritten."* First one that was ours rather than inherited.

**Write the invariant, not the reading.**

### 4. Add-then-measure-away — 3 for 3

Every rule this project has added from a real failure and then measured has turned out not to
change behaviour. All three shared one tell: **the concept was already reachable elsewhere in the
skill, and the new rule restated it closer to where the failure was noticed.**

| Rule | Added because | Measured | Outcome |
|---|---|---|---|
| Goal-ambiguity tier trigger | triage found ambiguity was the dominant blocker | control 5/5 *without* it — folds into the human-judgment trigger unprompted | **cut**, 18 lines → 4 |
| Intake's withheld-decision exception | #649 was unspecifiable and intake refused the pass that could fix it | treatment 5/5 no over-trigger; control 5/5 correct without it, independently reproducing three of the paragraph's four sentences | **cut** |
| `acceptance-criteria.md` § 2, "Does it discriminate?" | #129's AC1 and #638's obvious check were both vacuous | 170 reps, 9 arms: file *without* § 2 scored **15/15**, file as shipped **8/15** (Fisher, p ≈ 0.006), replicated | **cut** |

**The mandated check before adding a rule: grep the skill for the concept.** On the discriminate
rule it appeared in **seven** places outside § 2, twice at the point of use.

**The instinct to add is apparently reliable; the judgment that it is *needed* is not.**

### 5. "I wrote a guard" is not evidence

A guard is decoration until you mutate the thing it guards and watch it fail.

- The `skill-readonly` guard grepped for `Edit(...)`, which matches inside `NotebookEdit(...)` —
  deleting the standalone `Edit` deny rule still passed. It *also* false-positived on an
  `Edit(//tmp/x/**)` example inside a comment. Written minutes after re-reading the warning about
  inert-content false positives (moves 4a, 4c).
- C4 asserting only that a façade *lacks* `attach`/`spawn`/`write_input` is satisfiable by never
  building the façade — `hasattr(None, "attach")` is `False`. It must assert existence *and*
  absence (move 4b).
- Of move 5's two new ci-sha tests, **only the stale one discriminates**: an unparseable sha also
  yields "current", so the obvious test would have been the non-discriminating one.
- Two micro-test fixtures in move 1 were discarded as non-discriminating. *"Control passed 5/5" is
  only evidence about wording when the fixture can actually fail.*
- **Eight live assertions in `test-driver.sh` are `grep -q "<literal>" "$DRIVER"`** — lines 196,
  202, 227, 269, 274, 281, 286, 351. Each passes if the string appears anywhere in the driver,
  including inside a comment. That is the same inert-content trap the `skill-readonly` guard fell
  into twice, still shipping (verified 2026-07-27). **A test that greps its subject for a literal
  is a spelling check, not a test.** *(An earlier version of this entry said "two" — it counted
  only the `ci-stale` pair. Corrected by a triage scanner.)*
- **`test-driver.sh:20` says "Source the driver's functions without running main."** The file
  sources nothing; it hand-copies. The comment describes the fix that was never made — the defect
  class in miniature, inside the file that demonstrates it.

Mutation-testing caught a non-discriminating test in move 5 that review did not.

### 6. The vacuous check is the default outcome, not a rare slip

When nobody runs a check before freezing it, it tends not to discriminate.

- starnet #129's AC1 (`SHALL produce zero tick-cap runs`) already passed on untouched code.
- #638's intuitive check, `pytest -W error::DeprecationWarning`, passes today — the warning is
  emitted in the forked child.
- The `triage` batch: **0 of 17 proposed criteria passed today**, across eight independent
  unsupervised contexts — the rule holding, not failing.
- #625's C1 passed vacuously whenever the widget registry was uninitialised. Triage had *run* it
  and recorded a pass, because *its* probe happened to have the registry loaded.

**Read this next part carefully before acting on the above.** Move 5 measured the skill section
that stated this rule and **deleted it** — it scored worse than its own absence, and the failure it
names (`FREEZE-AS-WRITTEN`: freeze a check you just watched pass) occurred **once in 125**
forced-choice reps. There is no contradiction: the phenomenon is real, and *restating it in that
file* made outcomes worse. The concept is already reachable from seven other places in the skill.

**So: this belongs in a human's head and in review, not in another rule.** Before re-adding
anything about discrimination, read
`dev-sessions/2026-07-27-1403-measurement/microtest/results.md`. **The trim that looks obviously
safe — reduce § 2 to "run the check and confirm it fails" — measured worst of all nine arms
(2/15) and is the only arm that ever froze a vacuous check.** A bare instruction to run the check,
stripped of its elaboration, appears to license *"I ran it, it's green, done."*

---

## Rules about oracles, earned from runs

Each of these came out of a specific failure and still governs.

**A check whose outcome depends on unstated test-environment setup is not freezable.** The same
command answers differently in different harness states. Running the check is not sufficient if the
run's preconditions are not part of the check. (#625's C1 — an instance of gameability test 3, not
a new rule.)

**State the assertion in the check; let the criterion *prose* carry the scenario.** #668's C2
specified the test's *mechanics* ("mutates `_rawText`") rather than only its assertion, and the
shipped fix tracked a flag that direct mutation never sets. What made the resulting dispute
adjudicable at all is that the criterion prose was independent of the check's mechanics — and C2
nearly destroyed that independence.

**Tamper rules must be invariants over what a check *asserts*, never whitelists of allowed line
forms.** A rule that fires on inert changes (comments, appends) produces false positives, and
**false positives train the operator to wave the mechanism through.** This is also why
`checks.md` can be inside its own baseline: no CRITERION/CHECK/guard line may differ, appends are
inert.

**Amendment vs. clarification.** An amendment changes what a check *asserts* → stop, human-confirm,
log, downgrade the run to `needs-review`. A clarification fixes wording that never matched its own
intent → logged, human-adjudicated, no downgrade. **Settled 2026-07-27: re-run both wordings
against BOTH trees — the freeze commit and the current implementation — and any verdict change at
either is an amendment.** The freeze tree alone is near-vacuous: at freeze the work does not exist,
so almost any non-vacuous check fails there, *including a replacement shaped to fit the
implementation*. **Applies to tamper rules too.**

**A decision recorded in an issue comment is invisible to every downstream mode.** They read the
body through the marker. **Comments are provenance; the body is the constraint.**

**Mechanism choice and tier are coupled.** #638 stayed `auto-ok` because per-test marks were chosen
over a `pyproject.toml` change, which would have touched build/CI config and pulled toward
`needs-review`. How you propose to do it changes how it must be reviewed.

**When a decision passes an object across a trust boundary, enumerate the object's methods before
recommending it.** "It's the existing pattern" was true and irrelevant in #625 — the precedent
passed a *single callable*, not a capability-rich object. Deliberately **not** added as a skill
rule: one instance, and it feels exactly like the two rules that were measured away. If it recurs,
that is the signal.

**A guard's pass count is not a coverage measure, and `-k` selections silently include
neighbours.** #586's G1 `12 passed` was 8 irrelevant tests from a different method; exactly one
covered the path at issue.

**"I ran the checks" is a claim about a tree, and the tree you ran them on is not necessarily the
one you pushed.** #649's review fix was uncommitted, so every check ran against a working tree that
did not match the remote.

**Construct fixtures from the code, never from plausibility.** A fabricated measurement — built by
hand as "realistic" and reported to Les as fact — reached decafclaw issue #710 before an `express`
run read the actual code and refuted it. The method it named did not exist; the length it assumed
was one the code cannot produce; **the issue's original table was right.** (Retraction is now in
#710's body.) Two levels of the same failure: move 2b's un-sealed fixture was detected by a
subagent as synthetic; here a subagent detected a synthetic *measurement*.

**A skill that requires its own config shape silently no-ops on every project that documented the
same facts differently** — worse than no integration, because it looks identical to working.
`github-projects.md` demanded a bespoke `## GitHub Project` heading while decafclaw declared its
board in prose under `## Project board`. Now: locate the declaration by *content*, read column
names from `gh project field-list` (real casing was `In progress`), and say `board: not configured`
when it genuinely isn't.

**A gate row is only as good as the permission floor of the thing that must satisfy it.** Move 4a
added "wait for CI to settle" to `pr.md`; the run tried a `sleep` poll, a backgrounded shell, and
the `Monitor` tool — **all three denied under `dontAsk`** — burned its whole $12 budget and stopped
at `pending` on a PR whose CI went green minutes later. Two artifacts built in one session were in
direct conflict, and only a real unattended run could surface it.

**Resolve only what you fixed.** A gate row of the form "no unresolved review threads" is
self-satisfiable if the agent may resolve threads it merely disagrees with. On #638, 3 of Copilot's
4 comments were factually wrong; skipping them was right, resolving them would have cleared the row
on the agent's own say-so.

---

## The verifier catches its author — four instances

Dispatching the verifier as `Explore` (**no Edit/Write**, so it structurally cannot touch the
oracle it grades) is not ceremony. Four times it has caught the person who wrote the thing:

1. **#638** — a scoped tamper rule said "every added line MUST be a `@pytest.mark.filterwarnings`
   decorator"; the author's own mechanical check used a looser regex allowing comments, silently
   applying the rule's *intent* rather than its letter. The verifier read it literally.
2. **#586** — established that post-squash the freeze commit is a dangling local object, resolvable
   locally but not an ancestor of HEAD and unreachable from origin, so nobody else can reproduce
   the tamper diff.
3. **#649** — reported a task unanswerable because there was no separate commit to diff. Correct:
   the review fix was uncommitted and the pushed PR did not contain it.
4. **#710** — refuted the fabricated measurement above. **First time what it caught was a claim
   already reported to Les as fact.**

Corollary: **confident architectural review is not a substitute for measurement.** A fresh-context
reviewer's most confident deletion in the consolidation pass was "`criteria-grammar.md` teaches
EARS to a model that already knows EARS." Plausible, and wrong — the model knows *of* EARS but
defaults nearly everything to `WHEN`, losing Ubiquitous and `WHILE` and missing `IF/THEN` for the
error path 3 times in 5.

---

## The evidence ledger

**Nine micro-test studies have run.** Four shipped wording was kept, three rules were cut, one was
trimmed, and one measured a fix. Every arm was read by hand.

| Study | Design | Result | Outcome |
|---|---|---|---|
| Intake's criteria gate | control vs treatment, 5/arm | control 0/5 checkable, treatment 5/5 | **keep** — load-bearing |
| Oracle-must-already-exist | after a 4:1 tier-split surfaced the gap | 5/5 after the fix | **keep** |
| `frozen-checks.md` read-only rule + amendment path | fixture: frozen check contradicts its own criterion, implementation already correct | control **4/5 edited the frozen check inline**; treatment 0/5 edited, 5/5 stopped with the prescribed statement, no over-trigger | **keep** — load-bearing |
| "Run each check by name / aggregate green is not the gate" | 20 reps, two fixtures — including one where the implementation *looks* done: an idiomatic dict dedup keeping the **last** occurrence where the criterion wants the **first**, with `make check` green | both arms 10/10 — the `checks.md` manifest naming the exact command is the mechanism; the exhortation adds nothing | **trim** to one sentence |
| Gameability (satisfiable-without-the-work) | control vs treatment, 5/arm | control 0/5 on the test-as-oracle case, treatment 5/5 | **keep** |
| Goal-ambiguity tier trigger | control vs treatment, 5/arm | control 5/5 without it | **cut** |
| `criteria-grammar.md` | four requirement shapes | control 1/5, 1/5, 2/5, 5/5; treatment 5/5 on all four | **keep** |
| Withheld-decision exception | 2 cells of a 2×2, deliberately | treatment 5/5 no over-trigger; control 5/5 correct without | **cut** |
| Discriminate rule (§ 2) | **170 reps, 9 arms, 4 fixture versions** | without: 15/15; shipped: 8/15 (p ≈ 0.006); replicated with `intake.md` in context, unmoved; arm M (the safe-looking trim) **2/15, worst of nine** | **cut** |

**A note on the count.** Earlier entries in the build log tally "three, then four rules measured."
That undercounts — it was counting rules *surviving in the shipped skill*, and omitted the intake
criteria-gate study and the aggregate-green trim, both of which measured shipped wording. Nine is
the honest number of studies.

**The standing evidence gap is still real.** The skill has accumulated rules faster than
measurements. Most of what the moves added is *mechanical correction* — a wrong command, an
unsatisfiable row, missing vocabulary — which is the right treatment for a broken command and
**carries no behavioural evidence at all** about wording that shapes behaviour. Distinguishing the
two is the standing judgment call: **mechanical fix → just fix it; behaviour-shaping wording →
measure or don't add it.**

**What is structurally unmeasurable here:** the *procedural* half — does a rule make an agent
actually **run** a check? The seal that stops a subagent wandering into this repo's docs to verify
the fixture is real is the same seal that stops it running anything. **Only a dogfood tests that.**

### The standing limit: this project's own oracle is too expensive

**The governing principle has turned on the project itself.** *An agent is only as autonomous as
its verifier is trustworthy* — and for skill-wording work, the trustworthy verifier is a
micro-test. The discriminate-rule study cost **170 reps, ~$50 and most of a session** to answer one
question about one section. That is a research programme, not a check.

Several of the skill's behaviour-shaping rules remain unmeasured — the tier triggers, the
escalation ladder, the criteria/guards split, the amendment-vs-clarification wording, the
don't-fudge-a-weak-check rule, `express`'s Phase 0 preconditions. *No rigorous inventory of which
rules are unmeasured exists*, which is itself part of the gap.

**Record this as a limit, not a backlog item.** At current cost they will not all get measured, and
writing them down as "to measure" would imply otherwise. Two consequences that hold today:

- **The bar for *adding* wording is higher than the bar for cutting it.** An unmeasured addition
  is a liability with a known base rate: 3 for 3 of the rules this project measured were cut.
- **This backlog skews `needs-review` and should.** Do not fudge criteria to make skill-wording
  issues look `auto-ok`. An honest `needs-review` beats a checkable-looking proxy — and this is
  exactly the repo that would be tempted.

The limit lifts only if measurement gets cheaper. Nothing has made it cheaper yet.

---

## Method — the instrument rules

These are the rules for measuring, and they were each learned by getting an instrument wrong.

- **Control vs treatment, 5+ reps per arm, and read every rep by hand.** A tally-only reading of
  move 5's study would have concluded the opposite of the truth.
- **Labels must be disjoint on evidence — naming an action is necessary and not sufficient.**
  `CLOSE-AS-STALE` names an action perfectly well and still attracted **14/15** reps whose own
  reasoning contradicted it. What fixed it was giving each label an explicit `Asserts:` clause, so
  a correct chain of reasoning cannot land on two labels. Even then it leaked once.
- **Derive variants from the shipped file** by anchored deletion that dies if an anchor moves.
  Better still, make the control *be* the candidate edit, so you measure what you ship. Move 5's
  shipped file is byte-identical to the arm that was measured.
- **Seal the fixture.** Subagents run inside this repo and *will* go check whether the fixture is
  real — one rep detected a placeholder repo URL and refused.
- **Pre-register the rubric and commit it before running**, once you have revised an instrument
  twice. Move 5 did; it is why the v4 null is reportable rather than suspicious.
- **Report nulls with their cause named.** Move 5's v4 primary metric was unmeasurable by its own
  construction (the seal forbids running commands, which suppresses "run the check").
- **A clean no-guidance control is unreachable on this machine** — the global CLAUDE.md leaks into
  every `claude -p`. Effects are **lower bounds**. Say so.
- **An interim measurement is not a measurement.** Denials checked mid-run read zero; the finished
  streams carried 16.
- **Reps cost ~$0.33 and an arm of 15 takes ~12 minutes.** Cheap enough that measuring beat
  reasoning every single time in move 5.

**Testing calibration for the skill itself (agreed, still holds):** this is a workflow/reference
skill derived from a proven one — scaffold structurally without pressure-scenario TDD; micro-test
only novel behavior-shaping wording against a no-guidance control; **don't add nuance clauses to a
winning recipe**; dogfood after building. Full pressure scenarios deferred until there is something
worth hardening.

---

## Verified gotchas

Facts established by *running* something, each of which a plausible reading gets wrong. **These are
the entries most likely to be silently re-broken.**

### Claude Code CLI

| Fact | How it was verified |
|---|---|
| **`--bare` is unusable here.** Auth is strictly `ANTHROPIC_API_KEY` / `apiKeyHelper` via `--settings`; OAuth and keychain are never read, and no key is set on this machine. It also skips CLAUDE.md discovery, which `express.md` declares as an input — so even a *keyed* GHA runner using `--bare` would lose the project context the skill needs. **The reproducibility win is not free on either host.** | live run, move 3 |
| **`--max-budget-usd <amount>`** (`-p` only) is a real CLI-enforced per-run ceiling. Reading `total_cost_usd` afterwards tells you what you spent; this stops you spending it. Use both. | `claude --help` 2.1.220 + live |
| **`--permission-mode dontAsk` denies unlisted *mutations*, not unlisted commands.** `touch` outside the allowlist was denied; `ls` was allowed with an allowlist of only `Bash(echo:*)`. The floor is real but narrower than "denies anything outside allow-rules." | filesystem as the oracle |
| **Deny rules beat allow rules and match multi-word prefixes.** `--disallowedTools 'Bash(gh pr merge:*)'` blocks the merge even with `Bash(gh:*)` allowed — **this is what makes "nothing merges" a mechanism rather than an exhortation.** Not airtight: prefix-matched, so `gh api` remains reachable, which is why a `PreToolUse` hook is a precondition for any *unwatched* host. | live |
| **`--allowedTools`, `--disallowedTools` and `--add-dir` are variadic**, so a trailing positional prompt is swallowed and the run dies with *"Input must be provided either through stdin or as a prompt argument."* **Pass the prompt on stdin.** Generalisable: *a flag list that works is not evidence the flag list is right, when one of the flags is variadic.* | live |
| **Absolute paths in permission rules take a `//` prefix.** `Edit(/abs/path/**)` does **NOT** block; `Edit(//abs/path/**)` does. | file contents on disk as the oracle, move 4a |
| **A nonzero exit does not mean the run failed.** A stream can carry `subtype=success` with a complete gate verdict *and* a trailing `error_during_execution`, exiting 1. Do not "simplify" the driver's `has_success_result` guard away. | move 5 (#656) |
| **Permission denials are triggered by shell *syntax*, not command names.** All 16 denials in move 3 involved an output redirect (`>`, `>>`, `2>&1`) or control flow (`for`, `while`, a leading variable assignment); none involved an un-allowlisted command. A compound with pipes and `&&`/`;` and no redirect passes. **The allowlist cannot be fixed by adding names.** | move 3, 16 denials |
| **The hosted run is not hermetic.** A `SessionStart` hook fires and injects this machine's global context. That is the price of not using `--bare`, and it bounds what a local run proves about a GHA run. | move 3 |
| **The denial detector greps the permission layer's phrasing only.** A `PreToolUse` hook block would go uncounted — if that hook lands, teach the detector about it. | move 3 |

### `gh`

| Fact | How it was verified |
|---|---|
| **`gh pr view <n> --json reviewThreads` is not a valid field** (gh 2.96.0). It errors and prints the field list, which reads like "no threads." Use a GraphQL query. | move 2 |
| **`gh pr checks --json state` returns `SUCCESS`, not `pass`.** The normalised `pass\|fail\|pending\|skipping\|cancel` lives in **`bucket`**. Filtering on `.state != "pass"` returned 2 non-passing checks on a fully green PR — it would have made every green PR ineligible. **Read `bucket`, never `state`.** | move 4a |
| **`--required` is a trap on a repo with no required checks:** prints `no required checks reported` and **exits 1**. Grade *all* checks. | move 4a |
| **`gh pr checks <n> --watch` is the only settle-poll that survives `dontAsk`** — one `gh` invocation covered by the existing allow-rule, one turn instead of one per poll. `sleep` loops, backgrounded shells and the `Monitor` tool are all denied. Validated on a real 11m34s wait. | move 4c |
| **`gh project item-list` silently truncates at 30.** Pass an explicit `--limit` everywhere *and print the count read*, so truncation is visible rather than inferred from an empty queue. | move 3, 185-item board |
| **`gh` writes post as the repo owner's account.** A PR shows "review by lmorchard" for the agent's own thread reply, so **any gate row of the form "a human reviewed this" is self-satisfiable** in this setup. | move 2b |
| **`gh project create` applies no template**, so a CLI-created board gets `Todo` / `In Progress` / `Done` — missing `Ready` and `In review`, two of the three states the skill transitions through, and wrong casing on the third. Template boards get `Backlog` / `Ready` / `In progress` / `In review` / `Done`. Measured across six boards: 3 template, 3 bare. | move 7 |
| **`gh project field-list` does not expose option colors or descriptions.** Those need GraphQL (`projectV2.field(name:)` → `ProjectV2SingleSelectField.options { name color description }`). | move 7 |
| **`updateProjectV2Field` replaces the single-select option set wholesale** — it accepts no option IDs, so any option not in the new list is deleted and **every item assigned to it loses its status.** Renaming columns is therefore a two-step operation: replace the option set, then reassign every item. Verify no item is left blank. | move 7, verified on board 9 |

### Project toolchains

| Fact | How it was verified |
|---|---|
| **pytest exits 5 on empty collection.** `no tests ran` is a *failed check*, not a pass — a mechanical detector, not an exhortation. It bit twice in one session (a nonexistent file, then a mangled shell loop) and `tail -1` hid it both times. | move 2b |
| **npm 11 prunes 27 nested optional `@esbuild/*` platform entries that npm 10 records**, so `npm install` rewrites `package-lock.json` deterministically. A *verification* target must not run a command whose job is to mutate — use **`npm ci`**, which cannot write the lockfile and additionally fails when `package.json` and the lockfile disagree. | decafclaw #716 → #717 |

**A live hazard this closed for decafclaw but not in general: when the project gates dirty the
tree, two things downstream read the mess as signal.** The tamper check's *"no collateral edits"*
substitute would score a gate-rewritten lockfile as a collateral edit, and `pr.md` step 4's
`git diff origin/main..HEAD` runs against a tree the gates themselves modified. The #585 run
survived it, so **the exposure is not understood** — worth establishing before an unwatched host
runs the gates and then judges the diff. The skill itself contains no `git add` (verified by grep),
so it does not carry the specific hazard that bit us: `make check` dirtied the lockfile, a blanket
`git add -A` swept it up, and it reached decafclaw's `main` before being reverted.

**It happened again, 2026-07-29, to the author of the paragraph above.** A blanket `git add -A`
while the driver's `express` worktree was present committed `.worktrees/<branch>` as an **embedded
git repository** on this repo's `main`, and pushed it. Reverted with `git rm --cached`; `.worktrees/`
is now ignored. Two things worth keeping:

- **The window is created by the tooling.** A driver run leaves a worktree in the repo root, so any
  `git add -A` during or after a run is exposed. `.gitignore` needed the entry *before* the first
  run, not after.
- **Knowing the hazard demonstrably does not prevent it.** This is the second occurrence, both by
  the same person, the second within an hour of re-reading the note. **`git add -A` in a repo the
  tooling writes to is the problem, not the operator's memory** — stage explicit paths.
| **A hard line-wrap inside a code fence misleads readers.** It is what misled Copilot into a wrong review comment on #638. Test commands in their line-wrapped form. | move 2 |

### Operational figures

- **The re-verification tax is structural, not bad luck.** Every upstream landing invalidates the
  freeze sha and forces rebase + re-anchor + full re-verify. `origin/main` moved three times during
  #649 and four consecutive runs paid it in move 3. The machinery held every time; the wall-clock
  cost is the planning input.
- **Real `express` runs cost $4.41–$11.87.** Move 5's two-issue loop came in at $11.76 and $11.20,
  total $22.96 — both would have exhausted the old $12 ceiling. `make run` now defaults to
  `--max-budget-usd 25` and `make loop` does two issues; the hand-assembled command is obsolete.
- **A ~1-in-8 triage conversion rate** should govern board-driver expectations. Of 8 issues scanned,
  3 came out `auto-ok` but only 1 was genuinely ready.
- **A driver that dies between invoking and classifying leaves no record.** Observed: a run
  completed (98 turns, 19 min, **$9.44**) and opened a PR, then the process was killed before
  classifying — real money spent, a PR open, and an empty `runs.jsonl`. Everything the driver
  writes, it writes *after* the work, so the failure mode is invisible by construction. Fixed with
  an `inflight.json` marker written *before* the invocation, plus `--classify-only <n>`.
- **No trap can fire on SIGKILL or a host crash.** A VSCode crash reparented `claude -p` to init
  (PPID 1) — still running, still spending, still mutating the repo, for another ~15 minutes.
  Startup now detects a live orphan and refuses to start a second run against the same repo. A
  finished orphan wants `--classify-only`; a live one wants killing. **Conflating those two states
  was the actual bug.**

---

## Two operating rules that are not about code

**Verify, don't assume — including your own memory of the docs.** This project's recurring theme.
Move 4c's session got four things wrong while confident about all of them: a fabricated measurement
reported as fact, a guard that could not fail, a gate row its own driver could not satisfy, and a
bad commit pushed to another repo's `main`. **Every one was caught by *running* something.**

**Fresh context is load-bearing, not hygiene.** Running `express` cold through the marker is what
surfaced three of move 2's six findings — none of which the context that wrote the criteria could
have hit. The context that builds a thing knows which of its rules are load-bearing *by memory
rather than by evidence*, which is exactly the bias the next stage must not inherit.
