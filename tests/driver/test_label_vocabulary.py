"""Frozen acceptance checks for #261 T3 — the label vocabulary has one definition.

The constants were defined three times (`label_manager.py`, `parking.py`, `router.py`)
and `router.py` additionally reimplemented `is_specced` with the label name and the body
marker inlined as string literals. A rename needed four edits.

**Missing one fails open.** An issue silently stops being selected, or silently stops
being recognised as parked, and nothing errors — the driver cannot tell "no eligible
work" from "I am looking for a label nobody applies". That is defect class 2 with the
queue as its subject, and the queue is the thing the whole harness is for.

These checks are written so that a re-inlined literal fails them, which is the only
failure mode worth guarding: nothing stops someone typing the string again, so what has
to be caught is the *second* definition disagreeing with the first.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from agent_sessions.driver import labels, parking, router
from agent_sessions.scripts import label_manager

REPO_ROOT = Path(__file__).resolve().parents[2]
DRIVER = REPO_ROOT / "src" / "agent_sessions" / "driver"
SCRIPTS = REPO_ROOT / "src" / "agent_sessions" / "scripts"

#: Every module that consumes the vocabulary, and the object to read it from.
CONSUMERS = {"parking": parking, "router": router, "label_manager": label_manager}

VOCABULARY = {
    name: getattr(labels, name)
    for name in dir(labels)
    if name.isupper() and isinstance(getattr(labels, name), str)
}


def test_the_vocabulary_is_not_empty():
    """Control. Every check below is vacuous over an empty vocabulary."""
    assert len(VOCABULARY) >= 5, VOCABULARY


@pytest.mark.parametrize("module_name", sorted(CONSUMERS))
def test_every_consumer_agrees_with_the_owning_module(module_name):
    """C1. A consumer that re-declares a constant must not disagree with `labels.py`."""
    module = CONSUMERS[module_name]
    for name, value in VOCABULARY.items():
        seen = getattr(module, name, None)
        if seen is None:
            continue
        assert seen == value, (
            f"{module_name}.{name} is {seen!r} but labels.{name} is {value!r} -- a rename "
            f"was applied in one place and not the other, and nothing else would say so"
        )


#: Module-level names whose value is inert content rather than behaviour. `writes.EXAMPLES`
#: is one valid manifest entry per kind; it doubles as the documentation an agent is shown
#: and as the corpus the write tests sweep, so its label strings are *illustrations of what
#: an agent would write*, not uses. This is the inert-content false-positive class that
#: `docs_check`'s own docstring records hitting, and the answer is the same shape: exclude
#: the named subtree, never the whole file, so a behavioural literal elsewhere in the same
#: module is still caught.
INERT_ASSIGNMENTS = {"EXAMPLES"}


def _string_literals(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    inert: set[int] = set()
    for node in ast.walk(tree):
        targets = getattr(node, "targets", None) or ([node.target] if hasattr(node, "target") else [])
        if any(isinstance(t, ast.Name) and t.id in INERT_ASSIGNMENTS for t in targets):
            inert.update(id(sub) for sub in ast.walk(node))
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in inert
    }


@pytest.mark.parametrize(
    "path",
    sorted(
        p
        for p in list(DRIVER.glob("*.py")) + list(SCRIPTS.glob("*.py"))
        if p.name != "labels.py"
    ),
    ids=lambda p: p.name,
)
def test_no_shipping_module_hardcodes_a_label_name(path):
    """C2. The one that catches the defect coming back.

    C1 only fires if someone re-declares the *constant*. `router.py`'s version did not:
    it wrote `"agent-session:spec"` straight into an `if`, where no constant comparison
    could ever reach it. So this reads the AST and requires the literal to appear in
    `labels.py` and nowhere else.
    """
    hardcoded = sorted(_string_literals(path) & set(VOCABULARY.values()))
    assert not hardcoded, (
        f"{path.name} hardcodes {hardcoded}. Import them from "
        f"`agent_sessions.driver.labels` -- a literal here is invisible to a rename."
    )


def test_is_specced_has_one_implementation():
    """C3. `router` used to carry a second copy that could not see `labels.MARKER`."""
    assert router.is_specced is labels.is_specced
    assert parking.is_specced is labels.is_specced


def test_is_specced_honours_the_label_and_the_marker():
    """Both carriers, because issues specced before the label existed have only one."""
    assert labels.is_specced({"labels": [{"name": labels.SPEC_LABEL}], "body": ""})
    assert labels.is_specced({"labels": [], "body": f"text {labels.MARKER} more"})
    assert not labels.is_specced({"labels": [{"name": "P1"}], "body": "no marker"})
    assert not labels.is_specced({})
