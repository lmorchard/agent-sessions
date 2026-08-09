from __future__ import annotations

import json
from pathlib import Path

import pytest
from run_swarm import run_swarm


def test_run_swarm_missing_args() -> None:
    assert run_swarm([]) == 1


def test_run_swarm_prompt_files_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt1 = tmp_path / "task_1.txt"
    prompt1.write_text("Prompt 1", encoding="utf-8")
    prompt2 = tmp_path / "task_2.txt"
    prompt2.write_text("Prompt 2", encoding="utf-8")

    results_out = tmp_path / "results.json"

    class MockProc:
        def wait(self) -> int:
            return 0

    def mock_popen(*args, **kwargs):
        return MockProc()

    monkeypatch.setattr("subprocess.Popen", mock_popen)

    ret = run_swarm([
        str(prompt1),
        str(prompt2),
        "--repo-path", str(tmp_path),
        "--results-output", str(results_out),
    ])
    assert ret == 0
    assert results_out.exists()
    data = json.loads(results_out.read_text(encoding="utf-8"))
    assert data["passed"] is True
    assert len(data["tasks"]) == 2


def test_run_swarm_tasks_file_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tasks_file = tmp_path / "tasks.json"
    tasks_file.write_text(json.dumps({
        "tasks": [
            {"id": "t1", "prompt_file": "p1.txt"},
            {"id": "t2", "prompt_file": "p2.txt"},
        ]
    }), encoding="utf-8")

    results_out = tmp_path / "results.json"

    class MockProcFail:
        def __init__(self, retcode: int):
            self._retcode = retcode

        def wait(self) -> int:
            return self._retcode

    call_count = 0

    def mock_popen(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return MockProcFail(0 if call_count == 1 else 1)

    monkeypatch.setattr("subprocess.Popen", mock_popen)

    ret = run_swarm([
        "--tasks-file", str(tasks_file),
        "--repo-path", str(tmp_path),
        "--results-output", str(results_out),
    ])
    assert ret == 1
    assert results_out.exists()
    data = json.loads(results_out.read_text(encoding="utf-8"))
    assert data["passed"] is False
    assert data["tasks"][0]["passed"] is True
    assert data["tasks"][1]["passed"] is False
