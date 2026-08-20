# Micro-test: the discriminate rule — results

`references/acceptance-criteria.md` § **2. Does it discriminate?** — written from the #638
dogfood failure, never tested as *wording*. This is that test.

Everything here is reproducible: `build-variants.py` derives every guidance variant from the
shipped file by anchored deletion and dies if an anchor moves; `build-prompt.py <arm> <fixture>`
assembles a prompt; `run.sh <arm> <reps> <fixture>` runs it; `tally.sh` counts. Raw per-rep JSON
is in `results/`.

## The fixture is real, and that mattered

The issue text is decafclaw **#638**'s original author text, extracted verbatim from the live
issue (everything before the intake pass appended its criteria — so the fixture does not contain
the answer). Both terminal transcripts were **captured by running those exact commands** in a
worktree of decafclaw at `bd6cbf3`, the base of PR #659, i.e. the tree before the fix:

```
$ uv run pytest tests/test_terminals.py tests/web/test_terminal_ws.py -q -W error::DeprecationWarning
13 passed in 1.36s                                    ← exit 0. The intuitive check is vacuous.

$ uv run pytest tests/test_terminals.py tests/web/test_terminal_ws.py -q
13 passed, 2 warnings in 1.20s                        ← the symptom is still there.
```

Nothing was reconstructed from memory or plausibility. That is the rule move 4c broke when a
fabricated measurement reached a GitHub issue, and it is cheap to honour: the worktree took a
minute.

## Arms

Each arm differs **only** in the guidance text supplied with the fixture. `Z` gets none.

| Arm | Guidance |
|---|---|
| **Z** | none — no-guidance control |
| **C** | acceptance-criteria.md **minus § 2 entirely** (+ the renumbering and the two cross-references that are meaningless without it) |
| **T** | acceptance-criteria.md **exactly as shipped** — treatment |
| **P** | T minus § 2's branch-enumeration sentence |
| **R** | T minus § 2's "Record the observed failure …" paragraph |
| **N** | T minus § 2's near-miss paragraph |
| **M** | § 2 reduced to its heading + "**Run the check and confirm it fails on current behavior.**" |
| **D / E** | C / T with `phases/intake.md` also in context — the highest-fidelity pair |

**Arm C is not a synthetic control — it is the candidate edit.** So the experiment measures the
artifact that would actually ship, not a stand-in for it.

## The instrument had to be fixed twice, and both fixes are part of the result

- **v1** gave only the green transcript. Under-determined: "the issue is stale" is a defensible
  read when you cannot go and look, and the seal forbids looking. 15/15 said `CLOSE-AS-STALE`.
- **v2** added the second transcript, closing that branch with evidence. **14/15 still said
  `CLOSE-AS-STALE`** — several while their own reasoning said the opposite. Tv2-4: *"the 2
  warnings are still present … This means the behavior the issue asks for has already been
  implemented."* That is not a judgment, it is a label magnet.
- **v3** gave each label an explicit `Asserts:` clause. This moved the numbers and is the round
  everything below is measured on. It did **not** fully cure the problem — Tv3-3 ends *"the
  oracle cannot discriminate 'done' from 'untouched'"*, verbatim the `REPLACE-CHECK` assertion,
  and answers `CLOSE-AS-STALE`.
- **v4** dropped the labels entirely (see below).

This is the handoff's "labels must name actions" rule failing twice more, in a session that had
read the rule. Naming an action is necessary and **not sufficient**: `CLOSE-AS-STALE` names an
action perfectly well. What v3 added was making the labels *disjoint on evidence*.

## Result 1 — the failure the rule exists to prevent never happens

**`FREEZE-AS-WRITTEN`: 1 of 125 forced-choice reps.** Not one arm — including the arm with no
guidance whatsoever — froze a check it had just watched pass. The single exception is arm **M**,
discussed below.

