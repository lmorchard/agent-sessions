<!-- agent-session:spec -->

`make docs-check` scans **zero files** when run from inside a git worktree, and reports green.
Every `express` run works inside a worktree, so **the doc-rot detector has never actually run on any
driver run's own documentation.**

## Measured

`scripts/docs_check.py`:

```python
ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", ".worktrees", "node_modules", ".venv", ".driver-state", "__pycache__"}
```

From a worktree, `__file__` resolves under `.worktrees/<branch>/scripts/`, so `ROOT` becomes
`.worktrees/<branch>` — and every markdown file beneath it has `.worktrees` among its path parts, so
`md_files()` skips all of them as their own excluded ancestor.

Verified 2026-08-01, same commit, same file, two working directories:

```
from repo root:          ROOT = /Users/lorchard/devel/agent-sessions
                         md files scanned = 103

from inside a worktree:  ROOT = .../.worktrees/fix/51-dry-run-orphan-exempt
                         md files scanned = 0
```

Both print `docs-check: links resolve, tables well-formed, counts match` and exit 0.

## Why this is the expensive kind of null

`docs-check` is in `make check`, and `make check` is the `project-gates` row of every merge gate this
project publishes. So `project-gates: make check green` has, on every run to date, included a doc-rot
detector that examined nothing. The detector was built specifically to catch stale docs, and the one
place a run's *own* freshly-written session docs would be checked is the one place it is blind.

This is `findings.md` defect class 2 — a null rendering as a positive — with the added sting that the
affected component is itself a detector built to close that class. It is also a clean instance of
class 5, *"I wrote a guard" is not evidence*: the guard exists, runs, and passes, and passing means
nothing.

It was found by the unattended run on issue #51 while establishing a baseline, and reported as
*"my green baseline for that target meant nothing."* That is a run catching a defect in the
infrastructure grading it.

## Suggested shape (not a decision — needs intake)

1. **Do not simply delete `.worktrees` from `SKIP_DIRS`.** From the repo root that entry is doing real
   work — it stops a run's worktree being scanned twice and stops one branch's docs being linted
   against another's. The bug is that the *same* entry means "skip a subtree" from the root and
   "skip everything" from inside it.
2. **Make the exclusion relative to `ROOT` rather than matched against absolute path parts**, so a
   directory cannot exclude itself. That is the actual defect and the one-line shape of the fix.
3. **The discriminating check** is not "docs-check passes" — it is that the *file count* is non-zero
   from both working directories, and specifically that a known-bad markdown file placed in the tree
   is reported from inside a worktree as well as from the root. A check that only asserts exit 0 would
   pass today, which is exactly how this survived.
4. **Consider whether the same shape affects the other detectors.** `assertion_lint` and `commit_lint`
   also derive paths from `__file__`; whether they are reachable from a worktree has not been checked
   here. Worth establishing in the same pass rather than one detector at a time — this is the fourth
   detector-level defect in this project's history and they have arrived one at a time so far.

`scripts/` is on `CLAUDE.md`'s drivable allowlist and pytest fixtures for `docs_check` already exist
(`scripts/test_docs_check.py`, run by `make gate-test`), so the oracle for items 2 and 3 exists today.

~~Not triaged: no spec marker, so the board-driver will skip it until it goes through intake.~~

**Triaged 2026-08-01** — the marker now leads this body and the criteria are below.

---

## Verifiable acceptance criteria

- **C1.** GIVEN a `ROOT` whose own path contains a component named in `SKIP_DIRS`, WHEN `docs_check`
  enumerates markdown files, THEN it SHALL still find the files beneath that `ROOT`.
  **CHECK:** a new case in `scripts/test_docs_check.py` that sets `ROOT` to
  `<tmp>/.worktrees/<branch>`, writes two markdown files beneath it, and asserts both are scanned;
  with a control at `<tmp>/plain/<branch>` asserting the same two.
  **DEMONSTRATED FAILING 2026-08-01**, with the control, by running the shipped `md_files()`:

  ```
  ROOT = <tmp>/.worktrees/fix-branch   md files scanned = 0   (expected 2)
  ROOT = <tmp>/plain/fix-branch        md files scanned = 2   (expected 2)
  ```

  And in the real repo, same commit, same file: **103 files from the repo root, 0 from inside a
  worktree**, both printing green and exiting 0.
  **ORACLE EXISTS NOW:** `scripts/test_docs_check.py`, run by `make gate-test`.

  **Why the existing suite missed it, which the fix must not reproduce:** the `isolate` fixture does
  `monkeypatch.setattr(docs_check, "ROOT", tmp_path)`, and `tmp_path` never contains an excluded
  component — so every existing test bypasses the path-matching this bug lives in. C1's case must
  therefore **not** use `isolate` as-is.

