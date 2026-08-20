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


import pytest

from agent_sessions.scripts import label_manager

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


# -- the three commands the original fix missed -------------------------------
#
# `removable()` was added for park/unpark/clear-attempts. `spec`, `attempt` and
# `merge-ready` build their remove lists unconditionally and were left as they were, so
# the bug the docstring above describes stayed live in three more places for as long as
# it took someone to look. Two of them are on paths the driver takes on every run:
#
#   parking.py increment_attempts  -> `attempt --count N`   (inside except Exception: pass)
#   parking.py apply_park_state    -> `merge-ready`         (inside except Exception: pass)
#
# Both swallow the failure, so on a fresh target repo the attempt counter silently never
# increments -- and the attempt counter is what stops a phase from looping forever.


def test_attempt_survives_a_repo_missing_the_higher_attempt_labels(gh):
    """The live one: `attempt --count 1` on a repo that has only attempt-1.

    The unconditional list asks to remove attempt-2, attempt-3 and the interactive
    label, none of which the repo has, so the whole edit fails -- add included.
    """
    label_manager.cmd_attempt(args(count=1))
    assert "agent-session:attempt-1" in gh.issue_labels, (
        "the attempt label never landed; the loop breaker cannot count"
    )


def test_attempt_only_removes_labels_the_issue_actually_carries(gh):
    label_manager.cmd_attempt(args(count=1))
    for label in ("agent-session:needs-human-interactive", "agent-session:attempt-2", "agent-session:attempt-3"):
        assert label not in removed(gh), f"asked to remove {label}, which the repo does not have"


def test_attempt_supersedes_the_previous_counter(gh):
    """Narrowing must not stop it clearing a counter that *is* present."""
    gh.repo_labels.add("agent-session:attempt-2")
    gh.issue_labels.append("agent-session:attempt-2")
    label_manager.cmd_attempt(args(count=1))
    assert "agent-session:attempt-2" in removed(gh)
    assert "agent-session:attempt-1" in gh.issue_labels


def test_merge_ready_survives_a_repo_missing_the_parking_and_attempt_labels(gh):
    """The other live one: the `gate-eligible` success path stamps this label."""
    label_manager.cmd_merge_ready(args())
    assert "agent-session:merge-ready" in gh.issue_labels, (
        "the success path failed to stamp merge-ready"
    )


def test_merge_ready_still_clears_a_park_the_issue_carries(gh):
    gh.issue_labels.append("agent-session:needs-human")
    label_manager.cmd_merge_ready(args(force=True))
    assert "agent-session:needs-human" in removed(gh)


def test_spec_survives_a_repo_missing_the_labels_it_wants_to_clear(gh):
    label_manager.cmd_spec(args(tier="auto-ok"))
    assert "agent-session:spec" in gh.issue_labels
    assert "agent-session:auto-ok" in gh.issue_labels


def test_spec_only_removes_labels_the_issue_actually_carries(gh):
    label_manager.cmd_spec(args(tier="auto-ok"))
    for label in ("agent-session:needs-human-interactive", "agent-session:attempt-2", "agent-session:attempt-3"):
        assert label not in removed(gh), f"asked to remove {label}, which the repo does not have"


def test_spec_clears_the_opposite_tier_when_the_issue_carries_it(gh):
    gh.repo_labels.add("agent-session:needs-review")
    gh.issue_labels.append("agent-session:needs-review")
    label_manager.cmd_spec(args(tier="auto-ok"))
    assert "agent-session:needs-review" in removed(gh)


# -- failure must not read as "no labels" -------------------------------------


def test_a_failed_label_query_raises_instead_of_reporting_no_labels(monkeypatch):
    """The null-as-positive case. `[]` means "not parked" to the transition guard."""
    def boom(cmd, repo=None):
        raise RuntimeError("gh command failed: API rate limit exceeded")

    monkeypatch.setattr(label_manager, "run_gh", boom)
    with pytest.raises(RuntimeError, match="rate limit"):
        label_manager.get_current_labels(198, repo=REPO)


def test_main_fails_closed_when_labels_cannot_be_read(monkeypatch, capsys):
    calls = []

    def boom(cmd, repo=None):
        calls.append(cmd)
        raise RuntimeError("gh command failed: HTTP 401")

    monkeypatch.setattr(label_manager, "run_gh", boom)
    rc = label_manager.main(["--repo", REPO, "spec", "--issue", "198"])

    assert rc == 1
    err = capsys.readouterr().err
    assert "could not read labels" in err
    assert "#198" in err
    assert all(c[:2] != ["issue", "edit"] for c in calls), (
        "it must not attempt an edit after failing to read the current labels"
    )


def test_an_explicit_current_labels_override_needs_no_query(monkeypatch):
    """--current-labels exists so the driver can skip the read; keep that working."""
    def boom(cmd, repo=None):
        raise AssertionError(f"should not have queried: {cmd}")

    monkeypatch.setattr(label_manager, "run_gh", boom)
    assert label_manager.get_current_labels(198, repo=REPO, override="a, b") == ["a", "b"]


def test_ensure_label_exists_tolerates_an_existing_label(monkeypatch):
    def already(cmd, repo=None):
        raise RuntimeError("gh command failed: label already exists; use --force")

    monkeypatch.setattr(label_manager, "run_gh", already)
    label_manager.ensure_label_exists("x", "0E8A16", "d", repo=REPO)  # must not raise


def test_ensure_label_exists_reraises_a_permission_failure(monkeypatch):
    """A read-only token must not look like the already-exists case."""
    def forbidden(cmd, repo=None):
        raise RuntimeError("gh command failed: HTTP 403: Resource not accessible")

    monkeypatch.setattr(label_manager, "run_gh", forbidden)
    with pytest.raises(RuntimeError, match="403"):
        label_manager.ensure_label_exists("x", "0E8A16", "d", repo=REPO)
