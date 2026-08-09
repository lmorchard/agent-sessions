import json
import pytest
from unittest.mock import patch, MagicMock

from discussion_manager import (
    ensure_category,
    get_or_create_daily_discussion,
    post_start,
    post_finish,
)


def test_ensure_category_success():
    def mock_run_gh(args):
        if "repo" in args:
            return 0, "R_123", ""
        if "graphql" in args:
            return 0, json.dumps({"data": {"createDiscussionCategory": {"discussionCategory": {"id": "DC_1"}}}}), ""
        return 1, "", "error"

    with patch("discussion_manager.run_gh", side_effect=mock_run_gh):
        assert ensure_category("owner/repo") is True


def test_ensure_category_already_exists():
    def mock_run_gh(args):
        if "repo" in args:
            return 0, "R_123", ""
        if "graphql" in args:
            return 1, "", "Name already exists"
        return 1, "", "error"

    with patch("discussion_manager.run_gh", side_effect=mock_run_gh):
        assert ensure_category("owner/repo") is True


def test_get_or_create_daily_discussion_finds_existing():
    sample_json = json.dumps([{"title": "Lab Notebook: 2026-08-09", "url": "https://github.com/owner/repo/discussions/10"}])

    def mock_run_gh(args):
        if "discussion" in args and "list" in args:
            return 0, sample_json, ""
        return 1, "", "error"

    with patch("discussion_manager.run_gh", side_effect=mock_run_gh):
        url = get_or_create_daily_discussion("owner/repo")
        assert url == "https://github.com/owner/repo/discussions/10"


def test_get_or_create_daily_discussion_creates_new():
    def mock_run_gh(args):
        if "discussion" in args and "list" in args:
            return 0, "[]", ""
        if "discussion" in args and "create" in args:
            return 0, "https://github.com/owner/repo/discussions/11\n", ""
        return 1, "", "error"

    with patch("discussion_manager.run_gh", side_effect=mock_run_gh):
        url = get_or_create_daily_discussion("owner/repo")
        assert url == "https://github.com/owner/repo/discussions/11"


def test_post_start():
    calls = []

    def mock_run_gh(args):
        calls.append(args)
        if "list" in args:
            return 0, json.dumps([{"title": "Lab Notebook: 2026-08-09", "url": "https://github.com/owner/repo/discussions/10"}]), ""
        if "comment" in args:
            return 0, "commented", ""
        return 1, "", "error"

    with patch("discussion_manager.run_gh", side_effect=mock_run_gh):
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
            return 0, json.dumps([{"title": "Lab Notebook: 2026-08-09", "url": "https://github.com/owner/repo/discussions/10"}]), ""
        if "comment" in args:
            return 0, "commented", ""
        return 1, "", "error"

    with patch("discussion_manager.run_gh", side_effect=mock_run_gh):
        ok = post_finish("owner/repo", "123", "execute", "gate-eligible", "1.25", "sess-123", "https://github.com/pr", "all good", str(rundir))
        assert ok is True
        comment_calls = [c for c in calls if "comment" in c]
        assert len(comment_calls) == 1
        body = comment_calls[0][-1]
        assert "Hello narrative" in body