- **C2.** GIVEN a *sibling* git worktree beneath `ROOT` at a path `SKIP_DIRS` does not name — Claude
  Code creates them at `.claude/worktrees/<branch>/`, **no dot on `worktrees`** — WHEN `docs_check`
  enumerates markdown files, THEN it SHALL NOT scan any file inside that worktree.
  **CHECK:** a new case in `scripts/test_docs_check.py` that builds, beneath `ROOT`, a directory
  containing a `.git` file whose content is `gitdir: …` plus a markdown file under it, and asserts
  that file is not scanned; with a control asserting a markdown file at the same depth under a plain
  (non-worktree) directory *is* scanned.
  **DEMONSTRATED FAILING 2026-08-03**, with the control, by running the shipped `md_files()` and
  `is_frozen()` against a fixture with all three spellings present:

  ```
  scanned: ['.claude/worktrees/wt/docs/dev-sessions/s/notes.md',   <- expected: not scanned
            'docs/dev-sessions/s/notes.md']
           ('.worktrees/wt/...' correctly skipped -- the name list works only for the dotted spelling)

    frozen-exempt? False  .claude/worktrees/wt/docs/dev-sessions/s/notes.md
    frozen-exempt? True   docs/dev-sessions/s/notes.md
  ```

  **ORACLE EXISTS NOW:** `scripts/test_docs_check.py`, run by `make gate-test`.

  **Why this is the same defect and not a second one.** `md_files()` decides what is a worktree by
  *matching directory names*, and there is no name list that can be right: `.worktrees` is the
  fallback this repo never uses, `.claude/worktrees/` is what Claude Code actually creates. C1 is
  that a name can exclude its own `ROOT`; C2 is that a name can fail to exclude a real worktree.
  Both are the name list.

  **Why it produced failures rather than merely wasted work**, which is the part that matters
  operationally: the freshness exemption at `:65` is `rel.startswith(FROZEN)`, and
  `.claude/worktrees/<b>/docs/dev-sessions/…` starts with neither entry — so **frozen session
  records lose their exemption** and their historical counts get graded as live claims. Verified on
  `main`, 2026-08-03: `make check` reported 11 `docs-check` failures, every one a session artifact
  that is exempt in its real location and zero of them in `docs/`. **`make check` therefore cannot
  go green on this repo while any `.claude/worktrees/` copy exists** — so one session working in a
  worktree breaks verification for every other session, a collision cost beyond the obvious ones.
  C2 is written as "not scanned" rather than "exemption preserved" deliberately: scanning another
  worktree at all is the cross-branch linting G1 exists to prevent.

## Regression guards

- **G1.** Exclusion still works for *descendants*: a `.worktrees/` directory **inside** `ROOT` is
  still skipped. **CHECK:** a case with `ROOT = <tmp>` and a file at `<tmp>/.worktrees/x.md` asserting
  it is not scanned. Passes today.
  **This is the guard that blocks the obvious wrong fix** — deleting `.worktrees` from `SKIP_DIRS`
  would green C1 and reintroduce scanning one branch's docs while linting another's.
- **G2.** All existing `docs_check` cases pass unchanged. **CHECK:** `make gate-test`, no case lost,
  newly skipped or newly failing. Passes today.
- **G3.** `python3 scripts/docs_check.py` from the repo root still reports the same verdict on the
  real tree. **CHECK:** exit 0 and a non-zero file count. Passes today at 103 files.
- **G4.** `ROOT` itself does not exclude itself via its own `.git`. A main checkout has `.git` as a
  *directory* and a worktree has it as a *file*; either way `ROOT` carries one, so a rule that skips
  "any directory containing a `.git` entry" applied to `ROOT` would scan zero files — reintroducing
  the C1 bug through the C2 fix. **CHECK:** the C1 cases still pass with a `.git` entry created at
  `ROOT`, from both the excluded-name and plain spellings. Passes today (there is no `.git` logic yet).
  **This is the guard that blocks the obvious wrong fix for C2**, and it is C1's principle restated
  against the new mechanism: a directory must not be able to exclude itself.

