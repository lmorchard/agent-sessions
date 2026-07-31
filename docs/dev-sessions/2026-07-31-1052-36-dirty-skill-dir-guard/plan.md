# Dirty-skill-dir refusal — Implementation Plan

**Goal:** the driver refuses to start when `--skill-dir` sits in a git working tree with
uncommitted changes to tracked files under it, so an unattended run can never take its
instructions from unreviewed edits.

**Source issue:** https://github.com/lmorchard/agent-sessions/issues/36 — **Tier:** `auto-ok`
(every criterion reduces to a runnable check whose oracle exists; the work lands in
`driver/agent-session-driver.sh` and `driver/test-driver.sh`, both on `CLAUDE.md`'s drivable
allowlist — not `skills/**`, not `driver/gate.py`).

**Approach:** refuse rather than warn — a warning in an unattended run is read by nobody until
after the money is spent, and the failure it guards against produces output that looks entirely
normal. Scope the check to tracked files **under `SKILL_DIR`**, not the whole repo, because the
driver is routinely pointed at a checkout with unrelated work in flight and a whole-repo test would
be disabled within a day. No escape-hatch flag, and no skill wording about which tree governs — the
mechanism removes the question.

**Criteria:** C1 a dirty skill tree refuses, naming the modified paths, without reaching the
required-command loop · C2 a clean skill tree proceeds exactly as today (the positive control that
closes the degenerate "refuse always" green).

Full text and checks live in `checks.md`, frozen at `1bd50f030f446c9abd7d486d68caf7410fc8c363`.

---

## Phase 0: Freeze the acceptance checks — **DONE**

Per `references/frozen-checks.md`. No implementation.

**Files:**
- Created: `docs/dev-sessions/2026-07-31-1052-36-dirty-skill-dir-guard/checks.md`
- Modified: `driver/test-driver.sh` — the `#36` section (C1 both arms, C2, G3, the untracked and
  dirty-elsewhere scope assertions, two reducer probes), plus four existing nest cases moved onto a
  clean committed scratch fixture

**Verification — automated:**
- [x] C1 runs and **fails for the expected reason** in both arms — `unnamed gh-check` against an
      expected `named stopped-early`, raw stderr `error: required command not found: gh`. Not a
      setup artifact; the four grounds are recorded in `checks.md`.
- [x] Every guard runs and **passes** — G1 (88 → 94 passed, the 88 pre-existing all still passing),
      G2 (existing dry-run / classify-only cases), G3 (`#36 G3 a skill dir outside any git repo
      still proceeds`), G4 (`make driver-check`)
- [x] Freeze commit `1bd50f0`; sha recorded in `checks.md` by follow-up commit `b79abb6`

---

## Phase 1: The cleanliness check in the driver

One slice, end to end: the validation block learns to ask git whether the skill directory is
modified, and refuses if it is. This is the whole of the work — C1 and C2 are both satisfied or
neither is, because C2 is the same code path taking the other branch.

**Advances:** C1, C2. Nothing remains for a later phase.

**Files:**
- Modify: `driver/agent-session-driver.sh` — one block inside the existing
  `if [ "$DRY_RUN" -eq 0 ] && [ -z "$CLASSIFY_ONLY" ]` guard, **after** the containment `case`
  statement and **before** the block's closing `fi`
- Test: none of its own. The frozen checks in `driver/test-driver.sh` are the test, and they are
  read-only from here onward.

**Placement is load-bearing, not incidental.** Three constraints pin it:

1. **Inside the `DRY_RUN`/`CLASSIFY_ONLY` guard** — G2 requires `--dry-run` and `--classify-only`
   to acquire no new failure mode, and neither even requires `--skill-dir`.
2. **After the containment check** — recorded in `checks.md` under G1. The nest cases that die at
   containment still point at this repo's real `skills/agent-session`; if cleanliness were tested
   first, a developer mid-skill-edit would flip them from `warned` to `no-warn`, reintroducing the
   host-dependence the constructed `PATH` exists to remove.
