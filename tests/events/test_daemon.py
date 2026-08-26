from __future__ import annotations

import asyncio
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from agent_sessions.events.pollers import PollRunResult
from agent_sessions.events.store import QueueStore


async def _wait_for(predicate, *, timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("condition did not become true")
        await asyncio.sleep(0.005)


def _store_factory(path: Path, stores: list[QueueStore]):
    def factory() -> QueueStore:
        store = QueueStore.open(path, busy_timeout_ms=100)
        stores.append(store)
        return store

    return factory


@pytest.mark.anyio
async def test_runtime_runs_each_poll_immediately_then_at_its_own_fixed_delay_with_a_new_closed_store(
    tmp_path: Path,
) -> None:
    from agent_sessions.events.daemon import DaemonRuntime, ScheduledPoll

    database = tmp_path / "events.sqlite3"
    QueueStore.migrate(database, busy_timeout_ms=100)
    stores: list[QueueStore] = []
    projects_started: list[float] = []
    reactions_started: list[float] = []
    first_started = threading.Event()
    first_released = threading.Event()
    first_completed = threading.Event()
    completed_at: list[float] = []
    active = maximum_active = 0
    lock = threading.Lock()

    def projects(
        store: QueueStore, _now: datetime, _stop_requested
    ) -> PollRunResult:
        nonlocal active, maximum_active
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
            projects_started.append(time.monotonic())
            first_pass = len(projects_started) == 1
        try:
            if first_pass:
                first_started.set()
                assert first_released.wait(timeout=1)
            return PollRunResult(attempted=1)
        finally:
            with lock:
                active -= 1
                if first_pass:
                    completed_at.append(time.monotonic())
                    first_completed.set()

    def reactions(
        _store: QueueStore, _now: datetime, _stop_requested
    ) -> PollRunResult:
        reactions_started.append(time.monotonic())
        return PollRunResult(attempted=1)

    runtime = DaemonRuntime(
        _store_factory(database, stores),
        (
            ScheduledPoll("projects", timedelta(milliseconds=40), projects),
            ScheduledPoll("reactions", timedelta(milliseconds=70), reactions),
        ),
        lambda _name, _result: None,
    )
    async with runtime.lifespan(None):
        await asyncio.to_thread(first_started.wait, 1)
        await _wait_for(lambda: reactions_started)
        await asyncio.sleep(0.1)
        assert len(projects_started) == 1
        first_released.set()
        await asyncio.to_thread(first_completed.wait, 1)
        await _wait_for(lambda: len(projects_started) >= 2)
        assert runtime.ready()

    assert projects_started[1] - completed_at[0] >= 0.035
    assert maximum_active == 1
    assert len({id(store.connection) for store in stores}) == len(stores)
    for store in stores:
        with pytest.raises(sqlite3.ProgrammingError):
            store.connection.execute("SELECT 1")


@pytest.mark.anyio
async def test_runtime_logs_result_failures_but_a_raised_pass_exception_makes_it_unready(
    tmp_path: Path,
) -> None:
    from agent_sessions.events.daemon import DaemonRuntime, ScheduledPoll

    database = tmp_path / "events.sqlite3"
    QueueStore.migrate(database, busy_timeout_ms=100)
    stores: list[QueueStore] = []
    logged: list[tuple[str, PollRunResult]] = []
    calls = 0

    def transient(
        _store: QueueStore, _now: datetime, _stop_requested
    ) -> PollRunResult:
        nonlocal calls
        calls += 1
        return PollRunResult(errors=("temporary source failure",))

    def broken(_store: QueueStore, _now: datetime, _stop_requested) -> PollRunResult:
        raise RuntimeError("unexpected poll crash")

    runtime = DaemonRuntime(
        _store_factory(database, stores),
        (
            ScheduledPoll("transient", timedelta(milliseconds=20), transient),
            ScheduledPoll("broken", timedelta(seconds=1), broken),
        ),
        lambda name, result: logged.append((name, result)),
    )
    async with runtime.lifespan(None):
        await _wait_for(lambda: calls >= 2 and not runtime.ready())

    assert len(logged) >= 2
    assert all(name == "transient" and result.errors for name, result in logged)


@pytest.mark.anyio
async def test_runtime_shutdown_waits_for_an_inflight_bounded_pass(tmp_path: Path) -> None:
    from agent_sessions.events.daemon import DaemonRuntime, ScheduledPoll

    database = tmp_path / "events.sqlite3"
    QueueStore.migrate(database, busy_timeout_ms=100)
    stores: list[QueueStore] = []
    entered = threading.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()

    def in_flight(
        _store: QueueStore, _now: datetime, _stop_requested
    ) -> PollRunResult:
        entered.set()
        while not release.is_set():
            time.sleep(0.005)
        return PollRunResult(attempted=1)

    runtime = DaemonRuntime(
        _store_factory(database, stores),
        (ScheduledPoll("reactions", timedelta(seconds=1), in_flight),),
        lambda _name, _result: None,
    )
    lifespan = runtime.lifespan(None)
    await lifespan.__aenter__()
    try:
        await asyncio.to_thread(entered.wait, 1)
        exit_task = asyncio.create_task(lifespan.__aexit__(None, None, None))
        await asyncio.sleep(0.05)
        assert not exit_task.done()
        loop.call_soon_threadsafe(release.set)
        await exit_task
    finally:
        if not release.is_set():
            release.set()
            await lifespan.__aexit__(None, None, None)

    assert len(stores) == 1


@pytest.mark.anyio
async def test_runtime_shutdown_stops_an_inflight_pass_before_its_next_call(
    tmp_path: Path,
) -> None:
    from agent_sessions.events.daemon import DaemonRuntime, ScheduledPoll

    database = tmp_path / "events.sqlite3"
    QueueStore.migrate(database, busy_timeout_ms=100)
    stores: list[QueueStore] = []
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()

    def two_calls(
        _store: QueueStore,
        _now: datetime,
        stop_requested,
    ) -> PollRunResult:
        first_entered.set()
        assert release_first.wait(timeout=1)
        if not stop_requested():
            second_entered.set()
        return PollRunResult(attempted=1)

    runtime = DaemonRuntime(
        _store_factory(database, stores),
        (ScheduledPoll("projects", timedelta(seconds=1), two_calls),),
        lambda _name, _result: None,
    )
    lifespan = runtime.lifespan(None)
    await lifespan.__aenter__()
    exit_task: asyncio.Task[object] | None = None
    try:
        assert await asyncio.to_thread(first_entered.wait, 1)
        exit_task = asyncio.create_task(lifespan.__aexit__(None, None, None))
        await asyncio.sleep(0.05)
        release_first.set()
        await exit_task
        assert not second_entered.is_set()
    finally:
        release_first.set()
        if exit_task is None:
            await lifespan.__aexit__(None, None, None)


def test_scheduled_polls_omit_projects_without_boards_but_keep_reactions() -> None:
    from agent_sessions.events import cli
    from agent_sessions.events.models import EventsConfig, PollingPolicy, ScanPolicy

    loaded = EventsConfig(
        database=Path("/tmp/events.sqlite3"),
        busy_timeout_ms=100,
        claim_limit=1,
        claim_lease=timedelta(seconds=1),
        retry_base=timedelta(seconds=1),
        retry_maximum=timedelta(seconds=1),
        max_body_bytes=1024,
        delivery_retention=timedelta(days=1),
        invalidation_retention=timedelta(days=1),
        scan=ScanPolicy(timedelta(seconds=1), timedelta(seconds=1), timedelta(seconds=1)),
        polling=PollingPolicy(timedelta(seconds=60), timedelta(seconds=60)),
        repositories=(),
        boards=(),
    )

    assert [
        poll.name
        for poll in cli._scheduled_polls(
            loaded, "read-token", frozenset({"agent-reader"})
        )
    ] == [
        "poll-reactions"
    ]
