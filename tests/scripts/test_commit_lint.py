"""Acceptance test for scripts/commit_lint.py -- issue #47's CRITERIA C1 and C2.

    C1: GIVEN a commit-message body containing a closing keyword inside
    backticks, WHEN the detector runs, THEN it SHALL report that commit; AND
    GIVEN a body whose only closing keyword is an ordinary trailing
    `Closes #N`, it SHALL NOT report it.

    C2: WHEN the detector runs over the commits on the current branch that are
    not yet on `origin/main`, THEN a quoted closing keyword SHALL fail the
    check with a non-zero exit.

Written BEFORE the detector exists, so it is the interface definition rather
than a description of an implementation. `scripts/commit_lint.py` must provide:

    scan_message(message: str) -> list[tuple[int, str]]
        Every *quoted* closing keyword in ONE raw commit message, in order of
        appearance, as `(1-based line number within `message`, the matched
        text exactly as it appears)`. A closing keyword is
        `close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved`
        (case-insensitive) followed by whitespace and `#<digits>` -- GitHub's
        own list. "Quoted" means the match falls inside a backtick-delimited
        span. A closing keyword that is NOT inside backticks is not returned.
        Pure function over text: no git, no filesystem, no cwd.

    scan_range(rev_range: str, repo: Path | None = None) -> list[tuple[str, int, str]]
        The same, across every commit git selects. `rev_range` is handed to
        `git log` as a single argument, so both `A..B` and `--all` are valid.
        The message scanned is the commit's FULL RAW message -- `%B`, subject
        line included -- which is what fixes the line numbers. Returns one
        entry PER OCCURRENCE (not per commit) as
        `(commit sha, line number within that commit's message, matched text)`,
        with the full 40-character sha. `repo` is the working tree to run git
        in; `None` means the current working directory.

    main(argv: list[str] | None = None) -> int
        Entry point. `python3 scripts/commit_lint.py [REV_RANGE]`, run from
        inside the repo to scan; `REV_RANGE` defaults to `origin/main..HEAD`
        per C2. Returns/exits non-zero iff at least one occurrence was found,
        and prints each occurrence -- the commit sha at least, so an operator
        can find it. An empty range is clean and exits 0 -- unlike
        `assertion_lint`, where
        zero files scanned means a broken scope, a branch with no new commits
        is the ordinary case and must not render as a failure.

Shape copied from `scripts/test_assertion_lint.py`: it **imports** the module
rather than restating its logic (a test that re-implements the detector grades
a replica -- the defect issue #9 removed), and the range tests build a
throwaway `git init` repo in pytest's `tmp_path`, so nothing depends on the
state of the real working tree.

With one deliberate exception, and it is the point of the file. The last test
scans this repo's own `git log --all` and asserts the result matches the table
verified at freeze in `checks.md`: exactly ONE occurrence, `2cbe106`'s quoted
`Closes #7`, and specifically not `2cbe106`'s own genuine `Closes #23`, which
lives in the same commit body. That is guard G1 as an executable test, and a
detector that flags every closing keyword cannot pass it -- which matters
because flagging everything is the cheap way to green C1.

*(These fixtures contain literal closing keywords. That is safe in a FILE --
GitHub only reads commit messages and PR bodies. The throwaway repo's commits
are local, never pushed, and use issue numbers that do not exist.)*
"""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_sessions.scripts import commit_lint

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "src" / "agent_sessions" / "scripts" / "commit_lint.py"


# --- fixtures, shaped like real commit messages -----------------------------

# The defect, reduced from the real one at 2cbe106: a sentence that *describes*
# a fixture whose payload happens to be a closing keyword. The author is
# quoting, GitHub is parsing.
QUOTED = """Phase 1: gate selection on the closing link, not on a mention

Tightening the shared matcher would have flipped the frozen fixture at
test-park-state.sh:89 -- `Closes #99001`, branch `fix/99001-stub`, no
closingIssuesReferences key.
"""
QUOTED_LINE = 4
QUOTED_TEXT = "Closes #99001"

# The load-bearing negative. Every legitimate commit in this repo's history
# looks like this, so a detector that reports it fires ten times on `--all`
# and is disabled within a day.
GENUINE = """fix(#99002): stop the thing from doing the other thing

The one matcher becomes two, because its two callers want opposite errors.

Closes #99002

Co-Authored-By: Somebody <nobody@example.invalid>
"""

# Both in one body -- exactly `2cbe106`'s shape, and the reason G1 counts
# occurrences rather than commits. A detector graded on "how many commits did
# you flag" passes this while firing for the wrong reason.
BOTH = QUOTED + "\nAnd then, genuinely:\n\nCloses #99002\n"

# A fenced block. In scope on purpose: commit messages are not rendered as
# markdown, so ``` is three literal backticks exactly as ` is one, and a
# closing keyword inside a fence closes the issue by the identical mechanism.
# Indented (four-space) code blocks are NOT in scope -- there is no delimiter
# to key on, and guessing at indentation would cost false positives on ordinary
# quoted logs.
FENCED = """docs: record what the payload looks like

The stub payload the suite freezes:

```
{"title": "chore: stub", "body": "Closes #99003"}
```

Closes #99002
"""


# --- C1, first conjunct: the quoted keyword is reported ---------------------

def test_a_quoted_closing_keyword_is_reported():
    assert commit_lint.scan_message(QUOTED) == [(QUOTED_LINE, QUOTED_TEXT)]


