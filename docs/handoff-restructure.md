# Handoff: split the docs, then the amendment policy (move 6)

Task brief for a fresh context. Read `CLAUDE.md` and `docs/design.md`. This doc is the task plus
the things that are in nobody's head anymore.

## Corrections to inherit — read this before anything else

Things a naive reading of the repo would get wrong, because they were asserted and later found
false. The first five carry over from `handoff-measurement.md` and still hold; **6–9 are new**.

1. **`--bare` is unusable here** (auth is strictly `ANTHROPIC_API_KEY` / `apiKeyHelper`, no key on
   this machine, and it drops the CLAUDE.md `express` declares as an input).
   **`--max-budget-usd` exists.** `--permission-mode dontAsk` denies unlisted **mutations**, not
   unlisted commands — read-only commands are auto-allowed.
2. **A fabricated measurement once reached a GitHub issue** (decafclaw #710, since retracted in
   place). *Construct fixtures from the code, never from plausibility.*
3. **`--allowedTools`, `--disallowedTools` and `--add-dir` are variadic**, so a positional prompt
   after them is swallowed. The driver passes prompts on **stdin**.
4. **Permission-rule paths need a `//` prefix when absolute.** `Edit(/abs/**)` does **not** block.
5. **`gh pr checks --json state` returns `SUCCESS`, not `pass`** — the normalised field is
   `bucket`.
6. **The discriminate rule is GONE from `acceptance-criteria.md`, deliberately, and the evidence
   says keep it gone.** 170 reps: it measured *worse than its own absence* (15/15 vs 8/15, twice,
   p ≈ 0.006). Before re-adding anything about discrimination, read
   `dev-sessions/2026-07-27-1403-measurement/microtest/results.md`. **The trim that looks
   obviously safe measured worst of nine arms** and was the only arm that ever froze a vacuous
   check.
7. **"Verdict labels must name actions" is necessary and not sufficient.** `CLOSE-AS-STALE` names
   an action perfectly well and still attracted 14/15 reps whose own reasoning contradicted it.
   The working rule is stronger: **labels must be disjoint on evidence** — each stating what
   choosing it asserts about the world.
8. **A nonzero `claude -p` exit does not mean the run failed.** A stream can carry a successful
   result *and* a trailing `error_during_execution`. Fixed in the driver; do not "simplify" the
   `has_success_result` guard away.
9. **`make run` now defaults to `--max-budget-usd 25`, and `make loop` does two issues.** The
   hand-assembled command is no longer needed.

## State

The skill is complete; all four routing paths have real-run evidence. **Eight PRs** have gone
through it. The board-driver needed zero skill changes, enforced by `make skill-readonly`.

Move 5 closed the two big gaps: the **discriminate rule is measured and cut**, and the
**multi-issue loop has run** — #668 → PR #719 and #656 → PR #722, both `gate-eligible`, $11.76 and
$11.20. Neither PR is merged; nothing merges.

**Genuinely not yet proven:**

- **Phase 3 (conditional auto-merge)** — untouched, and now gated on *two* things: the `PreToolUse`
  merge-block hook **and** the amendment-policy ambiguity below.
- **`ci-stale` has still never fired on a real PR.** It has fixture tests and, as of move 5, an
  extraction that actually works.
- **Multi-phase `execute` with real implementer subagents.** decafclaw **#625** remains the
  specced `needs-review` vehicle.

## The task, in order

### 1. Split `docs/design.md` — Les asked for this directly

It is ~1300 lines and has turned into a dev diary. The reason it keeps growing: **each move's
durable lessons are interleaved with its chronology**, so the parts a new session needs are buried
in narrative it doesn't. The four `handoff-*.md` docs are informal workarounds for exactly this.

Proposed split, agreed in conversation but **not started** — treat the shape as a proposal, not a
decision:

- **`design.md`** — governing principle, skill architecture, the criteria/tier contract, capability
  ladder, phased rollout, open questions, a short current-state block. Readable in one sitting.
- **`build-log.md`** — the chronological account, moves 1–5. Append-only; nothing reads it to make
  a decision.
- **`findings.md`** — the durable, still-governing lessons. **This is the file that actually fixes
  the problem** — the diary grows because a lesson has nowhere else to live. At minimum it should
  carry: the recurring "gate row satisfied by adjacent evidence" class (now **eight** instances),
  the instrument rules, the add-then-measure-away tell (**3 for 3**), and the verified command
  gotchas from "Corrections to inherit".

Do this **first and in a fresh context** — it is a large mechanical move over a file that must not
lose content, and it is much safer before the context fills up. Verify by diffing content
inventories, not by eye.

### 2. Resolve the amendment-policy ambiguity — a phase-3 blocker

`frozen-checks.md` says: *"re-run every criterion and guard under both the old and the new wording.
If any verdict changes, it's an amendment."* **It does not say against which tree**, and on #668
the two readings gave opposite answers:

| | at the freeze commit | against the shipped implementation |
|---|---|---|
| original frozen check | fails | **fails** |
| clarified check | fails | passes |

