"""Fresh GitHub reads for resolving dirty target identities."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Callable, cast

from agent_sessions.driver import credentials

from .models import (
    ApprovalWatch,
    BoardConfig,
    ClaimedTarget,
    JSONValue,
    PollFailure,
    ProjectItemProjection,
    RepositoryConfig,
)


class GitHubError(RuntimeError):
    """A live target could not be resolved from GitHub."""


class GitHubTransientError(GitHubError):
    """A target read may succeed on a later queue attempt."""


class GitHubReadStopped(GitHubTransientError):
    """A read was not started because service shutdown was requested."""


class GitHubPermanentError(GitHubError):
    """A target read failed in a way retrying cannot repair."""


class ProjectFieldsIncomplete(GitHubTransientError):
    """The Project was readable but its complete field list was not."""


class _GitHubNotFound(GitHubError):
    pass


class GraphQLOperation(StrEnum):
    """The event queries that the strong GitHub fake dispatches exactly."""

    OPEN_PULL_REQUEST_DISCOVERY = "OpenPullRequestDiscovery"
    CLOSING_ISSUES = "ClosingIssues"
    UNRESOLVED_THREADS = "UnresolvedThreads"
    ISSUE_REACTIONS = "IssueReactions"
    COMMENT_REACTIONS = "CommentReactions"
    PROJECT_ITEMS = "ProjectItems"
    PROJECT_FIELDS = "ProjectFields"


@dataclass(frozen=True)
class GraphQLQuery:
    operation: GraphQLOperation
    document: str


@dataclass(frozen=True)
class ResolvedTarget:
    claim: ClaimedTarget
    issues: tuple[dict[str, JSONValue], ...]
    pull_requests: tuple[dict[str, JSONValue], ...]
    board_items: tuple[dict[str, JSONValue], ...]
    irrelevant_reason: str = ""
    control_plane_only: bool = False


_ISSUE_FIELDS = "number,title,body,labels,url,updatedAt,state,comments"
_PR_FIELDS = (
    "number,title,body,headRefName,headRefOid,url,state,closingIssuesReferences,"
    "mergeStateStatus,mergeable,reviewDecision,reviewRequests,reviews,"
    "statusCheckRollup,commits,comments"
)
_UNRESOLVED_THREADS_QUERY = GraphQLQuery(GraphQLOperation.UNRESOLVED_THREADS, """
query UnresolvedThreads($owner:String!,$repo:String!,$pr:Int!,$endCursor:String){
  repository(owner:$owner,name:$repo){
    pullRequest(number:$pr){
      reviewThreads(first:100,after:$endCursor){
        nodes { isResolved }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
""")
_ISSUE_REACTIONS_QUERY = GraphQLQuery(GraphQLOperation.ISSUE_REACTIONS, """
query IssueReactions($owner:String!,$repo:String!,$issue:Int!,$endCursor:String){
  repository(owner:$owner,name:$repo){
    issue(number:$issue){
      comments(first:100,after:$endCursor){
        nodes {
          id
          author { login }
          createdAt
          reactions(first:100){
            nodes { content user { login } createdAt }
            pageInfo { hasNextPage endCursor }
          }
        }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
""")
_COMMENT_REACTIONS_QUERY = GraphQLQuery(GraphQLOperation.COMMENT_REACTIONS, """
query CommentReactions($comment:ID!,$endCursor:String){
  node(id:$comment){
    ... on IssueComment {
      reactions(first:100,after:$endCursor){
        nodes { content user { login } createdAt }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
""")
_OPEN_PR_DISCOVERY_QUERY = GraphQLQuery(GraphQLOperation.OPEN_PULL_REQUEST_DISCOVERY, """
query OpenPullRequestDiscovery($owner:String!,$repo:String!,$endCursor:String){
  repository(owner:$owner,name:$repo){
    pullRequests(first:100,after:$endCursor,states:OPEN){
      nodes {
        number
        headRefOid
        closingIssuesReferences(first:100){
          nodes { number }
          pageInfo { hasNextPage endCursor }
        }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
}
""")
_CLOSING_ISSUES_QUERY = GraphQLQuery(GraphQLOperation.CLOSING_ISSUES, """
query ClosingIssues($owner:String!,$repo:String!,$pr:Int!,$endCursor:String){
  repository(owner:$owner,name:$repo){
    pullRequest(number:$pr){
      closingIssuesReferences(first:100,after:$endCursor){
        nodes { number }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
""")
_PROJECT_ITEMS_QUERY = GraphQLQuery(GraphQLOperation.PROJECT_ITEMS, """
query ProjectItems($owner:String!,$number:Int!,$endCursor:String){
  user(login:$owner){
    projectV2(number:$number){
      id
      items(first:100,after:$endCursor){
        nodes {
          id
          type
          content {
            __typename
            ... on Issue {
              number
              title
              repository { databaseId nameWithOwner }
            }
            ... on PullRequest {
              number
              title
              repository { databaseId nameWithOwner }
            }
            ... on DraftIssue { title }
          }
          fieldValues(first:100){
            nodes {
              __typename
              ... on ProjectV2ItemFieldSingleSelectValue {
                name
                field { ... on ProjectV2SingleSelectField { name } }
              }
            }
            pageInfo { hasNextPage endCursor }
          }
        }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
  rateLimit { limit cost remaining resetAt }
}
""")
_PROJECT_FIELDS_QUERY = GraphQLQuery(GraphQLOperation.PROJECT_FIELDS, """
query ProjectFields($owner:String!,$number:Int!,$endCursor:String){
  user(login:$owner){
    projectV2(number:$number){
      id
      fields(first:100,after:$endCursor){
        totalCount
        nodes {
          __typename
          ... on ProjectV2FieldCommon { id name }
          ... on ProjectV2SingleSelectField { options { id name } }
        }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
""")
_GRAPHQL_CONNECTION_PATHS = {
    GraphQLOperation.UNRESOLVED_THREADS: (
        "data",
        "repository",
        "pullRequest",
        "reviewThreads",
    ),
    GraphQLOperation.ISSUE_REACTIONS: (
        "data",
        "repository",
        "issue",
        "comments",
    ),
    GraphQLOperation.COMMENT_REACTIONS: ("data", "node", "reactions"),
    GraphQLOperation.OPEN_PULL_REQUEST_DISCOVERY: (
        "data",
        "repository",
        "pullRequests",
    ),
    GraphQLOperation.CLOSING_ISSUES: (
        "data",
        "repository",
        "pullRequest",
        "closingIssuesReferences",
    ),
    GraphQLOperation.PROJECT_ITEMS: ("data", "user", "projectV2", "items"),
    GraphQLOperation.PROJECT_FIELDS: ("data", "user", "projectV2", "fields"),
}
_SUPPORTED_PROJECT_ITEM_TYPES = frozenset({"ISSUE", "PULL_REQUEST"})
_UNSUPPORTED_PROJECT_ITEM_TYPES = frozenset({"DRAFT_ISSUE", "REDACTED"})


@dataclass(frozen=True)
class CompleteProjectSnapshot:
    board_key: str
    items: tuple[ProjectItemProjection, ...]
    fetched_at: datetime


@dataclass(frozen=True)
class ApprovalPredicateObservation:
    watch: ApprovalWatch
    value: bool


class LiveTargetResolver:
    """Resolve a queue identity using only current GitHub responses."""

    def __init__(
        self,
        *,
        read_token: str,
        runner: Callable[..., Any] | None = None,
        stop_requested: Callable[[], bool] | None = None,
    ) -> None:
        self.read_token = read_token
        self.runner = subprocess.run if runner is None else runner
        self.stop_requested = (lambda: False) if stop_requested is None else stop_requested

    def _read(
        self,
        command: list[str],
        *,
        missing_is_permanent: bool = False,
        token: str | None = None,
    ) -> JSONValue:
        if self.stop_requested():
            raise GitHubReadStopped("GitHub read stopped before starting a subprocess")
        env = dict(os.environ)
        credential = self.read_token if token is None else token
        if credential:
            env["GH_TOKEN"] = credential
            env["GITHUB_TOKEN"] = credential
        try:
            result = self.runner(command, capture_output=True, text=True, env=env, timeout=60)
        except subprocess.TimeoutExpired as error:
            raise GitHubTransientError("GitHub read timed out") from error
        except OSError as error:
            raise GitHubTransientError(f"GitHub command could not start: {error}") from error
        if result.returncode != 0:
            message = str(result.stderr or result.stdout or "GitHub read failed").strip()
            lowered = message.lower()
            confirmed_missing = "404" in lowered and (
                "http" in lowered or "not found" in lowered
            )
            if missing_is_permanent and confirmed_missing:
                raise _GitHubNotFound(message)
            raise GitHubTransientError(message)
        try:
            value = cast(JSONValue, json.loads(result.stdout))
        except (TypeError, json.JSONDecodeError) as error:
            raise GitHubTransientError("GitHub returned malformed JSON") from error
        if isinstance(value, dict) and value.get("errors"):
            raise GitHubTransientError("GitHub returned an incomplete GraphQL response")
        return value

    @staticmethod
    def _dict(value: JSONValue, subject: str) -> dict[str, JSONValue]:
        if not isinstance(value, dict):
            raise GitHubTransientError(f"GitHub returned malformed {subject} data")
        return value

    @staticmethod
    def _list(value: JSONValue, subject: str) -> list[dict[str, JSONValue]]:
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            raise GitHubTransientError(f"GitHub returned malformed {subject} data")
        return value  # type: ignore[return-value]

    def _graphql_pages(
        self,
        query: GraphQLQuery,
        *,
        subject: str,
        variables: tuple[tuple[str, str], ...],
        end_cursor: str = "",
    ) -> list[dict[str, JSONValue]]:
        pages: list[dict[str, JSONValue]] = []
        cursor = end_cursor
        while True:
            command = _graphql_command(query, variables, end_cursor=cursor)
            page = self._dict(self._read(command), subject)
            if page.get("errors"):
                raise GitHubTransientError(f"GitHub returned incomplete {subject} data")
            pages.append(page)

            current: JSONValue = page
            for key in _GRAPHQL_CONNECTION_PATHS[query.operation]:
                current = self._dict(current, subject).get(key)
            connection = self._dict(current, subject)
            page_info = self._dict(connection.get("pageInfo"), subject)
            if page_info.get("hasNextPage") is False:
                break
            next_cursor = page_info.get("endCursor")
            if (
                page_info.get("hasNextPage") is not True
                or not isinstance(next_cursor, str)
                or not next_cursor
            ):
                raise GitHubTransientError(
                    f"GitHub returned incomplete {subject} pagination"
                )
            cursor = next_cursor
        return pages

    def _connection_nodes(
        self,
        pages: list[dict[str, JSONValue]],
        *,
        path: tuple[str, ...],
        subject: str,
    ) -> list[dict[str, JSONValue]]:
        nodes: list[dict[str, JSONValue]] = []
        for index, page in enumerate(pages):
            current: JSONValue = page
            for key in path:
                current = self._dict(current, subject).get(key)
            connection = self._dict(current, subject)
            nodes.extend(self._list(connection.get("nodes"), subject))
            page_info = self._dict(connection.get("pageInfo"), subject)
            terminal = index == len(pages) - 1
            if terminal:
                if page_info.get("hasNextPage") is not False:
                    raise GitHubTransientError(
                        f"GitHub returned incomplete {subject} pagination"
                    )
            elif (
                page_info.get("hasNextPage") is not True
                or not isinstance(page_info.get("endCursor"), str)
                or not page_info.get("endCursor")
            ):
                raise GitHubTransientError(
                    f"GitHub returned malformed {subject} pagination"
                )
        return nodes

    def _issue(self, repository: RepositoryConfig, number: str) -> dict[str, JSONValue] | None:
        identity = repository.identity
        try:
            value = self._read(
                [
                    "gh",
                    "issue",
                    "view",
                    number,
                    "--repo",
                    f"{identity.owner}/{identity.name}",
                    "--json",
                    _ISSUE_FIELDS,
                ],
                missing_is_permanent=True,
            )
        except _GitHubNotFound:
            return None
        issue = self._dict(value, "issue")
        if issue.get("state") != "OPEN":
            return None
        labels = issue.get("labels")
        if isinstance(labels, list) and any(
            isinstance(label, dict)
            and label.get("name") == "agent-session:needs-human"
            for label in labels
        ):
            issue = {
                **issue,
                "comments": cast(JSONValue, self._issue_comments(repository, number)),
            }
        return issue

    def _issue_comments(
        self,
        repository: RepositoryConfig,
        number: str,
    ) -> list[dict[str, JSONValue]]:
        identity = repository.identity
        pages = self._graphql_pages(
            _ISSUE_REACTIONS_QUERY,
            subject="issue comments",
            variables=(
                ("owner", identity.owner),
                ("repo", identity.name),
                ("issue", number),
            ),
        )
        comments = self._connection_nodes(
            pages,
            path=("data", "repository", "issue", "comments"),
            subject="issue comments",
        )
        hydrated: list[dict[str, JSONValue]] = []
        for comment in comments:
            reactions = self._dict(comment.get("reactions"), "comment reactions")
            reaction_nodes = self._list(reactions.get("nodes"), "comment reactions")
            page_info = self._dict(reactions.get("pageInfo"), "comment reactions")
            if page_info.get("hasNextPage") is True:
                comment_id = str(comment.get("id", ""))
                cursor = str(page_info.get("endCursor", ""))
                if not comment_id or not cursor:
                    raise GitHubTransientError("GitHub returned incomplete reaction pagination")
                reaction_pages = self._graphql_pages(
                    _COMMENT_REACTIONS_QUERY,
                    subject="comment reactions",
                    variables=(("comment", comment_id),),
                    end_cursor=cursor,
                )
                reaction_nodes.extend(
                    self._connection_nodes(
                        reaction_pages,
                        path=("data", "node", "reactions"),
                        subject="comment reactions",
                    )
                )
            elif page_info.get("hasNextPage") is not False:
                raise GitHubTransientError("GitHub returned incomplete reaction pagination")
            hydrated.append(
                {
                    **comment,
                    "reactions": cast(JSONValue, {**reactions, "nodes": reaction_nodes}),
                }
            )
        return hydrated

    def _with_unresolved_threads(
        self,
        repository: RepositoryConfig,
        pull_request: dict[str, JSONValue],
    ) -> dict[str, JSONValue]:
        if "unresolvedThreads" in pull_request:
            return pull_request
        identity = repository.identity
        number = str(pull_request.get("number", ""))
        pages = self._graphql_pages(
            _UNRESOLVED_THREADS_QUERY,
            subject="review threads",
            variables=(
                ("owner", identity.owner),
                ("repo", identity.name),
                ("pr", number),
            ),
        )
        threads = self._connection_nodes(
            pages,
            path=("data", "repository", "pullRequest", "reviewThreads"),
            subject="review threads",
        )
        return {
            **pull_request,
            "unresolvedThreads": sum(
                1 for thread in threads if thread.get("isResolved") is False
            ),
        }

    def _closing_issues(
        self,
        repository: RepositoryConfig,
        pull_request: dict[str, JSONValue],
    ) -> list[dict[str, JSONValue]]:
        connection = self._dict(
            pull_request.get("closingIssuesReferences"), "closing issue references"
        )
        nodes = self._list(connection.get("nodes"), "closing issue references")
        page_info = self._dict(connection.get("pageInfo"), "closing issue references")
        if page_info.get("hasNextPage") is False:
            return nodes
        identity = repository.identity
        number = str(pull_request.get("number", ""))
        cursor = str(page_info.get("endCursor", ""))
        if not number or not cursor:
            raise GitHubTransientError("GitHub returned incomplete closing issue pagination")
        pages = self._graphql_pages(
            _CLOSING_ISSUES_QUERY,
            subject="closing issue references",
            variables=(
                ("owner", identity.owner),
                ("repo", identity.name),
                ("pr", number),
            ),
            end_cursor=cursor,
        )
        nodes.extend(
            self._connection_nodes(
                pages,
                path=(
                    "data",
                    "repository",
                    "pullRequest",
                    "closingIssuesReferences",
                ),
                subject="closing issue references",
            )
        )
        return nodes

    def _open_prs(self, repository: RepositoryConfig) -> list[dict[str, JSONValue]]:
        identity = repository.identity
        pages = self._graphql_pages(
            _OPEN_PR_DISCOVERY_QUERY,
            subject="open pull request discovery",
            variables=(("owner", identity.owner), ("repo", identity.name)),
        )
        discovered = self._connection_nodes(
            pages,
            path=("data", "repository", "pullRequests"),
            subject="open pull request discovery",
        )
        return [
            {
                **pull_request,
                "closingIssuesReferences": cast(
                    JSONValue,
                    self._closing_issues(repository, pull_request),
                ),
            }
            for pull_request in discovered
        ]

    def _current_closing_issues(
        self,
        repository: RepositoryConfig,
        number: str,
    ) -> list[dict[str, JSONValue]]:
        identity = repository.identity
        pages = self._graphql_pages(
            _CLOSING_ISSUES_QUERY,
            subject="closing issue references",
            variables=(
                ("owner", identity.owner),
                ("repo", identity.name),
                ("pr", number),
            ),
        )
        return self._connection_nodes(
            pages,
            path=(
                "data",
                "repository",
                "pullRequest",
                "closingIssuesReferences",
            ),
            subject="closing issue references",
        )

    def _pr(self, repository: RepositoryConfig, number: str) -> dict[str, JSONValue] | None:
        identity = repository.identity
        try:
            value = self._read(
                [
                    "gh",
                    "pr",
                    "view",
                    number,
                    "--repo",
                    f"{identity.owner}/{identity.name}",
                    "--json",
                    _PR_FIELDS,
                ],
                missing_is_permanent=True,
            )
        except _GitHubNotFound:
            return None
        pull_request = self._dict(value, "pull request")
        if pull_request.get("state") != "OPEN":
            return None
        pull_request = {
            **pull_request,
            "closingIssuesReferences": cast(
                JSONValue,
                self._current_closing_issues(repository, number),
            ),
        }
        return self._with_unresolved_threads(repository, pull_request)

    @staticmethod
    def _closing_numbers(pull_request: dict[str, JSONValue]) -> tuple[str, ...]:
        references = pull_request.get("closingIssuesReferences")
        if not isinstance(references, list):
            return ()
        return tuple(
            str(reference["number"])
            for reference in references
            if isinstance(reference, dict) and reference.get("number") is not None
        )

    def _issues_for_prs(
        self,
        repository: RepositoryConfig,
        pull_requests: list[dict[str, JSONValue]],
    ) -> tuple[dict[str, JSONValue], ...]:
        issues: dict[str, dict[str, JSONValue]] = {}
        for pull_request in pull_requests:
            for number in self._closing_numbers(pull_request):
                if number in issues:
                    continue
                issue = self._issue(repository, number)
                if issue is not None:
                    issues[number] = issue
        return tuple(issues.values())

    def resolve(
        self,
        repository: RepositoryConfig,
        claim: ClaimedTarget,
    ) -> ResolvedTarget:
        if claim.target_kind == "issue":
            issue = self._issue(repository, claim.target_key)
            if issue is None:
                return ResolvedTarget(claim, (), (), (), "issue is missing or closed")
            issue_pull_requests = tuple(
                hydrated
                for pull_request in self._open_prs(repository)
                if claim.target_key in self._closing_numbers(pull_request)
                if (hydrated := self._pr(repository, str(pull_request.get("number", ""))))
            )
            return ResolvedTarget(claim, (issue,), issue_pull_requests, ())

        if claim.target_kind == "pull_request":
            pull_request = self._pr(repository, claim.target_key)
            if pull_request is None:
                return ResolvedTarget(claim, (), (), (), "pull request is missing or closed")
            issues = self._issues_for_prs(repository, [pull_request])
            if not issues:
                return ResolvedTarget(
                    claim,
                    (),
                    (pull_request,),
                    (),
                    "pull request has no current closing issue",
                )
            return ResolvedTarget(claim, issues, (pull_request,), ())

        if claim.target_kind == "revision":
            revision_pull_requests = [
                hydrated
                for pull_request in self._open_prs(repository)
                if pull_request.get("headRefOid") == claim.target_key
                if (hydrated := self._pr(repository, str(pull_request.get("number", ""))))
            ]
            if not revision_pull_requests:
                return ResolvedTarget(claim, (), (), (), "revision has no current open pull request")
            issues = self._issues_for_prs(repository, revision_pull_requests)
            if not issues:
                return ResolvedTarget(
                    claim,
                    (),
                    tuple(revision_pull_requests),
                    (),
                    "revision has no current closing issue",
                )
            return ResolvedTarget(claim, issues, tuple(revision_pull_requests), ())

        identity = repository.identity
        if claim.target_kind == "repository":
            try:
                self._read(
                    ["gh", "api", f"repos/{identity.owner}/{identity.name}"],
                    missing_is_permanent=True,
                )
            except _GitHubNotFound:
                return ResolvedTarget(claim, (), (), (), "repository is unavailable")
            return ResolvedTarget(claim, (), (), (), control_plane_only=True)

        if claim.target_kind == "installation":
            return ResolvedTarget(
                claim,
                (),
                (),
                (),
                "installation topology is not reconciled by the static read credential",
                control_plane_only=True,
            )

        raise GitHubPermanentError(f"unsupported target kind: {claim.target_kind}")


def _graphql_command(
    query: GraphQLQuery,
    variables: tuple[tuple[str, str], ...],
    *,
    end_cursor: str = "",
) -> list[str]:
    command = ["gh", "api", "graphql", "-f", f"query={query.document}"]
    for key, value in variables:
        command.extend(["-F", f"{key}={value}"])
    if end_cursor:
        command.extend(["-F", f"endCursor={end_cursor}"])
    return command


def project_items_command(board: str) -> list[str]:
    """Build the first direct-GraphQL item query for a Project."""
    if "/" not in board:
        raise ValueError("board identifier is malformed")
    owner, number = board.split("/", 1)
    return _graphql_command(
        _PROJECT_ITEMS_QUERY,
        (("owner", owner), ("number", number)),
    )


def fetch_board_items(
    board: str,
    *,
    token: str,
    runner: Callable[..., Any] | None = None,
    stop_requested: Callable[[], bool] | None = None,
) -> list[dict[str, JSONValue]]:
    """Read a complete board snapshot without converting failures to emptiness."""
    if "/" not in board:
        raise GitHubTransientError("board identifier is malformed")
    owner, number = board.split("/", 1)
    resolver = LiveTargetResolver(
        read_token=token,
        runner=runner,
        stop_requested=stop_requested,
    )
    pages = resolver._graphql_pages(
        _PROJECT_ITEMS_QUERY,
        subject="project items",
        variables=(("owner", owner), ("number", number)),
    )
    raw_items = resolver._connection_nodes(
        pages,
        path=_GRAPHQL_CONNECTION_PATHS[GraphQLOperation.PROJECT_ITEMS],
        subject="project items",
    )
    items: list[dict[str, JSONValue]] = []
    for raw_item in raw_items:
        item = _driver_board_item(resolver, raw_item)
        if item is not None:
            items.append(item)
    return items


def _driver_board_item(
    resolver: LiveTargetResolver,
    raw_item: dict[str, JSONValue],
) -> dict[str, JSONValue] | None:
    """Convert one GraphQL Project item to the driver's established input shape."""
    item_id = raw_item.get("id")
    item_type = raw_item.get("type")
    if not isinstance(item_id, str) or not item_id or not isinstance(item_type, str):
        raise GitHubTransientError("GitHub returned malformed project item identity")
    if item_type == "REDACTED":
        return None
    content = resolver._dict(raw_item.get("content"), "project item content")
    typename = content.get("__typename")
    title = content.get("title")
    if not isinstance(typename, str) or not isinstance(title, str):
        raise GitHubTransientError("GitHub returned malformed project item content")
    if item_type == "DRAFT_ISSUE":
        if typename != "DraftIssue":
            raise GitHubTransientError("GitHub returned inconsistent project item content")
        return {
            "id": item_id,
            "title": title,
            "content": {"type": "DraftIssue", "title": title},
        }
    if item_type not in _SUPPORTED_PROJECT_ITEM_TYPES:
        raise GitHubTransientError(f"GitHub returned unknown project item type: {item_type}")
    expected_typename = "Issue" if item_type == "ISSUE" else "PullRequest"
    repository = resolver._dict(content.get("repository"), "project item repository")
    number = content.get("number")
    repository_name = repository.get("nameWithOwner")
    if (
        typename != expected_typename
        or not isinstance(number, int)
        or isinstance(number, bool)
        or not isinstance(repository_name, str)
    ):
        raise GitHubTransientError("GitHub returned inconsistent project item content")
    field_values = resolver._dict(raw_item.get("fieldValues"), "project field values")
    page_info = resolver._dict(field_values.get("pageInfo"), "project field pagination")
    if page_info.get("hasNextPage") is not False:
        raise GitHubTransientError("GitHub returned incomplete project field pagination")
    status: JSONValue = None
    priority: JSONValue = None
    for field_value in resolver._list(field_values.get("nodes"), "project field values"):
        if field_value.get("__typename") != "ProjectV2ItemFieldSingleSelectValue":
            continue
        field = resolver._dict(field_value.get("field"), "project field")
        field_name = field.get("name")
        value_name = field_value.get("name")
        if not isinstance(field_name, str) or not isinstance(value_name, str):
            raise GitHubTransientError("GitHub returned malformed project field data")
        if field_name == "Status":
            status = value_name
        elif field_name == "Priority":
            priority = value_name
    return {
        "id": item_id,
        "title": title,
        "status": status,
        "priority": priority,
        "content": {
            "type": typename,
            "number": number,
            "title": title,
            "repository": repository_name,
        },
    }


def fetch_project_fields(
    board: str,
    *,
    token: str,
    runner: Callable[..., Any] | None = None,
) -> dict[str, JSONValue]:
    """Read a complete Project field list through direct GraphQL."""
    if "/" not in board:
        raise GitHubTransientError("board identifier is malformed")
    owner, number = board.split("/", 1)
    resolver = LiveTargetResolver(read_token=token, runner=runner)
    pages = resolver._graphql_pages(
        _PROJECT_FIELDS_QUERY,
        subject="project fields",
        variables=(("owner", owner), ("number", number)),
    )
    fields = resolver._connection_nodes(
        pages,
        path=_GRAPHQL_CONNECTION_PATHS[GraphQLOperation.PROJECT_FIELDS],
        subject="project fields",
    )
    project_ids: set[str] = set()
    total_counts: set[int] = set()
    for page in pages:
        data = resolver._dict(page.get("data"), "project fields")
        user = resolver._dict(data.get("user"), "project owner")
        project = resolver._dict(user.get("projectV2"), "project")
        project_id = project.get("id")
        connection = resolver._dict(project.get("fields"), "project fields")
        total_count = connection.get("totalCount")
        if (
            not isinstance(project_id, str)
            or not project_id
            or not isinstance(total_count, int)
            or isinstance(total_count, bool)
        ):
            raise GitHubTransientError("GitHub returned malformed project field metadata")
        project_ids.add(project_id)
        total_counts.add(total_count)
    if len(project_ids) != 1:
        raise GitHubTransientError("GitHub returned incomplete project field metadata")
    if total_counts != {len(fields)}:
        raise ProjectFieldsIncomplete("GitHub returned incomplete project field metadata")
    for field in fields:
        if not isinstance(field.get("id"), str) or not isinstance(field.get("name"), str):
            raise GitHubTransientError("GitHub returned malformed project field")
    return {
        "id": next(iter(project_ids)),
        "fields": cast(JSONValue, fields),
        "totalCount": len(fields),
    }


def _project_item_projection(
    resolver: LiveTargetResolver,
    board: BoardConfig,
    raw_item: dict[str, JSONValue],
    *,
    fetched_at: datetime,
) -> ProjectItemProjection | None:
    item_node_id = raw_item.get("id")
    if not isinstance(item_node_id, str) or not item_node_id:
        raise PollFailure("GitHub returned a project item without a stable node ID")
    item_type = raw_item.get("type")
    if not isinstance(item_type, str):
        raise PollFailure("GitHub returned a project item without a valid type")
    if (
        item_type not in _SUPPORTED_PROJECT_ITEM_TYPES
        and item_type not in _UNSUPPORTED_PROJECT_ITEM_TYPES
    ):
        raise PollFailure(f"GitHub returned an unknown project item type: {item_type}")

    field_values = resolver._dict(raw_item.get("fieldValues"), "project field values")
    field_page_info = resolver._dict(
        field_values.get("pageInfo"), "project field pagination"
    )
    if "hasNextPage" not in field_page_info or "endCursor" not in field_page_info:
        raise PollFailure("GitHub returned malformed project field pagination")
    field_end_cursor = field_page_info["endCursor"]
    if (
        field_page_info["hasNextPage"] is not False
        or not (field_end_cursor is None or isinstance(field_end_cursor, str))
    ):
        raise PollFailure("GitHub returned incomplete project field pagination")
    field_nodes = resolver._list(field_values.get("nodes"), "project field values")

    raw_content = raw_item.get("content")
    if item_type == "REDACTED":
        if raw_content is not None:
            raise PollFailure("GitHub returned inconsistent unsupported project item content")
        return None
    content = resolver._dict(raw_content, "project item content")
    if item_type == "DRAFT_ISSUE":
        if content.get("__typename") != "DraftIssue":
            raise PollFailure("GitHub returned inconsistent unsupported project item content")
        return None
    expected_typename = "Issue" if item_type == "ISSUE" else "PullRequest"
    if content.get("__typename") != expected_typename:
        raise PollFailure("GitHub returned inconsistent project item content")
    repository = resolver._dict(content.get("repository"), "project item repository")
    repository_id = repository.get("databaseId")
    repository_name = repository.get("nameWithOwner")
    content_number = content.get("number")
    if (
        not isinstance(repository_id, int)
        or isinstance(repository_id, bool)
        or repository_id <= 0
        or not isinstance(repository_name, str)
        or "/" not in repository_name
        or not isinstance(content_number, int)
        or isinstance(content_number, bool)
        or content_number <= 0
    ):
        raise PollFailure("GitHub returned unstable project item coordinates")

    status: str | None = None
    priority: str | None = None
    for field_value in field_nodes:
        if field_value.get("__typename") != "ProjectV2ItemFieldSingleSelectValue":
            continue
        field = resolver._dict(field_value.get("field"), "project field")
        field_name = field.get("name")
        value_name = field_value.get("name")
        if not isinstance(field_name, str) or not isinstance(value_name, str):
            raise PollFailure("GitHub returned malformed project field data")
        if field_name == "Status":
            status = value_name
        elif field_name == "Priority":
            priority = value_name

    if repository_id not in board.repository_ids:
        return None
    return ProjectItemProjection(
        board.key,
        item_node_id,
        repository_id,
        "issue" if item_type == "ISSUE" else "pull_request",
        content_number,
        status,
        priority,
        fetched_at,
    )


def fetch_project_items(
    board: BoardConfig,
    token: str,
    *,
    runner: Callable[..., Any] | None = None,
    now: datetime | None = None,
    stop_requested: Callable[[], bool] | None = None,
) -> CompleteProjectSnapshot:
    """Fetch and validate one complete Projects V2 routing projection."""
    fetched_at = datetime.now(UTC) if now is None else now
    resolver = LiveTargetResolver(
        read_token=token,
        runner=runner,
        stop_requested=stop_requested,
    )
    try:
        pages = resolver._graphql_pages(
            _PROJECT_ITEMS_QUERY,
            subject="project items",
            variables=(("owner", board.owner), ("number", str(board.number))),
        )
        projections: list[ProjectItemProjection] = []
        item_ids: set[str] = set()
        for index, page in enumerate(pages):
            data = resolver._dict(page.get("data"), "project response")
            rate_limit = resolver._dict(data.get("rateLimit"), "GraphQL rate limit")
            remaining = rate_limit.get("remaining")
            if (
                not isinstance(remaining, int)
                or isinstance(remaining, bool)
                or remaining <= 0
            ):
                raise PollFailure("GitHub GraphQL rate limit is exhausted or malformed")
            user = resolver._dict(data.get("user"), "project owner")
            project = resolver._dict(user.get("projectV2"), "project")
            items = resolver._dict(project.get("items"), "project items")
            page_info = resolver._dict(items.get("pageInfo"), "project pagination")
            if "hasNextPage" not in page_info or "endCursor" not in page_info:
                raise PollFailure("GitHub returned malformed project pagination")
            has_next = page_info["hasNextPage"]
            end_cursor = page_info["endCursor"]
            if not (end_cursor is None or isinstance(end_cursor, str)):
                raise PollFailure("GitHub returned malformed project pagination")
            terminal = index == len(pages) - 1
            if terminal:
                if has_next is not False:
                    raise PollFailure("GitHub returned incomplete project pagination")
            elif has_next is not True or not isinstance(end_cursor, str) or not end_cursor:
                raise PollFailure("GitHub returned malformed project pagination")
            for raw_item in resolver._list(items.get("nodes"), "project items"):
                projection = _project_item_projection(
                    resolver,
                    board,
                    raw_item,
                    fetched_at=fetched_at,
                )
                if projection is None:
                    continue
                if projection.item_node_id in item_ids:
                    raise PollFailure("GitHub returned a duplicate project item")
                item_ids.add(projection.item_node_id)
                projections.append(projection)
    except (PollFailure, GitHubReadStopped):
        raise
    except GitHubError as error:
        raise PollFailure(str(error)) from error
    return CompleteProjectSnapshot(board.key, tuple(projections), fetched_at)


def _github_timestamp(value: JSONValue, subject: str) -> datetime:
    if not isinstance(value, str):
        raise PollFailure(f"GitHub returned an undated {subject}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise PollFailure(f"GitHub returned a malformed {subject} timestamp") from error
    if parsed.tzinfo is None:
        raise PollFailure(f"GitHub returned a timezone-free {subject} timestamp")
    return parsed


def _human_actor_after(
    actor: JSONValue,
    created_at: JSONValue,
    parked_at: datetime,
    bot_logins: frozenset[str],
    *,
    subject: str,
) -> bool:
    if actor is None:
        return False
    if not isinstance(actor, dict):
        raise PollFailure(f"GitHub returned a malformed {subject} actor")
    login = actor.get("login")
    if login is None:
        return False
    if not isinstance(login, str):
        raise PollFailure(f"GitHub returned a malformed {subject} login")
    if credentials.is_bot_login(login, known_bots=set(bot_logins)):
        return False
    if parked_at.tzinfo is None:
        raise PollFailure("approval watch parked_at must be timezone-aware")
    return _github_timestamp(created_at, subject) > parked_at


def _approval_predicate(
    resolver: LiveTargetResolver,
    comments: list[dict[str, JSONValue]],
    watch: ApprovalWatch,
    bot_logins: frozenset[str],
) -> bool:
    for comment in comments:
        if _human_actor_after(
            comment.get("author"),
            comment.get("createdAt"),
            watch.parked_at,
            bot_logins,
            subject="comment",
        ):
            return True
        reactions = resolver._dict(comment.get("reactions"), "comment reactions")
        for reaction in resolver._list(reactions.get("nodes"), "comment reactions"):
            content = reaction.get("content")
            if not isinstance(content, str):
                raise PollFailure("GitHub returned a reaction without content")
            if content != "THUMBS_UP":
                continue
            if _human_actor_after(
                reaction.get("user"),
                reaction.get("createdAt"),
                watch.parked_at,
                bot_logins,
                subject="reaction",
            ):
                return True
    return False


def fetch_approval_predicates(
    repository: RepositoryConfig,
    watches: tuple[ApprovalWatch, ...],
    token: str,
    bot_logins: frozenset[str],
    *,
    runner: Callable[..., Any] | None = None,
    stop_requested: Callable[[], bool] | None = None,
) -> tuple[ApprovalPredicateObservation, ...]:
    """Resolve only active approval watches for one repository."""
    resolver = LiveTargetResolver(
        read_token=token,
        runner=runner,
        stop_requested=stop_requested,
    )
    observations: list[ApprovalPredicateObservation] = []
    try:
        for watch in watches:
            if watch.repository_id != repository.identity.id:
                raise PollFailure("approval watch belongs to a different repository")
            if watch.predicate != "human_approval_since_park":
                raise PollFailure(f"unsupported approval predicate: {watch.predicate}")
            comments = resolver._issue_comments(repository, str(watch.issue_number))
            observations.append(
                ApprovalPredicateObservation(
                    watch,
                    _approval_predicate(resolver, comments, watch, bot_logins),
                )
            )
    except (PollFailure, GitHubReadStopped):
        raise
    except GitHubError as error:
        raise PollFailure(str(error)) from error
    return tuple(observations)
