from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_sessions.events.github import (
    CompleteProjectSnapshot,
    GitHubReadStopped,
    fetch_board_items,
    fetch_project_items,
)
from agent_sessions.events.models import (
    BoardConfig,
    EventsConfig,
    Invalidation,
    PollFailure,
    PollingPolicy,
    ProjectItemProjection,
    RepositoryConfig,
    RepositoryIdentity,
    ScanPolicy,
)
from agent_sessions.events.pollers import PollRunResult, diff_project_snapshot, poll_projects_once
from agent_sessions.events.store import QueueStore

NOW = datetime(2026, 8, 25, 12, tzinfo=UTC)
EARLIER = NOW - timedelta(hours=1)
BOARD = BoardConfig("owner", 9, (1,))


class Result:
    def __init__(self, *, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class Runner:
    def __init__(self, result: Result | list[Result]) -> None:
        self.results = iter(result if isinstance(result, list) else [result])
        self.calls: list[tuple[list[str], dict[str, object]]] = []

    def __call__(self, command, **kwargs):
        self.calls.append((list(command), kwargs))
        return next(self.results)


def repository(repository_id: int = 1, name: str = "repo") -> RepositoryConfig:
    return RepositoryConfig(RepositoryIdentity(repository_id, "owner", name, 99))


def config(path: Path, *, boards: tuple[BoardConfig, ...] = (BOARD,)) -> EventsConfig:
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
        repositories=(repository(), repository(2, "other")),
        boards=boards,
    )


def migrated(tmp_path: Path) -> QueueStore:
    path = tmp_path / "events.sqlite3"
    QueueStore.migrate(path, busy_timeout_ms=250)
    store = QueueStore.open(path, busy_timeout_ms=250)
    store.register_repositories((repository().identity, repository(2, "other").identity))
    return store


def projection(
    item_id: str = "PVTI_1",
    *,
    repository_id: int = 1,
    kind: str = "issue",
    number: int = 42,
    status: str | None = "Ready",
    priority: str | None = "P1",
    seen_at: datetime = NOW,
) -> ProjectItemProjection:
    return ProjectItemProjection(
        "owner/9",
        item_id,
        repository_id,
        kind,  # type: ignore[arg-type]
        number,
        status,
        priority,
        seen_at,
    )


def project_item(
    item_id: str,
    *,
    repository_id: int = 1,
    repository_name: str = "owner/repo",
    typename: str = "Issue",
    number: int = 42,
    status: str | None = "Ready",
    priority: str | None = "P1",
    title: str = "Issue title",
) -> dict[str, object]:
    fields: list[dict[str, object]] = [
        {
            "__typename": "ProjectV2ItemFieldTextValue",
            "text": "ignored field",
            "field": {"name": "Notes"},
        }
    ]
    if status is not None:
        fields.append(
            {
                "__typename": "ProjectV2ItemFieldSingleSelectValue",
                "name": status,
                "field": {"name": "Status"},
            }
        )
    if priority is not None:
        fields.append(
            {
                "__typename": "ProjectV2ItemFieldSingleSelectValue",
                "name": priority,
                "field": {"name": "Priority"},
            }
        )
    return {
        "id": item_id,
        "type": "ISSUE" if typename == "Issue" else "PULL_REQUEST",
        "content": {
            "__typename": typename,
            "number": number,
            "title": title,
            "repository": {
                "databaseId": repository_id,
                "nameWithOwner": repository_name,
            },
        },
        "fieldValues": {
            "nodes": fields,
            "pageInfo": {"hasNextPage": False, "endCursor": None},
        },
    }


