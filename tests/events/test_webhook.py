from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import sqlite3
import threading
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from agent_sessions.events.models import (
    EnqueueResult,
    EventsConfig,
    Invalidation,
    QueueBusy,
    QueueUnavailable,
    RepositoryConfig,
    RepositoryIdentity,
    ScanPolicy,
    StoreHealth,
    VerifiedDelivery,
)
from agent_sessions.events.store import QueueStore

SECRET = b"test secret"
NOW = datetime(2026, 8, 25, tzinfo=UTC)


def config(database: Path, *, max_body_bytes: int = 1024) -> EventsConfig:
    return EventsConfig(
        database=database,
        busy_timeout_ms=100,
        claim_limit=1,
        claim_lease=timedelta(seconds=1),
        retry_base=timedelta(seconds=1),
        retry_maximum=timedelta(seconds=1),
        max_body_bytes=max_body_bytes,
        delivery_retention=timedelta(days=1),
        invalidation_retention=timedelta(days=1),
        scan=ScanPolicy(timedelta(seconds=1), timedelta(seconds=1), timedelta(seconds=1)),
        repositories=(RepositoryConfig(RepositoryIdentity(1, "owner", "repo", installation_id=10)),),
        boards=(),
    )


def store_for(tmp_path: Path) -> QueueStore:
    database = tmp_path / "events.sqlite3"
    QueueStore.migrate(database, busy_timeout_ms=100)
    store = QueueStore.open(database, busy_timeout_ms=100)
    store.register_repositories((RepositoryIdentity(1, "owner", "repo", installation_id=10),))
    return store


def body(**extra: Any) -> bytes:
    payload = {"action": "opened", "repository": {"id": 1}, "issue": {"number": 42}}
    payload.update(extra)
    return json.dumps(payload, separators=(",", ":")).encode()


def headers(raw: bytes, **extra: str) -> dict[str, str]:
    values = {
        "X-GitHub-Delivery": "delivery-1",
        "X-GitHub-Event": "issues",
        "X-Hub-Signature-256": "sha256=" + hmac.new(SECRET, raw, hashlib.sha256).hexdigest(),
    }
    values.update(extra)
    return values


async def request(app: Any, raw: bytes, **header_values: str):
    import httpx

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        return await client.post("/github/webhook", content=raw, headers=headers(raw, **header_values))


@pytest.mark.anyio
async def test_signed_exact_bytes_are_retained_after_normalization(tmp_path: Path) -> None:
    from agent_sessions.events.webhook import create_app

    store = store_for(tmp_path)
    raw = b'{"repository":{"id":1},"action":"opened","issue":{"number":42}}\n'
    response = await request(create_app(config=config(tmp_path / "events.sqlite3"), store=store, webhook_secret=SECRET), raw)

    assert response.status_code == 202
    assert store.connection.execute("SELECT raw_body, disposition FROM webhook_deliveries").fetchone()[:] == (raw, "accepted")


@pytest.mark.anyio
async def test_headers_signatures_and_malformed_supported_payloads_are_rejected_without_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from agent_sessions.events import webhook

    store = store_for(tmp_path)
    app = webhook.create_app(config=config(tmp_path / "events.sqlite3"), store=store, webhook_secret=SECRET)
    raw = body()
    import httpx

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post("/github/webhook", content=raw)).status_code == 400
        parsed = False

        def no_parse(_: str):
            nonlocal parsed
            parsed = True
            raise AssertionError("bad signatures must not parse JSON")

        monkeypatch.setattr(webhook.json, "loads", no_parse)
        assert (await client.post("/github/webhook", content=raw, headers=headers(raw, **{"X-Hub-Signature-256": "sha256=" + "0" * 64}))).status_code == 401
        assert not parsed
        monkeypatch.undo()
        malformed_json = b"{"
        assert (await client.post("/github/webhook", content=malformed_json, headers=headers(malformed_json, **{"X-GitHub-Delivery": "bad-json"}))).status_code == 400
        malformed_identity = body(issue={"number": "wrong"})
        assert (await client.post("/github/webhook", content=malformed_identity, headers=headers(malformed_identity, **{"X-GitHub-Delivery": "bad-identity"}))).status_code == 400
    assert store.connection.execute("SELECT count(*) FROM webhook_deliveries").fetchone()[0] == 0


@pytest.mark.anyio
@pytest.mark.parametrize("signature", ["sha1=" + "0" * 64, "sha256=" + "0" * 63, "sha256=" + "g" * 64])
async def test_malformed_signature_syntax_returns_bad_request_without_parsing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, signature: str,
) -> None:
    from agent_sessions.events import webhook

    store = store_for(tmp_path)
    app = webhook.create_app(config=config(tmp_path / "events.sqlite3"), store=store, webhook_secret=SECRET)
    monkeypatch.setattr(webhook.json, "loads", lambda _: pytest.fail("malformed signatures must not parse JSON"))

    response = await request(app, body(), **{"X-Hub-Signature-256": signature})

    assert response.status_code == 400
    assert store.connection.execute("SELECT count(*) FROM webhook_deliveries").fetchone()[0] == 0


@pytest.mark.anyio
async def test_malformed_action_returns_bad_request_without_persistence(tmp_path: Path) -> None:
    from agent_sessions.events.webhook import create_app

    store = store_for(tmp_path)
    raw = body(action=None)
    response = await request(create_app(config=config(tmp_path / "events.sqlite3"), store=store, webhook_secret=SECRET), raw)

    assert response.status_code == 400
    assert store.connection.execute("SELECT count(*) FROM webhook_deliveries").fetchone()[0] == 0