This is the robust number, and it is immune to the label problem: no correct chain of reasoning
lands on `FREEZE-AS-WRITTEN` by accident. Every arm identified, unprompted, that a check which
passes today cannot grade the work. Zv1-1, with zero guidance: *"Since the criterion's check
already passes without any implementation work…"*

So § 2's interpretive claim — "a check that already passes proves nothing" — **is supplied by the
model without being told.** It is not load-bearing.

## Result 2 — the section makes action selection worse, and less of it is worse still

Fixture v3, n = 15 per arm (Z at n = 5):

| Arm | § 2 content | REPLACE-CHECK | STALE | FREEZE |
|---|---|---|---|---|
| **C** | *absent* | **15 / 15** | 0 | 0 |
| **R** | minus record-para | 10 / 15 | 5 | 0 |
| **T** | as shipped | 8 / 15 | 7 | 0 |
| **P** | minus enumeration | 8 / 15 | 7 | 0 |
| **N** | minus near-miss | 6 / 15 | 9 | 0 |
| **M** | one sentence only | **2 / 15** | 12 | **1** |
| Z | *(no guidance at all)* | 2 / 5 | 3 | 0 |

C vs T: Fisher exact, two-tailed **p ≈ 0.006**. C vs M: **p < 0.0001**.

Two things fall out, and the second was a surprise:

1. **Removing § 2 entirely is the best configuration measured**, and by a margin that is not
   noise. Every variant that *keeps* the section, in any form, is worse.
2. **Trimming § 2 toward its procedural core makes it monotonically worse.** M — heading plus
   "Run the check and confirm it fails on current behavior." — is the worst arm in the study and
   the **only** one that ever produced `FREEZE-AS-WRITTEN`. A bare instruction to run the check,
   with the elaboration stripped, appears to license "I ran it, it's green, done."

I expected the opposite. "Trim to the procedural sentence" was the small, safe-looking edit, and
it is the actively harmful one. It was only ruled out because it was measured.

**Attribution failed.** No single paragraph explains C's advantage: removing the enumeration
changes nothing (P = T), removing the record-paragraph helps slightly (R = 10), and removing the
near-miss paragraph *hurts* (N = 6). The effect belongs to the section as a whole and the
mechanism is not established. Recorded as unexplained rather than narrated into a story.

## Result 3 — v4, no labels at all

v4 removes the drafted criterion, the transcript, and the verdict labels: the model is asked to
write the criteria section itself, which is what `intake` actually does. Rubric fixed in advance
(`v4-preregistration.md`) and every rep read by hand.

| Mark | Z | C | T |
|---|---|---|---|
| states a check must be **run and observed failing** before freeze | 0/5 | 0/5 | 0/5 |
| records the current failing observation ("currently 2 warnings") | 3/5 | 1/5 | 3/5 |
| proposes the vacuous `-W error` check | 0/5 | 1/5 | 0/5 |
| separates guards from criteria | 0/5 | 5/5 | 5/5 |

The guard-split row is the manipulation check: C and T are demonstrably reading the guidance and
Z is not, so a null on the other rows is a real null, not a plumbing failure.

**v4's primary metric is unmeasurable and that is my fault**: SEAL_V4 says "you cannot run
commands", which directly suppresses "run the check". What survives is that no arm separates on
anything else, and that the no-guidance arm never proposed the vacuous check — it went straight
to `make test` → 0 warnings, which is the discriminating check the real intake pass landed on.

## Redundancy — the grep the handoff mandated

`grep -rn "discriminat\|fails today\|passes today\|fail now"` over `skills/agent-session/`
finds the concept in **seven** places outside § 2:

- `acceptance-criteria.md` itself — the guards section (*"It must discriminate — fail now, pass
  when done"*), the gameability lead-in, tier trigger 1, and the pure-refactor example
- `spec-template.md` — twice, including *"At least one criterion must discriminate"*
- `frozen-checks.md` — the guards note
- **`intake.md` step 5** — the whole procedure, stated harder than § 2 states it: *"Demonstrate
  that each criterion's condition fails today. Not 'assert that it does' — show it, with a
  command you actually ran, and record the output."*
- `triage.md` step 2 — *"runs each proposed check and records what it observed … (fail today =
  criterion, pass today = guard)"*

