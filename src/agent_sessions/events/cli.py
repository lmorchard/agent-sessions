"""Command line interface for the event invalidation queue."""

from __future__ import annotations

import argparse
import os
import socket
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Sequence

import uvicorn

from agent_sessions.driver import credentials

from . import config, operations, pollers
from . import logging as event_logging
from .daemon import DaemonRuntime, ScheduledPoll
from .store import QueueStore
from .webhook import create_app

CONFIG_HELP = "shared TOML path (default: AGENT_SESSION_EVENTS_CONFIG)"


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _secret_from_environment(parser: argparse.ArgumentParser) -> bytes:
    value = os.environ.get("AGENT_SESSION_WEBHOOK_SECRET_FILE")
    if not value:
        parser.error("AGENT_SESSION_WEBHOOK_SECRET_FILE is required for serve")
    path = Path(value)
    try:
        details = path.stat()
    except OSError as error:
        parser.error(f"cannot read webhook secret file: {error}")
    if not stat.S_ISREG(details.st_mode) or details.st_uid != os.geteuid() or details.st_mode & 0o077:
        parser.error("webhook secret file must be a regular owner-only file")
    try:
        secret = path.read_bytes()
    except OSError as error:
        parser.error(f"cannot read webhook secret file: {error}")
    if secret.endswith(b"\n"):
        secret = secret[:-1]
    if not secret:
        parser.error("webhook secret file must not be empty")
    return secret


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-session-events",
        description="Receive GitHub hints and inspect or maintain the local queue.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=os.environ.get("AGENT_SESSION_EVENTS_CONFIG"),
        help=CONFIG_HELP,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    migrate = subparsers.add_parser(
        "migrate", help="apply schema migrations while services are stopped"
    )
    status = subparsers.add_parser(
        "queue-status", help="show backlog, lease, clock, and error state"
    )
    status.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    doctor = subparsers.add_parser(
        "doctor", help="run read-only configuration and capability probes"
    )
    prune = subparsers.add_parser(
        "prune", help="remove expired immutable history and checkpoint WAL"
    )
    prune.add_argument(
        "--deliveries-days", type=_positive_int, help="override delivery retention age"
    )
    prune.add_argument(
        "--invalidations-days", type=_positive_int, help="override invalidation retention age"
    )
    serve = subparsers.add_parser(
        "serve", help="run the loopback webhook receiver with one worker"
    )
    poll_projects = subparsers.add_parser(
        "poll-projects", help="poll configured Projects once, then exit"
    )
    poll_reactions = subparsers.add_parser(
        "poll-reactions", help="poll active approval watches once, then exit"
    )
    for command in (
        migrate,
        status,
        doctor,
        prune,
        serve,
        poll_projects,
        poll_reactions,
    ):
        command.add_argument(
            "--config", type=Path, default=argparse.SUPPRESS, help=CONFIG_HELP
        )
    return parser


def _worker_id(command: str) -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{command}"


def _reaction_bot_logins(read_login: str, extra: tuple[str, ...] = ()) -> frozenset[str]:
    """Machine logins for the reaction poller: always-bots, this daemon, plus config.

    Deliberately built from *this service's* inputs. `tests/events/test_poll_reactions.py`
    asserts the daemon reads neither `DRIVER_GH_LOGIN` nor `DRIVER_BOT_LOGINS` and refuses
    to inspect the board credential -- it does not inherit the driver's identity
    configuration. So `extra` arrives from `events.toml`'s `bot_logins`, which is this
    service's own configuration file, and the boundary holds.

    Why completeness matters rather than being a nicety: this set is what
    `_approval_predicate` uses to decide whether an actor is a human, and that decision
    can unpark an issue awaiting human judgment. A machine login missing from here is a
    machine that can approve.
    """
    return credentials.bot_logins(
        credentials.Credentials(login=read_login, extra_bot_logins=extra)
    )


def _disclose_bot_logins(command: str, logins: frozenset[str]) -> None:
    """Say which logins count as machines, once, at start.

    The set is opt-in, so an operator with an unlisted machine user otherwise finds out
    by being wrongly unparked. Printing the belief does not close that, but it makes it
    checkable without reading source -- the same reason `docs-check` prints "no claims
    found to check" rather than staying silent.
    """
    event_logging.emit(
        command.replace("-", "_"),
        message=f"machine logins honoured: {', '.join(sorted(logins))}",
    )


