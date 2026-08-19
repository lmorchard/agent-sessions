"""Tests for driver/agent_runner.py."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from agent_sessions.driver import agent_runner, credentials  # noqa: E402

EXPECTED_DEFAULT_ALLOWED_TOOLS = [
    "Read",
    "Write",
    "Edit",
    "Glob",
    "Grep",
    "Task",
    "TodoWrite",
    "BashOutput",
    "KillShell",
    "NotebookEdit",
    "Bash(*)",
]

EXPECTED_BASE_DENIED_TOOLS = [
    "Bash(gh pr merge:*)",
    "Bash(gh pr merge *)",
    "Bash(git push --force:*)",
    "Bash(git push --force *)",
    "Bash(git push -f:*)",
    "Bash(git push -f *)",
    "Bash(gh repo delete:*)",
]


def test_parse_result_stream_claude(tmp_path: Path):
    raw = tmp_path / "stream.jsonl"
    events = [
        {"type": "init", "session_id": "ses_123"},
        {"type": "result", "subtype": "success", "session_id": "ses_123", "total_cost_usd": 1.25, "result": "Done successfully"},
        {"type": "error_during_execution", "total_cost_usd": 0.0}
    ]
    raw.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")

    res = agent_runner.parse_result_stream("claude", raw)
    assert res["final"] == "Done successfully"
    assert res["total_cost_usd"] == 1.25
    assert res["session_id"] == "ses_123"
    assert res["cost_known"] is True


def test_parse_result_stream_opencode(tmp_path: Path):
    raw = tmp_path / "opencode.jsonl"
    events = [
        {"type": "step_start", "sessionID": "ses_opencode_999"},
        {"type": "text", "sessionID": "ses_opencode_999", "part": {"type": "text", "text": "Hello "}},
        {"type": "text", "sessionID": "ses_opencode_999", "part": {"type": "text", "text": "World!"}},
        {"type": "step_finish", "sessionID": "ses_opencode_999", "part": {"type": "step-finish", "reason": "stop", "cost": 0.0042}}
    ]
    raw.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")

    res = agent_runner.parse_result_stream("opencode", raw)
    assert res["final"] == "Hello World!"
    assert res["total_cost_usd"] == 0.0042
    assert res["session_id"] == "ses_opencode_999"
    assert res["cost_known"] is True


def test_stream_has_events(tmp_path: Path):
    raw = tmp_path / "empty.jsonl"
    raw.write_text("", encoding="utf-8")
    assert agent_runner.stream_has_events(raw) is False

    raw.write_text('{"type": "init"}\n', encoding="utf-8")
    assert agent_runner.stream_has_events(raw) is True


def test_has_success_result_claude(tmp_path: Path):
    raw = tmp_path / "stream.jsonl"
    raw.write_text(json.dumps({"type": "result", "subtype": "success", "is_error": False}) + "\n", encoding="utf-8")
    assert agent_runner.has_success_result("claude", raw) is True

    raw.write_text(json.dumps({"type": "result", "subtype": "failure", "is_error": True}) + "\n", encoding="utf-8")
    assert agent_runner.has_success_result("claude", raw) is False


def test_has_success_result_opencode(tmp_path: Path):
    raw = tmp_path / "opencode.jsonl"
    raw.write_text(json.dumps({"type": "step_finish", "part": {"reason": "stop"}}) + "\n", encoding="utf-8")
    assert agent_runner.has_success_result("opencode", raw) is True


def test_partial_trailing_line_handling(tmp_path: Path):
    raw = tmp_path / "stream.jsonl"
    raw.write_text('{"type": "init"}\n{"type": "result", "subtype": "success", "is_error": false}\n{"partial": "trun', encoding="utf-8")
    assert agent_runner.stream_has_events(raw) is True
    assert agent_runner.has_success_result("claude", raw) is True


def test_missing_prompt_writes_nested_stderr_and_returns_configuration_error(
    tmp_path: Path,
):
    prompt = tmp_path / "missing" / "prompt.txt"
    stderr = tmp_path / "run" / "stderr.txt"

    result = agent_runner.run_agent(
        [
            "--backend",
            "claude",
            "--repo-path",
            str(tmp_path),
            "--skill-dir",
            str(tmp_path),
            "--prompt-file",
            str(prompt),
            "--raw-output",
            str(tmp_path / "run" / "stream.jsonl"),
            "--stderr-output",
            str(stderr),
        ]
    )

    assert result == 2
    assert stderr.read_text(encoding="utf-8") == (
        f"error: prompt file not found: {prompt.resolve()}\n"
    )


def test_run_agent_model_tiers(tmp_path: Path, monkeypatch):
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Hello", encoding="utf-8")
    raw = tmp_path / "stream.jsonl"
    stderr = tmp_path / "stderr.txt"

    captured_cmds = []

    class MockPopen:
        def __init__(self, cmd, *args, **kwargs):
            captured_cmds.append(cmd)
            self.stdin = type("Pipe", (), {"write": lambda self, x: None, "close": lambda self: None})()
            self.returncode = 0

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    monkeypatch.setattr("subprocess.Popen", MockPopen)

    # Test high tier model default
    agent_runner.run_agent([
        "--backend", "claude",
        "--repo-path", str(tmp_path),
        "--skill-dir", str(tmp_path),
        "--prompt-file", str(prompt),
        "--raw-output", str(raw),
        "--stderr-output", str(stderr),
        "--high-tier-model", "claude-3-5-sonnet",
        "--low-tier-model", "claude-3-5-haiku",
        "--tier", "high"
    ])
    assert "--model" in captured_cmds[-1]
    assert captured_cmds[-1][captured_cmds[-1].index("--model") + 1] == "claude-3-5-sonnet"

    # Test low tier model
    agent_runner.run_agent([
        "--backend", "claude",
        "--repo-path", str(tmp_path),
        "--skill-dir", str(tmp_path),
        "--prompt-file", str(prompt),
        "--raw-output", str(raw),
        "--stderr-output", str(stderr),
        "--high-tier-model", "claude-3-5-sonnet",
        "--low-tier-model", "claude-3-5-haiku",
        "--tier", "low"
    ])
    assert "--model" in captured_cmds[-1]
    assert captured_cmds[-1][captured_cmds[-1].index("--model") + 1] == "claude-3-5-haiku"



def run_and_capture(
    tmp_path: Path,
    monkeypatch,
    extra_argv=(),
    *,
    backend: str = "claude",
    repo_path: Path | None = None,
    skill_dir: Path | None = None,
    version_output: str = "1.18.18",
    version_returncode: int = 0,
    version_error: OSError | subprocess.TimeoutExpired | None = None,
):
    """Invoke `run_agent` and capture the Popen boundary."""
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Hello", encoding="utf-8")
    captured = {"command": None, "env": None, "version_kwargs": None}
    repo_path = repo_path or tmp_path
    skill_dir = skill_dir or tmp_path

    class MockPopen:
        def __init__(self, cmd, *args, **kwargs):
            captured["command"] = cmd
            captured["env"] = kwargs.get("env")
            self.stdin = type("Pipe", (), {"write": lambda self, x: None, "close": lambda self: None})()
            self.returncode = 0

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    monkeypatch.setattr("subprocess.Popen", MockPopen)
    if backend == "opencode":
        fake_opencode = tmp_path / "bin" / "opencode"
        fake_opencode.parent.mkdir(exist_ok=True)
        fake_opencode.write_text("test executable\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            agent_runner.shutil, "which", lambda command: "bin/opencode"
        )
        monkeypatch.setattr(agent_runner.secrets, "token_hex", lambda _size: "abc123")

        def fake_run(*args, **kwargs):
            assert args[0] == [str(fake_opencode.resolve()), "--version"]
            assert kwargs["timeout"] == agent_runner.OPENCODE_VERSION_TIMEOUT_SECONDS
            captured["version_kwargs"] = kwargs
            if version_error is not None:
                raise version_error
            return subprocess.CompletedProcess(
                args[0], version_returncode, stdout=version_output + "\n", stderr=""
            )

        monkeypatch.setattr("subprocess.run", fake_run)

    result = agent_runner.run_agent([
        "--backend", backend,
        "--repo-path", str(repo_path),
        "--skill-dir", str(skill_dir),
        "--prompt-file", str(prompt),
        "--raw-output", str(tmp_path / "stream.jsonl"),
        "--stderr-output", str(tmp_path / "stderr.txt"),
        *extra_argv,
    ])
    return result, captured["command"], captured["env"]


def option_value(command: list[str], name: str) -> str:
    return command[command.index(name) + 1]


def expected_denied_tools(skill_dir: Path, additional: list[str] | None = None) -> list[str]:
    return [
        *EXPECTED_BASE_DENIED_TOOLS,
        f"Edit(/{skill_dir.resolve()}/**)",
        f"Write(/{skill_dir.resolve()}/**)",
        f"NotebookEdit(/{skill_dir.resolve()}/**)",
        *(additional or []),
    ]


def assert_permission_options(
    command: list[str], *, allowed: list[str], denied: list[str]
) -> None:
    assert command.count("--allowedTools") == 1
    assert command.count("--disallowedTools") == 1
    assert option_value(command, "--allowedTools").split(",") == allowed
    assert option_value(command, "--disallowedTools").split(",") == denied


def test_claude_command_restores_mandatory_permission_policy(tmp_path, monkeypatch):
    _, command, _ = run_and_capture(tmp_path, monkeypatch)
    assert_permission_options(
        command,
        allowed=EXPECTED_DEFAULT_ALLOWED_TOOLS,
        denied=expected_denied_tools(tmp_path),
    )


def test_caller_rules_cannot_replace_mandatory_denials(tmp_path, monkeypatch):
    _, command, _ = run_and_capture(
        tmp_path,
        monkeypatch,
        extra_argv=(
            "--allowed-tools",
            "Task,Read,Grep",
            "--disallowed-tools",
            "Bash(rm:*),Bash(git clean:*)",
        ),
    )
    assert_permission_options(
        command,
        allowed=["Task", "Read", "Grep"],
        denied=expected_denied_tools(
            tmp_path, ["Bash(rm:*)", "Bash(git clean:*)"]
        ),
    )


def test_opencode_command_applies_mandatory_permission_policy(tmp_path, monkeypatch):
    repo_path = tmp_path / "repo"
    skill_dir = tmp_path / "hosted-skill"
    repo_path.mkdir()
    skill_dir.mkdir()
    monkeypatch.setenv(credentials.READ_TOKEN_VAR, "read-token")
    monkeypatch.setenv(credentials.WRITE_TOKEN_VAR, "write-token")
    monkeypatch.setenv("GH_TOKEN", "write-token")
    monkeypatch.setenv("OPENCODE_CONFIG_CONTENT", '{"permission":"allow"}')
    monkeypatch.setenv("OPENCODE_CONFIG", "/target/config.json")
    monkeypatch.setenv("OPENCODE_CONFIG_DIR", "/target/.opencode")
    monkeypatch.setenv("OPENCODE_PERMISSION", '{"edit":"allow"}')
    monkeypatch.setenv("OPENCODE_TEST_HOME", "/target/home")
    monkeypatch.setenv("XDG_CONFIG_HOME", "/target/xdg")

    result, command, env = run_and_capture(
        tmp_path,
        monkeypatch,
        backend="opencode",
        repo_path=repo_path,
        skill_dir=skill_dir,
    )

    assert result == 0
    assert command[:3] == [str((tmp_path / "bin" / "opencode").resolve()), "--pure", "run"]
    assert "--auto" in command
    assert option_value(command, "--dir") == str(repo_path.resolve())
    assert command.count("--agent") == 1
    assert option_value(command, "--agent") == "agent-session-abc123"
    policy = json.loads(env["OPENCODE_CONFIG_CONTENT"])
    skill = str(skill_dir.resolve())
    edit_resource = skill.removeprefix("/")
    expected_permissions = {
        "edit": {
            "*": "allow",
            skill: "deny",
            f"{skill}/**": "deny",
            edit_resource: "deny",
            f"{edit_resource}/**": "deny",
        },
        "external_directory": {
            "*": "deny",
            skill: "allow",
            f"{skill}/**": "allow",
        },
        "bash": {
            "*": "allow",
            "gh pr merge": "deny",
            "gh pr merge *": "deny",
            "git push --force": "deny",
            "git push --force *": "deny",
            "git push -f": "deny",
            "git push -f *": "deny",
            "gh repo delete": "deny",
            "gh repo delete *": "deny",
            "gh api *pulls/*/merge*": "deny",
            "curl *pulls/*/merge*": "deny",
        },
        "task": "deny",
    }
    assert policy == {
        "permission": expected_permissions,
        "agent": {
            "agent-session-abc123": {
                "mode": "primary",
                "disable": False,
                "permission": expected_permissions,
            }
        },
    }
    assert list(policy["permission"]["edit"]) == [
        "*",
        skill,
        f"{skill}/**",
        edit_resource,
        f"{edit_resource}/**",
    ]
    assert list(policy["permission"]["external_directory"]) == [
        "*",
        skill,
        f"{skill}/**",
    ]
    assert list(policy["permission"]["bash"])[0] == "*"
    assert env["GH_TOKEN"] == env["GITHUB_TOKEN"] == "read-token"
    assert "write-token" not in env.values()
    assert credentials.WRITE_TOKEN_VAR not in env
    assert env["OPENCODE_DISABLE_PROJECT_CONFIG"] == "true"
    assert env["OPENCODE_TEST_HOME"] == env["XDG_CONFIG_HOME"]
    assert env["XDG_CONFIG_HOME"] != "/target/xdg"
    assert not Path(env["XDG_CONFIG_HOME"]).exists()
    assert "OPENCODE_CONFIG" not in env
    assert "OPENCODE_CONFIG_DIR" not in env
    assert "OPENCODE_PERMISSION" not in env


@pytest.mark.parametrize(
    ("version_output", "message"),
    [
        ("1.18.17", "unsupported OpenCode version 1.18.17"),
        ("1.18.19", "unsupported OpenCode version 1.18.19"),
        ("2.0.0", "unsupported OpenCode version 2.0.0"),
        ("not-a-version", "could not parse OpenCode version"),
    ],
)
def test_opencode_rejects_unverified_versions_before_launch(
    tmp_path, monkeypatch, version_output, message
):
    result, command, _ = run_and_capture(
        tmp_path,
        monkeypatch,
        backend="opencode",
        version_output=version_output,
    )

    assert result == 2
    assert command is None
    assert message in (tmp_path / "stderr.txt").read_text(encoding="utf-8")


def test_opencode_rejects_failed_version_process_before_launch(tmp_path, monkeypatch):
    result, command, _ = run_and_capture(
        tmp_path,
        monkeypatch,
        backend="opencode",
        version_returncode=9,
    )

    assert result == 2
    assert command is None
    assert (tmp_path / "stderr.txt").read_text(encoding="utf-8") == (
        "error: OpenCode version probe exited 9\n"
    )


def test_opencode_rejects_missing_version_command_before_launch(tmp_path, monkeypatch):
    result, command, _ = run_and_capture(
        tmp_path,
        monkeypatch,
        backend="opencode",
        version_error=OSError("missing"),
    )

    assert result == 2
    assert command is None
    assert (tmp_path / "stderr.txt").read_text(encoding="utf-8") == (
        "error: could not run OpenCode version probe: OSError\n"
    )


def test_opencode_rejects_timed_out_version_probe_before_launch(tmp_path, monkeypatch):
    result, command, _ = run_and_capture(
        tmp_path,
        monkeypatch,
        backend="opencode",
        version_error=subprocess.TimeoutExpired("opencode", 10),
    )

    assert result == 2
    assert command is None
    assert (tmp_path / "stderr.txt").read_text(encoding="utf-8") == (
        "error: OpenCode version probe timed out\n"
    )


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("--allowed-tools", "Read"),
        ("--disallowed-tools", "Bash(rm:*)"),
    ],
)
def test_opencode_rejects_claude_only_permission_options_before_launch(
    tmp_path, monkeypatch, option, value
):
    result, command, _ = run_and_capture(
        tmp_path,
        monkeypatch,
        [option, value],
        backend="opencode",
    )

    assert result == 2
    assert command is None
    assert (tmp_path / "stderr.txt").read_text(encoding="utf-8") == (
        f"error: {option} is only supported by the Claude backend\n"
    )


def test_opencode_rejects_unserializable_policy_before_launch(tmp_path, monkeypatch):
    monkeypatch.setattr(
        agent_runner.json,
        "dumps",
        lambda *args, **kwargs: (_ for _ in ()).throw(TypeError("bad policy")),
    )

    result, command, _ = run_and_capture(
        tmp_path,
        monkeypatch,
        backend="opencode",
    )

    assert result == 2
    assert command is None
    assert (tmp_path / "stderr.txt").read_text(encoding="utf-8") == (
        "error: could not serialize OpenCode permission policy\n"
    )


def test_opencode_rejects_config_home_creation_failure_before_launch(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        agent_runner.tempfile,
        "TemporaryDirectory",
        lambda **kwargs: (_ for _ in ()).throw(OSError("full")),
    )

    result, command, _ = run_and_capture(tmp_path, monkeypatch, backend="opencode")

    assert result == 2
    assert command is None
    assert (tmp_path / "stderr.txt").read_text(encoding="utf-8") == (
        "error: could not create OpenCode config home: OSError\n"
    )


def test_opencode_cleanup_failure_does_not_replace_agent_result(tmp_path, monkeypatch):
    class FailingCleanupDirectory:
        name = str(tmp_path / "isolated-config")

        def cleanup(self):
            raise OSError("busy")

    monkeypatch.setattr(
        agent_runner.tempfile,
        "TemporaryDirectory",
        lambda **kwargs: FailingCleanupDirectory(),
    )

    result, _, _ = run_and_capture(tmp_path, monkeypatch, backend="opencode")

    assert result == 0
    assert (tmp_path / "stderr.txt").read_text(encoding="utf-8") == (
        "warning: could not remove OpenCode config home: OSError\n"
    )


def test_caller_cannot_broaden_default_allowed_tools(tmp_path, monkeypatch):
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Hello", encoding="utf-8")
    stderr = tmp_path / "stderr.txt"
    launched = False

    class FailIfLaunched:
        def __init__(self, *args, **kwargs):
            nonlocal launched
            launched = True
            raise AssertionError("Popen must not run for a widened allow list")

    monkeypatch.setattr("subprocess.Popen", FailIfLaunched)
    result = agent_runner.run_agent(
        [
            "--backend",
            "claude",
            "--repo-path",
            str(tmp_path),
            "--skill-dir",
            str(tmp_path),
            "--prompt-file",
            str(prompt),
            "--raw-output",
            str(tmp_path / "stream.jsonl"),
            "--stderr-output",
            str(stderr),
            "--allowed-tools",
            "Read,WebFetch",
        ]
    )

    assert result == 2
    assert launched is False
    assert (
        stderr.read_text(encoding="utf-8")
        == "error: --allowed-tools may only narrow the default; unsupported rule(s): WebFetch\n"
    )


def test_agent_child_env_carries_the_read_token_only(tmp_path: Path, monkeypatch):
    """The containment property, at the one place it is actually applied (#191)."""
    monkeypatch.setenv(credentials.READ_TOKEN_VAR, "read-token")
    monkeypatch.setenv(credentials.WRITE_TOKEN_VAR, "write-token")
    monkeypatch.setenv("GH_TOKEN", "write-token")

    _, _, env = run_and_capture(tmp_path, monkeypatch)

    assert env["GH_TOKEN"] == "read-token"
    assert env["GITHUB_TOKEN"] == "read-token"
    assert "write-token" not in env.values(), f"the agent got a write-capable credential: {env}"
    assert credentials.WRITE_TOKEN_VAR not in env


def test_agent_child_env_hands_over_nothing_when_no_read_token_is_configured(tmp_path: Path, monkeypatch):
    """Fail closed. Passing the host credential through was the pre-bot-account
    behaviour; the driver now refuses to start in this configuration at all, and the
    runner invoked on its own applies the same policy rather than inheriting."""
    monkeypatch.delenv(credentials.READ_TOKEN_VAR, raising=False)
    monkeypatch.setenv("GH_TOKEN", "host-token")

    _, _, env = run_and_capture(tmp_path, monkeypatch)

    assert "GH_TOKEN" not in env
    assert "host-token" not in env.values()


def test_writes_file_is_exported_to_the_agent(tmp_path: Path, monkeypatch):
    monkeypatch.delenv(credentials.READ_TOKEN_VAR, raising=False)
    writes_file = tmp_path / "runs" / "writes.jsonl"

    _, _, env = run_and_capture(
        tmp_path, monkeypatch, ["--writes-file", str(writes_file)]
    )

    assert env[agent_runner.WRITES_FILE_VAR] == str(writes_file.resolve())


def test_run_agent_progress_polling(tmp_path: Path, monkeypatch, capsys):
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Hello", encoding="utf-8")
    raw = tmp_path / "stream.jsonl"
    stderr = tmp_path / "stderr.txt"

    import subprocess
    class MockPopen:
        def __init__(self, cmd, *args, **kwargs):
            self.calls = 0
            self.stdin = type("Pipe", (), {"write": lambda self, x: None, "close": lambda self: None})()

        def wait(self, timeout=None):
            self.calls += 1
            if self.calls == 1:
                # Write valid stream jsonl before raising TimeoutExpired
                raw.write_text(json.dumps({"type": "result", "total_cost_usd": 0.10, "result": "ok"}) + "\n", encoding="utf-8")
                raise subprocess.TimeoutExpired(cmd="test", timeout=timeout)
            return 0

        def kill(self):
            pass

    monkeypatch.setattr("subprocess.Popen", MockPopen)

    ret = agent_runner.run_agent([
        "--backend", "claude",
        "--repo-path", str(tmp_path),
        "--skill-dir", str(tmp_path),
        "--prompt-file", str(prompt),
        "--raw-output", str(raw),
        "--stderr-output", str(stderr),
        "--progress-interval", "0.01",
    ])
    assert ret == 0
    captured = capsys.readouterr()
    # Check that progress output was printed to sys.stderr during the timeout
    assert "run" in captured.err
    assert "$0.10" in captured.err
