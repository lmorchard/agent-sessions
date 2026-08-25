"""Initial command line interface for queue maintenance."""

from __future__ import annotations

import argparse
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Sequence

from . import config, operations


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-session-events")
    parser.add_argument("--config", type=Path, default=os.environ.get("AGENT_SESSION_EVENTS_CONFIG"))
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("migrate")
    status = subparsers.add_parser("queue-status")
    status.add_argument("--json", action="store_true")
    subparsers.add_parser("doctor")
    prune = subparsers.add_parser("prune")
    prune.add_argument("--deliveries-days", type=int)
    prune.add_argument("--invalidations-days", type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.config is None:
        parser.error("--config or AGENT_SESSION_EVENTS_CONFIG is required")
    loaded = config.load(args.config)
    if args.command == "migrate":
        return operations.migrate(loaded.database, busy_timeout_ms=loaded.busy_timeout_ms)
    if args.command == "doctor":
        return operations.doctor(loaded.database, busy_timeout_ms=loaded.busy_timeout_ms)
    if args.command == "queue-status":
        return operations.queue_status(loaded.database, busy_timeout_ms=loaded.busy_timeout_ms, as_json=args.json, now=datetime.now(UTC))
    now = datetime.now(UTC)
    return operations.prune(loaded.database, busy_timeout_ms=loaded.busy_timeout_ms, deliveries_before=now - timedelta(days=args.deliveries_days or loaded.delivery_retention.days), invalidations_before=now - timedelta(days=args.invalidations_days or loaded.invalidation_retention.days))