@pytest.mark.anyio
async def test_body_limit_is_enforced_while_streaming(tmp_path: Path) -> None:
    import httpx

    from agent_sessions.events.webhook import create_app

    raw = body()
    app = create_app(config=config(tmp_path / "events.sqlite3", max_body_bytes=len(raw) - 1), store=store_for(tmp_path), webhook_secret=SECRET)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/github/webhook", content=raw, headers=headers(raw))
    assert response.status_code == 413


@pytest.mark.anyio
async def test_duplicate_delivery_returns_accepted_without_incrementing_generation(tmp_path: Path) -> None:
    from agent_sessions.events.webhook import create_app

    store = store_for(tmp_path)
    app = create_app(config=config(tmp_path / "events.sqlite3"), store=store, webhook_secret=SECRET)
    raw = body()
    assert (await request(app, raw)).status_code == 202
    assert (await request(app, raw)).status_code == 202
    assert store.connection.execute("SELECT generation FROM dirty_targets").fetchone()[0] == 1


@pytest.mark.anyio
async def test_health_ready_and_documentation_routes_have_fixed_surface(tmp_path: Path) -> None:
    import httpx

    from agent_sessions.events.webhook import create_app

    store = store_for(tmp_path)
    app = create_app(config=config(tmp_path / "events.sqlite3"), store=store, webhook_secret=SECRET)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/healthz")).json() == {"status": "alive"}
        assert (await client.get("/readyz")).status_code == 200
        for path in ("/openapi.json", "/docs", "/redoc"):
            assert (await client.get(path)).status_code == 404


@pytest.mark.anyio
async def test_store_failures_return_service_unavailable(tmp_path: Path) -> None:
    from agent_sessions.events.webhook import create_app

    class FailingStore:
        def ready(self) -> StoreHealth:
            raise QueueUnavailable("unavailable")

        def enqueue_webhook(self, _: VerifiedDelivery, __: Iterable[Invalidation], *, now: datetime) -> EnqueueResult:
            raise QueueBusy("busy")

    app = create_app(config=config(tmp_path / "events.sqlite3"), store=FailingStore(), webhook_secret=SECRET)
    assert (await request(app, body())).status_code == 503
    import httpx

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/readyz")).status_code == 503


@pytest.mark.anyio
async def test_locked_real_queue_returns_service_unavailable(tmp_path: Path) -> None:
    from agent_sessions.events.webhook import create_app

    store = store_for(tmp_path)
    locker = sqlite3.connect(tmp_path / "events.sqlite3", isolation_level=None)
    locker.execute("BEGIN IMMEDIATE")
    try:
        response = await request(create_app(config=config(tmp_path / "events.sqlite3"), store=store, webhook_secret=SECRET), body())
    finally:
        locker.rollback()
        locker.close()

    assert response.status_code == 503


@pytest.mark.anyio
async def test_response_waits_until_enqueue_commit_returns(tmp_path: Path) -> None:
    from agent_sessions.events.webhook import create_app

    real = store_for(tmp_path)
    entered = threading.Event()
    release = threading.Event()

    class BlockingStore:
        def ready(self):
            return real.ready()

        def enqueue_webhook(self, delivery, invalidations, *, now) -> EnqueueResult:
            entered.set()
            assert release.wait(timeout=2)
            return real.enqueue_webhook(delivery, invalidations, now=now)

    app = create_app(config=config(tmp_path / "events.sqlite3"), store=BlockingStore(), webhook_secret=SECRET)
    pending = asyncio.create_task(request(app, body()))
    assert await asyncio.to_thread(entered.wait, 1)
    assert not pending.done()
    release.set()
    assert (await pending).status_code == 202


@pytest.mark.anyio
async def test_signed_asgi_delivery_can_be_claimed_from_second_connection(tmp_path: Path) -> None:
    from agent_sessions.events.webhook import create_app

    store = store_for(tmp_path)
    database = tmp_path / "events.sqlite3"
    app = create_app(config=config(database), store=store, webhook_secret=SECRET)
    assert (await request(app, body())).status_code == 202
    other = QueueStore.open(database, busy_timeout_ms=100)
    claim = other.claim_targets(1, worker_id="worker", limit=1, lease_until=NOW + timedelta(minutes=1), now=NOW)
    assert [(item.target_kind, item.target_key) for item in claim] == [("issue", "42")]


def test_serve_uses_a_private_secret_file_and_accepts_config_after_subcommand(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import uvicorn

    from agent_sessions.events.cli import main

    database = tmp_path / "events.sqlite3"
    settings = tmp_path / "events.toml"
    settings.write_text(
        f'''database = "{database}"
busy_timeout_ms = 100
claim_limit = 1
claim_lease_seconds = 1
retry_base_seconds = 1
retry_max_seconds = 1
max_body_bytes = 1024
delivery_retention_days = 1
invalidation_retention_days = 1
[scan]
quiet_period_seconds = 1
interval_seconds = 1
maximum_age_seconds = 1
[[repositories]]
id = 1
owner = "owner"
name = "repo"
[[boards]]
owner = "owner"
number = 1
repository_ids = [1]
''',
        encoding="utf-8",
    )
    secret = tmp_path / "webhook.secret"
    secret.write_bytes(b"secret\n")
    monkeypatch.setenv("AGENT_SESSION_WEBHOOK_SECRET_FILE", str(secret))
    seen: dict[str, Any] = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: seen.update(app=app, **kwargs))
    secret.chmod(0o644)
    with pytest.raises(SystemExit) as rejected:
        main(["serve", "--config", str(settings)])
    assert rejected.value.code == 2
    secret.chmod(0o600)
    assert main(["migrate", "--config", str(settings)]) == 0
    assert main(["serve", "--config", str(settings)]) == 0
    assert seen["host"] == "127.0.0.1" and seen["port"] == 8080
