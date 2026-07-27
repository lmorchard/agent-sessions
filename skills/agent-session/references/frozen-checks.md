# Frozen checks — the verification contract

Read by `plan`, `execute`, and `pr`. This is the back half's core, the counterpart to
`acceptance-criteria.md`: that file makes criteria *checkable*, this one makes the checks
*trustworthy* while an agent implements against them.

## The failure mode this prevents

An implementer that can edit its own oracle has no oracle. The failure is not dramatic — it
looks like a reasonable judgment call: the check asserts something slightly awkward, the
implementation "obviously" does the right thing, so the assertion gets relaxed, the suite goes
green, and the run reports success. Every downstream signal now says done. Nothing says wrong.

So the contract has three parts, and each is mechanical rather than exhortative:

1. **Freeze** the checks before implementation, in a commit.
2. Keep the checks **read-only** to the implementer.
3. Have a **different context** run them and diff them.

## The manifest — `checks.md`

`plan` writes this in the session directory at Phase 0, before any implementation. Criteria
and checks are copied **verbatim** from the issue spec — paraphrasing a check is already a
weakening, because the paraphrase is authored by the implementer.

````markdown
# Frozen acceptance checks

**Source:** https://github.com/owner/repo/issues/129
**Frozen at:** a1b2c3d (2026-07-24)
**Check files — read-only from Phase 1 onward:**
- `tests/test_export.py`
- `tests/test_dedup.py`
(If every criterion is a command rather than a test, this list is empty — say so explicitly and
follow "When the criteria are commands, not test files" below. Don't leave it blank.)

## C1
CRITERION: WHEN a user exports a dataset over 10k rows THE SYSTEM SHALL stream the file
without loading all rows into memory at once.
CHECK: `pytest tests/test_export.py::test_large_export_is_streamed` passes.
AT FREEZE: fails — `AssertionError: peak RSS 812MB exceeds 200MB threshold` (correct reason:
the behavior is genuinely absent, not a setup error).

## C2
CRITERION: the deduplication pass SHALL NOT drop or merge two records with distinct ids.
CHECK (property): `pytest tests/test_dedup.py::test_dedup_preserves_distinct_ids` passes.
AT FREEZE: fails — `Falsifying example: [Record(id=1), Record(id=1)]` (correct reason).

## C3
CRITERION: the export button's spinner should feel responsive.
CHECK: none — human judgment. Forces tier `needs-review`.
EVIDENCE TO PRESENT: screen recording of a 50k-row export, for the human to grade.

## Guards
(Pass today; must keep passing. Not criteria — they can't fail at freeze. See
`acceptance-criteria.md` "Criteria vs. regression guards".)

- G1: `pytest tests/test_export.py -q` — the existing export suite. Passed at freeze.
- G2: `test_real_pty_echo_and_cleanup` still RUNS and passes — not skipped, not deleted.
  Passed at freeze.

## Amendments
(Append-only. Empty unless an amendment was made — see "When a check is genuinely wrong".)
````

Assign ids `C1…Cn` in the order the criteria appear in the spec. Ids are stable for the run:
the plan, the commits, the verifier's report, and the PR body all reference the same `Cn`.

Human-judgment criteria go in the manifest too. They have no frozen test, so they carry the
**evidence to present** instead — that is what the human grades at the gate, and naming it up
front stops "human decides" from meaning "nobody decided."

## The freeze

Phase 0 of every plan, no implementation in it:

1. Write `checks.md`.
2. Author the tests the checks name. Dispatch a **check-author subagent** given the spec and
   the criteria but **not** the implementation plan — a verifier that has read the intended
   implementation tends to test the implementation rather than the criterion.
3. Run each check and confirm it **fails for the expected reason**. A check that fails on an
   import error, a typo'd path, or a missing fixture is not yet a check; it would pass later
   for reasons unrelated to the criterion. Record the observed failure per criterion in
   `AT FREEZE`.
4. Commit. Then record that commit's sha as `Frozen at` **in a follow-up commit** — a commit
   cannot contain its own hash, so this is two commits, not one. The freeze commit (the first)
   is the tamper-diff baseline; the second just writes the sha down.

   Re-anchor the sha if the branch is ever rebased, and run the tamper check before any squash
   that would collapse the freeze commit away — see `phases/pr.md`.

A **criterion's** check that *passes* at freeze means the behavior already exists — surface it,
don't proceed. Either the criterion is already satisfied (the issue may be stale), the check
doesn't actually test the criterion, or it was a guard filed as a criterion.

**Guards are the opposite:** run them at freeze and confirm they **pass**. A guard that already
fails isn't guarding anything — it's a pre-existing break, and you need to know that *now*
rather than discover it at the gate and mistake it for your own regression.

## The read-only rule

**From Phase 1 onward, the files listed in `Check files` are read-only.** When a frozen check
fails, the default assumption is that the implementation is wrong.

Do not edit, relax, skip, xfail, delete, or narrow the scope of a frozen check to make it
pass. Do not add a passing variant alongside it. If a check appears wrong, that is a **STOP**
— surface it per "When a check is genuinely wrong" below. Never resolve it inline.

This applies to implementer subagents too. When dispatching one, state the check files it may
not modify, and that a failing frozen check is a report-back, not a fix-up.

Unit tests written *for* a slice are a different thing and are freely editable — they are the
implementer's own scaffolding. Only what `Check files` lists is frozen.

`checks.md` is frozen too, in one direction: **append only.** The sanctioned writes are the
`Frozen at` sha, a logged amendment, and the pre-squash tamper verdict. Changing a CRITERION line
or a CHECK command in it is editing the oracle, whatever the diff's size.

## Independent verification

At the end of `execute` (and again in `pr`), dispatch a **verifier subagent** with a fresh
context. Give it only `checks.md` and the repo. Do **not** give it the plan, the
implementation notes, or any explanation of why a failure might be acceptable — that context
is exactly what produces a rationalized pass.

It reports, per criterion: the command it ran, the observed output, and `pass` / `fail`. Plus
the tamper diff below. It renders no opinion on whether a failure is acceptable.

## The tamper check

```bash
git diff <freeze-sha> -- <each path in Check files>
```

Must be empty. A non-empty diff means a frozen check changed after the freeze — the run's
green checks are not evidence until that diff is explained by a logged amendment.

**An empty `Check files` list makes this command meaningless rather than satisfied.** If that's
the case, run the substitutes in "When the criteria are commands, not test files" below.

Run this at the end of `execute`, and again in `pr` **before the squash** — a soft-reset squash
collapses the freeze commit and the baseline stops being reachable from the branch, so the verdict
recorded at that point is what the gate cites. It's two seconds and it's the difference between a
claim and a check.

### When the criteria are commands, not test files

Some criteria are satisfied by a command rather than a test — a `grep` count, a CLI invocation, a
one-line interpreter call. Then `Check files` is empty and everything above quietly goes slack:
no file to hold read-only, nothing for `git diff <freeze-sha>` to compare, no test for the
check-author subagent to write. **An empty diff there is an absent result, not a clean one.** Say
so in those words, or a reader downstream takes the null for a pass.

Three things substitute, and each must be run and recorded:

1. **Manifest integrity.** For a command-based criterion the manifest *is* the whole oracle, so
   diff the manifest: `git diff <freeze-sha> -- <session-dir>/checks.md`. That diff is never
   empty — the freeze procedure itself writes the sha in a follow-up commit — so state it as an
   invariant, never as an equality: **no CRITERION line, CHECK command, or guard command may
   differ from the freeze version.** Sanctioned appends (the `Frozen at` sha, a logged amendment,
   the pre-squash tamper verdict) are inert. A changed command is not — quote both sides.
2. **Equality against the independent source.** The commands were copied verbatim from the issue,
   and the issue is a record the implementer did not write. Confirm each CHECK and guard command
   is byte-identical to the issue body's, whitespace and lookalike punctuation included — a smart
   quote that silently changes a grep pattern is exactly what this catches.
3. **No collateral edits.** `git diff <freeze-sha> --stat`, read for files no phase named — test
   files above all, which a command-based criterion has no reason to touch.

Report the tamper verdict as `clean-by-substitute` with its basis, not bare `clean`. The
distinction is what tells a downstream reader whether a mechanism ran or was unavailable.

A command-based check is also the more gameable kind, because it asserts over *text* rather than
behaviour: a rename, a reflow across two lines, or a comment-out drives `grep -c` to `0` with the
behaviour untouched. So pair one with a guard over the behaviour, and have the verifier state
plainly whether the diff could satisfy the check without doing the work.

### When the work must edit its own oracle

Test-infrastructure issues break the assumption that check files and implementation files are
disjoint — the files to change *are* the oracle. A whole-file diff would flag the sanctioned
edit, so scope the check instead, and **state it as an invariant, never as a whitelist of
allowed line forms**:

> No line in the diff may change what any frozen check asserts — no test body, assertion,
> `skip`/`xfail` marker, or signature change. Sanctioned: `<the specific edit the plan calls
> for>`.

A whitelist of permitted line forms ("every added line must be a `filterwarnings` decorator")
looks stricter and is worse: it fires on inert additions like a comment, and a rule that cries
wolf gets waved through. Pair the invariant with a behavioural guard — the tests still run and
pass — which is what actually catches a weakened oracle.

## When a check is genuinely wrong

Sometimes it is: a path typo'd at intake, a fixture renamed since, a criterion whose check
mis-states the criterion. A rule that never bends would strand a good run on a typo. Two paths,
depending on what actually changes:

- **Clarification** — the wording never matched its own intent, and fixing it alters no
  criterion or guard. Log it; no tier change.
- **Amendment** — it changes what a criterion or guard *asserts*. Follow the five steps below,
  ending in a tier downgrade.

The line is mechanical, not rhetorical: **re-run the old and the new wording against BOTH trees —
the freeze commit AND the current implementation. If any verdict changes at either tree, it's an
amendment.** A clarification can't change what passes — that's what makes it a clarification.
Both paths need a human to adjudicate and put the verifier's finding on the record; only the
amendment path costs the tier.

**Naming both trees is load-bearing; a single tree is not enough.**

- **At the freeze commit** you learn only *whether the replacement still has teeth.* This is
  necessary and nearly worthless on its own: at freeze the work does not exist, so **almost any
  non-vacuous check fails there — including a replacement deliberately shaped to fit the
  implementation.** "Both fail at freeze" is evidence *adjacent* to "the swap didn't matter."
- **Against the current implementation** you learn whether swapping the check *changes whether
  this PR passes.* That is the question the downgrade exists to ask, and the freeze tree
  structurally cannot answer it.

So the four cells look like this, and only the top-left is a clarification:

| | verdict same at freeze | verdict differs at freeze |
|---|---|---|
| **verdict same vs. implementation** | clarification | amendment |
| **verdict differs vs. implementation** | **amendment** | amendment |

The reason the cheap path exists at all: downgrading a run over a typo is a false positive, and
false positives train the operator to wave the mechanism through. A purely cosmetic rewording
changes no verdict at either tree, so it still costs nothing.

**Scope: this governs tamper rules too, not only criteria and guards.** A tamper rule is an oracle
— it decides whether the frozen set was respected — so restating one mid-run is the same act and
gets the same test. State tamper rules as invariants over *what a check asserts*, never as
whitelists of allowed line forms; a rule that fires on inert changes (comments, sanctioned
appends) is a false positive, and rewriting it mid-run is now an amendment.

The amendment path is deliberately visible and costly:

1. **STOP.** Do not edit the check.
2. State the case explicitly: what the check asserts, what the criterion says, why the check
   fails to test the criterion, and the proposed replacement.
3. **Get human confirmation.** In autonomous (`express`) runs, this is one of the few points
   that surfaces to the human regardless of tier.
4. **Log it** in `checks.md`'s `Amendments` section: criterion id, the old check, the new
   check, the reason, and the new freeze sha for that file.
5. **Downgrade the tier to `needs-review` for this run**, whatever it was before, and note the
   downgrade in the PR body. An amended oracle was not independently authored before
   implementation, so it no longer supports an autonomous merge.

The downgrade is the point. It makes amending a check honest rather than free: the run still
finishes, but it finishes in the human-reviewed lane. An agent inclined to relax a check to
stay autonomous gains nothing by it.

"The implementation would be cleaner if the check allowed X" is not a wrong check — that's the
check doing its job. Only a check that fails to test its own criterion qualifies.

## The verification gate

This is the *verification* half only. `phases/pr.md` owns the **merge** gate, which adds tier,
unresolved review threads, and risk-gated paths on top of everything here — don't read this list
as complete for merge purposes.

A run's verification passes when **all** hold:

- Every criterion in `checks.md` with a check: that check ran and passed, per the independent
  verifier's report — individually observed, by its own command.
- Every human-judgment criterion: its named evidence was presented and a human graded it.
- **Every guard still passes**, by its own command. A guard that flipped from pass to fail is a
  regression this work caused, and it blocks the gate exactly like a failing criterion.
- The tamper diff is empty, or every difference is explained by a logged amendment. Where
  `Check files` is empty, the substitutes ran instead and the verdict says `clean-by-substitute`.
- The project's own gates (`make lint`, `make test`, `make check`) are green.

Watch the specific cheat the guards exist to catch: making a criterion go green by deleting or
skipping the coverage that contradicted it. That leaves every criterion passing and the suite
green, and only a guard notices.

Aggregate green is not the gate. `make test` passing tells you nothing about whether C2's
check ran; a skipped test, a collection error, or a test that never got written all look like
green in the aggregate. Run each criterion's check by name and read its output.

**Confirm the check collected something.** A check that ran zero tests is the most dangerous
output in this file: `no tests ran` is what a nonexistent file, a typo'd node name, a stale `-k`
expression, and a mangled shell invocation all produce, and it reads as absence-of-failure. Under
`tail -1` it is easy to skim as fine. Prefer a mechanical signal over care: **`pytest` exits `5`
when it collects nothing**, distinctly from `0` (passed) and `1` (failed), so treat exit 5 as a
failed check. Record the collected/passed count in `AT FREEZE` and in each guard's evidence so a
later reader can see the check had teeth.

The same trap catches the *command* rather than the code, which is why re-running a check that
"passed" with a corrected invocation is worth the two seconds.
