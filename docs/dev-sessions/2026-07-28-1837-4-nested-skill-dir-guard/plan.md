# Nested `--skill-dir` guard — Implementation Plan

**Goal:** Make the driver warn loudly, and refuse without an explicit opt-in, when `--skill-dir`
resolves inside `--repo-path` — so a mistyped flag pair fails fast at startup instead of dying
confusingly deep in the run.

**Source issue:** https://github.com/lmorchard/agent-sessions/issues/4 — **Tier:** `auto-ok`
(every criterion is a direct invocation of the shipped driver asserting a specific stderr string;
the oracle is bash plus the driver, both present now; the diff lands in `driver/`, which
`CLAUDE.md` names drivable and which explicitly excludes `driver/gate.py`)

**Approach:** Add a containment test to the existing validation block in
`agent-session-driver.sh` (lines 103–109), which already runs only when a real run is going to
happen (`--dry-run` and `--classify-only` skip it). Containment is decided on **resolved** paths,
so both arguments are canonicalised first with the builtin `cd "$d" && pwd -P` rather than
`realpath`, which is not in the driver's required-command loop. A new `--allow-nested-skill-dir`
flag downgrades the refusal to a warning-and-proceed.

**Criteria:** C1 nested warns + exits 2 · C2 the same-directory degenerate case · C3 containment
is decided on resolved paths, not argument strings · C4 the override proceeds, still warning.
Full text + checks live in `checks.md`; ids are assigned there.

---

## Phase 0: Freeze the acceptance checks — **DONE**

**Files:**
- Created: `docs/dev-sessions/2026-07-28-1837-4-nested-skill-dir-guard/checks.md`
- Modified: `driver/test-driver.sh` — eleven new cases, section
  `nested skill-dir: the flags must not be able to describe a self-editing run`

**Verification — automated:**
- [x] Every criterion's check ran and **failed for the expected reason** — C1/C2/C3 fell through
      to `error: required command not found: gh`; C4 died at
      `error: unknown argument: --allow-nested-skill-dir`. Recorded per criterion in `checks.md`.
- [x] Every guard ran and **passed** — G1, G2, G3 (G3 was UNRUN at triage), plus G4 (49 → 55
      passing assertions, nothing lost) and G5 (`make skill-readonly`).
- [x] Freeze commit `207ead9`; sha recorded in `checks.md` by follow-up commit `9d2b30d`.

**Read-only from here on:** `driver/test-driver.sh`.

---

## Phase 1: The containment guard

The whole feature, end to end: flag parsing → path resolution → the containment test → the
warning → the refusal. One vertical slice, because there is no seam that would leave an earlier
slice independently valuable — a resolver with no comparison, or a comparison with no flag, is
not a shippable half.

**Advances:** C1, C2, C3, C4 — all of them. Nothing remains for a later phase.

**Files:**
- Modify: `driver/agent-session-driver.sh` — four edits, listed below.
- Test: none. This slice's own unit tests would duplicate the frozen acceptance cases exactly;
  the frozen set already covers every branch (nested / same / relative / `..` / override /
  sibling / unrelated / string-prefix-not-path-prefix). Documented opt-out from TDD-by-default:
  the tests exist, they were written first, and they are frozen — they are just not editable
  by this phase.

**Key changes:**

1. **New default**, beside the others at the top (`:23–35`):

```bash
ALLOW_NESTED=0
```

2. **New flag** in the arg loop (`:80–98`), placed beside `--dry-run` since it is likewise a
   bare switch:

```bash
    --allow-nested-skill-dir) ALLOW_NESTED=1; shift ;;
```

3. **New usage line** (`:56–78`), after `--dry-run`:

```
  --allow-nested-skill-dir
                          proceed when --skill-dir is inside --repo-path. The run
                          cannot write skill files either way (see DENIED_TOOLS),
                          but the nesting is usually a typo, so it must be opted
                          into. Pointing the driver at this repo is the legitimate
                          case: SKILL := $(CURDIR)/skills/agent-session.
```

4. **The guard**, at the end of the existing validation block, after the
   `phases/express.md` check (`:108`) and before the block's closing `fi`:

