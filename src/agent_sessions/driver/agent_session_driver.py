#!/usr/bin/env python3
"""Agent session board driver and reconciliation loop in Python.

Stateless state machine that evaluates GitHub repository state (issues, PRs,
review comments, CI status) and dispatches tightly-scoped, short-lived LLM agents.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

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
    die,
    invoke_agent,
    is_git_ignored,
    load_env_file,
    log,
    main,
    preflight,
    prepare_workspace,
    report_results,
    run_classify_only,
    say,
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
    "datetime",
    "decrement_attempts",
    "die",
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
    "log",
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
    "say",
    "select_queue",
    "timezone",
    "whoami",
    "writes_summary",
]

if __name__ == "__main__":
    sys.exit(main())
