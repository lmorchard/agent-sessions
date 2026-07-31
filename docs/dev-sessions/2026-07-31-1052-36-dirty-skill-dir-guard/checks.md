# Frozen acceptance checks

**Source:** https://github.com/lmorchard/agent-sessions/issues/36
**Frozen at:** `1bd50f030f446c9abd7d486d68caf7410fc8c363` (2026-07-31)
**Check files — read-only from Phase 1 onward:**
- `driver/test-driver.sh`

Criteria and checks are copied verbatim from the issue. Implementation touches
`driver/agent-session-driver.sh` only.

## C1

CRITERION: WHEN `--skill-dir` resolves inside a git working tree that has uncommitted changes to
tracked files under that directory, THEN the driver SHALL refuse to start, naming the modified
paths, and SHALL NOT reach the required-command loop.

CHECK: a new case in `driver/test-driver.sh` following the constructed-`PATH` nest pattern — build
a scratch git repo containing `skills/agent-session/phases/express.md`, commit it, dirty it, invoke
the driver against it, and assert stderr names the modified path and does **not** contain
`required command not found: gh`.

AT FREEZE: **fails**, in both arms, for the behavioural reason — the driver reached the loop the
criterion forbids and said nothing about the dirty tree.

| case | expected | observed | raw stderr |
|---|---|---|---|
| `#36 C1 an uncommitted edit under --skill-dir refuses, naming the path` | `named stopped-early` | `unnamed gh-check` | `error: required command not found: gh` (rc=2) |
| `#36 C1 a staged-but-uncommitted edit is dirty too` | `named stopped-early` | `unnamed gh-check` | `error: required command not found: gh` (rc=2) |

Not a setup artifact, on four grounds: (a) stderr is *only* the required-command message, so the
driver got past `--skill-dir` exists, `--repo-path` exists, `phases/express.md` present, and the
containment check; (b) the observed token is `unnamed`, not `missing-fixture` — the reducer has a
dedicated arm for the driver's pre-existing `no phases/express.md under <dir>` message, which also
contains `phases/express.md`, so a fixture that failed to write the file could not have produced a
false `named`; (c) `_nest_require_dirt` preconditions assert each fixture is actually dirty before
the driver is invoked, and the suite aborts otherwise; (d) C2 is the same fixture builder with the
edit committed and it reaches `gh-check`, so `git init`/commit and the layout are sound.

Two reducer probes (`probe: a refusal naming the path reduces to the token C1 expects` and its
negative arm) feed a synthetic stderr to the reducer to establish that C1's expected token is
*producible at all* — an expectation nothing could satisfy is a permanent red, not a check. They
assert nothing about the driver, and the wording they use is invented and never matched against it.

## C2

CRITERION: WHEN the skill directory is clean, THEN the driver SHALL proceed exactly as it does today.

CHECK: the same case with the edit committed rather than left dirty, asserting the run reaches
the required-command loop as before.

AT FREEZE: expected to **pass** at freeze, deliberately. This is the positive control, not a
discriminating criterion — the issue says so in those words: *"the cheapest way to green C1 is to
refuse always, and a criterion whose degenerate satisfaction bricks the driver needs its opposite
asserted in the same node."* Its passing at freeze is therefore **not** the
`frozen-checks.md` "a criterion's check passes at freeze → surface it, don't proceed" signal;
that signal is about a criterion whose behaviour unexpectedly already exists. Recorded here so a
later reader does not mistake a predicted pass for a stale issue.

## Guards