Both consuming modes state the procedure at the point of use. § 2 is the seventh statement. This
is the same tell as the two rules already measured away — *the concept was already reachable
elsewhere, and the new rule restated it closer to where the failure was noticed* — now 3 for 3.

## Limits, stated rather than buried

- **The no-guidance control is not clean.** The global `~/.claude/CLAUDE.md` leaks into every
  `claude -p` on this machine. Runs are launched from `/tmp/mt-cwd` so this repo's own docs
  cannot leak, but the global file cannot be suppressed. Effects here are **lower bounds**.
- **One fixture, one issue shape.** Everything rests on #638's near-miss. A different vacuity
  (missing oracle, wrong config) might behave differently.
- **v1–v3 are forced-choice**, and forced choice is exactly what went wrong twice. The
  `FREEZE-AS-WRITTEN` count is the number to trust; the REPLACE/STALE split is weaker evidence.
- **The mechanism behind C's advantage is unknown.** Acting on an unexplained effect is a real
  risk and is why arms D/E were run.

## Result 4 — the effect survives the strongest confound

The obvious objection to cutting § 2: the arms read `acceptance-criteria.md` alone, but the real
consumer reads `intake.md` too, and **intake.md step 5 is the discriminate procedure stated
harder than § 2 states it**. If § 2 looked inert only because that context was missing, adding it
back should close the gap.

Fixture v3, n = 15, with `phases/intake.md` prepended to the guidance:

| Arm | Guidance | REPLACE-CHECK |
|---|---|---|
| **D** | intake.md + acceptance-criteria.md **minus § 2** | **15 / 15** |
| **E** | intake.md + acceptance-criteria.md as shipped | 8 / 15 |

Identical to the pair without intake.md (C 15/15, T 8/15). Fisher exact **p ≈ 0.006** again.
Adding the phase file moved neither arm by a single rep. § 2 adds nothing to intake.md, and
intake.md does not rescue § 2.

## Decision: cut § 2 entirely

Applied. The shipped `acceptance-criteria.md` is now **byte-identical to arm C** — the artifact
that was measured, not a hand-edit resembling it.

Three independent lines point the same way, which is why an unexplained mechanism is still
actionable:

1. The failure the section prevents does not occur without it (1 `FREEZE` in 125, and that one
   was produced *by* a variant of the section, not by its absence).
2. Removing it is the best-measured configuration, before and after the confound check.
3. The concept is stated seven other times, twice at the point of use by the modes that consume
   this file.

**Rejected: trimming § 2 to its procedural sentence.** That was my instinct going in — smaller
edit, keeps the "three tests" structure, no cross-file changes. Arm M measured it as the worst
configuration in the study and the only one that ever froze a vacuous check. It was ruled out by
measurement, not by argument, and I would have shipped it otherwise.

**No pointer was added to the skill** explaining the absence, unlike the withheld-decision cut
which left one in `intake.md`. Two reasons: the shipped skill is then byte-identical to arm D
(pointer included would not be), and this study's whole lesson is that text in this file has
effects that do not follow from reading it. The provenance lives in `docs/design.md`.

Two cross-file edits were unavoidable, since both named a section that no longer exists:
`SKILL.md`'s index row and `intake.md` step 5's "apply the three tests". Both now say two. Note
that arm D carried intake.md's *stale* three-tests reference and still scored 15/15, so removing
a dangling pointer is the only respect in which the shipped combination differs from the measured
one.

## What is still unmeasured

The **procedural** half — does the rule make an agent actually *run* the check before freezing?
No sealed fixture can test it: the seal that stops a subagent wandering into this repo's docs is
the same seal that stops it running anything. v4 tried and its own prompt suppressed the metric.
That half is testable only by dogfood, and the #668 intake this session is one data point for it
(both criteria demonstrated failing with real commands, one via a throwaway reproduction).
