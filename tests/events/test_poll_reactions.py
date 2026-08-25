from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_sessions.events.github import (
    ApprovalPredicateObservation,
    fetch_approval_predicates,
)
from agent_sessions.events.models import (
    ApprovalWatch,
    EventsConfig,
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
            Result(stdout=json.dumps([first_page, second_page])),
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
    assert len(commands) == 2
    assert all(command[:4] == ["gh", "api", "graphql", "--paginate"] for command in commands)
    assert [next(part for part in command if part.startswith("issue=")) for command in commands] == [
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
    monkeypatch.setattr(
        cli.credentials,
        "resolve_board_credential",
        lambda: pytest.fail("Reaction polling inspected the board credential"),
    )
    monkeypatch.setenv("DRIVER_GH_LOGIN", "agent-bot")
    monkeypatch.setenv("DRIVER_BOT_LOGINS", "extra-bot")

    def one_pass(_config, _store, token, bot_logins, *, worker_id, now):
        calls.append((token, bot_logins, worker_id))
        assert now.tzinfo is not None
        return PollRunResult(attempted=1, invalidations=1)

    monkeypatch.setattr(cli.pollers, "poll_reactions_once", one_pass)

    assert cli.main(["--config", str(tmp_path / "events.toml"), "poll-reactions"]) == 0
    assert len(calls) == 1 and calls[0][0] == "read-token"
    assert {"agent-bot", "extra-bot"} <= calls[0][1]
    assert "attempted=1" in capsys.readouterr().err