@pytest.mark.parametrize(
    "keyword",
    ["close", "closes", "closed", "fix", "fixes", "fixed",
     "resolve", "resolves", "resolved", "CLOSES", "Fixed"],
)
def test_every_closing_keyword_inflection_is_recognised(keyword):
    """GitHub's list, not a subset of it. `Closes` is merely the one this repo
    happens to write; `Fixes #N` in backticks closes the issue just as dead."""
    message = f"subject line\n\nthe payload is `{keyword} #99004` verbatim\n"
    assert commit_lint.scan_message(message) == [(3, f"{keyword} #99004")]


def test_a_keyword_inside_a_fenced_block_is_reported():
    assert commit_lint.scan_message(FENCED) == [(6, "Closes #99003")]


# --- C1, second conjunct: the load-bearing negative -------------------------

def test_an_ordinary_trailing_closing_reference_is_not_reported():
    """The half that decides whether the detector survives contact. Ten of the
    eleven closing references in this repo's history are this shape."""
    assert commit_lint.scan_message(GENUINE) == []


def test_a_bare_issue_mention_is_not_reported():
    """`#N` without a keyword back-links but does not close -- noise, not
    damage. Issue #47's second open question resolves this to `no`."""
    message = "subject\n\nrefuted by PR #21, per `#99005` and issue #99006\n"
    assert commit_lint.scan_message(message) == []


# --- per-occurrence discrimination: guard G1's mechanism --------------------

def test_a_body_carrying_both_reports_only_the_quoted_one():
    """One body, two closing keywords, one report -- and the test names WHICH.
    Counting flagged commits would pass a detector that flags everything."""
    found = commit_lint.scan_message(BOTH)
    assert found == [(QUOTED_LINE, QUOTED_TEXT)]
    assert not any("99002" in text for _, text in found)


# --- C2: scanning a real revision range -------------------------------------

GIT_CONF = [
    "-c", "user.email=commit-lint-test@example.invalid",
    "-c", "user.name=Commit Lint Test",
    "-c", "commit.gpgsign=false",
]


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *GIT_CONF, *args],
        cwd=repo, capture_output=True, text=True, check=True,
    )
    return proc.stdout


@pytest.fixture
def fixture_repo(tmp_path):
    """A throwaway local repo: a base commit, a genuine one, a quoted one.

    Empty commits, `--no-verify`, and identity/signing forced off the command
    line so it runs unattended on a machine with hooks or gpg configured.
    """
    repo = tmp_path / "throwaway"
    repo.mkdir()
    git(repo, "init", "-q")

    def commit(message: str) -> str:
        git(repo, "commit", "-q", "--allow-empty", "--no-verify", "-m", message)
        return git(repo, "rev-parse", "HEAD").strip()

    base = commit("chore: base commit, nothing to see")
    clean = commit(GENUINE)
    dirty = commit(QUOTED)
    return SimpleNamespace(path=repo, base=base, clean=clean, dirty=dirty)


def test_range_scan_finds_the_dirty_commit_and_not_the_clean_one(fixture_repo):
    found = commit_lint.scan_range(
        f"{fixture_repo.base}..HEAD", repo=fixture_repo.path
    )
    assert [(sha, text) for sha, _line, text in found] == [
        (fixture_repo.dirty, QUOTED_TEXT)
    ]


def test_range_scan_of_only_clean_commits_is_empty(fixture_repo):
    found = commit_lint.scan_range(
        f"{fixture_repo.base}..{fixture_repo.clean}", repo=fixture_repo.path
    )
    assert found == []


def run_entry_point(repo: Path, *argv: str) -> subprocess.CompletedProcess:
    """The process, not the function -- C2 is about the exit status `make
    check` will see."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), *argv],
        cwd=repo, capture_output=True, text=True,
    )


def test_entry_point_exits_non_zero_when_a_quoted_keyword_is_present(fixture_repo):
    proc = run_entry_point(fixture_repo.path, f"{fixture_repo.base}..HEAD")
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert fixture_repo.dirty[:7] in (proc.stdout + proc.stderr)


def test_entry_point_exits_zero_on_a_clean_range(fixture_repo):
    proc = run_entry_point(
        fixture_repo.path, f"{fixture_repo.base}..{fixture_repo.clean}"
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_entry_point_exits_zero_on_an_empty_range(fixture_repo):
    """A branch with no new commits is the ordinary case, not a broken scope.
    `make check` must stay green on it (G2)."""
    proc = run_entry_point(fixture_repo.path, "HEAD..HEAD")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "scanned 0 commits" in proc.stdout

def test_entry_point_reports_commit_count_on_clean_range(fixture_repo):
    proc = run_entry_point(
        fixture_repo.path, f"{fixture_repo.base}..{fixture_repo.clean}"
    )
    assert proc.returncode == 0
    assert "in 1 commits" in proc.stdout



# --- G1, executable: this repo's real history -------------------------------

def test_real_history_reports_exactly_the_one_known_occurrence():
    """Deliberately the live object database, not a copy.

    `checks.md` verified at freeze that `git log --all` carries eleven closing
    references across nine commits: ten genuine, and one quoted -- `2cbe106`'s
    `Closes #7`, the reference that actually closed a live issue. A detector
    that flags everything reports eleven here and cannot pass, which a
    synthetic clean fixture would let it do.
    """
    found = commit_lint.scan_range("--all", repo=REPO_ROOT)
    assert [(sha[:7], text) for sha, _line, text in found] == [
        ("2cbe106", "Closes #7")
    ], found
    # Named separately because it is the specific confusion G1 exists to catch:
    # 2cbe106's OWN genuine trailer lives in the same body as the quoted one.
    assert not any("#23" in text for _, _, text in found)
