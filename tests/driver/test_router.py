"""Tests for driver/router.py (pure phase-selection router)."""

from __future__ import annotations

from agent_sessions.driver import router


def test_router_no_io(monkeypatch):
    """Prove router.select performs zero I/O by patching subprocess.run to raise."""
    def mock_run(*args, **kwargs):
        raise RuntimeError("Subprocess run called during router selection!")

    monkeypatch.setattr("subprocess.run", mock_run)

    open_issues = [
        {
            "number": 42,
            "title": "Test issue",
            "body": "## Tier: auto-ok\n<!-- agent-session:spec -->",
            "labels": [{"name": "agent-session:spec"}],
        }
    ]
    res = router.select(
        open_issues=open_issues,
        open_prs=[],
        board_items=[],
        parked_nums=set(),
        config={"repo": "owner/repo", "all_issues": True},
    )
    assert res["candidates"] == [("42", "execute")]


def test_router_priority_ladder_and_skips():
    # 1. P3 Groom (markerless issue)
    res_markerless = router.select(
        open_issues=[{"number": 10, "title": "Markerless", "body": "Plain text", "labels": []}],
        open_prs=[],
        config={"all_issues": True},
    )
    assert res_markerless["candidates"] == [("10", "triage")]

    # 2. P2 Execute (auto-ok specced candidate, no PR)
    res_execute = router.select(
        open_issues=[
            {
                "number": 20,
                "title": "Specced auto",
                "body": "## Tier: auto-ok\n<!-- agent-session:spec -->",
                "labels": [{"name": "agent-session:spec"}],
            }
        ],
        open_prs=[],
        config={"all_issues": True},
    )
    assert res_execute["candidates"] == [("20", "execute")]

    # 3. P3 Groom (needs-review specced candidate, no PR)
    res_refine = router.select(
        open_issues=[
            {
                "number": 30,
                "title": "Specced review",
                "body": "## Tier: needs-review\n<!-- agent-session:spec -->",
                "labels": [{"name": "agent-session:spec"}],
            }
        ],
        open_prs=[],
        config={"all_issues": True},
    )
    assert res_refine["candidates"] == [("30", "refine")]

    # 4. Skip: Parked issue without human comment
    res_parked = router.select(
        open_issues=[
            {
                "number": 40,
                "title": "Parked issue",
                "body": "Plain",
                "labels": [{"name": "agent-session:needs-human"}],
            }
        ],
        open_prs=[],
        parked_nums={"40"},
        park_reasons={"40": "test reason"},
        config={"all_issues": True},
    )
    assert res_parked["candidates"] == []
    assert any("parked: test reason" in m for m in res_parked["messages"])

    # 5. Unpark: Parked issue with new human comment
    res_unpark = router.select(
        open_issues=[
            {
                "number": 40,
                "title": "Parked issue",
                "body": "Plain",
                "labels": [{"name": "agent-session:needs-human"}],
            }
        ],
        open_prs=[],
        parked_nums={"40"},
        human_comments_map={"40": (True, "alice")},
        config={"all_issues": True},
    )
    assert "40" in res_unpark["unpark_actions"]

    # 6. Skip: Invalid tier
    res_invalid_tier = router.select(
        open_issues=[
            {
                "number": 50,
                "title": "Bad tier",
                "body": "No tier heading here\n<!-- agent-session:spec -->",
                "labels": [{"name": "agent-session:spec"}],
            }
        ],
        open_prs=[],
        config={"all_issues": True},
    )
    assert res_invalid_tier["candidates"] == []
    assert any("tier is invalid (missing)" in m for m in res_invalid_tier["messages"])

    # 7. P1 Unblock (PR blocking issue)
    open_prs = [{"number": 100, "closingIssuesReferences": [{"number": 60}], "body": "Fixes #60"}]
    res_unblock = router.select(
        open_issues=[
            {
                "number": 60,
                "title": "PR blocked",
                "body": "## Tier: auto-ok\n<!-- agent-session:spec -->",
                "labels": [{"name": "agent-session:spec"}],
            }
        ],
        open_prs=open_prs,
        pr_details_map={"100": {"unresolved": 0, "failed_ci": 0, "pending_ci": 0, "req_rev": 0, "revd": 1}},
        config={"all_issues": True},
    )
    assert res_unblock["candidates"] == [("60", "grade_gate")]
