"""Tests for scripts/docs_check.py.

These **import** the module rather than restating its logic — the same reason
`driver/test_gate.py` exists. The detector was mutation-tested by hand when it was
written (break a link, split a table, insert a stale count: each produced exactly
one failure), but **a hand mutation-test does not persist**, which is precisely the
gap issue #9 was about. These make it repeatable.

Each test builds a throwaway docs tree in `tmp_path` and points the module at it,
so nothing here depends on the repo's real documentation — a test that asserted
against the live docs would fail every time a doc legitimately changed.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from agent_sessions.scripts import docs_check


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    """Point the checker at a scratch tree and reset its module-level accumulators."""
    monkeypatch.setattr(docs_check, "ROOT", tmp_path)
    docs_check.failures.clear()
    docs_check.skips.clear()
    return tmp_path


def write(root: Path, rel: str, body: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    return p


# --- links -----------------------------------------------------------------

def test_resolving_link_passes(isolate):
    write(isolate, "docs/a.md", "see [b](b.md)")
    write(isolate, "docs/b.md", "hi")
    docs_check.check_links()
    assert docs_check.failures == []


def test_dead_link_fails(isolate):
    write(isolate, "docs/a.md", "see [gone](nope.md)")
    docs_check.check_links()
    assert len(docs_check.failures) == 1
    assert "nope.md" in docs_check.failures[0]


def test_link_up_a_level_resolves(isolate):
    """The case that broke twice while relocating docs into archive/."""
    write(isolate, "docs/archive/a.md", "see [design](../design.md)")
    write(isolate, "docs/design.md", "hi")
    docs_check.check_links()
    assert docs_check.failures == []


def test_external_and_anchor_links_are_ignored(isolate):
    write(isolate, "docs/a.md",
          "[x](https://example.invalid/y) [m](mailto:a@b.c) [s](a.md#frag)")
    write(isolate, "docs/a.md", (isolate / "docs/a.md").read_text())
    docs_check.check_links()
    assert docs_check.failures == []


# --- tables ----------------------------------------------------------------

GOOD_TABLE = "| A | B |\n|---|---|\n| 1 | 2 |\n"


def test_well_formed_table_passes(isolate):
    write(isolate, "docs/a.md", GOOD_TABLE)
    docs_check.check_tables()
    assert docs_check.failures == []


def test_table_split_by_prose_fails(isolate):
    """The findings.md shape: prose between rows orphans the ones after it."""
    write(isolate, "docs/a.md", GOOD_TABLE + "\nInterrupting prose.\n\n| 3 | 4 |\n")
    docs_check.check_tables()
    assert len(docs_check.failures) == 1
    assert "header separator" in docs_check.failures[0]


def test_a_stray_blank_line_between_rows_fails(isolate):
    """The exact regression that survived two readings of the file."""
    write(isolate, "docs/a.md", GOOD_TABLE + "\n| 3 | 4 |\n")
    docs_check.check_tables()
    assert len(docs_check.failures) == 1


def test_pipes_inside_a_code_fence_are_not_a_table(isolate):
    write(isolate, "docs/a.md", "```\n| not | a | table |\n```\n")
    docs_check.check_tables()
    assert docs_check.failures == []


# --- derivable counts ------------------------------------------------------

def test_matching_count_passes(isolate, monkeypatch):
    monkeypatch.setattr(docs_check, "live_bash_assertions", lambda: 61)
    write(isolate, "docs/a.md", "the 61-assertion fixture suite")
    docs_check.check_counts()
    assert docs_check.failures == []


def test_stale_count_fails(isolate, monkeypatch):
    """The '49-assertion' class that sat stale in CLAUDE.md."""
    monkeypatch.setattr(docs_check, "live_bash_assertions", lambda: 61)
    write(isolate, "docs/a.md", "the 49-assertion fixture suite")
    docs_check.check_counts()
    assert len(docs_check.failures) == 1
    assert "49" in docs_check.failures[0] and "61" in docs_check.failures[0]


def test_frozen_dirs_are_exempt_from_freshness(isolate, monkeypatch):
    """archive/ and dev-sessions/ are historical records, not maintained claims."""
    monkeypatch.setattr(docs_check, "live_bash_assertions", lambda: 61)
    write(isolate, "docs/archive/old.md", "the 21-assertion fixture suite")
    write(isolate, "docs/dev-sessions/s/notes.md", "the 47-assertion fixture suite")
    docs_check.check_counts()
    assert docs_check.failures == []


def test_unavailable_suite_is_a_skip_not_a_pass(isolate, monkeypatch):
    """A null must never render as a positive — including in the checker itself."""
    monkeypatch.setattr(docs_check, "live_bash_assertions", lambda: None)
    write(isolate, "docs/a.md", "the 49-assertion fixture suite")
    docs_check.check_counts()
    assert docs_check.failures == []          # cannot judge, so does not fail...
    assert len(docs_check.skips) == 1         # ...but says so out loud
    assert "NOT verified" in docs_check.skips[0]


# --- enumeration: which files get scanned at all ----------------------------
#
# Everything above points ROOT at `tmp_path` via the autouse `isolate` fixture,
# and `tmp_path` never contains a component named in SKIP_DIRS. So no test above
# exercises `md_files()`'s path-matching against ROOT's *own* path — which is
# where the worktree-root defect lives. These cases re-point ROOT explicitly
# (still through `monkeypatch`, so it is restored automatically) at paths that do
# contain an excluded component. `isolate` is left exactly as it is; its
# accumulator reset still runs for these tests, its ROOT is simply overridden.

BRANCH = "fix-62"
TREE = {"README.md": "top\n", "docs/design.md": "nested\n"}
TREE_FILES = ["README.md", "docs/design.md"]


def point_root_at(monkeypatch, root: Path) -> Path:
    """Override `isolate`'s ROOT with an arbitrary path (auto-restored)."""
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(docs_check, "ROOT", root)
    return root


