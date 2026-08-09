"""Tests for scripts/label_manager.py."""

import sys
from pathlib import Path
from unittest.mock import call, patch

import pytest

SYS_PATH_PARENT = str(Path(__file__).resolve().parent)
if SYS_PATH_PARENT not in sys.path:
    sys.path.insert(0, SYS_PATH_PARENT)

from agent_sessions.scripts import label_manager as lm  # noqa: E402


@pytest.fixture
def mock_run_gh():
    with patch.object(lm, "run_gh") as mock:
        mock.return_value = ""
        yield mock


def test_cmd_spec(mock_run_gh):
    ret = lm.main(["--repo", "owner/repo", "--current-labels", "", "spec", "--issue", "42"])
    assert ret == 0
    assert mock_run_gh.call_count == 2
    mock_run_gh.assert_has_calls([
        call(["label", "create", "agent-session:spec", "--color", "0E8A16", "--description", "Verifiable EARS criteria & tier applied"], repo="owner/repo"),
        call([
            "issue", "edit", "42",
            "--add-label", "agent-session:spec",
            "--remove-label", "agent-session:needs-human",
            "--remove-label", "agent-session:needs-human-interactive",
            "--remove-label", "agent-session:attempt-1",
            "--remove-label", "agent-session:attempt-2",
            "--remove-label", "agent-session:attempt-3"
        ], repo="owner/repo"),
    ])


def test_cmd_park_default(mock_run_gh):
    ret = lm.main(["--repo", "owner/repo", "--current-labels", "", "park", "--issue", "42"])
    assert ret == 0
    assert mock_run_gh.call_count == 2
    mock_run_gh.assert_has_calls([
        call(["label", "create", "agent-session:needs-human", "--color", "FBCA04", "--description", "the agent-session driver parked this issue"], repo="owner/repo"),
        call([
            "issue", "edit", "42",
            "--add-label", "agent-session:needs-human",
            "--remove-label", "agent-session:needs-human-interactive",
            "--remove-label", "agent-session:attempt-1",
            "--remove-label", "agent-session:attempt-2",
            "--remove-label", "agent-session:attempt-3"
        ], repo="owner/repo"),
    ])


def test_cmd_park_interactive(mock_run_gh):
    ret = lm.main(["--repo", "owner/repo", "--current-labels", "", "park", "--issue", "42", "--interactive"])
    assert ret == 0
    assert mock_run_gh.call_count == 3
    mock_run_gh.assert_has_calls([
        call(["label", "create", "agent-session:needs-human", "--color", "FBCA04", "--description", "the agent-session driver parked this issue"], repo="owner/repo"),
        call(["label", "create", "agent-session:needs-human-interactive", "--color", "D4C5F9", "--description", "interactive CLI session required"], repo="owner/repo"),
        call([
            "issue", "edit", "42",
            "--add-label", "agent-session:needs-human-interactive",
            "--remove-label", "agent-session:needs-human",
            "--remove-label", "agent-session:attempt-1",
            "--remove-label", "agent-session:attempt-2",
            "--remove-label", "agent-session:attempt-3"
        ], repo="owner/repo"),
    ])


def test_cmd_unpark(mock_run_gh):
    ret = lm.main(["--repo", "owner/repo", "--current-labels", "", "unpark", "--issue", "42"])
    assert ret == 0
    mock_run_gh.assert_called_once_with([
        "issue", "edit", "42",
        "--remove-label", "agent-session:needs-human",
        "--remove-label", "agent-session:needs-human-interactive",
        "--remove-label", "agent-session:attempt-1",
        "--remove-label", "agent-session:attempt-2",
        "--remove-label", "agent-session:attempt-3"
    ], repo="owner/repo")


def test_cmd_attempt(mock_run_gh):
    ret = lm.main(["--repo", "owner/repo", "--current-labels", "", "attempt", "--issue", "42", "--count", "2"])
    assert ret == 0
    assert mock_run_gh.call_count == 2
    mock_run_gh.assert_has_calls([
        call(["label", "create", "agent-session:attempt-2", "--color", "D93F0B", "--description", "Execution attempt counter"], repo="owner/repo"),
        call([
            "issue", "edit", "42",
            "--add-label", "agent-session:attempt-2",
            "--remove-label", "agent-session:needs-human",
            "--remove-label", "agent-session:needs-human-interactive",
            "--remove-label", "agent-session:attempt-1",
            "--remove-label", "agent-session:attempt-3"
        ], repo="owner/repo"),
    ])


def test_cmd_clear_attempts(mock_run_gh):
    ret = lm.main(["--repo", "owner/repo", "--current-labels", "", "clear-attempts", "--issue", "42"])
    assert ret == 0
    mock_run_gh.assert_called_once_with([
        "issue", "edit", "42",
        "--remove-label", "agent-session:attempt-1",
        "--remove-label", "agent-session:attempt-2",
        "--remove-label", "agent-session:attempt-3"
    ], repo="owner/repo")


def test_cmd_merge_ready(mock_run_gh):
    ret = lm.main(["--repo", "owner/repo", "--current-labels", "", "merge-ready", "--issue", "42"])
    assert ret == 0
    assert mock_run_gh.call_count == 2
    mock_run_gh.assert_has_calls([
        call(["label", "create", "agent-session:merge-ready", "--color", "2E8A16", "--description", "Eligible for auto-merge"], repo="owner/repo"),
        call([
            "issue", "edit", "42",
            "--add-label", "agent-session:merge-ready",
            "--remove-label", "agent-session:needs-human",
            "--remove-label", "agent-session:needs-human-interactive",
            "--remove-label", "agent-session:attempt-1",
            "--remove-label", "agent-session:attempt-2",
            "--remove-label", "agent-session:attempt-3"
        ], repo="owner/repo"),
    ])


def test_invalid_transition_spec_when_parked(capsys, mock_run_gh):
    ret = lm.main(["--repo", "owner/repo", "--current-labels", "agent-session:needs-human", "spec", "--issue", "42"])
    assert ret == 1
    captured = capsys.readouterr()
    assert "Transition Error" in captured.err
    assert "currently parked" in captured.err
    mock_run_gh.assert_not_called()


def test_invalid_transition_attempt_when_parked(capsys, mock_run_gh):
    ret = lm.main(["--repo", "owner/repo", "--current-labels", "agent-session:needs-human", "attempt", "--issue", "42", "--count", "1"])
    assert ret == 1
    captured = capsys.readouterr()
    assert "Transition Error" in captured.err
    assert "currently parked" in captured.err
    mock_run_gh.assert_not_called()


def test_force_flag_bypasses_validation(mock_run_gh):
    ret = lm.main(["--repo", "owner/repo", "--current-labels", "agent-session:needs-human", "--force", "spec", "--issue", "42"])
    assert ret == 0
    assert mock_run_gh.call_count == 2
