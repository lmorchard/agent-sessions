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

## Board column vocabulary — renamed to match the convention (2026-07-28)

Les's hypothesis was right and the data sharpened it. Measured across all six boards:

| Shape | Status options | Boards |
|---|---|---|
| Template | `Backlog` · `Ready` · `In progress` · `In review` · `Done` | 6 decafclaw, 7 starnet, 8 foxcloud-bidi |
| Bare default | `Todo` · `In Progress`/`In progress` · `Done` | 4 Fossilizer, 5 Pebbling Club, **9 agent-sessions** |

**So the skill is not idiosyncratic — every actively-managed board already uses the exact five-state
vocabulary `github-projects.md` transitions through.** Board 9 was the outlier because
`gh project create` applies no template.

Renamed board 9 to match board 6 byte-for-byte (verified by `diff` of the option lists), including
colors and descriptions fetched via GraphQL. Then reassigned all nine items: the eight
`needs-review` issues to `Backlog`, #4 (`auto-ok`) to `Ready`.

**Selection re-verified after the rename:** `eligible: 1`, and the column-disagreement note is now
gone — it reads `board column: Ready`, because column and tier finally agree. That is the first time
the advisory-column mechanism has had agreement to report rather than a mismatch.

### Mechanics worth not rediscovering

- `gh project field-list` does **not** expose option colors or descriptions — GraphQL only.
- **`updateProjectV2Field` replaces the option set wholesale.** It accepts no option IDs, so any
  option absent from the new list is deleted and every item assigned to it **loses its status**.
  Renaming is a two-step operation: replace, then reassign, then verify nothing is blank.

All three recorded: the general fact in `references/github-projects.md` (it is useful to any project
installing the skill, not just this one), the API mechanics in `findings.md`, the board's own
declaration in `CLAUDE.md`.

### A self-inflicted trap found while documenting

`github-projects.md`'s CLAUDE.md schema example wrote `In Progress` / `In Review` **three lines
above its own warning** that real boards use lowercase and an exact-match transition would fail. The
example contradicted the warning. Fixed the example to the casing GitHub's templates actually ship.

### Left as a question rather than a rule

The skill handles *"no board declared"* but not *"board declared, target column absent."* I extended
the existing **say so once** pattern to cover it rather than inventing a new rule — that pattern is
already load-bearing in this file, and this project is 3-for-3 on added rules measuring away. The
deeper question (should the skill create a missing column? map to the nearest? refuse?) is
behaviour-shaping and belongs on the board, not in an unmeasured paragraph.

## The decision pass (2026-07-28) — seven decisions, three issues converted

| # | Decision | Effect |
|---|---|---|
| **#5** | Derive the park list from `runs.jsonl`; abandon `parked.jsonl` as source of truth | → **`auto-ok`**. Write-side criterion withdrawn; the four stale entries fixed by construction, so trigger 2 ("data migration") never fires |
| **#6** | Option **(d)** — replay `--classify-only` against a PR whose head moved | → **`auto-ok`**. Free, no invocation. C2/C3 withdrawn to #9; C4 demoted |
| **#8** | Option **(c)** — carve out read-only `Explore` in operator policy; skill unchanged | **Closed.** No unmeasured skill wording added |
| **#9** | Parsing **and** classification move; pytest managed by `uv` | Scope settled; trigger-1 leg retired |
| **#1** | Merge endpoints only (`gh pr merge`, `gh api` PUT/POST to `*/pulls/*/merge`, `curl`) | One of two trigger-1 legs retired |
| **#2** | Enumeration only; fixes become their own issues | Finite exit condition |
| **#7** | *Not* unblocked by #8 — needs a separate write-capable grant | Still `Backlog` |

**Queue went from 1 eligible to 3.** `#4`, `#5`, `#6` all `auto-ok` and `Ready`.

### #9's decision has a consequence worth stating plainly

pytest + `uv` means **this repo grows its first Python dependency manifest** (`pyproject.toml`,
`uv.lock`). Dependency addition is a trigger-2 risk-gated path, so #9's `needs-review` now stands on
**two independent legs** rather than one — its own hand-run hazard, plus the dependency. Recorded so
the tier is not later mistaken for over-caution. The invariant that survives is narrower than "no
third-party imports": **`driver/gate.py` itself must stay stdlib-only** so the driver remains
portable, while its *tests* may use pytest. `make` stays the operator interface; `uv run pytest`
becomes a `driver-test` prerequisite rather than a replacement.

### #7's blocker is asymmetric, which #8's decision does not cover

