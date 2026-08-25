"""Pure, identity-only normalization of selected GitHub webhook events."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from .models import EventsConfig, Invalidation, JSONValue, NormalizedDelivery, TargetKind

_ACTIONS = {
    "issues": {"opened", "edited", "transferred", "deleted", "closed", "reopened", "labeled", "unlabeled"},
    "issue_comment": {"created", "edited", "deleted"},
    "pull_request": {"opened", "edited", "closed", "reopened", "synchronize", "converted_to_draft", "ready_for_review", "review_requested", "review_request_removed"},
    "pull_request_review": {"submitted", "edited", "dismissed"},
    "pull_request_review_comment": {"created", "edited", "deleted"},
    "pull_request_review_thread": {"resolved", "unresolved"},
    "check_run": {"created", "rerequested", "completed", "requested_action"},
    "check_suite": {"requested", "rerequested", "completed"},
    "status": {""},
    "installation": {"created", "deleted", "suspend", "unsuspend", "new_permissions_accepted"},
    "installation_repositories": {"added", "removed"},
    "installation_target": {"renamed"},
    "ping": {""},
    "meta": {"deleted"},
}
_PR_EVENTS = {"pull_request", "pull_request_review", "pull_request_review_comment", "pull_request_review_thread"}


def _mapping(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None


def _positive(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _result(event_type: str, action: str, repository_id: int | None, disposition: str, invalidations: tuple[Invalidation, ...] = (), diagnostic: Mapping[str, JSONValue] | None = None) -> NormalizedDelivery:
    return NormalizedDelivery(event_type, action, repository_id, disposition, invalidations, diagnostic or {})


def _diagnostic(payload: Mapping[str, JSONValue]) -> Mapping[str, JSONValue]:
    repository = _mapping(payload.get("repository"))
    if repository is None:
        return {}
    owner = _mapping(repository.get("owner"))
    result: dict[str, JSONValue] = {}
    login = None if owner is None else owner.get("login")
    if isinstance(login, str):
        result["repository_owner"] = login
    name = repository.get("name")
    if isinstance(name, str):
        result["repository_name"] = name
    return result


def _number(payload: Mapping[str, JSONValue], field: str) -> int | None:
    item = _mapping(payload.get(field))
    return None if item is None else _positive(item.get("number"))


def _invalidation(repository_id: int, kind: str, key: int | str, event_type: str, action: str) -> Invalidation:
    return Invalidation(repository_id, cast(TargetKind, kind), str(key), f"{event_type}:{action}")


def _check_targets(event_type: str, action: str, payload: Mapping[str, JSONValue], repository_id: int) -> tuple[Invalidation, ...] | None:
    check = _mapping(payload.get(event_type))
    if check is None:
        return None
    pull_requests = check.get("pull_requests")
    if not isinstance(pull_requests, list):
        return None
    targets: list[Invalidation] = []
    for item in pull_requests:
        pull_request = _mapping(item)
        number = None if pull_request is None else _positive(pull_request.get("number"))
        if number is None:
            return None
        targets.append(_invalidation(repository_id, "pull_request", number, event_type, action))
    if targets:
        return tuple(targets)
    head_sha = _text(check.get("head_sha"))
    return None if head_sha is None else (_invalidation(repository_id, "revision", head_sha, event_type, action),)


def _installation_id(payload: Mapping[str, JSONValue]) -> int | None:
    installation = _mapping(payload.get("installation"))
    return None if installation is None else _positive(installation.get("id"))


def _configured_repositories(payload: Mapping[str, JSONValue], field: str, configured_ids: set[int]) -> tuple[int, ...] | None:
    values = payload.get(field)
    if not isinstance(values, list):
        return None
    ids: list[int] = []
    for value in values:
        item = _mapping(value)
        identifier = None if item is None else _positive(item.get("id"))
        if identifier is None:
            return None
        if identifier in configured_ids and identifier not in ids:
            ids.append(identifier)
    return tuple(ids)


def normalize_delivery(event_type: str, payload: Mapping[str, JSONValue], config: EventsConfig) -> NormalizedDelivery:
    """Map a verified delivery into opaque current-state invalidation identities."""
    repository = _mapping(payload.get("repository"))
    repository_id = None if repository is None else _positive(repository.get("id"))
    diagnostic = _diagnostic(payload)
    if repository_id is None:
        return _result(event_type, "", None, "malformed", diagnostic=diagnostic)

    if "action" in payload and not isinstance(payload["action"], str):
        return _result(event_type, "", repository_id, "malformed", diagnostic=diagnostic)
    action = payload.get("action", "")
    assert isinstance(action, str)

    configured = {item.identity.id for item in config.repositories}
    if repository_id not in configured:
        return _result(event_type, action, repository_id, "ignored_unconfigured", diagnostic=diagnostic)
    if event_type not in _ACTIONS:
        return _result(event_type, action, repository_id, "ignored_unknown_event", diagnostic=diagnostic)
    if "action" not in payload and event_type not in {"status", "ping"}:
        return _result(event_type, action, repository_id, "malformed", diagnostic=diagnostic)
    if action not in _ACTIONS[event_type]:
        return _result(event_type, action, repository_id, "ignored_unknown_action", diagnostic=diagnostic)

    if event_type in {"ping", "meta"}:
        return _result(event_type, action, repository_id, "accepted", diagnostic=diagnostic)
    targets: tuple[Invalidation, ...] | None
    if event_type == "issues":
        number = _number(payload, "issue")
        targets = None if number is None else (_invalidation(repository_id, "issue", number, event_type, action),)
    elif event_type == "issue_comment":
        issue = _mapping(payload.get("issue"))
        number = None if issue is None else _positive(issue.get("number"))
        kind = "pull_request" if issue is not None and "pull_request" in issue else "issue"
        targets = None if number is None else (_invalidation(repository_id, kind, number, event_type, action),)
    elif event_type in _PR_EVENTS:
        number = _number(payload, "pull_request")
        targets = None if number is None else (_invalidation(repository_id, "pull_request", number, event_type, action),)
    elif event_type in {"check_run", "check_suite"}:
        targets = _check_targets(event_type, action, payload, repository_id)
    elif event_type == "status":
        sha = _text(payload.get("sha"))
        targets = None if sha is None else (_invalidation(repository_id, "revision", sha, event_type, action),)
    else:
        installation_id = _installation_id(payload)
        if installation_id is None:
            targets = None
        elif event_type == "installation_target":
            targets = (_invalidation(repository_id, "installation", installation_id, event_type, action),)
        else:
            fields = ("repositories",) if event_type == "installation" else ("repositories_added", "repositories_removed")
            repository_ids: list[int] = []
            for field in fields:
                selected = _configured_repositories(payload, field, configured)
                if selected is None:
                    targets = None
                    break
                repository_ids.extend(identifier for identifier in selected if identifier not in repository_ids)
            else:
                targets = (_invalidation(repository_id, "installation", installation_id, event_type, action),) + tuple(
                    _invalidation(identifier, "repository", identifier, event_type, action) for identifier in repository_ids
                )
    if targets is None:
        return _result(event_type, action, repository_id, "malformed", diagnostic=diagnostic)
    return _result(event_type, action, repository_id, "accepted", targets, diagnostic)
