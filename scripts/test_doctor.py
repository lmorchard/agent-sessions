"""Tests for `make doctor` — the credential preflight.

Every check here exists because it caught something real on 2026-08-10, setting up
the first machine-user account. The setup failed three times in a row, each time
with a symptom that pointed somewhere other than the cause:

1. `gh` reported `"push": true` on the repo, which is the *collaborator role* and
   says nothing about a fine-grained token's own permissions.
2. A write probe against a nonexistent issue returned 404, because GitHub checks
   existence before permission on that endpoint. Ambiguous, and read as a pass.
3. The real cause was invisible from any of it: a fine-grained PAT owned by the
   machine user cannot reach another user's private repo at all, whatever the
   collaborator status, and there is no setting that changes it.

So the value of this module is not that it runs `gh` — it is that it knows which
probes discriminate and which look like they do.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from agent_sessions.scripts import doctor  # noqa: E402

BOT = "agent-bot"
HUMAN = "lmorchard"
REPO = "lmorchard/agent-sessions"
READ, WRITE = "read-tok", "write-tok"


def env(**over):
    base = {
        "DRIVER_GH_LOGIN": BOT,
        "AGENT_GH_READ_TOKEN": READ,
        "DRIVER_GH_WRITE_TOKEN": WRITE,
    }
    base.update(over)
    return base


class FakeGh:
    """A `gh` that answers per token, so a check that ignores the token fails here.

    `visible` maps token -> set of repos. `writable` maps token -> set of repos.
    """

    def __init__(self, *, logins=None, visible=None, writable=None, labels=("bug",), origin=None,
                 write_token=WRITE, repo=REPO, discussions=True, categories=("Lab Notebook",),
                 scopes="project, repo, read:org", board_ok=True):
        # `write_token` lets a test swap in a real-shaped token (`github_pat_…` vs
        # `ghp_…`) without having to restate every map by hand.
        self.logins = logins if logins is not None else {READ: BOT, write_token: BOT}
        self.visible = visible if visible is not None else {READ: {repo}, write_token: {repo}}
        self.writable = writable if writable is not None else {write_token: {repo}}
        self.labels = list(labels)
        self.origin = origin if origin is not None else f"https://github.com/{REPO}.git"
        self.discussions = discussions
        self.categories = list(categories)
        self.scopes = scopes
        self.board_ok = board_ok
        self.calls: list[tuple[str, list[str]]] = []

    def __call__(self, argv, **kwargs):
        token = (kwargs.get("env") or {}).get("GH_TOKEN", "")
        self.calls.append((token, list(argv)))
        joined = " ".join(argv)

        def result(code, out="", err=""):
            class R:
                returncode = code
                stdout = out
                stderr = err

            return R()

        if argv[0] == "git":
            return result(0, self.origin + "\n") if "get-url" in argv else result(1, "", "fake: unhandled git")

        if argv[:2] == ["gh", "project"]:
            if not self.board_ok:
                return result(1, "", "unknown owner type")
            return result(0, '{"items":[]}')

        if "-i" in argv and argv[-1] == "user":
            body = '{"login":"%s"}' % self.logins.get(token, "")
            hdr = f"X-Oauth-Scopes: {self.scopes}\n" if self.scopes else ""
            return result(0, f"HTTP/2.0 200 OK\n{hdr}\n{body}")

        if "api user" in joined or argv[:3] == ["gh", "api", "user"]:
            login = self.logins.get(token)
            return result(0, login + "\n") if login else result(1, "", "gh: Bad credentials (HTTP 401)")

        target = next((a for a in argv if "/" in a and not a.startswith("-")), "")
        repo = target.replace("repos/", "").split("/labels")[0].split("/")[0:2]
        repo = "/".join(repo) if len(repo) == 2 else ""

        if repo and repo not in self.visible.get(token, set()):
            return result(1, "", 'gh: Not Found (HTTP 404)')

        if "labels" in joined and "POST" in joined:
            if repo in self.writable.get(token, set()):
                return result(1, "", "gh: Validation Failed (HTTP 422) already_exists")
            return result(1, "", "gh: Resource not accessible by personal access token (HTTP 403)")

        if "hasDiscussionsEnabled" in joined:
            cats = ",".join('{"name":"%s"}' % c for c in self.categories)
            return result(0, '{"data":{"repository":{"hasDiscussionsEnabled":%s,"discussionCategories":{"nodes":[%s]}}}}'
                          % ("true" if self.discussions else "false", cats))

        if "labels" in joined:
            return result(0, "\n".join(self.labels) + "\n")

        return result(0, '{"full_name": "%s", "visibility": "private"}' % repo)


def run(gh=None, environ=None, repo=REPO):
    return doctor.check_all(environ or env(), gh or FakeGh(), repo=repo, repo_path=".", board="")


def by_name(checks, name):
    return next(c for c in checks if c.name == name)


def statuses(checks):
    return {c.name: c.status for c in checks}


# -- the happy path ----------------------------------------------------------


def test_a_correct_setup_passes_everything():
    checks = run()
    assert all(c.status in ("pass", "skip") for c in checks), [
        (c.name, c.status, c.detail) for c in checks if c.status not in ("pass", "skip")
    ]
    assert doctor.exit_code(checks) == 0


def test_the_report_never_prints_a_token():
    report = doctor.render(run())
    assert READ not in report and WRITE not in report


# -- identity ----------------------------------------------------------------


def test_a_token_belonging_to_a_human_fails():
    checks = run(FakeGh(logins={READ: BOT, WRITE: HUMAN}))
    assert by_name(checks, "write token identity").status == "fail"
    assert HUMAN in by_name(checks, "write token identity").detail
    assert doctor.exit_code(checks) != 0


def test_an_unusable_token_fails_with_the_gh_message():
    checks = run(FakeGh(logins={READ: BOT}))
    check = by_name(checks, "write token identity")
    assert check.status == "fail"
    assert "401" in check.detail or "Bad credentials" in check.detail


# -- repo visibility, and the diagnosis that took three tries ----------------


def test_an_invisible_repo_fails():
    checks = run(FakeGh(visible={READ: set(), WRITE: set()}))
    assert by_name(checks, "read token sees the repo").status == "fail"


def test_an_invisible_repo_owned_by_someone_else_names_the_real_cause():
    """The failure that cost the most time. A fine-grained PAT owned by the machine
    user cannot reach another user's private repo -- no setting, no collaborator
    invite, no 'All repositories' selection changes it. The remedy has to say so,
    because the GitHub UI offers nothing that looks like the problem."""
    checks = run(FakeGh(visible={READ: set(), WRITE: set()}))
    remedy = by_name(checks, "read token sees the repo").remedy
    assert "fine-grained" in remedy.lower()
    assert BOT in remedy and "lmorchard" in remedy
    assert "organization" in remedy.lower() or "github app" in remedy.lower()


def test_a_repo_owned_by_the_token_holder_gets_a_different_remedy():
    """Same symptom, different cause: here the resource owner is right and it is
    genuinely a repository-selection problem, which *is* fixable in the UI."""
    own = f"{BOT}/thing"
    checks = run(FakeGh(visible={READ: set(), WRITE: set()}), repo=own)
    remedy = by_name(checks, "read token sees the repo").remedy
    assert "Repository access" in remedy
    assert "organization" not in remedy.lower()


# -- write capability --------------------------------------------------------


def test_a_read_token_that_can_write_fails():
    """The whole containment claim. If this passes wrongly, nothing else matters."""
    checks = run(FakeGh(writable={READ: {REPO}, WRITE: {REPO}}))
    check = by_name(checks, "read token cannot write")
    assert check.status == "fail"


def test_a_write_token_that_cannot_write_fails():
    checks = run(FakeGh(writable={}))
    assert by_name(checks, "write token can write").status == "fail"


def test_the_write_probe_uses_an_existing_label_so_it_changes_nothing():
    """Creating a label that already exists is a 422 no-op. The obvious alternatives
    are worse: a nonexistent issue returns 404 before the permission check (so it
    cannot discriminate), and anything else that succeeds leaves a real artifact."""
    gh = FakeGh(labels=("needs-triage",))
    run(gh)
    probes = [argv for _, argv in gh.calls if "POST" in " ".join(argv) and "labels" in " ".join(argv)]
    assert probes, "no write probe was issued"
    for argv in probes:
        assert "name=needs-triage" in argv, f"probe invented a label name: {argv}"


def test_write_capability_is_unverified_rather_than_assumed_when_no_label_exists():
    """A repo with no labels has nothing safe to probe with. Say so; do not guess,
    and do not create one just to have something to push against."""
    checks = run(FakeGh(labels=()))
    for name in ("read token cannot write", "write token can write"):
        assert by_name(checks, name).status == "skip"
    # A skip is not a pass, but it is also not a reason to fail the whole preflight.
    assert doctor.exit_code(run(FakeGh(labels=()))) == 0


def test_a_repo_permissions_field_is_not_used_as_evidence():
    """`GET /repos` reports the *collaborator role*, which read `push: true` for a
    token that could not write a thing. Pinning that the doctor never consults it."""
    gh = FakeGh()
    run(gh)
    for _, argv in gh.calls:
        assert "--jq" not in argv or ".permissions" not in " ".join(argv)


# -- configuration -----------------------------------------------------------


def test_missing_configuration_is_reported_before_anything_is_probed():
    gh = FakeGh()
    checks = doctor.check_all({}, gh, repo=REPO, repo_path=".", board="")
    assert by_name(checks, "credentials configured").status == "fail"
    assert gh.calls == [], "probed GitHub with a configuration it had already rejected"


def test_identical_tokens_are_reported():
    checks = run(environ=env(DRIVER_GH_WRITE_TOKEN=READ))
    assert by_name(checks, "credentials configured").status == "fail"


# -- the git remote ----------------------------------------------------------


def test_an_ssh_origin_is_a_warning_not_a_failure(tmp_path: Path):
    """Pushes fall outside the split on SSH, but the loop still works, so this is
    advice rather than a stop."""
    check = doctor.remote_check("git@github.com:lmorchard/agent-sessions.git")
    assert check.status == "warn"


def test_an_https_origin_passes():
    assert doctor.remote_check("https://github.com/lmorchard/agent-sessions.git").status == "pass"


def test_a_warning_does_not_fail_the_preflight():
    checks = run() + [doctor.remote_check("git@github.com:x/y.git")]
    assert doctor.exit_code(checks) == 0


# -- the board ---------------------------------------------------------------

def test_the_board_is_probed_with_the_write_token():
    """The driver reads the board with its own credential, so that is the one that
    has to be able to see it."""
    gh = FakeGh()
    doctor.check_all(env(), gh, repo=REPO, repo_path=".", board="lmorchard/9")
    tokens = [tok for tok, argv in gh.calls if argv[:3] == ["gh", "project", "item-list"]]
    assert tokens == [WRITE]


def test_an_invisible_board_warns_rather_than_fails():
    """`fetch_board_json` degrades to label-based selection, so this is advice --
    but advice that has to say what the degradation costs."""
    checks = doctor.check_all(env(), FakeGh(board_ok=False), repo=REPO, repo_path=".", board="lmorchard/9")
    check = by_name(checks, "board readable")
    assert check.status == "warn"
    assert "read:org" in check.remedy
    assert doctor.exit_code(checks) == 0



def test_the_notebook_category_name_matches_discussion_manager():
    """Two copies of a string that must agree. Pinned rather than trusted."""
    import inspect

    from agent_sessions.driver import discussion_manager

    default = inspect.signature(discussion_manager.post_start).parameters
    used = inspect.signature(discussion_manager.get_or_create_daily_discussion).parameters
    assert used["category_name"].default == doctor.NOTEBOOK_CATEGORY
    assert default is not None


def test_a_present_notebook_category_passes():
    checks = run(FakeGh(), repo=REPO)
    assert by_name(checks, "discussions notebook").status == "pass"


def test_a_missing_category_names_the_mutation_that_cannot_create_it():
    """`ensure_category` calls `createDiscussionCategory`, which is not in GitHub's
    GraphQL schema -- so it has never worked and fails silently. An operator hitting
    a missing category should be told to create it by hand, not left waiting."""
    checks = run(FakeGh(categories=("General",)), repo=REPO)
    check = by_name(checks, "discussions notebook")
    assert check.status == "warn"
    assert "createDiscussionCategory" in check.remedy
    assert "by hand" in check.remedy


def test_discussions_disabled_warns_that_the_trail_is_lost_silently():
    checks = run(FakeGh(discussions=False), repo=REPO)
    check = by_name(checks, "discussions notebook")
    assert check.status == "warn"
    assert "silence" in check.remedy or "silent" in check.remedy


def test_the_notebook_check_does_not_fail_the_preflight():
    """The driver wraps the notes in try/except, so the loop runs without them."""
    assert doctor.exit_code(run(FakeGh(discussions=False), repo=REPO)) == 0


# -- why a board is invisible: three causes, one symptom ---------------------


def board_remedy(error, token="ghp_x", login=BOT, board="lmorchard/9"):
    return doctor._board_remedy(board, login, token, error)


def test_a_scope_error_is_diagnosed_as_a_scope_error():
    remedy = board_remedy("your token has not been granted the required scopes")
    assert "read:project" in remedy


def test_a_not_found_on_a_classic_token_is_diagnosed_as_per_project_access():
    """The case that caught this out: project 6 was readable and project 9 was not,
    with the same classic token. The scope was never the problem -- project 6 is
    public and project 9 is private, and ProjectsV2 keeps its own collaborator list
    that repository access does not feed into."""
    remedy = board_remedy("GraphQL: Could not resolve to a ProjectV2 with the number 9. NOT_FOUND")
    assert "Manage access" in remedy
    assert "separate from repository" in remedy
    assert "read:project" not in remedy, "blamed the scope again"


def test_a_not_found_on_a_fine_grained_token_is_diagnosed_as_ownership():
    remedy = board_remedy("NOT_FOUND", token="github_pat_x")
    assert "fine-grained" in remedy
    assert "classic PAT" in remedy


def test_a_fine_grained_token_on_its_owners_project_is_not_told_about_ownership():
    remedy = board_remedy("NOT_FOUND", token="github_pat_x", board=f"{BOT}/3")
    assert "Manage access" in remedy


# -- the board check must call what the driver calls --------------------------


def test_the_board_probe_is_the_drivers_own_command():
    """The check passed while the driver failed, because it asked GraphQL directly
    and the driver shells out to `gh project item-list` -- which needs `read:org`
    to resolve `--owner` and errors with `unknown owner type` without it. Checking a
    proxy for the real call is how a configuration that cannot select an issue was
    reported green.

    Derived, not restated: both sides come from `agent_session_driver.board_command`,
    so the two cannot drift apart again."""
    from agent_sessions.driver import agent_session_driver

    gh = FakeGh()
    doctor.check_all(env(), gh, repo=REPO, repo_path=".", board="lmorchard/9")

    expected = agent_session_driver.board_command("lmorchard/9", limit=1)
    issued = [argv for _, argv in gh.calls if argv[:3] == ["gh", "project", "item-list"]]
    assert issued, f"the board was not probed with the driver's own command: {gh.calls}"
    assert issued[0] == expected


def test_unknown_owner_type_is_diagnosed_as_the_missing_read_org_scope():
    """`gh` resolves `--owner` by asking for the organization *and* user id in one
    query, so the org branch fails the whole thing without `read:org` -- even for a
    user-owned project. The surfaced error says only `unknown owner type`."""
    remedy = doctor._board_remedy("lmorchard/9", BOT, "ghp_x", "unknown owner type")
    assert "read:org" in remedy


def test_the_board_remedy_says_what_an_unreadable_board_actually_costs():
    """'Falls back to labels' reads as harmless. It is not: with no priority labels
    on any issue, nothing is eligible and the loop does nothing at all."""
    checks = run(FakeGh(), repo=REPO)
    board = [c for c in checks if c.name == "board readable"]
    remedy = doctor._board_remedy("lmorchard/9", BOT, "ghp_x", "NOT_FOUND")
    assert "nothing" in remedy.lower() or "no issue" in remedy.lower()
    assert board == [] or board[0].status in ("pass", "warn")


# -- classic token scopes are readable, so read them -------------------------


def test_classic_token_scopes_are_reported():
    """`X-OAuth-Scopes` is returned for classic tokens and is definitive -- no
    probing needed. Only fine-grained tokens require guessing."""
    gh = FakeGh(scopes="project, repo, write:discussion")
    checks = doctor.check_all(env(DRIVER_GH_WRITE_TOKEN="ghp_x"), FakeGh(write_token="ghp_x", scopes="project, repo"),
                              repo=REPO, repo_path=".", board="lmorchard/9")
    scope_check = [c for c in checks if c.name == "write token scopes"]
    assert scope_check, [c.name for c in checks]
    assert gh is not None


def test_a_board_without_read_org_is_flagged_from_the_scopes():
    checks = doctor.check_all(
        env(DRIVER_GH_WRITE_TOKEN="ghp_x"),
        FakeGh(write_token="ghp_x", scopes="project, repo"),
        repo=REPO, repo_path=".", board="lmorchard/9",
    )
    check = next(c for c in checks if c.name == "write token scopes")
    assert check.status == "warn"
    assert "read:org" in check.remedy


def test_the_workflow_scope_is_called_out_as_dangerous():
    """It buys whoever holds the token arbitrary CI execution -- a far larger prize
    than the token, and the one scope this project tells you never to grant."""
    checks = doctor.check_all(
        env(DRIVER_GH_WRITE_TOKEN="ghp_x"),
        FakeGh(write_token="ghp_x", scopes="repo, workflow, project, read:org"),
        repo=REPO, repo_path=".", board="lmorchard/9",
    )
    check = next(c for c in checks if c.name == "write token scopes")
    assert check.status == "warn"
    assert "workflow" in check.remedy


def test_a_fine_grained_token_has_no_scopes_header_and_is_skipped_not_failed():
    checks = doctor.check_all(
        env(DRIVER_GH_WRITE_TOKEN="github_pat_x"),
        FakeGh(write_token="github_pat_x", scopes=None),
        repo=REPO, repo_path=".", board="lmorchard/9",
    )
    check = next(c for c in checks if c.name == "write token scopes")
    assert check.status == "skip"
    assert doctor.exit_code(checks) == 0


def test_the_scopes_check_never_prints_the_token():
    checks = doctor.check_all(
        env(DRIVER_GH_WRITE_TOKEN="ghp_secret"),
        FakeGh(write_token="ghp_secret", scopes="repo"),
        repo=REPO, repo_path=".", board="lmorchard/9",
    )
    assert "ghp_secret" not in doctor.render(checks)


def test_a_warning_is_not_reported_as_all_checks_passed():
    """It printed `all checks passed` above two warnings that between them explained
    why the driver could not select a single issue. Same shape as the worst defect
    this tool exists to catch: a summary that reads as a pass over something broken."""
    report = doctor.render(doctor.check_all(env(), FakeGh(board_ok=False), repo=REPO, repo_path=".", board="lmorchard/9"))
    assert "all checks passed" not in report
    assert "warning" in report


def test_a_wholly_clean_run_still_says_so():
    """The control: without it, the fix above is satisfiable by never saying it.

    Needs a classic token and a board, since those are what make the scopes check
    resolvable rather than a skip -- and a skip is not a pass either."""
    tok = "ghp_clean"
    checks = doctor.check_all(
        env(DRIVER_GH_WRITE_TOKEN=tok),
        FakeGh(write_token=tok, scopes="public_repo, project, read:org"),
        repo=REPO, repo_path=".", board="lmorchard/9",
    )
    assert [c.name for c in checks if c.status != "pass"] == []
    assert "all checks passed" in doctor.render(checks)