def project_page(
    nodes: list[dict[str, object]],
    *,
    has_next: bool,
    end_cursor: str | int | None,
    remaining: int = 5000,
    include_page_info: bool = True,
    include_has_next: bool = True,
    include_end_cursor: bool = True,
) -> dict[str, object]:
    items: dict[str, object] = {"nodes": nodes}
    if include_page_info:
        page_info: dict[str, object] = {}
        if include_has_next:
            page_info["hasNextPage"] = has_next
        if include_end_cursor:
            page_info["endCursor"] = end_cursor
        items["pageInfo"] = page_info
    return {
        "data": {
            "user": {"projectV2": {"id": "PVT_9", "items": items}},
            "rateLimit": {
                "limit": 5000,
                "cost": 1,
                "remaining": remaining,
                "resetAt": "2026-08-25T13:00:00Z",
            },
        }
    }


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        (
            (),
            (projection(),),
            (
                Invalidation(
                    1,
                    "issue",
                    "42",
                    "project_membership_added",
                    {"board_key": "owner/9", "item_node_id": "PVTI_1"},
                ),
            ),
        ),
        (
            (projection(repository_id=1, number=42),),
            (),
            (
                Invalidation(
                    1,
                    "issue",
                    "42",
                    "project_membership_removed",
                    {"board_key": "owner/9", "item_node_id": "PVTI_1"},
                ),
            ),
        ),
        (
            (projection(status="Ready"),),
            (projection(status="In progress"),),
            (
                Invalidation(
                    1,
                    "issue",
                    "42",
                    "project_fields_changed",
                    {
                        "board_key": "owner/9",
                        "item_node_id": "PVTI_1",
                        "fields": ["status"],
                    },
                ),
            ),
        ),
        (
            (projection(priority="P1"),),
            (projection(priority="P2"),),
            (
                Invalidation(
                    1,
                    "issue",
                    "42",
                    "project_fields_changed",
                    {
                        "board_key": "owner/9",
                        "item_node_id": "PVTI_1",
                        "fields": ["priority"],
                    },
                ),
            ),
        ),
        ((projection(seen_at=EARLIER),), (projection(seen_at=NOW),), ()),
    ],
)
def test_project_diff_uses_only_membership_status_and_priority(
    before: tuple[ProjectItemProjection, ...],
    after: tuple[ProjectItemProjection, ...],
    expected: tuple[Invalidation, ...],
) -> None:
    assert diff_project_snapshot(before, after) == expected


def test_fetch_project_items_reads_every_page_and_filters_other_repositories() -> None:
    runner = Runner(
        [
            Result(
                stdout=json.dumps(
                    project_page(
                        [project_item("PVTI_1", number=42)],
                        has_next=True,
                        end_cursor="cursor-1",
                    )
                )
            ),
            Result(
                stdout=json.dumps(
                    project_page(
                        [
                            project_item(
                                "PVTI_2",
                                repository_id=2,
                                repository_name="owner/other",
                                typename="PullRequest",
                                number=7,
                            ),
                            project_item(
                                "PVTI_3",
                                typename="PullRequest",
                                number=8,
                                status="In progress",
                                priority=None,
                            ),
                        ],
                        has_next=False,
                        end_cursor=None,
                    )
                )
            ),
        ]
    )

    snapshot = fetch_project_items(BOARD, "board-token", runner=runner, now=NOW)

    assert snapshot == CompleteProjectSnapshot(
        "owner/9",
        (
            projection("PVTI_1", number=42),
            projection(
                "PVTI_3",
                kind="pull_request",
                number=8,
                status="In progress",
                priority=None,
            ),
        ),
        NOW,
    )
    assert len(runner.calls) == 2
    first_command, first_kwargs = runner.calls[0]
    second_command, second_kwargs = runner.calls[1]
    assert first_command[:3] == ["gh", "api", "graphql"]
    assert "--paginate" not in first_command
    assert "--slurp" not in first_command
    assert not any(part.startswith("endCursor=") for part in first_command)
    assert "endCursor=cursor-1" in second_command
    assert first_kwargs["env"]["GH_TOKEN"] == "board-token"  # type: ignore[index]
    assert second_kwargs["env"]["GH_TOKEN"] == "board-token"  # type: ignore[index]
    assert first_kwargs["timeout"] == second_kwargs["timeout"] == 60


def test_driver_board_items_use_the_direct_graphql_snapshot_shape() -> None:
    runner = Runner(
        Result(
            stdout=json.dumps(
                project_page(
                    [project_item("PVTI_1", title="Direct GraphQL")],
                    has_next=False,
                    end_cursor=None,
                )
            )
        )
    )

    items = fetch_board_items(
        "owner/9",
        env={"GH_TOKEN": "read-token", "GITHUB_TOKEN": "read-token"},
        runner=runner,
    )

    assert items == [
        {
            "id": "PVTI_1",
            "title": "Direct GraphQL",
            "status": "Ready",
            "priority": "P1",
            "content": {
                "type": "Issue",
                "number": 42,
                "title": "Direct GraphQL",
                "repository": "owner/repo",
            },
        }
    ]
    assert runner.calls[0][0][:3] == ["gh", "api", "graphql"]