def build_tree(root: Path) -> Path:
    for rel, body in TREE.items():
        write(root, rel, body)
    return root


def scanned(root: Path) -> list[str]:
    """What `md_files()` found, as posix paths relative to `root`, sorted."""
    return sorted(p.relative_to(root).as_posix() for p in docs_check.md_files())


# --- C1: ROOT's own path may contain an excluded component ------------------

def test_c1_root_under_an_excluded_directory_name_still_scans_its_files(
        tmp_path, monkeypatch):
    """The defect: run from `.worktrees/<branch>/` and ROOT excludes itself.

    Every path under ROOT has `.worktrees` among its parts, so the SKIP_DIRS
    match fires on all of them and the checker scans nothing while still exiting
    0 — a null rendering as a pass. Only exclusions *relative to* ROOT are meant
    to apply.

    The excluded descendants below are load-bearing, not scenery. Without them a
    "fix" of the shape *"if ROOT's own path is tainted, stop excluding anything"*
    would satisfy an exact-set assertion over two clean files — while making
    `node_modules`, `.venv` and nested worktrees scannable in exactly the
    environment this issue is about. Asserting the *exact* set here means the
    right answer is 2 files, the wrong answer is 4.
    """
    root = build_tree(point_root_at(monkeypatch, tmp_path / ".worktrees" / BRANCH))
    write(root, f".worktrees/{BRANCH}/docs/design.md", "theirs\n")
    write(root, "node_modules/pkg/README.md", "vendored\n")
    assert scanned(root) == TREE_FILES


def test_c1_control_root_under_a_plain_directory_name_scans_its_files(
        tmp_path, monkeypatch):
    """Control for C1: identical tree, ROOT's parent merely not excluded.

    Isolates the cause to ROOT's own path components — if this failed too, the
    C1 failure would be a fixture bug, not the defect.
    """
    root = build_tree(point_root_at(monkeypatch, tmp_path / "plain" / BRANCH))
    assert scanned(root) == TREE_FILES


# --- C2: sibling worktrees at a path SKIP_DIRS does not name ----------------

