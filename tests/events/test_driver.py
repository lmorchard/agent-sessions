from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_sessions.driver.credentials import Credentials
from agent_sessions.events import driver as events_driver
from agent_sessions.events.driver import QueueRuntime, select_work
from agent_sessions.events.github import (
    GitHubPermanentError,
    GitHubTransientError,
    LiveTargetResolver,
    ResolvedTarget,
)
from agent_sessions.events.models import (
    ApprovalWatch,
    ClaimedTarget,
    EventsConfig,
    Invalidation,
    RepositoryConfig,
    RepositoryIdentity,
    ScanPolicy,
)
from agent_sessions.events.store import QueueStore

NOW = datetime(2026, 8, 25, 12, tzinfo=UTC)
REPOSITORY = RepositoryConfig(RepositoryIdentity(1, "owner", "repo", 99))


class Result:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class RecordingRunner:
    def __init__(self, responses: list[Result]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[list[str], dict[str, str]]] = []

    def __call__(self, command, **kwargs):
        self.calls.append(([str(item) for item in command], dict(kwargs.get("env") or {})))
        return self.responses.pop(0)


def issue(number: int, *, body: str = "", labels: tuple[str, ...] = ("P1",), comments=()):
    return {
        "number": number,
        "title": f"Issue {number}",
        "body": body,
        "labels": [{"name": label} for label in labels],
        "url": f"https://github.com/owner/repo/issues/{number}",
        "updatedAt": "2026-08-25T11:00:00Z",
        "state": "OPEN",
        "comments": list(comments),
    }


def pull(number: int, *, closes: tuple[int, ...], head: str = "head", unresolved: int = 0):
    return {
        "number": number,
        "title": f"PR {number}",
        "body": "",
        "headRefName": f"issue-{number}",
        "headRefOid": head,
        "url": f"https://github.com/owner/repo/pull/{number}",
        "state": "OPEN",
        "closingIssuesReferences": [{"number": value} for value in closes],
        "mergeStateStatus": "CLEAN",
        "mergeable": "MERGEABLE",
        "reviewDecision": "",
        "reviewRequests": [],
        "reviews": [],
        "statusCheckRollup": [],
        "commits": [],
        "comments": [],
        "unresolvedThreads": unresolved,
    }


def discovery_pages(*pull_requests: dict) -> list[dict]:
    return [
        {
            "data": {
                "repository": {
                    "pullRequests": {
                        "nodes": [
                            {
                                "number": item["number"],
                                "headRefOid": item["headRefOid"],
                                "closingIssuesReferences": {
                                    "nodes": item["closingIssuesReferences"],
                                    "pageInfo": {
                                        "hasNextPage": False,
                                        "endCursor": None,
                                    },
                                },
                            }
                            for item in pull_requests
                        ],
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                    }
                }
            }
        }
    ]


def closing_reference_pages(*numbers: int) -> list[dict]:
    return [
        {
            "data": {
                "repository": {
                    "pullRequest": {
                        "closingIssuesReferences": {
                            "nodes": [{"number": number} for number in numbers],
                            "pageInfo": {
                                "hasNextPage": False,
                                "endCursor": None,
                            },
                        }
                    }
                }
            }
        }
    ]


def claim(kind: str, key: str, *, generation: int = 1) -> ClaimedTarget:
    return ClaimedTarget(1, kind, key, generation, "worker")  # type: ignore[arg-type]


def test_issue_target_fetches_current_issue_and_current_closing_prs() -> None:
    current_issue = issue(42, body="current body")
    matching = pull(7, closes=(42,))
    unrelated = pull(8, closes=(99,))
    runner = RecordingRunner(
        [
            Result(stdout=json.dumps(current_issue)),
            Result(stdout=json.dumps(discovery_pages(matching, unrelated))),
            Result(stdout=json.dumps(matching)),
            Result(stdout=json.dumps(closing_reference_pages(42))),
        ]
    )

    resolved = LiveTargetResolver(read_token="read-token", runner=runner).resolve(
        REPOSITORY, claim("issue", "42")
    )

    assert resolved.issues == (current_issue,)
    assert resolved.pull_requests == (matching,)
    assert all(env.get("GH_TOKEN") == "read-token" for _, env in runner.calls)


def test_pr_target_uses_current_closing_references_to_fetch_issues() -> None:
    current_pr = pull(7, closes=(42,))
    current_issue = issue(42, body="fresh from GitHub")
    runner = RecordingRunner(
        [
            Result(stdout=json.dumps(current_pr)),
            Result(stdout=json.dumps(closing_reference_pages(42))),
            Result(stdout=json.dumps(current_issue)),
        ]
    )

    resolved = LiveTargetResolver(read_token="read-token", runner=runner).resolve(
        REPOSITORY, claim("pull_request", "7")
    )

    assert [item["number"] for item in resolved.issues] == [42]
    assert resolved.pull_requests == (current_pr,)


