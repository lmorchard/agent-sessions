"""The merge-block hook script's own behaviour, at the path the driver actually installs.

Two things changed here beyond the move. The script is now located via
`lifecycle.hook_script_path()` rather than the literal `driver/merge-block-hook.sh`, so
these tests grade the file a real run executes and no longer depend on pytest's working
directory. And the cases are parametrised, which is what made it obvious that the
allow-side had two assertions crammed into one test while `git push --force` had none.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from agent_sessions.driver import lifecycle

HOOK = lifecycle.hook_script_path()


def run_hook(command: str, tool_name: str = "Bash") -> tuple[int, dict]:
    payload = {"tool_name": tool_name, "tool_input": {"command": command}}
    res = subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload).encode(),
        capture_output=True,
    )
    return res.returncode, json.loads(res.stdout.decode())


DENIED = [
    "gh pr merge 12 --squash",
    "gh api -X PUT repos/o/r/pulls/12/merge",
    "gh api --method POST repos/o/r/pulls/12/merge",
    "curl -X POST https://api.github.com/repos/o/r/pulls/12/merge",
    "curl --request PUT https://api.github.com/repos/o/r/pulls/12/merge",
]

ALLOWED = [
    "gh pr view 12",
    "gh api repos/o/r/pulls/12",
    "gh pr checks 12 --watch",
    "git push origin HEAD",
]


def test_the_hook_script_ships_with_the_package() -> None:
    """If this fails, the render in `preflight` has nothing to install."""
    assert HOOK.is_file(), f"hook script missing at {HOOK}"


@pytest.mark.parametrize("command", DENIED)
def test_merge_paths_are_denied(command: str) -> None:
    code, decision = run_hook(command)
    assert code == 1, f"expected a denial exit for: {command}"
    assert decision["decision"] == "deny", f"expected deny for: {command}"
    assert decision.get("reason"), "a denial must carry a reason"


@pytest.mark.parametrize("command", ALLOWED)
def test_read_paths_are_allowed(command: str) -> None:
    code, decision = run_hook(command)
    assert code == 0, f"expected an allow exit for: {command}"
    assert decision["decision"] == "allow", f"expected allow for: {command}"


def test_non_bash_tools_pass_through() -> None:
    """The hook only adjudicates Bash; anything else is not its business."""
    code, decision = run_hook("irrelevant", tool_name="Read")
    assert code == 0
    assert decision["decision"] == "allow"


def test_a_malformed_payload_fails_closed() -> None:
    """The script traps errors into a denial. Verify that, rather than trusting the trap."""
    res = subprocess.run(
        ["bash", str(HOOK)],
        input=b"not json at all",
        capture_output=True,
    )
    assert res.returncode == 1
    assert json.loads(res.stdout.decode())["decision"] == "deny"
