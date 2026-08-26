"""In-process fixed-delay scheduling for the read-only event pollers."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .pollers import PollRunResult
from .store import QueueStore

PollPass = Callable[[QueueStore, datetime], PollRunResult]


@dataclass(frozen=True)
class ScheduledPoll:
    name: str
    interval: timedelta
    run: PollPass


class DaemonRuntime:
    """Run independent polling sources without coupling them to webhook ingress."""

    def __init__(
        self,
        store_factory: Callable[[], QueueStore],
        polls: tuple[ScheduledPoll, ...],
        result_logger: Callable[[str, PollRunResult], None],
    ) -> None:
        self._store_factory = store_factory
        self._polls = polls
        self._result_logger = result_logger
        self._stopping = asyncio.Event()
        self._tasks: tuple[asyncio.Task[None], ...] = ()

    async def _run(self, poll: ScheduledPoll) -> None:
        while not self._stopping.is_set():
            store = self._store_factory()
            try:
                result = await asyncio.to_thread(poll.run, store, datetime.now(UTC))
                self._result_logger(poll.name, result)
            finally:
                store.close()
            try:
                await asyncio.wait_for(
                    self._stopping.wait(), poll.interval.total_seconds()
                )
            except TimeoutError:
                pass

    @asynccontextmanager
    async def lifespan(self, _app: Any) -> AsyncIterator[None]:
        self._stopping.clear()
        self._tasks = tuple(
            asyncio.create_task(self._run(poll), name=f"event-poll:{poll.name}")
            for poll in self._polls
        )
        try:
            yield
        finally:
            self._stopping.set()
            if self._tasks:
                await asyncio.gather(*self._tasks, return_exceptions=True)

    def ready(self) -> bool:
        return not self._stopping.is_set() and all(not task.done() for task in self._tasks)