def test_pr_target_fetches_current_unresolved_review_threads() -> None:
    current_pr = pull(7, closes=(42,))
    del current_pr["unresolvedThreads"]
    runner = RecordingRunner(
        [
            Result(stdout=json.dumps(current_pr)),
            Result(stdout=json.dumps(closing_reference_pages(42))),
            Result(
                stdout=json.dumps(
                    {
                        "data": {
                            "repository": {
                                "pullRequest": {
                                    "reviewThreads": {
                                        "nodes": [
                                            {"isResolved": False},
                                            {"isResolved": True},
                                        ],
                                        "pageInfo": {
                                            "hasNextPage": False,
                                            "endCursor": None,
                                        },
                                    }
                                }
                            }
                        }
                    }
                )
            ),
            Result(stdout=json.dumps(issue(42))),
        ]
    )

    resolved = LiveTargetResolver(read_token="read-token", runner=runner).resolve(
        REPOSITORY, claim("pull_request", "7")
    )

    assert resolved.pull_requests[0]["unresolvedThreads"] == 1
    assert any(
        "reviewThreads(first:100,after:$endCursor" in " ".join(command)
        for command, _env in runner.calls
    )


def test_parked_issue_fetches_current_comments_and_reactions() -> None:
    parked = issue(42, labels=("P1", "agent-session:needs-human"))
    comments = [
        {
            "id": "comment-1",
            "author": {"login": "agent-session-bot"},
            "createdAt": "2026-08-25T10:00:00Z",
            "reactions": {
                "nodes": [
                    {
                        "content": "THUMBS_UP",
                        "user": {"login": "les"},
                        "createdAt": "2026-08-25T11:30:00Z",
                    }
                ],
                "pageInfo": {"hasNextPage": False, "endCursor": None},
            },
        }
    ]
    runner = RecordingRunner(
        [
            Result(stdout=json.dumps(parked)),
            Result(
                stdout=json.dumps(
                    {
                        "data": {
                            "repository": {
                                "issue": {
                                    "comments": {
                                        "nodes": comments,
                                        "pageInfo": {
                                            "hasNextPage": False,
                                            "endCursor": None,
                                        },
                                    }
                                }
                            }
                        }
                    }
                )
            ),
            Result(stdout=json.dumps(discovery_pages())),
        ]
    )

    resolved = LiveTargetResolver(read_token="read-token", runner=runner).resolve(
        REPOSITORY, claim("issue", "42")
    )

    assert resolved.issues[0]["comments"] == comments
    assert runner.calls[1][0][1:3] == ["api", "graphql"]


def test_revision_target_finds_current_pr_by_head_sha_and_then_closing_issues() -> None:
    matching = pull(7, closes=(42,), head="wanted")
    unrelated = pull(8, closes=(99,), head="other")
    runner = RecordingRunner(
        [
            Result(stdout=json.dumps(discovery_pages(matching, unrelated))),
            Result(stdout=json.dumps(matching)),
            Result(stdout=json.dumps(closing_reference_pages(42))),
            Result(stdout=json.dumps(issue(42))),
        ]
    )

    resolved = LiveTargetResolver(read_token="read-token", runner=runner).resolve(
        REPOSITORY, claim("revision", "wanted")
    )

    assert resolved.pull_requests == (matching,)
    assert [item["number"] for item in resolved.issues] == [42]


def test_issue_pr_and_revision_targets_converge_on_the_same_current_issue() -> None:
    current_issue = issue(42)
    current_pr = pull(7, closes=(42,), head="wanted")
    runner = RecordingRunner(
        [
            Result(stdout=json.dumps(current_issue)),
            Result(stdout=json.dumps(discovery_pages(current_pr))),
            Result(stdout=json.dumps(current_pr)),
            Result(stdout=json.dumps(closing_reference_pages(42))),
            Result(stdout=json.dumps(current_pr)),
            Result(stdout=json.dumps(closing_reference_pages(42))),
            Result(stdout=json.dumps(current_issue)),
            Result(stdout=json.dumps(discovery_pages(current_pr))),
            Result(stdout=json.dumps(current_pr)),
            Result(stdout=json.dumps(closing_reference_pages(42))),
            Result(stdout=json.dumps(current_issue)),
        ]
    )
    resolver = LiveTargetResolver(read_token="read-token", runner=runner)

    results = [
        resolver.resolve(REPOSITORY, claim("issue", "42")),
        resolver.resolve(REPOSITORY, claim("pull_request", "7")),
        resolver.resolve(REPOSITORY, claim("revision", "wanted")),
    ]

    assert {item["number"] for result in results for item in result.issues} == {42}


def test_missing_and_control_plane_targets_are_non_actionable() -> None:
    runner = RecordingRunner(
        [
            Result(returncode=1, stderr="HTTP 404: Not Found"),
            Result(stdout=json.dumps({"id": "R_1", "nameWithOwner": "owner/repo"})),
            Result(stdout=json.dumps({"id": 99, "account": {"login": "owner"}})),
        ]
    )
    resolver = LiveTargetResolver(read_token="read-token", runner=runner)

    missing = resolver.resolve(REPOSITORY, claim("issue", "404"))
    repository = resolver.resolve(REPOSITORY, claim("repository", "1"))
    installation = resolver.resolve(REPOSITORY, claim("installation", "99"))

    assert missing.irrelevant_reason == "issue is missing or closed"
    assert repository.control_plane_only is True
    assert installation.control_plane_only is True