(Pass today; must keep passing. Not criteria — they can't fail at freeze.)

- **G1:** `bash driver/test-driver.sh` — the nine existing nested-`--skill-dir` cases still report
  their current verdicts; no assertion lost, newly skipped, or newly failing. Passed at freeze:
  before the freeze `make driver-test` reported 88 passed / 0 failed; after it, 94 passed / 2 failed,
  where 94 = the same 88 plus 6 new passers and the 2 failures are C1's arms. No pre-existing
  assertion was weakened, deleted, or skipped.

  **Freeze-time change to the harness, disclosed because it is an edit to a check file.** Four
  existing cases (`--allow-nested-skill-dir proceeds past validation` + its `and warns on the way
  through`, `a sibling directory is not containment`, `an unrelated checkout is not containment`,
  `an ambient gh cannot reach the driver` + its `and no state dir is created`) pointed
  `--skill-dir` at *this repo's* `skills/agent-session` **and** expected to reach the
  required-command loop. Under C1 their stop-point would become a property of whether the
  developer's working tree happens to carry uncommitted skill edits — the same host-dependence the
  section's constructed `PATH` exists to remove, one input over. They now run against a clean,
  committed scratch repo laid out like the real one (with its own `driver/`, so the sibling case
  keeps a genuine sibling). Labels and expected verdicts are unchanged; only the directory is
  constructed. The cases that die *at* the containment check keep the real `$NEST_SKILL`.

  **This imposes an ordering constraint on the implementation:** the cleanliness check must run
  **after** the containment check. If it ran first, a dirty real working tree would flip
  `nested --skill-dir warns with the literal message` and its three siblings from `warned` to
  `no-warn` — reintroducing exactly the host-dependence above. Flagged by the check author as
  unconstrained by the criteria; resolved here, before implementation, rather than discovered by it.
- **G2:** `--dry-run` and `--classify-only` are unaffected — both skip the skill-dir validation
  block entirely (guarded on `DRY_RUN -eq 0` and an empty `CLASSIFY_ONLY`) and neither requires
  `--skill-dir`. Covered by the existing suite's dry-run and classify-only cases. Passed at freeze.
- **G3:** a skill directory **not inside a git repository at all** still proceeds past validation.
  A `git status` that errors must not be read as "dirty" — a null must never render as a positive
  (`docs/findings.md` defect class 2). Asserted by `#36 G3 a skill dir outside any git repo still
  proceeds` in `driver/test-driver.sh`. Passed at freeze.

Two further assertions land in the same section and pin the criteria's stated scope. Both passed at
freeze, and both would be broken by the obvious one-line implementation (refuse on any
`git status --porcelain` output):

- `#36 an untracked file under the skill dir is not dirt` — a stray scratch file changes nothing
  about what the run is told to do, and porcelain reports it anyway with `??`.
- `#36 a repo dirty outside the skill dir still proceeds` — the scope is tracked files *under*
  `SKILL_DIR`; a whole-repo test would refuse nearly every real invocation of this driver.
- **G4:** `make driver-check` — the driver still has no executable merge path. Passed at freeze.

## Amendments

(Append-only. Empty unless an amendment was made.)

_None._

## Tamper verdict

**`clean`** — not `clean-by-substitute`: `Check files` is non-empty, so the real mechanism ran.

`git diff 1bd50f030f446c9abd7d486d68caf7410fc8c363 -- driver/test-driver.sh` → **empty**, taken by
the independent verifier at the end of execute and re-run in `pr` before pushing. The branch is not
squashed, so `1bd50f0` is an ancestor of the pushed head and a reviewer can re-run this command
rather than taking the verdict on trust.

`git diff <freeze-sha> --stat` lists only `checks.md` (the sanctioned `Frozen at` sha line, plus
this section), `plan.md` (new), and `driver/agent-session-driver.sh` (the implementation). No
collateral edit to any file no phase named.

The rebase in `pr` step 1 was a **no-op** — the branch was already atop `origin/main` at `c46c8e2`
— so the freeze sha needed no re-anchoring and this verdict was never taken against a rewritten
commit.

## Post-verification note — an uncovered state, recorded not fixed

The independent verifier's adversarial probe found one state the frozen checks do not cover: a skill
dir that **is** in a repo and **is** dirty, but whose `git status` fails for a reason other than
not-being-a-repo (probe: `chmod 000 .git/index` → exit 128, empty stdout). The driver proceeds.

This is the behaviour the issue specifies — G3 says *"a `git status` that errors must not be read as
'dirty'"* — so it is **not** an amendment, not a failing check, and not a check that mis-states its
criterion. It is a residual risk, now named in a comment at the code as well as here. Narrowing it
would mean deciding what "inside a repo" means without being able to ask git, and getting that wrong
refuses every legitimate non-checkout skill dir. A candidate follow-up, for a human to file if it is
judged worth closing.