3. **Before the required-command loop** — C1 says so in as many words. It follows from (1), since
   the guarded block closes before the loop.

**Key changes** — the block to add, in full:

```bash
  # An unattended run READS $SKILL_DIR and is graded by what it reads there. If that
  # directory has uncommitted edits to tracked files, the run is graded by text that
  # is in no commit: nothing in the PR, the ledger row or the gate block records what
  # it actually read, and the same invocation an hour later is a different run. This
  # happened -- the run on issue #23 found phases/express.md, phases/pr.md and
  # references/frozen-checks.md modified-but-uncommitted, where committed pr.md said
  # "Squash and open" and the working tree said "Push and open". It stopped
  # voluntarily and nothing in the system helped it. See issue #36.
  #
  # Refuse rather than warn: a warning in an unattended run is read by nobody until
  # after the money is spent, and unreviewed instructions produce output that looks
  # entirely normal. No escape-hatch flag either -- it would be reached for by reflex,
  # which is the trap --allow-nested-skill-dir's false-positive guards exist to
  # prevent. Add one if it is ever actually wanted.
  #
  # AFTER the containment check on purpose: the nest cases that die at containment
  # point --skill-dir at this repo's own skill dir, so testing cleanliness first would
  # make their stop-point depend on the developer's working tree.
  #
  # Scoped to tracked files UNDER the skill dir, via the `-- .` pathspec:
  #   - not the whole repo, because this driver is routinely pointed at a checkout
  #     with unrelated work in flight (docs/, .driver-state/), and a check that
  #     refuses almost every real invocation gets disabled within a day;
  #   - --untracked-files=no, because a stray scratch file changes nothing about what
  #     the run is told to do, while a modified tracked file does. Narrower is better
  #     here; widen only with evidence.
  # Staged counts as dirty -- `git status` reports the index too, which is why this is
  # not `git diff`. Staged is still not committed and still not reviewed.
  #
  # The `if` is what keeps a null from rendering as a positive (docs/findings.md
  # defect class 2). `git status` prints nothing on stdout in TWO different
  # situations: a clean tree, and a SKILL_DIR that is in no repository at all -- where
  # it exits nonzero and writes "fatal: not a git repository" to stderr. Reading the
  # output alone would be fine here by luck; reading the redirected stderr as content
  # would refuse every unpacked-tarball skill dir. Only exit 0 means git answered, and
  # a git that answered nothing means clean. `git` itself may still be missing at this
  # point -- the required-command loop is below, not above -- and that case correctly
  # lands here as "could not determine", proceeding to the loop that reports it
  # properly.
  skill_dirty=""
  if skill_status="$(CDPATH= cd -- "$skill_real" \
        && git status --porcelain --untracked-files=no -- . 2>/dev/null)"; then
    skill_dirty="$skill_status"
  fi
  if [ -n "$skill_dirty" ]; then
    log "ERROR: --skill-dir has uncommitted changes to tracked files: $skill_real"
    printf '%s\n' "$skill_dirty" | while IFS= read -r skill_dirty_line; do
      log "  $skill_dirty_line"
    done
    die "--skill-dir is not clean: an unattended run would be graded by instructions that are in no commit"
  fi
```

Notes on the details, each a real hazard rather than style:

- **`$skill_real`, not `$SKILL_DIR`.** `skill_real` is the `pwd -P`-resolved path computed just
  above for the containment check; `SKILL_DIR` is still possibly relative here (`abspath` runs
  further down, at line ~202). Using the raw flag would make a relative `--skill-dir` resolve
  against whatever the subshell's cwd turned out to be.
- **`CDPATH=`** matches the two `cd`s directly above. `skill_real` is absolute so `CDPATH` cannot
  bite, but the cost is nil and the precedent is local.
- **The message names the paths.** `git status --porcelain` prints them relative to the repo root,
  so the operator sees `M skills/agent-session/phases/express.md`; `$skill_real` on the first line
  supplies the absolute anchor. C1 requires the naming — "dirty" alone makes the operator go hunt.
