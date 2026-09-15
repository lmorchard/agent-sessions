from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from agent_sessions.events.github import (
    ApprovalPredicateObservation,
    GitHubTransientError,
    LiveTargetResolver,
    fetch_approval_predicates,
)
from agent_sessions.events.models import (
    ApprovalWatch,
    EventsConfig,
    PollingPolicy,
    RepositoryConfig,
    RepositoryIdentity,
    ScanPolicy,
)
from agent_sessions.events.pollers import PollRunResult, poll_reactions_once
from agent_sessions.events.store import QueueStore

NOW = datetime(2026, 8, 25, 12, tzinfo=UTC)
PARKED = NOW - timedelta(hours=1)
BOTS = frozenset({"agent-bot", "dependabot[bot]"})
REPOSITORY = RepositoryConfig(RepositoryIdentity(1, "owner", "repo", 99))


def fixed_clock(value: datetime) -> Callable[[], datetime]:
    return lambda: value


def test_github_reads_have_a_bounded_timeout_and_translate_expiry() -> None:
    calls: list[dict[str, object]] = []

    def timed_out(_command, **kwargs):
        calls.append(kwargs)
        raise subprocess.TimeoutExpired("gh api", 60)

    resolver = LiveTargetResolver(read_token="read-token", runner=timed_out)

    with pytest.raises(GitHubTransientError, match="timed out"):
        resolver._read(["gh", "api", "repos/owner/repo"])
    assert len(calls) == 1
    assert calls[0]["timeout"] == 60


def test_github_reads_check_for_shutdown_before_each_subprocess() -> None:
    stopping = False
    calls = 0

    def runner(_command, **_kwargs):
        nonlocal calls, stopping
        calls += 1
        stopping = True
        return Result(stdout="{}")

    resolver = LiveTargetResolver(
        read_token="read-token",
        runner=runner,
        stop_requested=lambda: stopping,
    )

    assert resolver._read(["gh", "api", "user"]) == {}
    with pytest.raises(GitHubTransientError, match="stopped"):
        resolver._read(["gh", "api", "rate_limit"])
    assert calls == 1


