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

## The verification round is where the real value was

The independent verifier passed both criteria, all three guards, and the tamper diff — and then
found **three defects** by constructing adversarial inputs of its own. All three passed the frozen
suite. That is the sentence worth keeping: *a frozen check that discriminates is not the same as a
frozen check that is exhaustive.* C1's fixtures proved the detector could tell a quoted reference
from a genuine one; they said nothing about doubled backticks, same-line triple spans, or unclosed
fences.

Two of the three were **false positives on legitimate commits** — the failure mode this detector
was specifically designed to avoid, reproduced inside the detector meant to avoid it:

1. `` ``Closes #N`` `` was missed. Spans were matched as `` `[^`]*` ``, so the *empty* span between
   each doubled tick matched, and the keyword sat between two spans instead of inside one.
2. ```` ```Closes #N``` ```` on one line read as a fence opener: the line was skipped unscanned
   *and* fence state was left flipped, so the quoted one was missed and the commit's own genuine
   trailer was reported instead.
3. An unclosed fence swallowed everything after it, reporting the commit's genuine trailer.

One cause underneath all three: **parity**. "An odd number of backticks so far means we are inside
a span" reclassifies everything after a stray delimiter. The fix pairs delimiters — fences and
inline runs alike — and makes an unmatched one inert.

The irony is instructive rather than embarrassing. The module docstring had *already* rejected
global parity, in writing, for exactly this reason, and then used line-scoped parity anyway.
Narrowing the blast radius of a fragile rule is not the same as replacing it, and the docstring's
own argument applied at both scopes.

Regressions went into `scripts/test_commit_lint_edges.py`, a separate file, because
`scripts/test_commit_lint.py` is the frozen oracle and adding to it would be the implementer
editing what grades it.

## Design decision worth keeping

**Parity was rejected at every scope, and it took two passes to actually do it.** Counting
backticks and calling odd-parity regions "quoted" is a few lines and classifies all eleven
historical references correctly. Rejected because one stray backtick flips the classification of
everything after it, in *both* directions — silently failing genuine commits, or silently hiding a
real one. Neither failure announces itself.

The first draft rejected *global* parity and then used *line-scoped* parity, which has the same
defect over a smaller region; the verifier found it three times. Delimiters are now paired
explicitly, and an unmatched one is inert.

**Where the asymmetry points matters.** A missed detection costs one wrongly-closed issue,
recoverable by reopening it — which is what actually happened to #7. A false positive costs the
whole mechanism, because it fires on commits that were fine and the operator switches it off.
Every tie in this module is broken toward not reporting, which is also why the three documented
non-features (indented blocks, `~~~` fences, cross-line spans) stay non-features until something
measured says otherwise.

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