```bash
  # Containment is a fact about resolved paths, not about the argument strings --
  # `--skill-dir ./skills/agent-session --repo-path .` is the nested case and
  # shares no prefix at all. abspath() below runs too late and only prepends $PWD;
  # it does not fold `.`/`..`. So resolve both here, with the shell builtin rather
  # than realpath, which is not in the required-command loop above.
  #
  # This does NOT protect the skill files -- DENIED_TOOLS is built from SKILL_DIR
  # unconditionally, so a nested run still cannot write them. What it catches is a
  # mistyped --skill-dir that silently aims the deny rules at paths the run needs.
  # Pointing the driver at THIS repo is nested and legitimate, which is why the
  # override exists and why the default is a refusal rather than a hard error.
  # CDPATH= because a relative --skill-dir with CDPATH set in the environment
  # would resolve against it and echo the destination, corrupting the capture.
  # SKILL_DIR really can still be relative here: abspath() is 20 lines below.
  skill_real="$(CDPATH= cd -- "$SKILL_DIR" && pwd -P)"
  repo_real="$(CDPATH= cd -- "$REPO_PATH" && pwd -P)"
  # The trailing slash is what makes this a path-prefix test rather than a string
  # one: without it, --repo-path /a/b matches --skill-dir /a/bc.
  case "$skill_real/" in
    "$repo_real"/*)
      log "WARNING: --skill-dir is inside --repo-path: the run's work product would be the instructions grading it"
      log "  skill: $skill_real"
      log "  repo:  $repo_real"
      [ "$ALLOW_NESTED" -eq 1 ] || die "--skill-dir is inside --repo-path (pass --allow-nested-skill-dir to proceed)"
      ;;
  esac
```

Why `case "$_skill_real/"` in `"$_repo_real"/*` handles all four shapes:

| case | `skill_real/` | pattern | match |
|---|---|---|---|
| C1 nested | `/w/skills/agent-session/` | `/w/*` | yes |
| C2 same | `/w/` | `/w/*` | yes — `*` matches the empty string, so the trailing slash on the subject is what makes the degenerate case match |
| G1 sibling | `/w/skills/agent-session/` | `/w/driver/*` | no |
| G3 string-not-path | `/t/a/bc/` | `/t/a/b/*` | no — the pattern's `/` is literal, and `bc` ≠ `b/` |

The `"$repo_real"` half of the pattern is quoted, so a glob metacharacter in a real path
(`/tmp/proj[1]/`) is matched literally rather than as a bracket expression.

`pwd -P` also resolves symlinks, which is a superset of what C3 asks for. Not asserted by any
frozen case (noted as a follow-up in `checks.md`), but it is the correct behaviour and comes free.

**Known unhandled edge, deliberately:** `--repo-path /` yields `repo_real=/` and a pattern of
`//*`, which matches nothing. Every path is inside `/`, so this under-reports. No frozen case
covers it, running the board-driver with the filesystem root as a checkout is not a real
configuration, and the extra branch would be untested code. Noted rather than handled.

**Verification — automated:**
- [x] C1's check passes: `make driver-test` — `nested --skill-dir warns with the literal message`,
      `  and exits 2`, `  and does not create the state dir` all `ok`
- [x] C2's check passes: `make driver-test` — `identical --skill-dir and --repo-path warn the same way` `ok`
- [x] C3's check passes: `make driver-test` — `relative paths still detect containment` and
      `.. in the path still detects containment` both `ok`
- [x] C4's check passes: `make driver-test` — `--allow-nested-skill-dir proceeds past validation`
      and `  and warns on the way through` both `ok`
- [x] Guards still pass: `make driver-test` — `a sibling directory is not containment` (G1),
      `an unrelated checkout is not containment` (G2),
      `a string prefix that is not a path prefix is not containment` (G3), and the suite reports
      `61 passed, 0 failed` (G4 — 55 + the 6 that were failing; nothing lost)
- [x] G5: `make skill-readonly` passes — `driver denies Edit/Write/NotebookEdit on the skill dir`
- [x] `make check` green (`driver-check` + `driver-test` + `skill-readonly`) — `all checks passed`.
      The repo has no `make lint` or `make test` target; `make check` is this project's aggregate gate
- [x] `make dry-run` still works — `read 178 open issues`, `eligible: 0`,
      `dry run -- no claude invocation.` No path demand, no containment complaint

**Verification — manual:**
- [x] None required. Every criterion is machine-checkable; that is why the tier is `auto-ok`.

---

## Out of scope (do not drift into these)

- **Reverse containment** (`--repo-path` inside `--skill-dir`) — the spec names it a follow-up.
- **Making G2 host-portable.** It hardcodes `$HOME/devel/decafclaw`. Real, but changing a frozen
  guard needs a human even as a clarification. Recorded in `checks.md`; not touched here.
- **A symlink case for C3.** `pwd -P` gives the behaviour; no frozen case asserts it. Follow-up.
- **Anything in `driver/gate.py`** — risk-gated by `CLAUDE.md`. Nothing here needs it.
- Tidying the validation block, the arg parser, or `abspath()` while passing through.