`execute`'s implementers need **write**; its verifier must **not** have it. The verifier's value in
this project comes precisely from being structurally unable to edit what it grades — dispatched as
`Explore`, no Edit/Write, which is how it caught its author four times. **A blanket grant would
quietly remove the property that makes it worth dispatching.** So the grant #7 needs is not "allow
Agent tool for execute" but a shaped one.

### A live finding, and the mechanism caught me

Appending a revised `## Tier:` heading left **two** conflicting tier headings in #5 and #6. The
driver did **not** silently honor the first — it returned:

```
SKIP #5  tier: CONFLICT -- body names both tiers on Tier heading lines; surfacing rather than picking
```

**That is move 1's "if they disagree, surface the conflict rather than picking one" decision firing
live for the first time**, and what it caught was my own write-back. The anchored extraction
(`^##[[:space:]]*Tier[[:space:]]*:`) plus an explicit `conflict` state did exactly what it was
designed for.

Fixed by demoting the original heading to `## Original tier assessment (superseded …)` — which no
longer matches the anchor — leaving exactly one `## Tier:` line. Verified: `eligible: 3`.

**The generalisable lesson for the write-back path:** a revised tier must *replace* the heading, not
append a second one. `intake`/`triage` write-back should say so, since re-tiering after a decision is
a normal event and the obvious way to do it produces a body the driver refuses to read. That is a
skill-wording change, so it belongs on the board rather than in an unmeasured edit — candidate #10.

## Step 6 — the gate parser extracted (issue #9)

Frozen checks in [checks.md](checks.md); frozen at `22897d4`, all six demonstrated failing before
any implementation existed.

### The hazard #9 named is real, and it fails silently

Tested before building anything, since it gates whether this issue can ever be driver-run:

| Write strategy | Effect on a running script |
|---|---|
| **truncate-and-rewrite in place** (`cat >`, Python `open(w)`) | the running script executed **`REPLACED-B` and `REPLACED-C` — lines that did not exist when it started.** Exit 0. |
| **atomic replace via rename** (`mv`) | unaffected; the process keeps its original inode |

**So the hazard is real and it is worse than "corrupt": exit 0, no error, no signal — it silently
ran different code than it started with.** Another null rendering as a positive.

The mitigation is not "know your editor's write strategy" — it is **`exec` from a snapshot copy**,
which `handoff-restructure.md` proposed and this confirms. Recorded as the answer to #9's open
question.

### What shipped

- **`driver/gate.py`** — stdlib-only, importable. `extract_gate`, `gate_field`, `gate_fields`,
  `ci_sha`, `classify`, `tier_of`, `tier_batch`, `budget_reclass`, plus a CLI
  (`classify` / `tier` / `tier-batch` / `budget-reclass`) emitting normalised JSON.
- **`driver/test_gate.py`** — 45 pytest cases that **import** the module. Defines no parsing logic.
- **The driver** calls `classify_pr_body` (one `python3` invocation) and `tier-batch` for selection.
  Plain `python3`, never `uv`, so the GHA-portability claim in its header stays true.
- **`test-driver.sh`** — all replicas deleted; its helpers now shell out to the same CLI the driver
  uses. 47 → **49 assertions**, 0 failed.
- **`pyproject.toml` + `uv.lock`**, dev-group pytest. Runtime `dependencies = []`.
- **`make gate-test`**, a `driver-test` prerequisite. `make` stays the operator interface.

### I created a second divergence mid-refactor, and a test caught it

Removing `TIER_JQ` from `test-driver.sh` while leaving it in the driver would have left **two tier
implementations** — the exact defect being fixed, reintroduced one field over. Caught by the bash
assertion `no marker -> not a candidate at all` failing. Fixed by adding `tier-batch` to `gate.py`
and deleting `TIER_JQ` from the driver entirely.

Worth noting *why* it was caught: that assertion encoded a distinction I would have flattened —
**a marker-less issue is *dropped* by selection, which is not the same as `missing`** (specced but
carrying no `## Tier:` line, a real defect worth reporting). `tier_batch` preserves both.

### Two source-greps converted to real tests

`grep -q '<literal>' "$DRIVER"` — *"a spelling check, not a test"* per `findings.md` — replaced with
behavioural assertions through the parser CLI. Net effect on the eight such assertions: **two down,
six remain.**

### The mutation test is the evidence the work mattered

Narrowing `gate.py`'s ci-sha regex `{7,40}` → `{40}`:

```
pytest:  6 failed, 39 passed
bash:    44 passed, 5 failed
```

**Before this change, the same mutation to the driver's regex left `driver-test` entirely green.**
That was the defect. Restored: 45 pytest / 49 bash, 0 failed.