@pytest.mark.parametrize(
    ("returncode", "stderr"),
    [
        (1, "HTTP 401: Bad credentials"),
        (1, "HTTP 500: Internal Server Error"),
        (128, "transport closed unexpectedly"),
        (127, "gh: command not found"),
    ],
)
def test_unresolved_github_failures_are_transient(
    returncode: int,
    stderr: str,
) -> None:
    runner = RecordingRunner([Result(returncode=returncode, stderr=stderr)])

    with pytest.raises(GitHubTransientError):
        LiveTargetResolver(read_token="read-token", runner=runner).resolve(
            REPOSITORY,
            claim("issue", "42"),
        )


def test_only_confirmed_missing_objects_are_permanent() -> None:
    runner = RecordingRunner([Result(returncode=1, stderr="HTTP 404: Not Found")])

    resolved = LiveTargetResolver(read_token="read-token", runner=runner).resolve(
        REPOSITORY,
        claim("issue", "42"),
    )

    assert resolved.irrelevant_reason == "issue is missing or closed"
    with pytest.raises(GitHubPermanentError):
        LiveTargetResolver(read_token="read-token", runner=RecordingRunner([])).resolve(
            REPOSITORY,
            ClaimedTarget(1, "unsupported", "42", 1, "worker"),  # type: ignore[arg-type]
        )


def test_review_thread_pagination_includes_a_later_unresolved_thread() -> None:
    current_pr = pull(7, closes=(42,))
    del current_pr["unresolvedThreads"]
    pages = [
        {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {
                            "nodes": [{"isResolved": True}],
                            "pageInfo": {"hasNextPage": True, "endCursor": "one"},
                        }
                    }
                }
            }
        },
        {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {
                            "nodes": [{"isResolved": False}],
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                        }
                    }
                }
            }
        },
    ]
    runner = RecordingRunner(
        [
            Result(stdout=json.dumps(current_pr)),
            Result(stdout=json.dumps(closing_reference_pages(42))),
            Result(stdout=json.dumps(pages)),
            Result(stdout=json.dumps(issue(42))),
        ]
    )

    resolved = LiveTargetResolver(read_token="read-token", runner=runner).resolve(
        REPOSITORY,
        claim("pull_request", "7"),
    )

    assert resolved.pull_requests[0]["unresolvedThreads"] == 1
    review_calls = [
        command
        for command, _env in runner.calls
        if "reviewThreads(first:100,after:$endCursor" in " ".join(command)
    ]
    assert len(review_calls) == 1
    assert "--paginate" in review_calls[0]
    assert "--slurp" in review_calls[0]


def test_comment_and_reaction_pagination_includes_later_human_activity() -> None:
    parked = issue(42, labels=("P1", "agent-session:needs-human"))
    comment_pages = [
        {
            "data": {
                "repository": {
                    "issue": {
                        "comments": {
                            "nodes": [
                                {
                                    "id": "comment-1",
                                    "author": {"login": "agent-session"},
                                    "createdAt": "2026-08-25T10:00:00Z",
                                    "reactions": {
                                        "nodes": [],
                                        "pageInfo": {
                                            "hasNextPage": False,
                                            "endCursor": None,
                                        },
                                    },
                                }
                            ],
                            "pageInfo": {"hasNextPage": True, "endCursor": "comments-1"},
                        }
                    }
                }
            }
        },
        {
            "data": {
                "repository": {
                    "issue": {
                        "comments": {
                            "nodes": [
                                {
                                    "id": "comment-2",
                                    "author": {"login": "agent-session"},
                                    "createdAt": "2026-08-25T11:00:00Z",
                                    "reactions": {
                                        "nodes": [],
                                        "pageInfo": {
                                            "hasNextPage": True,
                                            "endCursor": "reactions-1",
                                        },
                                    },
                                }
                            ],
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                        }
                    }
                }
            }
        },
    ]
    reaction_pages = [
        {
            "data": {
                "node": {
                    "reactions": {
                        "nodes": [
                            {
                                "content": "THUMBS_UP",
                                "user": {"login": "les"},
                                "createdAt": "2026-08-25T11:30:00Z",
                            }
                        ],
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                    }
                }
            }
        }
    ]
    no_pr_pages = [
        {
            "data": {
                "repository": {
                    "pullRequests": {
                        "nodes": [],
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                    }
                }
            }
        }
    ]
    runner = RecordingRunner(
        [
            Result(stdout=json.dumps(parked)),
            Result(stdout=json.dumps(comment_pages)),
            Result(stdout=json.dumps(reaction_pages)),
            Result(stdout=json.dumps(no_pr_pages)),
        ]
    )

    resolved = LiveTargetResolver(read_token="read-token", runner=runner).resolve(
        REPOSITORY,
        claim("issue", "42"),
    )

    comments = resolved.issues[0]["comments"]
    assert isinstance(comments, list)
    assert len(comments) == 2
    later_comment = comments[1]
    assert isinstance(later_comment, dict)
    reactions = later_comment["reactions"]
    assert isinstance(reactions, dict)
    reaction_nodes = reactions["nodes"]
    assert isinstance(reaction_nodes, list)
    later_reaction = reaction_nodes[0]
    assert isinstance(later_reaction, dict)
    user = later_reaction["user"]
    assert isinstance(user, dict)
    assert user["login"] == "les"


