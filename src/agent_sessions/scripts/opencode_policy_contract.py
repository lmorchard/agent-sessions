#!/usr/bin/env python3
"""Model-free contract check for the supported OpenCode permission boundary."""

from __future__ import annotations

import fnmatch
import json
import os
import subprocess
import tempfile
from pathlib import Path

from agent_sessions.driver import agent_runner

COMMAND_TIMEOUT_SECONDS = 30


class ContractError(RuntimeError):
    """The installed OpenCode binary violated the runner's safety contract."""


def run_debug(
    command: str,
    arguments: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [command, "--pure", "debug", "agent", *arguments],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        raise ContractError("OpenCode contract command timed out") from error


def last_permission_action(
    rules: list[dict[str, object]], permission: str, resource: str
) -> str:
    action = ""
    for rule in rules:
        rule_permission = rule.get("permission")
        pattern = rule.get("pattern")
        if rule_permission not in ("*", permission) or not isinstance(pattern, str):
            continue
        if fnmatch.fnmatchcase(resource, pattern):
            candidate = rule.get("action")
            if isinstance(candidate, str):
                action = candidate
    return action


def require_denial(result: subprocess.CompletedProcess[str], label: str) -> None:
    output = f"{result.stdout}\n{result.stderr}".lower()
    if "prevents you from using this specific tool call" not in output:
        raise ContractError(f"{label} did not report a permission-rule denial")


def run_contract() -> None:
    command, error = agent_runner.verified_opencode_command()
    if error:
        raise ContractError(error)

    with tempfile.TemporaryDirectory(prefix="agent-session-opencode-contract-") as root:
        root_path = Path(root)
        repo = root_path / "repo"
        skill = root_path / "skill"
        config_home = root_path / "xdg"
        repo.mkdir()
        skill.mkdir()
        config_home.mkdir()

        agent_name = "agent-session-contract"
        protected = skill / "protected-marker.txt"
        protected.write_text("protected-original\n", encoding="utf-8")
        custom_tool_marker = root_path / "custom-tool-loaded.txt"
        home_tool_marker = root_path / "home-tool-loaded.txt"

        target_policy = {
            "agent": {
                agent_name: {
                    "disable": True,
                    "permission": {
                        "edit": {
                            str(skill): "allow",
                            f"{skill}/**": "allow",
                            "*": "allow",
                        },
                        "task": "allow",
                    },
                },
                "build": {"permission": {"edit": {"*": "allow"}}},
            }
        }
        (repo / "opencode.json").write_text(
            json.dumps(target_policy), encoding="utf-8"
        )
        tools_dir = repo / ".opencode" / "tools"
        tools_dir.mkdir(parents=True)
        (tools_dir / "escape.ts").write_text(
            f'''await Bun.write({json.dumps(str(custom_tool_marker))}, "loaded");
export default {{
  description: "contract escape fixture",
  args: {{}},
  async execute() {{ return "loaded"; }}
}};
''',
            encoding="utf-8",
        )
        adversarial_home = root_path / "adversarial-home"
        home_tools_dir = adversarial_home / ".opencode" / "tools"
        home_tools_dir.mkdir(parents=True)
        (home_tools_dir / "escape-home.ts").write_text(
            f'''await Bun.write({json.dumps(str(home_tool_marker))}, "loaded");
export default {{
  description: "home contract escape fixture",
  args: {{}},
  async execute() {{ return "loaded"; }}
}};
''',
            encoding="utf-8",
        )

        policy = json.dumps(
            agent_runner.opencode_permission_policy(skill, agent_name),
            separators=(",", ":"),
        )
        inherited = dict(os.environ)
        inherited.update(
            {
                "OPENCODE_CONFIG": str(repo / "opencode.json"),
                "OPENCODE_CONFIG_DIR": str(repo / ".opencode"),
                "OPENCODE_PERMISSION": json.dumps({"edit": "allow"}),
                "OPENCODE_TEST_HOME": str(adversarial_home),
            }
        )
        env = agent_runner.isolated_opencode_env(inherited, policy, config_home)

        resolved = run_debug(command, [agent_name], cwd=repo, env=env)
        if resolved.returncode != 0:
            raise ContractError(f"runner-owned agent did not resolve: {resolved.stderr}")
        try:
            agent = json.loads(resolved.stdout)
        except json.JSONDecodeError as decode_error:
            raise ContractError("resolved agent output was not JSON") from decode_error
        if agent.get("name") != agent_name:
            raise ContractError("OpenCode fell back from the selected runner-owned agent")
        rules = agent.get("permission")
        if not isinstance(rules, list):
            raise ContractError("resolved agent omitted permission rules")
        if last_permission_action(rules, "task", "*") != "deny":
            raise ContractError("delegation is not denied by the effective policy")

        edit = run_debug(
            command,
            [
                agent_name,
                "--tool",
                "edit",
                "--params",
                json.dumps(
                    {
                        "filePath": str(protected),
                        "oldString": "protected-original",
                        "newString": "changed",
                    }
                ),
            ],
            cwd=repo,
            env=env,
        )
        require_denial(edit, "protected edit")
        if protected.read_text(encoding="utf-8") != "protected-original\n":
            raise ContractError("protected marker changed")

        bash = run_debug(
            command,
            [
                agent_name,
                "--tool",
                "bash",
                "--params",
                json.dumps({"command": "gh pr merge --help"}),
            ],
            cwd=repo,
            env=env,
        )
        require_denial(bash, "merge command")
        if custom_tool_marker.exists():
            raise ContractError("target custom tool executed during discovery")
        if home_tool_marker.exists():
            raise ContractError("user-home custom tool executed during discovery")


def main() -> int:
    try:
        run_contract()
    except ContractError as error:
        print(f"opencode-policy-contract: FAIL: {error}")
        return 1
    print("opencode-policy-contract: config roots isolated and mandatory denials hold")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
