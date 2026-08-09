import json
import os
import subprocess
from pathlib import Path

def test_c3_settings_in_argv():
    with open("driver/agent_session_driver.py") as f:
        content = f.read()
    assert '--settings' in content, "C3: driver does not pass --settings to claude"

def test_c3_hook_json_structure():
    with open("driver/settings.json") as f:
        settings = json.load(f)
    assert "PreToolUse" in settings.get("hooks", {}), "C3: PreToolUse hook not defined in settings.json"
    hooks = settings["hooks"]["PreToolUse"]
    assert len(hooks) > 0, "C3: PreToolUse hook list is empty"
    assert hooks[0].get("tool_name") == "Bash", "C3: PreToolUse hook does not target Bash"

def test_c3_rendered_settings_points_to_executable():
    hook_script = Path("driver/merge-block-hook.sh").resolve()
    template = Path("driver/settings.json").resolve()
    
    res = subprocess.run(
        ["jq", "--arg", "script", str(hook_script), ".hooks.PreToolUse[0].command = $script", str(template)],
        capture_output=True, text=True, check=True
    )
    rendered = json.loads(res.stdout)
    command = rendered["hooks"]["PreToolUse"][0]["command"]
    
    assert command == str(hook_script), "C3: Rendered settings does not point to the expected hook script"
    assert os.access(command, os.X_OK), "C3: Rendered hook script is not executable"