def test_pr_discovery_pagination_finds_a_later_closing_pr() -> None:
    current_issue = issue(42)
    matching = pull(7, closes=(42,))
    discovery_pages = [
        {
            "data": {
                "repository": {
                    "pullRequests": {
                        "nodes": [
                            {
                                "number": 8,
                                "headRefOid": "other",
                                "closingIssuesReferences": {
                                    "nodes": [{"number": 99}],
                                    "pageInfo": {"hasNextPage": False},
                                },
                            }
                        ],
                        "pageInfo": {"hasNextPage": True, "endCursor": "prs-1"},
                    }
                }
            }
        },
        {
            "data": {
                "repository": {
                    "pullRequests": {
                        "nodes": [
                            {
                                "number": 7,
                                "headRefOid": "wanted",
                                "closingIssuesReferences": {
                                    "nodes": [{"number": 42}],
                                    "pageInfo": {"hasNextPage": False},
                                },
                            }
                        ],
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                    }
                }
            }
        },
    ]
    runner = RecordingRunner(
        [
            Result(stdout=json.dumps(current_issue)),
            Result(stdout=json.dumps(discovery_pages)),
            Result(stdout=json.dumps(matching)),
            Result(stdout=json.dumps(closing_reference_pages(42))),
        ]
    )

    resolved = LiveTargetResolver(read_token="read-token", runner=runner).resolve(
        REPOSITORY,
        claim("issue", "42"),
    )

    assert [item["number"] for item in resolved.pull_requests] == [7]


@pytest.mark.parametrize(
    ("target_kind", "target_key"),
    [("pull_request", "7"), ("revision", "wanted")],
)
def test_direct_pr_hydration_paginates_all_closing_issue_references(
    target_kind: str,
    target_key: str,
) -> None:
    current_pr = pull(7, closes=(42,), head="wanted")
    closing_pages = [
        {
            "data": {
                "repository": {
                    "pullRequest": {
                        "closingIssuesReferences": {
                            "nodes": [{"number": 42}],
                            "pageInfo": {
                                "hasNextPage": True,
                                "endCursor": "closing-1",
                            },
                        }
                    }
                }
            }
        },
        {
            "data": {
                "repository": {
                    "pullRequest": {
                        "closingIssuesReferences": {
                            "nodes": [{"number": 99}],
                            "pageInfo": {
                                "hasNextPage": False,
                                "endCursor": None,
                            },
                        }
                    }
                }
            }
        },
    ]
    def runner(command, **_kwargs):
        argv = [str(item) for item in command]
        if argv[1:3] == ["pr", "view"]:
            return Result(stdout=json.dumps(current_pr))
        if argv[1:3] == ["issue", "view"]:
            return Result(stdout=json.dumps(issue(int(argv[3]))))
        if argv[1:3] == ["api", "graphql"]:
            query = next(
                (item for item in argv if item.startswith("query=")), ""
            )
            if "pullRequests(first:100,after:$endCursor" in query:
                return Result(stdout=json.dumps(discovery_pages(current_pr)))
            if "closingIssuesReferences(first:100,after:$endCursor" in query:
                return Result(stdout=json.dumps(closing_pages))
        pytest.fail(f"unexpected GitHub command: {argv}")

    resolved = LiveTargetResolver(read_token="read-token", runner=runner).resolve(
        REPOSITORY,
        claim(target_kind, target_key),
    )

    assert [item["number"] for item in resolved.issues] == [42, 99]
    closing_references = resolved.pull_requests[0]["closingIssuesReferences"]
    assert isinstance(closing_references, list)
    assert all(isinstance(item, dict) for item in closing_references)
    assert [
        item["number"]
        for item in closing_references
        if isinstance(item, dict)
    ] == [42, 99]


def config(database: Path, *, claim_limit: int = 25) -> EventsConfig:
    return EventsConfig(
        database=database,
        busy_timeout_ms=50,
        claim_limit=claim_limit,
        claim_lease=timedelta(minutes=5),
        retry_base=timedelta(seconds=30),
        retry_maximum=timedelta(minutes=30),
        max_body_bytes=1024,
        delivery_retention=timedelta(days=1),
        invalidation_retention=timedelta(days=1),
        scan=ScanPolicy(timedelta(minutes=5), timedelta(minutes=15), timedelta(hours=1)),
        repositories=(REPOSITORY,),
        boards=(),
    )


def runtime(tmp_path: Path, *, claim_limit: int = 25) -> QueueRuntime:
    database = tmp_path / "events.sqlite3"
    QueueStore.migrate(database, busy_timeout_ms=50)
    store = QueueStore.open(database, busy_timeout_ms=50)
    store.register_repositories((REPOSITORY.identity,))
    assert store.acquire_scan_lease(
        1,
        worker_id="seed",
        lease_until=NOW + timedelta(minutes=1),
        now=NOW - timedelta(seconds=1),
    )
    store.finish_scan(1, worker_id="seed", succeeded=True, now=NOW)
    return QueueRuntime(config(database, claim_limit=claim_limit), store, REPOSITORY)


