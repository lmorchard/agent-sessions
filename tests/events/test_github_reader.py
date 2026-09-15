"""Frozen acceptance checks for the two defects found in `_read`, the GitHub read chokepoint.

Both were reachable, neither was caught by the suite, and both are asserted here against
real captured GitHub output rather than against the shape the code happened to expect.

**The not-found predicate spoke one dialect of two.** `gh api` prints `HTTP 404`, but
`gh issue view` / `gh pr view` resolve through GraphQL and print no status code at all --
so a predicate keyed on "404" made `_GitHubNotFound` unreachable from the two call sites
that reach for an issue or a pull request. A deleted or transferred target came back
transient and its queue entry retried forever instead of draining. The existing fixture
fed the REST shape to an issue lookup, which is why the gap survived.

**The credential scrub was computed and discarded.** `_read` bases the child environment
on `dict(os.environ)`, and installing the token only when one is present means *absent*
resolved to *inherit whatever the operator has* -- possibly the write token. The whole
point of `credentials.driver_env` popping those variables is that a missing read token
fails closed, and the test below asserts the child environment, which is the only place
that is observable.
"""

from __future__ import annotations

import json

from agent_sessions.driver import credentials
from agent_sessions.events.github import LiveTargetResolver, _is_confirmed_missing

#: Captured live from `gh issue view 999999 --repo lmorchard/agent-sessions`.
GRAPHQL_MISSING = (
    "GraphQL: Could not resolve to an issue or pull request with the number of "
    "999999. (repository.issue)"
)
#: Captured live from `gh api repos/lmorchard/agent-sessions/issues/999999`.
REST_MISSING = "gh: Not Found (HTTP 404)"


class CapturingRunner:
    """Answers any command successfully and keeps the environment it was handed."""

    def __init__(self) -> None:
        self.env: dict[str, str] | None = None

    def __call__(self, command, **kwargs):  # noqa: ANN001, ANN003
        self.env = dict(kwargs["env"])

        class Completed:
            returncode = 0
            stdout = "{}"
            stderr = ""

        return Completed()


def test_graphql_not_found_is_a_confirmed_missing_target() -> None:
    assert _is_confirmed_missing(GRAPHQL_MISSING.lower()) is True


def test_rest_not_found_is_still_a_confirmed_missing_target() -> None:
    """The dialect that already worked has to keep working."""
    assert _is_confirmed_missing(REST_MISSING.lower()) is True


def test_a_transient_failure_is_not_read_as_missing() -> None:
    """The predicate has to be able to answer no, or it would drain live targets."""
    for message in (
        "error connecting to api.github.com",
        "gh: api rate limit exceeded",
        "graphql: something went wrong while executing your query",
        "http 500: internal server error",
    ):
        assert _is_confirmed_missing(message) is False, message


def test_missing_issue_raises_not_found_through_the_real_call_path(monkeypatch) -> None:
    """End to end through `_read`, in the dialect `gh issue view` actually produces."""
    from agent_sessions.events.github import _GitHubNotFound

    class Failing:
        def __call__(self, command, **kwargs):  # noqa: ANN001, ANN003
            class Completed:
                returncode = 1
                stdout = ""
                stderr = GRAPHQL_MISSING

            return Completed()

    resolver = LiveTargetResolver(read_token="read-token", runner=Failing())
    try:
        resolver._read(["gh", "issue", "view", "999999"], missing_is_permanent=True)
    except _GitHubNotFound:
        return
    except Exception as error:  # noqa: BLE001
        raise AssertionError(f"expected _GitHubNotFound, got {type(error).__name__}") from error
    raise AssertionError("expected _GitHubNotFound, got no exception")


def test_absent_read_credential_scrubs_the_inherited_token(monkeypatch) -> None:
    """Fail closed: no read token must mean no token, not the operator's ambient one."""
    for var in credentials.AGENT_TOKEN_VARS:
        monkeypatch.setenv(var, "AMBIENT-WRITE-TOKEN")
    runner = CapturingRunner()

    LiveTargetResolver(read_token="", runner=runner)._read(["gh", "issue", "view", "1"])

    assert runner.env is not None
    for var in credentials.AGENT_TOKEN_VARS:
        assert var not in runner.env, f"{var} leaked into the child environment"


def test_present_read_credential_replaces_the_inherited_token(monkeypatch) -> None:
    for var in credentials.AGENT_TOKEN_VARS:
        monkeypatch.setenv(var, "AMBIENT-WRITE-TOKEN")
    runner = CapturingRunner()

    LiveTargetResolver(read_token="READ-ONLY", runner=runner)._read(["gh", "issue", "view", "1"])

    assert runner.env is not None
    for var in credentials.AGENT_TOKEN_VARS:
        assert runner.env[var] == "READ-ONLY"


