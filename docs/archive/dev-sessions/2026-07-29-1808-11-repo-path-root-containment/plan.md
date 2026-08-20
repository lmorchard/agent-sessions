# `--repo-path /` containment bypass — Implementation Plan

**Goal:** make the nested-`--skill-dir` containment guard detect `--repo-path /`, which today it
silently reads as containing nothing.

**Source issue:** https://github.com/lmorchard/agent-sessions/issues/11 — **Tier:** `auto-ok`
(every criterion is a runnable check whose oracle exists now; the touched files are
`driver/agent-session-driver.sh` and `driver/test-driver.sh`, both on `CLAUDE.md`'s drivable
allowlist and neither of them `driver/gate.py`)

**Approach:** the guard compares resolved paths with a glob whose pattern is built as
`"$repo_real"/*`. `pwd -P` returns `/` for the root directory — the one resolved path that already
ends in a slash — so the pattern becomes `//*` and matches no ordinary absolute path. Normalise the
one degenerate value so the pattern is `/*` instead. One line, at the point where `repo_real` is
established, before it is used in the `case`.

**Criteria:** C1 — `--repo-path /` with an absolute `--skill-dir` beneath it warns and stops before
the required-command loop.
Full text, checks and guards live in `checks.md`. Ids are assigned there.

---

## Phase 0: Freeze the acceptance checks — **DONE**

Manifest written; the check the criterion names authored into the frozen file; freeze committed at
`6f18f87`, sha recorded in `8a8cbd5`.

**Files:**
- Created: `docs/archive/dev-sessions/2026-07-29-1808-11-repo-path-root-containment/checks.md`
- Modified: `driver/test-driver.sh` — one new nest case, `--repo-path / is containment, not a
  wildcard`, plus its comment block

**Verification — automated:**
- [x] C1's check runs and **fails for the expected reason** — `expected: warned stopped-early` /
      `actual: no-warn gh-check`. Not an import error, not a typo'd path: the *control* probe and
      the four existing containment cases fire correctly on the same run, so the harness reaches
      the guard and the guard is silent only for `/`.
- [x] Suite total moved `64` → `65` assertions with exactly one failing, so the case was collected
- [x] Every guard runs and **passes** at freeze — G1 (`make driver-check`, exit 0), G2 (all three
      false-positive cases `no-warn gh-check`), G3 (`64 passed, 0 failed` on the unmodified tree,
      full `make check` green)
- [x] Freeze commit made; sha recorded in `checks.md` in a follow-up commit

**Deviation, recorded rather than glossed:** `references/frozen-checks.md` asks for a
**check-author subagent** that has not seen the implementation plan. That dispatch needs Write
access, and this project grants read-only `Explore` dispatch only — write-capable dispatch is a
separate grant, still withheld (`design.md`, resolved decisions; it is also what blocks roadmap
item 7). So the check was authored in this context. What limits the damage: triage had already
specified the check down to its two assertions, both copied verbatim, and it was written *before*
this plan's Phase 1. The verifier at Phase 2 **is** read-only `Explore`, so the independent half of
the contract is intact where it matters most.

---

## Phase 1: Normalise the root directory before the containment glob

Make `repo_real` never the value that breaks the pattern it is interpolated into, then re-run the
frozen check and every guard.

**Advances:** C1 — fully; nothing remains for a later phase.

**Files:**
- Modify: `driver/agent-session-driver.sh` — insert the normalisation between `repo_real`'s
  assignment (line 152-153) and the `case` that consumes it (line 157)
- Test: none. The acceptance check already exists from Phase 0 and is **read-only** from here on;
  `driver/test-driver.sh` receives no further edit in this run.

**Key change:**

```bash
# `pwd -P` returns `/` for the root directory -- the one resolved path that
# already ends in a separator. The pattern below appends another, so `/` yields
# `//*`, which matches no ordinary absolute path: every path reads as OUTSIDE the
# root and the guard goes silent on the one --repo-path that contains everything.
# Collapse it to the empty string so the pattern is `/*`. Only `/` is touched, so
# the `/a/b`-vs-`/a/bc` prefix distinction below is unaffected.
[ "$repo_real" = "/" ] && repo_real=""
```

Placed immediately before the existing `case "$skill_real/" in` block, so both the pattern and the
`log "  repo:  $repo_real"` line that reports it are reached with the normalised value.

**One consequence to check rather than assume:** the warning's second log line prints
`$repo_real`, so after normalisation it would read `repo:  ` with an empty value for the root case.
That is a message-quality regression, not a correctness one — C1 asserts only the first line's
literal. Handle it by keeping the *reported* value separate from the *pattern* value rather than by
weakening anything: log `$REPO_PATH`-resolved-before-normalisation. Concretely, normalise into a
second variable used only by the `case`:

```bash
repo_prefix="$repo_real"
[ "$repo_prefix" = "/" ] && repo_prefix=""
case "$skill_real/" in
  "$repo_prefix"/*)
```

This is the shape Phase 1 implements — it fixes C1 and leaves both log lines truthful.

**Verification — automated:**
- [ ] C1's check passes: `make driver-test`, reading the line
      `--repo-path / is containment, not a wildcard` — expect `ok`, not `FAIL`
- [ ] G1 passes: `make driver-check`
- [ ] G2 passes: `make driver-test`, reading all three of `a sibling directory is not
      containment`, `an unrelated checkout is not containment`, `a string prefix that is not a path
      prefix is not containment` — each `ok` with verdict `no-warn gh-check`
- [ ] G3 passes: `make driver-test` reports `65 passed, 0 failed` — no test lost, none newly
      failing, none newly skipped (invariant; the number is evidence the total did not shrink, not
      a pinned expectation)
- [ ] `make check` passes end to end (`driver-check`, `driver-test`, `gate-test`, `park-test`,
      `skill-readonly`, `docs-check`)
- [ ] Tamper diff: `git diff 6f18f87 -- driver/test-driver.sh` is **empty** — the frozen file took
      no edit after the freeze

**Verification — manual:**
- [ ] None. C1 has no human-judgment component; there is no evidence for a human to grade, which
      is why this issue is `auto-ok`.
