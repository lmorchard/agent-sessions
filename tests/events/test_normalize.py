from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_sessions.events.models import EventsConfig, RepositoryConfig, RepositoryIdentity, ScanPolicy

MISSING = object()


def config() -> EventsConfig:
    from datetime import timedelta

    return EventsConfig(
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
        repositories=(
            RepositoryConfig(RepositoryIdentity(1, "owner", "repo", installation_id=10)),
            RepositoryConfig(RepositoryIdentity(2, "other", "repo", installation_id=10)),
        ),
        boards=(),
    )


def payload(repository_id: int = 1, **values: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"repository": {"id": repository_id, "owner": {"login": "owner"}, "name": "repo"}}
    result.update(values)
    return result


@pytest.mark.parametrize(
    ("event_type", "action", "body", "kind", "key"),
    [
        ("issues", "opened", {"issue": {"number": 11}}, "issue", "11"),
        ("issue_comment", "created", {"issue": {"number": 12}}, "issue", "12"),
        ("pull_request", "synchronize", {"pull_request": {"number": 13}}, "pull_request", "13"),
        ("pull_request_review", "submitted", {"pull_request": {"number": 14}}, "pull_request", "14"),
        ("pull_request_review_comment", "edited", {"pull_request": {"number": 15}}, "pull_request", "15"),
        ("pull_request_review_thread", "resolved", {"pull_request": {"number": 16}}, "pull_request", "16"),
        ("check_run", "completed", {"check_run": {"pull_requests": [{"number": 17}]}}, "pull_request", "17"),
        ("check_suite", "requested", {"check_suite": {"pull_requests": [{"number": 18}]}}, "pull_request", "18"),
        ("status", "", {"sha": "abc123"}, "revision", "abc123"),
        ("installation_target", "renamed", {"installation": {"id": 10}}, "installation", "10"),
    ],
)
def test_selected_event_families_normalize_to_identity_targets(
    event_type: str, action: str, body: dict[str, Any], kind: str, key: str,
) -> None:
    from agent_sessions.events.normalize import normalize_delivery

    delivery = normalize_delivery(event_type, payload(action=action, **body), config())

    assert delivery.disposition == "accepted"
    assert [(item.repository_id, item.target_kind, item.target_key) for item in delivery.invalidations] == [(1, kind, key)]


@pytest.mark.parametrize(
    ("event_type", "action"),
    [
        ("issues", "edited"), ("issues", "transferred"), ("issues", "deleted"), ("issues", "closed"), ("issues", "reopened"), ("issues", "labeled"), ("issues", "unlabeled"),
        ("issue_comment", "edited"), ("issue_comment", "deleted"),
        ("pull_request", "opened"), ("pull_request", "edited"), ("pull_request", "closed"), ("pull_request", "reopened"), ("pull_request", "converted_to_draft"), ("pull_request", "ready_for_review"), ("pull_request", "review_requested"), ("pull_request", "review_request_removed"),
        ("pull_request_review", "edited"), ("pull_request_review", "dismissed"),
        ("pull_request_review_comment", "created"), ("pull_request_review_comment", "deleted"),
        ("pull_request_review_thread", "unresolved"),
        ("check_run", "created"), ("check_run", "rerequested"), ("check_run", "requested_action"),
        ("check_suite", "rerequested"), ("check_suite", "completed"),
        ("installation", "created"), ("installation", "deleted"), ("installation", "suspend"), ("installation", "unsuspend"), ("installation", "new_permissions_accepted"),
        ("installation_repositories", "added"), ("installation_repositories", "removed"),
        ("meta", "deleted"),
    ],
)
def test_all_selected_actions_are_not_unknown(event_type: str, action: str) -> None:
    from agent_sessions.events.normalize import normalize_delivery

    body: dict[str, Any] = {"action": action}
    if event_type in {"issues", "issue_comment"}:
        body["issue"] = {"number": 1}
    elif event_type.startswith("pull_request"):
        body["pull_request"] = {"number": 1}
    elif event_type.startswith("check_"):
        body[event_type] = {"pull_requests": [], "head_sha": "head"}
    elif event_type == "installation":
        body.update({"installation": {"id": 10}, "repositories": [{"id": 1}]})
    elif event_type == "installation_repositories":
        body.update({"installation": {"id": 10}, "repositories_added": [{"id": 1}], "repositories_removed": []})
    elif event_type == "meta":
        body = {"action": action}

    assert normalize_delivery(event_type, payload(**body), config()).disposition == "accepted"


