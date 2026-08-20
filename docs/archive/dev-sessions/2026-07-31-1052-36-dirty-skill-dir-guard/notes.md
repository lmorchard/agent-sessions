# Session notes — #36 dirty-skill-dir refusal

Mode: `agent-session express`, unattended, invoked by the board-driver. Tier `auto-ok`, no
human stops implied by the tier's reason, and none needed.

## What shipped

`driver/agent-session-driver.sh` gains one block at the end of the existing skill-dir validation
section: `git status --porcelain --untracked-files=no -- .` run from the resolved skill dir, and a
refusal naming every modified path if it reports anything.

## Three decisions the criteria left open, and how they were closed

1. **Where the check goes.** Inside the `DRY_RUN`/`CLASSIFY_ONLY` guard (G2 requires those two to
   gain no failure mode), **after** the containment check, and therefore before the required-command
   loop (C1 requires that). The middle one is the interesting one — see below.

2. **What "dirty" means.** Tracked-file modifications under the skill dir. Staged counts; untracked
   does not; dirt elsewhere in the same repo does not. All three have their own assertion, because
   the obvious one-liner — refuse on any `git status --porcelain` output — gets two of them wrong.

3. **What an erroring `git status` means.** Proceed. The issue's G3 says so explicitly, and this is
   the null-must-not-render-as-a-positive case. It has a cost, recorded below.

## The coupling this change introduced, and what it cost

Adding the check made **four existing test cases host-dependent**. They pointed `--skill-dir` at this
repo's own `skills/agent-session` *and* expected to reach the required-command loop — so once a dirty
skill tree is a refusal, their stop-point became a property of whether the developer happens to have
uncommitted skill edits. That is precisely the failure mode the nest section's constructed `PATH`
exists to remove (`test-driver.sh` ~361–370: *"true on the authoring host, guaranteed nowhere"*), one
input over.

Fixed in the **freeze commit**, not after — a check file is read-only from Phase 1 onward, so this
had to happen before implementation or not at all. Those four now run against a clean committed
scratch fixture laid out like the real repo (with its own `driver/`, so the sibling case keeps a
genuine sibling). Labels and expected verdicts unchanged; only the directory is constructed. The
cases that die *at* containment keep the real skill dir, where realism is worth something.

That retention is what creates the **ordering constraint**: cleanliness must be checked after
containment, or a dirty real tree flips those cases from `warned` to `no-warn`. The check author
flagged the ordering as unconstrained by the criteria and declined to resolve it; it was resolved in
`checks.md` before implementation rather than discovered by it.

**Generalizable lesson:** a new precondition on an input that the test suite *itself* feeds from the
live repo will silently make that suite host-dependent. Adding the precondition and auditing the
suite's own inputs are one task, not two.

## Residual risk, named rather than gated away

A skill dir that is in a repo, is dirty, and whose `git status` fails for some *other* reason — an
unreadable `.git/index`, a corrupt repo, dubious ownership — **proceeds**. Found by the independent
verifier's adversarial probe (`chmod 000 .git/index`), not by the frozen checks, which do not cover
it.

This is the specified behaviour (G3), so it is not an amendment and not a failing check. Closing it
means deciding what "inside a repo" means without being able to ask git, and getting that wrong
refuses every legitimate non-checkout skill dir. Recorded in a comment at the code and in
`checks.md`; a candidate follow-up for a human to file.

## Operational consequence worth knowing before it surprises someone

`make run` and `make run-self` pass `--skill-dir $(SKILL)` where `SKILL :=
$(CURDIR)/skills/agent-session` (`Makefile:2`). **Both now refuse while this repo has uncommitted
tracked changes under `skills/`** — including `make run-self`, the dogfooding path. That is the
feature working: skill wording is `needs-review` human work, and a driver run launched mid-edit is
exactly what #36 exists to stop. No Makefile override was added; that would be the escape hatch the
spec explicitly declined.

## Verification summary

- Freeze `1bd50f0`: C1 failed both arms with `error: required command not found: gh` — the driver
  reaching the loop the criterion forbids. Behavioural, not a setup artifact (four grounds in
  `checks.md`).
- After implementation: `make driver-test` 96 passed / 0 failed; `make check` all green.
- Independent verifier (fresh context, `checks.md` + repo only): every criterion and guard `pass`,
  tamper diff empty, criteria faithful to the issue, and refuse-always closed by C2 — which
  exercises a real clean **git** tree, asserted by `_nest_require_clean`, not merely a non-repo
  directory.
- Verifier probes beyond the frozen checks: symlinked skill dir, relative `--skill-dir`, a *deleted*
  tracked file, and a linked `git worktree` all refuse correctly.