def context(tmp_path: Path):
    state_dir = tmp_path / "state"
    state_dir.mkdir(exist_ok=True)
    return SimpleNamespace(
        repo="owner/repo",
        repo_path=tmp_path,
        state_dir=state_dir,
        parked_log=state_dir / "parked.jsonl",
        board="",
        all_issues=False,
        max_phase_attempts=3,
        retry="",
        issue="",
        driver_bots=frozenset({"agent-session-bot"}),
        creds=Credentials(read_token="read-token"),
        clean_workspaces=False,
        workspaces_dir=None,
    )


class FakeResolver:
    def __init__(
        self,
        results: Mapping[tuple[str, str], ResolvedTarget | Exception],
    ) -> None:
        self.results = results
        self.claims: list[ClaimedTarget] = []

    def resolve(self, repository, current_claim):
        self.claims.append(current_claim)
        result = self.results[(current_claim.target_kind, current_claim.target_key)]
        if isinstance(result, Exception):
            raise result
        return result


def enqueue(current: QueueRuntime, *targets: tuple[str, str]) -> None:
    current.store.enqueue_synthetic(
        "test",
        "test",
        tuple(Invalidation(1, kind, key, "test") for kind, key in targets),  # type: ignore[arg-type]
        now=NOW,
    )


def install_resolver(monkeypatch: pytest.MonkeyPatch, resolver: FakeResolver) -> None:
    monkeypatch.setattr(events_driver, "LiveTargetResolver", lambda **_kwargs: resolver)


def test_irrelevant_and_control_plane_claims_are_acknowledged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = runtime(tmp_path)
    enqueue(current, ("issue", "404"), ("repository", "1"))
    claims = {
        ("issue", "404"): ResolvedTarget(claim("issue", "404"), (), (), (), "missing"),
        ("repository", "1"): ResolvedTarget(
            claim("repository", "1"), (), (), (), control_plane_only=True
        ),
    }
    install_resolver(monkeypatch, FakeResolver(claims))

    result = select_work(context(tmp_path), current, now=NOW, worker_id="worker")

    assert len(result.acknowledged) == 2
    assert current.store.status(now=NOW).backlog_count == 0
    assert result.selection is None


def test_housekeeping_only_unpark_is_applied_and_acknowledged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = runtime(tmp_path)
    enqueue(current, ("issue", "42"))
    current.store.upsert_watch(
        ApprovalWatch(1, 42, "human_approval_since_park", NOW - timedelta(hours=1))
    )
    parked = issue(
        42,
        labels=("P1", "agent-session:needs-human"),
        comments=({"author": {"login": "les"}, "createdAt": "2026-08-25T11:30:00Z"},),
    )
    resolver = FakeResolver(
        {("issue", "42"): ResolvedTarget(claim("issue", "42"), (parked,), (), ())}
    )
    install_resolver(monkeypatch, resolver)
    removed: list[str] = []
    monkeypatch.setattr(
        "agent_sessions.driver.agent_session_driver.park_label_remove",
        lambda number, _repo: removed.append(str(number)),
    )
    monkeypatch.setattr(
        events_driver.lifecycle,
        "authoritative_issue_is_parked",
        lambda _ctx, _number: False,
    )

    result = select_work(context(tmp_path), current, now=NOW, worker_id="worker")

    assert removed == ["42"]
    assert [item.target_key for item in result.acknowledged] == ["42"]
    assert result.selection is None
    assert current.store.list_watches(1) == ()


def test_failed_targeted_unpark_preserves_approval_watch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = runtime(tmp_path)
    enqueue(current, ("issue", "42"))
    original_watch = ApprovalWatch(
        1, 42, "human_approval_since_park", NOW - timedelta(hours=1)
    )
    current.store.upsert_watch(original_watch)
    parked = issue(
        42,
        labels=("P1", "agent-session:needs-human"),
        comments=(
            {"author": {"login": "les"}, "createdAt": "2026-08-25T11:30:00Z"},
        ),
    )
    install_resolver(
        monkeypatch,
        FakeResolver(
            {("issue", "42"): ResolvedTarget(claim("issue", "42"), (parked,), (), ())}
        ),
    )
    monkeypatch.setattr(
        "agent_sessions.driver.agent_session_driver.park_label_remove",
        lambda _number, _repo: None,
    )
    monkeypatch.setattr(
        events_driver.lifecycle,
        "authoritative_issue_is_parked",
        lambda _ctx, _number: True,
        raising=False,
    )

    result = select_work(context(tmp_path), current, now=NOW, worker_id="worker")

    assert [item.target_key for item in result.acknowledged] == ["42"]
    assert current.store.list_watches(1) == (original_watch,)


@pytest.mark.parametrize(
    "label_payload",
    [
        {},
        {"labels": None},
        {"labels": {}},
        {"labels": "not-a-list"},
        {"labels": [42]},
        {"labels": [{}]},
    ],
    ids=["missing", "null", "mapping", "string", "scalar-item", "missing-name"],
)
def test_malformed_targeted_unpark_verification_preserves_approval_watch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    label_payload: object,
) -> None:
    current = runtime(tmp_path)
    enqueue(current, ("issue", "42"))
    original_watch = ApprovalWatch(
        1, 42, "human_approval_since_park", NOW - timedelta(hours=1)
    )
    current.store.upsert_watch(original_watch)
    parked = issue(
        42,
        labels=("P1", "agent-session:needs-human"),
        comments=(
            {"author": {"login": "les"}, "createdAt": "2026-08-25T11:30:00Z"},
        ),
    )
    install_resolver(
        monkeypatch,
        FakeResolver(
            {("issue", "42"): ResolvedTarget(claim("issue", "42"), (parked,), (), ())}
        ),
    )
    monkeypatch.setattr(
        "agent_sessions.driver.agent_session_driver.park_label_remove",
        lambda _number, _repo: None,
    )
    monkeypatch.setattr(
        events_driver.lifecycle.subprocess,
        "run",
        lambda *_args, **_kwargs: Result(stdout=json.dumps(label_payload)),
    )

    result = select_work(context(tmp_path), current, now=NOW, worker_id="worker")

    assert [item.target_key for item in result.acknowledged] == ["42"]
    assert current.store.list_watches(1) == (original_watch,)


