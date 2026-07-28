# Move 7 — notes

## Step 2 — `skills/` marked risk-gated (done)

Added a **"Risk-gated paths (off-limits to unattended work)"** section to `CLAUDE.md` declaring
`skills/**`. No new mechanism: `acceptance-criteria.md`'s trigger 2 is already
project-configurable and fires on *"anything the project's CLAUDE.md marks off-limits."* No skill
file was touched to achieve the partition, which was the point.

**Verification deliberately routed through the triage fan-out rather than a self-check.** The brief
asks to "confirm the tier falls out rather than being argued into place" — a claim I cannot honestly
test on myself, having just written the CLAUDE.md line. Instead the triage subagents (fresh
contexts, given only `acceptance-criteria.md` and the repo) tier every issue independently. Whether
a skill-touching issue comes back `needs-review` citing trigger 2, unprompted, is the real test.
The scanners were **not** told that `skills/` is risk-gated.

## Step 3 — board + issues (done)

Board: <https://github.com/users/lmorchard/projects/9>. Nine issues filed and added, from the
reconciled roadmap only.

Filed **without** criteria, tier or marker. Supplying those would have left `triage` nothing to do
and made the "second corpus" fake — the corpus has to start in the pre-triage state to measure
anything.

| # | Title |
|---|---|
| 1 | Driver: add a PreToolUse merge-block hook before any unwatched host |
| 2 | Sweep every gate row for evidence adjacent to what it names |
| 3 | GHA host, and a park mechanism that survives a host change |
| 4 | Driver: refuse to run when `--repo-path` contains `--skill-dir` |
| 5 | `parked.jsonl` is append-only with no un-park record, so it lies |
| 6 | `ci-stale` has never fired on a real PR |
| 7 | Get a real multi-phase `execute` run (vehicle: decafclaw #625) |
| 8 | Decide the standing posture for modes that dispatch subagents |
| 9 | Extract gate-block parsing into a Python module its tests import |

### Finding — the skill's column vocabulary does not match GitHub's default board

`gh project field-list 9` returns **`Todo` / `In Progress` / `Done`** — GitHub's default template.
`references/github-projects.md` describes transitioning through **`Ready` → `In progress` →
`In review`**. There is no `Ready` and no `In review` on a default board.

Not blocking here: selection gates on marker + anchored tier and treats the column as advisory, and
this move does no invocation. But **a transition to a non-existent column cannot succeed**, and
every *new* board starts from this template. decafclaw's board was built up by hand over time,
which is why this never surfaced.

The skill already says to read names from `gh project field-list` rather than the doc, so it will
*read* correctly — the gap is what it does when its target state has no matching option. Recorded
rather than fixed; it is a skill-wording question and therefore `needs-review` by the rule this
move just added.

## Step 5 — host-agnosticism, tested for the first time (done)

`agent-session-driver.sh`'s header claims *"deliberately host-agnostic: no `$HOME` assumptions,
every path a flag"* and it had **only ever run against one repo with one board.**

```
make dry-run REPO=lmorchard/agent-sessions BOARD=lmorchard/9
```
```
== select ==
repo lmorchard/agent-sessions: read 9 open issues
board lmorchard/9: read 9 items (advisory only; does not gate)
no issues carry the marker -- nothing for this driver to consider.
dry run -- no claude invocation.
```

**The claim holds for the selection path.** A second repo and a second board resolved with no code
change, both counts printed (the `item-list` truncation lesson applied), and the empty result is
correctly attributed to *no markers* rather than to an empty board — a null reported as a null.

Worth re-running after triage writes markers back: this run exercised selection's *reject*
path only. Seeing it actually surface eligible issues is the stronger test.

## Step 4 — `triage`, the second corpus (scan complete, not yet written back)

Nine read-only `Explore` scanners, one per issue, run as the mode specifies. Agent-tool dispatch
authorized by Les for this fan-out — the first time `triage` step 2 has run as designed rather than
inline.

### Result: 1 `auto-ok`, 8 `needs-review`

| # | Score | Tier | Load-bearing trigger |
|---|---|---|---|
| 1 | under-specified | needs-review | 1 — hook-block fixture has no oracle; block surface withheld |
| 2 | under-specified | needs-review | 2 (`skills/**`) + 1 |
| 3 | under-specified | needs-review | 2 (CI config) + 1 |
| 4 | under-specified | **auto-ok** | none fired |
| 5 | under-specified | needs-review | 1 — un-park design choice |
| 6 | intent-unclear | needs-review | 1 — three-way choice |
| 7 | under-specified | needs-review | 2 (inherited from decafclaw #625) + 1 |
| 8 | under-specified | needs-review | 1 primary; 2 only on one branch |
| 9 | under-specified | needs-review | 2 (own hazard: hand-run only) + 1 |

**The heavy skew is the predicted outcome, not a failure.** The brief said to expect it and not to
fudge against it. Two scanners explicitly declined to manufacture a passing criterion and said so:
#8 reported that no honest discriminating criterion exists that is not a placement-or-keyword
proxy, and #4 declined to propose "a test case named X exists in `test-driver.sh`" because that is
the presence proxy the rulebook rejects.

**Every proposed criterion failed today.** Across nine independent contexts, no scanner proposed a
criterion that already passes — the same result as the first corpus's 0-of-17, now replicated.

### Step 2's verification — PASSED, and in both directions

The scanners were never told `skills/` is risk-gated. Unprompted:

- **#2 and #8 cited the new `CLAUDE.md` line verbatim** and fired trigger 2 on it.
- **#3, #4, #5, #6 explicitly checked it and declined to fire**, quoting *"Everything else here is
  drivable — `driver/`, `docs/`, `Makefile`."*

So the partition works as a mechanism, not as an argument — and the negative direction (correctly
*not* gating driver work) is the half that would have been easy to get wrong. #4's scanner went
further and flagged that trigger 2's generic "deploy/infra/CI config" default would arguably catch
any driver script, noting the project's explicit configuration overrides the default and that the
ratify pass should make that call knowingly rather than inherit it.

### The headline technical finding, reproduced independently

Scanner #2 ran the shipped classifier and the test file's copy over one identical gate block. I
reproduced it:

```
shipped driver  -> ci-stale       "verdict rests on a commit that no longer ships"
test-file copy  -> gate-eligible  "all gate rows satisfied"
```

**The suite's classifier calls a stale-CI PR eligible for auto-merge exactly where the shipped
driver voids it.** Move 5's record that the ci-sha fix was "mutation-tested" therefore does not
hold for the classifier path. Now in `findings.md` as instance 9, the live one.

### Five errors in text I wrote, caught by the scanners

1. Issue #1 repeated *"`PreToolUse` can hard-block even under `bypassPermissions`"* — traceable to
   `design.md:104`, from the 2026-07-23 research pass whose own note says several specifics from it
   could not be verified. **Zero** entries in `findings.md`'s ledger. Phase-3 blocker #1 rests on
   it, and it is not even load-bearing for the current host (`dontAsk`, not `bypassPermissions`).
2. Issue #8: *"Touches `skills/`, so needs-review by trigger 2 regardless"* — over-claimed. One of
   the issue's own three branches needs no skill edit. Tier right, reason wrong.
3. `findings.md`: "Instance 8 is the live one" — stale within the hour; 8 was closed by the
   amendment decision.
4. `findings.md`: "two live `ci-stale` assertions are `grep -q`" — there are **eight**.
5. Issue #9: "`test-driver.sh` defines 11 helpers" — **15** (12 excluding the harness), inherited
   from the handoff.

Corrections 3 and 4 are committed. 1, 2 and 5 are issue-body edits, batched into write-back.

### A dependency graph none of the issues knew about

- **#7 is blocked by #8.** `execute`'s implementer subagents and independent verifier are
  Agent-tool dispatch. For `intake`/`triage` running inline was survivable; here it **collapses
  implementer and verifier into one context, destroying the only property the run exists to test.**
  Tonight's authorization was scoped to `triage`.
- **#3 and #5 collide in `parked.jsonl`.** A naive "port it to a durable store" would make three
  known-wrong records durable.
- **#3's GHA half is blocked by #1** — a GHA host is unwatched by definition.
- **#9 should sequence before or with #2 and #5.** Both need frozen checks that extract the real
  function rather than mirror it; #9 is the general fix.
- **#4 conflicts with the drivable-half premise.** `SKILL := $(CURDIR)/skills/agent-session`, so
  driving this repo *is* the nested configuration #4 refuses. And the deny rules are built from
  `$SKILL_DIR` regardless of nesting, so the hazard #4 names is already covered by
  `make skill-readonly`.

### Also surfaced

- **#649 has no row in `runs.jsonl`** (only 585, 656, 668, 710). It was a hand-run dogfood, so it
  is evidence about the *skill's* `needs-review` branch, not about the *driver* carrying a
  `needs-review` issue to completion — which remains untested.
- **#6's scanner proposed an option (d) the issue did not list:** replay `--classify-only` against
  a PR whose head has moved past its gate's ci sha. Reaches the `ci-stale` branch with a real
  `GATE_HEAD_SHA`, no `claude` invocation, no cost.
- The parking case list is duplicated (driver `:567` and `:685`); a write-side fix must touch both,
  and the recovery path is exactly how #656 got its stale record.

## Step 4 (cont.) — write-back complete

All nine augmented in place: marker + criteria + guards + tier + observed check results, original
text preserved. **Verified by substring comparison against a pre-edit snapshot, not by eye** — all
nine byte-identical. Tier labels applied (`auto-ok` / `needs-review`, created for this repo).

### Three reshapes, for actionability over corpus purity

- **#3 → "GHA host for the driver."** Shed its park half. Its trigger-2 tier is *structural and
  will never clear* (a `.github/workflows/` file is risk-gated by definition), so the issue now
  says not to spend effort reducing it. Blocked by #1: a GHA host is unwatched by definition.
- **#5 → absorbs durability**, and now owns `parked.jsonl` entirely. Correctness and durability
  turn on the same undecided question (*what is a park record, and where does it live?*), so
  splitting them into adjacent issues would have institutionalised the collision the scanners
  predicted. One answer — append-an-un-park-record versus derive-from-`runs.jsonl` — collapses it
  to `auto-ok`.
- **#4 → rescoped from refuse to warn-with-`--allow-nested-skill-dir`.** Its stated hazard is
  already covered: the driver builds deny rules from `$SKILL_DIR` unconditionally (`:139`), so a
  nested skill dir still cannot be written. And an absolute refusal would have foreclosed the
  drivable-half dogfood, since `SKILL := $(CURDIR)/skills/agent-session` makes driving this repo
  *the* nested configuration. Residual value is fail-fast on a typo, not prevention.

## Step 5 (re-run) — selection's accept path, the stronger test

```
eligible: 1
  ELIGIBLE #4  tier: auto-ok  |  board column: Todo
    note: board column is 'Todo', not 'Ready' -- not a gate, see spec.md Q2
  SKIP #1,2,3,5,6,7,8,9  tier: needs-review
```

**Host-agnosticism now verified on both paths.** The first run only exercised reject-everything;
this one resolves markers, parses anchored tiers, admits one issue and skips eight — against a
second repo and a second board, with no code change.

The driver also **surfaced the column mismatch on its own**, correctly as advisory rather than as a
gate. That is the move-3 decision ("the board column is advisory; disagreements are reported, not
resolved") paying off in a case it was never tested against.

**A recursion worth noting, not acting on:** #4 is now the one eligible issue, and driving it would
require `--repo-path` = this repo — which is exactly the nested configuration #4 exists to warn
about. The issue is its own first test case.
