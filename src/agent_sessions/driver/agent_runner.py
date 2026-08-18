#!/usr/bin/env python3
"""Agent execution runner and stream parser for claude and opencode backends.

Provides unified execution, timeout management, output stream capture,
and result/cost/session parsing for agent-session driver.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

try:
    from agent_sessions.scripts import run_progress  # type: ignore[no-redef]

    from . import credentials
except ImportError:  # invoked as a script rather than imported as a package
    import credentials  # type: ignore[no-redef]

    from agent_sessions.scripts import run_progress  # type: ignore[no-redef]

#: Where the agent records the GitHub writes it wants the driver to perform.
WRITES_FILE_VAR = "AGENT_SESSION_WRITES"


def run_agent(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run agent backend")
    p.add_argument("--backend", choices=["claude", "opencode"], default="claude")
    p.add_argument("--repo-path", required=True)
    p.add_argument("--skill-dir", required=True)
    p.add_argument("--prompt-file", required=True)
    p.add_argument("--raw-output", required=True)
    p.add_argument("--stderr-output", required=True)
    p.add_argument("--max-budget", type=float, default=10.0)
    p.add_argument("--timeout", type=int, default=5400)
    p.add_argument("--progress-interval", type=float, default=10.0)
    p.add_argument("--model", default="")
    p.add_argument("--high-tier-model", default="")
    p.add_argument("--low-tier-model", default="")
    p.add_argument("--tier", choices=["high", "low"], default="high")
    p.add_argument("--allowed-tools", default="")
    p.add_argument("--disallowed-tools", default="")
    p.add_argument("--settings", default="")
    p.add_argument(
        "--writes-file",
        default="",
        help="path the agent appends its intended GitHub writes to; exported as AGENT_SESSION_WRITES",
    )

    args = p.parse_args(argv)

    repo_path = Path(args.repo_path).resolve()
    skill_dir = Path(args.skill_dir).resolve()
    prompt_file = Path(args.prompt_file).resolve()
    raw_output = Path(args.raw_output).resolve()
    stderr_output = Path(args.stderr_output).resolve()

    if not prompt_file.is_file():
        stderr_output.write_text(f"error: prompt file not found: {prompt_file}\n")
        return 2

    prompt_text = prompt_file.read_text(encoding="utf-8")

    target_model = args.model
    if not target_model:
        if args.tier == "low" and args.low_tier_model:
            target_model = args.low_tier_model
        elif args.tier == "high" and args.high_tier_model:
            target_model = args.high_tier_model
        elif args.high_tier_model:
            target_model = args.high_tier_model
        elif args.low_tier_model:
            target_model = args.low_tier_model
        else:
            target_model = os.environ.get("MODEL", "")

    if args.backend == "claude":
        cmd = [
            "claude",
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--permission-mode",
            "dontAsk",
            "--allowedTools",
            args.allowed_tools,
            "--disallowedTools",
            args.disallowed_tools,
            "--settings",
            args.settings,
            "--max-budget-usd",
            str(args.max_budget),
            "--add-dir",
            str(skill_dir),
        ]
        if target_model:
            cmd.extend(["--model", target_model])
        stdin_data = prompt_text.encode("utf-8")
    elif args.backend == "opencode":
        cmd = [
            "opencode",
            "run",
            prompt_text,
            "--format",
            "json",
            "--auto",
            "--dir",
            str(repo_path),
        ]
        if target_model:
            cmd.extend(["-m", target_model])
        stdin_data = None
    else:
        stderr_output.write_text(f"error: unknown backend: {args.backend}\n")
        return 2

    raw_output.parent.mkdir(parents=True, exist_ok=True)
    stderr_output.parent.mkdir(parents=True, exist_ok=True)

    # The agent's credential, not the driver's: `agent_env` installs the read-scoped
    # token and strips every write-capable one. This is the containment layer --
    # the prompt and the PreToolUse hook are defence in depth behind it.
    env = credentials.agent_env(dict(os.environ), credentials.resolve())
    if args.writes_file:
        env[WRITES_FILE_VAR] = str(Path(args.writes_file).resolve())
    if args.high_tier_model:
        env["HIGH_TIER_MODEL"] = args.high_tier_model
    if args.low_tier_model:
        env["LOW_TIER_MODEL"] = args.low_tier_model
    if args.model and not env.get("MODEL"):
        env["MODEL"] = args.model

    try:
        import time
        start_time = time.time()
        with open(raw_output, "wb") as out_f, open(stderr_output, "wb") as err_f:
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE if stdin_data is not None else None,
                stdout=out_f,
                stderr=err_f,
                cwd=str(repo_path),
                env=env,
            )
            if stdin_data is not None and process.stdin is not None:
                try:
                    process.stdin.write(stdin_data)
                    process.stdin.close()
                except Exception:
                    pass

            while True:
                # Check overall timeout first
                elapsed = time.time() - start_time
                remaining = args.timeout - elapsed
                if remaining <= 0:
                    try:
                        process.kill()
                    except Exception:
                        pass
                    with open(stderr_output, "ab") as err_f:
                        err_f.write(f"error: timed out after {args.timeout}s\n".encode("utf-8"))
                    return 124

                poll_timeout = min(args.progress_interval, remaining)
                try:
                    returncode = process.wait(timeout=poll_timeout)
                    return returncode
                except subprocess.TimeoutExpired:
                    # Check if progress summarization can be printed to sys.stderr
                    try:
                        snap = run_progress.read_progress(raw_output.parent)
                        digest = run_progress.format_progress(snap)
                        sys.stderr.write(f"{digest}\n")
                        sys.stderr.flush()
                    except Exception:
                        pass
    except subprocess.TimeoutExpired:
        with open(stderr_output, "ab") as err_f:
            err_f.write(f"error: timed out after {args.timeout}s\n".encode("utf-8"))
        return 124
    except Exception as e:
        with open(stderr_output, "ab") as err_f:
            err_f.write(f"error: execution failed: {e}\n".encode("utf-8"))
        return 1


def parse_result_stream(backend: str, raw_path: Path) -> dict:
    """Parse raw output stream and return normalized result dict:
    {
      "final": str,
      "total_cost_usd": float,
      "session_id": str,
      "cost_known": bool
    }
    """
    if not raw_path.exists() or raw_path.stat().st_size == 0:
        return {"final": "", "total_cost_usd": 0.0, "session_id": "", "cost_known": False}

    lines = raw_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    events = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    if backend == "claude":
        results = [e for e in events if isinstance(e, dict) and e.get("type") == "result"]
        if not results:
            return {"final": "", "total_cost_usd": 0.0, "session_id": "", "cost_known": False}

        # Pick max by total_cost_usd
        best = max(results, key=lambda r: r.get("total_cost_usd", 0.0) or 0.0)
        final = best.get("result", "") or ""
        cost = float(best.get("total_cost_usd", 0.0) or 0.0)
        session = str(best.get("session_id", "") or "")
        cost_known = "total_cost_usd" in best
        return {
            "final": final,
            "total_cost_usd": cost,
            "session_id": session,
            "cost_known": cost_known,
        }

    elif backend == "opencode":
        # Opencode events: step_finish has cost, sessionID. Text events have text.
        session_id = ""
        total_cost = 0.0
        cost_known = False
        text_parts = []

        for e in events:
            if not isinstance(e, dict):
                continue
            sid = e.get("sessionID")
            if sid:
                session_id = str(sid)

            etype = e.get("type")
            if etype == "text":
                part = e.get("part")
                if isinstance(part, dict) and "text" in part:
                    text_parts.append(str(part["text"]))
            elif etype == "step_finish":
                part = e.get("part")
                if isinstance(part, dict):
                    c = part.get("cost")
                    if c is not None:
                        try:
                            total_cost = float(c)
                            cost_known = True
                        except (TypeError, ValueError):
                            pass

        final = "".join(text_parts)
        return {
            "final": final,
            "total_cost_usd": total_cost,
            "session_id": session_id,
            "cost_known": cost_known,
        }

    return {"final": "", "total_cost_usd": 0.0, "session_id": "", "cost_known": False}


def stream_has_events(raw_path: Path) -> bool:
    if not raw_path.exists() or raw_path.stat().st_size == 0:
        return False
    try:
        lines = raw_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        count = 0
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                json.loads(line)
                count += 1
            except (json.JSONDecodeError, ValueError):
                continue
        return count > 0
    except Exception:
        return False


def has_success_result(backend: str, raw_path: Path) -> bool:
    if not raw_path.exists() or raw_path.stat().st_size == 0:
        return False
    try:
        lines = raw_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(e, dict):
                continue
            if backend == "claude":
                if (
                    e.get("type") == "result"
                    and e.get("subtype") == "success"
                    and e.get("is_error") is not True
                ):
                    return True
            elif backend == "opencode":
                if e.get("type") == "step_finish":
                    part = e.get("part")
                    if isinstance(part, dict) and part.get("reason") == "stop":
                        return True
        return False
    except Exception:
        return False


def _main(argv: list[str] | None = None) -> int:
    if len(sys.argv) < 2:
        print("usage: agent_runner.py <run|parse|has-events|has-success> ...", file=sys.stderr)
        return 2

    cmd = sys.argv[1]
    if cmd == "run":
        return run_agent(sys.argv[2:])
    elif cmd == "parse":
        p = argparse.ArgumentParser()
        p.add_argument("--backend", choices=["claude", "opencode"], default="claude")
        p.add_argument("--raw-output", required=True)
        p.add_argument("--output-json", required=True)
        args = p.parse_args(sys.argv[2:])
        res = parse_result_stream(args.backend, Path(args.raw_output))
        Path(args.output_json).write_text(json.dumps(res, indent=2))
        return 0
    elif cmd == "has-events":
        p = argparse.ArgumentParser()
        p.add_argument("--raw-output", required=True)
        args = p.parse_args(sys.argv[2:])
        if stream_has_events(Path(args.raw_output)):
            return 0
        return 1
    elif cmd == "has-success":
        p = argparse.ArgumentParser()
        p.add_argument("--backend", choices=["claude", "opencode"], default="claude")
        p.add_argument("--raw-output", required=True)
        args = p.parse_args(sys.argv[2:])
        if has_success_result(args.backend, Path(args.raw_output)):
            return 0
        return 1
    else:
        print(f"unknown command: {cmd}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(_main())