def _log_poll_result(command: str, result: pollers.PollRunResult) -> None:
    event_logging.emit(
        command.replace("-", "_"),
        message=(
            f"attempted={result.attempted} skipped={result.skipped} "
            f"invalidations={result.invalidations} errors={len(result.errors)}"
        ),
    )


def _scheduled_polls(
    loaded: config.EventsConfig,
    read_token: str,
    bot_logins: frozenset[str],
) -> tuple[ScheduledPoll, ...]:
    polls: list[ScheduledPoll] = []
    if loaded.boards:
        polls.append(
            ScheduledPoll(
                "poll-projects",
                loaded.polling.projects_interval,
                lambda store, now, stop_requested: pollers.poll_projects_once(
                    loaded,
                    store,
                    read_token,
                    worker_id=_worker_id("poll-projects"),
                    now=now,
                    stop_requested=stop_requested,
                ),
            )
        )
    polls.append(
        ScheduledPoll(
            "poll-reactions",
            loaded.polling.reactions_interval,
            lambda store, now, stop_requested: pollers.poll_reactions_once(
                loaded,
                store,
                read_token,
                bot_logins,
                worker_id=_worker_id("poll-reactions"),
                now=now,
                stop_requested=stop_requested,
            ),
        )
    )
    return tuple(polls)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.config is None:
        parser.error("--config or AGENT_SESSION_EVENTS_CONFIG is required")
    if args.command == "doctor":
        return operations.doctor(args.config)
    try:
        loaded = config.load(args.config)
    except (OSError, ValueError) as error:
        parser.error(f"invalid events configuration: {error}")
    if args.command == "migrate":
        return operations.migrate(loaded.database, busy_timeout_ms=loaded.busy_timeout_ms)
    if args.command == "serve":
        webhook_secret = _secret_from_environment(parser)
        try:
            read_token = credentials.resolve_read_credential()
            bot_logins = _reaction_bot_logins(
                credentials.resolve_read_login(read_token), loaded.bot_logins
            )
        except RuntimeError as error:
            event_logging.emit("serve", message=f"failed: {error}")
            return 1
        _disclose_bot_logins("serve", bot_logins)
        store = QueueStore.open(loaded.database, busy_timeout_ms=loaded.busy_timeout_ms)
        store.register_repositories(item.identity for item in loaded.repositories)
        runtime = DaemonRuntime(
            lambda: QueueStore.open(loaded.database, busy_timeout_ms=loaded.busy_timeout_ms),
            _scheduled_polls(loaded, read_token, bot_logins),
            _log_poll_result,
        )
        uvicorn.run(
            create_app(config=loaded, store=store, webhook_secret=webhook_secret, runtime=runtime),
            host="127.0.0.1",
            port=8080,
            workers=1,
        )
        return 0
    if args.command in {"poll-projects", "poll-reactions"}:
        store = QueueStore.open(loaded.database, busy_timeout_ms=loaded.busy_timeout_ms)
        store.register_repositories(item.identity for item in loaded.repositories)
        now = datetime.now(UTC)
        try:
            read_token = credentials.resolve_read_credential()
            if args.command == "poll-projects":
                result = pollers.poll_projects_once(
                    loaded,
                    store,
                    read_token,
                    worker_id=_worker_id(args.command),
                    now=now,
                )
            else:
                bot_logins = _reaction_bot_logins(
                    credentials.resolve_read_login(read_token), loaded.bot_logins
                )
                _disclose_bot_logins(args.command, bot_logins)
                result = pollers.poll_reactions_once(
                    loaded,
                    store,
                    read_token,
                    bot_logins,
                    worker_id=_worker_id(args.command),
                    now=now,
                )
        except RuntimeError as error:
            event_logging.emit(
                args.command.replace("-", "_"), message=f"failed: {error}"
            )
            return 1
        finally:
            store.close()
        _log_poll_result(args.command, result)
        return result.exit_code
    if args.command == "queue-status":
        return operations.queue_status(
            loaded.database,
            busy_timeout_ms=loaded.busy_timeout_ms,
            as_json=args.json,
            now=datetime.now(UTC),
        )
    now = datetime.now(UTC)
    return operations.prune(
        loaded.database,
        busy_timeout_ms=loaded.busy_timeout_ms,
        deliveries_before=now
        - timedelta(
            days=(
                loaded.delivery_retention.days
                if args.deliveries_days is None
                else args.deliveries_days
            )
        ),
        invalidations_before=now
        - timedelta(
            days=(
                loaded.invalidation_retention.days
                if args.invalidations_days is None
                else args.invalidations_days
            )
        ),
    )
