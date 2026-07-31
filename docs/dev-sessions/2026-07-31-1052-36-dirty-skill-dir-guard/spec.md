# Driver: refuse to run against a skill directory with uncommitted changes

_Captured verbatim from https://github.com/lmorchard/agent-sessions/issues/36 (marker line stripped)._

**Goal:** stop an unattended run from silently taking its instructions from uncommitted,
unreviewed edits to the skill.

**Source:** the run on #23, 2026-07-30. It reached Phase 0, found `phases/express.md`, `phases/pr.md`
and `references/frozen-checks.md` **modified but uncommitted** in the checkout it was pointed at —
work in progress for #29 — and **parked rather than guess** which version governed. Cost $1.20, zero
writes. It was right to stop, and nothing in the system helped it.

## Why this matters more than an ordinary precondition

The divergence was not cosmetic. Committed `pr.md` said *"Squash and open"*; the working tree said
*"Push and open"*. That decides whether the freeze commit survives to the gate, and therefore whether
the gate's `tamper` row is a re-runnable command or a self-report. **An unattended run would have
adopted unreviewed skill edits as normative** — and `CLAUDE.md` gates `skills/**` precisely because
*"the implementer's work product is the instructions grading it."*

`docs/findings.md` already carries the class one level down: *"'I ran the checks' is a claim about a
tree, and the tree you ran them on is not necessarily the one you pushed."* This is the same defect
applied to the **instructions** rather than the code.

## Current state — verified, not assumed

- **The driver performs no git check on `SKILL_DIR`.** `grep -nE 'SKILL_DIR' driver/agent-session-driver.sh`
  filtered for `git|status|dirty|clean` returns nothing. It validates that the directory exists, that
  `phases/express.md` is inside it, and that it is not nested inside `--repo-path` — nothing about
  its version-control state.
- **The skill states no clean-tree precondition anywhere.** `grep -rniE 'clean tree|working tree|uncommitted|dirty' skills/agent-session/`
  returns three unrelated hits (`pr.md:182`, `pr-body-template.md:64`, `execute.md:61`) and no rule.
- **Demonstrated live.** A scratch git repo with a committed `phases/express.md`, then dirtied:

  ```
  skill dir is dirty:
     M skills/agent-session/phases/express.md
  $ driver --skill-dir <that dir> --repo-path <clean dir> ...
  error: required command not found: gh
  ```

  Reaching the required-command loop means it sailed past validation with the dirty skill dir
  unremarked. (Run on a hermetic `PATH` with no `gh`, so it stops there rather than proceeding.)

## The fix is a mechanism, not a rule

The run's report framed the gap as two things — no clean-tree precondition, and no rule about whether
committed or working-tree instructions govern. **The second question disappears if the first is
answered mechanically:** a driver that refuses to start against a modified skill directory leaves no
ambiguity to resolve, so no wording is needed and none should be added. `docs/findings.md` is 3-for-3
on added rules measuring away, and consistently better served by detectors.

## Verifiable acceptance criteria

- **C1.** WHEN `--skill-dir` resolves inside a git working tree that has uncommitted changes to
  tracked files under that directory, THEN the driver SHALL refuse to start, naming the modified
  paths, and SHALL NOT reach the required-command loop.
  **CHECK:** a new case in `driver/test-driver.sh` following the constructed-`PATH` nest pattern — build
  a scratch git repo containing `skills/agent-session/phases/express.md`, commit it, dirty it, invoke
  the driver against it, and assert stderr names the modified path and does **not** contain
  `required command not found: gh`.
  **VERIFIED DISCRIMINATING:** yes, ran it. Today that exact setup prints `error: required command not
  found: gh` and nothing about the dirty skill dir — so the driver reached the required-command loop,
  which is the state the criterion forbids.

- **C2.** WHEN the skill directory is clean, THEN the driver SHALL proceed exactly as it does today.
  **CHECK:** the same case with the edit committed rather than left dirty, asserting the run reaches
  the required-command loop as before.
  **VERIFIED DISCRIMINATING:** no — **this is the positive control and it passes today**, deliberately.
  It is here because the cheapest way to green C1 is to refuse *always*, and a criterion whose degenerate
  satisfaction bricks the driver needs its opposite asserted in the same node.

## Regression guards

- **G1.** The nine existing nested-`--skill-dir` cases still report their current verdicts — the new
  check runs in the same validation block and must not perturb them.
  **CHECK:** `bash driver/test-driver.sh`; invariant, no assertion lost, newly skipped or newly failing.
  Passes today.
- **G2.** `--dry-run` and `--classify-only` are unaffected. Both skip the skill-dir validation block
  entirely (it is guarded on `DRY_RUN -eq 0` and an empty `CLASSIFY_ONLY`), and neither requires
  `--skill-dir` at all, so neither should acquire a new failure mode. Passes today.
- **G3.** A skill directory that is **not** inside a git repository at all still works. A `git status`
  that errors must not be read as "dirty" — *a null must never render as a positive*, which is
  `docs/findings.md` defect class 2 and the single most likely way to get this wrong.
- **G4.** `make driver-check` — the driver still has no executable merge path. Passes today.

## Tier: `auto-ok`

**Trigger 1 does not fire.** C1's oracle exists (`driver/test-driver.sh` plus the constructed-`PATH`
pattern), it fails today, and its cheapest honest green is the work. The degenerate green — refuse
always — is closed by C2.

**Trigger 2 does not fire.** The work lands in `driver/agent-session-driver.sh` and
`driver/test-driver.sh`, both on `CLAUDE.md`'s drivable allowlist. It does **not** touch `skills/**`,
which is the point: the fix is a driver precondition, not skill wording. Not `driver/gate.py` either.

## Design decisions

- **Decision:** refuse, do not warn-and-continue.
  - **Why:** a warning in an unattended run is read by nobody until after the money is spent, and the
    failure it guards against — instructions silently differing from the reviewed ones — produces
    output that looks entirely normal. The run that found this stopped voluntarily; the driver should
    not depend on that judgment being made again.
  - **Rejected:** warn-only; and an `--allow-dirty-skill-dir` escape hatch, which can be added later if
    it is ever actually wanted. Adding it now would be the first thing reached for by reflex, which is
    the same trap `--allow-nested-skill-dir`'s false-positive guards exist to prevent.

- **Decision:** scope the check to tracked files **under `SKILL_DIR`**, not to the whole repo.
  - **Why:** the driver is routinely pointed at this repo while other work is in flight elsewhere in
    the tree — every run in this session had a dirty `docs/` or `.driver-state/` at some point. A
    whole-repo cleanliness check would refuse constantly and be disabled within a day.
  - **Rejected:** whole-repo `git status --porcelain`.

- **Decision:** add no rule to the skill about version authority.
  - **Why:** the mechanism removes the question. See "The fix is a mechanism, not a rule".

## What we're NOT doing

- **Adding skill wording** about which tree governs. The refusal makes it moot, and `skills/**` is
  gated anyway.
- **Checking `--repo-path`'s cleanliness.** Different question, and a dirty target tree is normal
  mid-session. Only the *instructions* need this guarantee.
- **Untracked files under the skill dir.** A stray untracked file does not change what a run is told
  to do. Modified tracked files do. Narrower is better here; widen only with evidence.

## Open questions

- **Should staged-but-uncommitted changes count as dirty?** **Default: yes** — staged is still not
  committed, and not reviewed.
- **What if `SKILL_DIR` is not in a git repo?** **Default: proceed silently.** See G3; this is the
  null-as-positive trap and the guard exists for it.
