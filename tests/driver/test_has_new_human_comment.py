"""Characterisation of `parking.has_new_human_comment`, branch by branch — #261 T3.

The function consults three sources in order and stops at the first that answers yes:
the GraphQL comment+reaction query, then `gh issue view --json comments`, then
`gh pr view --json reviews`. `test_driver.py`'s two cases predate the split and cannot
tell them apart: their fake answers *every* command with one payload, so a case aimed at
the REST branch reaches it only because the GraphQL branch happens to find no `data` key
in the same bytes, and a change that swapped the two would still pass.

These use `recording_gh`, which fails on a command it was not asked to model. That is
what makes the *negative* half assertable: "GraphQL answered, so REST was never called"
is a claim about a call that did not happen, and a catch-all fake cannot make it.

Written before collapsing the doubled scan, and unchanged by it. Their value is that
they pass against both shapes, including the one tolerance nobody would choose on
purpose (see `test_the_rest_branch_tolerates_a_bare_reaction_list`). One case changed
deliberately afterwards: `test_no_source_unparks_on_an_actor_it_cannot_date` records
#261's decision to make the review branch fail closed like the other two.
"""

from __future__ import annotations

import json

import pytest

from agent_sessions.driver import parking

REPO = "owner/repo"
PARK = "20260810T120000Z"
BEFORE = "2026-08-10T11:00:00Z"
AFTER = "2026-08-10T13:00:00Z"

BOTS = frozenset({"driver-account", "github-actions[bot]"})


def is_graphql(argv):
    return argv[:3] == ["gh", "api", "graphql"]


def is_issue_view(argv):
    return argv[:3] == ["gh", "issue", "view"]


def is_pr_view(argv):
    return argv[:3] == ["gh", "pr", "view"]


def graphql_comments(*nodes):
    return json.dumps({"data": {"repository": {"issue": {"comments": {"nodes": list(nodes)}}}}})


def gql_comment(login, created_at, *, reactions=()):
    return {
        "author": {"login": login},
        "createdAt": created_at,
        "reactions": {"nodes": [dict(r) for r in reactions]},
    }


def reaction(login, created_at, content="THUMBS_UP"):
    return {"content": content, "user": {"login": login}, "createdAt": created_at}


def rest_comments(*nodes):
    return json.dumps({"comments": list(nodes)})


def reviews(*nodes):
    return json.dumps({"reviews": list(nodes)})


def call(gh, **kwargs):
    return parking.has_new_human_comment(42, REPO, bot_logins=BOTS, park_time=PARK, **kwargs)


# --- source 1: the GraphQL query --------------------------------------------


def test_a_human_comment_in_graphql_answers_without_reaching_rest(recording_gh):
    recording_gh.on(is_graphql, graphql_comments(gql_comment("alice", AFTER)))
    assert call(recording_gh) == (True, "alice")
    assert [c[:3] for c in recording_gh.calls] == [["gh", "api", "graphql"]]


def test_a_human_reaction_on_a_bot_comment_answers(recording_gh):
    recording_gh.on(
        is_graphql,
        graphql_comments(gql_comment("driver-account", BEFORE, reactions=[reaction("lmorchard", AFTER)])),
    )
    assert call(recording_gh) == (True, "lmorchard")


def test_a_reaction_predating_the_park_does_not_answer(recording_gh):
    """The #183 case: an approval must be newer than the park to unpark."""
    recording_gh.on(
        is_graphql,
        graphql_comments(gql_comment("driver-account", BEFORE, reactions=[reaction("lmorchard", BEFORE)])),
    )
    recording_gh.on(is_issue_view, rest_comments())
    recording_gh.on(is_pr_view, reviews())
    assert call(recording_gh) == (False, "")


def test_the_newest_comment_wins(recording_gh):
    """Scanned in reverse, so the login returned is the latest human, not the first."""
    recording_gh.on(
        is_graphql,
        graphql_comments(gql_comment("alice", AFTER), gql_comment("bob", AFTER)),
    )
    assert call(recording_gh) == (True, "bob")


@pytest.mark.parametrize(
    "response",
    [
        pytest.param(graphql_comments(), id="empty-nodes"),
        pytest.param("{}", id="no-data-key"),
        pytest.param("not json at all", id="unparseable"),
        pytest.param("", id="empty-stdout"),
    ],
)
def test_an_unusable_graphql_answer_falls_through_to_rest(recording_gh, response):
    recording_gh.on(is_graphql, response)
    recording_gh.on(is_issue_view, rest_comments({"author": {"login": "alice"}, "createdAt": AFTER}))
    assert call(recording_gh) == (True, "alice")


def test_a_repo_with_no_slash_skips_graphql_entirely(recording_gh):
    recording_gh.on(is_issue_view, rest_comments({"author": {"login": "alice"}, "createdAt": AFTER}))
    assert parking.has_new_human_comment(42, "norepo", bot_logins=BOTS, park_time=PARK) == (True, "alice")
    assert [c[:3] for c in recording_gh.calls] == [["gh", "issue", "view"]]


# --- source 2: `gh issue view --json comments` -------------------------------