def test_current_human_reaction_after_park_triggers_unpark_housekeeping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = runtime(tmp_path)
    enqueue(current, ("issue", "42"))
    current.store.upsert_watch(
        ApprovalWatch(1, 42, "human_approval_since_park", NOW - timedelta(hours=1))
    )
    parked = issue(
        42,
        labels=("P1", "agent-session:needs-human"),
        comments=(
            {
                "author": {"login": "agent-session"},
                "createdAt": "2026-08-25T10:00:00Z",
                "reactions": {
                    "nodes": [
                        {
                            "content": "THUMBS_UP",
                            "user": {"login": "les"},
                            "createdAt": "2026-08-25T11:30:00Z",
                        }
                    ]
                },
            },
        ),
    )
    install_resolver(
        monkeypatch,
        FakeResolver(
            {("issue", "42"): ResolvedTarget(claim("issue", "42"), (parked,), (), ())}
        ),
    )
    removed: list[str] = []
    monkeypatch.setattr(
        "agent_sessions.driver.agent_session_driver.park_label_remove",
        lambda number, _repo: removed.append(str(number)),
    )
    monkeypatch.setattr(
        events_driver.lifecycle,
        "authoritative_issue_is_parked",
        lambda _ctx, _number: False,
    )

    select_work(context(tmp_path), current, now=NOW, worker_id="worker")

    assert removed == ["42"]
    assert current.store.list_watches(1) == ()


def test_transient_resolution_failure_retries_with_exponential_capped_backoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = runtime(tmp_path)
    enqueue(current, ("issue", "42"))
    first = current.store.claim_targets(
        1,
        worker_id="setup-1",
        limit=1,
        lease_until=NOW + timedelta(minutes=1),
        now=NOW,
    )[0]
    assert current.store.retry(first, error="one", next_attempt_at=NOW)
    second = current.store.claim_targets(
        1,
        worker_id="setup-2",
        limit=1,
        lease_until=NOW + timedelta(minutes=1),
        now=NOW,
    )[0]
    assert current.store.retry(second, error="two", next_attempt_at=NOW)
    install_resolver(
        monkeypatch,
        FakeResolver({("issue", "42"): GitHubTransientError("rate limited")}),
    )

    result = select_work(context(tmp_path), current, now=NOW, worker_id="worker")

    assert [item.target_key for item in result.retried] == ["42"]
    row = current.store.connection.execute(
        "SELECT retry_count,next_attempt_at FROM dirty_targets WHERE target_key='42'"
    ).fetchone()
    assert row["retry_count"] == 3
    assert row["next_attempt_at"] == "2026-08-25T12:02:00Z"


