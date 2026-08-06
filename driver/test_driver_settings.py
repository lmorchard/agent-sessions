import json
from pathlib import Path

def test_c3_settings_in_argv():
    with open("driver/agent-session-driver.sh") as f:
        content = f.read()
    assert '--settings "$HOOK_SETTINGS_FILE"' in content, "C3: driver does not pass --settings to claude"

def test_c3_hook_json_structure():
    with open("driver/settings.json") as f:
        settings = json.load(f)
    assert "PreToolUse" in settings.get("hooks", {}), "C3: PreToolUse hook not defined in settings.json"
    hooks = settings["hooks"]["PreToolUse"]
    assert len(hooks) > 0, "C3: PreToolUse hook list is empty"
    assert hooks[0].get("tool_name") == "Bash", "C3: PreToolUse hook does not target Bash"
    
def test_c3_hook_executable():
    import os
    assert os.access("driver/merge-block-hook.sh", os.X_OK), "C3: Hook script is not executable"