def test_shutdown_stops_project_pagination_before_the_next_page() -> None:
    stopping = False
    calls: list[list[str]] = []
    first_page = project_page(
        [project_item("PVTI_1")],
        has_next=True,
        end_cursor="next-page",
    )

    def runner(command, **_kwargs):
        nonlocal stopping
        calls.append(list(command))
        if len(calls) > 1:
            pytest.fail("shutdown allowed a second GraphQL page subprocess")
        stopping = True
        return Result(stdout=json.dumps(first_page))

    with pytest.raises(GitHubReadStopped, match="stopped"):
        fetch_project_items(
            BOARD,
            "read-token",
            runner=runner,
            now=NOW,
            stop_requested=lambda: stopping,
        )

    assert len(calls) == 1


@pytest.mark.parametrize(
    "unsupported",
    [
        {
            "id": "PVTI_draft",
            "type": "DRAFT_ISSUE",
            "content": {"__typename": "DraftIssue"},
            "fieldValues": {
                "nodes": [],
                "pageInfo": {"hasNextPage": False, "endCursor": None},
            },
        },
        {
            "id": "PVTI_redacted",
            "type": "REDACTED",
            "content": None,
            "fieldValues": {
                "nodes": [],
                "pageInfo": {"hasNextPage": False, "endCursor": None},
            },
        },
    ],
    ids=("draft", "redacted"),
)
def test_fetch_project_items_ignores_a_structurally_valid_known_unsupported_type(
    unsupported: dict[str, object],
) -> None:
    runner = Runner(
        Result(
            stdout=json.dumps(
                project_page([unsupported], has_next=False, end_cursor=None)
            )
        )
    )

    assert fetch_project_items(BOARD, "board-token", runner=runner, now=NOW) == (
        CompleteProjectSnapshot("owner/9", (), NOW)
    )


def test_first_complete_project_fetch_is_a_silent_baseline_even_when_empty(
    tmp_path: Path,
) -> None:
    store = migrated(tmp_path)
    loaded = config(tmp_path / "events.sqlite3")
    snapshots = iter(
        (
            CompleteProjectSnapshot("owner/9", (), NOW),
            CompleteProjectSnapshot("owner/9", (projection(),), NOW + timedelta(minutes=5)),
        )
    )

    first = poll_projects_once(
        loaded,
        store,
        "board-token",
        worker_id="projects-one",
        now=NOW,
        fetcher=lambda _board, _token: next(snapshots),
        clock=lambda: NOW,
    )
    assert first.invalidations == 0
    assert store.connection.execute("SELECT count(*) FROM dirty_targets").fetchone()[0] == 0
    assert store.poller_last_success_at("projects:owner/9") == NOW

    second = poll_projects_once(
        loaded,
        store,
        "board-token",
        worker_id="projects-two",
        now=NOW + timedelta(minutes=5),
        fetcher=lambda _board, _token: next(snapshots),
        clock=lambda: NOW + timedelta(minutes=5),
    )
    assert second.invalidations == 1
    assert store.connection.execute(
        "SELECT target_kind,target_key,generation FROM dirty_targets"
    ).fetchone()[:] == ("issue", "42", 1)
    assert store.connection.execute(
        "SELECT source_kind,source_key FROM invalidations"
    ).fetchone()[:] == ("project_snapshot", "projects:owner/9")


def test_project_diff_silently_drops_rows_outside_the_current_board_allowlist(
    tmp_path: Path,
) -> None:
    store = migrated(tmp_path)
    allowed = projection("PVTI_allowed", repository_id=1, number=42, seen_at=EARLIER)
    removed_from_config = projection(
        "PVTI_unconfigured",
        repository_id=2,
        number=43,
        seen_at=EARLIER,
    )
    store.replace_project_snapshot(
        "owner/9",
        (allowed, removed_from_config),
        (),
        now=EARLIER,
    )
    assert store.acquire_poller_lease(
        "projects:owner/9",
        worker_id="baseline",
        lease_until=EARLIER + timedelta(minutes=1),
        now=EARLIER,
    )
    store.finish_poller(
        "projects:owner/9",
        worker_id="baseline",
        succeeded=True,
        now=EARLIER,
    )

    outcome = poll_projects_once(
        config(tmp_path / "events.sqlite3"),
        store,
        "board-token",
        worker_id="projects",
        now=NOW,
        fetcher=lambda _board, _token: CompleteProjectSnapshot("owner/9", (), NOW),
        clock=lambda: NOW,
    )

    assert outcome.invalidations == 1
    assert store.project_snapshot("owner/9") == ()
    assert [
        row[0]
        for row in store.connection.execute(
            "SELECT repository_id FROM invalidations ORDER BY id"
        )
    ] == [1]


