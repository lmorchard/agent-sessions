"""The skill may not instruct a GitHub write it can no longer perform (issue #191).

Under the board-driver the agent holds a read-scoped credential, so a phase file that
says `gh issue comment ...` is instructing a command that will fail with a 403. Worse,
it will fail *silently from the loop's point of view*: the park comment simply never
appears, and the run looks like it declined to explain itself.

This is a lint, not a proof. It reads the phase files as text and cannot tell an
instruction from a prohibition, so a line that *names* a write command is allowed when
it also names the manifest or explicitly says the command is unavailable. Deliberately
loose in that one direction; the tight direction is the one that matters.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PHASES = sorted((Path(__file__).resolve().parents[2] / "skills" / "agent-session" / "phases").glob("*.md"))

#: Commands that write to GitHub, and are therefore refused by a read-scoped token.
WRITE_COMMANDS = (
    "gh issue comment",
    "gh issue create",
    "gh issue edit",
    "gh pr create",
    "gh pr edit",
    "gh pr comment",
    "gh pr merge",
    "gh pr review",
    "gh label create",
    "gh project item-add",
    "gh project item-edit",
    "gh api graphql -f mutation",
    "label_manager.py",
    "git push",
)

#: A line naming a write command is fine when it is telling the agent *not* to run it,
#: or pointing at the manifest that replaces it.
EXEMPTING = (
    "write-manifest",
    "cannot",
    "Do not ",
    "Never ",
    "never ",
    "no GitHub write",
    "will be refused",
)


def offending_lines(path: Path) -> list[tuple[int, str]]:
    out = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not any(cmd in line for cmd in WRITE_COMMANDS):
            continue
        if any(marker in line for marker in EXEMPTING):
            continue
        out.append((lineno, line.strip()))
    return out


def test_the_phase_directory_was_actually_found():
    assert PHASES, "no phase files found; this lint would pass vacuously"


@pytest.mark.parametrize("phase", PHASES, ids=lambda p: p.name)
def test_no_phase_instructs_a_github_write_directly(phase: Path):
    offenders = offending_lines(phase)
    assert not offenders, (
        f"{phase.name} instructs a GitHub write the agent's read-scoped token cannot perform.\n"
        "Record it as a write-manifest entry instead -- see "
        "skills/agent-session/references/write-manifest.md.\n"
        + "\n".join(f"  line {n}: {text}" for n, text in offenders)
    )


def test_the_manifest_reference_exists_and_lists_every_kind():
    """The doc the phases now point at has to agree with the code they run under."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
    from agent_sessions.driver import writes

    doc = (
        Path(__file__).resolve().parents[2]
        / "skills" / "agent-session" / "references" / "write-manifest.md"
    ).read_text(encoding="utf-8")

    missing = [kind for kind in writes.KINDS if f"`{kind}`" not in doc]
    assert not missing, f"write-manifest.md does not document these kinds: {missing}"


def test_the_lint_can_fail(tmp_path: Path):
    """A lint nobody has seen fail is a lint nobody knows the polarity of."""
    bad = tmp_path / "bad.md"
    bad.write_text("Post a comment with `gh issue comment <n> --body ...`.\n", encoding="utf-8")
    assert offending_lines(bad)

    good = tmp_path / "good.md"
    good.write_text("Record an `issue_comment` entry -- see `references/write-manifest.md`.\n", encoding="utf-8")
    assert not offending_lines(good)