## Tier: auto-ok

**Trigger 1 does not fire.** C1 and C2 are both file counts with controls, each demonstrated failing
by running the shipped function; the oracle is an existing pytest suite already wired into
`make gate-test`.

**Trigger 2 does not fire.** `scripts/` is on the drivable allowlist, and `CLAUDE.md`'s narrow reading
of "the oracle" is explicit that `scripts/docs_check.py` is drivable however detector-shaped it looks.

**The residual risk `CLAUDE.md` already names applies here literally**, and is worth repeating at the
point of use: a change that edits `docs/` *and* `docs_check.py` together could weaken the detector
that would have caught its own doc rot. This issue edits only the detector and its tests; a reviewer
should check that the diff contains no `docs/` content changes riding along.

## Design decisions

- **Decision:** make the exclusion relative to `ROOT` rather than matched against absolute path parts.
  - **Why:** the defect is that one `SKIP_DIRS` entry means "skip a subtree" from the root and "skip
    everything" from inside it. Relativising is the smallest change that makes a directory unable to
    exclude itself, and it keeps the entry doing its real job.
  - **Rejected:** removing `.worktrees` from `SKIP_DIRS` (see G1); and special-casing worktree
    detection via `git rev-parse`, which adds a subprocess and only fixes the one excluded name.
    > **Superseded in part, 2026-08-03 — kept above verbatim because the reasoning is still
    > instructive and the amendment below is a change of decision, not a correction of a typo.**
    > The rejection of git-based detection was written when only C1 was known, and its stated
    > reason — *"only fixes the one excluded name"* — is an argument against `git rev-parse`
    > specifically. C2 shows the name list cannot be made right by any choice of names, so
    > "fixes only one name" stopped being a reason to prefer it. What survives is the objection
    > to *adding a subprocess*, and the decision below honours that: it detects a worktree from
    > the filesystem, stdlib-only, which is the module's stated constraint.

- **Decision (added 2026-08-03, with C2):** detect a worktree by its `.git` **entry**, not by its
  directory name — skip any *descendant* directory of `ROOT` that contains a `.git` file or
  directory. This is **additive to `SKIP_DIRS`, which keeps every entry it has today**, including
  `.worktrees`.
  - **`.worktrees` must stay in `SKIP_DIRS`, and this is not belt-and-braces redundancy — G1
    requires it.** G1's check is a *bare* `<tmp>/.worktrees/x.md` with no `.git` entry beneath it, so
    the new rule alone would scan it and G1 would fail. An implementation that removes `.worktrees`
    on the grounds that the `.git` rule supersedes it has broken a frozen guard.
  - **Why:** a worktree root always carries a `.git` file containing `gitdir: …` (verified
    2026-08-03 against the live `.claude/worktrees/` copy), and a nested checkout carries a `.git`
    directory. So this identifies the *class* — any nested working tree, whatever it is called and
    wherever a tool decides to put it — rather than enumerating spellings. It removes a
    hand-maintained inventory, which is the shape #50 argued against, and it needs no subprocess.
  - **Composes with C1 rather than replacing it:** C1 relativises the remaining `SKIP_DIRS` entries
    (all of which stay) so `ROOT` cannot exclude itself; this decision is what stops correctness
    depending on whether a worktree's location happens to be *among* those entries.
  - **Rejected:** adding `worktrees` alongside `.worktrees` in `SKIP_DIRS` — it greens C2 for
    today's tool and breaks the next time anything puts a worktree somewhere else, and it would
    also skip a legitimately tracked directory that happened to be named `worktrees`.
  - **Rejected:** enumerating markdown via `git ls-files` instead of `rglob`. It would fix both C1
    and C2 at once and delete the name list entirely, but the existing suite monkeypatches `ROOT` to
    a non-git `tmp_path`, so it would reshape the fixture every current case depends on — trading a
    known oracle for a rewritten one inside the change that needs the oracle. Worth revisiting
    separately; not here.

## What we're NOT doing

- **Auditing `assertion_lint` and `commit_lint` for the same shape in this issue.** They also derive
  paths from `__file__` and may or may not be reachable from a worktree. That is worth a single
  deliberate pass rather than a third one-at-a-time discovery — this is the fourth detector-level
  defect in this project's history — but it is a different issue with different checks.
