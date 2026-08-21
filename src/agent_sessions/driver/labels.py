"""The label vocabulary, in one place.

Why this module exists
----------------------
These constants were defined three times -- `label_manager.py`, `parking.py` and
`router.py` -- and `router.py` additionally reimplemented `parking.is_specced` with the
label name and the marker inlined as literals. A rename therefore needed four edits, and
**missing one fails open**: an issue silently stops being selected, or silently stops
being recognised as parked, with no error anywhere. The driver has no way to tell "no
eligible work" from "I am looking for a label nobody applies", which is defect class 2
with the queue as its subject.

`scripts/` already imports from `driver/` in four places, so the vocabulary lives on the
driver side and `label_manager` reads it rather than restating it.

**Adding a label here is a decision, not a detail.** The set is the interface between the
driver, the skill and whatever a human does by hand in the GitHub UI; `usage.md` documents
it for operators, and `writes.py` gates which of them an agent may request.
"""

from __future__ import annotations

#: Stamped by `intake` and `triage` once an issue carries verifiable criteria. The
#: producer/consumer seam: the working modes refuse to run without it.
SPEC_LABEL = "agent-session:spec"

#: The tier, derived rather than chosen. Controls *where a run surfaces to a human*.
AUTO_OK_LABEL = "agent-session:auto-ok"
NEEDS_REVIEW_LABEL = "agent-session:needs-review"

#: Parked: excluded from selection until a human or a later run clears it.
PARK_LABEL = "agent-session:needs-human"

#: Parked *and* needing a person at a keyboard rather than an asynchronous answer.
INTERACTIVE_LABEL = "agent-session:needs-human-interactive"

#: The gate reached `eligible-for-auto-merge`. A finding the system reports, never an
#: action it takes -- nothing in this repo merges by machine.
MERGE_READY_LABEL = "agent-session:merge-ready"

#: The loop breaker. `MAX_PHASE_ATTEMPTS` reached on any of these parks the issue.
ATTEMPT_LABELS = [
    "agent-session:attempt-1",
    "agent-session:attempt-2",
    "agent-session:attempt-3",
]

#: The body marker, the pre-label carrier of the same fact. Both are honoured because
#: issues specced before the label existed still carry only this.
MARKER = "<!-- agent-session:spec -->"


def is_specced(iss: dict) -> bool:
    """True if the issue has been through intake or triage.

    Label *or* marker. `rethink` retires the marker and relies on this returning False
    afterwards, which it does not if the label is still applied -- recorded on #261 as
    K2, and not fixed here because it is a `skills/**` change.
    """
    labels = [lbl.get("name") for lbl in iss.get("labels", []) if isinstance(lbl, dict)]
    return SPEC_LABEL in labels or MARKER in (iss.get("body") or "")