def test_claim_batch_is_bounded_and_nonselected_actionable_claims_are_released(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = runtime(tmp_path, claim_limit=2)
    enqueue(current, ("issue", "10"), ("issue", "11"), ("issue", "12"))
    responses = {
        ("issue", key): ResolvedTarget(
            claim("issue", key),
            (issue(int(key), body="<!-- agent-session:spec -->\n## Tier: auto-ok"),),
            (),
            (),
        )
        for key in ("10", "11", "12")
    }
    resolver = FakeResolver(responses)
    install_resolver(monkeypatch, resolver)
    monkeypatch.setattr(
        "agent_sessions.driver.agent_session_driver.acquire_lock", lambda *_args: True
    )

    result = select_work(context(tmp_path), current, now=NOW, worker_id="worker")

    assert len(resolver.claims) == 2
    assert result.selection is not None
    assert len(result.selection.candidates) == 1
    assert len(result.released) == 1
    assert current.store.status(now=NOW).backlog_count == 3


def test_router_priority_wins_and_git_ref_lock_is_the_final_exclusion_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = runtime(tmp_path)
    enqueue(current, ("issue", "10"), ("pull_request", "20"))
    execute_issue = issue(10, body="<!-- agent-session:spec -->\n## Tier: auto-ok")
    unblock_issue = issue(20, body="<!-- agent-session:spec -->\n## Tier: auto-ok")
    unblock_pr = pull(120, closes=(20,), unresolved=1)
    install_resolver(
        monkeypatch,
        FakeResolver(
            {
                ("issue", "10"): ResolvedTarget(
                    claim("issue", "10"), (execute_issue,), (), ()
                ),
                ("pull_request", "20"): ResolvedTarget(
                    claim("pull_request", "20"), (unblock_issue,), (unblock_pr,), ()
                ),
            }
        ),
    )
    lock_calls: list[tuple[str, str]] = []

    def acquire(number, phase, _repo_path):
        lock_calls.append((str(number), phase))
        return True

    monkeypatch.setattr("agent_sessions.driver.agent_session_driver.acquire_lock", acquire)

    result = select_work(context(tmp_path), current, now=NOW, worker_id="worker")

    assert result.selection is not None
    assert result.selection.candidates == [("20", "address_comments")]
    assert result.selected_claim is not None
    assert result.selected_claim.target_key == "20"
    assert lock_calls == [("20", "address_comments")]
    assert [item.target_key for item in result.released] == ["10"]


def test_current_board_status_can_qualify_an_issue_without_a_priority_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = runtime(tmp_path)
    enqueue(current, ("issue", "42"))
    actionable = issue(
        42,
        body="<!-- agent-session:spec -->\n## Tier: auto-ok",
        labels=(),
    )
    install_resolver(
        monkeypatch,
        FakeResolver(
            {("issue", "42"): ResolvedTarget(claim("issue", "42"), (actionable,), (), ())}
        ),
    )
    ctx = context(tmp_path)
    ctx.board = "owner/9"
    monkeypatch.setattr(
        events_driver,
        "fetch_board_items",
        lambda _board, **_kwargs: [
            {
                "id": "item-42",
                "status": "Ready",
                "priority": "",
                "content": {"number": 42},
            }
        ],
    )
    monkeypatch.setattr(
        "agent_sessions.driver.agent_session_driver.acquire_lock", lambda *_args: True
    )

    result = select_work(ctx, current, now=NOW, worker_id="worker")

    assert result.selection is not None
    assert result.selection.candidates == [("42", "execute")]
    assert result.selection.board_item_ids == {"42": "item-42"}


def test_board_read_failure_retries_board_only_claim_instead_of_acknowledging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = runtime(tmp_path)
    enqueue(current, ("issue", "42"))
    board_only = issue(
        42,
        body="<!-- agent-session:spec -->\n## Tier: auto-ok",
        labels=(),
    )
    install_resolver(
        monkeypatch,
        FakeResolver(
            {("issue", "42"): ResolvedTarget(claim("issue", "42"), (board_only,), (), ())}
        ),
    )
    ctx = context(tmp_path)
    ctx.board = "owner/9"
    monkeypatch.setattr(
        events_driver,
        "fetch_board_items",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            GitHubTransientError("board read incomplete")
        ),
        raising=False,
    )

    result = select_work(ctx, current, now=NOW, worker_id="worker")

    assert [item.target_key for item in result.retried] == ["42"]
    assert result.acknowledged == ()
    row = current.store.connection.execute(
        "SELECT retry_count,last_error FROM dirty_targets WHERE target_key='42'"
    ).fetchone()
    assert row["retry_count"] == 1
    assert row["last_error"] == "board read incomplete"


@pytest.mark.parametrize(
    "closing_result",
    [
        Result(
            stdout=json.dumps(
                {
                    "data": {
                        "repository": {
                            "pullRequest": {
                                "closingIssuesReferences": {
                                    "nodes": [{"number": 42}]
                                }
                            }
                        }
                    }
                }
            )
        ),
        Result(returncode=1, stderr="HTTP 502 while fetching closing-reference page 2"),
    ],
    ids=["missing-page-info", "later-page-failure"],
)
def test_incomplete_direct_pr_pagination_retries_without_acknowledgement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    closing_result: Result,
) -> None:
    current = runtime(tmp_path)
    enqueue(current, ("pull_request", "7"))
    current_pr = pull(7, closes=(42,))

    def runner(command, **_kwargs):
        argv = [str(item) for item in command]
        if argv[1:3] == ["pr", "view"]:
            return Result(stdout=json.dumps(current_pr))
        if argv[1:3] == ["issue", "view"]:
            return Result(
                stdout=json.dumps(
                    issue(
                        int(argv[3]),
                        body="<!-- agent-session:spec -->\n## Tier: auto-ok",
                    )
                )
            )
        if argv[1:3] == ["api", "graphql"]:
            return closing_result
        pytest.fail(f"unexpected GitHub command: {argv}")

    monkeypatch.setattr(
        events_driver,
        "LiveTargetResolver",
        lambda **_kwargs: LiveTargetResolver(
            read_token="read-token",
            runner=runner,
        ),
    )
    monkeypatch.setattr(
        "agent_sessions.driver.agent_session_driver.acquire_lock", lambda *_args: False
    )

    result = select_work(context(tmp_path), current, now=NOW, worker_id="worker")

    assert [item.target_key for item in result.retried] == ["7"]
    assert result.acknowledged == ()
    row = current.store.connection.execute(
        "SELECT retry_count,last_error FROM dirty_targets "
        "WHERE target_kind='pull_request' AND target_key='7'"
    ).fetchone()
    assert row["retry_count"] == 1
    assert row["last_error"]


