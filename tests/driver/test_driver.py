"""Tests for driver/agent_session_driver.py and the Python driver integration."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest

from agent_sessions.driver import agent_session_driver


def test_abspath_resolution(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    abs_p = agent_session_driver.abspath("foo/bar")
    assert abs_p == tmp_path / "foo" / "bar"

    abs_existing = agent_session_driver.abspath("/absolute/path")
    assert abs_existing == Path("/absolute/path")


def test_parked_numbers():
    issues = [
        {"number": 1, "labels": [{"name": "agent-session:needs-human"}]},
        {"number": 2, "labels": [{"name": "bug"}]},
        {"number": 3, "labels": [{"name": "agent-session:needs-human-interactive"}]},
    ]
    parked = agent_session_driver.parked_numbers(issues)
    assert parked == {"1", "3"}


def test_build_prompt(tmp_path: Path, monkeypatch):
    class MockResult:
        stdout = json.dumps({
            "title": "Fix bug",
            "body": "Some body content",
            "comments": [{"author": {"login": "alice"}, "body": "Please fix this"}]
        })
        returncode = 0

    def mock_run(cmd, *args, **kwargs):
        if [str(c) for c in cmd][:3] == ["gh", "api", "user"]:
            class Login:
                stdout = "agent-session-bot\n"
                returncode = 0
            return Login()
        return MockResult()

    monkeypatch.setattr("subprocess.run", mock_run)

    prompt = agent_session_driver.build_prompt(42, "express", tmp_path)
    assert "issue #42" in prompt

    prompt_refine = agent_session_driver.build_prompt(42, "refine", tmp_path)
    assert "pass --comments" in prompt_refine


def test_driver_cli_help(tmp_path: Path):
    driver_script = Path(__file__).resolve().parents[2] / "driver" / "agent-session-driver.sh"
    res = subprocess.run([str(driver_script), "--help"], capture_output=True, text=True)
    assert res.returncode == 0
    assert "--repo" in res.stdout


def test_driver_env_defaults(tmp_path: Path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "REPO=owner/repo\n"
        "REPO_PATH=/tmp/repo\n"
        "SKILL_DIR=/tmp/skill\n"
        "BOARD=owner/1\n"
        "BACKEND=opencode\n"
        "HIGH_TIER_MODEL=model-high\n"
        "LOW_TIER_MODEL=model-low\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REPO", "owner/repo")
    monkeypatch.setenv("REPO_PATH", "/tmp/repo")
    monkeypatch.setenv("SKILL_DIR", "/tmp/skill")
    monkeypatch.setenv("BOARD", "owner/1")
    monkeypatch.setenv("BACKEND", "opencode")
    monkeypatch.setenv("HIGH_TIER_MODEL", "model-high")
    monkeypatch.setenv("LOW_TIER_MODEL", "model-low")
    # The driver refuses to start without its own account (#191).
    monkeypatch.setenv("AGENT_GH_READ_TOKEN", "read-token")
    monkeypatch.setenv("DRIVER_GH_WRITE_TOKEN", "write-token")
    monkeypatch.setenv("DRIVER_GH_LOGIN", "agent-session-bot")

    class MockResult:
        stdout = json.dumps([])
        returncode = 0

    def mock_run(cmd, *args, **kwargs):
        if [str(c) for c in cmd][:3] == ["gh", "api", "user"]:
            class Login:
                stdout = "agent-session-bot\n"
                returncode = 0
            return Login()
        return MockResult()

    monkeypatch.setattr("subprocess.run", mock_run)

    ret = agent_session_driver.main(["--dry-run"])
    assert ret == 0


def test_has_new_human_comment(monkeypatch):
    class MockResult:
        returncode = 0

        def __init__(self, login, created_at="2026-08-10T13:00:00Z"):
            self.stdout = json.dumps({"comments": [{"author": {"login": login}, "body": "Comment text", "createdAt": created_at}]})

    def mock_run_human(cmd, *args, **kwargs):
        return MockResult("alice")

    monkeypatch.setattr("subprocess.run", mock_run_human)
    has_human, login = agent_session_driver.has_new_human_comment(42, "owner/repo")
    assert has_human is True
    assert login == "alice"

    def mock_run_bot(cmd, *args, **kwargs):
        return MockResult("github-actions[bot]")

    monkeypatch.setattr("subprocess.run", mock_run_bot)
    has_human, login = agent_session_driver.has_new_human_comment(42, "owner/repo")
    assert has_human is False

    # Issue 183: Exclude driver identity and extra bot logins
    def mock_run_driver(cmd, *args, **kwargs):
        return MockResult("driver-account")

    monkeypatch.setattr("subprocess.run", mock_run_driver)
    bots = {"driver-account", "extra-bot"}
    has_human, login = agent_session_driver.has_new_human_comment(42, "owner/repo", bot_logins=bots)
    assert has_human is False

    # Issue 183: Filter out comments predating park_time
    def mock_run_predated(cmd, *args, **kwargs):
        return MockResult("alice", created_at="2026-08-10T11:00:00Z")

    monkeypatch.setattr("subprocess.run", mock_run_predated)
    has_human, login = agent_session_driver.has_new_human_comment(42, "owner/repo", park_time="20260810T120000Z")
    assert has_human is False


def test_has_new_human_reaction(monkeypatch):
    class MockGraphQLResult:
        returncode = 0

        def __init__(self, user_login, created_at="2026-08-10T13:00:00Z"):
            self.stdout = json.dumps({
                "data": {
                    "repository": {
                        "issue": {
                            "comments": {
                                "nodes": [
                                    {
                                        "author": {"login": "bot-user"},
                                        "createdAt": "2026-08-10T10:00:00Z",
                                        "reactions": {
                                            "nodes": [
                                                {
                                                    "content": "THUMBS_UP",
                                                    "user": {"login": user_login},
                                                    "createdAt": created_at,
                                                }
                                            ]
                                        }
                                    }
                                ]
                            }
                        }
                    }
                }
            })

    def mock_run_human_reaction(cmd, *args, **kwargs):
        return MockGraphQLResult("lmorchard", created_at="2026-08-10T13:00:00Z")

    monkeypatch.setattr("subprocess.run", mock_run_human_reaction)
    bots = {"bot-user"}
    has_human, login = agent_session_driver.has_new_human_comment(
        42, "owner/repo", bot_logins=bots, park_time="20260810T120000Z"
    )
    assert has_human is True
    assert login == "lmorchard"

    # Predated reaction
    def mock_run_predated_reaction(cmd, *args, **kwargs):
        return MockGraphQLResult("lmorchard", created_at="2026-08-10T11:00:00Z")

    monkeypatch.setattr("subprocess.run", mock_run_predated_reaction)
    has_human, login = agent_session_driver.has_new_human_comment(
        42, "owner/repo", bot_logins=bots, park_time="20260810T120000Z"
    )
    assert has_human is False


def test_is_specced():
    # Issue with label agent-session:spec but no body marker
    iss_label = {
        "number": 1,
        "labels": [{"name": "agent-session:spec"}],
        "body": "No marker here",
    }
    assert agent_session_driver.is_specced(iss_label) is True

    # Issue with body marker but no label
    iss_marker = {
        "number": 2,
        "labels": [],
        "body": "<!-- agent-session:spec -->\nSome spec content",
    }
    assert agent_session_driver.is_specced(iss_marker) is True

    # Issue with neither
    iss_neither = {
        "number": 3,
        "labels": [{"name": "bug"}],
        "body": "Plain issue description",
    }
    assert agent_session_driver.is_specced(iss_neither) is False


def test_phase_tiers_coverage():
    expected_phases = {
        "triage",
        "refine",
        "execute",
        "address_comments",
        "fix_ci",
        "request_review",
        "grade_gate",
    }
    assert expected_phases.issubset(agent_session_driver.PHASE_TIERS.keys())
    for phase, tier in agent_session_driver.PHASE_TIERS.items():
        assert tier in ("high", "low")


def test_driver_tier_passed(tmp_path: Path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()

    env_file = tmp_path / ".env"
    env_file.write_text(
        "REPO=owner/repo\n"
        f"REPO_PATH={repo_dir}\n"
        f"SKILL_DIR={skill_dir}\n"
        "BACKEND=opencode\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REPO", "owner/repo")
    monkeypatch.setenv("REPO_PATH", str(repo_dir))
    monkeypatch.setenv("SKILL_DIR", str(skill_dir))
    monkeypatch.setenv("BACKEND", "opencode")
    # The driver refuses to start without its own account (#191).
    monkeypatch.setenv("AGENT_GH_READ_TOKEN", "read-token")
    monkeypatch.setenv("DRIVER_GH_WRITE_TOKEN", "write-token")
    monkeypatch.setenv("DRIVER_GH_LOGIN", "agent-session-bot")

    class MockResult:
        stdout = json.dumps([])
        returncode = 0

    def mock_run(cmd, *args, **kwargs):
        if [str(c) for c in cmd][:3] == ["gh", "api", "user"]:
            class Login:
                stdout = "agent-session-bot\n"
                returncode = 0
            return Login()
        if [str(c) for c in cmd][:3] == ["gh", "pr", "list"]:
            class PRList:
                stdout = json.dumps([{"number": 123, "closingIssuesReferences": [{"number": 42}]}])
                returncode = 0
            return PRList()
        return MockResult()

    monkeypatch.setattr("subprocess.run", mock_run)

    captured_args = []

    def mock_run_agent(argv):
        captured_args.append(argv)
        return 0

    monkeypatch.setattr("agent_sessions.driver.agent_runner.run_agent", mock_run_agent)

    # Test execute tier (high)
    ret = agent_session_driver.main(["--issue", "42"])
    assert ret == 0
    assert len(captured_args) == 1
    assert "--tier" in captured_args[0]
    tier_idx = captured_args[0].index("--tier")
    assert captured_args[0][tier_idx + 1] == "high"

    # Test grade_gate tier (low): mock pr_for_issue and check functions
    captured_args.clear()

    def mock_pr_for_issue(num, open_prs):
        return "123\thttps://github.com/owner/repo/pull/123"

    monkeypatch.setattr("agent_sessions.driver.gh_query.pr_for_issue", mock_pr_for_issue)
    monkeypatch.setattr("agent_sessions.driver.agent_session_driver.check_pr_unresolved_threads", lambda r, p, t: 0)
    monkeypatch.setattr("agent_sessions.driver.agent_session_driver.check_pr_ci_status", lambda r, p: (0, 0))
    monkeypatch.setattr("agent_sessions.driver.agent_session_driver.check_pr_reviews", lambda r, p: (1, 1, "APPROVED"))

    ret = agent_session_driver.main(["--issue", "42"])
    assert ret == 0
    assert len(captured_args) == 1
    assert "--tier" in captured_args[0]
    tier_idx = captured_args[0].index("--tier")
    assert captured_args[0][tier_idx + 1] == "low"


def test_check_and_handle_rate_limit_ok(monkeypatch):
    monkeypatch.setattr("agent_sessions.driver.gh_query.check_rate_limit", lambda env=None: (4000, 5000, 1700000000))
    messages = []
    agent_session_driver.check_and_handle_rate_limit(say_fn=messages.append)
    assert len(messages) == 0


def test_check_and_handle_rate_limit_backoff(monkeypatch):
    calls = [0]

    def mock_check(env=None):
        calls[0] += 1
        if calls[0] == 1:
            return (5, 5000, int(time.time()) + 2)
        return (5000, 5000, int(time.time()) + 3600)

    monkeypatch.setattr("agent_sessions.driver.gh_query.check_rate_limit", mock_check)
    monkeypatch.setattr("time.sleep", lambda s: None)
    messages = []
    agent_session_driver.check_and_handle_rate_limit(min_headroom=20, max_wait_seconds=600, say_fn=messages.append)
    assert len(messages) == 2
    assert "RATE LIMIT: GraphQL points low" in messages[0]
    assert "Resuming run after rate limit backoff" in messages[1]


def test_check_and_handle_rate_limit_die(monkeypatch):
    monkeypatch.setattr("agent_sessions.driver.gh_query.check_rate_limit", lambda env=None: (0, 5000, int(time.time()) + 1800))
    messages = []
    with pytest.raises(SystemExit):
        agent_session_driver.check_and_handle_rate_limit(min_headroom=20, max_wait_seconds=300, say_fn=messages.append)


def test_mark_board_in_progress_retry_success(monkeypatch):
    agent_session_driver._BOARD_METADATA_CACHE.clear()
    attempts = [0]

    class MockResView:
        stdout = json.dumps({"id": "PVT_123"})

    class MockResFields:
        stdout = json.dumps({
            "fields": [
                {
                    "name": "Status",
                    "id": "FLD_456",
                    "options": [{"name": "In progress", "id": "OPT_789"}]
                }
            ]
        })

    class MockResEdit:
        stdout = ""

    def mock_run(cmd, *args, **kwargs):
        cmd_str = [str(c) for c in cmd]
        if cmd_str[:2] == ["gh", "project"] and cmd_str[2] == "view":
            return MockResView()
        if cmd_str[:2] == ["gh", "project"] and cmd_str[2] == "field-list":
            return MockResFields()
        if cmd_str[:2] == ["gh", "project"] and cmd_str[2] == "item-edit":
            attempts[0] += 1
            if attempts[0] == 1:
                raise subprocess.CalledProcessError(1, cmd, stderr="GraphQL: temporary timeout")
            return MockResEdit()
        raise ValueError(f"unexpected cmd: {cmd}")

    monkeypatch.setattr("subprocess.run", mock_run)
    monkeypatch.setattr("time.sleep", lambda s: None)

    ok = agent_session_driver.mark_board_in_progress("owner/6", "ITEM_1", retries=3)
    assert ok is True
    assert attempts[0] == 2


def test_mark_board_in_progress_failure_logs_stderr(monkeypatch):
    agent_session_driver._BOARD_METADATA_CACHE.clear()
    logs = []

    class MockResView:
        stdout = json.dumps({"id": "PVT_123"})

    class MockResFields:
        stdout = json.dumps({
            "fields": [
                {
                    "name": "Status",
                    "id": "FLD_456",
                    "options": [{"name": "In progress", "id": "OPT_789"}]
                }
            ]
        })

    def mock_run(cmd, *args, **kwargs):
        cmd_str = [str(c) for c in cmd]
        if cmd_str[:2] == ["gh", "project"] and cmd_str[2] == "view":
            return MockResView()
        if cmd_str[:2] == ["gh", "project"] and cmd_str[2] == "field-list":
            return MockResFields()
        if cmd_str[:2] == ["gh", "project"] and cmd_str[2] == "item-edit":
            raise subprocess.CalledProcessError(1, cmd, stderr="GraphQL: Could not resolve item\n")
        raise ValueError(f"unexpected cmd: {cmd}")

    monkeypatch.setattr("subprocess.run", mock_run)
    monkeypatch.setattr("time.sleep", lambda s: None)
    # Patch the module that emits, not a re-export of it. `board.log` is bound from
    # `output` at import, so patching `agent_session_driver.log` no longer reaches it --
    # the same shape as the CURRENT_LOCK_ISSUE patch that silently did nothing.
    monkeypatch.setattr("agent_sessions.driver.board.log", logs.append)

    ok = agent_session_driver.mark_board_in_progress("owner/6", "ITEM_1", retries=2)
    assert ok is False
    assert len(logs) == 1
    assert "failed to mark item ITEM_1 in progress: GraphQL: Could not resolve item" in logs[0]


def test_lifecycle_preflight(tmp_path: Path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AGENT_GH_READ_TOKEN", "read-token")
    monkeypatch.setenv("DRIVER_GH_WRITE_TOKEN", "write-token")
    monkeypatch.setenv("DRIVER_GH_LOGIN", "agent-session-bot")

    class MockResult:
        stdout = json.dumps([])
        returncode = 0

    def mock_run(cmd, *args, **kwargs):
        if [str(c) for c in cmd][:3] == ["gh", "api", "user"]:
            class Login:
                stdout = "agent-session-bot\n"
                returncode = 0
            return Login()
        return MockResult()

    monkeypatch.setattr("subprocess.run", mock_run)

    argv = [
        "--repo", "owner/repo",
        "--repo-path", str(repo_dir),
        "--skill-dir", str(skill_dir),
        "--state-dir", str(tmp_path / "state"),
        "--dry-run",
    ]
    ctx = agent_session_driver.preflight(argv)
    assert isinstance(ctx, agent_session_driver.RunContext)
    assert ctx.repo == "owner/repo"
    assert ctx.repo_path == repo_dir.resolve()
    assert ctx.skill_dir == skill_dir.resolve()
    assert ctx.dry_run is True


def test_lifecycle_selection(tmp_path: Path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AGENT_GH_READ_TOKEN", "read-token")
    monkeypatch.setenv("DRIVER_GH_WRITE_TOKEN", "write-token")
    monkeypatch.setenv("DRIVER_GH_LOGIN", "agent-session-bot")

    class MockResult:
        stdout = json.dumps([])
        returncode = 0

    def mock_run(cmd, *args, **kwargs):
        if [str(c) for c in cmd][:3] == ["gh", "api", "user"]:
            class Login:
                stdout = "agent-session-bot\n"
                returncode = 0
            return Login()
        if [str(c) for c in cmd][:3] == ["gh", "issue", "list"]:
            class Issues:
                stdout = json.dumps([{
                    "number": 10,
                    "title": "Fix something",
                    "body": "<!-- agent-session:spec -->\n\n## Tier: auto-ok\n",
                    "labels": [{"name": "P1"}],
                    "url": "https://github.com/owner/repo/issues/10",
                    "updatedAt": "2026-08-10T12:00:00Z",
                }])
                returncode = 0
            return Issues()
        return MockResult()

    monkeypatch.setattr("subprocess.run", mock_run)

    argv = [
        "--repo", "owner/repo",
        "--repo-path", str(repo_dir),
        "--skill-dir", str(skill_dir),
        "--state-dir", str(state_dir),
        "--dry-run",
    ]
    ctx = agent_session_driver.preflight(argv)
    sel = agent_session_driver.select_queue(ctx)

    assert isinstance(sel, agent_session_driver.SelectionResult)
    assert isinstance(sel.candidates, list)
    assert len(sel.candidates) == 1
    assert sel.candidates[0] == ("10", "execute")


def test_lifecycle_classify_and_record(tmp_path: Path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    state_dir = tmp_path / "state"

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AGENT_GH_READ_TOKEN", "read-token")
    monkeypatch.setenv("DRIVER_GH_WRITE_TOKEN", "write-token")
    monkeypatch.setenv("DRIVER_GH_LOGIN", "agent-session-bot")

    class MockResult:
        stdout = json.dumps([])
        returncode = 0

    def mock_run(cmd, *args, **kwargs):
        if [str(c) for c in cmd][:3] == ["gh", "api", "user"]:
            class Login:
                stdout = "agent-session-bot\n"
                returncode = 0
            return Login()
        return MockResult()

    monkeypatch.setattr("subprocess.run", mock_run)

    argv = [
        "--repo", "owner/repo",
        "--repo-path", str(repo_dir),
        "--skill-dir", str(skill_dir),
        "--state-dir", str(state_dir),
    ]
    ctx = agent_session_driver.preflight(argv)

    rundir = ctx.runs_dir / "10-20260810T120000Z"
    rundir.mkdir(parents=True, exist_ok=True)
    raw_output = rundir / "stream.jsonl"
    raw_output.write_text(json.dumps({"type": "result", "total_cost_usd": 0.5, "result": "done"}) + "\n")
    stderr_output = rundir / "stderr.txt"
    writes_file = rundir / "writes.jsonl"
    writes_file.write_text("")

    inv = agent_session_driver.InvocationResult(
        issue_num="10",
        phase="execute",
        ts="20260810T120000Z",
        rundir=rundir,
        raw_output=raw_output,
        stderr_output=stderr_output,
        exit_code=0,
        cost=0.5,
        session_id="sess-123",
        cost_known=True,
        final_text="Agent completed work.",
        # All six keys, because `WritesResult` declares six. The fixture carried four
        # and passed only because `ok=True` short-circuits `writes_summary` before it
        # reads `errors` or `results`; a case that set `ok=False` would have raised
        # `KeyError` from the code under test.
        writes_result={"ok": True, "errors": [], "results": [], "entries": [], "applied": 0, "messages": []},
    )

    outcome = agent_session_driver.classify_and_record(ctx, inv, open_prs=[])

    assert isinstance(outcome, agent_session_driver.RunOutcome)
    assert outcome.issue_num == "10"
    assert outcome.outcome == "parked"
    assert outcome.cost == 0.5

    runs_log_lines = ctx.runs_log.read_text(encoding="utf-8").splitlines()
    assert len(runs_log_lines) == 1
    row = json.loads(runs_log_lines[0])
    assert row["issue"] == 10
    assert row["outcome"] == "parked"
    assert row["cost_usd"] == 0.5




def test_the_facade_does_not_re_export_the_output_helpers():
    """`say`/`log`/`die` originate in `output`; the facade must not offer a copy.

    It used to import them *from `lifecycle`* — which had aliased them from `output` —
    and re-export them, and nothing anywhere consumed the result. What that buys is a
    trap: `monkeypatch.setattr(agent_session_driver, "log", ...)` looks like it patches
    the emitter and patches a bound copy instead, exactly as the `CURRENT_LOCK_ISSUE`
    re-export did. `test_board_marks_item_in_progress_logs_graphql_failure` above patches
    `board.log` for that reason, and its comment says so.

    Asserted rather than left to review because the re-export is one line and reads as
    harmless. Patch the module that emits.
    """
    from agent_sessions.driver import agent_session_driver as facade

    offered = [name for name in ("say", "log", "die") if name in facade.__all__]
    assert offered == [], (
        f"the facade re-exports {offered}; patching those reaches a copy, not the "
        f"emitter. Import them from `agent_sessions.driver.output`."
    )


def test_no_driver_module_aliases_an_output_helper():
    """`log = output.log` at module level is the re-export in another costume.

    The alias and a real `from ... import log` bind the same object, so this is not
    about behaviour — it is about what the line claims. An assignment reads as "this
    module provides `log`", which invites patching it, and patching it reaches a copy.
    An import reads as "this module uses `log`", which is true.

    Six modules carried the assignment form. Five were caught in one pass and `locks.py`
    was missed, which is why this is a check and not a tidy-up: the pattern is one line,
    it is easy to add without thinking, and grepping for it by hand missed an instance.

    `output.now()` is deliberately excluded — it must stay module-qualified so the suites
    can freeze it, and a `now = output.now` alias is exactly what would break that. If
    one appears, this catches it too.
    """
    import ast

    driver_dir = Path(__file__).resolve().parents[2] / "src" / "agent_sessions" / "driver"
    offenders = []
    for path in sorted(driver_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:  # module level only
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Attribute):
                continue
            value = node.value
            if isinstance(value.value, ast.Name) and value.value.id == "output":
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        offenders.append(f"{path.name}:{node.lineno}: {target.id} = output.{value.attr}")

    assert offenders == [], (
        "these modules alias an `output` helper instead of importing it:\n  "
        + "\n  ".join(offenders)
        + "\nUse `from agent_sessions.driver.output import <name>`."
    )