@pytest.mark.parametrize(
    "result",
    [
        Result(returncode=1, stderr="transport failed"),
        Result(stdout=json.dumps({"errors": [{"message": "GraphQL failed"}]})),
        Result(
            stdout=json.dumps(
                project_page(
                    [project_item("PVTI_new")],
                    has_next=False,
                    end_cursor=None,
                    remaining=0,
                )
            )
        ),
        [
            Result(
                stdout=json.dumps(
                    project_page(
                        [project_item("PVTI_new")],
                        has_next=True,
                        end_cursor="cursor-1",
                    )
                )
            ),
            Result(
                stdout=json.dumps(
                    project_page(
                        [{"id": "PVTI_broken", "type": "ISSUE", "content": None}],
                        has_next=False,
                        end_cursor=None,
                    )
                )
            ),
        ],
        Result(
            stdout=json.dumps(
                project_page(
                    [project_item("PVTI_new")],
                    has_next=False,
                    end_cursor=None,
                    include_page_info=False,
                )
            )
        ),
        Result(
            stdout=json.dumps(
                project_page(
                    [
                        {
                            key: value
                            for key, value in project_item("PVTI_missing_type").items()
                            if key != "type"
                        }
                    ],
                    has_next=False,
                    end_cursor=None,
                )
            )
        ),
        Result(
            stdout=json.dumps(
                project_page(
                    [{**project_item("PVTI_non_string_type"), "type": 7}],
                    has_next=False,
                    end_cursor=None,
                )
            )
        ),
        Result(
            stdout=json.dumps(
                project_page(
                    [{**project_item("PVTI_unknown_type"), "type": "MYSTERY"}],
                    has_next=False,
                    end_cursor=None,
                )
            )
        ),
        Result(
            stdout=json.dumps(
                project_page(
                    [
                        {
                            "id": "",
                            "type": "DRAFT_ISSUE",
                            "content": {"__typename": "DraftIssue"},
                            "fieldValues": {
                                "nodes": [],
                                "pageInfo": {
                                    "hasNextPage": False,
                                    "endCursor": None,
                                },
                            },
                        }
                    ],
                    has_next=False,
                    end_cursor=None,
                )
            )
        ),
        Result(
            stdout=json.dumps(
                project_page(
                    [project_item("PVTI_missing_cursor")],
                    has_next=False,
                    end_cursor=None,
                    include_end_cursor=False,
                )
            )
        ),
        Result(
            stdout=json.dumps(
                project_page(
                    [project_item("PVTI_missing_has_next")],
                    has_next=False,
                    end_cursor=None,
                    include_has_next=False,
                )
            )
        ),
        Result(
            stdout=json.dumps(
                project_page(
                    [project_item("PVTI_bad_cursor")],
                    has_next=False,
                    end_cursor=7,
                )
            )
        ),
        Result(
            stdout=json.dumps(
                project_page(
                    [
                        {
                            **project_item("PVTI_missing_field_cursor"),
                            "fieldValues": {
                                "nodes": [],
                                "pageInfo": {"hasNextPage": False},
                            },
                        }
                    ],
                    has_next=False,
                    end_cursor=None,
                )
            )
        ),
    ],
    ids=(
        "transport",
        "graphql",
        "rate-limit",
        "malformed-middle",
        "missing-page-info",
        "missing-item-type",
        "non-string-item-type",
        "unknown-item-type",
        "malformed-known-unsupported-item",
        "missing-terminal-cursor",
        "missing-has-next-page",
        "non-string-terminal-cursor",
        "missing-field-terminal-cursor",
    ),
)
def test_failed_project_fetch_preserves_the_prior_snapshot_and_success_clock(
    tmp_path: Path,
    result: Result | list[Result],
) -> None:
    store = migrated(tmp_path)
    old = projection("PVTI_old", number=41, seen_at=EARLIER)
    store.replace_project_snapshot("owner/9", (old,), (), now=EARLIER)
    assert store.acquire_poller_lease(
        "projects:owner/9",
        worker_id="baseline",
        lease_until=EARLIER + timedelta(minutes=1),
        now=EARLIER,
    )
    store.finish_poller(
        "projects:owner/9", worker_id="baseline", succeeded=True, now=EARLIER
    )
    runner = Runner(result)

    outcome = poll_projects_once(
        config(tmp_path / "events.sqlite3"),
        store,
        "board-token",
        worker_id="projects",
        now=NOW,
        fetcher=lambda board, token: fetch_project_items(
            board, token, runner=runner, now=NOW
        ),
        clock=lambda: NOW,
    )

    assert outcome.exit_code == 1
    assert store.project_snapshot("owner/9") == (old,)
    assert store.connection.execute("SELECT count(*) FROM dirty_targets").fetchone()[0] == 0
    assert store.poller_last_success_at("projects:owner/9") == EARLIER
    assert store.status(now=NOW).pollers[0].last_error