def test_the_rest_branch_applies_the_same_bot_and_park_filters(recording_gh):
    recording_gh.on(is_graphql, graphql_comments())
    recording_gh.on(
        is_issue_view,
        rest_comments(
            {"author": {"login": "driver-account"}, "createdAt": AFTER},
            {"author": {"login": "alice"}, "createdAt": BEFORE},
        ),
    )
    recording_gh.on(is_pr_view, reviews())
    assert call(recording_gh) == (False, "")


def test_the_rest_branch_tolerates_a_bare_reaction_list(recording_gh):
    """A divergence from the GraphQL branch, pinned rather than endorsed.

    REST accepts `reactions` as either `{"nodes": [...]}` or a bare list; GraphQL
    accepts only the former. Nothing observed produces the bare shape, and no note
    records why the tolerance is here -- so it is preserved on the grounds that
    removing it is a behaviour change wearing a cleanup's clothes, not because it
    is right.
    """
    recording_gh.on(is_graphql, graphql_comments())
    recording_gh.on(
        is_issue_view,
        rest_comments({"author": {"login": "driver-account"}, "createdAt": BEFORE,
                       "reactions": [reaction("lmorchard", AFTER)]}),
    )
    assert call(recording_gh) == (True, "lmorchard")


def test_a_comment_with_no_author_login_is_skipped(recording_gh):
    recording_gh.on(is_graphql, graphql_comments())
    recording_gh.on(is_issue_view, rest_comments({"author": None, "createdAt": AFTER}))
    recording_gh.on(is_pr_view, reviews())
    assert call(recording_gh) == (False, "")


# --- source 3: `gh pr view --json reviews` -----------------------------------


def test_a_human_review_after_the_park_answers(recording_gh):
    recording_gh.on(is_graphql, graphql_comments())
    recording_gh.on(is_issue_view, rest_comments())
    recording_gh.on(is_pr_view, reviews({"author": {"login": "alice"}, "submittedAt": AFTER}))
    assert call(recording_gh) == (True, "alice")


def test_a_review_predating_the_park_does_not(recording_gh):
    recording_gh.on(is_graphql, graphql_comments())
    recording_gh.on(is_issue_view, rest_comments())
    recording_gh.on(is_pr_view, reviews({"author": {"login": "alice"}, "submittedAt": BEFORE}))
    assert call(recording_gh) == (False, "")


def test_a_review_with_no_author_is_skipped_like_a_comment_with_none(recording_gh):
    """The three branches agree on an authorless actor, by two different routes.

    The comment branches test `login and not is_bot_login(login)`; the review branch
    tests only `is_bot_login(login)`. Reading the source, that looks like a divergence
    -- the review branch appears to be missing the truthy check, so an authorless
    review would unpark and report the actor as `""`. It does not:
    `credentials.is_bot_login` returns True for an empty login (`credentials.py:470`),
    so the missing guard is subsumed rather than absent.

    Worth a test rather than a comment, because the agreement rests on a line in
    another module and nothing else says so. Delete that early return from
    `is_bot_login` and this is the case that reports it.
    """
    recording_gh.on(is_graphql, graphql_comments())
    recording_gh.on(is_issue_view, rest_comments())
    recording_gh.on(is_pr_view, reviews({"author": None, "submittedAt": AFTER}))
    assert call(recording_gh) == (False, "")


def test_no_source_unparks_on_an_actor_it_cannot_date(recording_gh):
    """All three fail closed on a missing timestamp. Resolved on #261.

    The comment branches always did. The review branch did not -- it skipped only
    reviews it could prove were older, so an undated review unparked the issue while
    an undated comment did not. Same input, opposite verdict, from one function.

    Failing closed is the choice, because parked is the safe state: it means no human
    has spoken yet, and an actor the driver cannot place in time is not evidence that
    one has. The cost is named rather than hidden -- a real review that GitHub returns
    without `submittedAt` now leaves the issue parked, and a person waiting on it has
    to comment as well.

    All three sources are consulted, which is the second half of the claim: the issue
    stays parked because every source declined, not because one of them answered early.
    """
    recording_gh.on(is_graphql, graphql_comments(gql_comment("alice", "")))
    recording_gh.on(is_issue_view, rest_comments({"author": {"login": "alice"}}))
    recording_gh.on(is_pr_view, reviews({"author": {"login": "alice"}}))
    assert call(recording_gh) == (False, "")
    assert [c[:3] for c in recording_gh.calls] == [
        ["gh", "api", "graphql"],
        ["gh", "issue", "view"],
        ["gh", "pr", "view"],
    ]


def test_a_dated_review_still_unparks(recording_gh):
    """The control for the case above: failing closed must not close the door entirely."""
    recording_gh.on(is_graphql, graphql_comments())
    recording_gh.on(is_issue_view, rest_comments())
    recording_gh.on(is_pr_view, reviews({"author": {"login": "alice"}, "submittedAt": AFTER}))
    assert call(recording_gh) == (True, "alice")


def test_no_park_time_means_any_human_activity_counts(recording_gh):
    recording_gh.on(is_graphql, graphql_comments(gql_comment("alice", BEFORE)))
    assert parking.has_new_human_comment(42, REPO, bot_logins=BOTS) == (True, "alice")
