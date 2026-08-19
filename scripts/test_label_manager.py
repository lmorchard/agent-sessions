"""Tests for `label_manager` — written after a live run broke on it.

`park` used to remove the interactive label and all three attempt labels
unconditionally. `gh issue edit --remove-label X` exits 0 when the *issue* lacks X
but the repo has it — a gotcha already recorded in findings.md — but **errors when
the repo itself has no such label**, which is a different case and the one that
fired. A fresh target repo has only the labels something has already created, so
the driver's own park failed with `'agent-session:needs-human-interactive' not
found` and warned that the issue stayed selectable.

It was harmless that time only because the agent's write manifest had already
applied the park label. A run whose agent recorded no label entry would have been
left selectable, re-run, and burned budget on a loop the breaker could not stop.

There were no tests here at all before this file, which is why three commands
carried the same bug.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from agent_sessions.scripts import label_manager  # noqa: E402

REPO = "owner/repo"


class FakeGh:
    """Records `gh` calls; refuses to remove a label the repo does not have, the
    way the real one does."""

    def __init__(self, *, repo_labels=(), issue_labels=()):
        self.repo_labels = set(repo_labels)
        self.issue_labels = list(issue_labels)
        self.calls: list[list[str]] = []

    def __call__(self, cmd, repo=None):
        self.calls.append(list(cmd))
        if cmd[:2] == ["label", "create"]:
            self.repo_labels.add(cmd[2])
            return ""
        if cmd[:2] == ["issue", "view"]:
            # The real call passes `--jq .labels[].name`, so it gets bare names on
            # separate lines -- not JSON. A fake that ignores the jq expression
            # returns something the caller silently parses as zero labels.
            assert "--jq" in cmd, f"unexpected issue view without --jq: {cmd}"
            return "\n".join(self.issue_labels)
        if cmd[:2] == ["issue", "edit"]:
            for i, tok in enumerate(cmd):
                if tok == "--remove-label" and cmd[i + 1] not in self.repo_labels:
                    raise RuntimeError(
                        f"gh command failed: failed to update: '{cmd[i + 1]}' not found"
                    )
            for i, tok in enumerate(cmd):
                if tok == "--add-label" and cmd[i + 1] not in self.issue_labels:
                    self.issue_labels.append(cmd[i + 1])
                elif tok == "--remove-label" and cmd[i + 1] in self.issue_labels:
                    self.issue_labels.remove(cmd[i + 1])
            return ""
        return ""


def args(**kw):
    import argparse

    ns = argparse.Namespace(issue=198, repo=REPO, interactive=False, current_labels=None, count=1)
    for k, v in kw.items():
        setattr(ns, k, v)
    return ns


@pytest.fixture
def gh(monkeypatch):
    fake = FakeGh(
        repo_labels={"agent-session:spec", "agent-session:needs-human", "agent-session:attempt-1", "enhancement"},
        issue_labels=["enhancement", "agent-session:attempt-1"],
    )
    monkeypatch.setattr(label_manager, "run_gh", fake)
    return fake


def removed(gh):
    out = []
    for cmd in gh.calls:
        for i, tok in enumerate(cmd):
            if tok == "--remove-label":
                out.append(cmd[i + 1])
    return out


# -- the live failure --------------------------------------------------------


def test_park_survives_a_repo_missing_the_interactive_and_higher_attempt_labels(gh):
    """The exact configuration that failed: the repo has `needs-human` and
    `attempt-1`, and nothing else the park wants to remove."""
    label_manager.cmd_park(args())
    assert "agent-session:needs-human" in gh.issue_labels


def test_park_only_removes_labels_the_issue_actually_carries(gh):
    label_manager.cmd_park(args())
    assert removed(gh) == []
    assert "agent-session:needs-human-interactive" not in removed(gh)


def test_park_preserves_the_attempt_label(gh):
    """Parking pauses an attempt sequence; it does not start a new one."""
    label_manager.cmd_park(args())
    assert "agent-session:attempt-1" in gh.issue_labels


def test_unpark_removes_parking_but_preserves_the_attempt_label(gh):
    gh.issue_labels.append("agent-session:needs-human")
    label_manager.cmd_unpark(args())
    assert removed(gh) == ["agent-session:needs-human"]
    assert "agent-session:attempt-1" in gh.issue_labels


def test_clear_attempts_survives_the_same_repo(gh):
    label_manager.cmd_clear_attempts(args())
    assert removed(gh) == ["agent-session:attempt-1"]


def test_an_issue_with_nothing_to_remove_issues_no_remove_flags(gh):
    gh.issue_labels = ["enhancement"]
    label_manager.cmd_clear_attempts(args())
    assert removed(gh) == []


def test_the_fake_reproduces_the_real_failure():
    """The control. If the fake tolerates a missing repo label, none of the above
    is testing anything."""
    fake = FakeGh(repo_labels={"a"}, issue_labels=[])
    with pytest.raises(RuntimeError, match="not found"):
        fake(["issue", "edit", "1", "--remove-label", "missing"])