class Result:
    def __init__(self, *, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class SequenceRunner:
    def __init__(self, results: list[Result]) -> None:
        self.results = iter(results)
        self.calls: list[tuple[list[str], dict[str, object]]] = []

    def __call__(self, command, **kwargs):
        self.calls.append((list(command), kwargs))
        return next(self.results)


def config(path: Path) -> EventsConfig:
    return EventsConfig(
        database=path,
        busy_timeout_ms=250,
        claim_limit=10,
        claim_lease=timedelta(minutes=5),
        retry_base=timedelta(seconds=30),
        retry_maximum=timedelta(minutes=30),
        max_body_bytes=1024,
        delivery_retention=timedelta(days=14),
        invalidation_retention=timedelta(days=30),
        scan=ScanPolicy(timedelta(minutes=5), timedelta(minutes=15), timedelta(hours=1)),
        polling=PollingPolicy(timedelta(seconds=60), timedelta(seconds=60)),
        repositories=(REPOSITORY,),
        boards=(),
    )


def migrated(tmp_path: Path) -> QueueStore:
    path = tmp_path / "events.sqlite3"
    QueueStore.migrate(path, busy_timeout_ms=250)
    store = QueueStore.open(path, busy_timeout_ms=250)
    store.register_repositories((REPOSITORY.identity,))
    return store


def watch(
    issue_number: int = 42,
    *,
    last_value: bool | None = None,
    last_checked_at: datetime | None = None,
) -> ApprovalWatch:
    return ApprovalWatch(
        1,
        issue_number,
        "human_approval_since_park",
        PARKED,
        last_value,
        last_checked_at,
    )


def reaction(
    login: str | None,
    created_at: datetime,
    *,
    content: str = "THUMBS_UP",
) -> dict[str, object]:
    return {
        "content": content,
        "user": None if login is None else {"login": login},
        "createdAt": created_at.isoformat().replace("+00:00", "Z"),
    }


def comment(
    comment_id: str,
    login: str | None,
    created_at: datetime,
    *,
    reactions: tuple[dict[str, object], ...] = (),
) -> dict[str, object]:
    return {
        "id": comment_id,
        "author": None if login is None else {"login": login},
        "createdAt": created_at.isoformat().replace("+00:00", "Z"),
        "reactions": {
            "nodes": list(reactions),
            "pageInfo": {"hasNextPage": False, "endCursor": None},
        },
    }


def comments_page(
    nodes: list[dict[str, object]],
    *,
    has_next: bool = False,
    end_cursor: str | None = None,
    include_page_info: bool = True,
) -> dict[str, object]:
    comments: dict[str, object] = {"nodes": nodes}
    if include_page_info:
        comments["pageInfo"] = {
            "hasNextPage": has_next,
            "endCursor": end_cursor,
        }
    return {
        "data": {"repository": {"issue": {"comments": comments}}}
    }


def test_fetch_approval_predicates_groups_watches_and_reads_every_comment_page() -> None:
    first_page = comments_page(
        [comment("c1", "agent-bot", NOW)],
        has_next=True,
        end_cursor="comments-1",
    )
    second_page = comments_page(
        [comment("c2", "les", NOW + timedelta(seconds=1))]
    )
    runner = SequenceRunner(
        [
            Result(stdout=json.dumps(first_page)),
            Result(stdout=json.dumps(second_page)),
            Result(stdout=json.dumps(comments_page([]))),
        ]
    )

    observations = fetch_approval_predicates(
        REPOSITORY,
        (watch(42), watch(43)),
        "read-token",
        BOTS,
        runner=runner,
    )

    assert [(item.watch.issue_number, item.value) for item in observations] == [
        (42, True),
        (43, False),
    ]
    commands = [command for command, _kwargs in runner.calls]
    assert len(commands) == 3
    assert all(command[:3] == ["gh", "api", "graphql"] for command in commands)
    assert all("--paginate" not in command for command in commands)
    assert all("--slurp" not in command for command in commands)
    assert "endCursor=comments-1" in commands[1]
    assert [next(part for part in command if part.startswith("issue=")) for command in commands] == [
        "issue=42",
        "issue=42",
        "issue=43",
    ]
    assert all(kwargs["env"]["GH_TOKEN"] == "read-token" for _command, kwargs in runner.calls)  # type: ignore[index]


def test_approval_predicate_requires_non_bot_activity_strictly_after_park() -> None:
    runner = SequenceRunner(
        [
            Result(
                stdout=json.dumps(
                    comments_page(
                        [
                            comment("bot", "agent-bot", NOW),
                            comment("boundary", "les", PARKED),
                            comment(
                                "reactions",
                                "agent-bot",
                                PARKED,
                                reactions=(
                                    reaction("les", NOW, content="HEART"),
                                    reaction("dependabot[bot]", NOW),
                                    reaction("les", PARKED),
                                ),
                            ),
                        ]
                    )
                )
            )
        ]
    )

    observations = fetch_approval_predicates(
        REPOSITORY, (watch(),), "read-token", BOTS, runner=runner
    )

    assert observations[0].value is False


def test_a_human_thumbs_up_strictly_after_park_satisfies_the_predicate() -> None:
    runner = SequenceRunner(
        [
            Result(
                stdout=json.dumps(
                    comments_page(
                        [
                            comment(
                                "approval",
                                "agent-bot",
                                PARKED,
                                reactions=(reaction("les", NOW),),
                            )
                        ]
                    )
                )
            )
        ]
    )

    observations = fetch_approval_predicates(
        REPOSITORY, (watch(),), "read-token", BOTS, runner=runner
    )

    assert observations[0].value is True


def test_reaction_observations_are_silent_first_then_emit_only_on_changes(
    tmp_path: Path,
) -> None:
    """Silent first *because the first value here is False*, not because it is first.

    The sequence below starts unapproved, which is the ordinary case: nothing has
    happened yet. A fresh watch whose first observation is already True is a different
    case and does invalidate -- see
    `test_a_first_poll_seeing_approval_invalidates_immediately`.
    """
    store = migrated(tmp_path)
    store.upsert_watch(watch())
    values = iter((False, False, True, False))

    def fetcher(repository, watches, token, bot_logins):
        assert repository == REPOSITORY
        assert token == "read-token" and bot_logins == BOTS
        return tuple(ApprovalPredicateObservation(item, next(values)) for item in watches)

    outcomes = []
    for offset in range(4):
        observed_at = NOW + timedelta(minutes=offset)
        outcomes.append(
            poll_reactions_once(
                config(tmp_path / "events.sqlite3"),
                store,
                "read-token",
                BOTS,
                worker_id=f"reactions-{offset}",
                now=observed_at,
                fetcher=fetcher,
                clock=fixed_clock(observed_at),
            )
        )

    assert [item.invalidations for item in outcomes] == [0, 0, 1, 1]
    assert store.connection.execute(
        "SELECT generation FROM dirty_targets WHERE target_kind='issue' AND target_key='42'"
    ).fetchone()[0] == 2
    assert store.connection.execute(
        "SELECT source_kind,source_key FROM invalidations ORDER BY id"
    ).fetchall()[0][:] == ("reaction_observation", "reactions:1")
    observed = store.list_watches(1)[0]
    assert observed.last_value is False
    assert observed.last_checked_at == NOW + timedelta(minutes=3)


def test_changed_reaction_observation_is_claimable_by_the_driver(tmp_path: Path) -> None:
    store = migrated(tmp_path)
    store.upsert_watch(watch(last_value=False, last_checked_at=PARKED))

    outcome = poll_reactions_once(
        config(tmp_path / "events.sqlite3"),
        store,
        "read-token",
        BOTS,
        worker_id="reactions",
        now=NOW,
        fetcher=lambda _repository, watches, _token, _bots: tuple(
            ApprovalPredicateObservation(item, True) for item in watches
        ),
        clock=lambda: NOW,
    )

    claim = store.claim_targets(
        1,
        worker_id="driver",
        limit=10,
        lease_until=NOW + timedelta(minutes=5),
        now=NOW,
    )[0]
    assert outcome.invalidations == 1
    assert (claim.repository_id, claim.target_kind, claim.target_key) == (1, "issue", "42")


def test_reaction_source_lease_excludes_a_second_pass(tmp_path: Path) -> None:
    store = migrated(tmp_path)
    store.upsert_watch(watch())
    assert store.acquire_poller_lease(
        "reactions:1",
        worker_id="other",
        lease_until=NOW + timedelta(minutes=1),
        now=NOW,
    )
    called = False

    def fetcher(*_args):
        nonlocal called
        called = True
        return ()

    outcome = poll_reactions_once(
        config(tmp_path / "events.sqlite3"),
        store,
        "read-token",
        BOTS,
        worker_id="reactions",
        now=NOW,
        fetcher=fetcher,
        clock=lambda: NOW,
    )

    assert outcome.exit_code == 0 and outcome.skipped == 1
    assert called is False


def test_reaction_worker_losing_its_lease_cannot_record_an_observation(
    tmp_path: Path,
) -> None:
    first = migrated(tmp_path)
    second = QueueStore.open(tmp_path / "events.sqlite3", busy_timeout_ms=250)
    original = watch(last_value=False, last_checked_at=PARKED)
    first.upsert_watch(original)
    after_expiry = NOW + timedelta(minutes=6)

    def fetcher(_repository, watches, _token, _bots):
        assert second.acquire_poller_lease(
            "reactions:1",
            worker_id="newer-reactions",
            lease_until=after_expiry + timedelta(minutes=5),
            now=after_expiry,
        )
        return tuple(ApprovalPredicateObservation(item, True) for item in watches)

    outcome = poll_reactions_once(
        config(tmp_path / "events.sqlite3"),
        first,
        "read-token",
        BOTS,
        worker_id="stale-reactions",
        now=NOW,
        fetcher=fetcher,
        clock=lambda: after_expiry,
    )

    assert outcome.exit_code == 1
    assert first.list_watches(1) == (original,)
    assert first.connection.execute("SELECT count(*) FROM dirty_targets").fetchone()[0] == 0
    state = first.status(now=after_expiry).pollers[0]
    assert state.lease_owner == "newer-reactions"
    assert state.last_success_at is None


def test_reaction_worker_cannot_commit_after_an_unclaimed_lease_expires(
    tmp_path: Path,
) -> None:
    store = migrated(tmp_path)
    original = watch(last_value=False, last_checked_at=PARKED)
    store.upsert_watch(original)
    after_expiry = NOW + timedelta(minutes=6)

    outcome = poll_reactions_once(
        config(tmp_path / "events.sqlite3"),
        store,
        "read-token",
        BOTS,
        worker_id="stale-reactions",
        now=NOW,
        fetcher=lambda _repository, watches, _token, _bots: tuple(
            ApprovalPredicateObservation(item, True) for item in watches
        ),
        clock=lambda: after_expiry,
    )

    assert outcome.exit_code == 1
    assert store.list_watches(1) == (original,)
    assert store.connection.execute("SELECT count(*) FROM dirty_targets").fetchone()[0] == 0
    assert store.poller_last_success_at("reactions:1") is None


def test_each_reaction_observation_checks_lease_expiry_at_its_own_transaction(
    tmp_path: Path,
) -> None:
    store = migrated(tmp_path)
    first = watch(42, last_value=False, last_checked_at=PARKED)
    second = watch(43, last_value=False, last_checked_at=PARKED)
    store.upsert_watch(first)
    store.upsert_watch(second)
    before_expiry = NOW + timedelta(minutes=1)
    after_expiry = NOW + timedelta(minutes=6)
    times = iter((before_expiry, after_expiry, after_expiry))

    outcome = poll_reactions_once(
        config(tmp_path / "events.sqlite3"),
        store,
        "read-token",
        BOTS,
        worker_id="reactions",
        now=NOW,
        fetcher=lambda _repository, watches, _token, _bots: (
            ApprovalPredicateObservation(watches[0], False),
            ApprovalPredicateObservation(watches[1], True),
        ),
        clock=lambda: next(times),
    )

    assert outcome.exit_code == 1
    assert store.list_watches(1) == (
        ApprovalWatch(
            1,
            42,
            "human_approval_since_park",
            PARKED,
            False,
            before_expiry,
        ),
        second,
    )
    assert store.connection.execute("SELECT count(*) FROM dirty_targets").fetchone()[0] == 0


@pytest.mark.parametrize(
    "result",
    [
        Result(returncode=1, stderr="transport failed"),
        Result(stdout=json.dumps({"errors": [{"message": "GraphQL failed"}]})),
        Result(stdout=json.dumps(comments_page([], include_page_info=False))),
    ],
    ids=("transport", "graphql", "missing-page-info"),
)
def test_failed_reaction_fetch_preserves_the_prior_observation_and_success_clock(
    tmp_path: Path,
    result: Result,
) -> None:
    store = migrated(tmp_path)
    original = watch(last_value=False, last_checked_at=PARKED)
    store.upsert_watch(original)
    assert store.acquire_poller_lease(
        "reactions:1",
        worker_id="baseline",
        lease_until=PARKED + timedelta(minutes=1),
        now=PARKED,
    )
    store.finish_poller(
        "reactions:1", worker_id="baseline", succeeded=True, now=PARKED
    )
    runner = SequenceRunner([result])

    outcome = poll_reactions_once(
        config(tmp_path / "events.sqlite3"),
        store,
        "read-token",
        BOTS,
        worker_id="reactions",
        now=NOW,
        fetcher=lambda repository, watches, token, bots: fetch_approval_predicates(
            repository, watches, token, bots, runner=runner
        ),
        clock=lambda: NOW,
    )

    assert outcome.exit_code == 1
    assert store.list_watches(1) == (original,)
    assert store.poller_last_success_at("reactions:1") == PARKED
    assert store.connection.execute("SELECT count(*) FROM dirty_targets").fetchone()[0] == 0


def test_repark_resets_the_first_observation_to_silent(tmp_path: Path) -> None:
    store = migrated(tmp_path)
    store.upsert_watch(watch(last_value=True, last_checked_at=NOW))
    reparking = ApprovalWatch(
        1,
        42,
        "human_approval_since_park",
        NOW + timedelta(minutes=1),
    )

    store.upsert_watch(reparking)

    assert store.list_watches(1) == (reparking,)
    assert store.record_watch_observation(
        reparking, value=False, observed_at=NOW + timedelta(minutes=2)
    ) is False
    assert store.connection.execute("SELECT count(*) FROM dirty_targets").fetchone()[0] == 0


def test_stale_same_park_observation_cannot_reverse_a_newer_value(tmp_path: Path) -> None:
    first = migrated(tmp_path)
    second = QueueStore.open(tmp_path / "events.sqlite3", busy_timeout_ms=250)
    initial = watch(last_value=False, last_checked_at=PARKED)
    first.upsert_watch(initial)
    stale = first.list_watches(1)[0]

    assert second.record_watch_observation(stale, value=True, observed_at=NOW) is True
    assert (
        first.record_watch_observation(
            stale,
            value=False,
            observed_at=NOW + timedelta(minutes=1),
        )
        is False
    )

    assert first.list_watches(1)[0] == ApprovalWatch(
        1,
        42,
        "human_approval_since_park",
        PARKED,
        True,
        NOW,
    )
    assert first.connection.execute(
        "SELECT generation FROM dirty_targets WHERE target_kind='issue' AND target_key='42'"
    ).fetchone()[0] == 1


def test_stale_same_value_fetch_cannot_regress_a_newer_check_time(tmp_path: Path) -> None:
    first = migrated(tmp_path)
    second = QueueStore.open(tmp_path / "events.sqlite3", busy_timeout_ms=250)
    initial = watch(last_value=False, last_checked_at=PARKED)
    first.upsert_watch(initial)
    stale = first.list_watches(1)[0]
    newer_checked_at = NOW + timedelta(minutes=2)

    assert (
        second.record_watch_observation(
            stale,
            value=False,
            observed_at=newer_checked_at,
        )
        is False
    )
    assert (
        first.record_watch_observation(
            stale,
            value=True,
            observed_at=NOW + timedelta(minutes=1),
        )
        is False
    )

    assert first.list_watches(1)[0] == ApprovalWatch(
        1,
        42,
        "human_approval_since_park",
        PARKED,
        False,
        newer_checked_at,
    )
    assert first.connection.execute("SELECT count(*) FROM dirty_targets").fetchone()[0] == 0


def test_poll_reactions_cli_runs_one_pass_with_only_the_read_credential(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from agent_sessions.events import cli

    database = tmp_path / "events.sqlite3"
    QueueStore.migrate(database, busy_timeout_ms=250)
    loaded = config(database)
    calls: list[tuple[str, frozenset[str], str]] = []
    monkeypatch.setattr(cli.config, "load", lambda _path: loaded)
    monkeypatch.setattr(
        cli.credentials,
        "resolve_read_credential",
        lambda: "read-token",
    )
    resolved_logins: list[str] = []

    def resolve_read_login(token: str) -> str:
        resolved_logins.append(token)
        return "agent-reader"

    monkeypatch.setattr(
        cli.credentials,
        "resolve_read_login",
        resolve_read_login,
    )
    monkeypatch.setattr(
        cli.credentials,
        "resolve_board_credential",
        lambda: pytest.fail("Reaction polling inspected the board credential"),
    )
    monkeypatch.setenv("DRIVER_GH_LOGIN", "private-driver-login")
    monkeypatch.setenv("DRIVER_BOT_LOGINS", "private-extra-bot")

    def one_pass(_config, _store, token, bot_logins, *, worker_id, now):
        calls.append((token, bot_logins, worker_id))
        assert now.tzinfo is not None
        return PollRunResult(attempted=1, invalidations=1)

    monkeypatch.setattr(cli.pollers, "poll_reactions_once", one_pass)

    assert cli.main(["--config", str(tmp_path / "events.toml"), "poll-reactions"]) == 0
    assert len(calls) == 1 and calls[0][0] == "read-token"
    assert "agent-reader" in calls[0][1]
    assert "private-driver-login" not in calls[0][1]
    assert "private-extra-bot" not in calls[0][1]
    assert resolved_logins == ["read-token"]
    assert "attempted=1" in capsys.readouterr().err


# --- queue contention is a recorded error, never a raised one -------------------------
#
# `DaemonRuntime._run` lets a raised exception kill the poll task, which makes the daemon
# unready. That is deliberate and asserted in `tests/events/test_daemon.py` -- it is the
# fail-loud signal for a bug. But `list_watches` and `acquire_poller_lease` used to sit
# outside the pass's try, so a three-second lock wait against the driver's own write
# transaction reached the daemon by raising and was classified as a bug: the task died,
# `ready()` returned False forever, and behind a readiness-gated proxy webhook ingestion
# stopped until restart. `docs/events.md` promises the opposite for a normal poll error.
#
# The tests below pin both halves. Contention is recorded and the pass returns; a genuine
# bug still propagates, so the fail-loud path is not widened into swallowing defects.


class _Boom:
    """A store whose watch listing or lease acquisition fails a chosen way."""

    def __init__(self, inner: QueueStore, error: BaseException, *, on: str) -> None:
        self._inner = inner
        self._error = error
        self._on = on

    def __getattr__(self, name: str):  # noqa: ANN204
        if name == self._on:
            def fail(*_args, **_kwargs):
                raise self._error

            return fail
        return getattr(self._inner, name)


def _boom(inner: QueueStore, error: BaseException, *, on: str) -> QueueStore:
    """A `_Boom` in the store's clothing. The cast is the usual test-double escape."""
    return cast(QueueStore, _Boom(inner, error, on=on))


def _watched(store: QueueStore) -> None:
    store.upsert_watch(ApprovalWatch(REPOSITORY.identity.id, 42, "reaction", PARKED, None, None))


def test_a_busy_queue_while_listing_watches_is_recorded_not_raised(tmp_path: Path) -> None:
    store = migrated(tmp_path)
    _watched(store)
    from agent_sessions.events.models import QueueBusy

    result = poll_reactions_once(
        config(tmp_path / "events.sqlite3"),
        _boom(store, QueueBusy("queue database is busy"), on="list_watches"),
        "read-token",
        BOTS,
        worker_id="w1",
        now=NOW,
        fetcher=lambda *_a: (),
    )

    assert result.errors and "busy" in result.errors[0]
    assert result.attempted == 0


def test_a_locked_queue_while_listing_watches_is_recorded_not_raised(tmp_path: Path) -> None:
    """Store *reads* bypass `_transaction`, so they raise sqlite3's own exception."""
    import sqlite3

    store = migrated(tmp_path)
    _watched(store)

    result = poll_reactions_once(
        config(tmp_path / "events.sqlite3"),
        _boom(store, sqlite3.OperationalError("database is locked"), on="list_watches"),
        "read-token",
        BOTS,
        worker_id="w1",
        now=NOW,
        fetcher=lambda *_a: (),
    )

    assert result.errors and "locked" in result.errors[0]


def test_a_busy_queue_while_acquiring_the_lease_is_recorded_not_raised(tmp_path: Path) -> None:
    store = migrated(tmp_path)
    _watched(store)
    from agent_sessions.events.models import QueueBusy

    result = poll_reactions_once(
        config(tmp_path / "events.sqlite3"),
        _boom(store, QueueBusy("queue database is busy"), on="acquire_poller_lease"),
        "read-token",
        BOTS,
        worker_id="w1",
        now=NOW,
        fetcher=lambda *_a: (),
    )

    assert result.errors and "busy" in result.errors[0]
    assert result.attempted == 0


def test_a_genuine_bug_still_propagates_and_is_not_recorded(tmp_path: Path) -> None:
    """The fail-loud path must stay open, or the daemon can never report a defect."""
    store = migrated(tmp_path)
    _watched(store)

    with pytest.raises(AttributeError, match="programming error"):
        poll_reactions_once(
            config(tmp_path / "events.sqlite3"),
            _boom(store, AttributeError("programming error"), on="list_watches"),
            "read-token",
            BOTS,
            worker_id="w1",
            now=NOW,
            fetcher=lambda *_a: (),
        )


# --- configured machine logins reach the poller, the driver's env still does not ------
#
# `bot_logins` is what `_approval_predicate` uses to decide whether an actor is a human,
# and that decision can unpark an issue awaiting human judgment -- so a machine login
# missing from the set is a machine that can approve. The set now comes from this
# service's own `events.toml`, which is what keeps the boundary above intact:
# `test_poll_reactions_cli_runs_one_pass_with_only_the_read_credential` still asserts
# that `DRIVER_BOT_LOGINS` and `DRIVER_GH_LOGIN` are not read, and it is unchanged.


def test_configured_bot_logins_reach_the_reaction_poller(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from agent_sessions.events import cli

    database = tmp_path / "events.sqlite3"
    QueueStore.migrate(database, busy_timeout_ms=250)
    loaded = replace(config(database), bot_logins=("renovate", "ci-account"))
    calls: list[frozenset[str]] = []
    monkeypatch.setattr(cli.config, "load", lambda _path: loaded)
    monkeypatch.setattr(cli.credentials, "resolve_read_credential", lambda: "read-token")
    monkeypatch.setattr(cli.credentials, "resolve_read_login", lambda _token: "agent-reader")
    monkeypatch.setenv("DRIVER_BOT_LOGINS", "should-not-be-read")

    def one_pass(_config, _store, _token, bot_logins, *, worker_id, now):
        calls.append(bot_logins)
        return PollRunResult(attempted=1, invalidations=0)

    monkeypatch.setattr(cli.pollers, "poll_reactions_once", one_pass)

    assert cli.main(["--config", str(tmp_path / "events.toml"), "poll-reactions"]) == 0

    assert len(calls) == 1
    honoured = calls[0]
    assert "renovate" in honoured and "ci-account" in honoured
    assert "agent-reader" in honoured, "the daemon's own login must stay a machine"
    assert "github-actions[bot]" in honoured, "the always-bots must stay included"
    assert "should-not-be-read" not in honoured, "the driver's env is still not read"


def test_the_honoured_machine_logins_are_disclosed_at_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The set is opt-in, so an operator needs to see the belief without reading source."""
    from agent_sessions.events import cli

    database = tmp_path / "events.sqlite3"
    QueueStore.migrate(database, busy_timeout_ms=250)
    loaded = replace(config(database), bot_logins=("renovate",))
    monkeypatch.setattr(cli.config, "load", lambda _path: loaded)
    monkeypatch.setattr(cli.credentials, "resolve_read_credential", lambda: "read-token")
    monkeypatch.setattr(cli.credentials, "resolve_read_login", lambda _token: "agent-reader")
    monkeypatch.setattr(
        cli.pollers,
        "poll_reactions_once",
        lambda *_a, **_k: PollRunResult(attempted=0),
    )

    assert cli.main(["--config", str(tmp_path / "events.toml"), "poll-reactions"]) == 0

    err = capsys.readouterr().err
    assert "machine logins honoured" in err
    assert "renovate" in err


def test_a_first_poll_seeing_approval_invalidates_immediately(tmp_path: Path) -> None:
    """The finding-7 fix at the poller level, where the cost was actually paid.

    A watch is created with `last_value=None` on every fresh park, and the predicate is
    scoped to after `parked_at` -- so a True first observation means a human acted in the
    window between the park and this poll. Treating None as "unknown" swallowed it: the
    first pass stored True and enqueued nothing, and every later pass was True->True, so
    the polling path never signalled the approval at all. It was found only by the next
    quiet-period or hard-deadline full scan, which is the latency this feature exists to
    remove.

    The bot half of the same decision is covered upstream by
    `test_approval_predicate_requires_non_bot_activity_strictly_after_park`: a bot's
    reaction never reaches this point as True.
    """
    store = migrated(tmp_path)
    store.upsert_watch(watch())
    assert store.list_watches(1)[0].last_value is None, "precondition: a fresh park"

    outcome = poll_reactions_once(
        config(tmp_path / "events.sqlite3"),
        store,
        "read-token",
        BOTS,
        worker_id="reactions",
        now=NOW,
        fetcher=lambda _repository, watches, _token, _bots: tuple(
            ApprovalPredicateObservation(item, True) for item in watches
        ),
        clock=lambda: NOW,
    )

    assert outcome.invalidations == 1
    assert store.connection.execute(
        "SELECT source_kind FROM invalidations ORDER BY id"
    ).fetchall()[0][0] == "reaction_observation"
    assert store.list_watches(1)[0].last_value is True


def test_a_first_poll_seeing_no_approval_stays_quiet(tmp_path: Path) -> None:
    """Non-vacuity: the common case must not enqueue an invalidation per parked issue."""
    store = migrated(tmp_path)
    store.upsert_watch(watch())

    outcome = poll_reactions_once(
        config(tmp_path / "events.sqlite3"),
        store,
        "read-token",
        BOTS,
        worker_id="reactions",
        now=NOW,
        fetcher=lambda _repository, watches, _token, _bots: tuple(
            ApprovalPredicateObservation(item, False) for item in watches
        ),
        clock=lambda: NOW,
    )

    assert outcome.invalidations == 0
    assert store.connection.execute("SELECT count(*) FROM invalidations").fetchone()[0] == 0
