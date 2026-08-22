#!/usr/bin/env python3
"""Agent execution runner and stream parser for claude and opencode backends.

Provides unified execution, timeout management, output stream capture,
and result/cost/session parsing for agent-session driver.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from agent_sessions.scripts import run_progress

from . import credentials, jsonl

#: Where the agent records the GitHub writes it wants the driver to perform.
WRITES_FILE_VAR = "AGENT_SESSION_WRITES"

DEFAULT_ALLOWED_TOOLS = (
    "Read", "Write", "Edit", "Glob", "Grep", "Task", "TodoWrite",
    "BashOutput", "KillShell", "NotebookEdit", "Bash(*)",
)

BASE_DENIED_TOOLS = (
    "Bash(gh pr merge:*)",
    "Bash(gh pr merge *)",
    "Bash(git push --force:*)",
    "Bash(git push --force *)",
    "Bash(git push -f:*)",
    "Bash(git push -f *)",
    "Bash(gh repo delete:*)",
)
# What is deliberately NOT here, and why, so the gap is a decision rather than an
# oversight someone rediscovers.
#
# `gh api --method PUT .../pulls/N/merge` and the `curl` equivalent are the other two
# ways to merge, and OPENCODE_DENIED_COMMANDS below denies both. They are absent here
# because the merge endpoint appears *mid-command*, and these entries are prefix
# patterns -- `Bash(gh pr merge:*)` matches a command that starts that way. Whether
# Claude Code's rule syntax supports a mid-string glob is not something `--help`
# states, and findings.md defect class 5 is precisely "I wrote a guard" not being
# evidence. Adding an unverified pattern to a floor whose value is that it is verified
# would be the wrong trade.
#
# Those two vectors are covered by the PreToolUse hook instead
# (`merge-block-hook.sh`, cases 2 and 3), which greps the whole command line and is
# tested per-vector in tests/driver/test_merge_hook.py. Promoting them to tool-level
# rules as well needs one live run to confirm the syntax: `make backend-permission-probe
# BACKEND=claude EVIDENCE_DIR=...`. Until then the hook is the load-bearing layer for
# the REST paths, which is why its install is now fail-closed.

OPENCODE_CONFIG_VAR = "OPENCODE_CONFIG_CONTENT"
OPENCODE_AGENT_PREFIX = "agent-session"
OPENCODE_VERSION_TIMEOUT_SECONDS = 10
OPENCODE_INHERITED_OVERRIDES = (
    "OPENCODE_CONFIG",
    "OPENCODE_CONFIG_DIR",
    "OPENCODE_PERMISSION",
    "OPENCODE_TEST_HOME",
)
SUPPORTED_OPENCODE_VERSION = (1, 18, 18)
OPENCODE_DENIED_COMMANDS = (
    "gh pr merge",
    "gh pr merge *",
    "git push --force",
    "git push --force *",
    "git push -f",
    "git push -f *",
    "gh repo delete",
    "gh repo delete *",
    "gh api *pulls/*/merge*",
    "curl *pulls/*/merge*",
)


def compose_allowed_tools(requested: str = "") -> str:
    if not requested:
        return ",".join(DEFAULT_ALLOWED_TOOLS)

    rules = requested.split(",")
    unsupported = [rule for rule in rules if rule not in DEFAULT_ALLOWED_TOOLS]
    if unsupported:
        raise ValueError(
            "--allowed-tools may only narrow the default; unsupported rule(s): "
            + ", ".join(unsupported)
        )
    return requested


def mandatory_disallowed_tools(skill_dir: Path) -> tuple[str, ...]:
    return BASE_DENIED_TOOLS + tuple(
        f"{tool}(/{skill_dir}/**)" for tool in ("Edit", "Write", "NotebookEdit")
    )


def compose_disallowed_tools(skill_dir: Path, additional: str = "") -> str:
    rules = [*mandatory_disallowed_tools(skill_dir)]
    rules.extend(rule for rule in additional.split(",") if rule)
    return ",".join(rules)


def opencode_permission_policy(
    skill_dir: Path, agent_name: str
) -> dict[str, object]:
    skill = str(skill_dir.resolve())
    # OpenCode 1.18.18 evaluates `external_directory` against the canonical absolute
    # path, but evaluates `edit` against that path with its leading slash removed.
    # Cover both resource shapes; the live probe for issue #250 caught this mismatch.
    edit_resource = skill.removeprefix("/")
    permissions = {
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
            **dict.fromkeys(OPENCODE_DENIED_COMMANDS, "deny"),
        },
        # OpenCode 1.18.18 does not propagate an agent's configured mandatory
        # policy to delegated agents. Re-enable only with an independently enforced
        # subagent boundary.
        "task": "deny",
    }
    # Repeat the floor on a random selected agent as defense in depth. Target and
    # user component config are isolated separately at the child-env boundary.
    return {
        "permission": permissions,
        "agent": {
            agent_name: {
                "mode": "primary",
                "disable": False,
                "permission": permissions,
            }
        },
    }


def verified_opencode_command() -> tuple[str, str]:
    command = shutil.which("opencode")
    if command is None:
        return "", "could not find OpenCode executable"
    try:
        resolved_command = str(Path(command).resolve(strict=True))
    except OSError as error:
        return "", f"could not resolve OpenCode executable: {type(error).__name__}"

    try:
        result = subprocess.run(
            [resolved_command, "--version"],
            capture_output=True,
            text=True,
            timeout=OPENCODE_VERSION_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return "", "OpenCode version probe timed out"
    except OSError as error:
        return "", f"could not run OpenCode version probe: {type(error).__name__}"

    if result.returncode != 0:
        return "", f"OpenCode version probe exited {result.returncode}"

    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", (result.stdout or "").strip())
    if match is None:
        return "", "could not parse OpenCode version"

    version = tuple(int(part) for part in match.groups())
    if version != SUPPORTED_OPENCODE_VERSION:
        rendered = ".".join(str(part) for part in version)
        return "", f"unsupported OpenCode version {rendered}"
    return resolved_command, ""


def isolated_opencode_env(
    base_env: dict[str, str], policy: str, config_home: Path
) -> dict[str, str]:
    """Return an OpenCode child environment isolated from target configuration."""
    env = dict(base_env)
    for variable in OPENCODE_INHERITED_OVERRIDES:
        env.pop(variable, None)
    env.update(
        {
            OPENCODE_CONFIG_VAR: policy,
            "OPENCODE_DISABLE_PROJECT_CONFIG": "true",
            # v1.18.18 scans Global.Path.home/.opencode even when project config is
            # disabled. Its version-gated test-home hook is the only supported way
            # to isolate that loader without repurposing the child's HOME.
            "OPENCODE_TEST_HOME": str(config_home),
            "XDG_CONFIG_HOME": str(config_home),
        }
    )
    return env


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
    stderr_output.parent.mkdir(parents=True, exist_ok=True)

    if not prompt_file.is_file():
        stderr_output.write_text(
            f"error: prompt file not found: {prompt_file}\n", encoding="utf-8"
        )
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

    opencode_config_home: tempfile.TemporaryDirectory[str] | None = None

    if args.backend == "claude":
        try:
            allowed_tools = compose_allowed_tools(args.allowed_tools)
        except ValueError as e:
            stderr_output.write_text(f"error: {e}\n", encoding="utf-8")
            return 2

        cmd = [
            "claude",
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--permission-mode",
            "dontAsk",
            "--allowedTools",
            allowed_tools,
            "--disallowedTools",
            compose_disallowed_tools(skill_dir, args.disallowed_tools),
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
        for option, value in (
            ("--allowed-tools", args.allowed_tools),
            ("--disallowed-tools", args.disallowed_tools),
        ):
            if value:
                stderr_output.write_text(
                    f"error: {option} is only supported by the Claude backend\n",
                    encoding="utf-8",
                )
                return 2

        opencode_command, version_error = verified_opencode_command()
        if version_error:
            stderr_output.write_text(f"error: {version_error}\n", encoding="utf-8")
            return 2

        agent_name = f"{OPENCODE_AGENT_PREFIX}-{secrets.token_hex(8)}"
        try:
            policy = json.dumps(
                opencode_permission_policy(skill_dir, agent_name),
                separators=(",", ":"),
            )
        except (TypeError, ValueError):
            stderr_output.write_text(
                "error: could not serialize OpenCode permission policy\n",
                encoding="utf-8",
            )
            return 2

        try:
            opencode_config_home = tempfile.TemporaryDirectory(
                prefix="agent-session-opencode-"
            )
        except OSError as error:
            stderr_output.write_text(
                "error: could not create OpenCode config home: "
                f"{type(error).__name__}\n",
                encoding="utf-8",
            )
            return 2
        cmd = [
            opencode_command,
            "--pure",
            "run",
            prompt_text,
            "--format",
            "json",
            "--auto",
            "--agent",
            agent_name,
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

    # The agent's credential, not the driver's: `agent_env` installs the read-scoped
    # token and strips every write-capable one. This is the containment layer --
    # the prompt and the PreToolUse hook are defence in depth behind it.
    env = credentials.agent_env(dict(os.environ), credentials.resolve())
    if args.backend == "opencode":
        assert opencode_config_home is not None
        env = isolated_opencode_env(
            env, policy, Path(opencode_config_home.name)
        )
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
    finally:
        if opencode_config_home is not None:
            try:
                opencode_config_home.cleanup()
            except OSError as error:
                # The child has already exited and its result is authoritative. The
                # OS temp root remains the fallback cleanup boundary.
                try:
                    with open(stderr_output, "ab") as err_f:
                        err_f.write(
                            (
                                "warning: could not remove OpenCode config home: "
                                f"{type(error).__name__}\n"
                            ).encode("utf-8")
                        )
                except OSError:
                    pass


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

    events, _ = jsonl.read_records(raw_path)

    if backend == "claude":
        results = [e for e in events if e.get("type") == "result"]
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
        events, _ = jsonl.read_records(raw_path)
        for e in events:
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
    """Entry point. Reads `argv` when given, so it can be driven from a test.

    It previously declared `argv` and then read `sys.argv` throughout, which made the
    parameter a promise the function did not keep -- a caller passing a list would have
    been silently ignored and graded the process's real arguments instead.
    """
    tokens = list(sys.argv[1:] if argv is None else argv)
    if not tokens:
        print("usage: agent_runner.py <run|parse|has-events|has-success> ...", file=sys.stderr)
        return 2

    cmd = tokens[0]
    if cmd == "run":
        return run_agent(tokens[1:])
    elif cmd == "parse":
        p = argparse.ArgumentParser()
        p.add_argument("--backend", choices=["claude", "opencode"], default="claude")
        p.add_argument("--raw-output", required=True)
        p.add_argument("--output-json", required=True)
        args = p.parse_args(tokens[1:])
        res = parse_result_stream(args.backend, Path(args.raw_output))
        Path(args.output_json).write_text(json.dumps(res, indent=2))
        return 0
    elif cmd == "has-events":
        p = argparse.ArgumentParser()
        p.add_argument("--raw-output", required=True)
        args = p.parse_args(tokens[1:])
        if stream_has_events(Path(args.raw_output)):
            return 0
        return 1
    elif cmd == "has-success":
        p = argparse.ArgumentParser()
        p.add_argument("--backend", choices=["claude", "opencode"], default="claude")
        p.add_argument("--raw-output", required=True)
        args = p.parse_args(tokens[1:])
        if has_success_result(args.backend, Path(args.raw_output)):
            return 0
        return 1
    else:
        print(f"unknown command: {cmd}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(_main())
