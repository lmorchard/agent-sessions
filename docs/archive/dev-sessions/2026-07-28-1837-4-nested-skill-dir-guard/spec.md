# Spec — Driver: warn when `--skill-dir` is inside `--repo-path`, with an explicit override

**Source:** https://github.com/lmorchard/agent-sessions/issues/4
**Captured:** 2026-07-28 (issue body verbatim below, marker line stripped)

---

`driver/agent-session-driver.sh` validates that `--skill-dir` and `--repo-path` both exist, and
that `--skill-dir` contains `phases/express.md`. It does **not** check whether `--repo-path`
contains `--skill-dir`.

That configuration is precisely the self-modification case: the hosted run's work product would be
the instructions grading it, which is the single failure this whole system exists to prevent.
`make skill-readonly` denies `Edit`/`Write`/`NotebookEdit` on the skill dir, so the deny rule would
still fire — but the run would be trying to do the work it is forbidden to do, and would fail in a
confusing way rather than being refused up front.

Today it is reachable by typo. A startup check that refuses (or at minimum warns loudly) is small
and mechanical.

**Mutation-test it.** The guard is worthless unless removing it makes a named test fail — this
project has shipped three guards that could not fail, and the discipline is what caught a
non-discriminating test in move 5.


---

## Rescoped at triage (2026-07-27): refuse → warn, with an override

**The rationale in the text above is largely already satisfied, and an absolute refusal would do
real harm.** Two findings from the scan:

1. **The hazard named is already covered.** The driver builds its deny rules from `$SKILL_DIR`
   unconditionally (`:139`), so nesting does not weaken them — a run whose `--skill-dir` sits
   inside `--repo-path` still cannot write skill files. `make skill-readonly` is the guard; this
   check adds nothing to the write path.
2. **An absolute refusal forecloses the drivable half.** `SKILL := $(CURDIR)/skills/agent-session`,
   so pointing the driver at *this* repo — the `driver/`/`docs/`/`Makefile` work `CLAUDE.md`
   explicitly calls drivable — **is** the nested configuration. Refusing it outright would kill
   move 7's premise to prevent a hazard the deny rules already handle.

**New scope:** warn loudly, and require an explicit `--allow-nested-skill-dir` to proceed. The
residual value is fail-fast on a *typo* (a mistyped `--skill-dir` that silently makes the deny
rules cover paths the run needs), not prevention of a configuration that is sometimes correct.

## Acceptance criteria

Checks run with `PATH=/usr/bin:/bin` to hide `gh`, so the invocation is hermetic — no network, no
state-dir write, no `claude`. **Exit code alone does not discriminate (both paths exit 2), so every
check asserts the stderr message.** All invoke the *shipped* driver, so deleting the guard flips
them from pass to fail by construction — that is the mutation-testability, structural rather than
a separate meta-check.

- **C1.** IF `--skill-dir` resolves inside `--repo-path` AND `--allow-nested-skill-dir` is absent,
  THEN the driver SHALL warn with the literal `--skill-dir is inside --repo-path` and exit 2
  without invoking `claude` or creating the state dir.
- **C2.** IF the two paths resolve to the *same* directory, the driver SHALL behave identically
  (the degenerate containment case).
- **C3.** WHEN paths are given non-canonically (relative, or containing `.`/`..`), containment
  SHALL still be detected — the comparison is on fully resolved paths, not raw argument strings.
  **CHECK:** both `--skill-dir ./skills/agent-session --repo-path .` and
  `--skill-dir "$PWD/driver/../skills/agent-session" --repo-path "$PWD"` produce the warning.
- **C4.** IF `--allow-nested-skill-dir` IS passed with a nested configuration, THEN the driver
  SHALL proceed past validation (reaching the `gh` check), having emitted the warning.

## Guards

- **G1.** Siblings are not read as containment: `--skill-dir "$PWD/skills/agent-session"
  --repo-path "$PWD/driver"` proceeds.
- **G2.** An unrelated checkout proceeds: `--repo-path "$HOME/devel/decafclaw"`.
- **G3.** A *string* prefix that is not a *path* prefix proceeds (`/a/b` vs `/a/bc`) — this is what
  catches a naive `[[ $SKILL_DIR == $REPO_PATH* ]]`.
- **G4.** `bash driver/test-driver.sh` — 47 passed / 0 failed today; nothing lost.
- **G5.** `make skill-readonly` still passes.

## Checks as observed at triage (run, not inferred)

| Check | Result today |
|---|---|
| C1 nested | **FAILS** — proceeds to `error: required command not found: gh`, exit 2. No refusal exists. |
| C2 equal | **FAILS** — same. |
| C3 relative and `..` | **FAILS** — both. |
| *control* | `--skill-dir /nope` → `error: --skill-dir does not exist: /nope`. Confirms the message assertion is a real discriminator, not a constant. |
| G1, G2 | **PASS** — both proceed today. |
| G4 | **PASSES** — 47 passed, 0 failed. |
| G5 | **PASSES.** |
| G3 | UNRUN — needs two directories created; scanner was read-only. Run at freeze. |

## Tier: `auto-ok`

**The only `auto-ok` on this board.** Trigger 1 does not fire: every criterion is a direct
invocation of the shipped driver asserting a specific stderr string; the oracle is bash plus the
driver, both present now; and the cheapest way to green them is to write the guard — there is no
keyword-grep or test-existence proxy in the set. Trigger 2 does not fire: the diff lands in
`driver/`, which `CLAUDE.md` names drivable.

**Flagged for the record rather than inherited silently:** trigger 2's generic default
*"deploy/infra/CI config"* would arguably catch any driver script. This project has configured
trigger 2 explicitly to `skills/**`, and the configuration overrides the default.

## Implementation notes

- The validation block is skipped under `--dry-run` and `--classify-only`; the check belongs inside
  that same block.
- `abspath()` runs **after** validation and does not normalise `.`/`..` — it just prepends `$PWD`.
  C3 exists to force real resolution. Prefer builtin `cd "$d" && pwd -P` over `realpath`, which is
  not in the driver's required-command loop.
- A bare `case "$SKILL_DIR" in "$REPO_PATH"/*)` is nearly right but must handle the equal case (C2)
  and a trailing slash. G3 catches the naive string-prefix form.
- `test-driver.sh` has no subprocess-invocation pattern today; every case restates logic or `eval`s
  a function out. These cases would be the first of their kind — which is why **#9** is worth
  sequencing alongside.
- Suggested message: `--skill-dir is inside --repo-path: the run's work product would be the instructions grading it (pass --allow-nested-skill-dir to proceed)`.

## What we're NOT doing

Reverse containment (`--repo-path` inside `--skill-dir`) — noted as a possible follow-up.

---
*Criteria + tier added via `agent-session triage`. Checks were run at triage time, not inferred. Original issue text preserved verbatim above; the "Rescoped at triage" section supersedes its refuse-by-default framing.*
