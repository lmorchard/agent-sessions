# Frozen acceptance checks

**Source:** https://github.com/lmorchard/agent-sessions/issues/11
**Frozen at:** `6f18f87` (2026-07-29)
**Check files — read-only from Phase 1 onward:**
- `driver/test-driver.sh`

This is the **work must edit its own oracle** case from `references/frozen-checks.md`: the
criterion's check IS a case in `driver/test-driver.sh`, and the fix lives in
`driver/agent-session-driver.sh`. Those two files are disjoint, so the read-only rule applies
cleanly to the check file — Phase 1 edits the driver only. The scoped tamper invariant is stated
under **Tamper rule** below because Phase 0 must itself add a case to the frozen file.

## C1

CRITERION: IF `--repo-path` resolves to `/` and `--skill-dir` is an absolute path beneath it, THEN
the driver SHALL emit the nested-`--skill-dir` containment warning, and SHALL NOT proceed past
validation to the required-command loop.
CHECK: a new case in `driver/test-driver.sh` invoking the driver with `--repo-path /` and an
absolute `--skill-dir`, asserting that output **contains** `--skill-dir is inside --repo-path` and
**does not contain** `required command not found: gh`.

Realised as, in `driver/test-driver.sh`:

```
check "--repo-path / is containment, not a wildcard" "warned stopped-early" "$(_nest_verdict)"
```

`_nest_verdict` is the existing harness reduction and it asserts exactly the criterion's two
halves, derived from the real stderr by literal substring match:
`_nest_warned` → `warned` iff the output contains `--skill-dir is inside --repo-path`;
`_nest_reached` → `stopped-early` iff it does **not** contain `required command not found: gh`.

Run it by name: `make driver-test`, and read the line
`--repo-path / is containment, not a wildcard`.

AT FREEZE: **fails**, observed verbatim:

```
  FAIL  --repo-path / is containment, not a wildcard
     expected: warned stopped-early
     actual:   no-warn gh-check
```

Suite reports `64 passed, 1 failed` — against the unmodified tree's `64 passed, 0 failed`, so the
new case was collected (total 64 → 65) and it is the **only** failure. Correct reason: the
behaviour is genuinely absent. `pwd -P` in the root directory
returns `/`, the only path already ending in a slash, so `"$repo_real"/*` at
`agent-session-driver.sh:158` expands to the pattern `//*`, which matches no ordinary absolute
path — every path reads as outside `/` and the guard goes silent. Not a setup error: the
*control* below fires the warning through the same harness on the same run.

**Discrimination, and the trap the spec named.** `rc` is `2` on both branches, so an exit-code
assertion would not discriminate — only the message and the stop-point do, which is what
`_nest_verdict` pairs. The cheapest way to make this green is normalising `repo_real`; **deleting
the `case` block instead would fail the three false-positive guards and the four existing
containment cases**, so that shortcut is closed by G2/G3 rather than by good intentions.

## Guards

