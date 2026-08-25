"""Fresh GitHub reads for resolving dirty target identities."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from typing import Any, Callable, cast

from .models import ClaimedTarget, JSONValue, RepositoryConfig


class GitHubError(RuntimeError):
    """A live target could not be resolved from GitHub."""


class GitHubTransientError(GitHubError):
    """A target read may succeed on a later queue attempt."""


class GitHubPermanentError(GitHubError):
    """A target read failed in a way retrying cannot repair."""


class _GitHubNotFound(GitHubError):
    pass


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
_UNRESOLVED_THREADS_QUERY = """
query($owner:String!,$repo:String!,$pr:Int!,$endCursor:String){
  repository(owner:$owner,name:$repo){
    pullRequest(number:$pr){
      reviewThreads(first:100,after:$endCursor){
        nodes { isResolved }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""
_ISSUE_REACTIONS_QUERY = """
query($owner:String!,$repo:String!,$issue:Int!,$endCursor:String){
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
"""
_COMMENT_REACTIONS_QUERY = """
query($comment:ID!,$endCursor:String){
  node(id:$comment){
    ... on IssueComment {
      reactions(first:100,after:$endCursor){
        nodes { content user { login } createdAt }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""
_OPEN_PR_DISCOVERY_QUERY = """
query($owner:String!,$repo:String!,$endCursor:String){
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
"""
_CLOSING_ISSUES_QUERY = """
query($owner:String!,$repo:String!,$pr:Int!,$endCursor:String){
  repository(owner:$owner,name:$repo){
    pullRequest(number:$pr){
      closingIssuesReferences(first:100,after:$endCursor){
        nodes { number }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""


class LiveTargetResolver:
    """Resolve a queue identity using only current GitHub responses."""

    def __init__(
        self,
        *,
        read_token: str,
        runner: Callable[..., Any] | None = None,
    ) -> None:
        self.read_token = read_token
        self.runner = subprocess.run if runner is None else runner

    def _read(
        self,
        command: list[str],
        *,
        missing_is_permanent: bool = False,
        token: str | None = None,
    ) -> JSONValue:
        env = dict(os.environ)
        credential = self.read_token if token is None else token
        env["GH_TOKEN"] = credential
        env["GITHUB_TOKEN"] = credential
        try:
            result = self.runner(command, capture_output=True, text=True, env=env)
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
        query: str,
        *,
        subject: str,
        variables: tuple[tuple[str, str], ...],
        end_cursor: str = "",
    ) -> list[dict[str, JSONValue]]:
        command = [
            "gh",
            "api",
            "graphql",
            "--paginate",
            "--slurp",
            "-f",
            f"query={query}",
        ]
        for key, variable_value in variables:
            command.extend(["-F", f"{key}={variable_value}"])
        if end_cursor:
            command.extend(["-F", f"endCursor={end_cursor}"])
        response = self._read(command)
        raw_pages: list[JSONValue] = (
            response if isinstance(response, list) else [response]
        )
        pages: list[dict[str, JSONValue]] = []
        for raw_page in raw_pages:
            page = self._dict(raw_page, subject)
            if page.get("errors"):
                raise GitHubTransientError(f"GitHub returned incomplete {subject} data")
            pages.append(page)
        if not pages:
            raise GitHubTransientError(f"GitHub returned no {subject} pages")
        return pages

    def _connection_nodes(
        self,
        pages: list[dict[str, JSONValue]],
        *,
        path: tuple[str, ...],
        subject: str,
    ) -> list[dict[str, JSONValue]]:
        nodes: list[dict[str, JSONValue]] = []
        last_page_info: dict[str, JSONValue] | None = None
        for page in pages:
            current: JSONValue = page
            for key in path:
                current = self._dict(current, subject).get(key)
            connection = self._dict(current, subject)
            nodes.extend(self._list(connection.get("nodes"), subject))
            last_page_info = self._dict(connection.get("pageInfo"), subject)
        if last_page_info is None or last_page_info.get("hasNextPage") is not False:
            raise GitHubTransientError(f"GitHub returned incomplete {subject} pagination")
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
            try:
                self._read(
                    ["gh", "api", "installation/repositories"],
                    missing_is_permanent=True,
                )
            except _GitHubNotFound:
                return ResolvedTarget(claim, (), (), (), "installation is unavailable")
            return ResolvedTarget(claim, (), (), (), control_plane_only=True)

        raise GitHubPermanentError(f"unsupported target kind: {claim.target_kind}")


def fetch_board_items(
    board: str,
    *,
    token: str,
    runner: Callable[..., Any] | None = None,
) -> list[dict[str, JSONValue]]:
    """Read a complete board snapshot without converting failures to emptiness."""
    if "/" not in board:
        raise GitHubTransientError("board identifier is malformed")
    owner, number = board.split("/", 1)
    resolver = LiveTargetResolver(read_token=token, runner=runner)
    value = resolver._dict(
        resolver._read(
            [
                "gh",
                "project",
                "item-list",
                number,
                "--owner",
                owner,
                "--format",
                "json",
                "--limit",
                "10000",
            ],
            token=token,
        ),
        "board",
    )
    return resolver._list(value.get("items"), "board items")