def test_a_supplied_environment_is_used_as_given(monkeypatch) -> None:
    """The env came from `credentials.*_env`, which already decided what belongs."""
    for var in credentials.AGENT_TOKEN_VARS:
        monkeypatch.setenv(var, "AMBIENT-WRITE-TOKEN")
    runner = CapturingRunner()

    LiveTargetResolver(
        env={"GH_TOKEN": "BOARD-TOKEN", "GITHUB_TOKEN": "BOARD-TOKEN", "PATH": "/usr/bin"},
        runner=runner,
    )._read(["gh", "api", "graphql"])

    assert runner.env is not None
    for var in credentials.AGENT_TOKEN_VARS:
        assert runner.env[var] == "BOARD-TOKEN"
    assert runner.env["PATH"] == "/usr/bin"


def test_a_supplied_environments_absences_are_honoured(monkeypatch) -> None:
    """This is the case `driver/board.py` produces when no read token is configured.

    `credentials.driver_env` pops the token variables to fail closed. Flattening that
    environment to a bare token string lost the distinction between "no token" and
    "empty token", and rebuilding from `os.environ` reinstated the operator's ambient
    credential -- possibly the write token. A supplied environment is now passed
    through, so an absence stays an absence.
    """
    for var in credentials.AGENT_TOKEN_VARS:
        monkeypatch.setenv(var, "AMBIENT-WRITE-TOKEN")
    runner = CapturingRunner()

    scrubbed = credentials.driver_env(dict(__import__("os").environ), credentials.Credentials())
    assert all(var not in scrubbed for var in credentials.AGENT_TOKEN_VARS), (
        "precondition: driver_env with no read token must scrub"
    )

    LiveTargetResolver(env=scrubbed, runner=runner)._read(["gh", "api", "graphql"])

    assert runner.env is not None
    for var in credentials.AGENT_TOKEN_VARS:
        assert var not in runner.env, f"{var} leaked into the child environment"


def test_env_with_token_installs_and_removes() -> None:
    base = {"GH_TOKEN": "AMBIENT", "GITHUB_TOKEN": "AMBIENT", "PATH": "/bin"}

    installed = credentials.env_with_token(base, "READ-ONLY")
    removed = credentials.env_with_token(base, "")

    assert all(installed[var] == "READ-ONLY" for var in credentials.AGENT_TOKEN_VARS)
    assert all(var not in removed for var in credentials.AGENT_TOKEN_VARS)
    assert installed["PATH"] == removed["PATH"] == "/bin"
    assert base["GH_TOKEN"] == "AMBIENT", "must not mutate the caller's environment"


def test_board_fetchers_pass_the_environment_through(monkeypatch) -> None:
    """The regression that started this: an env reaching the child unflattened."""
    from agent_sessions.events import github

    for var in credentials.AGENT_TOKEN_VARS:
        monkeypatch.setenv(var, "AMBIENT-WRITE-TOKEN")
    seen: list[dict[str, str]] = []

    def runner(command, **kwargs):  # noqa: ANN001, ANN003
        seen.append(dict(kwargs["env"]))

        class Completed:
            returncode = 0
            stdout = '{"data": {"repositoryOwner": {"projectV2": {"fields": {"nodes": [], '
            stdout += '"pageInfo": {"hasNextPage": false, "endCursor": null}}}}}}'
            stderr = ""

        return Completed()

    try:
        github.fetch_project_fields("owner/9", env={"PATH": "/bin"}, runner=runner)
    except Exception:  # noqa: BLE001 -- the payload shape is not what is under test
        pass

    assert seen, "the fetcher never invoked the runner"
    for var in credentials.AGENT_TOKEN_VARS:
        assert var not in seen[0], f"{var} leaked past an environment that omitted it"


# --- GraphQL variables: -f for strings, -F only for Int ------------------------------
#
# `gh`'s two flags are not interchangeable and each is wrong for the other's type.
# Verified live against the API in both directions:
#
#     -F s=12345  against String!  ->  Could not coerce value 12345 to String
#     -f s=12345  against String!  ->  accepted
#     -f n=9      against Int!     ->  Could not coerce value "9" to Int
#     -F n=9      against Int!     ->  accepted
#
# Everything used to go out as `-F`, the typed flag, which coerces a numeric-looking
# value to a number. `owner/2024` is a valid login, so an all-digits owner broke every
# GraphQL read for that repository while the `gh issue view --repo` paths kept working.


def _flag_for(document: str, name: str) -> str:
    from agent_sessions.events.github import _graphql_variable_flag

    return _graphql_variable_flag(document, name)