def test_selected_pr_claim_is_not_released_when_it_closes_multiple_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = runtime(tmp_path)
    enqueue(current, ("pull_request", "120"))
    spec = "<!-- agent-session:spec -->\n## Tier: auto-ok"
    install_resolver(
        monkeypatch,
        FakeResolver(
            {
                ("pull_request", "120"): ResolvedTarget(
                    claim("pull_request", "120"),
                    (issue(20, body=spec), issue(21, body=spec)),
                    (pull(120, closes=(20, 21)),),
                    (),
                )
            }
        ),
    )
    monkeypatch.setattr(
        "agent_sessions.driver.agent_session_driver.acquire_lock", lambda *_args: True
    )

    result = select_work(context(tmp_path), current, now=NOW, worker_id="worker")

    assert result.selected_claim is not None
    assert result.selected_claim.target_key == "120"
    assert result.selected_claim not in result.released
    row = current.store.connection.execute(
        "SELECT lease_owner FROM dirty_targets WHERE target_kind='pull_request' AND target_key='120'"
    ).fetchone()
    assert row["lease_owner"] == "worker"


def test_selected_pr_claim_materializes_unselected_closing_issue_for_the_next_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = runtime(tmp_path)
    enqueue(current, ("pull_request", "120"))
    spec = "<!-- agent-session:spec -->\n## Tier: auto-ok"
    install_resolver(
        monkeypatch,
        FakeResolver(
            {
                ("pull_request", "120"): ResolvedTarget(
                    claim("pull_request", "120"),
                    (issue(20, body=spec), issue(21, body=spec)),
                    (pull(120, closes=(20, 21)),),
                    (),
                )
            }
        ),
    )
    monkeypatch.setattr(
        "agent_sessions.driver.agent_session_driver.acquire_lock", lambda *_args: True
    )

    first = select_work(context(tmp_path), current, now=NOW, worker_id="first")

    assert first.selection is not None
    assert first.selection.candidates == [("20", "request_review")]
    assert first.selected_claim is not None
    assert current.store.acknowledge(first.selected_claim)
    dirty = current.store.connection.execute(
        "SELECT target_kind,target_key,generation,lease_owner "
        "FROM dirty_targets ORDER BY target_kind,target_key"
    ).fetchall()
    assert [tuple(row) for row in dirty] == [("issue", "21", 1, None)]

    install_resolver(
        monkeypatch,
        FakeResolver(
            {
                ("issue", "21"): ResolvedTarget(
                    claim("issue", "21"),
                    (issue(21, body=spec),),
                    (),
                    (),
                )
            }
        ),
    )
    second = select_work(
        context(tmp_path),
        current,
        now=NOW + timedelta(seconds=1),
        worker_id="second",
    )

    assert second.selection is not None
    assert second.selection.candidates == [("21", "execute")]
    assert second.selected_claim is not None
    assert second.selected_claim.target_kind == "issue"
    assert second.selected_claim.target_key == "21"


def test_pr_sibling_materialization_coalesces_and_preserves_a_newer_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = runtime(tmp_path)
    enqueue(current, ("pull_request", "120"), ("issue", "21"))
    concurrent_claims = current.store.claim_targets(
        1,
        worker_id="concurrent",
        limit=2,
        lease_until=NOW + timedelta(minutes=1),
        now=NOW,
    )
    source_claim = next(
        item for item in concurrent_claims if item.target_kind == "pull_request"
    )
    sibling_claim = next(
        item for item in concurrent_claims if item.target_kind == "issue"
    )
    spec = "<!-- agent-session:spec -->\n## Tier: auto-ok"
    # Release only the source claim so this worker can reconcile the PR while the
    # sibling issue remains leased to a concurrent generation.
    assert current.store.release(source_claim)
    install_resolver(
        monkeypatch,
        FakeResolver(
            {
                ("pull_request", "120"): ResolvedTarget(
                    claim("pull_request", "120"),
                    (issue(20, body=spec), issue(21, body=spec)),
                    (pull(120, closes=(20, 21)),),
                    (),
                )
            }
        ),
    )
    monkeypatch.setattr(
        "agent_sessions.driver.agent_session_driver.acquire_lock", lambda *_args: True
    )

    result = select_work(context(tmp_path), current, now=NOW, worker_id="worker")

    assert result.selected_claim is not None
    row = current.store.connection.execute(
        "SELECT generation,lease_owner FROM dirty_targets "
        "WHERE target_kind='issue' AND target_key='21'"
    ).fetchone()
    assert tuple(row) == (2, None)
    assert current.store.acknowledge(sibling_claim) is False
    assert current.store.connection.execute(
        "SELECT count(*) FROM dirty_targets "
        "WHERE target_kind='issue' AND target_key='21'"
    ).fetchone()[0] == 1


def test_lock_contended_actionable_claim_is_released_without_a_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = runtime(tmp_path)
    enqueue(current, ("issue", "42"))
    actionable = issue(42, body="<!-- agent-session:spec -->\n## Tier: auto-ok")
    install_resolver(
        monkeypatch,
        FakeResolver(
            {("issue", "42"): ResolvedTarget(claim("issue", "42"), (actionable,), (), ())}
        ),
    )
    monkeypatch.setattr(
        "agent_sessions.driver.agent_session_driver.acquire_lock", lambda *_args: False
    )

    result = select_work(context(tmp_path), current, now=NOW, worker_id="worker")

    assert result.selection is None
    assert [item.target_key for item in result.released] == ["42"]
    assert current.store.claim_targets(
        1,
        worker_id="next",
        limit=1,
        lease_until=NOW + timedelta(minutes=1),
        now=NOW,
    )