def test_project_source_lease_excludes_a_second_pass(tmp_path: Path) -> None:
    store = migrated(tmp_path)
    assert store.acquire_poller_lease(
        "projects:owner/9",
        worker_id="other",
        lease_until=NOW + timedelta(minutes=1),
        now=NOW,
    )
    called = False

    def fetcher(_board: BoardConfig, _token: str) -> CompleteProjectSnapshot:
        nonlocal called
        called = True
        raise PollFailure("must not fetch")

    outcome = poll_projects_once(
        config(tmp_path / "events.sqlite3"),
        store,
        "board-token",
        worker_id="projects",
        now=NOW,
        fetcher=fetcher,
        clock=lambda: NOW,
    )

    assert outcome.exit_code == 0 and outcome.skipped == 1
    assert called is False


def test_shutdown_stops_project_polling_before_the_next_board(tmp_path: Path) -> None:
    store = migrated(tmp_path)
    stopping = False
    fetched: list[str] = []
    boards = (BOARD, BoardConfig("owner", 10, (2,)))

    def fetcher(board: BoardConfig, _token: str) -> CompleteProjectSnapshot:
        nonlocal stopping
        fetched.append(board.key)
        stopping = True
        return CompleteProjectSnapshot(board.key, (), NOW)

    outcome = poll_projects_once(
        config(tmp_path / "events.sqlite3", boards=boards),
        store,
        "read-token",
        worker_id="projects",
        now=NOW,
        fetcher=fetcher,
        stop_requested=lambda: stopping,
        clock=lambda: NOW,
    )

    assert outcome.attempted == 1
    assert fetched == ["owner/9"]


def test_project_worker_losing_its_lease_cannot_replace_the_snapshot(
    tmp_path: Path,
) -> None:
    first = migrated(tmp_path)
    second = QueueStore.open(tmp_path / "events.sqlite3", busy_timeout_ms=250)
    old = projection("PVTI_old", number=41, seen_at=EARLIER)
    first.replace_project_snapshot("owner/9", (old,), (), now=EARLIER)
    assert first.acquire_poller_lease(
        "projects:owner/9",
        worker_id="baseline",
        lease_until=EARLIER + timedelta(minutes=1),
        now=EARLIER,
    )
    first.finish_poller(
        "projects:owner/9",
        worker_id="baseline",
        succeeded=True,
        now=EARLIER,
    )
    after_expiry = NOW + timedelta(minutes=6)

    def fetcher(_board: BoardConfig, _token: str) -> CompleteProjectSnapshot:
        assert second.acquire_poller_lease(
            "projects:owner/9",
            worker_id="newer-projects",
            lease_until=after_expiry + timedelta(minutes=5),
            now=after_expiry,
        )
        return CompleteProjectSnapshot(
            "owner/9",
            (projection("PVTI_new", number=42, seen_at=after_expiry),),
            after_expiry,
        )

    outcome = poll_projects_once(
        config(tmp_path / "events.sqlite3"),
        first,
        "board-token",
        worker_id="stale-projects",
        now=NOW,
        fetcher=fetcher,
        clock=lambda: after_expiry,
    )

    assert outcome.exit_code == 1
    assert first.project_snapshot("owner/9") == (old,)
    assert first.connection.execute("SELECT count(*) FROM invalidations").fetchone()[0] == 0
    state = first.status(now=after_expiry).pollers[0]
    assert state.lease_owner == "newer-projects"
    assert state.last_success_at == EARLIER


