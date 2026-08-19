"""GitHub Project Board API queries and status edits."""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import timezone

from agent_sessions.driver import credentials, gh_query


def say(msg: str) -> None:
    from agent_sessions.driver import agent_session_driver

    agent_session_driver.say(msg)


def log(msg: str) -> None:
    from agent_sessions.driver import agent_session_driver

    agent_session_driver.log(msg)


def die(msg: str, code: int = 2) -> None:
    from agent_sessions.driver import agent_session_driver

    agent_session_driver.die(msg, code)


_BOARD_METADATA_CACHE: dict[str, dict | None] = {}


def board_command(board: str, limit: int = 500) -> list[str]:
    owner, num = board.split("/", 1)
    return ["gh", "project", "item-list", num, "--owner", owner, "--format", "json", "--limit", str(limit)]


def fetch_board_json(board: str) -> list[dict]:
    if not board or "/" not in board:
        return []
    try:
        env = credentials.board_env(dict(os.environ), credentials.resolve())
        res = subprocess.run(board_command(board), capture_output=True, text=True, check=True, env=env)
        data = json.loads(res.stdout)
        items = data.get("items", [])
        say(f"board {board}: read {len(items)} items (advisory only; does not gate)")
        return items if isinstance(items, list) else []
    except Exception as e:
        detail = getattr(e, "stderr", "") or str(e)
        say(f"board {board}: UNREADABLE ({' '.join(str(detail).split())[:120]}) -- selection falls back to priority labels")
        return []


def _cmd_error_msg(e: Exception) -> str:
    err = getattr(e, "stderr", "")
    if isinstance(err, str) and err.strip():
        return ' '.join(err.strip().split())
    return str(e)


def get_board_metadata(board: str, retries: int = 3) -> dict | None:
    if board in _BOARD_METADATA_CACHE and _BOARD_METADATA_CACHE[board] is not None:
        return _BOARD_METADATA_CACHE[board]

    if not board or "/" not in board:
        return None

    owner, number = board.split("/", 1)
    last_err = ""
    env = credentials.board_env(dict(os.environ), credentials.resolve())
    for attempt in range(retries):
        try:
            res = subprocess.run(["gh", "project", "view", number, "--owner", owner, "--format", "json"], capture_output=True, text=True, check=True, env=env)
            project_id = json.loads(res.stdout)["id"]

            res = subprocess.run(["gh", "project", "field-list", number, "--owner", owner, "--format", "json"], capture_output=True, text=True, check=True, env=env)
            fields = json.loads(res.stdout).get("fields", [])
            status_field = next((f for f in fields if f.get("name") == "Status"), None)
            if not status_field:
                return None

            field_id = status_field["id"]
            in_progress_opt = next((o for o in status_field.get("options", []) if o.get("name") == "In progress"), None)
            if not in_progress_opt:
                return None

            option_id = in_progress_opt["id"]

            meta = {
                "project_id": project_id,
                "field_id": field_id,
                "option_id": option_id
            }
            _BOARD_METADATA_CACHE[board] = meta
            return meta
        except Exception as e:
            last_err = _cmd_error_msg(e)
            if attempt < retries - 1:
                time.sleep(1 * (attempt + 1))
                continue

    log(f"failed to get board metadata for {board}: {last_err}")
    return None


def mark_board_in_progress(board: str, item_id: str, retries: int = 3) -> bool:
    meta = get_board_metadata(board)
    if not meta:
        return False

    last_err = ""
    env = credentials.board_env(dict(os.environ), credentials.resolve())
    for attempt in range(retries):
        try:
            subprocess.run([
                "gh", "project", "item-edit",
                "--id", item_id,
                "--project-id", str(meta["project_id"]),
                "--field-id", str(meta["field_id"]),
                "--single-select-option-id", str(meta["option_id"])
            ], capture_output=True, text=True, check=True, env=env)
            return True
        except Exception as e:
            last_err = _cmd_error_msg(e)
            if attempt < retries - 1:
                time.sleep(1 * (attempt + 1))
                continue

    log(f"failed to mark item {item_id} in progress: {last_err}")
    return False


def check_and_handle_rate_limit(
    env: dict | None = None,
    min_headroom: int = 20,
    max_wait_seconds: int = 300,
    say_fn=print,
) -> None:
    from agent_sessions.driver import agent_session_driver

    remaining, limit, reset = gh_query.check_rate_limit(env)
    if remaining >= min_headroom:
        return

    now_epoch = int(agent_session_driver.datetime.now(timezone.utc).timestamp())
    wait_sec = max(1, reset - now_epoch + 2) if reset > now_epoch else 1
    reset_dt = agent_session_driver.datetime.fromtimestamp(reset, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if reset else "soon"

    if wait_sec <= max_wait_seconds:
        say_fn(
            f"RATE LIMIT: GraphQL points low ({remaining}/{limit}). "
            f"Backing off for {wait_sec}s until reset at {reset_dt}..."
        )
        time.sleep(wait_sec)
        rem2, lim2, _ = gh_query.check_rate_limit(env)
        say_fn(f"Resuming run after rate limit backoff: {rem2}/{lim2} GraphQL points available.")
    else:
        wait_min = round(wait_sec / 60)
        die(
            f"refusing to start: GitHub GraphQL API rate limit exhausted ({remaining}/{limit} remaining). "
            f"Resets in ~{wait_min}m at {reset_dt}."
        )