DOCUMENT = (
    "query Thing($owner:String!,$repo:String!,$pr:Int!,$comment:ID!,$endCursor:String){x}"
)


def test_string_and_id_variables_use_the_untyped_flag() -> None:
    for name in ("owner", "repo", "comment", "endCursor"):
        assert _flag_for(DOCUMENT, name) == "-f", name


def test_int_variables_use_the_typed_flag() -> None:
    """`-F` has to stay for these: `-f n=9` against `Int!` is rejected by the API."""
    assert _flag_for(DOCUMENT, "pr") == "-F"
    assert _flag_for("query Q($number:Int!){x}", "number") == "-F"
    assert _flag_for("query Q($issue:Int!){x}", "issue") == "-F"


def test_an_undeclared_variable_falls_back_to_the_untyped_flag() -> None:
    """The safe direction: GitHub reports an unused variable, rather than silent coercion."""
    assert _flag_for(DOCUMENT, "unheard_of") == "-f"


def test_a_numeric_looking_owner_is_still_sent_as_a_string() -> None:
    """The regression, at the level of the built command."""
    from agent_sessions.events.github import _PROJECT_ITEMS_QUERY, _graphql_command

    command = _graphql_command(
        _PROJECT_ITEMS_QUERY, (("owner", "2024"), ("number", "9")), end_cursor="CUR"
    )

    assert command[command.index("owner=2024") - 1] == "-f"
    assert command[command.index("number=9") - 1] == "-F"
    assert command[command.index("endCursor=CUR") - 1] == "-f"


def test_the_flag_is_read_from_the_document_not_a_list_of_names() -> None:
    """A name list beside the queries would be a second source of truth to drift."""
    assert _flag_for("query Q($owner:Int!){x}", "owner") == "-F"
    assert _flag_for("query Q($pr:String!){x}", "pr") == "-f"


# --- boards must work for an organization owner, not only a user ---------------------
#
# Both project queries rooted at `user(login:$owner)` while `events/config.py` accepts
# any owner. Verified live: `user(login:"cli")` returns `{"user": null}` with a NOT_FOUND
# error, so an org-owned board degraded silently -- `fetch_board_json` logged UNREADABLE
# and selection fell back to priority labels, `get_board_metadata` returned None so
# `mark_board_in_progress` no-opped, and the Projects poller failed every interval. The
# `gh project --owner` path this replaced handled both owner types.
#
# GraphQL cannot switch its root field on a value, so the queries now root at
# `repositoryOwner`, which returns the `RepositoryOwner` interface, and spread a fragment
# typed on `ProjectV2Owner`. Both User and Organization implement both interfaces, so one
# document serves either owner with no duplicated selection set. Verified live against
# both a user login and an organization login.


def test_project_queries_are_owner_type_agnostic() -> None:
    from agent_sessions.events.github import (
        _PROJECT_FIELDS_QUERY,
        _PROJECT_ITEMS_QUERY,
    )

    for query in (_PROJECT_ITEMS_QUERY, _PROJECT_FIELDS_QUERY):
        document = query.document
        assert "repositoryOwner(login:$owner)" in document, query.operation
        assert "on ProjectV2Owner" in document, query.operation
        assert "user(login:$owner)" not in document, query.operation


def test_the_project_connection_paths_match_the_query_root() -> None:
    """The path walks the response; if it disagrees with the root, every read fails."""
    from agent_sessions.events.github import (
        _GRAPHQL_CONNECTION_PATHS,
        GraphQLOperation,
    )

    assert _GRAPHQL_CONNECTION_PATHS[GraphQLOperation.PROJECT_ITEMS] == (
        "data",
        "repositoryOwner",
        "projectV2",
        "items",
    )
    assert _GRAPHQL_CONNECTION_PATHS[GraphQLOperation.PROJECT_FIELDS] == (
        "data",
        "repositoryOwner",
        "projectV2",
        "fields",
    )


def test_an_organization_shaped_response_is_read_the_same_way() -> None:
    """An Organization payload differs from a User one only by `__typename`."""
    from agent_sessions.events import github

    captured: list[list[str]] = []

    def runner(command, **kwargs):  # noqa: ANN001, ANN003
        captured.append(list(command))

        class Completed:
            returncode = 0
            stdout = json.dumps(
                {
                    "data": {
                        "repositoryOwner": {
                            "__typename": "Organization",
                            "projectV2": {
                                "id": "PVT_org",
                                "fields": {
                                    "totalCount": 0,
                                    "nodes": [],
                                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                                },
                            },
                        }
                    }
                }
            )
            stderr = ""

        return Completed()

    result = github.fetch_project_fields("someorg/4", env={"PATH": "/bin"}, runner=runner)

    assert result["id"] == "PVT_org"
    assert captured and "graphql" in captured[0]
