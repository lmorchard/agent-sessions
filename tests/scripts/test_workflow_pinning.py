"""Frozen acceptance checks for #261 H2 — every workflow action is pinned by SHA.

`.github/workflows/check.yml` took three actions on mutable major tags, one of them
eight majors stale and from a third party:

    actions/checkout      uses v4   latest v7.0.1
    actions/setup-python  uses v5   latest v7.0.0
    astral-sh/setup-uv    uses v2   latest v10.0.1

**A mutable tag is a tag someone else can move.** `CLAUDE.md` gates `.github/**`
*"because they define the environment the checks run in"* -- so a directory whose whole
justification for being human-reviewed is that it controls the checks was resolving three
of its four steps at run time, against refs this project does not own. That is the
loudest internal inconsistency the audit found, and it is the one an attacker upstream
would use.

**These checks grade the ref's shape, not a list of names.** Naming the three current
actions here would rot the moment a fourth arrived, and would be a spelling check rather
than a test. So they discover every `uses:` in every workflow and require each to resolve
to a 40-hex commit. Add a step, and it is graded with no edit here.

The trailing `# v7.0.1` comments in the workflow are for a human reading the diff. They
are deliberately *not* graded: a comment that has to agree with a SHA is a second thing
to keep in sync, and this project's whole documentation rule is that a doc must not state
a fact a command can print.

C2 and C3 are the controls, and they matter more than usual here, because C1 alone is
satisfied by a workflow directory containing no workflows.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

#: `uses: owner/repo@ref`, and the `docker://` / `./local-action` forms that carry no ref.
_USES = re.compile(r"^\s*(?:-\s*)?uses:\s*(?P<value>\S+)", re.MULTILINE)
_SHA = re.compile(r"^[0-9a-f]{40}$")


def _workflow_files() -> list[Path]:
    return sorted(p for p in WORKFLOWS.glob("*.y*ml"))


def _uses_refs() -> list[tuple[Path, str]]:
    found = []
    for p in _workflow_files():
        for m in _USES.finditer(p.read_text(encoding="utf-8")):
            found.append((p, m.group("value")))
    return found


def test_every_third_party_action_is_pinned_to_a_commit():
    """C1. No `@v4`, no `@main`, no floating ref of any kind."""
    unpinned = []
    for path, value in _uses_refs():
        if value.startswith(("./", "docker://")):
            continue  # a local action or an image; neither has a git ref to pin
        _, _, ref = value.partition("@")
        if not _SHA.match(ref):
            unpinned.append(f"{path.relative_to(REPO_ROOT)}: {value}")
    assert not unpinned, (
        "these actions resolve at run time against a ref this project does not own:\n  "
        + "\n  ".join(unpinned)
    )


def test_there_is_a_workflow_to_grade():
    """C2, the control. C1 passes vacuously over an empty directory."""
    assert _workflow_files(), f"no workflow files under {WORKFLOWS}"


def test_the_uses_pattern_finds_the_steps_that_are_there():
    """C3, the second control. C1 also passes if the pattern stops matching.

    A workflow with steps but no discovered `uses:` means the regex has drifted from the
    file's shape, which would read as a clean bill over nothing -- the null-as-positive
    this project exists to catch.
    """
    for path in _workflow_files():
        text = path.read_text(encoding="utf-8")
        if "uses:" in text:
            assert any(p == path for p, _ in _uses_refs()), (
                f"{path.relative_to(REPO_ROOT)} contains `uses:` lines that the "
                f"discovery pattern does not match"
            )


def test_the_checkout_step_keeps_a_full_clone():
    """`commit-lint` scopes to `origin/main..HEAD`, so a shallow clone grades nothing.

    Asserted because it is the one input in this file whose loss is silent: a shallow
    clone does not fail the checkout, and `commit-lint` over an empty range prints a pass.
    """
    for path in _workflow_files():
        text = path.read_text(encoding="utf-8")
        if "actions/checkout@" not in text:
            continue
        assert "fetch-depth: 0" in text, (
            f"{path.relative_to(REPO_ROOT)} checks out shallowly; commit-lint's "
            f"origin/main..HEAD range would be empty and pass"
        )