def test_issue_comment_uses_pull_request_identity_when_present() -> None:
    from agent_sessions.events.normalize import normalize_delivery

    delivery = normalize_delivery("issue_comment", payload(action="created", issue={"number": 12, "pull_request": {}}), config())

    assert [(item.target_kind, item.target_key) for item in delivery.invalidations] == [("pull_request", "12")]


def test_check_delivery_creates_one_target_for_each_pull_request() -> None:
    from agent_sessions.events.normalize import normalize_delivery

    delivery = normalize_delivery("check_run", payload(action="completed", check_run={"pull_requests": [{"number": 17}, {"number": 18}]}), config())

    assert [(item.target_kind, item.target_key) for item in delivery.invalidations] == [("pull_request", "17"), ("pull_request", "18")]


def test_check_delivery_falls_back_to_head_revision() -> None:
    from agent_sessions.events.normalize import normalize_delivery

    delivery = normalize_delivery("check_suite", payload(action="completed", check_suite={"pull_requests": [], "head_sha": "abc123"}), config())

    assert [(item.target_kind, item.target_key) for item in delivery.invalidations] == [("revision", "abc123")]


def test_installation_delivery_filters_repositories_to_configured_ids() -> None:
    from agent_sessions.events.normalize import normalize_delivery

    delivery = normalize_delivery("installation", payload(action="created", installation={"id": 10}, repositories=[{"id": 1}, {"id": 99}]), config())

    assert [(item.repository_id, item.target_kind, item.target_key) for item in delivery.invalidations] == [(1, "installation", "10"), (1, "repository", "1")]


def test_installation_repositories_uses_added_and_removed_allowed_repositories() -> None:
    from agent_sessions.events.normalize import normalize_delivery

    delivery = normalize_delivery("installation_repositories", payload(action="added", installation={"id": 10}, repositories_added=[{"id": 1}], repositories_removed=[{"id": 2}, {"id": 99}]), config())

    assert [(item.repository_id, item.target_kind, item.target_key) for item in delivery.invalidations] == [(1, "installation", "10"), (1, "repository", "1"), (2, "repository", "2")]


@pytest.mark.parametrize(("event_type", "body"), [("ping", {}), ("meta", {"action": "deleted"})])
def test_ping_and_meta_are_accepted_without_workflow_targets(event_type: str, body: dict[str, Any]) -> None:
    from agent_sessions.events.normalize import normalize_delivery

    delivery = normalize_delivery(event_type, payload(**body), config())

    assert delivery.disposition == "accepted" and delivery.invalidations == ()


def test_unknown_event_and_action_are_retained_as_ignored() -> None:
    from agent_sessions.events.normalize import normalize_delivery

    assert normalize_delivery("fork", payload(), config()).disposition == "ignored_unknown_event"
    assert normalize_delivery("issues", payload(action="assigned", issue={"number": 1}), config()).disposition == "ignored_unknown_action"


@pytest.mark.parametrize(
    ("event_type", "body", "action", "disposition"),
    [
        ("status", {"sha": "abc123"}, MISSING, "accepted"),
        ("ping", {}, MISSING, "accepted"),
        ("issues", {"issue": {"number": 1}}, MISSING, "malformed"),
        ("issues", {"issue": {"number": 1}}, None, "malformed"),
        ("issues", {"issue": {"number": 1}}, 1, "malformed"),
        ("issues", {"issue": {"number": 1}}, {}, "malformed"),
        ("issues", {"issue": {"number": 1}}, "assigned", "ignored_unknown_action"),
    ],
)
def test_action_presence_and_type_are_distinct_from_unknown_actions(
    event_type: str, body: dict[str, Any], action: object, disposition: str,
) -> None:
    from agent_sessions.events.normalize import normalize_delivery

    value = payload(**body)
    if action is not MISSING:
        value["action"] = action

    assert normalize_delivery(event_type, value, config()).disposition == disposition


def test_malformed_supported_identity_has_no_targets() -> None:
    from agent_sessions.events.normalize import normalize_delivery

    delivery = normalize_delivery("issues", payload(action="opened", issue={"number": "wrong"}), config())

    assert delivery.disposition == "malformed" and delivery.invalidations == ()


def test_unconfigured_repository_is_ignored_before_target_mapping() -> None:
    from agent_sessions.events.normalize import normalize_delivery

    delivery = normalize_delivery("issues", payload(99, action="opened", issue={"number": 1}), config())

    assert delivery.repository_id == 99 and delivery.disposition == "ignored_unconfigured" and delivery.invalidations == ()
