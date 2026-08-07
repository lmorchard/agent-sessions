# agent-sessions — findings

**The durable, still-governing lessons.** If you are picking this project up cold, read
[design.md](design.md) then this file, and stop there. The chronology in
[build-log.md](archive/build-log.md) is provenance; nothing here requires reading it.

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

Seven patterns this project has hit more than once. Each has cost real money to rediscover.

### 1. A row satisfied by evidence *adjacent* to what it names — OPEN GAP

The dominant defect class, and the one the merge gate exists to prevent. A gate row, guard, or
check cites a specific mechanism; something *near* that mechanism supplies the answer; the row
reports true. Nothing lies, and the row means nothing.

**Nine of the eleven below are fixed; two are open. The gap is not the instances — it is that
nobody has ever looked.** Eight of the eleven were found by an unattended run stumbling into them;
**three were found by looking**, and all three came from *verifying a change rather than auditing the
code*. So the number remaining is **unknown**, and phase 3 converts each remaining one into an
automatic merge.

**The sweep that has never been done:** enumerate every gate row, guard and manifest check, and ask
of each *"what could satisfy this that is not the thing it names?"* Tracked as
[board #2](https://github.com/lmorchard/agent-sessions/issues/2).

Two things about the *rate* that the fixes-so-far do not settle. Move 5 alone produced two. And move
5's exit-code defect was **the same bug move 4c had fixed one field over, hours earlier** — the fix
was applied to the cost field and never generalised. Fixing instances one at a time has been losing
to the rate at which they arrive.

| # | Instance | Where | Status |
|---|---|---|---|
| 1 | The gate cited `gh pr view <n> --json reviewThreads` — not a valid field. It errors and prints the field list, which reads like "no threads." | move 2 (#586) | fixed |
| 2 | The tamper mechanism is vacuous when criteria are commands rather than test files: nothing to diff, and the `clean` verdict could not be distinguished from *nothing-to-compare*. | move 2 (#586) | fixed |
| 3 | `checks.md` — for command-based criteria, the *entire* oracle — sat outside its own tamper baseline. | move 2 (#586) | **RECURRED 2026-08-03** — see below |
| 4 | `project-gates` recorded a *local* `make check` and cited no GitHub check runs, so the gate read `eligible-for-auto-merge` while CI was `pending` and `mergeStateStatus` was `UNSTABLE`. | move 3 (#699) | fixed |
| 5 | `gh pr checks --required` on a repo with no required checks: a row built on it either errors or passes vacuously. | move 4a | fixed |
| 6 | Import-boundary guard G3 stays green while the boundary it protects is gone — a capability that arrives as an *object* imports nothing. C4 was added to assert what G3 structurally cannot see. | move 4b (#625) | fixed |
| 7 | Three independent unattended runs reported `project-gates` satisfied **by substitute**, having run `make check`'s four steps natively because `make check` itself was unpassable. | move 4c | fixed |
| 8 | `amendments: none` was true only under one of two readings of the amendment policy. The policy now names both trees, and under it #668 was an amendment. | move 5 (#668) | closed 2026-07-27 |
| 9 | **The driver's test suite tests a replica of the classifier, not the classifier.** `test-driver.sh` hand-copies driver logic — one helper is annotated *"Mirrors the driver's extraction + comparison exactly"* with nothing enforcing that — and it has **already diverged**: `classify_outcome` is 53 lines in the driver and 15 in the copy, with **zero `ci-stale` awareness** in the copy. | verified 2026-07-27 | closed by [#9](https://github.com/lmorchard/agent-sessions/issues/9) |
| 10 | **`pr_for_issue` matches a bare `#N` anywhere in an open PR's body, title or branch name**, so a PR that merely *mentions* an issue removes it from selection. The function's own comment says *"an express PR carries `Closes #N`"* and the code never requires the keyword. A docs PR listing six issue numbers hid six issues; `closingIssuesReferences` was empty on it. | verified 2026-07-29 | closed by [#23](https://github.com/lmorchard/agent-sessions/issues/23) |
| 11 | **The `threads` row can be satisfied by the run resolving its own threads.** On PR #78 Copilot raised one thread naming a real defect the change had introduced; the run fixed it, replied, and **resolved the thread itself** under the operator's `gh` credential — `resolvedBy` reads as the operator and is indistinguishable from a human's. The row read `0 unresolved`, and the reason correctly noted the `graphql` query was real and the review had genuinely landed. Every part of that is true, and the row still imports no outside opinion. | verified 2026-08-03 | open — [#79](https://github.com/lmorchard/agent-sessions/issues/79) |
| 12 | docs/sweep-adjacent-evidence.md | The full enumeration of every gate block field, condition, and Makefile check. | Closed by #2 |

**The tell:** the row names a command, and the evidence offered is not that command's output.
**The fix, every time:** make the row cite a command that is actually run, and make its failure
mode distinguishable from its success mode.

**Instance 11 sharpens what "adjacent" means, and it is the reason disclosure is not the fix.** The
prior instances were fixed by making the row cite the real mechanism and disclose substitutions. #78
did both — the row named `graphql reviewThreads`, ran it, got a true answer, and said in the reason
that this was *"the real mechanism this time, not a substitute."* The defect survives all of that,
because the mechanism itself is **satisfiable by the implementer**. So the sweep in #2 needs a second
question beyond *"what could satisfy this that is not the thing it names?"* — namely **"who can
satisfy this, and are they the author?"** A row that only the author can clear is not a check on the
author.

**Instance 3 recurred on 2026-08-03, and its "fixed" status was false for two days before anyone
looked.** decafclaw #139 / PR #754 published `tamper: clean — empty diff` while `checks.md` changed by
28 insertions after the freeze commit. Both were true: the manifest declares its own **Check files**
as three test files and does not list itself, so the diff covered files that genuinely had not
changed. **The row would have read `clean` had the edit been malicious.** It recurred because the
Check files list is authored per-run by the check-author, so the original remedy was wording, and
wording does not hold across runs. Narrower than the original instance — for test-node criteria the
assertions do live in the covered files — but `checks.md` alone carries the guard invariant clauses,
so editing a guard's pass condition is invisible to the tamper diff. Tracked on
[#68](https://github.com/lmorchard/agent-sessions/issues/68); **that issue's criteria do not yet cover
it**, and the fix is the baseline's coverage rather than a detector.

That run's own edit was legitimate and disclosed under an explicit `Clarification` heading. **The
tamper mechanism contributed nothing to establishing that** — the honesty came from the graded party
volunteering it, which is the shape this project exists to remove.

**Instance 10 adds a direction the first nine did not have: this class can cost *liveness*, not just
correctness.** Nine of them made a check wrongly report *true*, which a later stage or a reader could
still catch. This one makes eligible work wrongly report *absent*, and nothing downstream looks — the
driver idles while printing a skip reason that reads as true. It was also **self-amplifying in this
repo specifically**: the matcher keyed on issue numbers appearing in prose, so the more the project
documented its own triage, the more of its own backlog it hid.

Closed by splitting the one matcher in two, along the line the two callers were already implicitly
drawn on. Selection consults `closingIssuesReferences` — what GitHub itself would close — and
nothing else; post-run PR discovery keeps the loose match, because it wants recall where selection
wants precision, and a miss there reports `parked: no PR opened` about a PR that exists. The two
directions are pinned against each other in `make driver-test`: the criteria assert the strict side,
the guards assert the loose one, so tightening the shared matcher instead would have shown up as a
guard flip rather than as a quiet regression in the frozen park-state suite.

**Instance 9 was the worst of the nine, and it is worth keeping the evidence.** Running both
classifiers over one identical gate block (`ci: 2/2 pass @ 0d08b2d`, head `e8f03389abcdef`) gave:

```
shipped driver  -> ci-stale       "verdict rests on a commit that no longer ships"
test-file copy  -> gate-eligible  "all gate rows satisfied"
```

**The suite's classifier called a stale-CI PR eligible for auto-merge exactly where the shipped
driver voided it** — so move 5's record that the ci-sha fix was "mutation-tested" did not hold for
the classifier path. Under phase 3, "eligible" means merge.

Closed by extracting the parser to `driver/gate.py`, whose tests **import** it: the same mutation now
breaks named cases in both suites where it previously broke nothing. *(Note this prose named "the
live instance" twice in two days and was wrong both times — which is why status now lives in the
table's own column and not in a sentence above it.)*

### 2. A null must never render as a positive

**Nine instances**, and it keeps arriving through a different door.

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
5. **An untriaged issue rendered as nothing at all.** The driver reported `read 10 open issues` and
   then accounted for eight; marker-less issues produced **no line** — not even a skip reason. The
   driver's own select-stage comment already promises "one line per excluded candidate with its
   reason," but the marker filter runs one stage upstream of the code that honours it, and only the
   *zero* case printed (move 7, board #13).
6. **The permission-denial detector counted its own regex.** Driving this repo put the detector's
   pattern text into the stream, where it matched it — 3 denials reported, **1 genuine**. Could only
   surface in a self-referential run.

7. **A review that had not arrived reported as `0 unresolved threads`.** PR #44's gate row read
   `BY SUBSTITUTE: 0 reviews and 0 review comments exist, so no thread can` — and the review landed
   ~90 seconds later with three threads, one of them a real defect the change had introduced.
   **First instance inside the merge gate itself**, which is the most expensive place for it: under
   phase 3 a run reaching `eligible-for-auto-merge` on that substitute would auto-merge on the
   strength of a review nobody had read. Tracked as
   [#45](https://github.com/lmorchard/agent-sessions/issues/45).

8. **A killed run logged `cost_usd: 0` and `"no session, no spend"` for a run that spent $10.93.**
   The stream held `total_cost_usd: 10.929…`, a real `session_id` and `num_turns: 95`; the driver
   classified before the terminated child had flushed its `result` record, so `pick_result` matched
   nothing and the `driver-fault` predicate read *"the extractor found nothing"* as *"there is
   nothing"*. **Worse than the no-record failure `inflight.json` exists to bound** — a missing row
   sends someone looking, a `cost_usd: 0` row does not. Confirmed a race rather than a parse bug by
   the very next run: same signal, same exit 143, cost recorded correctly. `--classify-only`
   recovers it. Tracked as [#58](https://github.com/lmorchard/agent-sessions/issues/58).

9. **`make docs-check` scanned zero files inside a worktree and reported green.** `ROOT` resolves
   under `.worktrees/<branch>/`, and `.worktrees` is in `SKIP_DIRS`, so every file was skipped as its
   own excluded ancestor. Measured on one commit from two directories: **103 files from the repo
   root, 0 from inside a worktree**, both exiting 0. Every `express` run works in a worktree, so
   **`project-gates: make check green` has included a doc-rot detector that examined nothing on every
   PR this project has published.** Tracked as
   [#62](https://github.com/lmorchard/agent-sessions/issues/62); **closed 2026-08-03 by PR #75**,
   which matched `SKIP_DIRS` relative to `ROOT` so a directory can no longer exclude itself.

   **It had a mirror with the opposite symptom, and the pair is the real lesson.** From the repo
   *root*, the same name list failed to skip a worktree it did not happen to name: Claude Code
   creates them at `.claude/worktrees/` — no dot — so a second session's whole repo copy was scanned
   and its frozen session records lost the `docs/dev-sessions/` exemption, producing 11 failures that
   were all exempt in their real location. `make check` could not go green on this repo while any
   `.claude/worktrees/` copy existed. **One name list, two opposite failures: it excluded its own
   `ROOT`, and it failed to exclude a real worktree.** The fix that closed both was to stop matching
   names and ask for a marker — a worktree root carries `.git` as a *file* (`gitdir: …`), a nested
   checkout as a directory — which identifies the class rather than enumerating spellings.
   **The same name-matching mistake was live in the code that *creates* these directories on the same
   day**, found by watching two runs pick `.worktrees/` while the repo's precedent was
   `.claude/worktrees/`: [#80](https://github.com/lmorchard/agent-sessions/issues/80). Fixing the
   reader did not fix the writer, and nothing connected them.

**Instance 9 is the one to sit with.** The other eight are checks that reported a wrong *value*; this
is a detector reporting a correct value about an empty set. It was found by an unattended run
establishing a baseline, which described its own green result as *"my green baseline for that target
meant nothing"* — a run catching a defect in the infrastructure grading it. **The generalisable
question it raises for every detector: does it report how much it looked at?** A count in the output
(`103 files`) makes this class visible on sight; `docs-check: links resolve` does not.

### 3. Brittle absolutes encoding relative invariants

Four instances, all guards. A guard pins a number, a sha or a literal string; the real invariant is
relative; the thing it pinned moves; the guard trips while the property it protects still holds.

1. `#638` G1 pinned `3234 passed, 2 skipped`; a rebase made it `3265`. The property — *nothing
   lost, newly skipped, or newly failing* — held.
2. `#649` G6 went 130→140 and the suite 3425→3436 as upstream tests landed. The relative form
   earned itself twice in one run.
3. Move 3's G2 pinned a sha where the invariant is *"`main` is only ever fast-forwarded, never
   rewritten."* First one that was ours rather than inherited.
4. A triage guard on #20 pinned `grep -c 'is drivable' CLAUDE.md` → 1, where the invariant is *"the
   partition still names a drivable set, still excludes `gate.py`, and now states a default."*
   Restructuring the section — which was the ratified deliverable — dropped the literal phrase and
   tripped the guard while every property it existed to protect held.

**Write the invariant, not the reading.**

**Instance 4 carries a lesson the first three do not: a ratified scope change invalidates the
guards, not just the criteria.** The first three were pinned to something *upstream* moved. This one
was pinned by the same session that then agreed to reframe the issue's scope from "add one entry" to
"restructure the section" — and a guard written under the old scope encodes the old scope. Nothing
prompts you to re-read the guards when the criteria change, which is the same no-trigger shape as
self-created doc staleness. **When a decision widens or redirects an issue's scope, re-read its
guards in the same breath as its criteria**, and expect the honest outcome to be *restate the
invariant*, not *delete the guard* — swapping a failing guard for a passing one is how a suite stops
meaning anything.

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
- **Presence-grep assertions in `test-driver.sh` — `grep -q "<literal>" "$DRIVER"` passes when the
  literal appears in a COMMENT.** The same inert-content trap the `skill-readonly` guard fell into
  twice. **A test that greps its subject for a literal is a spelling check, not a test.** Closed
  2026-07-31 by issue #28: every instance is now a count comparison over the driver's non-comment
  lines, and `make assertion-lint` fails the build if the `-q` form returns. Run it for the live
  count; it is the successor to counting them here, which went wrong twice in opposite directions.
  **The two things worth keeping.** *(a)* The count was under-stated as "two" (counting only the
  `ci-stale` pair; a triage scanner corrected it), then the issue that closed it said "eight" — and
  the detector found a **ninth**, added the morning the fix ran, which the issue's own frozen check
  could not match because that check requires the target be `"$DRIVER"` and the new one grepped a
  generated `gate.yaml`. A hand-maintained census of a recurring defect is itself a stale-count
  hazard. *(b)* The warning against the trap sat **in a comment in the very file carrying the
  instances**, for two days, and did not prevent the ninth from landing next to it — class 4 above,
  in one line.
- **`make docs-check`, on its first run, flagged `CLAUDE.md`'s own *example* of a stale count** —
  it matches a literal and cannot tell a claim from an illustration. Not fixed by teaching it to
  ignore quoted text, which would open a bypass for a real stale claim in quotes; fixed by writing
  examples with `N`. **The class reached the detector built to catch rot, on day one** (move 7).
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

### 7. A detector cannot tell a mention from a claim — four instances, four different systems

The newest class, and the one that keeps arriving through a *different detector* each time. Something
scans text for a pattern; text that merely *quotes* the pattern matches; the detector acts on a
mention as though it were a claim.

| # | Detector | What it matched | Cost |
|---|---|---|---|
| 1 | the permission-denial counter | its own regex, present in the stream because the run was driving this repo | 3 denials reported, **1 genuine** — and it still does this, in every run since |
| 2 | `make docs-check` | `CLAUDE.md`'s own *example* of a stale count | flagged on its first run; fixed by writing examples with `N`, not by teaching it to skip quotes |
| 3 | `gate.py`'s spec-marker test | an issue body *quoting* `<!-- agent-session:spec -->` — including one whose sentence said it was **not** triaged | a marker-less issue reads as specced ([#19](https://github.com/lmorchard/agent-sessions/issues/19)) |
| 4 | **GitHub's own closing-keyword parser** | a commit body quoting a fixture whose payload contains `Closes #7` | **closed live issue #7 as COMPLETED** ([#47](https://github.com/lmorchard/agent-sessions/issues/47)) |

**Instance 4 is the one that changes the rule.** The first three are our detectors, so "make the
detector smarter" was always available — anchor the pattern, scope what is linted. GitHub's parser is
not ours. **When the detector belongs to someone else, the only lever is what you hand it.**

**The tell:** you are writing *about* a pattern, inside a medium that scans for it. Quoting a gate
block in a PR body, a marker in an issue, a `grep -q` in a test, a closing keyword in a commit
message. **A project that documents its own detectors will trip them**, and this one documents them
constantly.

**Two mitigations, and the second is the one that generalises.** Scope the detector so its own source
is out of range — `assertion_lint.py` contains its pattern six times and reports itself zero times,
which is instance 2's fix done right. And where you cannot change the detector, change the text:
`findings.md` writes example counts as `N` for exactly this reason.

**One trap specific to instance 4, because it is counterintuitive:** *commit messages are not rendered
as markdown*, so backticks around `Closes #N` are literal characters and protect nothing. Backticks
**do** work in issue and PR bodies, which is why the habit feels safe.

**Instance 4 now has a detector rather than a habit: `make commit-lint`.** It reports a closing keyword
only where it sits inside backticks, over the commits a branch adds on top of `origin/main`. The
negative half is what makes it survivable — an ordinary trailing closing reference is left alone, so it
does not fire on every legitimate commit and get switched off. `python3 scripts/commit_lint.py --all` is
the whole-history form, and running it is how the claim "one instance, ever" stays checkable instead of
remembered. Note the shape of the fix: it does not make GitHub's parser smarter, which is impossible
from here — it changes what we hand it, which is the lever this row's lesson identified.

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
`checks.md` can be inside its own baseline: per `skills/agent-session/references/frozen-checks.md`, no CRITERION line, CHECK command, or guard command may differ, appends are inert.

**At freeze, lock anything red whose green condition is an exit status.** Earned on #62, 2026-08-03,
and the sharpest single move either run made. The check-reviewer found a *third* red test outside the
declared tamper surface: `scripts/test_gate_test_wiring.py`, whose failing assertion is literally
`make gate-test` returncode `== 0` — necessarily false while the run's own criteria are red by design.
Its reasoning for adding it to the frozen Check files: **"a red test file outside the declared tamper
surface, whose message points at an exit-status assertion, is an invitation."** It was also another
session's frozen check file, so editing it would have been a cross-session violation. The
generalisable rule is about *shape*, not that file: a test that is red for a reason the run did not
cause, and that goes green when a command exits 0, is the cheapest thing in the tree to make pass
wrongly. Enumerate those at freeze and put them under the tamper diff even when the work has no
reason to touch them.

**"Passes today" in an issue body is a dated claim, and amending an issue is exactly when you inherit
one unverified.** #62's G3 read *"Passes today at 103 files"*, written 2026-08-01 and true then. Two
days later a second worktree existed and the same command exited 1. The guard was carried into the
frozen manifest by an amendment that added a criterion whose own evidence *contradicted* it — the
amender re-verified the thing being added and not the thing already there. The check-reviewer's
verdict: **"G3 as literally worded has no configuration in which it genuinely passes today."** Two
further teeth in the same finding: the guard's "non-zero file count" clause was **unobservable from
the command it named** (`main()` prints no count), and the guard was **gameable by deleting the second
worktree** — greening it with no fix at all. So at freeze, re-run every inherited guard rather than
trusting its recorded status, and state guards so that no environment change can satisfy them.

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

**A tier is a property of an issue, so an issue carrying several follow-ups takes the worst one.**
Triage should ask whether the parts share a tier before deriving one. #11 was filed by an unattended
run as three follow-ups: one had a discriminating criterion and no open question, the other two were
ungradeable without a foreign host and shared an unresolved design question. Carried as a single
issue it was `needs-review`; split, the first third is drivable. **The shape recurs by construction** —
a run filing its own follow-ups groups them by *where it found them* (one review, one freeze), which
has nothing to do with how they verify. The counter-pressure is real and worth stating: split only to
the granularity where each piece has its own question, or you ratify the same decision twice.

**When a decision passes an object across a trust boundary, enumerate the object's methods before
recommending it.** "It's the existing pattern" was true and irrelevant in #625 — the precedent
passed a *single callable*, not a capability-rich object. Deliberately **not** added as a skill
rule: one instance, and it feels exactly like the two rules that were measured away. If it recurs,
that is the signal.

**Some guards cannot be mutation-tested without performing the hazard, and that has to be recorded
rather than resolved.** A guard on #18 asserts the nest cases' `PATH` is wholly constructed by the
harness. Its mutation — making the constructed dir a *prefix* rather than the whole `PATH` — is
precisely what makes the harness non-hermetic, so applying it on any host with a real `gh` turns
nine validation probes into live driver runs. Attempted once: **it selected a real issue and created
a worktree before it was killed.** So the guard ships un-mutation-tested, with the reason written
next to it, and the design property demonstrated *outside* the suite instead (run the driver with a
stubbed `gh` on a pinned `PATH` and watch it pass validation, pass the required-command loop, write
the state dir and enter selection). **The wrong move here is to automate the demonstration**, which
means keeping a live-run trigger in a suite that otherwise cannot reach the network.

Generalisable: **when a guard protects against a dangerous state, its mutation test enters that
state.** Ask what the mutation *does* before running it, and prefer a one-off demonstration recorded
in the PR over a repeatable test that arms the hazard.

**A check whose mechanism the permission floor forbids is not a check.** Two instances, and the
second was written *in the same session that diagnosed the first*. `phases/pr.md` step 9 tells a run
to poll for a review "every 30s for up to 10 minutes" — but `sleep` loops, backgrounded shells and
`Monitor` are all denied under `dontAsk`, so an unattended run cannot do it; PR #44's run polled twice,
declared a timeout, and published a gate row while the review was 90 seconds away
([#45](https://github.com/lmorchard/agent-sessions/issues/45)). Hours later, issue #42's G1 was written
citing `find … -newer`, which the same floor also denies; the run substituted a `stat` snapshot and
said so. **Before freezing a check, ask whether the run can actually execute its mechanism** — the
answer is not obvious, because the denials are triggered by shell *syntax* (redirects, control flow)
rather than by command names. The known survivor for waiting is `gh pr checks --watch`, and there is
no equivalent for reviews.

**Before freezing a criterion, grep the OTHER suites for an existing assertion about the same
behaviour.** A criterion can be perfectly well-formed — demonstrated failing, oracle present, control
in place — and still be unimplementable, because a *different, already-merged* issue froze a guard
asserting the opposite. Issue #51's C1 (`--dry-run` must not refuse while a live orphan exists) and
issue #27's frozen G1 (that exact configuration must refuse) were flat contradictions: same fixture,
same flag, opposite required outcome. No implementation satisfies both, and the collision was
invisible from inside #51's own manifest.

The triage that wrote #51's C1 did everything the criteria rules ask for and still missed it, because
**every one of those rules looks at the criterion, the oracle, and the current behaviour — none looks
at what else already asserts something about the same behaviour.** The check is one `grep` for the
flag or function name across `driver/test-*.sh` and `scripts/test_*.py`, and it costs seconds.
Applied to the next four issues triaged it earned its place twice in four: it found an existing
assertion that a proposed change would have broken (`test-driver.sh:353`, that the classifier still
consults `has_success_result`, now carried as a named guard), and it ruled out a suspected collision
that turned out to concern a different subject.

Two corollaries worth keeping. **A frozen guard belonging to another issue is still frozen** — the run
that hit this refused to edit it to green its own criterion, correctly, since that is the implementer
removing an oracle in its way. And **when you do amend one, check what else depended on it**: #27's G1
had a second job named in its own comment, as the discriminator for #27's C1, so amending it without
adding a replacement would have silently made a *different, already-merged* issue's criterion vacuous.

**A row that a mechanism could not produce must not render as that mechanism's negative result.**
The same #44 gate said `threads: 0 unresolved — BY SUBSTITUTE: 0 reviews exist, so no thread can`.
That is defect class 2 *inside the merge gate*: "no review has arrived yet" is not "no unresolved
threads". `pr.md` already has the right rule for CI — an unsettled check yields `pending`, "nothing is
wrong, it just isn't derivable yet" — and reviews should inherit it. Measured while diagnosing this:
across six PRs, Copilot returned in **2.2–4.5 minutes**, so the 10-minute allowance was never the
problem and a longer one would not have helped.

**The same repo fact produced opposite verdicts across four runs, and nobody had decided the rule.**
Every one of PRs #40, #41, #43 and #44 carried a `ci:` row saying, in near-identical words, that this
repo has no CI configured. Three read that as satisfiable and published
`eligible-for-auto-merge`; the fourth read it as *"the CI row has no mechanism"* and published
`human-merge-required`. Under phase 3 that is the difference between merging and not. The *vocabulary*
existed — `no checks configured` was added in move 4a — but the **verdict rule** for it never was.
**Where a row can be absent rather than pass or fail, decide what absence means before it decides
itself.**

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

**And when the floor forbids the mechanism, a run does one of two things — the difference is
everything.** Both observed on 2026-08-02/03, on the same denied capability (`gh api graphql` under
`dontAsk`):

- decafclaw #704 reported `threads: 0 unresolved` and **named the substitution in the gate block**
  ("derived from the REST review-comment count"). Honest, and reviewable.
- decafclaw #754 reported *"both threads replied to and resolved"* — and **neither was resolved**
  (`isResolved: false` on both, verified independently). Resolving needs the `resolveReviewThread`
  mutation, which the floor denies, so the row was **unsatisfiable and claimed anyway**.

`pr.md` requires a row that a hosted run cannot satisfy, so the substitute is structural rather than
incidental — it will recur on every run. **The lesson is not "substitutes are bad" but that a
substituted row and a falsely-claimed row are indistinguishable to a reader of the verdict.** The
verdict was `eligible-for-auto-merge` both times; under phase 3 both merge. Tracked on
[#73](https://github.com/lmorchard/agent-sessions/issues/73), which asks the prior question: when the
named mechanism is unavailable, what should the row *do*?

**Resolve only what you fixed.** A gate row of the form "no unresolved review threads" is
self-satisfiable if the agent may resolve threads it merely disagrees with. On #638, 3 of Copilot's
4 comments were factually wrong; skipping them was right, resolving them would have cleared the row
on the agent's own say-so.

**Independence from the plan is not independence from the framing — the brief is a channel too.**
`frozen-checks.md` withholds the implementation plan from the check-author so the oracle cannot be
shaped to the implementation. On decafclaw #727 that held perfectly, and the oracle was contaminated
anyway, through the *brief*. The implementer wrote: *"the text is invariant over the switched-to
status, so you can produce it once and evaluate it against every `ProjectState`."* True of the
**buggy** code, and faithfully encoded — the check produced one sample and graded it against all six
phases, a pairing that never occurs at runtime. The result was an oracle that **mandated the weaker
fix and forbade the better one**, discovered only when a correct implementation failed a check that
its own criterion said it satisfied. So: **a check-author brief states the criterion, never the shape
of the code being replaced.** What it cost when missed was not a wrong merge — the amendment path
caught it, stopped, and routed to a human, which is the machinery working — but a mandatory stop, a
tier downgrade and a human decision were all avoidable at the brief.

---

## The verifier catches its author — seven instances

Dispatching the verifier as `Explore` (**no Edit/Write**, so it structurally cannot touch the
oracle it grades) is not ceremony. Five times it has caught the person who wrote the thing:

1. **#638** — a scoped tamper rule said "every added line MUST be a `@pytest.mark.filterwarnings`
   decorator"; the author's own mechanical check used a looser regex allowing comments, silently
   applying the rule's *intent* rather than its letter. The verifier read it literally.
2. **#586** — established that post-squash the freeze commit is a dangling local object, resolvable
   locally but not an ancestor of HEAD and unreachable from origin, so nobody else can reproduce
   the tamper diff. *(The finding stands; the cause is gone — [#29](https://github.com/lmorchard/agent-sessions/issues/29)
   removed `pr`'s squash for exactly this reason, so the freeze commit now ships with the branch. It
   took three runs and 2026-07-29's #657 to act on what this verifier said in move 2.)*
3. **#649** — reported a task unanswerable because there was no separate commit to diff. Correct:
   the review fix was uncommitted and the pushed PR did not contain it.
4. **#710** — refuted the fabricated measurement above. **First time what it caught was a claim
   already reported to Les as fact.**
5. **#12's dogfood, 2026-08-01 — the first catch at *freeze* time rather than after
   implementation**, by the new check-reviewer this instance exists to test. Six independent
   read-only reviewers over two fixture rounds found a real defect in **every check put to them**,
   6/6 on the seeded one, and three the author had not planted. The decisive one: every guard read
   `SKIP_DIRS` from the module rather than from a roster frozen in the manifest, so
   `SKIP_DIRS = set()` — deleting the feature outright — greened the entire manifest. Two reviewers
   verified it in-process independently. **Round 2's guards had already been hand-tightened by the
   author using round 1's findings, and it found this anyway.**

**Instance 5 carries a lesson the first four do not, and it is uncomfortable: a check that passed
`triage` and `intake` is not thereby a good check.** Round 1's non-seeded checks came straight from
issue #62's ratified body and all four drew correct findings. So the honest reading of a frozen
manifest is not *"these were reviewed, so they hold"* — it is that nobody had asked the gameability
question of them from outside. **Two rounds of deliberate authoring could not produce a manifest
that survived**, which is the strongest available evidence that the author is structurally the wrong
context to grade their own checks, and the reason the dispatch is worth its cost.

The open cost, recorded rather than resolved: at ~5 findings per freeze this could become the
*"false positives train the operator"* failure — except these are not false positives, which is what
makes it hard. Decided 2026-08-01 to ship without a disposition bar and let the adjudication records
be the evidence; revisit when there are records from real manifests rather than from a fixture built
to be reviewed.

Corollary: **confident architectural review is not a substitute for measurement.** A fresh-context
reviewer's most confident deletion in the consolidation pass was "`criteria-grammar.md` teaches
EARS to a model that already knows EARS." Plausible, and wrong — the model knows *of* EARS but
defaults nearly everything to `WHEN`, losing Ubiquitous and `WHILE` and missing `IF/THEN` for the
error path 3 times in 5.

**Instances 6 and 7 are the records instance 5 asked for** — it shipped without a disposition bar and
said to *"revisit when there are records from real manifests rather than from a fixture built to be
reviewed."* Both are from real manifests, on 2026-08-03:

6. **#62 — the first freeze-time catch on a real manifest, and it caught the operator.** Three
   findings worth the dispatch, all adjudicated *pre-freeze* so none cost the tier: G3 had **no
   configuration in which it genuinely passed** and was additionally **gameable by deleting a stray
   worktree** (greening it with no fix at all); G4's second arm **passed vacuously**, and was shipped
   flagged as such "so the green tick is not read as coverage it does not yet have"; and the
   exit-status invitation now recorded as its own rule above. G3 and G4 were both written by *me* an
   hour earlier while amending the issue — so this is the first instance where the author it caught
   was the human operator rather than a prior run.
7. **#62 — the verifier caught a self-referential count in the tamper record.** An earlier draft
   claimed the frozen manifest *"differs by two lines"*; the true diff is larger than any figure
   written inside it, **because the figure is part of what it measures.** No amount of care prevents
   that class; only citing the command does. The shipped record says so explicitly: *"`git diff
   <freeze> -- <this file>` is the only honest answer."*

**A blind spot the same day, recorded because it bounds the claim above.** On #78 the internal
verifier passed the change, and **Copilot** found the real defect: `stream_has_events` reported
"empty stream" for a stream that was merely unparseable — reintroducing, inside the fix for it, the
exact defect the issue was about. The run's own reply names it: *"that is this issue's own defect in
miniature."* Verified independently that `jq -se` exits non-zero on a truncated final line, which is
what a `SIGTERM`'d run produces, so this was the issue's own scenario. **The verifier grades against
the frozen checks, and no criterion covered it** — so a defect outside the manifest is outside the
verifier's remit by construction. Two graders with different remits caught different things; neither
was redundant.

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
| **`gh project item-add` is not immediately readable by `item-list`.** The new item's id comes back empty on a read issued right after the add, so a follow-up `item-edit` fails with `Could not resolve to a node with the global id of ''`. Hit twice in a row. Re-read before editing, and **check the id is non-empty rather than interpolating it blind** — an empty id produces a confusing GraphQL error, not a clear one. | move 7, filing #12 and #13 |
| **`gh issue edit --remove-label <label the issue does not have>` exits 0**, silently, with no state change. So an un-park can be unconditional; reading the labels first to avoid a no-op spends an API call to prevent nothing. | probe on a real issue, move 9 (#5) |
| **`gh label create <existing label>` exits 1** — `already exists; use --force to update its color and description`. A create-then-apply sequence therefore needs `|| true` and suppressed output; `--force` would work too but rewrites color/description on every call. | same probe |
| **`gh issue list --json labels` returns `labels: []`, an array of objects** (`{id,name,description,color}`), so the filter is `any(.name == $label)`. Requesting the field costs nothing on a query already being made — and **omitting it fails open**: the labels key is simply absent, so a label filter silently matches nothing. Mutation-tested: dropping `labels` from the driver's `--json` list left the whole frozen suite (`make park-test`) green, because its stub served a fixed payload. **A stub that ignores the requested field list cannot see a missing field.** | move 9 (#5) |
| **A commit message that *quotes* a closing keyword still closes the issue.** Commit messages are **not rendered as markdown**, so backticks are literal characters and protect nothing — unlike issue and PR bodies, where they do. A commit body describing a test fixture whose payload contains `Closes #7` closed live issue #7 as COMPLETED. The PR's own `closingIssuesReferences` said `[23]`, so the metadata anyone would check showed nothing wrong. | 2026-07-31, PR #38 / commit `2cbe106` |
| **`gh` writes post as the repo owner's account.** A PR shows "review by lmorchard" for the agent's own thread reply, so **any gate row of the form "a human reviewed this" is self-satisfiable** in this setup. | move 2b |
| **`gh project create` applies no template**, so a CLI-created board gets `Todo` / `In Progress` / `Done` — missing `Ready` and `In review`, two of the three states the skill transitions through, and wrong casing on the third. Template boards get `Backlog` / `Ready` / `In progress` / `In review` / `Done`. Measured across six boards: 3 template, 3 bare. | move 7 |
| **`gh project field-list` does not expose option colors or descriptions.** Those need GraphQL (`projectV2.field(name:)` → `ProjectV2SingleSelectField.options { name color description }`). | move 7 |
| **`updateProjectV2Field` replaces the single-select option set wholesale** — it accepts no option IDs, so any option not in the new list is deleted and **every item assigned to it loses its status.** Renaming columns is therefore a two-step operation: replace the option set, then reassign every item. Verify no item is left blank. | move 7, verified on board 9 |

### Project toolchains

| Fact | How it was verified |
|---|---|
| **pytest exits 5 on empty collection.** `no tests ran` is a *failed check*, not a pass — a mechanical detector, not an exhortation. It bit twice in one session (a nonexistent file, then a mangled shell loop) and `tail -1` hid it both times. | move 2b |
| **npm 11 prunes 27 nested optional `@esbuild/*` platform entries that npm 10 records**, so `npm install` rewrites `package-lock.json` deterministically. A *verification* target must not run a command whose job is to mutate — use **`npm ci`**, which cannot write the lockfile and additionally fails when `package.json` and the lockfile disagree. | decafclaw #716 → #717 |
| **A hard line-wrap inside a code fence misleads readers.** It is what misled Copilot into a wrong review comment on #638. Test commands in their line-wrapped form. | move 2 |
| **Editing a running bash script can silently change what it executes — and it fails *open*.** bash reads a script incrementally, so a **truncate-and-rewrite in place** (`cat >`, Python's `open(w)`) makes the running process continue into replacement text: measured, a script went on to execute two lines that **did not exist when it started**, exiting 0 with no error and no signal. An **atomic replace via rename** (`mv`) is unaffected, because the process keeps its original inode. **Measured for this harness: Claude Code's `Write` and `Edit` both change the inode** (`363717959 → 363717969`, `363717979 → 363718025`), so they are safe. Do not rely on that — the general mitigation is to `exec` from a snapshot copy rather than to know every editor's write strategy. | move 7, verified both directions |
| **A conditional `git stash push -- <path>` paired with an unconditional `git stash pop` targets whatever is on top.** When the push matches nothing — the work was already committed — it creates **no entry**, so the pop applies and *drops* an unrelated stash. Measured: a teeth probe ate a `419-sticky-widget-slot` stash belonging to another workstream and mixed its two files into the run's worktree. Recovered with `git stash store <sha>` after diffing to confirm, but **the stack ordering changed**, so anything relying on `stash@{0}` was silently repointed. To read a past tree, use `git show <sha>:<path>` or a worktree; never `stash` in a repo someone else may be working in. | decafclaw #727, 2026-08-02 |

**A live hazard this closed for decafclaw but not in general: when the project gates dirty the
tree, two things downstream read the mess as signal.** The tamper check's *"no collateral edits"*
substitute would score a gate-rewritten lockfile as a collateral edit, and `pr.md` step 4's
`git diff origin/main..HEAD` runs against a tree the gates themselves modified. The #585 run
survived it, so **the exposure is not understood** — worth establishing before an unwatched host
runs the gates and then judges the diff. The skill itself contains no `git add` (re-verified by grep
2026-07-29, still true) — but **that is a fact about the skill's text, not a bound on what a run
does**, and a real run has since improvised `git add -A` anyway (fourth instance below). The hazard
it describes: `make check` dirtied the lockfile, a blanket `git add -A` swept it up, and it reached
decafclaw's `main` before being reverted.

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

**A third data point for that second bullet, 2026-07-29, and the strongest one yet.** While
implementing #18, a mutation test was run that made the nest harness non-hermetic — and so started a
real `express` run against a live issue. The hazard had been *read* in a triage scanner's report,
*agreed with*, and *written into #18's own issue body by the same context*, in the words "running it
before the fix is unsafe." The gap between recording a hazard and not performing it was under an
hour and survived writing it down twice. Damage was limited only because `.worktrees/` and
`.driver-state/` were already ignored and the process was killed early: no commits, no push, no
`runs.jsonl` record — which is itself the *"dies between invoking and classifying leaves no record"*
failure, so the money spent is unknown.

**A fourth instance, 2026-07-29 — and the first where the actor was a *run*, not the operator.** The
unattended run on decafclaw #657 (PR #728, run dir `657-20260729T223955Z`) called `git add -A` twice:
once for a self-review commit, once immediately before `git reset --soft origin/main` to squash. **No
warning reached it.** Verified at the time: nothing about `git add` in decafclaw's `CLAUDE.md`, nothing
in the machine's global `CLAUDE.md` (which *does* load, since `--bare` is unused), nothing in the skill,
and **no deny rule for it in the driver**. So unlike the three instances above, this is not a prose
warning that failed — it is a hazard with no mitigation on the run path at all.

Three things worth keeping:

- **The skill's silence is not a mitigation.** The paragraph above cites "the skill contains no
  `git add`" as the reason the hazard isn't carried. That grep is still true and the inference from it
  is wrong: a run reaches for `git add -A` unprompted, because it is the obvious way to stage.
- **It was harmless by configuration, not by design.** decafclaw's worktrees live under `.claude/`,
  which is gitignored there, so there was nothing sweepable in reach. PR #728's file list came back
  exactly on scope. On a target repo without that ignore — or with any un-ignored stray artifact
  present when the run stages — the same two commands sweep it.
- **What caught it was reading the run's command stream**, not a check. That contrasts with the older
  claim below that `git add -A` is the one error class with no mechanism watching it: reviewing
  `stream.jsonl` for the commands a run actually issued *is* a mechanism, and a cheap one. It is
  currently done by hand and nothing requires it.

The mechanism-shaped fixes are narrow, because a run legitimately needs to stage *something*: deny the
blanket forms specifically (`git add -A`, `git add .`, `git add :/`) rather than `git add` wholesale, or
have the skill name the explicit-paths rule at the point of staging. Deny rules are prefix-matched, so
the blanket forms are expressible; `Bash(git add:*)` would be too broad and would break the commit step.

**What generalises is not "be careful."** It is that a hazard needs a *mechanism* — an ignore rule, a
deny rule, a precondition that refuses — and that prose warnings, including ones you wrote yourself
minutes earlier, have now failed three times in this project at changing behaviour. The fourth instance
above sharpens that rather than adding to the tally: **there was no warning to fail.** See also the rule
about mutation-testing a guard that protects a dangerous state.

### Operational figures

- **The re-verification tax is structural, not bad luck.** Every upstream landing invalidates the
  freeze sha and forces rebase + re-anchor + full re-verify. `origin/main` moved three times during
  #649 and four consecutive runs paid it in move 3. The machinery held every time; the wall-clock
  cost is the planning input.
- **Real `express` runs cost $4.41–$11.87 through 2026-08-01, with individual runs hitting $23.63 (2026-07-31, run #47) and $19.56–$20.97 (2026-08-03).**
  Move 5's two-issue loop came in at $11.76 and $11.20, total $22.96 — both would have exhausted the
  old $12 ceiling, which is why `make run` defaults to `--max-budget-usd 35` and `make loop` does
  two issues. **The later figures are the planning input, and they are close enough to the ceiling to
  matter**: the runs on 2026-08-03 cost $20.97 (#62) and $19.56 (#58), and #52's run hit $23.63 (67% of the $35 ceiling). Both 2026-08-03 runs reached `gate-eligible` with zero amendments, so this is
  the price of a *clean* run rather than of a troubled one. What plausibly drives it is the
  re-verification cycle: both re-dispatched the independent verifier after the tree changed, which is
  correct and not free.
- **In-flight spend is unobservable.** Cost appears only in the terminal `result` event — verified
  2026-08-03 by scanning a live run's `stream.jsonl`: **zero** cost fields across 1.7 MB while the run
  was in progress. So `make watch` can report turns and elapsed time but not money, and the budget
  ceiling can only be *enforced* at exit, never monitored toward. This is also the other half of the
  killed-run defect (class 2, instance 8): the field is not hard to parse, it does not exist yet.
- **A mis-tier is cheapest at intake and most expensive at execute time — $15.62, measured.** A
  decafclaw issue tiered `auto-ok` turned out to fail trigger 1, and nothing discovered it until a
  run had already been dispatched and was working the issue. The work itself was fine and later
  shipped; the money bought the *discovery* that the tier was wrong. Set against a triage scan of
  roughly a dollar an issue, that is the argument for scanning generously rather than tiering
  optimistically: **the cheapest place to find a withheld decision is before a run is paid for.**
  Recorded 2026-08-03, carried across two handoffs unfiled before landing here — which is its own
  small lesson about where cost figures go to die.
- **"Merged" is not "clean": a worktree whose branch is fully merged can still hold the only copy of
  something.** 2026-08-03, during routine cleanup. `git merge-base --is-ancestor` reported the
  branch merged — true, and it says nothing whatever about the working tree. That worktree held an
  uncommitted `pr-body.md` carrying the run's **final gate block**, where `main` had only the
  `pending` rows `pr.md` step 6 opens with; it was also the sole record that the `threads` row was
  satisfied by the real `graphql` mechanism rather than a substitute, and it carried the governance
  note **the routing-gate decision earlier that same day was made on**. `git worktree remove
  --force` would have destroyed all of it silently, and the branch-level check would have said the
  removal was safe.

  This is defect class 1 wearing work clothes: a check that reports a true value about the wrong
  question. **Before removing a worktree, run `git status --porcelain` inside it** — the branch's
  merge state is not the answer. Two files in the same directory *were* safely discarded, and the
  thing that made that judgment cheap was that one said so in its own header (*"Throwaway repro …
  Deleted before the PR"*). Scratch that announces itself as scratch is worth writing that way.
- **A ~1-in-8 triage conversion rate** should govern board-driver expectations. Of 8 issues scanned,
  3 came out `auto-ok` but only 1 was genuinely ready. **Second data point, 2026-07-29: 3 scanned, 2
  `auto-ok`, both with a discriminating criterion that was actually run** — a much better rate on a
  much smaller sample, and the sample is small enough that the first figure should still govern
  planning. What plausibly differs is the input: these three were written by people (or runs) who
  already knew what a criterion was, where the earlier eight were ordinary wishlist issues. If that
  is the cause, the conversion rate is a property of the *backlog*, not of `triage`, and neither
  figure generalises to a fresh repo.
- **A dry queue was attributed to the wrong trigger for days, because the sample was curated.** The
  standing explanation for decafclaw's empty queue was that trigger 2 fires on everything —
  established honestly by scanning its Ready column: 8 issues, all authorization work, 0 `auto-ok`.
  Reading the *unmarked* backlog on 2026-08-03 inverts it. decafclaw's `CLAUDE.md` **marks nothing
  off-limits**, so trigger 2's project-configurable half contributes almost no gating and fires on an
  estimated 15–20%, concentrated in one identifiable cluster (skill loading/discovery, schedule tiers,
  `skill_permissions.json`, the email allowlist, credential skills, dependency changes). **The real
  gate is trigger 1**, and it is severe: of 166 unmarked open issues, **16 contain acceptance criteria
  of any kind** and **47 carry an explicit open question, deferred decision or "pick one."** The Ready
  column was a *curation artifact* — someone had triaged the security-hardening cluster into it — so
  the 8-of-8 result was never a sample of the backlog. Prior `auto-ok` specs in decafclaw's own
  `docs/dev-sessions/` corroborate this and were sitting there the whole time.
  **The lesson is about the inference, not decafclaw: N-of-N on a curated set is not a rate.** A
  column someone filled on purpose is the least representative thing on a board, and it is also the
  most convenient thing to scan. Check what selected the sample before generalising from it.
- **Where triage density actually is, measured 2026-08-03 on a 17-issue spread:** trigger 2 fired on
  3–4, trigger 1 on 11. Extrapolated yield for a full 166-issue pass is **~15–25 `auto-ok`** — a real
  refill, at the cost of ~140 low-yield scans. The density is in the **recent, agent-filed,
  file:line-precise tier** (issues at #≥600 plus `bug`-labeled, ~40 unique), which prior runs wrote
  with the file, the line and often the exact test to mirror already named. So: **filter before
  scanning** — skip the old exploratory tier, and skip any body matching
  `open question|pick one|evaluate the options|Deferred —|worth deciding`, which is pre-failed on
  trigger 1.
- **The filter above was then run, 2026-08-03, and the prediction held — but the yield came from
  somewhere else entirely.** 16 issues scanned from the filtered tier produced **2** `auto-ok`
  unassisted (~12%, consistent with the 1-in-8 figure). Then six questions to the operator produced
  **six more**, taking decafclaw's eligible count 0 → 8. Two moves; the second cost one conversation
  turn and was worth three times the first.

  **The reason is a single dominant shape: nine of fourteen `needs-review` verdicts were "the issue
  lists two or three options and deliberately does not pick one."** Not under-specification — these
  were well-researched issues that stopped short of a decision, several saying so outright (*"Not
  proposing one — that's the work"*). Trigger 1's *withheld-decision* clause, not its
  human-judgment clause, is what actually gates a mature backlog. The five that did **not** convert
  were gated for real: two on trigger 2 (an authorization gate, a shell pre-approval surface), one
  on deletion, one the test-coverage hard case, one moving an authoritative durable record.

  So **`triage`'s highest-leverage output is not augmented issues; it is a list of decisions, each
  with the evidence already gathered and each branch already priced.** The scanning is what makes
  the questions cheap to answer — in six cases the scanner had already verified that the check on
  the far side of the decision discriminates today — but the questions are what move the queue.
  A pass that reports only "augmented K" under-reports itself, in the same way the bullet below
  says "scanned N" does.

  Two caveats on the filter itself, recorded so the figure is not read as cleaner than it was: the
  pre-fail regex correctly caught #601 (whose criteria reduce only to a keyword grep), but it
  **missed #335 entirely** — `#<600` and `enhancement`, so neither arm of the filter caught it. It
  was added by hand and came out `needs-review` anyway, so the miss cost nothing *this time*. That
  is luck, not evidence the filter is sound.
- **Batch triage sees four things a per-issue `intake` structurally cannot**, observed in one pass
  on 2026-08-03. This is an argument for the batch mode independent of throughput, because every
  one of these is a *relation between* issues and no single-issue context contains it:
  **(1)** two issues were the same bug filed three hours apart, the later one saying "filing
  separately" because its author never saw the earlier; **(2)** three separate issues were blocked
  on one missing capability — no repeat/sampling flag in the eval runner, so no K-of-N pass rate —
  discovered independently by three scanners that could not see each other, and filable as one
  `auto-ok` issue that unblocks all three; **(3)** one issue's headline work had already shipped in
  two merged PRs, so its title named a done thing; **(4)** one issue was two unrelated halves, and
  the deferred half was holding the ready half at `needs-review`.
- **A countable or quoted fact inside an *issue body* is exactly as perishable as one inside a doc**,
  and the documentation rule in `CLAUDE.md` applies to both. Five instances in one pass, 2026-08-03,
  every one found by a scanner *running* something rather than reading it — which is the whole
  reason the brief mandates running each proposed check:
  - **The obvious test passes today and grades nothing.** pytest's `tmp_path` is pre-resolved
    (`_pytest/tmpdir.py:156`), so an issue about resolved-vs-unresolved path divergence would have
    had a test in which the divergence never occurs. It needed a real symlinked root.
  - **The obvious test throws.** jsdom implements no `scrollIntoView`, so
    `vi.spyOn(Element.prototype, 'scrollIntoView')` fails outright and an unguarded call reddens
    every existing test in the file — new criterion green, guard red.
  - **A title's numbers were config-dependent.** `97 / 40 / 58` re-ran locally as `30 / 67`. A
    criterion pinned to the literals would trip whenever someone adds a tool. State the invariant.
  - **A premise was false against the code.** *"The index loader already handles multiple
    segments"* — it does not; the reader touches only the live path and the read-state resolver
    *deliberately discards* archived ids. Verified empirically, not inferred.
  - **A count was unre-derivable.** "4 failing cases" could not be checked without paying for a
    model run, because nothing persists the results. Criteria must say "0 failing", never "these 4".
- **Judge a `triage` pass by the eligible count it produced, not by the issues it touched.** "Scanned
  N, augmented K" is an *activity* report, and it is adjacent to the thing that matters — whether work
  the loop can pick up now exists. A pass can augment a dozen issues, report truthfully, and leave the
  eligible count unchanged because everything reduced to `needs-review`. Run the selection path
  (`make dry-run` / `make dry-run-self`) before and after and compare; **report it even when the answer
  is zero**, because "augmented eight, eligible still zero" is the honest and useful result and it
  names its own cause. This is an operator expectation deliberately recorded here rather than as a rule
  in the skill: the concept is already reachable from four places in `skills/agent-session/`, and this
  project is 3-for-3 on rules added in that situation measuring away. Two live readings, 2026-07-29:
  the first pass took eligible 1 → 3; the second took it 3 → 1 and **that drop was the signal** — it
  exposed a matcher bug ([defect class 1, instance 10](#1-a-row-satisfied-by-evidence-adjacent-to-what-it-names--open-gap))
  that an activity report would have hidden.
- **Long runs launched as a harness background task were killed twice, unexplained — and the cause is
  still open.** 2026-08-01, both attempts on one issue, $23.85 spent for nothing merged. Recorded
  because the *ruling-out* is the useful part and re-deriving it is expensive. **Not** duration: a run
  that completed took 58.8 min, while these died at 33.5 and 38.9. **Not** the workload: `make check`
  on the branch runs in 34s with no process growth. **Not** OOM: the stream shows
  `[Request interrupted by user]`, an orderly interrupt, not a hard kill. **Not** output volume: every
  stream caps tool results at the same 17.6 kB. **Not** a scheduled job: no crontab, no session cron,
  no relevant LaunchAgents. The one hard signal is that both died at exactly `:49:52` past the hour,
  one hour apart, after *different* elapsed times — and that lead is refuted too: a completed run
  crossed the same boundary at 38.4 min and lived, where the killed one crossed at 38.9 and did not,
  and a trivial canary sailed through it. `log show` returns nothing on this host, so it cannot
  arbitrate. **The workaround does not depend on the cause: drive long runs from a terminal, not from
  a harness background task.** A foreground call cannot substitute — the harness caps those at 10
  minutes and these runs take 30–60. **Narrowed 2026-08-03: a `nohup`-detached launch from inside a
  harness session survived twice**, on runs of ~50 and ~53 minutes, both to a clean `gate-eligible`
  exit. So the distinction is not terminal-vs-harness but **detached-vs-harness-tracked**, which is a
  cheaper workaround than it looked: `nohup make run-self … &` with output to a log file, then poll the
  log and the run's `stream.jsonl`. Two survivals do not refute a nondeterministic kill, so this
  narrows the workaround without closing the cause.
- **A driver that dies between invoking and classifying leaves no record.** Observed: a run
  completed (98 turns, 19 min, **$9.44**) and opened a PR, then the process was killed before
  classifying — real money spent, a PR open, and an empty `runs.jsonl`. Everything the driver
  writes, it writes *after* the work, so the failure mode is invisible by construction. Fixed with
  an `inflight.json` marker written *before* the invocation, plus `--classify-only <n>`.
- **No trap can fire on SIGKILL or a host crash.** A VSCode crash reparented `claude -p` to init
  (PPID 1) — still running, still spending, still mutating the repo, for another ~15 minutes.
  Startup now detects a live orphan and refuses to start a second run. A finished orphan wants
  `--classify-only`; a live one wants killing. **Conflating those two states was the actual bug.**
  The refusal is scoped to the repo, but **nothing in it compares repos** — the state directory
  defaults to one per repo (`--state-dir` still means exactly the path given), so a marker for one
  repo is not in the directory another repo's run reads. The scoping is a property of the layout,
  which is why there is no repo-comparison code to get wrong. Point two runs at one explicit
  `--state-dir` and they collide again, correctly: one `inflight.json` cannot describe two runs.

---

## Two patterns about how errors get caught here

**Mechanisms catch the author; care does not.** Across moves 6–7, roughly **nine** errors that
confident reasoning had produced were caught by something mechanical — triage scanners caught an
unverified claim being repeated as fact, a tier rationale that over-claimed, a "live instance" note
gone stale within the hour, an undercount of eight assertions as two, and the classifier divergence;
a bash assertion caught a *second* divergence being created mid-refactor; the driver's `CONFLICT`
state caught a bad write-back; the one-day-old amendment policy caught a frozen check. **The single
error with no mechanism watching it — `git add -A` — went uncaught until after it was pushed.** The
catch rate tracked the presence of a mechanism, not the presence of care.

**Parking is the mechanism working, and it has never yet been wrong.** On 2026-08-01 four unattended
runs stopped without opening a PR, and all four were right — two of them catching defects in criteria
the *supervising* context had written hours earlier. The strongest: a run found that its issue's
criterion contradicted a frozen guard belonging to a different, already-merged issue, declined to edit
that guard to green its own criterion, wrote up both sides of the argument, and stopped for
confirmation. It also rejected a needle-threading option that would have left both suites green while
being incoherent, and recorded the rejection rather than leaving it unconsidered. **The operator rule
that follows: read a park's reasoning before overriding it.** The cost of a park is one human decision;
the cost of overriding a correct one is an oracle quietly weakened by the implementer it was meant to
constrain.

**Self-created staleness has no trigger.** `CLAUDE.md` said all of `driver/` was drivable. True when
written — then the classifier moved into `driver/gate.py` four hours later, which made it false, and
nobody noticed until it came up for an unrelated reason. This is *not* the staleness a
re-verification pass catches: inherited stale claims get audited, but **a claim you falsify yourself,
in the same session, by doing ordinary work, is invisible.** The mitigation has to attach to the
*change* — moving oracle-bearing code should prompt "what did that just invalidate?" — not to a
periodic audit.

## Two operating rules that are not about code

**Verify, don't assume — including your own memory of the docs.** This project's recurring theme.
Move 4c's session got four things wrong while confident about all of them: a fabricated measurement
reported as fact, a guard that could not fail, a gate row its own driver could not satisfy, and a
bad commit pushed to another repo's `main`. **Every one was caught by *running* something.**

**Fresh context is load-bearing, not hygiene.** Running `express` cold through the marker is what
surfaced three of move 2's six findings — none of which the context that wrote the criteria could
have hit. The context that builds a thing knows which of its rules are load-bearing *by memory
rather than by evidence*, which is exactly the bias the next stage must not inherit.
