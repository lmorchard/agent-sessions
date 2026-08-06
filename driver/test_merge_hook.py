import json
import subprocess
import pytest
from pathlib import Path

def test_hook_gh_pr_merge():
    payload = {"tool_name": "Bash", "tool_input": {"command": "gh pr merge 12 --squash"}}
    res = subprocess.run(["bash", "driver/merge-block-hook.sh"], input=json.dumps(payload).encode(), capture_output=True)
    assert res.returncode == 1
    assert json.loads(res.stdout.decode())["decision"] == "deny"

def test_hook_gh_api_merge():
    payload = {"tool_name": "Bash", "tool_input": {"command": "gh api -X PUT repos/o/r/pulls/12/merge"}}
    res = subprocess.run(["bash", "driver/merge-block-hook.sh"], input=json.dumps(payload).encode(), capture_output=True)
    assert res.returncode == 1
    assert json.loads(res.stdout.decode())["decision"] == "deny"

def test_hook_curl_merge():
    payload = {"tool_name": "Bash", "tool_input": {"command": "curl -X POST https://api.github.com/repos/o/r/pulls/12/merge"}}
    res = subprocess.run(["bash", "driver/merge-block-hook.sh"], input=json.dumps(payload).encode(), capture_output=True)
    assert res.returncode == 1
    assert json.loads(res.stdout.decode())["decision"] == "deny"

def test_hook_allow_reads():
    payload = {"tool_name": "Bash", "tool_input": {"command": "gh pr view 12"}}
    res = subprocess.run(["bash", "driver/merge-block-hook.sh"], input=json.dumps(payload).encode(), capture_output=True)
    assert res.returncode == 0
    assert json.loads(res.stdout.decode())["decision"] == "allow"

    payload = {"tool_name": "Bash", "tool_input": {"command": "gh api repos/o/r/pulls/12"}}
    res = subprocess.run(["bash", "driver/merge-block-hook.sh"], input=json.dumps(payload).encode(), capture_output=True)
    assert res.returncode == 0
    assert json.loads(res.stdout.decode())["decision"] == "allow"
