import json
import subprocess
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent))
import gh_query

def test_module_imports_without_site_packages():
    """Verify the module relies only on the stdlib."""
    module_path = Path(__file__).parent / "gh_query.py"
    cmd = [sys.executable, "-I", "-S", "-c", f"import sys; sys.path.insert(0, '{module_path.parent}'); import gh_query"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, f"Module failed to import without site-packages: {result.stderr}"

def test_fetch_open_prs_empty(monkeypatch):
    """Empty result is distinct from failure."""
    def mock_run(*args, **kwargs):
        class MockResult:
            stdout = ""
        return MockResult()
    monkeypatch.setattr(subprocess, "run", mock_run)
    assert gh_query.fetch_open_prs("stub/repo") == []

def test_fetch_open_prs_failure(monkeypatch):
    """Failure raises an exception."""
    def mock_run(*args, **kwargs):
        raise subprocess.CalledProcessError(1, cmd="gh", stderr="Some error")
    monkeypatch.setattr(subprocess, "run", mock_run)
    with pytest.raises(RuntimeError, match="gh command failed: Some error"):
        gh_query.fetch_open_prs("stub/repo")

def test_pr_blocking_issue():
    prs = [
        {"number": 42, "url": "https://url/42", "closingIssuesReferences": [{"number": 7}]},
        {"number": 43, "url": "https://url/43", "closingIssuesReferences": []},
        {"number": 44, "url": "https://url/44"}, # Missing key
    ]
    assert gh_query.pr_blocking_issue("7", prs) == "42\thttps://url/42"
    assert gh_query.pr_blocking_issue("8", prs) is None

def test_pr_for_issue():
    prs = [
        {"number": 42, "url": "https://url/42", "title": "stub pr", "body": "Closes #7", "headRefName": "fix/7-stub"}
    ]
    assert gh_query.pr_for_issue("7", prs) == "42\thttps://url/42"
    assert gh_query.pr_for_issue("8", prs) is None
    
    prs_title = [{"number": 45, "url": "url", "title": "Fix #7"}]
    assert gh_query.pr_for_issue("7", prs_title) == "45\turl"
    
    prs_head = [{"number": 46, "url": "url", "headRefName": "issue-7-fix"}]
    assert gh_query.pr_for_issue("7", prs_head) == "46\turl"