### The amendment path fired, on my own frozen check

C3 asserted "exactly one implementation site" but checked it with `grep -rl`, which cannot tell an
implementation from a mention — so after the extraction it failed on **a comment** and on **test
expected-values** while zero code sites outside `gate.py` produced a verdict. **Inert-content false
positive, third instance in this project**, written hours after re-reading the warning about it.

Stopped rather than edited, stated the case, Les confirmed. **Classified an amendment, not a
clarification** — the both-trees table is in `checks.md` A1. The intuitive read ("the check never
matched its intent") is the same reasoning #668 used to publish `amendments: none`, and it is a
story always available to whoever wrote the check. Cost was zero here, which is exactly why it was
the right case to honour the policy on rather than carve its first exception.

The amended check was itself mutation-tested: a simulated code-level producer is caught, a
comment-only mention is ignored.

## Step 7 — prior-art leads 1-3, fetched (2026-07-28)

`prior-art.md` labelled these **unverified model recall, never fetched**. Fetched primary sources.
**Two of the three recorded claims did not survive.** Lead 4 (PIT/Stryker) left unfetched — ranked
lowest value, and the practice is already habitual here.

### Lead 1 — the hoped-for payoff is not there

Mechanism **confirmed**: SLSA provenance binds via in-toto `subject` + `digest`
(`sha256`/`sha512`/`gitCommit`); threat (F) requires *"the provenance's `subject` matches the hash of
the package."*

The valuable half is **refuted.** The lead asked whether their threat model already enumerates the
substitution/staleness failures we keep finding one run at a time. Checked the provenance spec **and**
the dedicated threats page: **attestation-applied-to-the-wrong-artifact is not modelled, staleness is
not covered, and adjacent-evidence satisfaction is not a threat entry.** The model is
build-artifact-centric; ours is a verification-time problem, and the standards hand it to "the
consumer."

**So we are not behind a literature here** — #2's sweep must enumerate its own. What *does* transfer
is the shape, and it produced a new candidate instance: **`project-gates` records a local
`make check` and names no commit at all** — an unbound claim of exactly the form the `ci` row used to
be.

### Lead 2 — promptfoo fits, and its default would have destroyed the study

`--repeat <number>` gives reps; multiple `prompts:` give control-vs-treatment; `-o` exports
`jsonl`/`json`/`csv` so **per-rep raw outputs survive for hand-reading** — the one thing move 5 could
not do without. Plausibly replaces the hand-rolled harness.

**But promptfoo caches LLM responses by default.** `--repeat 15` without `--no-cache` returns
identical cached results, so a study whose metric **is variance** would report zero variance with
every arm looking perfectly consistent. The instrument's default silently destroys the measurement
while appearing to work — "a null must never render as a positive," one level up. Also
`PROMPTFOO_STRIP_RESPONSE_OUTPUT` discards model outputs, a second way to lose the thing that must be
read. *Documented, not run — verify empirically before adopting.*

**DSPy refuted as the wrong instrument.** It optimises prompts toward an aggregate metric until
quality converges (0.41 → 0.63 F1). A tally-only reading of move 5 would have concluded the opposite
of the truth, so a tool that reports convergence is the wrong shape for this project's question.

### Lead 3 — confirmed, and it sharpens our own design

**The most transferable line in the whole survey:** *"Renovate only automerges branches which are
up-to-date and green."* Up-to-date is our `ci-stale` guard — but they make it a **precondition of
automerging** rather than a post-hoc check on a verdict already published. Our gate derives the
verdict and *then* asks whether the commit still ships. Theirs cannot reach the question.

`minimumReleaseAge` is a deliberate wait-before-acting as *policy* rather than a poll — compare move
4c, where "wait for CI to settle" had to become `gh pr checks --watch` because every polling
mechanism was denied.

**Partly refuted:** no pre-approved-low-risk-category exists; Renovate scopes automerge via
`packageRules` on the change's *nature*, not a durable per-item label.

**ITIL sharpens a real weakness in our tiering.** A standard change is pre-authorized on three
conditions *together*: documented procedure, risk formally accepted in advance, and **prior runs have
proven the outcome predictable** — and the governance body pre-approves the **template, not the
instance**. Our `auto-ok` is stamped **per issue** on its own criteria. We have no notion of *"this
class of change is safe because N instances landed cleanly."*

That is the answer to the phase-3 open decision's actual question: ITIL's *when may this be
automatic* is **evidence-based and finite**, which is exactly what a gate list growing by one per
session lacks. Both this and Renovate's ordering point are now recorded in `design.md`'s roadmap.
