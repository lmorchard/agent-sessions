"""Frozen acceptance checks for #261 — `bootstrap-repo.sh` creates the labels the driver uses.

The script is the setup path for a fresh target repository, and it was referenced by
nothing: not `src/`, not the `Makefile`, not `README.md`, not `usage.md`. Les's call was
to keep it and document it, which first means making it true. It had drifted three ways
while nobody ran it:

- it pointed at `../driver/discussion_manager.py`, a path the Python conversion left
  empty — the same dead-path class as C7;
- `agent-session:needs-human-interactive` carried `D93F0B`, the attempt counter's colour,
  where `label_manager` uses `D4C5F9`;
- `agent-session:auto-ok` and `agent-session:needs-review` were **absent**, so a freshly
  bootstrapped repository was still missing two labels the driver applies — and on a
  repository with no such label, `gh` errors the whole edit that carries it, which is the
  C6 failure arriving from the other end.

None of that could have been noticed by reading: a hand-written list in a shell script
diverging from a Python constant is invisible to every check this repo has. So the script
now reads the vocabulary from `driver/labels.py`, and this pins that it stays read.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from agent_sessions.driver import labels

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "bootstrap-repo.sh"

#: Every issue label the driver ever applies. `MARKER` is a body comment, not a label.
EXPECTED = {
    labels.SPEC_LABEL,
    labels.AUTO_OK_LABEL,
    labels.NEEDS_REVIEW_LABEL,
    labels.PARK_LABEL,
    labels.INTERACTIVE_LABEL,
    labels.MERGE_READY_LABEL,
}


def _emitted_labels() -> dict[str, str]:
    """Run the script's embedded label-spec generator and read what it emits.

    Extracted and executed rather than pattern-matched out of the shell source: the
    point is what the script *produces*, and a regex over the heredoc would be a
    spelling check on the thing this file exists to stop being a spelling check.
    """
    src = SCRIPT.read_text(encoding="utf-8")
    m = re.search(r"uv run python -c '\n(?P<code>.*?)\n'\)", src, re.S)
    assert m, "no embedded label-spec generator found in bootstrap-repo.sh"
    out = subprocess.run(
        ["uv", "run", "python", "-c", m.group("code")],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout
    return {
        line.split("\t")[0]: line.split("\t")[1]
        for line in out.splitlines()
        if line.strip()
    }


def test_the_script_still_has_a_generator_to_check():
    """Control. Every check below is vacuous if the generator is gone."""
    assert _emitted_labels()


def test_it_creates_every_label_the_driver_applies():
    """C1. Two were missing, and a missing label fails the edit that carries it."""
    missing = sorted(EXPECTED - set(_emitted_labels()))
    assert not missing, (
        f"bootstrap-repo.sh does not create {missing}. A target repo bootstrapped with it "
        f"would still error on the first edit that adds one."
    )


def test_it_invents_no_label_the_driver_does_not_know():
    """C2, the other direction. `agent-session:gate` is a PR label, not an issue label."""
    extra = sorted(set(_emitted_labels()) - EXPECTED)
    assert not extra, f"bootstrap-repo.sh creates label(s) the driver never applies: {extra}"


def test_the_colours_are_the_ones_label_manager_uses():
    """C3. The drift that was actually there, and the reason a name check is not enough.

    A label created with the wrong colour still works; it just looks wrong forever,
    because `gh label create` does not update an existing one.
    """
    emitted = _emitted_labels()
    assert emitted[labels.INTERACTIVE_LABEL] == "D4C5F9"
    assert emitted[labels.PARK_LABEL] == "FBCA04"
    assert emitted[labels.MERGE_READY_LABEL] == "2E8A16"
    assert emitted[labels.SPEC_LABEL] == "0E8A16"


def test_it_names_no_path_that_does_not_exist():
    """The dead-path class, checked for the one file the script reaches for."""
    src = SCRIPT.read_text(encoding="utf-8")
    assert "driver/discussion_manager.py" not in src, (
        "bootstrap-repo.sh names a pre-conversion path; the module is reached with -m"
    )
    assert "agent_sessions.driver.discussion_manager" in src
