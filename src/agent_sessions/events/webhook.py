"""Credential-free ASGI ingress for verified GitHub webhook deliveries."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, Protocol

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .models import (
    EnqueueResult,
    EventsConfig,
    Invalidation,
    QueueBusy,
    QueueUnavailable,
    StoreHealth,
    VerifiedDelivery,
)
from .normalize import normalize_delivery

logger = logging.getLogger(__name__)
_HEX = frozenset("0123456789abcdefABCDEF")


class WebhookStore(Protocol):
    def ready(self) -> StoreHealth: ...

    def enqueue_webhook(self, delivery: VerifiedDelivery, invalidations: Iterable[Invalidation], *, now: datetime) -> EnqueueResult: ...


def _signature_is_valid(value: str) -> bool:
    return value.startswith("sha256=") and len(value) == 71 and all(character in _HEX for character in value[7:])


def _log(delivery: VerifiedDelivery | None, *, status: int, invalidation_count: int, started_at: float) -> None:
    """Emit only receiver-safe diagnostic fields."""
    logger.info(
        "webhook_delivery",
        extra={
            "delivery_guid": None if delivery is None else delivery.guid,
            "event": None if delivery is None else delivery.event_type,
            "action": None if delivery is None else delivery.action,
            "repository_id": None if delivery is None else delivery.repository_id,
            "disposition": None if delivery is None else delivery.disposition,
            "invalidation_count": invalidation_count,
            "http_status": status,
            "elapsed_ms": int((time.monotonic() - started_at) * 1000),
        },
    )


def create_app(*, config: EventsConfig, store: WebhookStore, webhook_secret: bytes) -> FastAPI:
    """Create the receiver without opening sockets or resolving GitHub credentials."""
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    write_lock = asyncio.Lock()

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/readyz")
    async def readyz() -> JSONResponse:
        try:
            health = await asyncio.to_thread(store.ready)
        except (QueueBusy, QueueUnavailable):
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return JSONResponse({"status": "ready"} if health.ready else {"status": "unavailable"}, status_code=200 if health.ready else 503)

    @app.post("/github/webhook")
    async def github_webhook(request: Request) -> JSONResponse:
        started_at = time.monotonic()
        guid = request.headers.get("x-github-delivery")
        event_type = request.headers.get("x-github-event")
        signature = request.headers.get("x-hub-signature-256")
        if not guid or not event_type or not signature:
            _log(None, status=400, invalidation_count=0, started_at=started_at)
            return JSONResponse({"detail": "required GitHub webhook headers are missing"}, status_code=400)

        chunks: list[bytes] = []
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > config.max_body_bytes:
                _log(None, status=413, invalidation_count=0, started_at=started_at)
                return JSONResponse({"detail": "request body is too large"}, status_code=413)
            chunks.append(chunk)
        raw_body = b"".join(chunks)
        if not _signature_is_valid(signature):
            _log(None, status=400, invalidation_count=0, started_at=started_at)
            return JSONResponse({"detail": "webhook signature has invalid syntax"}, status_code=400)
        expected = "sha256=" + hmac.new(webhook_secret, raw_body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            _log(None, status=401, invalidation_count=0, started_at=started_at)
            return JSONResponse({"detail": "invalid webhook signature"}, status_code=401)
        try:
            payload: Any = json.loads(raw_body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            _log(None, status=400, invalidation_count=0, started_at=started_at)
            return JSONResponse({"detail": "request body is not valid JSON"}, status_code=400)
        if not isinstance(payload, dict):
            _log(None, status=400, invalidation_count=0, started_at=started_at)
            return JSONResponse({"detail": "request JSON must be an object"}, status_code=400)
        normalized = normalize_delivery(event_type, payload, config)
        delivery = VerifiedDelivery(guid, event_type, normalized.action, normalized.repository_id, raw_body, normalized.disposition, normalized.diagnostic)
        if normalized.disposition == "malformed":
            _log(delivery, status=400, invalidation_count=0, started_at=started_at)
            return JSONResponse({"detail": "webhook payload has malformed identity"}, status_code=400)
        try:
            async with write_lock:
                result = await asyncio.to_thread(store.enqueue_webhook, delivery, normalized.invalidations, now=datetime.now(UTC))
        except (QueueBusy, QueueUnavailable):
            _log(delivery, status=503, invalidation_count=0, started_at=started_at)
            return JSONResponse({"detail": "webhook queue is unavailable"}, status_code=503)
        _log(delivery, status=202, invalidation_count=result.invalidation_count, started_at=started_at)
        return JSONResponse({"status": "accepted", "duplicate": result.duplicate}, status_code=202)

    return app