def test_c2_a_nested_git_worktree_is_not_scanned(isolate):
    """Claude Code puts worktrees at `.claude/worktrees/<branch>/` — no dot on
    `worktrees`, so SKIP_DIRS never matches it and a whole second checkout's docs
    get scanned as if they were this one's. The marker that generalizes is the
    `.git` *file* (`gitdir: …`) every linked worktree carries at its root.

    Two worktrees, deliberately: `.claude/worktrees/` is the spelling that
    prompted this, and `tools/checkout-b/` is unremarkable and non-hidden. The
    second one is what forbids the shortcuts — `SKIP_DIRS |= {".claude"}`, or
    "skip any dot-prefixed component", would green the first and miss it. The
    criterion is about worktrees, not about names, and the spec rejects fixing
    this by adding names.
    """
    wt = isolate / ".claude/worktrees" / BRANCH
    write(isolate, f".claude/worktrees/{BRANCH}/.git",
          f"gitdir: /elsewhere/repo/.git/worktrees/{BRANCH}\n")
    write(isolate, "docs/design.md", "ours\n")
    write(wt, "docs/design.md", "theirs\n")
    write(isolate, "tools/checkout-b/.git",
          "gitdir: /elsewhere/repo/.git/worktrees/b\n")
    write(isolate, "tools/checkout-b/docs/design.md", "theirs too\n")
    assert scanned(isolate) == ["docs/design.md"]


def test_c2_control_a_plain_nested_directory_at_the_same_depth_is_scanned(isolate):
    """Control for C2: same depth, no `.git` marker, so it must still be scanned.

    Guards the over-corrections: excluding by depth, by any nested directory, or
    by dot-prefix. `.github/` is hidden and not a worktree, so it must still be
    scanned — that is what makes "skip anything starting with a dot" fail here
    instead of passing C2 for free.
    """
    write(isolate, "docs/design.md", "ours\n")
    write(isolate, f"docs/notes/{BRANCH}/deep/design.md", "also ours\n")
    write(isolate, ".github/CONTRIBUTING.md", "ours as well\n")
    assert scanned(isolate) == [".github/CONTRIBUTING.md",
                               "docs/design.md",
                               f"docs/notes/{BRANCH}/deep/design.md"]


# --- G1: exclusion still applies to descendants of ROOT --------------------

def test_g1_an_excluded_directory_inside_root_is_still_skipped(isolate):
    """Regression guard: relaxing the ROOT-path match must not relax the
    ordinary case it exists for — `.worktrees/` *below* ROOT stays skipped.
    """
    write(isolate, "docs/design.md", "ours\n")
    write(isolate, f".worktrees/{BRANCH}/docs/design.md", "theirs\n")
    write(isolate, "node_modules/pkg/README.md", "vendored\n")
    assert scanned(isolate) == ["docs/design.md"]


# --- G4: ROOT never excludes itself via its own `.git` ---------------------

def test_g4_a_dot_git_entry_at_root_does_not_exclude_root(tmp_path, monkeypatch):
    """A main checkout has `.git` as a directory, a worktree as a file; ROOT
    always carries one. A naive "skip any directory holding a `.git` entry" rule
    would therefore exclude ROOT and scan zero files. Both spellings, asserted
    absolutely so this has teeth today.
    """
    checkout = build_tree(point_root_at(monkeypatch, tmp_path / "plain" / "checkout"))
    (checkout / ".git").mkdir()
    assert scanned(checkout) == TREE_FILES

    worktree = build_tree(point_root_at(monkeypatch, tmp_path / "plain" / "worktree"))
    (worktree / ".git").write_text("gitdir: /elsewhere/repo/.git/worktrees/wt\n")
    assert scanned(worktree) == TREE_FILES


def test_g4_a_dot_git_entry_at_root_changes_nothing_under_an_excluded_name(
        tmp_path, monkeypatch):
    """The same guard where the two defects meet: a worktree ROOT has *both* an
    excluded component in its path and a `.git` file of its own. Stated as an
    invariance — a `.git` entry at ROOT must not change what ROOT scans — because
    the absolute expectation is C1's job, not this guard's. Vacuous while C1
    fails (both sides empty); load-bearing the moment C1 passes.
    """
    base = tmp_path / ".worktrees"
    without = build_tree(point_root_at(monkeypatch, base / (BRANCH + "-nogit")))
    baseline = scanned(without)

    with_git = build_tree(point_root_at(monkeypatch, base / (BRANCH + "-git")))
    (with_git / ".git").write_text("gitdir: /elsewhere/repo/.git/worktrees/wt\n")
    assert scanned(with_git) == baseline
