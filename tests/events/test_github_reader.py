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
            stdout = '{"data": {"user": {"projectV2": {"fields": {"nodes": [], '
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
