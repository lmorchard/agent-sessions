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
    PollingPolicy,
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
        polling=PollingPolicy(timedelta(seconds=60), timedelta(seconds=60)),
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
async def test_delivery_outcomes_emit_safe_structured_json_records(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from agent_sessions.events.webhook import create_app

    store = store_for(tmp_path)
    app = create_app(
        config=config(tmp_path / "events.sqlite3"),
        store=store,
        webhook_secret=SECRET,
    )
    accepted_body = body()
    malformed_body = body(issue={"number": "wrong"})

    assert (await request(app, accepted_body)).status_code == 202
    assert (
        await request(
            app,
            malformed_body,
            **{"X-GitHub-Delivery": "delivery-bad"},
        )
    ).status_code == 400

    captured = capsys.readouterr().err
    records = [json.loads(line) for line in captured.splitlines()]
    assert len(records) == 2
    assert records[0] == {
        "action": "opened",
        "delivery_guid": "delivery-1",
        "disposition": "accepted",
        "elapsed_ms": records[0]["elapsed_ms"],
        "event": "webhook_delivery",
        "event_type": "issues",
        "http_status": 202,
        "invalidation_count": 1,
        "repository_id": 1,
    }
    assert isinstance(records[0]["elapsed_ms"], int)
    assert records[1] == {
        "action": "opened",
        "delivery_guid": "delivery-bad",
        "disposition": "malformed",
        "elapsed_ms": records[1]["elapsed_ms"],
        "event": "webhook_delivery",
        "event_type": "issues",
        "http_status": 400,
        "invalidation_count": 0,
        "repository_id": 1,
    }
    assert accepted_body.decode() not in captured
    assert malformed_body.decode() not in captured
    assert SECRET.decode() not in captured
    assert headers(accepted_body)["X-Hub-Signature-256"] not in captured


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
async def test_uppercase_signature_digest_is_verified(tmp_path: Path) -> None:
    from agent_sessions.events.webhook import create_app

    store = store_for(tmp_path)
    raw = body()
    signature = headers(raw)["X-Hub-Signature-256"]

    response = await request(
        create_app(
            config=config(tmp_path / "events.sqlite3"),
            store=store,
            webhook_secret=SECRET,
        ),
        raw,
        **{"X-Hub-Signature-256": "sha256=" + signature[7:].upper()},
    )

    assert response.status_code == 202
    assert store.connection.execute(
        "SELECT count(*) FROM webhook_deliveries"
    ).fetchone()[0] == 1


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
async def test_readiness_includes_the_optional_background_runtime(tmp_path: Path) -> None:
    from contextlib import asynccontextmanager

    import httpx

    from agent_sessions.events.webhook import create_app

    class UnreadyRuntime:
        @asynccontextmanager
        async def lifespan(self, _app):
            yield

        def ready(self) -> bool:
            return False

    app = create_app(
        config=config(tmp_path / "events.sqlite3"),
        store=store_for(tmp_path),
        webhook_secret=SECRET,
        runtime=UnreadyRuntime(),
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/readyz")).status_code == 503


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
    from contextlib import asynccontextmanager

    import uvicorn

    from agent_sessions.events import cli
    from agent_sessions.events.pollers import PollRunResult

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
[polling]
projects_interval_seconds = 60
reactions_interval_seconds = 60
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
    resolved: list[str] = []
    received_tokens: list[tuple[str, str]] = []
    received_bot_logins: list[frozenset[str]] = []

    class CapturedRuntime:
        instance: "CapturedRuntime | None" = None

        def __init__(self, _store_factory, polls, _result_logger) -> None:
            self.polls = polls
            CapturedRuntime.instance = self

        @asynccontextmanager
        async def lifespan(self, _app):
            yield

        def ready(self) -> bool:
            return True

    def resolve_read_credential() -> str:
        resolved.append("read-token")
        return "read-token"

    resolved_logins: list[str] = []

    def resolve_read_login(token: str) -> str:
        resolved_logins.append(token)
        return "agent-reader"

    def projects(
        _config, _store, token, *, worker_id, now, stop_requested
    ) -> PollRunResult:
        assert stop_requested() is False
        received_tokens.append(("projects", token))
        return PollRunResult()

    def reactions(
        _config, _store, token, bot_logins, *, worker_id, now, stop_requested
    ) -> PollRunResult:
        assert stop_requested() is False
        received_tokens.append(("reactions", token))
        received_bot_logins.append(bot_logins)
        return PollRunResult()

    def forbidden(*_args, **_kwargs):
        pytest.fail("serve inspected a board, write, or App credential resolver")

    monkeypatch.setattr(cli, "DaemonRuntime", CapturedRuntime)
    monkeypatch.setattr(cli.credentials, "resolve_read_credential", resolve_read_credential)
    monkeypatch.setattr(cli.credentials, "resolve_read_login", resolve_read_login)
    monkeypatch.setattr(cli.credentials, "resolve_board_credential", forbidden)
    monkeypatch.setattr(cli.credentials, "resolve", forbidden)
    monkeypatch.setattr(cli.credentials, "generate_app_jwt", forbidden)
    monkeypatch.setattr(cli.credentials, "fetch_app_installation_token", forbidden)
    monkeypatch.setattr(cli.pollers, "poll_projects_once", projects)
    monkeypatch.setattr(cli.pollers, "poll_reactions_once", reactions)
    secret.chmod(0o644)
    with pytest.raises(SystemExit) as rejected:
        cli.main(["serve", "--config", str(settings)])
    assert rejected.value.code == 2
    secret.chmod(0o600)
    assert cli.main(["migrate", "--config", str(settings)]) == 0
    assert cli.main(["serve", "--config", str(settings)]) == 0
    assert seen["host"] == "127.0.0.1" and seen["port"] == 8080
    assert seen["workers"] == 1
    assert resolved == ["read-token"]
    assert CapturedRuntime.instance is not None
    for _pass in range(2):
        for poll in CapturedRuntime.instance.polls:
            poll.run(object(), NOW, lambda: False)
    assert received_tokens == [
        ("projects", "read-token"),
        ("reactions", "read-token"),
        ("projects", "read-token"),
        ("reactions", "read-token"),
    ]
    assert received_bot_logins == [
        cli.credentials.bot_logins(cli.credentials.Credentials(login="agent-reader")),
        cli.credentials.bot_logins(cli.credentials.Credentials(login="agent-reader")),
    ]
    assert resolved_logins == ["read-token"]
