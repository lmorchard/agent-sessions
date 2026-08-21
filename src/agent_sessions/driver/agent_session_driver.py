#!/usr/bin/env python3
"""Entry point for the agent session board driver. **Defines nothing itself.**

The driver is a stateless state machine: it evaluates GitHub repository state (issues,
PRs, review comments, CI status) and dispatches tightly-scoped, short-lived LLM agents.
None of that logic is here.

**Where the code actually lives**, because this file's name suggests otherwise and that
has sent people to the wrong place:

- `lifecycle.py` -- the run lifecycle and `main()`. `preflight`, `select_queue`,
  `invoke_agent`, `classify_and_record`, `report_results`. This is the file you want.
- `router.py` -- which issue, which phase; a pure function over fetched state.
- `gate.py` -- parses the merge-gate block and classifies the outcome.
- `writes.py` -- validates and executes the agent's requested writes.
- `agent_runner.py` -- the backend boundary and its mandatory permission policy.
- `output.py` -- `say`/`log`/`die` and `now()`, the driver's clock. **Not re-exported
  here.** Nothing imported them through this module, and leaving them would invite
  `monkeypatch.setattr(agent_session_driver, "log", ...)`, which binds a copy and
  silently patches nothing -- the same trap `CURRENT_LOCK_ISSUE` set. Patch the module
  that emits.

This module is a facade kept for two reasons: `pyproject.toml`'s `[project.scripts]`
entry and `driver/agent-session-driver.sh` both name it, and a large amount of the test
suite imports symbols through it. It re-exports rather than re-implements.

It used to be more than that. It re-exported the stdlib `datetime` so tests could freeze
time by patching one attribute, which made five other modules import this one from inside
function bodies purely to reach the clock -- an import cycle in service of a seam. The
clock is now `output.now()`. If you are adding something here, that is a sign it belongs
in one of the modules above instead.
"""

from __future__ import annotations

import sys

from agent_sessions.driver.board import (
    _BOARD_METADATA_CACHE,
    _cmd_error_msg,
    board_command,
    check_and_handle_rate_limit,
    fetch_board_json,
    get_board_metadata,
    mark_board_in_progress,
)
from agent_sessions.driver.lifecycle import (
    PHASE_TIERS,
    InvocationResult,
    RunContext,
    RunOutcome,
    SelectionResult,
    abspath,
    classify_and_record,
    invoke_agent,
    is_git_ignored,
    load_env_file,
    main,
    preflight,
    prepare_workspace,
    report_results,
    run_classify_only,
    select_queue,
    whoami,
)
from agent_sessions.driver.locks import (
    CURRENT_LOCK_ISSUE,
    acquire_lock,
    release_lock,
)
from agent_sessions.driver.parking import (
    INTERACTIVE_LABEL,
    MARKER,
    MERGE_READY_LABEL,
    PARK_LABEL,
    SPEC_LABEL,
    apply_park_state,
    clear_attempt_labels,
    decrement_attempts,
    get_attempts,
    get_park_time,
    has_new_human_comment,
    increment_attempts,
    is_specced,
    notify_human,
    park_label_add,
    park_label_remove,
    park_reason,
    parked_numbers,
)
from agent_sessions.driver.pr_checks import (
    build_prompt,
    check_pr_ci_status,
    check_pr_reviews,
    check_pr_unresolved_threads,
    get_pr_unresolved_threads_text,
    perform_writes,
    writes_summary,
)

__all__ = [
    "CURRENT_LOCK_ISSUE",
    "INTERACTIVE_LABEL",
    "InvocationResult",
    "MARKER",
    "MERGE_READY_LABEL",
    "PARK_LABEL",
    "PHASE_TIERS",
    "RunContext",
    "RunOutcome",
    "SPEC_LABEL",
    "SelectionResult",
    "_BOARD_METADATA_CACHE",
    "_cmd_error_msg",
    "abspath",
    "acquire_lock",
    "apply_park_state",
    "board_command",
    "build_prompt",
    "check_and_handle_rate_limit",
    "check_pr_ci_status",
    "check_pr_reviews",
    "check_pr_unresolved_threads",
    "classify_and_record",
    "clear_attempt_labels",
    "decrement_attempts",
    "fetch_board_json",
    "get_attempts",
    "get_board_metadata",
    "get_park_time",
    "get_pr_unresolved_threads_text",
    "has_new_human_comment",
    "increment_attempts",
    "invoke_agent",
    "is_git_ignored",
    "is_specced",
    "load_env_file",
    "main",
    "mark_board_in_progress",
    "notify_human",
    "park_label_add",
    "park_label_remove",
    "park_reason",
    "parked_numbers",
    "perform_writes",
    "preflight",
    "prepare_workspace",
    "release_lock",
    "report_results",
    "run_classify_only",
    "select_queue",
    "whoami",
    "writes_summary",
]

if __name__ == "__main__":
    sys.exit(main())