(Pass today; must keep passing. Not criteria — they can't fail at freeze.)

- **G1:** `make driver-check` — the driver still has no executable merge path.
  Passed at freeze: `driver-check: no executable merge path in driver/agent-session-driver.sh`,
  exit 0.
- **G2:** the three false-positive nest cases still report `no-warn gh-check` — `a sibling
  directory is not containment`, `an unrelated checkout is not containment`, `a string prefix that
  is not a path prefix is not containment`. **This is the guard the fix most plausibly breaks:**
  any normalisation of `repo_real` risks reopening the `/a/b`-vs-`/a/bc` string-prefix hole, and a
  containment check that refuses ordinary layouts trains the operator to reach for
  `--allow-nested-skill-dir` by reflex. Passed at freeze, all three.
  *(The issue recorded the `/a/bc` case as **UNRUN**, needing a `mkdir`. It is in the suite now —
  `test-driver.sh:521-527`, landed by #18 — and it ran green at freeze. So all three of G2 are
  observed, not two observed and one asserted.)*
- **G3:** `make driver-test` loses no test and gains no newly-failing or newly-skipped one. Stated
  as an invariant, not a pinned count, per `findings.md` defect class 3. Passed at freeze:
  `64 passed, 0 failed` on the unmodified tree, and `make check` green end to end
  (`driver-check`, `driver-test`, `gate-test`, `park-test`, `skill-readonly`, `docs-check`).
  *(The issue recorded this as **UNRUN** — the triage scan ran under a no-full-suites cap. It has
  now been run.)*

## Tamper rule

Phase 0 adds a case to `driver/test-driver.sh`, which is also the frozen check file, so a
whole-file diff cannot be the invariant. Scoped, as an invariant over what the checks *assert* —
not as a whitelist of allowed line forms:

> No line in the diff of `driver/test-driver.sh` after the freeze commit may change what any
> frozen check asserts — no `check` expectation string, no `_nest_*` helper body, no assertion
> deleted, skipped or narrowed. Sanctioned from Phase 1 onward: **nothing.** The file is
> read-only to the implementer; the only edit it ever receives is the freeze commit's own.

Paired behavioural guard: G3 (the suite still runs every case and passes), which is what actually
catches a weakened oracle — a deleted assertion drops the count.

## Amendments

(Append-only. **Empty** — no check was amended or clarified, so the tier takes no downgrade from
this section.)

## Tamper verdict — recorded pre-squash

Run before `git reset --soft origin/main` collapsed the freeze commit, because afterwards `6f18f87`
is a dangling local object: not an ancestor of the branch, absent from `origin`, so nobody can
re-run the command. **This record is the evidence.**

```
$ git diff 6f18f87 -- driver/test-driver.sh
(no output)
```

**Verdict: `clean`** — and genuinely `clean`, not `clean-by-substitute`. `Check files` is non-empty
(`driver/test-driver.sh`), so a real file diff ran and returned empty; the substitutes from
`frozen-checks.md`'s "When the criteria are commands, not test files" do not apply here.

`git diff 6f18f87 --stat` lists three files: `driver/agent-session-driver.sh` (the fix), this
`checks.md` (sanctioned appends only — the `Frozen at` sha and this section), and `plan.md` (a
session artifact written after the freeze). No test file, and no file no phase named.

The scoped **Tamper rule** above holds literally: the diff of the frozen file is zero lines, so no
line changes what any check asserts, and the file received no edit after the freeze commit.

## Independent verifier — report summary

Dispatched as read-only `Explore` (structurally cannot edit what it grades), given this manifest and
the repo, not the plan or the rationale.

| Row | Verdict | Evidence the verifier ran |
|---|---|---|
| C1 | **pass** | `ok    --repo-path / is containment, not a wildcard` |
| G1 | **pass** | `driver-check: no executable merge path in driver/agent-session-driver.sh`, exit 0 |
| G2 | **pass** | all three false-positive lines `ok`, expectation `no-warn gh-check` |
| G3 | **pass** | `65 passed, 0 failed`; 65 collected against the freeze tree's 65 collected / 1 failing — nothing lost, nothing newly failing |
| Project gates | **pass** | `all checks passed` |
| Tamper | **clean** | empty diff, as recorded above |

It also confirmed, on its own inspection rather than on this manifest's word:

- **C1 cannot be satisfied without the work.** The warning literal exists at exactly one site in
  the driver, inside the `case` arm, so `warned` requires the real guard to fire.
- **C1 discriminates.** `_nest_reached` alone is vacuously satisfiable by any early death, but
  `_nest_verdict` requires `warned` *and* `stopped-early` together, which no setup failure produces.
- **G2 passes for reasons adjacent to the concern it names.** See the finding below — this is the
  verifier catching its author, and it is recorded rather than resolved.

## Findings surfaced, not fixed — for follow-up

Recorded here because `driver/test-driver.sh` is read-only from Phase 1 and none of these is in
C1's scope. Fixing any of them in this run would mean the implementer widening its own oracle.

1. **G2's three cases are adjacent evidence** (`findings.md` defect class 1, applied to this run's
   own guards). All three use ordinary paths, so **none of them enters the branch the fix added**;
   they re-confirm a property of code that did not change. They would still catch a fix that
   normalised `repo_real` *generally*, which is the hole that mattered — but they are blind to any
   defect confined to the `= "/"` branch itself.
2. **A residual the fix does not close:** on a system where `pwd -P` yields `//` (POSIX permits a
   pathname beginning with exactly two slashes to be implementation-defined), `repo_prefix` stays
   `//`, the pattern is `///*`, and the original silent-guard bug is intact. Same near-nil
   reachability class as the bug C1 fixes. No case covers it and this manifest asserts nothing
   about it.
3. **`CLAUDE.md:62` cites `agent-session-driver.sh:485` and `:616` for `classify_pr_body`.** Stale
   *before* this branch — on `origin/main` the calls are at `632` and `756` (definition at `443`).
   This change shifts them a further 12 lines, to `644` and `768`. Not caused here, and `CLAUDE.md`
   is not on the drivable allowlist, so a fix belongs to a human or a listed path.
4. **The new case's comment cites `agent-session-driver.sh:158`**, which is where the pattern was
   *at the freeze tree* — the sentence is past-tense and accurate as history, but a reader at `HEAD`
   finds a comment line there. Not edited, because the file is frozen for this run and a comment
   changes no assertion (so it is neither an amendment nor a clarification).
