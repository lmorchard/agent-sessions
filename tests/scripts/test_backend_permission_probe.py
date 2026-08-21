"""Tests for the live backend-permission evidence probe."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from agent_sessions.driver import lifecycle


def load_probe():
    try:
        return importlib.import_module(
            "agent_sessions.scripts.backend_permission_probe"
        )
    except ModuleNotFoundError:
        pytest.fail("backend_permission_probe is not implemented")


def option_value(argv: list[str], option: str) -> str:
    return argv[argv.index(option) + 1]


def write_success_stream(backend: str, raw_output: Path, final: str) -> None:
    if backend == "claude":
        events = [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "id": "edit-1", "name": "Write"}
                    ]
                },
            },
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "edit-1",
                            "is_error": True,
                            "content": "File is in a directory that is denied by your permission settings.",
                        }
                    ]
                },
            },
            {
                "type": "system",
                "subtype": "permission_denied",
                "tool_name": "Bash",
                "message": "Permission to use Bash with command gh pr merge --help has been denied.",
            },
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "result": final,
            },
        ]
        raw_output.write_text(
            "\n".join(json.dumps(event) for event in events) + "\n",
            encoding="utf-8",
        )
        return

    events = [
        {
            "type": "tool_use",
            "part": {
                "tool": "write",
                "state": {
                    "error": "The user has specified a rule which prevents you from using this specific tool call."
                },
            },
        },
        {
            "type": "tool_use",
            "part": {
                "tool": "bash",
                "state": {
                    "error": "The user has specified a rule which prevents you from using this specific tool call."
                },
            },
        },
        {"type": "text", "part": {"type": "text", "text": final}},
        {"type": "step_finish", "part": {"reason": "stop"}},
    ]
    raw_output.write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize("backend", ["claude", "opencode"])
def test_probe_records_reproducible_success_evidence(
    tmp_path, monkeypatch, backend
):
    probe = load_probe()
    output_dir = tmp_path / backend
    captured = {}
    monkeypatch.setattr(
        probe, "backend_version", lambda selected: f"{selected}-test-version"
    )

    def fake_run_agent(argv):
        captured["argv"] = argv
        final = (
            "agent-session-permission-probe-read-ok\n"
            "native edit denied\ncommand denied"
        )
        write_success_stream(
            backend, Path(option_value(argv, "--raw-output")), final
        )
        Path(option_value(argv, "--stderr-output")).write_text("", encoding="utf-8")
        return 0

    monkeypatch.setattr(probe.agent_runner, "run_agent", fake_run_agent)

    result = probe.main(
        [
            "--backend",
            backend,
            "--output-dir",
            str(output_dir),
            "--model",
            "test/model",
        ]
    )

    assert result == 0
    argv = captured["argv"]
    assert option_value(argv, "--backend") == backend
    assert option_value(argv, "--repo-path") == str((output_dir / "repo").resolve())
    assert option_value(argv, "--skill-dir") == str((output_dir / "skill").resolve())
    assert option_value(argv, "--model") == "test/model"

    prompt = (output_dir / "prompt.txt").read_text(encoding="utf-8")
    assert str((output_dir / "skill" / "read-marker.txt").resolve()) in prompt
    assert str((output_dir / "skill" / "protected-marker.txt").resolve()) in prompt
    assert "native read tool" in prompt
    assert "native edit/write tool, never Bash" in prompt
    assert "agent-session-permission-probe-protected-original" in prompt
    assert "run exactly: gh pr merge --help" in prompt
    assert "do not try an alternate" in prompt

    settings = json.loads((output_dir / "settings.json").read_text(encoding="utf-8"))
    hook = Path(settings["hooks"]["PreToolUse"][0]["command"])
    assert hook == lifecycle.hook_script_path().resolve()
    assert hook.is_file()

    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary == {
        "backend": backend,
        "backend_version": f"{backend}-test-version",
        "runner_returncode": 0,
        "read_marker_observed": True,
        "edit_denial_observed": True,
        "bash_denial_observed": True,
        "protected_marker_unchanged": True,
        "prompt": str((output_dir / "prompt.txt").resolve()),
        "raw_output": str((output_dir / "stream.jsonl").resolve()),
        "stderr_output": str((output_dir / "stderr.txt").resolve()),
        "protected_marker": str(
            (output_dir / "skill" / "protected-marker.txt").resolve()
        ),
    }
    assert (output_dir / "skill" / "protected-marker.txt").read_text(
        encoding="utf-8"
    ) == "agent-session-permission-probe-protected-original\n"


@pytest.mark.parametrize(
    ("mutate_protected", "include_read_marker"),
    [(True, True), (False, False)],
)
def test_probe_fails_when_filesystem_or_read_evidence_is_missing(
    tmp_path, monkeypatch, mutate_protected, include_read_marker
):
    probe = load_probe()
    output_dir = tmp_path / "failed-evidence"
    monkeypatch.setattr(probe, "backend_version", lambda backend: "test-version")

    def fake_run_agent(argv):
        if mutate_protected:
            (output_dir / "skill" / "protected-marker.txt").write_text(
                "changed\n", encoding="utf-8"
            )
        final = (
            "agent-session-permission-probe-read-ok"
            if include_read_marker
            else "read failed"
        )
        write_success_stream(
            "claude", Path(option_value(argv, "--raw-output")), final
        )
        Path(option_value(argv, "--stderr-output")).write_text("", encoding="utf-8")
        return 0

    monkeypatch.setattr(probe.agent_runner, "run_agent", fake_run_agent)

    result = probe.main(
        ["--backend", "claude", "--output-dir", str(output_dir)]
    )

    assert result == 1
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["protected_marker_unchanged"] is (not mutate_protected)
    assert summary["read_marker_observed"] is include_read_marker
    assert summary["edit_denial_observed"] is True
    assert summary["bash_denial_observed"] is True


def test_probe_fails_when_agent_skips_denial_attempts(tmp_path, monkeypatch):
    probe = load_probe()
    output_dir = tmp_path / "skipped-denials"
    monkeypatch.setattr(probe, "backend_version", lambda backend: "test-version")

    def fake_run_agent(argv):
        raw_output = Path(option_value(argv, "--raw-output"))
        raw_output.write_text(
            json.dumps(
                {
                    "type": "result",
                    "subtype": "success",
                    "is_error": False,
                    "result": "agent-session-permission-probe-read-ok",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        Path(option_value(argv, "--stderr-output")).write_text("", encoding="utf-8")
        return 0

    monkeypatch.setattr(probe.agent_runner, "run_agent", fake_run_agent)

    result = probe.main(
        ["--backend", "claude", "--output-dir", str(output_dir)]
    )

    assert result == 1
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["read_marker_observed"] is True
    assert summary["protected_marker_unchanged"] is True
    assert summary["edit_denial_observed"] is False
    assert summary["bash_denial_observed"] is False


def test_probe_refuses_to_overwrite_existing_evidence(tmp_path, monkeypatch, capsys):
    probe = load_probe()
    output_dir = tmp_path / "existing"
    output_dir.mkdir()
    sentinel = output_dir / "keep.txt"
    sentinel.write_text("keep\n", encoding="utf-8")
    launched = False

    def fail_if_launched(argv):
        nonlocal launched
        launched = True
        raise AssertionError("the runner must not overwrite existing evidence")

    monkeypatch.setattr(probe.agent_runner, "run_agent", fail_if_launched)

    result = probe.main(
        ["--backend", "opencode", "--output-dir", str(output_dir)]
    )

    assert result == 2
    assert launched is False
    assert sentinel.read_text(encoding="utf-8") == "keep\n"
    assert "output directory is not empty" in capsys.readouterr().err
