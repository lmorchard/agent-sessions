#!/usr/bin/env python3
"""Deterministic swarm runner for parallel subagent execution.

Dispatches parallel implementer subagents via driver/agent_runner.py,
monitors process PIDs, validates TDD stream compliance via validate_tdd.py,
and verifies exit statuses deterministically.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from agent_sessions.scripts.validate_tdd import validate_stream

SCRIPTS_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPTS_DIR.parent


def run_swarm(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deterministic parallel swarm runner")
    parser.add_argument("prompt_files", nargs="*", help="Prompt files for parallel subagent tasks")
    parser.add_argument("--tasks-file", help="Path to JSON file specifying tasks")
    parser.add_argument("--tier", choices=["high", "low"], default="low")
    parser.add_argument("--high-tier-model", default=os.environ.get("HIGH_TIER_MODEL", ""))
    parser.add_argument("--low-tier-model", default=os.environ.get("LOW_TIER_MODEL", ""))
    parser.add_argument("--repo-path", default=str(ROOT_DIR))
    parser.add_argument("--skill-dir", default=str(ROOT_DIR / "skills" / "agent-session"))
    parser.add_argument("--results-output", default="runs/swarm_results.json")

    args = parser.parse_args(argv)

    tasks = []
    if args.tasks_file:
        tasks_path = Path(args.tasks_file)
        if not tasks_path.exists():
            print(f"error: tasks file {args.tasks_file} not found", file=sys.stderr)
            return 1
        with open(tasks_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            tasks = data.get("tasks", [])
    elif args.prompt_files:
        for i, pf in enumerate(args.prompt_files, start=1):
            stem = Path(pf).stem
            tasks.append({
                "id": stem or f"task_{i}",
                "prompt_file": pf,
                "raw_output": f"runs/{stem}_stream.jsonl",
                "stderr_output": f"runs/{stem}_stderr.txt",
            })
    else:
        print("error: specify prompt_files or --tasks-file", file=sys.stderr)
        return 1

    agent_runner_py = ROOT_DIR / "driver" / "agent_runner.py"
    if not agent_runner_py.exists():
        print(f"error: agent_runner.py not found at {agent_runner_py}", file=sys.stderr)
        return 1

    procs = []
    for task in tasks:
        task_id = task.get("id", "task")
        prompt_file = task.get("prompt_file")
        raw_output = task.get("raw_output", f"runs/{task_id}_stream.jsonl")
        stderr_output = task.get("stderr_output", f"runs/{task_id}_stderr.txt")

        Path(raw_output).parent.mkdir(parents=True, exist_ok=True)
        Path(stderr_output).parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            sys.executable,
            str(agent_runner_py),
            "run",
            "--tier", args.tier,
            "--repo-path", args.repo_path,
            "--skill-dir", args.skill_dir,
            "--prompt-file", prompt_file,
            "--raw-output", raw_output,
            "--stderr-output", stderr_output,
        ]
        if args.high_tier_model:
            cmd.extend(["--high-tier-model", args.high_tier_model])
        if args.low_tier_model:
            cmd.extend(["--low-tier-model", args.low_tier_model])

        env = dict(os.environ)
        if args.high_tier_model:
            env["HIGH_TIER_MODEL"] = args.high_tier_model
        if args.low_tier_model:
            env["LOW_TIER_MODEL"] = args.low_tier_model

        proc = subprocess.Popen(cmd, cwd=args.repo_path, env=env)
        procs.append({
            "task": task,
            "proc": proc,
            "raw_output": raw_output,
        })

    all_passed = True
    results = []

    for item in procs:
        task = item["task"]
        proc = item["proc"]
        raw_output = Path(item["raw_output"])

        returncode = proc.wait()
        process_ok = (returncode == 0)

        tdd_ok = validate_stream(raw_output) if raw_output.exists() else True

        check_cmd = task.get("check_command")
        check_ok = True
        if check_cmd:
            check_res = subprocess.run(check_cmd, shell=True, cwd=args.repo_path)
            check_ok = (check_res.returncode == 0)

        task_passed = process_ok and tdd_ok and check_ok
        if not task_passed:
            all_passed = False

        results.append({
            "id": task.get("id"),
            "passed": task_passed,
            "process_exit_code": returncode,
            "tdd_valid": tdd_ok,
            "check_ok": check_ok,
        })

    results_path = Path(args.results_output)
    results_path.parent.mkdir(parents=True, exist_ok=True)
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump({"passed": all_passed, "tasks": results}, f, indent=2)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(run_swarm())