def test_project_worker_cannot_commit_after_an_unclaimed_lease_expires(
    tmp_path: Path,
) -> None:
    store = migrated(tmp_path)
    old = projection("PVTI_old", number=41, seen_at=EARLIER)
    store.replace_project_snapshot("owner/9", (old,), (), now=EARLIER)
    assert store.acquire_poller_lease(
        "projects:owner/9",
        worker_id="baseline",
        lease_until=EARLIER + timedelta(minutes=1),
        now=EARLIER,
    )
    store.finish_poller(
        "projects:owner/9",
        worker_id="baseline",
        succeeded=True,
        now=EARLIER,
    )
    after_expiry = NOW + timedelta(minutes=6)

    outcome = poll_projects_once(
        config(tmp_path / "events.sqlite3"),
        store,
        "board-token",
        worker_id="stale-projects",
        now=NOW,
        fetcher=lambda _board, _token: CompleteProjectSnapshot(
            "owner/9",
            (projection("PVTI_new", number=42, seen_at=after_expiry),),
            after_expiry,
        ),
        clock=lambda: after_expiry,
    )

    assert outcome.exit_code == 1
    assert store.project_snapshot("owner/9") == (old,)
    assert store.connection.execute("SELECT count(*) FROM invalidations").fetchone()[0] == 0
    assert store.poller_last_success_at("projects:owner/9") == EARLIER


def test_poll_projects_cli_runs_one_pass_with_only_the_shared_read_credential(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from agent_sessions.events import cli

    database = tmp_path / "events.sqlite3"
    QueueStore.migrate(database, busy_timeout_ms=250)
    loaded = config(database)
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(cli.config, "load", lambda _path: loaded)
    monkeypatch.setattr(
        cli.credentials,
        "resolve_read_credential",
        lambda: "read-token",
    )
    monkeypatch.setattr(
        cli.credentials,
        "resolve_board_credential",
        lambda: pytest.fail("Projects polling inspected the board credential"),
    )

    def one_pass(_config, _store, token, *, worker_id, now):
        calls.append((token, worker_id))
        assert now.tzinfo is not None
        return PollRunResult(attempted=1, invalidations=2)

    monkeypatch.setattr(cli.pollers, "poll_projects_once", one_pass)

    assert cli.main(["poll-projects", "--config", str(tmp_path / "events.toml")]) == 0
    assert len(calls) == 1 and calls[0][0] == "read-token"
    assert "attempted=1" in capsys.readouterr().err


def test_poll_projects_cli_never_logs_failed_read_credential_command_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from agent_sessions.driver import credentials
    from agent_sessions.events import cli

    database = tmp_path / "events.sqlite3"
    QueueStore.migrate(database, busy_timeout_ms=250)
    loaded = config(database)
    stdout_secret = "ghp_cli_stdout_secret"
    stderr_secret = "ghs_cli_stderr_secret"
    resolve_read_credential = credentials.resolve_read_credential

    def failing_runner(_argv, **_kwargs):
        class Failure:
            returncode = 17
            stdout = stdout_secret
            stderr = stderr_secret

        return Failure()

    monkeypatch.setattr(cli.config, "load", lambda _path: loaded)
    monkeypatch.setattr(
        cli.credentials,
        "resolve_read_credential",
        lambda: resolve_read_credential(
            {
                credentials.READ_TOKEN_VAR
                + credentials.CMD_SUFFIX: "credential-helper board"
            },
            runner=failing_runner,
        ),
    )

    assert cli.main(["poll-projects", "--config", str(tmp_path / "events.toml")]) == 1
    logged = capsys.readouterr().err
    assert credentials.READ_TOKEN_VAR + credentials.CMD_SUFFIX in logged
    assert "exit" in logged and "17" in logged
    assert stdout_secret not in logged
    assert stderr_secret not in logged
