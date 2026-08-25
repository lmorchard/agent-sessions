"""Initial command line interface for queue maintenance."""

from __future__ import annotations

import argparse
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Sequence

import uvicorn

from . import config, operations
from .store import QueueStore
from .webhook import create_app


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
    parser = argparse.ArgumentParser(prog="agent-session-events")
    parser.add_argument("--config", type=Path, default=os.environ.get("AGENT_SESSION_EVENTS_CONFIG"))
    subparsers = parser.add_subparsers(dest="command", required=True)
    migrate = subparsers.add_parser("migrate")
    status = subparsers.add_parser("queue-status")
    status.add_argument("--json", action="store_true")
    doctor = subparsers.add_parser("doctor")
    prune = subparsers.add_parser("prune")
    prune.add_argument("--deliveries-days", type=int)
    prune.add_argument("--invalidations-days", type=int)
    serve = subparsers.add_parser("serve")
    for command in (migrate, status, doctor, prune, serve):
        command.add_argument("--config", type=Path, default=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.config is None:
        parser.error("--config or AGENT_SESSION_EVENTS_CONFIG is required")
    loaded = config.load(args.config)
    if args.command == "migrate":
        return operations.migrate(loaded.database, busy_timeout_ms=loaded.busy_timeout_ms)
    if args.command == "serve":
        webhook_secret = _secret_from_environment(parser)
        store = QueueStore.open(loaded.database, busy_timeout_ms=loaded.busy_timeout_ms)
        store.register_repositories(item.identity for item in loaded.repositories)
        uvicorn.run(create_app(config=loaded, store=store, webhook_secret=webhook_secret), host="127.0.0.1", port=8080)
        return 0
    if args.command == "doctor":
        return operations.doctor(loaded.database, busy_timeout_ms=loaded.busy_timeout_ms)
    if args.command == "queue-status":
        return operations.queue_status(loaded.database, busy_timeout_ms=loaded.busy_timeout_ms, as_json=args.json, now=datetime.now(UTC))
    now = datetime.now(UTC)
    return operations.prune(loaded.database, busy_timeout_ms=loaded.busy_timeout_ms, deliveries_before=now - timedelta(days=args.deliveries_days or loaded.delivery_retention.days), invalidations_before=now - timedelta(days=args.invalidations_days or loaded.invalidation_retention.days))
