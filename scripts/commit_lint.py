#!/usr/bin/env python3
"""Detect a closing keyword that a commit message only *quotes*.

Why this exists
---------------
GitHub closes an issue when a commit message says ``Closes #N``. **Commit
messages are not rendered as markdown**, so backticks around such a reference
are literal characters, not quoting -- GitHub reads the keyword and closes the
issue anyway.

That is not hypothetical. Commit ``2cbe106`` explains a selection/discovery
split by describing a frozen test fixture, and the fixture's payload contains
the literal text of a closing keyword for issue #7. Issue #7 was a live backlog
item. It was closed as COMPLETED on 2026-07-31 by that sentence, and nobody
noticed until the queue count changed.

**What made it invisible is that the two mechanisms disagree.** ``gh`` reports
that PR's ``closingIssuesReferences`` as ``[23]`` -- the PR never claimed to
close #7; only the commit body did. So the PR's own metadata, the place anyone
would look, says nothing is wrong.

This is the *self-matching* shape this repo keeps hitting -- a detector that
cannot tell a mention from a claim. The denial detector counted its own regex;
``docs_check`` flagged CLAUDE.md's own example of a stale count; an issue body
that merely quotes the spec marker reads as specced. The novelty here is that
the detector is **GitHub's**, so the parser is not ours to fix. Only what we
hand it.

Hence a detector rather than a rule telling authors to escape closing keywords.
This project is 3-for-3 on added rules measuring away (``findings.md`` defect
class 4), and an author who is quoting a fixture is not thinking about GitHub's
parser -- which is exactly when an exhortation fails and a check does not.

The rule
--------
A closing keyword is reported iff it falls inside a **backtick-delimited span**.
Nothing else is reported. In particular an ordinary trailing ``Closes #N`` is
left alone, and that negative is the load-bearing half: ten of the eleven
closing references in this repo's history are that shape, so a detector that
flagged them would fire on every legitimate commit and be switched off within a
day.

Quoting is decided by a small state machine, per line:

  * a line whose stripped text starts with three backticks toggles fenced-block
    state, and is not itself scanned;
  * inside a fence, every match on the line is quoted;
  * outside one, a match is quoted iff it lies within an inline ```...``` span
    **on that same line**.

Four deliberate non-features, each because a false positive trains the operator
to wave the mechanism through (``findings.md``):

  * **Four-space-indented blocks are not treated as quoting.** There is no
    delimiter to key on, and indentation in a commit message means many things.
    Measured over ``git log --all``: zero instances.
  * **``~~~`` fences are not recognised.** The criterion is about backticks, and
    a commit message is not markdown regardless.
  * **An inline span is not tracked across a line break.** Line-scoped by
    construction; the real defect is single-line.
  * **Global backtick parity is not the mechanism**, though it happens to
    classify every frozen fixture correctly. It is fragile in the way that
    matters: one stray backtick flips the classification of everything after
    it, in both directions -- silently turning genuine references into
    failures, or hiding a real one. Resetting per line cannot fail that way.

Scope
-----
**Commit messages only**, and that is what keeps this detector off its own back.
Its source and tests are full of quoted closing keywords as fixtures; they are
files, and files are not in scope. ``assertion_lint`` had to solve the same
self-matching problem by narrowing its glob. Here the media differ, so the
scoping is structural rather than a carve-out.

PR bodies are deliberately excluded: GitHub *renders* those, so backticks
genuinely quote there, and flagging them would fire on every PR body that
quotes a gate block.

By default the scan covers ``origin/main..HEAD`` -- the commits this branch adds
and has not yet merged. History is immutable and already contains the one known
instance; re-reporting it forever would train the operator to ignore the check.
``--all`` scans everything, which is how the regression guard is run by hand.

Stdlib only, and invoked with plain ``python3``, to match ``docs_check.py`` and
``assertion_lint.py`` and stay portable to a GHA runner.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

#: The commits scanned when no range is given: what this branch adds on top of
#: the default branch. Empty on `main` itself, which is a pass, not a fault.
DEFAULT_RANGE = "origin/main..HEAD"

#: GitHub's full closing-keyword list, followed by whitespace and `#<digits>`.
#: The inflections are spelled `close[sd]?` rather than `close|closes|closed`
#: because alternation is first-match: `close` would match the prefix of
#: `closes` and then fail to find the `#`, silently missing the reference.
CLOSING_KEYWORD = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#\d+",
    re.IGNORECASE,
)

#: A backtick-delimited fence line -- three or more backticks, optionally
#: indented, optionally followed by an info string.
FENCE = re.compile(r"^\s*```")

#: One inline code span: a backtick, the shortest run of non-backticks, a
#: backtick. Non-greedy so `a` and `b` on one line are two spans, not one that
#: swallows the text between them.
INLINE_SPAN = re.compile(r"`[^`]*`")

#: Record and field separators for `git log`, so a multi-line body cannot be
#: mistaken for the start of the next record. ASCII RS and NUL -- neither can
#: occur in a commit message written by any ordinary editor, unlike a newline or
#: a blank line.
#:
#: Written as git's own `%x1e` / `%x00` placeholders rather than as literal
#: characters in the Python string. `subprocess` rejects an argv element
#: containing a NUL byte outright (`ValueError: embedded null byte`), so the
#: expansion has to happen inside git, not before it.
_FORMAT = "%x1e%H%x00%B"
_RECORD_SEP = "\x1e"
_FIELD_SEP = "\x00"

failures: list[str] = []


def _quoted_spans(line: str) -> list[tuple[int, int]]:
    """The `(start, end)` character offsets of every inline code span in `line`."""
    return [m.span() for m in INLINE_SPAN.finditer(line)]


def scan_message(message: str) -> list[tuple[int, str]]:
    """Every *quoted* closing keyword in one raw commit message.

    Returns `(1-based line number within `message`, the matched text exactly as
    it appears)` for each occurrence, in order of appearance. A closing keyword
    that is not inside backticks is not returned.

    A pure function over text: it touches no git, no filesystem and no cwd, so
    a caller can test it without a repository.
    """
    found: list[tuple[int, str]] = []
    in_fence = False

    for lineno, line in enumerate(message.splitlines(), start=1):
        if FENCE.match(line):
            # The delimiter itself carries no reference worth reporting, and
            # scanning it would double-count an info string.
            in_fence = not in_fence
            continue

        if in_fence:
            found.extend((lineno, m.group(0)) for m in CLOSING_KEYWORD.finditer(line))
            continue

        spans = _quoted_spans(line)
        if not spans:
            continue
        for m in CLOSING_KEYWORD.finditer(line):
            if any(start < m.start() and m.end() <= end for start, end in spans):
                found.append((lineno, m.group(0)))

    return found


def commit_messages(rev_range: str, repo: Path | None = None) -> list[tuple[str, str]]:
    """`(sha, full raw message)` for every commit `git log` selects.

    `rev_range` is passed as a single argv element, so both `A..B` and `--all`
    work. The message is `%B` -- subject line included -- which is what makes
    `scan_message`'s line numbers line up with the message a human would read.
    """
    out = subprocess.run(
        [
            "git",
            "log",
            rev_range,
            f"--format={_FORMAT}",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    commits: list[tuple[str, str]] = []
    for record in out.split(_RECORD_SEP):
        if not record.strip():
            continue
        sha, _, body = record.partition(_FIELD_SEP)
        commits.append((sha.strip(), body))
    return commits


def scan_range(rev_range: str, repo: Path | None = None) -> list[tuple[str, int, str]]:
    """Every quoted closing keyword across a revision range.

    Returns one entry **per occurrence**, not per commit, as
    `(40-character sha, line number within that commit's message, matched text)`.

    Per-occurrence is the whole point rather than a detail. Commit `2cbe106`
    carries a quoted closing keyword *and* a genuine one in the same body, so a
    result counted per commit cannot distinguish a detector that found the
    defect from one that flagged everything.
    """
    return [
        (sha, lineno, text)
        for sha, message in commit_messages(rev_range, repo)
        for lineno, text in scan_message(message)
    ]


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    rev_range = args[0] if args else DEFAULT_RANGE

    try:
        found = scan_range(rev_range)
    except subprocess.CalledProcessError as exc:
        # A range git cannot resolve is a broken invocation, not a clean tree.
        # Failing loudly here is the same lesson as assertion-lint's empty-scope
        # check: a null must not render as a positive.
        sys.stderr.write(exc.stderr or "")
        print(f"FAIL: commit-lint could not read the range {rev_range!r}")
        return 1

    for sha, lineno, text in found:
        failures.append(f"{sha[:7]} line {lineno}: quoted closing keyword: {text}")

    for f in failures:
        print(f"  FAIL  {f}")

    if failures:
        print(
            f"\ncommit-lint: {len(failures)} quoted closing keyword(s) in "
            f"{rev_range}. Commit messages are NOT rendered as markdown, so the "
            f"backticks are literal and GitHub will close the issue anyway -- "
            f"this is how #7 was closed by accident. There is no escape that "
            f"works in a commit message: reword instead, e.g. \"the fixture's "
            f"payload includes a closing keyword\". See issue #47."
        )
        return 1

    print(f"commit-lint: no quoted closing keywords in {rev_range}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
