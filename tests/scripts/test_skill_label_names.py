"""Frozen acceptance checks for #261 C6 — skill files name only labels that exist.

`triage.md` told a run to record two labels the harness has never heard of:
`agent-session:needs-details`, which appears nowhere in `src/`, and
`agent-session:interactive`, whose real name is `agent-session:needs-human-interactive`.

That is not a typo with a cosmetic cost. `writes.py` executes a `label` entry as **one**
`gh issue edit` carrying every `--add-label`, with no ensure-exists, and `gh` errors when
the repository has no such label. So the whole edit fails, `write-manifest.md`'s
all-or-nothing rule stops the rest of the manifest, and **the issue is never parked** —
it stays selectable and the loop picks it up again, having just decided it needed a human.

Nothing caught it because `docs_check` only sees `[text](target)` markdown links and the
skill cites everything in backticks. This is that gap closed for label names specifically:
a backticked `agent-session:*` string in any skill file has to be one the driver knows.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_sessions.driver import labels

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL = REPO_ROOT / "skills" / "agent-session"

#: Any backticked `agent-session:<name>` token in prose.
_LABEL_TOKEN = re.compile(r"`(agent-session:[a-z0-9-]+)`")

#: Names that are not labels. `agent-session:spec` also exists as an HTML comment marker,
#: and `agent-session:gate` names the machine-readable block in a PR body — neither is
#: applied to an issue, so neither belongs in the vocabulary.
NON_LABEL_TOKENS = {"agent-session:gate"}


def known_labels() -> set[str]:
    vocab = {
        v for name in dir(labels)
        if name.isupper() and isinstance(v := getattr(labels, name), str) and v.startswith("agent-session:")
    }
    vocab.update(labels.ATTEMPT_LABELS)
    return vocab


def skill_files() -> list[Path]:
    return sorted(p for p in SKILL.rglob("*.md"))


def test_there_are_skill_files_and_labels_to_check():
    """Control. Both sides of every check below can silently become empty."""
    assert skill_files()
    assert len(known_labels()) >= 5, known_labels()


@pytest.mark.parametrize("path", skill_files(), ids=lambda p: p.name)
def test_every_label_a_skill_file_names_is_one_the_driver_knows(path):
    """C1. An unknown name here fails the whole `gh issue edit` that carries it."""
    named = {m.group(1) for m in _LABEL_TOKEN.finditer(path.read_text(encoding="utf-8"))}
    unknown = sorted(named - known_labels() - NON_LABEL_TOKENS)
    assert not unknown, (
        f"{path.relative_to(SKILL)} names label(s) the harness does not define: {unknown}. "
        f"`writes.py` applies every add in one `gh issue edit`, so an unknown name fails the "
        f"whole entry and the manifest stops -- the issue is never labelled at all."
    )


def test_the_check_would_notice_an_invented_label(tmp_path):
    """C2, the control. C1 passes over a file with no labels in it at all."""
    invented = {m.group(1) for m in _LABEL_TOKEN.finditer("record `agent-session:needs-details`")}
    assert invented - known_labels() == {"agent-session:needs-details"}
