# Notes — #47, commit-message closing-keyword detector

Unattended `express` run. Tier `auto-ok`, no amendments, no tier downgrade.

## What shipped

`scripts/commit_lint.py` — reports a closing keyword only where it sits inside a backtick span.
Wired into `make check` as `commit-lint` over `origin/main..HEAD`, and its frozen tests added to
`gate-test`. One paragraph appended to `findings.md`'s defect-class-7 section, recording that
instance 4 now has a detector rather than a habit.

## The one implementation bug, and why it is worth recording

The first run of the frozen suite failed six tests with `ValueError: embedded null byte`. The
cause: `git log --format=` was being handed a Python string containing literal `\x1e` and `\x00`
separators, and `subprocess` refuses an argv element with a NUL in it. The fix is to let *git*
expand the separators — `%x1e` and `%x00` in the format string — so the bytes never pass through
argv.

Worth writing down because the failure is loud and the cause is not where it looks: the traceback
lands inside `subprocess._fork_exec`, several frames from anything this repo wrote.

## Two things surfaced rather than fixed

- **`scripts/test_assertion_lint.py` is not run by `make check`.** `gate-test` invoked
  `driver/test_gate.py`, `scripts/test_docs_check.py` and `scripts/test_run_progress.py` — so
  `assertion_lint`'s own tests never ran, despite issue #47's spec asserting they did (its
  ORACLE EXISTS NOW note for C1 says the pattern file is "already run by `make gate-test`"). The
  claim was false when written. This run added `scripts/test_commit_lint.py` to that line because
  that is its own work; it did **not** add `test_assertion_lint.py`, because that is a different
  issue's fix and a drive-by is how partitions rot. Worth an issue.
- **`/tmp/cl_ref/`** — the check-author subagent built a throwaway reference implementation there
  to prove the frozen tests were satisfiable before freezing them, and the sandbox denied its
  `rm -rf` cleanup. Outside the repo, nothing reads it, but it should be deleted so nobody mistakes
  it for the deliverable. The implementation in this branch was written without reading it.

## Design decision worth keeping

**Global backtick parity was rejected even though it passes every frozen fixture.** Counting
backticks across the whole message and calling odd-parity regions "quoted" is four lines and
classifies all eleven historical references correctly. It was not used, because one stray backtick
anywhere in a message flips the classification of everything after it — in *both* directions. It
would silently start failing genuine commits, or silently stop reporting a real one, and neither
failure announces itself. A state machine that resets per line cannot fail that way.

This is the same instinct as the four documented non-features in the module docstring: a false
positive trains the operator to wave the mechanism through, which is the failure mode that ends
detectors.

## Dogfood note

The run exercised its own detector by accident and on purpose. Every commit message on this branch
had to be written to avoid quoting a closing keyword while describing a bug that is *about*
quoting closing keywords — which is precisely the trap `findings.md` names as "a project that
documents its own detectors will trip them." The scratch commit used to demonstrate C2's
`make check` half also tripped the frozen real-history guard, which is the guard working: both the
`commit-lint` target and the frozen test caught it independently.

**Consequence for whoever merges this.** GitHub's squash-merge default composes the commit message
from the PR title and body. A PR body quoting a closing keyword is safe *as a PR body* (rendered),
but becomes unsafe the moment it is squashed into a commit message. The PR body for this branch
therefore avoids quoting one at all, and describes the reference in prose instead.