At the freeze commit → clarification (no verdict changed), which is what the run published, along
with `amendments: none` and `eligible-for-auto-merge`. Against the implementation → amendment,
which costs a tier downgrade.

So there is a live route to `eligible-for-auto-merge` with a swapped oracle. **Nothing merged, so
nothing was lost — but this must be settled before anything merges automatically.** It was left
open deliberately: it changes *when runs get downgraded*, which is a tier-policy call, i.e. Les's.

Worth carrying into that decision: the run was **not** cheating. The criterion's *prose* always
said "the user types into the textarea", so there was an oracle outside the implementer's choice to
appeal to, and the clarified check still fails at freeze (verified by running all four cells). What
made it adjudicable is that **the criterion prose was independent of the check's mechanics** — and
the intake pass that wrote it nearly destroyed that independence by specifying mechanics in the
check.

### 2b. The roadmap is the third thing `design.md` must keep — and the easiest to lose

**Do not treat this as a detail of the split. It is the part most likely to go wrong.**

Chronology is safe to move: it is delimited by `### Move N` headings. Findings are identifiable.
**Forward-looking material is neither** — it is fragments embedded in narrative, and a faithful
mechanical split migrates them into `build-log.md` where nothing will ever read them again.

Where the fragments currently live:

| Location | What is there |
|---|---|
| `## Open questions (for the pending work)` | 3 entries, 2 already struck |
| `#### Pending after move 3` | 8 entries, 4 now struck |
| inside `### Move 4b` | the auto-ok-vehicle note (now annotated as resolved) |
| inside `### Move 5` | the amendment-policy blocker, deliberately left open |
| `## Resolved (was open)` / `## Resolved in move 1` | closed, but the *reasoning* is still load-bearing |
| this handoff | the backlog in §3 below |

**Five entries were reconciled just before this handoff was written** because they read as open and
were not: queue depth, the decafclaw lockfile churn, the three-rules-measured counter, move 4b's
"the auto-ok loop still has no vehicle", and "should the merge gate read GitHub's check runs".
That is a 5-out-of-11 stale rate in the forward-looking material — assume the same rot has
continued and **re-verify each surviving item against the repo before carrying it across**, rather
than copying it. Do not trust this table either; it was accurate when written.

### 3. Then the remaining backlog

- The `PreToolUse` merge-block hook — a hard precondition for any *unwatched* host.
- The GHA host, and a durable park mechanism that survives a host change.
- A real multi-phase `execute` run on #625.
- Whether `#656`'s stale `parked` entry matters: it was parked by the exit-code bug, and
  `parked.jsonl` is append-only with no un-park record. Moot in practice today (it has an open PR,
  so selection skips it anyway), but the state file now lies.

## Method — the instrument rules, updated

- **Control vs treatment, 5+ reps per arm, read every rep by hand.** A tally-only reading of move
  5's study would have concluded the opposite of the truth.
- **Derive variants from the shipped file** by anchored deletion that dies if an anchor moves.
  Better still, make the control *be* the candidate edit, so you measure what you ship.
- **Seal the fixture** — subagents run inside this repo and will check whether it is real.
- **Labels disjoint on evidence** (see correction 7).
- **Pre-register the rubric and commit it** before running, once you have revised an instrument
  twice. Move 5 did; it is why the v4 null is reportable rather than suspicious.
- **Mutate what a guard guards and watch it fail.** Every guard in move 5 was mutation-tested, and
  one new test was caught being non-discriminating that way.
- **A clean no-guidance control is unreachable** — the global CLAUDE.md leaks into every
  `claude -p`. Effects are **lower bounds**. Say so.
- **Reps cost ~$0.33 and an arm of 15 takes ~12 minutes.** Cheap enough that measuring beat
  reasoning every single time in move 5.

## Not in scope

Phase 3 auto-merge. decafclaw's `.nvmrc` drift (#716/#717). Merging #719 or #722 — those are Les's
calls, and `eligible-for-auto-merge` is a finding, not an instruction.

## Launcher prompt

> Continuing the `agent-session` skill in this repo (`~/devel/agent-sessions`). Read `CLAUDE.md`,
> `docs/design.md`, and `docs/handoff-restructure.md` — start with the handoff's **"Corrections to
> inherit"**, which now has nine entries; four are new this round and two of them reverse things a
> naive read of the repo would conclude.
>
> The task is **move 6: split `docs/design.md`**, which has grown to ~1300 lines and become a dev
> diary. The handoff proposes a three-way split into `design.md` / `build-log.md` / `findings.md`
> and explains why the third file is the one that actually fixes the problem. Treat that shape as a
> proposal, not a decision. Do it first, while context is fresh, and verify by diffing content
> inventories rather than by eye — the risk is losing content silently.
>
> Then **resolve the amendment-policy ambiguity** documented in the handoff: `frozen-checks.md`
> says to re-run both wordings and call it an amendment if any verdict changes, but not against
> which tree, and the two readings gave opposite answers on a real run. It is a phase-3 blocker and
> a tier-policy call, so bring me the options rather than picking one.
>
> **Nothing merges.** PRs #719 and #722 are both sitting at `eligible-for-auto-merge`; that is a
> finding the gate reports, not an action to take.
