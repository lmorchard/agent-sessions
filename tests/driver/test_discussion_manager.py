import json
from datetime import datetime, timezone
from unittest.mock import patch

from agent_sessions.driver.discussion_manager import (
    check_category,
    ensure_category,
    get_or_create_daily_discussion,
    post_finish,
    post_start,
)

MODULE_PATH = "agent_sessions.driver.discussion_manager"


def _today_title() -> str:
    return f"Lab Notebook: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"


def test_check_category_present():
    def mock_run_gh(args):
        if "graphql" in args:
            return 0, json.dumps({"data": {"repository": {"discussionCategories": {"nodes": [{"name": "Lab Notebook"}]}}}}), ""
        return 1, "", "error"

    with patch(f"{MODULE_PATH}.run_gh", side_effect=mock_run_gh):
        assert check_category("owner/repo", "Lab Notebook") is True
        assert ensure_category("owner/repo", "Lab Notebook") is True


def test_check_category_absent_and_no_mutation_attempted(capsys):
    calls = []

    def mock_run_gh(args):
        calls.append(args)
        if "graphql" in args:
            return 0, json.dumps({"data": {"repository": {"discussionCategories": {"nodes": [{"name": "General"}]}}}}), ""
        return 1, "", "error"

    with patch(f"{MODULE_PATH}.run_gh", side_effect=mock_run_gh):
        assert check_category("owner/repo", "Lab Notebook") is False
        stderr = capsys.readouterr().err
        assert "Lab Notebook" in stderr
        assert "created by hand" in stderr
        # Assert no create/mutation call was issued
        assert not any("mutation" in str(arg).lower() or "creatediscussion" in str(arg).lower() for c in calls for arg in c)


def test_get_or_create_daily_discussion_finds_existing():
    sample_json = json.dumps([{"title": _today_title(), "url": "https://github.com/owner/repo/discussions/10"}])

    def mock_run_gh(args):
        if "discussion" in args and "list" in args:
            return 0, sample_json, ""
        return 1, "", "error"

    with patch(f"{MODULE_PATH}.run_gh", side_effect=mock_run_gh):
        url = get_or_create_daily_discussion("owner/repo")
        assert url == "https://github.com/owner/repo/discussions/10"


def test_get_or_create_daily_discussion_creates_new():
    def mock_run_gh(args):
        if "discussion" in args and "list" in args:
            return 0, "[]", ""
        if "discussion" in args and "create" in args:
            return 0, "https://github.com/owner/repo/discussions/11\n", ""
        return 1, "", "error"

    with patch(f"{MODULE_PATH}.run_gh", side_effect=mock_run_gh):
        url = get_or_create_daily_discussion("owner/repo")
        assert url == "https://github.com/owner/repo/discussions/11"


def test_post_start():
    calls = []

    def mock_run_gh(args):
        calls.append(args)
        if "list" in args:
            return 0, json.dumps([{"title": _today_title(), "url": "https://github.com/owner/repo/discussions/10"}]), ""
        if "comment" in args:
            return 0, "commented", ""
        return 1, "", "error"

    with patch(f"{MODULE_PATH}.run_gh", side_effect=mock_run_gh):
        ok = post_start("owner/repo", "123", "execute", "10", "/tmp/rundir")
        assert ok is True
        comment_calls = [c for c in calls if "comment" in c]
        assert len(comment_calls) == 1
        body = comment_calls[0][-1]
        assert "Starting Work: Issue #123 (execute)" in body


def test_post_finish(tmp_path):
    rundir = tmp_path / "run1"
    rundir.mkdir()
    (rundir / "final.txt").write_text("Hello narrative")

    calls = []

    def mock_run_gh(args):
        calls.append(args)
        if "list" in args:
            return 0, json.dumps([{"title": _today_title(), "url": "https://github.com/owner/repo/discussions/10"}]), ""
        if "comment" in args:
            return 0, "commented", ""
        return 1, "", "error"

    with patch(f"{MODULE_PATH}.run_gh", side_effect=mock_run_gh):
        ok = post_finish("owner/repo", "123", "execute", "gate-eligible", "1.25", "sess-123", "https://github.com/pr", "all good", str(rundir))
        assert ok is True
        comment_calls = [c for c in calls if "comment" in c]
        assert len(comment_calls) == 1
        body = comment_calls[0][-1]
        assert "Hello narrative" in body
