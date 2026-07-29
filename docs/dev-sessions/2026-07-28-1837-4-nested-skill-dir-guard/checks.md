# Frozen acceptance checks

**Source:** https://github.com/lmorchard/agent-sessions/issues/4
**Frozen at:** `207ead9` (2026-07-28)
**Check files — read-only from Phase 1 onward:**
- `driver/test-driver.sh`

The criteria are command-shaped in the issue (direct driver invocations), but they are frozen
here as **named cases inside `driver/test-driver.sh`**, so `Check files` is non-empty and the
ordinary `git diff <freeze-sha> -- driver/test-driver.sh` tamper check applies. Two reasons:

1. The hosted run's tool allowlist has no `Bash(bash:*)`, so an ad-hoc `bash driver/…` invocation
   is not runnable here at all. `make` is allowlisted; `make driver-test` runs the suite.
2. The spec's own implementation notes anticipated this ("These cases would be the first of their
   kind" in `test-driver.sh`).

Every case invokes the **shipped** `driver/agent-session-driver.sh` as a subprocess with
`PATH=/usr/bin:/bin` — hermetic: `gh` is not on that PATH (verified: `/usr/bin` has `jq`, `git`,
`python3`, and no `gh`), so the run cannot reach the network, cannot invoke `claude`, and dies at
the `for c in gh jq git` loop (`agent-session-driver.sh:111`) if it gets past validation.
`mkdir -p "$STATE_DIR/runs"` is at `:153`, after that loop, so no state dir is written either way.

**Exit code alone does not discriminate — both the guarded and unguarded paths exit 2.** Every
case therefore asserts the stderr *message*.

**Mutation-testability is structural.** The cases call the shipped driver, so deleting the guard
flips C1–C4 from pass to fail by construction. No separate meta-check is needed.

**Per-criterion check command.** `make driver-test`, then read the named case's line. A case that
reports `ok` passed; a case that reports `FAIL` prints expected vs. actual. A case name absent
from the output entirely is a **failed** check, not a passing one — that is this harness's
equivalent of pytest's exit-5 "collected nothing".

---

## C1
CRITERION: IF `--skill-dir` resolves inside `--repo-path` AND `--allow-nested-skill-dir` is
absent, THEN the driver SHALL warn with the literal `--skill-dir is inside --repo-path` and exit 2
without invoking `claude` or creating the state dir.
CHECK: `make driver-test` — cases `nested --skill-dir warns with the literal message`,
`  and exits 2`, and `  and does not create the state dir` all report `ok`.
AT FREEZE: **fails** — `nested --skill-dir warns with the literal message`: expected `warned`,
actual `no-warn`. Raw stderr: `error: required command not found: gh` (rc 2) — validation passed
cleanly and fell through to the required-command loop. Correct reason: the behavior is genuinely
absent, not a setup error.

> **Only the message assertion discriminates.** `  and exits 2` and `  and does not create the
> state dir` **pass today** (2, and `absent`), because the unguarded path also exits 2 at the `gh`
> check and `mkdir -p "$STATE_DIR/runs"` (`:153`) sits after it. The spec anticipated this in so
> many words — *"Exit code alone does not discriminate (both paths exit 2)"* — so they are recorded
> as regression locks inside C1, not as detectors, and not split out as guards: they are conjuncts
> of one SHALL. They become load-bearing if a future guard is ever placed after the mkdir.

## C2
CRITERION: IF the two paths resolve to the *same* directory, the driver SHALL behave identically
(the degenerate containment case).
CHECK: `make driver-test` — case `identical --skill-dir and --repo-path warn the same way`
reports `ok`.
AT FREEZE: **fails** — expected `warned`, actual `no-warn`. Raw stderr:
`error: required command not found: gh` (rc 2). Genuinely absent.

## C3
CRITERION: WHEN paths are given non-canonically (relative, or containing `.`/`..`), containment
SHALL still be detected — the comparison is on fully resolved paths, not raw argument strings.
CHECK: `make driver-test` — cases `relative paths still detect containment` and
`.. in the path still detects containment` both report `ok`. (Verbatim from the spec: both
`--skill-dir ./skills/agent-session --repo-path .` and
`--skill-dir "$PWD/driver/../skills/agent-session" --repo-path "$PWD"` produce the warning.)
AT FREEZE: **both fail** — each expected `warned`, actual `no-warn`. Raw stderr for both:
`error: required command not found: gh` (rc 2). Both forms satisfy the existing `-d` checks, so
the setup is valid; there is simply no comparison. Genuinely absent.

## C4
CRITERION: IF `--allow-nested-skill-dir` IS passed with a nested configuration, THEN the driver
SHALL proceed past validation (reaching the `gh` check), having emitted the warning.
CHECK: `make driver-test` — cases `--allow-nested-skill-dir proceeds past validation` and
`  and warns on the way through` both report `ok`.
AT FREEZE: **both fail** — `proceeds past validation`: expected `gh-check`, actual
`stopped-early`; `and warns on the way through`: expected `warned`, actual `no-warn`. Raw stderr
for both: `error: unknown argument: --allow-nested-skill-dir (try --help)` (rc 2). The flag
genuinely does not exist. Genuinely absent, not a setup error.

