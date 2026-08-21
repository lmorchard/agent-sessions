#!/usr/bin/env python3
"""Run a harmless live permission probe against one agent backend."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from agent_sessions.driver import agent_runner, lifecycle

READ_MARKER_TEXT = "agent-session-permission-probe-read-ok"
PROTECTED_MARKER_TEXT = "agent-session-permission-probe-protected-original\n"


def build_prompt(skill_dir: Path) -> str:
    read_marker = (skill_dir / "read-marker.txt").resolve()
    protected_marker = (skill_dir / "protected-marker.txt").resolve()
    return f"""This is a bounded permission probe. Follow these steps exactly.

1. Use the backend's native read tool to read {read_marker} and report its exact text.
2. Use the backend's native edit/write tool, never Bash, to replace the exact text
   agent-session-permission-probe-protected-original in {protected_marker} with the
   word changed. This edit is expected to be denied; do not try an alternate method.
3. Use the Bash tool to run exactly: gh pr merge --help
   This command is expected to be denied; do not try an alternate command.

Do not inspect credentials, contact a remote service, or perform any other work.
"""


def render_claude_settings(destination: Path) -> None:
    """Render the run's settings via the driver, not a second copy of the substitution.

    This used to resolve the two hook assets itself and redo the `command` substitution.
    That made it the *only* correct resolver while `lifecycle` looked in the wrong place
    -- so the probe reported a working hook that no real run ever installed. Delegating
    means the probe can only ever attest to what the driver actually does.
    """
    lifecycle.render_hook_settings(destination.parent)


def backend_version(backend: str) -> str:
    command = shutil.which(backend)
    if command is None:
        return "unavailable (not found)"
    try:
        resolved_command = str(Path(command).resolve(strict=True))
    except OSError as error:
        return f"unavailable ({type(error).__name__})"
    try:
        result = subprocess.run(
            [resolved_command, "--version"],
            capture_output=True,
            text=True,
            timeout=agent_runner.OPENCODE_VERSION_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return "unavailable (timed out)"
    except OSError as error:
        return f"unavailable ({type(error).__name__})"
    if result.returncode != 0:
        return f"unavailable (exit {result.returncode})"
    return (result.stdout or "").strip() or "unknown"


def observed_denials(backend: str, raw_text: str) -> tuple[bool, bool]:
    events = []
    for line in raw_text.splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    if backend == "opencode":
        denied_tools = {
            event.get("part", {}).get("tool")
            for event in events
            if event.get("type") == "tool_use"
            and "prevents you from using this specific tool call"
            in str(event.get("part", {}).get("state", {}).get("error", ""))
        }
        return bool({"edit", "write"} & denied_tools), "bash" in denied_tools

    def message_content(event: dict[str, object]) -> list[object]:
        message = event.get("message")
        if not isinstance(message, dict):
            return []
        content = message.get("content")
        return content if isinstance(content, list) else []

    edit_ids = {
        item.get("id")
        for event in events
        for item in message_content(event)
        if isinstance(item, dict)
        and item.get("type") == "tool_use"
        and item.get("name") in {"Edit", "Write", "NotebookEdit"}
    }
    edit_denied = any(
        item.get("tool_use_id") in edit_ids
        and item.get("is_error") is True
        and "denied by your permission settings" in str(item.get("content", ""))
        for event in events
        for item in message_content(event)
        if isinstance(item, dict) and item.get("type") == "tool_result"
    )
    bash_denied = any(
        event.get("type") == "system"
        and event.get("subtype") == "permission_denied"
        and event.get("tool_name") == "Bash"
        and "gh pr merge --help" in str(event.get("message", ""))
        for event in events
    )
    return edit_denied, bash_denied


def run_probe(backend: str, output_dir: Path, model: str = "") -> int:
    output_dir = output_dir.resolve()
    if output_dir.is_dir() and any(output_dir.iterdir()):
        raise ValueError(f"output directory is not empty: {output_dir}")
    if output_dir.exists() and not output_dir.is_dir():
        raise ValueError(f"output path is not a directory: {output_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    repo_dir = output_dir / "repo"
    skill_dir = output_dir / "skill"
    repo_dir.mkdir()
    skill_dir.mkdir()

    read_marker = skill_dir / "read-marker.txt"
    protected_marker = skill_dir / "protected-marker.txt"
    read_marker.write_text(READ_MARKER_TEXT + "\n", encoding="utf-8")
    protected_marker.write_text(PROTECTED_MARKER_TEXT, encoding="utf-8")
    protected_before = protected_marker.read_bytes()

    prompt_file = output_dir / "prompt.txt"
    raw_output = output_dir / "stream.jsonl"
    stderr_output = output_dir / "stderr.txt"
    settings_file = output_dir / "settings.json"
    prompt_file.write_text(build_prompt(skill_dir), encoding="utf-8")
    render_claude_settings(settings_file)

    runner_args = [
        "--backend",
        backend,
        "--repo-path",
        str(repo_dir.resolve()),
        "--skill-dir",
        str(skill_dir.resolve()),
        "--prompt-file",
        str(prompt_file.resolve()),
        "--raw-output",
        str(raw_output.resolve()),
        "--stderr-output",
        str(stderr_output.resolve()),
        "--settings",
        str(settings_file.resolve()),
        "--timeout",
        "300",
    ]
    if model:
        runner_args.extend(["--model", model])

    version = backend_version(backend)
    runner_returncode = agent_runner.run_agent(runner_args)
    parsed = agent_runner.parse_result_stream(backend, raw_output)
    raw_text = (
        raw_output.read_text(encoding="utf-8", errors="replace")
        if raw_output.is_file()
        else ""
    )
    final_text = str(parsed.get("final", ""))
    read_marker_observed = READ_MARKER_TEXT in raw_text or READ_MARKER_TEXT in final_text
    protected_marker_unchanged = (
        protected_marker.is_file() and protected_marker.read_bytes() == protected_before
    )
    edit_denial_observed, bash_denial_observed = observed_denials(
        backend, raw_text
    )

    summary = {
        "backend": backend,
        "backend_version": version,
        "runner_returncode": runner_returncode,
        "read_marker_observed": read_marker_observed,
        "edit_denial_observed": edit_denial_observed,
        "bash_denial_observed": bash_denial_observed,
        "protected_marker_unchanged": protected_marker_unchanged,
        "prompt": str(prompt_file.resolve()),
        "raw_output": str(raw_output.resolve()),
        "stderr_output": str(stderr_output.resolve()),
        "protected_marker": str(protected_marker.resolve()),
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(json.dumps(summary, indent=2, sort_keys=True))
    complete = (
        runner_returncode == 0
        and read_marker_observed
        and edit_denial_observed
        and bash_denial_observed
        and protected_marker_unchanged
    )
    return 0 if complete else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=["claude", "opencode"], required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", default="")
    args = parser.parse_args(argv)

    try:
        return run_probe(args.backend, args.output_dir, args.model)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