- **`log` then `die`.** `log` goes to stderr with a timestamp, which is where every nest case reads
  from; `die` exits 2. Same shape as the containment refusal.
- **The `while` loop runs in a pipeline subshell.** It only calls `log`, so nothing needs to escape
  it — no variable is set inside for use outside, which is the usual trap here.

**Verification — automated:**
- [ ] C1's check passes, both arms: `make driver-test` reports
      `ok  #36 C1 an uncommitted edit under --skill-dir refuses, naming the path` and
      `ok  #36 C1 a staged-but-uncommitted edit is dirty too`
- [ ] C2's check passes: `ok  #36 C2 the same edit, committed, reaches the required-command loop as before`
- [ ] G1: `make driver-test` reports 96 passed, 0 failed — every one of the 88 pre-existing
      assertions still passing, none skipped or removed
- [ ] G2: the existing `--dry-run` and `--classify-only` cases in `make driver-test` still pass
- [ ] G3: `ok  #36 G3 a skill dir outside any git repo still proceeds`, plus
      `ok  #36 an untracked file under the skill dir is not dirt` and
      `ok  #36 a repo dirty outside the skill dir still proceeds`
- [ ] G4: `make driver-check` passes
- [ ] `make check` passes (the project's own gate: `driver-check driver-test park-test
      skill-readonly docs-check`)
- [ ] Tamper diff empty: `git diff 1bd50f030f446c9abd7d486d68caf7410fc8c363 -- driver/test-driver.sh`

**Verification — manual:**
- [ ] None. No human-judgment criterion in this spec, which is why the tier is `auto-ok`.

---

## Plan self-review (Phase 2b — replaces the human plan review for this `express` run)

- **Criteria coverage, both directions.** `checks.md` holds C1 and C2; both appear in Phase 1's
  **Advances**, and Phase 1 advances both. Phase 0 advances no `Cn` by design — it *is* the freeze,
  which is the template's own shape. No criterion is unadvanced; no phase advances nothing.
- **Checks cited by command.** Every automated checkbox names either an exact `make` target or the
  exact assertion label `make driver-test` prints, plus the literal tamper-diff command with the
  freeze sha in it. No "tests pass".
- **Placeholder scan.** No `TBD`, no "add appropriate error handling", no reference to anything no
  phase defines. The one code block is the complete block to add, not a sketch.
- **Name consistency.** `skill_dirty`, `skill_status`, `skill_dirty_line` are introduced and used in
  the same block; `skill_real` is the existing variable computed for the containment check at
  `driver/agent-session-driver.sh:150`, verified present, not invented here.
- **Shell-safety under `set -euo pipefail`** (line 16). An `if` condition is exempt from `set -e`, so
  a nonzero `git status` does not abort the script. `skill_status` is always assigned — a failed
  command substitution still assigns the (empty) captured stdout — so `set -u` has nothing to trip
  on. The `printf | while` pipeline sets no variable that needs to survive the subshell.

**One operational consequence, surfaced rather than discovered later.** `make run` and `make
run-self` both pass `--skill-dir $(SKILL)`, and `SKILL := $(CURDIR)/skills/agent-session`
(`Makefile:2`). So after this lands, **those targets refuse while this repo has uncommitted tracked
changes under `skills/`** — including `make run-self`, which is how this repo dogfoods itself. That
is the feature working as specified, not a regression: skill wording is `needs-review` human work,
and a driver run launched mid-edit is precisely what issue #36 exists to stop. It is written down
because the next person to hit it will otherwise read it as a bug. No Makefile change: adding an
override here would be the escape hatch the spec explicitly declined.

---

## Out of scope, recorded rather than done

Straight from the spec's "What we're NOT doing", so a later reader can see these were decided
rather than missed:

- No skill wording about which tree governs — the refusal makes it moot, and `skills/**` is gated.
- No cleanliness check on `--repo-path`. A dirty target tree is normal mid-session.
- No `--allow-dirty-skill-dir` escape hatch.
- Untracked files under the skill dir do not count.