> **Stream:** "warn" is asserted as a literal substring of **stderr**. The driver writes every
> diagnostic to stderr (`log()`, `die()`), so this is the only reading consistent with the file;
> it is not a free choice. Any prefix or severity wording satisfies the assertion.

## Control (not a criterion — a discriminator probe)
`a missing --skill-dir still reports its own error` — `--skill-dir /nope` must still produce
`--skill-dir does not exist: /nope`. This is what proves the C1–C3 message assertions are real
discriminators rather than constants. Copied from the spec's triage table.

AT FREEZE: **passes** — observed `error: --skill-dir does not exist: /nope`. The same helper that
returns `no-warn` for C1 returns this distinct, correct message here, so the message assertions
are real discriminators.

## Guards
(Pass today; must keep passing. Not criteria — they can't fail at freeze.
**All five ran at freeze and passed** — G3 included, clearing its UNRUN mark from triage.)

- **G1:** `make driver-test` — case `a sibling directory is not containment`
  (`--skill-dir "$PWD/skills/agent-session" --repo-path "$PWD/driver"` proceeds).
- **G2:** `make driver-test` — case `an unrelated checkout is not containment`
  (`--repo-path "$HOME/devel/decafclaw"` proceeds).
- **G3:** `make driver-test` — case `a string prefix that is not a path prefix is not containment`
  (`/a/b` vs `/a/bc`). This is what catches a naive `[[ $SKILL_DIR == $REPO_PATH* ]]`.
  Marked UNRUN at triage; run at freeze.
- **G4:** `make driver-test` — `N passed, 0 failed` with N ≥ the pre-existing count.
  The spec says 47; the tree has moved (#9 landed) and the measured baseline on this branch is
  **49 passed / 0 failed**. The guard is "nothing lost", and 49 ≥ 47 satisfies it.
- **G5:** `make skill-readonly` passes.

## Amendments
(Append-only. Empty unless an amendment was made.)

**None.** No frozen check was edited, relaxed, skipped, or narrowed at any point. The tier is
therefore not downgraded and remains `auto-ok` as filed.

## Pre-squash tamper verdict — `clean`

Recorded here because `git reset --soft origin/main` collapses the freeze commit away and the
baseline stops being reachable from the branch. **This record is the evidence; the command is not
reproducible after the squash.**

Run at the tip of the unsquashed branch (`73c257f`+), after the rebase onto `origin/main`
(a no-op — `origin/main` had not moved, so the freeze sha needed no re-anchoring):

| Command | Result |
|---|---|
| `git cat-file -t 207ead9` | `commit` — the freeze sha resolves |
| `git merge-base --is-ancestor 207ead9 HEAD` | exit 0 — it is an ancestor of the branch |
| `git diff 207ead9 -- driver/test-driver.sh` | **empty** — the sole frozen check file is byte-identical to the freeze |
| `git diff 207ead9 --stat` | 4 files: `driver/agent-session-driver.sh` (the work), `docs/design.md` (roadmap item 5 → DONE), this `checks.md` (+1/−1), `plan.md` (new). No collateral edits, and no frozen check file. |

This is a real `clean`, not `clean-by-substitute`: `Check files` is non-empty, so the ordinary
whole-file diff ran and means something.

The one `checks.md` line change is `**Frozen at:** (recorded in the follow-up commit)` →
`**Frozen at:** 207ead9`, which `frozen-checks.md` names as a sanctioned append. No CRITERION line,
CHECK command, or guard command differs from the freeze version.

**Could the diff satisfy the checks without doing the work?** No — confirmed by the independent
verifier against the implementation, not asserted here. The warning is emitted only inside a `case`
arm whose pattern is data-dependent on two freshly resolved paths; there is no unconditional echo
and no test against the fixtures' literal paths. The negative path is real and G1/G2/G3 hit it,
each asserting the warning is **absent** *and* that the run reached the `gh` check.

## Freeze run — the whole-suite figure

`make driver-test` at the freeze commit: **55 passed, 6 failed** (`make: *** [driver-test] Error 1`).
49 pre-existing assertions, all still passing; 6 new passes (C1's two locks, the control, G1, G2,
G3); 6 new failures (C1's message, C2, C3a, C3b, C4a, C4b). Verified by re-running the suite in
this context, not taken from the check-author's report.

## Under-specifications recorded, not resolved

Surfaced by the check-author and left as written — none changes what a criterion asserts, so none
is an amendment or a clarification:

- **Symlink resolution is untested.** C3 names relative and `.`/`..` forms only. Whether
  containment should follow symlinks is unspecified; no case was written for it. Follow-up.
- **C2 is nominally a subset of C1** (a directory contains itself). Covered separately on purpose:
  a plain prefix test could pass C1 and fail C2, and an equality shortcut the reverse.

## Notes on the guards as written
- **G2 is host-specific** (`$HOME/devel/decafclaw`, which exists on this host; there is no CI in
  this repo today, so nothing else runs the suite). Kept **verbatim** rather than portability-fixed
  — swapping in a `mktemp -d` would be a clarification, and `frozen-checks.md` requires a human to
  adjudicate even a clarification. Recorded as a follow-up instead.
