"""One complete driver pass, end to end, against fixture GitHub state — issue #187.

Every other suite in `driver/` covers a module. Nothing covered the *seam*: the
driver's `main()` reads issues, builds the priority ladder, takes a lock, writes an
inflight marker, invokes the runner, parses the stream, classifies the outcome,
applies park state, appends to `runs.jsonl` and posts discussion notes. This file
drives that sequence as a sequence.

**It calls the shipping `main()`.** `findings.md` defect class 1, instance 9 is this
project's worst: `test-driver.sh` hand-copied the classifier, the copy drifted, and
the suite graded a replica that called a stale-CI PR eligible for auto-merge exactly
where the shipped code voided it. So there is no selection logic and no
classification logic below — only fixture state going in, and observable effects
coming out.

The rig those cases run on — `FakeGitHub`, `StubAgent`, `LoopHarness` and the fixture
builders — is `loop_harness.py`, and the three load-bearing properties of the fake are
documented there.

## The selection golden

`test_selection_output_is_byte_identical_to_the_golden` pins the whole `--dry-run`
stdout for a twelve-issue fixture to `fixtures/select_golden.txt`, byte for byte. That
file is **#182's conformance target**: the router extraction's own criteria require
byte-identical selection output for a recorded fixture, and this is the recording.
Landing #187 before #182 is the only reason that criterion has somewhere to run.

Regenerate with `UPDATE_SELECT_GOLDEN=1 uv run pytest driver/test_full_loop.py`, and
read the diff before committing it. A golden you regenerate without reading is a
golden with no teeth.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import subprocess
import time
from datetime import timedelta
from pathlib import Path

import pytest
from loop_harness import (
    DRIVER_LOGIN,
    EMPTY_TREE,
    FROZEN,
    FROZEN_TS,
    HUMAN_LOGIN,
    LOCK_SHA,
    NEW_PR_HEAD,
    READ_TOKEN,
    REPO,
    WRITE_TOKEN,
    FakeGitHub,
    LoopHarness,
    StubAgent,
    agent_stream,
    board_item,
    comment,
    gate_body,
    issue,
    pr,
    spec_body,
)

from agent_sessions.driver import (
    agent_runner,
    agent_session_driver,
    credentials,
    gate,
    lifecycle,
    locks,
    output,
)
from agent_sessions.events import config as events_config
from agent_sessions.events import driver as events_driver
from agent_sessions.events.github import ResolvedTarget
from agent_sessions.events.models import (
    ApprovalWatch,
    Invalidation,
    QueueUnavailable,
    RepositoryIdentity,
)
from agent_sessions.events.store import CURRENT_SCHEMA_VERSION, QueueStore
from agent_sessions.events.webhook import create_app

GOLDEN = Path(__file__).parent / "fixtures" / "select_golden.txt"


@pytest.fixture
def loop(tmp_path, monkeypatch, capsys):
    """One pass's rig. Deliberately here and not in a `tests/driver/conftest.py`.

    A second conftest is what mypy sees as `Duplicate module named "conftest"` -- it has
    no `__init__.py` to derive a package from, and `tests/conftest.py` already owns the
    name. Getting mypy past that means `explicit_package_bases` plus a `mypy_path`, and
    both spellings of it broke something else: the repo-root base renamed the package to
    `src.agent_sessions.*`, and `mypy_path = "src"` turned on namespace packages, which
    lost every `from agent_sessions.driver import <submodule>` in 30 files.

    So the sharing boundary is `loop_harness.py`, which is an ordinary module and has
    none of these problems. A suite that wants this fixture copies these three lines;
    what it must not copy is the harness.
    """
    return LoopHarness(tmp_path, monkeypatch, capsys)


# --- case 1: a pass that ends gate-eligible ---------------------------------


def test_pass_ending_gate_eligible(loop):
    """select -> lock -> invoke -> parse -> classify -> record, ending eligible.

    #101 has a PR whose threads are resolved, CI green and review in hand, so the
    ladder picks Priority 1 / `grade_gate`; the PR's gate block votes eligible on the
    current head sha.
    """
    head = "abc1234def5678000000000000000000000000ff"
    gh = FakeGitHub(
        issues=[issue(101, body=spec_body("auto-ok"), labels=["P1"])],
        prs=[
            pr(
                201,
                body=gate_body(101, verdict="eligible-for-auto-merge", ci_row="2/2 pass @ abc1234"),
                closes=[101],
                head_oid=head,
                checks=[("lint", "pass"), ("test", "pass")],
                threads=[True],
                review_requests=1,
                reviews=1,
            )
        ],
        board_items=[board_item(101)],
    )
    agent = StubAgent(stream=agent_stream(final="Graded the gate: eligible.", cost=1.23, session="sess-abc"))

    code, out = loop.run(gh, agent=agent)

    assert code == 0
    assert "ELIGIBLE #101  tier: auto-ok (Priority 1: Unblock - grade_gate)" in out
    assert "outcome  gate-eligible" in out

    # The run was actually dispatched, at the tier `grade_gate` maps to.
    assert len(agent.calls) == 1
    argv = agent.calls[0]
    assert argv[argv.index("--tier") + 1] == "low"

    # The lock was taken through git, uncontended: no ref, so push a fresh one.
    assert ["rev-parse", "--git-dir"] in gh.git_calls
    assert ["commit-tree", EMPTY_TREE] in gh.git_calls
    assert ["ls-remote", "origin", "refs/locks/issue-101"] in gh.git_calls
    assert ["push", "origin", f"{LOCK_SHA}:refs/locks/issue-101"] in gh.git_calls

    rundir = loop.run_dir(101)
    assert loop.rows("runs.jsonl") == [
        {
            "issue": 101,
            "repo": REPO,
            "phase": "grade_gate",
            "started": FROZEN_TS,
            "exit": 0,
            "cost_usd": 1.23,
            "session_id": "sess-abc",
            "outcome": "gate-eligible",
            "reason": "all gate rows satisfied",
            "pr": f"https://github.com/{REPO}/pull/201",
            "changed_files": 1,
            "base_diff_sha": f"main..{head[:8]}",
            "run_dir": str(rundir),
            "writes": {"recorded": 0, "applied": 0, "ok": True},
            "provenance": {},
        }
    ]
    assert loop.rows("parked.jsonl") == []

    # Eligible is a finding, not a merge: the only write is the merge-ready label.
    assert gh.label_ops == [("attempt", "101", "1"), ("merge-ready", "101", None)]
    assert agent_session_driver.MERGE_READY_LABEL in gh.labels_of(101)
    assert agent_session_driver.PARK_LABEL not in gh.labels_of(101)

    # Run-dir artifacts.
    prompt = (rundir / "prompt.txt").read_text(encoding="utf-8")
    assert f"https://github.com/{REPO}/issues/101" in prompt
    assert f"{loop.skill_dir}/phases/grade_gate.md" in prompt
    assert json.loads((rundir / "parsed.json").read_text(encoding="utf-8")) == {
        "final": "Graded the gate: eligible.",
        "total_cost_usd": 1.23,
        "session_id": "sess-abc",
        "cost_known": True,
    }
    assert (rundir / "final.txt").read_text(encoding="utf-8") == "Graded the gate: eligible."
    assert (rundir / "stream.jsonl").is_file()
    # `gate.yaml` is the extracted block. This used to assert the *whole PR body*,
    # pinning the defect as behaviour and citing #184 as the fix -- #184 landed the
    # schema validation and closed without touching the extraction. #261's C5 did.
    assert (rundir / "gate.yaml").read_text(encoding="utf-8") == gate.extract_gate(
        gh.pr_by_number(201)["body"]
    )


def test_pass_with_empty_diff_is_classified_as_gate_human(loop):
    """Issue 192: A PR with 0 changed files is classified as gate-human with empty diff reason,
    and changed_files / base_diff_sha are recorded in runs.jsonl."""
    head = "abc1234def5678000000000000000000000000ff"
    gh = FakeGitHub(
        issues=[issue(101, body=spec_body("auto-ok"), labels=["P1"])],
        prs=[
            pr(
                201,
                body=gate_body(101, verdict="eligible-for-auto-merge", ci_row="2/2 pass @ abc1234"),
                closes=[101],
                head_oid=head,
                checks=[("lint", "pass"), ("test", "pass")],
                threads=[True],
                review_requests=1,
                reviews=1,
                changed_files=0,
            )
        ],
        board_items=[board_item(101)],
    )
    agent = StubAgent(stream=agent_stream(final="Graded the gate.", cost=1.23, session="sess-abc"))

    code, out = loop.run(gh, agent=agent)

    assert code == 0
    assert "outcome  gate-human" in out
    assert "empty diff" in out

    (row,) = loop.rows("runs.jsonl")
    assert row["outcome"] == "gate-human"
    assert "empty diff" in row["reason"]
    assert row["changed_files"] == 0
    assert "base_diff_sha" in row

    # The inflight marker was written and then cleared, so the next pass does not
    # report an orphan.
    assert not (loop.state_dir / "inflight.json").exists()
    assert "WARNING: a previous run died" not in out

    # Both discussion notes posted.
    assert len(gh.discussion_calls) == 2


def test_pass_with_a_stale_ci_row_is_not_eligible(loop):
    """The same pass, with the gate's ci row graded on a commit that no longer ships.

    Case 1 alone does not discriminate on staleness: blanking `head_sha` where the
    driver fetches it would leave that test green while silently disabling the check.
    That is `findings.md` defect class 1, instance 9 — the replica that called a
    stale-CI PR eligible exactly where the shipped code voided it — so the seam that
    *threads* the head sha into `gate.classify` gets its own case.
    """
    gh = FakeGitHub(
        issues=[issue(101, body=spec_body("auto-ok"), labels=["P1"])],
        prs=[
            pr(
                201,
                body=gate_body(101, verdict="eligible-for-auto-merge", ci_row="2/2 pass @ 0d08b2d"),
                closes=[101],
                head_oid="e8f03389abcdef000000000000000000000000ff",
                checks=[("lint", "pass"), ("test", "pass")],
                threads=[True],
                review_requests=1,
                reviews=1,
            )
        ],
        board_items=[board_item(101)],
    )

    code, out = loop.run(gh)

    assert code == 0
    assert "outcome  ci-stale" in out
    (row,) = loop.rows("runs.jsonl")
    assert row["outcome"] == "ci-stale"
    assert "0d08b2d" in row["reason"] and "e8f0338" in row["reason"]
    # Nothing was labelled merge-ready off a void verdict.
    assert gh.label_ops == [("attempt", "101", "1")]
    assert agent_session_driver.MERGE_READY_LABEL not in gh.labels_of(101)


# --- case 2: a pass that ends parked ----------------------------------------


def test_pass_ending_parked(loop):
    """A markerless issue goes to triage; the agent parks it and explains why.

    The park is the agent's *decision* but not the agent's *write*: since #191 it
    holds a read-scoped token, so it records the comment and the label in the write
    manifest and the driver applies them. The driver then reads the label back and
    records the outcome.
    """
    gh = FakeGitHub(
        issues=[issue(102, body="Something vague.", labels=["P2"])],
        board_items=[board_item(102)],
    )
    agent = StubAgent(
        stream=agent_stream(final="Two readings of the requirement; needs a human decision.", cost=0.42),
        manifest=[
            {"kind": "issue_comment", "issue": 102, "body": "Parking: two readings of the requirement."},
            {"kind": "label", "issue": 102, "add": [agent_session_driver.PARK_LABEL]},
        ],
    )

    code, out = loop.run(gh, agent=agent)

    assert code == 0
    assert "ELIGIBLE #102  triage (Priority 3: Groom)" in out
    assert "outcome  parked" in out
    assert "parked -- excluded from future selection unless --retry 102" in out

    # Both writes were performed by the driver, in manifest order, on the write
    # credential -- not by the agent, which had no way to issue them.
    assert [kind for kind, _ in gh.write_calls] == ["issue_comment", "issue_edit"]
    assert "  writes   2/2 applied by the driver" in out
    for argv, env in gh.calls_with_env:
        if argv[:3] in (["gh", "issue", "comment"], ["gh", "issue", "edit"]):
            assert env.get("GH_TOKEN") == WRITE_TOKEN, f"a write ran on the wrong credential: {argv}"

    (row,) = loop.rows("runs.jsonl")
    assert row["outcome"] == "parked"
    assert row["reason"] == (
        "parked by agent during triage: Two readings of the requirement; needs a human decision."
    )
    assert row["pr"] == ""
    assert row["cost_usd"] == 0.42

    assert loop.rows("parked.jsonl") == [
        {
            "issue": 102,
            "repo": REPO,
            "parked_at": FROZEN_TS,
            "outcome": "parked",
            "reason": row["reason"],
        }
    ]

    # The attempt counter goes up before the run and remains on the issue when parked.
    assert gh.label_ops == [("attempt", "102", "1"), ("park", "102", None)]
    assert agent_session_driver.PARK_LABEL in gh.labels_of(102)
    assert "agent-session:attempt-1" in gh.labels_of(102)

    inbox = (loop.state_dir / "inbox.md").read_text(encoding="utf-8")
    assert f"[{FROZEN_TS}] Issue #102 escalated: parked: {row['reason']}\n" == inbox


def test_a_held_lock_takes_the_issue_out_of_the_pass(loop):
    """An eligible issue whose lock another host holds is skipped, not run.

    The lock is the one step of the pass that can veto a decision selection has
    already made, so it gets a case where it does: a fresh ref on the remote, well
    inside the phase TTL.
    """
    gh = FakeGitHub(
        issues=[issue(103, body=spec_body("auto-ok"), labels=["P1"])],
        board_items=[board_item(103)],
        held_locks={"refs/locks/issue-103": ("2222222222222222222222222222222222222222", int(time.time()))},
    )
    agent = StubAgent()

    code, out = loop.run(gh, agent=agent)

    assert code == 0
    assert "ELIGIBLE #103  tier: auto-ok (Priority 2: Execute - execute)" in out
    assert "SKIP    #103  lock contention (another agent holds or held lock)" in out
    assert "eligible: 0 ()" in out
    assert "nothing eligible; no runs attempted." in out

    # Nothing ran, so nothing was spent, counted or recorded.
    assert agent.calls == []
    assert gh.label_ops == []
    assert loop.rows("runs.jsonl") == []
    assert not (loop.state_dir / "inflight.json").exists()
    # The contended ref was read, and no lock was pushed over it.
    assert ["ls-remote", "origin", "refs/locks/issue-103"] in gh.git_calls
    assert not [c for c in gh.git_calls if c[:1] == ["push"]]


# --- case 3: selection as a golden ------------------------------------------


def golden_fixture():
    """A repo state that reaches every rung of the ladder and every skip reason.

    Kept as a function rather than a module constant so the golden test owns it: it
    is the recorded input half of #182's conformance pair.
    """
    head = "cafe1234000000000000000000000000000000ff"
    issues = [
        # markerless -> triage
        issue(301, body="No marker, no tier.", labels=["P1"]),
        # markerless, parked, latest comment is a bot -> stays parked
        issue(302, body="Also markerless.", labels=["P1", agent_session_driver.PARK_LABEL],
              comments=[comment(HUMAN_LOGIN, "the original report"), comment("github-actions[bot]", "CI note")]),
        # specced auto-ok, no PR -> execute
        issue(303, body=spec_body("auto-ok"), labels=["P1"]),
        # specced needs-review -> refine
        issue(304, body=spec_body("needs-review"), labels=["P1"]),
        # two Tier headings -> conflict
        issue(305, body="<!-- agent-session:spec -->\n\n## Tier: auto-ok\n\n## Tier: needs-review\n", labels=["P1"]),
        # PR with unresolved threads -> address_comments
        issue(306, body=spec_body("auto-ok"), labels=["P1"]),
        # PR with failing CI -> fix_ci
        issue(307, body=spec_body("auto-ok"), labels=["P1"]),
        # PR with pending CI -> skip and wait
        issue(308, body=spec_body("auto-ok"), labels=["P1"]),
        # PR green, nobody asked for a review -> request_review
        issue(309, body=spec_body("auto-ok"), labels=["P1"]),
        # attempts exhausted -> loop breaker parks it
        issue(310, body=spec_body("auto-ok"), labels=["P1", "agent-session:attempt-3"]),
        # already merge-ready -> not a candidate at all
        issue(311, body=spec_body("auto-ok"), labels=["P1", agent_session_driver.MERGE_READY_LABEL]),
        # neither on the board nor priority-labelled -> filtered out before tiering
        issue(312, body=spec_body("auto-ok")),
    ]
    prs = [
        pr(406, closes=[306], head_oid=head, threads=[False, False], checks=[("test", "pass")]),
        pr(407, closes=[307], head_oid=head, threads=[True], checks=[("test", "fail"), ("lint", "pass")]),
        pr(408, closes=[308], head_oid=head, threads=[], checks=[("test", "pending"), ("lint", "pass")]),
        pr(409, closes=[309], head_oid=head, threads=[], checks=[("test", "pass")], review_requests=0, reviews=0),
    ]
    board = [board_item(n) for n in range(301, 312)]
    return FakeGitHub(issues=issues, prs=prs, board_items=board)


def test_selection_output_is_byte_identical_to_the_golden(loop):
    """#182's conformance target: the whole `--dry-run` stdout, byte for byte.

    Everything in the golden is a decision the router extraction must reproduce,
    including the two orderings that are easy to lose by accident: the markerless
    issues are processed *before* the `repo ...: read N open issues` line is printed,
    and the loop breaker's park message precedes its own SKIP line.
    """
    gh = golden_fixture()
    # A prior run's reason, so the parked skip prints history rather than the
    # "no history recorded on this host" fallback.
    loop.seed_runs([
        {"issue": 302, "repo": REPO, "started": FROZEN_TS, "outcome": "parked", "reason": "triage could not tell which subsystem this is about"}
    ])

    code, out = loop.run(gh, argv=["--dry-run"])
    assert code == 0

    if os.environ.get("UPDATE_SELECT_GOLDEN") == "1":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(out, encoding="utf-8")
        pytest.fail(
            f"rewrote {GOLDEN.relative_to(Path(__file__).resolve().parents[2])} from this run. "
            "Read the diff, then re-run without UPDATE_SELECT_GOLDEN."
        )

    assert GOLDEN.is_file(), (
        f"{GOLDEN} is missing. Regenerate with "
        "UPDATE_SELECT_GOLDEN=1 uv run pytest driver/test_full_loop.py"
    )
    assert out == GOLDEN.read_text(encoding="utf-8")

    # A golden can rot into agreement with a broken driver, so pin the two facts
    # that make it a *selection* golden rather than a string: the ladder ordered
    # Unblock first, and the loop breaker actually parked #310.
    assert "eligible: 1 (306:address_comments)" in out
    assert [row["issue"] for row in loop.rows("parked.jsonl")] == [310]


# --- case 4: the discriminating case (#183) ---------------------------------


def test_agent_park_comment_under_driver_identity_does_not_unpark(loop):
    """Two passes. The driver parks and comments as itself; the issue must stay parked.

    This is the chain from #183, not a tableau of it: pass 1's park label and park
    comment are real manifest writes, and pass 2 reads them back through the same
    `gh` surface a real pass would.

    It fails without `DRIVER_GH_LOGIN`. The driver's account is a PAT-backed machine
    user, so its login carries no `[bot]` suffix and nothing about the name says
    machine — its own park explanation reads as a human reply, the next pass unparks,
    and the agent runs again without a human signal.
    """
    gh = FakeGitHub(
        issues=[issue(102, body="Something vague.", labels=["P2"])],
        board_items=[board_item(102)],
    )
    agent = StubAgent(
        stream=agent_stream(final="Two readings of the requirement; needs a human decision."),
        manifest=[
            {"kind": "issue_comment", "issue": 102, "body": "Parking: two readings of the requirement."},
            {"kind": "label", "issue": 102, "add": [agent_session_driver.PARK_LABEL]},
        ],
    )

    first_code, _ = loop.run(gh, agent=agent)
    assert first_code == 0
    assert agent_session_driver.PARK_LABEL in gh.labels_of(102)
    ops_after_first_pass = list(gh.label_ops)

    second_code, out = loop.run(gh, agent=agent)
    assert second_code == 0

    assert "SKIP    #102" in out, (
        "#102 was parked and the only new comment is the agent's own park explanation, "
        f"so the second pass must skip it. stdout was:\n{out}"
    )
    # A skip writes nothing: no unpark, and no attempt counters reset.
    assert gh.label_ops == ops_after_first_pass
    assert agent_session_driver.PARK_LABEL in gh.labels_of(102)
    # And the agent was not dispatched a second time.
    assert len(agent.calls) == 1


def test_refine_that_still_needs_review_parks_after_one_pass(loop):
    """A conclusive refine may leave the authoritative tier unchanged. That is a
    human handoff, not permission for the driver to spend another attempt on the
    same inputs.
    """
    gh = FakeGitHub(
        issues=[issue(104, body=spec_body("needs-review"), labels=["P1"])],
        board_items=[board_item(104)],
    )
    agent = StubAgent(
        stream=agent_stream(final="The risk-gated change still requires human review."),
    )

    first_code, _ = loop.run(gh, agent=agent)
    assert first_code == 0
    assert agent_session_driver.PARK_LABEL in gh.labels_of(104)
    assert loop.rows("runs.jsonl")[0]["outcome"] == "parked"

    second_code, out = loop.run(gh, agent=agent)
    assert second_code == 0
    assert "SKIP    #104" in out
    assert len(agent.calls) == 1


def test_unpark_preserves_attempts_until_loop_breaker(loop):
    """Issue 183 Criterion 4:
    Unparking an issue does NOT clear attempt counters. Attempt counters accumulate
    across retries until MAX_PHASE_ATTEMPTS is reached and the loop breaker fires.
    """
    gh = FakeGitHub(
        issues=[issue(102, body="Something vague.", labels=["P2", "agent-session:attempt-2"])],
        board_items=[board_item(102)],
    )
    agent = StubAgent(
        stream=agent_stream(final="Need human input."),
        manifest=[
            {"kind": "issue_comment", "issue": 102, "body": "Parking."},
            {"kind": "label", "issue": 102, "add": [agent_session_driver.PARK_LABEL]},
        ],
    )

    # Pass 1: attempts 2 -> 3, agent runs and parks
    code1, out1 = loop.run(gh, agent=agent, argv=["--max-phase-attempts", "3"])
    assert code1 == 0
    assert "agent-session:attempt-3" in gh.labels_of(102)

    # Human comment unparks issue 102
    gh.add_comment(102, "alice", "Please try again with this info.", created_at="2099-01-01T00:00:00Z")

    # Pass 2: detects human comment and unparks #102
    code2, out2 = loop.run(gh, agent=agent, argv=["--max-phase-attempts", "3"])
    assert code2 == 0
    assert "UNPARK  #102  new comment from @alice" in out2

    # Pass 3: attempts is 3 >= max_phase_attempts (3) -> loop breaker fires
    code3, out3 = loop.run(gh, agent=agent, argv=["--max-phase-attempts", "3"])
    assert code3 == 0
    assert "MAX_PHASE_ATTEMPTS (3) reached for phase triage" in out3


def test_discussion_note_failure_is_reported_in_run_output(loop, monkeypatch):
    """Issue 211 Criterion 3: WHEN posting a discussion note fails, THE SYSTEM
    SHALL record the failure in the run's output rather than swallowing it."""
    gh = FakeGitHub(
        issues=[issue(101, body=spec_body("auto-ok"), labels=["P1"])],
        prs=[
            pr(
                201,
                body=gate_body(101, verdict="eligible-for-auto-merge", ci_row="2/2 pass @ abc1234"),
                closes=[101],
                head_oid="abc1234def5678000000000000000000000000ff",
                checks=[("lint", "pass"), ("test", "pass")],
                threads=[True],
            )
        ],
        board_items=[board_item(101)],
    )
    agent = StubAgent(stream=agent_stream(final="Graded.", cost=1.0))
    monkeypatch.setattr("agent_sessions.driver.discussion_manager.post_start", lambda **kw: False)
    monkeypatch.setattr("agent_sessions.driver.discussion_manager.post_finish", lambda **kw: False)

    code, out = loop.run(gh, agent=agent)
    assert code == 0
    assert "NOTE: could not post start discussion note" in out
    assert "NOTE: could not post finish discussion note" in out


# --- case 5: the credential split (#191) ------------------------------------


def test_the_driver_opens_the_pr_the_agent_recorded(loop):
    """The agent cannot call `gh pr create`. It records the PR, and the driver --
    holding the write credential -- pushes the branch and opens it, in that order.

    This is the pass that makes the split load-bearing rather than decorative: the
    PR the gate then grades is one the driver created.
    """
    head = NEW_PR_HEAD
    gh = FakeGitHub(
        issues=[issue(105, body=spec_body("auto-ok"), labels=["P1"])],
        board_items=[board_item(105)],
    )
    agent = StubAgent(
        stream=agent_stream(final="Implemented and graded.", cost=2.0),
        manifest=[
            {"kind": "push", "branch": "feat/105-thing"},
            {
                "kind": "pr_create",
                "head": "feat/105-thing",
                "title": "feat: the thing",
                "body": gate_body(105, verdict="eligible-for-auto-merge", ci_row=f"1/1 pass @ {head[:7]}"),
            },
        ],
    )

    code, out = loop.run(gh, agent=agent)

    assert code == 0
    assert "  writes   2/2 applied by the driver" in out

    # The branch went up before the PR referenced it, on an explicit refspec.
    assert ["push", "--set-upstream", "origin", "feat/105-thing:refs/heads/feat/105-thing"] in gh.git_calls
    assert [kind for kind, _ in gh.write_calls] == ["pr_create"]

    # And the gate graded the PR the driver just made.
    (row,) = loop.rows("runs.jsonl")
    assert row["outcome"] == "gate-eligible"
    assert row["pr"].endswith("/pull/900")
    assert row["writes"] == {"recorded": 2, "applied": 2, "ok": True}


def test_the_agent_is_invoked_with_a_credential_that_cannot_write(loop):
    """The driver installs the write token in its *own* environment so `gh` inherits
    it. The property that matters is that the child's environment, derived from that
    same environment, does not carry it."""
    gh = FakeGitHub(issues=[issue(106, body=spec_body("auto-ok"), labels=["P1"])], board_items=[board_item(106)])
    agent = StubAgent()

    loop.run(gh, agent=agent)

    parent = agent.env_at_call
    assert parent["GH_TOKEN"] == WRITE_TOKEN, "the driver's own writes were not on the write credential"

    child = credentials.agent_env(parent, credentials.resolve(parent))
    assert child["GH_TOKEN"] == READ_TOKEN
    assert WRITE_TOKEN not in child.values(), f"the agent inherited a write-capable credential: {child}"

    # And it was told where to record what it cannot write itself.
    argv = agent.calls[0]
    writes_file = Path(argv[argv.index("--writes-file") + 1])
    assert writes_file.parent == loop.run_dir(106)
    assert "write manifest" in (loop.run_dir(106) / "prompt.txt").read_text(encoding="utf-8")


def test_a_manifest_with_an_unknown_kind_applies_nothing(loop):
    """All-or-nothing. The valid comment ahead of the bad entry is not applied
    either, because a manifest the driver does not fully understand is one whose
    author's intent it does not fully understand."""
    gh = FakeGitHub(issues=[issue(107, body="Vague.", labels=["P2"])], board_items=[board_item(107)])
    agent = StubAgent(
        stream=agent_stream(final="Tried to merge itself.", cost=0.1),
        manifest=[
            {"kind": "issue_comment", "issue": 107, "body": "A perfectly good comment."},
            {"kind": "merge_pr", "pr": 900},
        ],
    )

    code, out = loop.run(gh, agent=agent)

    assert code == 0
    assert gh.write_calls == [], "a rejected manifest still reached GitHub"
    assert "WRITE REJECTED" in out and "merge_pr" in out

    (row,) = loop.rows("runs.jsonl")
    assert "write manifest rejected" in row["reason"]
    assert row["writes"] == {"recorded": 2, "applied": 0, "ok": False}


def test_a_manifest_cannot_push_to_the_integration_branch(loop):
    gh = FakeGitHub(issues=[issue(108, body=spec_body("auto-ok"), labels=["P1"])], board_items=[board_item(108)])
    agent = StubAgent(manifest=[{"kind": "push", "branch": "main"}])

    _, out = loop.run(gh, agent=agent)

    assert ["push", "--set-upstream", "origin", "main:refs/heads/main"] not in gh.git_calls
    assert "WRITE REJECTED" in out

def test_a_missing_credential_stops_the_run_rather_than_falling_back(loop):
    """No degraded mode. The driver runs under its own account or it does not run --
    because the fallback is reached by *omission* (an unexported variable, a cron with
    a clean environment), and its result is a write attributed to a human."""
    gh = FakeGitHub(issues=[issue(109, body=spec_body("auto-ok"), labels=["P1"])], board_items=[board_item(109)])

    for var in (credentials.READ_TOKEN_VAR, credentials.WRITE_TOKEN_VAR, credentials.LOGIN_VAR):
        loop.monkeypatch.setenv(credentials.READ_TOKEN_VAR, READ_TOKEN)
        loop.monkeypatch.setenv(credentials.WRITE_TOKEN_VAR, WRITE_TOKEN)
        loop.monkeypatch.setenv(credentials.LOGIN_VAR, DRIVER_LOGIN)
        loop.monkeypatch.delenv(var, raising=False)

        with pytest.raises(SystemExit) as excinfo:
            loop.run(gh, argv=["--dry-run"])
        assert excinfo.value.code == 2, f"missing {var} did not stop the run"
        assert gh.write_calls == []


def test_a_token_belonging_to_a_human_stops_the_run(loop):
    """The whole point of a dedicated account is that nothing is written as Les. A
    token pasted into the wrong slot is the likeliest way that happens, and it is
    invisible without asking GitHub whose token it is."""
    gh = FakeGitHub(
        issues=[issue(109, body=spec_body("auto-ok"), labels=["P1"])],
        board_items=[board_item(109)],
        logins={READ_TOKEN: DRIVER_LOGIN, WRITE_TOKEN: HUMAN_LOGIN},
    )

    with pytest.raises(SystemExit) as excinfo:
        loop.run(gh, argv=["--dry-run"])

    assert excinfo.value.code == 2
    assert gh.write_calls == []


def test_a_human_read_token_stops_the_run_too(loop):
    gh = FakeGitHub(
        issues=[issue(109, body=spec_body("auto-ok"), labels=["P1"])],
        board_items=[board_item(109)],
        logins={READ_TOKEN: HUMAN_LOGIN, WRITE_TOKEN: DRIVER_LOGIN},
    )

    with pytest.raises(SystemExit) as excinfo:
        loop.run(gh, argv=["--dry-run"])

    assert excinfo.value.code == 2


def test_the_resolved_identity_is_reported(loop):
    gh = FakeGitHub(issues=[issue(109, body=spec_body("auto-ok"), labels=["P1"])], board_items=[board_item(109)])

    _, out = loop.run(gh, argv=["--dry-run"])

    assert f"identity: acting as {DRIVER_LOGIN}" in out


def test_a_human_comment_still_unparks(loop):
    """The bot-login set must not swallow the signal it exists to disambiguate."""
    gh = FakeGitHub(
        issues=[issue(102, body="Vague.", labels=["P2", agent_session_driver.PARK_LABEL],
                      comments=[comment(DRIVER_LOGIN, "Parking: unclear."),
                                comment(HUMAN_LOGIN, "Do the first reading.")])],
        board_items=[board_item(102)],
    )

    _, out = loop.run(gh, argv=["--dry-run"])

    assert "UNPARK" in out.upper(), f"a real human reply did not unpark the issue:\n{out}"




def test_build_prompt_no_longer_instructs_a_github_write(loop):
    """Issue #191's named check for criterion 2: the prompt used to tell the agent to
    run `gh issue comment` and `label_manager.py park`, both of which its token now
    refuses. An instruction that cannot succeed is worse than none -- the agent
    retries it and the park explanation never appears."""
    prompt = agent_session_driver.build_prompt(
        "https://github.com/owner/repo/issues/42", "execute", Path("/skill"), Path("/run/writes.jsonl")
    )

    assert "gh issue comment" not in prompt
    assert "label_manager.py" not in prompt
    assert "/run/writes.jsonl" in prompt
    assert "read-scoped" in prompt


def test_an_ssh_remote_is_called_out_at_startup(loop):
    """The fake's origin is `git@github.com:...`, so the pass exercises the warning."""
    gh = FakeGitHub(issues=[issue(111, body=spec_body("auto-ok"), labels=["P1"])], board_items=[board_item(111)])

    _, out = loop.run(gh, argv=["--dry-run"])

    assert "SSH remote" in out
    assert "git push" in out



def test_the_write_token_can_live_in_a_user_credentials_file(loop):
    """So it is neither typed at a prompt nor kept in the agent's working tree."""
    creds_file = loop.tmp_path / "user-config" / "credentials.env"
    creds_file.parent.mkdir(parents=True)
    creds_file.write_text(f"{credentials.WRITE_TOKEN_VAR}={WRITE_TOKEN}\n", encoding="utf-8")
    creds_file.chmod(0o600)
    loop.monkeypatch.delenv(credentials.WRITE_TOKEN_VAR, raising=False)
    loop.monkeypatch.setenv(credentials.CONFIG_FILE_VAR, str(creds_file))

    gh = FakeGitHub(issues=[issue(112, body=spec_body("auto-ok"), labels=["P1"])], board_items=[board_item(112)])
    code, out = loop.run(gh, argv=["--dry-run"])

    assert code == 0
    assert f"identity: acting as {DRIVER_LOGIN}" in out


def test_a_group_readable_credentials_file_stops_the_run(loop):
    creds_file = loop.tmp_path / "user-config" / "credentials.env"
    creds_file.parent.mkdir(parents=True)
    creds_file.write_text(f"{credentials.WRITE_TOKEN_VAR}={WRITE_TOKEN}\n", encoding="utf-8")
    creds_file.chmod(0o644)
    loop.monkeypatch.setenv(credentials.CONFIG_FILE_VAR, str(creds_file))

    gh = FakeGitHub(issues=[issue(112, body=spec_body("auto-ok"), labels=["P1"])], board_items=[board_item(112)])
    with pytest.raises(SystemExit) as excinfo:
        loop.run(gh, argv=["--dry-run"])
    assert excinfo.value.code == 2


def test_a_project_env_still_wins_over_the_user_file(loop):
    """Project configuration is the more specific of the two, and an operator
    overriding for one repo should not have to edit their global file."""
    creds_file = loop.tmp_path / "user-config" / "credentials.env"
    creds_file.parent.mkdir(parents=True)
    creds_file.write_text(f"{credentials.LOGIN_VAR}=some-other-account\n", encoding="utf-8")
    creds_file.chmod(0o600)
    loop.monkeypatch.setenv(credentials.CONFIG_FILE_VAR, str(creds_file))

    gh = FakeGitHub(issues=[issue(112, body=spec_body("auto-ok"), labels=["P1"])], board_items=[board_item(112)])
    code, out = loop.run(gh, argv=["--dry-run"])

    assert code == 0
    assert f"identity: acting as {DRIVER_LOGIN}" in out


def test_a_write_token_in_a_committable_file_stops_the_run(loop):
    """The surviving hygiene check. Where the token lives is not containment -- the
    agent runs as the same uid and can read any file the driver can -- but a token in
    a file git would happily add is one `git add -A` from being published, and that
    does not un-happen."""
    env_file = loop.repo_path / ".env"
    env_file.write_text(f"{credentials.WRITE_TOKEN_VAR}={WRITE_TOKEN}\n", encoding="utf-8")
    loop.monkeypatch.chdir(loop.repo_path)

    gh = FakeGitHub(
        issues=[issue(113, body=spec_body("auto-ok"), labels=["P1"])],
        board_items=[board_item(113)],
        committable=[str(env_file.resolve())],
    )
    with pytest.raises(SystemExit) as excinfo:
        loop.run(gh, argv=["--dry-run"])
    assert excinfo.value.code == 2


def test_a_write_token_in_a_gitignored_env_beside_the_driver_is_allowed(loop):
    """The configuration Les actually keeps: both tokens in a git-ignored `.env`.
    Decided 2026-08-10 -- refusing it forbade the convenient setup and bought nothing,
    because no storage location on this host is out of the agent's reach anyway."""
    env_file = loop.repo_path / ".env"
    env_file.write_text(f"{credentials.WRITE_TOKEN_VAR}={WRITE_TOKEN}\n", encoding="utf-8")
    loop.monkeypatch.chdir(loop.repo_path)
    loop.monkeypatch.delenv(credentials.WRITE_TOKEN_VAR, raising=False)

    gh = FakeGitHub(issues=[issue(113, body=spec_body("auto-ok"), labels=["P1"])], board_items=[board_item(113)])
    code, out = loop.run(gh, argv=["--dry-run"])

    assert code == 0
    assert f"identity: acting as {DRIVER_LOGIN}" in out


def test_the_agent_still_never_gets_the_write_token_from_that_env(loop):
    """The split is what survives the relaxation: the token being readable *on disk*
    is not the same as it being handed over. The child's environment stays read-only,
    so every cooperative path is still contained."""
    env_file = loop.repo_path / ".env"
    env_file.write_text(f"{credentials.WRITE_TOKEN_VAR}={WRITE_TOKEN}\n", encoding="utf-8")
    loop.monkeypatch.chdir(loop.repo_path)
    loop.monkeypatch.delenv(credentials.WRITE_TOKEN_VAR, raising=False)

    gh = FakeGitHub(issues=[issue(114, body=spec_body("auto-ok"), labels=["P1"])], board_items=[board_item(114)])
    agent = StubAgent()
    loop.run(gh, agent=agent)

    child = credentials.agent_env(agent.env_at_call, credentials.resolve(agent.env_at_call))
    assert child["GH_TOKEN"] == READ_TOKEN
    assert WRITE_TOKEN not in child.values()

def test_pr_with_merge_conflict_is_eligible_for_fix_conflict(loop):
    gh = FakeGitHub(
        issues=[issue(101, body=spec_body("auto-ok"), labels=["P1"])],
        prs=[
            pr(
                201,
                closes=[101],
                merge_state_status="DIRTY",
                mergeable="CONFLICTING",
            )
        ],
        board_items=[board_item(101)],
    )
    agent = StubAgent(stream=agent_stream(final="Fixed conflict.", cost=1.23))

    code, out = loop.run(gh, agent=agent)

    assert code == 0
    assert "ELIGIBLE #101  tier: auto-ok (Priority 1: Unblock - fix_conflict)" in out


# --- C5: the oracle must read the gate block, not the whole PR body -----------


def test_prose_above_the_gate_block_cannot_supply_a_gate_row(loop):
    """The gate block is the channel. Everything else in the body is prose.

    `gate.extract_gate` exists to find the block, and `test_gate.py` exercises
    `classify(extract_gate(body))` at every one of its call sites. Production called
    `classify(body)` -- so the tested path and the run path differed **at the oracle**,
    and `gate_fields` harvested every `^key: value` line anywhere in the body.

    First occurrence wins, and an ordinary PR summary sits above the gate block. So a
    run whose gate block honestly voted `human-merge-required` was classified
    `gate-eligible` because the phrase `verdict: eligible-for-auto-merge` appeared in
    its own summary -- and that difference decides whether the issue is parked for a
    human or labelled merge-ready.

    Nothing exotic is needed to reach it. A PR that quotes a previous run's verdict
    while explaining what it fixed is a PR about this harness.
    """
    head = "abc1234def5678000000000000000000000000ff"
    gh = FakeGitHub(
        issues=[issue(101, body=spec_body("auto-ok"), labels=["P1"])],
        prs=[
            pr(
                201,
                body=gate_body(
                    101,
                    verdict="human-merge-required",
                    ci_row="2/2 pass @ abc1234",
                    reason="one reviewer thread is still open",
                    prose=(
                        "## Summary\n\n"
                        "The run before this one recorded\n\n"
                        "verdict: eligible-for-auto-merge\n\n"
                        "against a stale head, which is what this PR fixes."
                    ),
                ),
                closes=[101],
                head_oid=head,
                checks=[("lint", "pass"), ("test", "pass")],
                threads=[True],
                review_requests=1,
                reviews=1,
            )
        ],
        board_items=[board_item(101)],
    )

    code, out = loop.run(gh, agent=StubAgent(stream=agent_stream()))

    assert code == 0
    assert "outcome  gate-human" in out, (
        "the gate block voted human-merge-required; a verdict quoted in the summary "
        f"must not override it. Got:\n{out}"
    )
    assert loop.rows("runs.jsonl")[0]["outcome"] == "gate-human"

    # gate-eligible and gate-human route differently, which is the cost of getting it
    # wrong: one labels the PR merge-ready, the other parks the issue for a human.
    assert agent_session_driver.MERGE_READY_LABEL not in gh.labels_of(101)
    assert agent_session_driver.PARK_LABEL in gh.labels_of(101)


def test_the_recorded_gate_artifact_is_the_block_and_not_the_whole_body(loop):
    """`gate.yaml` is the run's provenance, read by a human at the merge gate.

    `classify` returns the text it was handed as `gate`, and the driver writes that to
    the run directory. Handed the whole body, it recorded the entire PR description --
    on a real PR, 2167 bytes of summary and design notes in place of a 305-byte block.
    """
    head = "abc1234def5678000000000000000000000000ff"
    gh = FakeGitHub(
        issues=[issue(101, body=spec_body("auto-ok"), labels=["P1"])],
        prs=[
            pr(
                201,
                body=gate_body(
                    101,
                    verdict="eligible-for-auto-merge",
                    ci_row="2/2 pass @ abc1234",
                    prose="## Summary\n\nRewrites the widget layer.",
                ),
                closes=[101],
                head_oid=head,
                checks=[("lint", "pass"), ("test", "pass")],
                threads=[True],
                review_requests=1,
                reviews=1,
            )
        ],
        board_items=[board_item(101)],
    )

    loop.run(gh, agent=StubAgent(stream=agent_stream()))

    recorded = (loop.run_dir(101) / "gate.yaml").read_text(encoding="utf-8")
    assert recorded.startswith("verdict:"), f"gate.yaml is not the gate block:\n{recorded}"
    assert "Rewrites the widget layer" not in recorded
    assert "## Merge gate" not in recorded


def test_a_zero_budget_does_not_reclassify_a_free_run_as_budget_exhausted(loop):
    """`gate.budget_reclass` guards on `budget > 0`. The inline copy did not.

    `--max-budget-usd 0` is accepted -- the flag is a bare `type=float` with no
    lower bound, and `MAX_BUDGET_USD=0` in the environment reaches the same place.
    With a zero ceiling the inline rule read `cost >= 0 * 0.95`, true for every run
    including one that spent nothing, so any verdict-less outcome was relabelled
    `budget-exhausted` and reported as having spent $0.0 of $0.0.

    That is not cosmetic: `budget-exhausted` is one of the outcomes that stops the
    loop, on the reasoning that the next issue inherits the same too-small ceiling.
    A misfire here halts a burndown and blames the budget.

    The tested function has said `budget > 0` since it was written; it was simply
    never the one running.
    """
    gh = FakeGitHub(
        issues=[issue(101, body=spec_body("auto-ok"), labels=["P1"])],
        prs=[],
        board_items=[board_item(101)],
    )
    agent = StubAgent(stream=agent_stream(final="Opened nothing.", cost=0.0, session="sess-z"))

    code, out = loop.run(gh, agent=agent, argv=["--max-budget-usd", "0"])

    assert code == 0
    assert "budget-exhausted" not in out, (
        "a run that spent nothing under a zero ceiling is not budget-exhausted; "
        f"got:\n{out}"
    )
    assert loop.rows("runs.jsonl")[0]["outcome"] != "budget-exhausted"


# --- X4: --classify-only, the recovery path with no coverage at all -----------
#
# `--classify-only` is what an operator reaches for *after* a run dies mid-flight;
# `lifecycle.py` prints it as the recovery instruction three times. It had no test.
# Everything below is observed behaviour, not intent -- including one line that is
# not true, which is noted where it shows up rather than pinned as correct.


def test_classify_only_grades_the_pr_and_parks_without_invoking_an_agent(loop):
    """The recovery path reaches the same oracle, so it needs the same extraction.

    Confirms it too reads the gate block rather than the whole body: the PR's summary
    quotes `verdict: eligible-for-auto-merge` while the block votes
    `human-merge-required`, and the recovery verdict follows the block.
    """
    head = "abc1234def5678000000000000000000000000ff"
    gh = FakeGitHub(
        issues=[issue(101, body=spec_body("auto-ok"), labels=["P1"])],
        prs=[
            pr(
                201,
                body=gate_body(
                    101,
                    verdict="human-merge-required",
                    ci_row="2/2 pass @ abc1234",
                    reason="a reviewer thread is open",
                    prose="## Summary\n\nAn earlier attempt claimed\n\nverdict: eligible-for-auto-merge",
                ),
                closes=[101],
                head_oid=head,
                checks=[("lint", "pass"), ("test", "pass")],
                threads=[True],
                review_requests=1,
                reviews=1,
            )
        ],
        board_items=[board_item(101)],
    )
    agent = StubAgent()

    code, out = loop.run(gh, agent=agent, argv=["--classify-only", "101"])

    assert code == 0
    assert "== classify-only #101 ==" in out
    assert agent.calls == [], "recovery classifies what already happened; it runs nothing"
    assert "outcome  gate-human" in out, out
    assert agent_session_driver.PARK_LABEL in gh.labels_of(101)


def test_classify_only_recovers_cost_and_session_from_the_dead_runs_stream(loop):
    """The reason the flag exists: a run whose stream survived its process."""
    head = "abc1234def5678000000000000000000000000ff"
    rundir = loop.state_dir / "runs" / f"101-{FROZEN_TS}"
    rundir.mkdir(parents=True)
    (rundir / "stream.jsonl").write_text(
        "\n".join(json.dumps(e) for e in agent_stream(cost=7.5, session="sess-dead")) + "\n",
        encoding="utf-8",
    )
    gh = FakeGitHub(
        issues=[issue(101, body=spec_body("auto-ok"), labels=["P1"])],
        prs=[
            pr(
                201,
                body=gate_body(101, verdict="eligible-for-auto-merge", ci_row="2/2 pass @ abc1234"),
                closes=[101],
                head_oid=head,
                checks=[("lint", "pass"), ("test", "pass")],
                threads=[True],
                review_requests=1,
                reviews=1,
            )
        ],
        board_items=[board_item(101)],
    )

    code, out = loop.run(gh, agent=StubAgent(), argv=["--classify-only", "101"])

    assert code == 0
    assert "recovered from stream: cost $7.5  session sess-dead" in out
    assert "outcome  gate-eligible" in out


def test_classify_only_with_no_pr_parks_the_issue(loop):
    gh = FakeGitHub(
        issues=[issue(101, body=spec_body("auto-ok"), labels=["P1"])],
        prs=[],
        board_items=[board_item(101)],
    )

    code, out = loop.run(gh, agent=StubAgent(), argv=["--classify-only", "101"])

    assert code == 0
    assert "no open PR found for #101" in out
    assert agent_session_driver.PARK_LABEL in gh.labels_of(101)


def test_classify_only_records_the_row_it_says_it_recorded(loop):
    """The recovery path completes the ledger, which is the whole reason it exists.

    This check used to assert the *discrepancy*: `run_classify_only` ended by printing
    "recorded to runs.jsonl. Nothing was merged." and only `classify_and_record` ever
    opened `ctx.runs_log`. Park state was applied, so an operator recovering a dead run
    got the issue parked, a line saying the ledger was written, and no row for the run
    that parked it -- a hole in the per-run provenance exactly where a run died, which
    is the case you most want recorded. Les settled it in favour of recording.

    Zero coverage of `--classify-only` is why it survived; that gap was X4.
    """
    gh = FakeGitHub(
        issues=[issue(101, body=spec_body("auto-ok"), labels=["P1"])],
        prs=[],
        board_items=[board_item(101)],
    )

    code, out = loop.run(gh, agent=StubAgent(), argv=["--classify-only", "101"])

    assert code == 0
    assert "recorded to runs.jsonl" in out

    rows = loop.rows("runs.jsonl")
    assert len(rows) == 1, f"the recovery path recorded {len(rows)} row(s)"
    assert rows[0]["issue"] == 101
    assert rows[0]["repo"] == REPO
    assert rows[0]["outcome"] == "parked"
    assert rows[0]["reason"] == "no open PR found for #101"
    assert loop.rows("parked.jsonl") != [], "park state is applied, and now the two agree"


def test_the_recovered_row_carries_the_dead_runs_phase(loop):
    """`phase` is `evidence.py`'s primary grouping key, so a blank one is a lost run.

    The inflight marker is written at the start of every run and describes the run in
    flight, so the phase belongs in it -- and recovery can then report what actually
    ran rather than a blank. Without this the recovered row groups under `unknown`,
    which is the state the pre-#27 archive was in and the reason `make evidence` used
    to render every PHASE cell as `unknown`.
    """
    head = "abc1234def5678000000000000000000000000ff"
    loop.state_dir.mkdir(parents=True, exist_ok=True)
    (loop.state_dir / "inflight.json").write_text(
        json.dumps({
            "issue": 101,
            "started": FROZEN_TS,
            "run_dir": str(loop.run_dir(101)),
            "url": f"https://github.com/{REPO}/issues/101",
            "phase": "grade_gate",
        }),
        encoding="utf-8",
    )
    gh = FakeGitHub(
        issues=[issue(101, body=spec_body("auto-ok"), labels=["P1"])],
        prs=[
            pr(
                201,
                body=gate_body(101, verdict="eligible-for-auto-merge", ci_row="2/2 pass @ abc1234"),
                closes=[101],
                head_oid=head,
                checks=[("lint", "pass"), ("test", "pass")],
                threads=[True],
                review_requests=1,
                reviews=1,
            )
        ],
        board_items=[board_item(101)],
    )

    code, _ = loop.run(gh, agent=StubAgent(), argv=["--classify-only", "101"])

    assert code == 0
    rows = loop.rows("runs.jsonl")
    assert len(rows) == 1
    assert rows[0]["phase"] == "grade_gate"
    assert rows[0]["outcome"] == "gate-eligible"


def test_an_inflight_marker_without_a_phase_still_recovers(loop):
    """Control. Markers written before the phase was added must not break recovery.

    A `KeyError` here would turn the recovery path -- the thing you reach for when a run
    has already died -- into a second failure, at the worst possible moment.
    """
    loop.state_dir.mkdir(parents=True, exist_ok=True)
    (loop.state_dir / "inflight.json").write_text(
        json.dumps({"issue": 101, "started": FROZEN_TS, "run_dir": "", "url": ""}),
        encoding="utf-8",
    )
    gh = FakeGitHub(
        issues=[issue(101, body=spec_body("auto-ok"), labels=["P1"])],
        prs=[],
        board_items=[board_item(101)],
    )

    code, _ = loop.run(gh, agent=StubAgent(), argv=["--classify-only", "101"])

    assert code == 0
    rows = loop.rows("runs.jsonl")
    assert len(rows) == 1
    assert rows[0]["phase"] == "", "an unknown phase is blank, not a crash and not a guess"


def test_the_inflight_marker_names_the_phase_it_is_marking(loop):
    """The producer side of the pair above, asserted on a normal pass.

    Recovery can only report the phase if the marker carries it, and the marker is
    written by `invoke_agent` -- a different function, in a different pass, which is
    exactly the coupling that goes stale unnoticed.
    """
    gh = FakeGitHub(
        issues=[issue(101, body=spec_body("auto-ok"), labels=["P1"])],
        prs=[],
        board_items=[board_item(101)],
    )
    captured = {}

    real_unlink = Path.unlink

    def capture_then_unlink(self, *a, **kw):
        if self.name == "inflight.json" and self.is_file():
            captured["marker"] = json.loads(self.read_text(encoding="utf-8"))
        return real_unlink(self, *a, **kw)

    loop.monkeypatch.setattr(Path, "unlink", capture_then_unlink)
    loop.run(gh, agent=StubAgent(stream=agent_stream()))

    assert captured, "no inflight marker was written during the pass"
    assert captured["marker"]["phase"], "the marker carries no phase for recovery to read"
    assert captured["marker"]["issue"] == 101


@pytest.mark.parametrize("phase", ["execute", "request_review"])
def test_after_inflight_sees_a_durable_marker_before_execution(loop, phase):
    gh = FakeGitHub(
        issues=[issue(101, body=spec_body("auto-ok"), labels=["P1"])],
        prs=[pr(201, closes=[101])] if phase == "request_review" else [],
        board_items=[board_item(101)],
    )
    loop.monkeypatch.setattr("subprocess.run", gh.run)
    loop.monkeypatch.setattr("requests.post", gh.requests_post)
    ctx = agent_session_driver.preflight(
        [
            "--repo",
            REPO,
            "--repo-path",
            str(loop.repo_path),
            "--skill-dir",
            str(loop.skill_dir),
            "--state-dir",
            str(loop.state_dir),
        ]
    )
    observed: list[dict] = []

    def after_inflight():
        observed.append(json.loads(ctx.inflight_file.read_text(encoding="utf-8")))

    if phase == "execute":
        class OrderedAgent(StubAgent):
            def __call__(self, argv):
                assert observed, "backend started before after_inflight"
                return super().__call__(argv)

        loop.monkeypatch.setattr(agent_runner, "run_agent", OrderedAgent())
    else:
        real_request_review = lifecycle.run_request_review

        def ordered_request_review(*args, **kwargs):
            assert observed, "deterministic phase started before after_inflight"
            return real_request_review(*args, **kwargs)

        loop.monkeypatch.setattr(lifecycle, "run_request_review", ordered_request_review)

    agent_session_driver.invoke_agent(
        ctx,
        "101",
        phase,
        loop.repo_path,
        gh.prs,
        {},
        after_inflight=after_inflight,
    )

    assert observed[0]["issue"] == 101
    assert observed[0]["phase"] == phase


def test_after_inflight_failure_removes_marker_and_never_starts_backend(loop):
    gh = FakeGitHub(
        issues=[issue(101, body=spec_body("auto-ok"), labels=["P1"])],
        board_items=[board_item(101)],
    )
    agent = StubAgent()
    loop.monkeypatch.setattr("subprocess.run", gh.run)
    loop.monkeypatch.setattr("requests.post", gh.requests_post)
    loop.monkeypatch.setattr(agent_runner, "run_agent", agent)
    ctx = agent_session_driver.preflight(
        [
            "--repo",
            REPO,
            "--repo-path",
            str(loop.repo_path),
            "--skill-dir",
            str(loop.skill_dir),
            "--state-dir",
            str(loop.state_dir),
        ]
    )

    with pytest.raises(QueueUnavailable):
        agent_session_driver.invoke_agent(
            ctx,
            "101",
            "execute",
            loop.repo_path,
            [],
            {},
            after_inflight=lambda: (_ for _ in ()).throw(QueueUnavailable("gone")),
        )

    assert not ctx.inflight_file.exists()
    assert agent.calls == []


def _events_config(path: Path, *, busy_timeout_ms: int = 10) -> Path:
    config_path = path.parent / f"{path.name}.toml"
    config_path.write_text(
        f'''database = "{path}"
busy_timeout_ms = {busy_timeout_ms}
claim_limit = 25
claim_lease_seconds = 300
retry_base_seconds = 30
retry_max_seconds = 1800
max_body_bytes = 1048576
delivery_retention_days = 14
invalidation_retention_days = 30
boards = []

[scan]
quiet_period_seconds = 300
interval_seconds = 900
maximum_age_seconds = 3600

[polling]
projects_interval_seconds = 60
reactions_interval_seconds = 60

[[repositories]]
id = 1
owner = "owner"
name = "repo"
''',
        encoding="utf-8",
    )
    return config_path


def test_main_without_events_configuration_uses_one_legacy_scan_and_never_opens_queue(
    loop, monkeypatch
):
    gh = FakeGitHub(
        issues=[issue(101, body=spec_body("auto-ok"), labels=["P1"])],
        board_items=[board_item(101)],
    )
    calls = 0
    real_select = agent_session_driver.select_queue

    def counted_select(ctx):
        nonlocal calls
        calls += 1
        return real_select(ctx)

    monkeypatch.setattr(agent_session_driver, "select_queue", counted_select)
    monkeypatch.setattr(
        lifecycle,
        "load_queue_runtime",
        lambda _ctx: pytest.fail("legacy mode imported/opened the queue"),
        raising=False,
    )

    code, _out = loop.run(gh, argv=["--dry-run"])

    assert code == 0
    assert calls == 1


@pytest.mark.parametrize("database_state", ["absent", "locked", "corrupt", "incompatible"])
def test_configured_database_failure_logs_one_degraded_event_and_uses_legacy_scan(
    loop, database_state
):
    database = loop.tmp_path / f"{database_state}.sqlite3"
    locker = None
    if database_state == "corrupt":
        database.write_bytes(b"not a sqlite database")
    elif database_state in {"locked", "incompatible"}:
        QueueStore.migrate(database, busy_timeout_ms=10)
        store = QueueStore.open(database, busy_timeout_ms=10)
        store.register_repositories((RepositoryIdentity(1, "owner", "repo"),))
        if database_state == "locked":
            locker = sqlite3.connect(database, isolation_level=None)
            locker.execute("BEGIN EXCLUSIVE")
        else:
            store.connection.execute(
                "INSERT INTO schema_migrations VALUES (?, ?)",
                (CURRENT_SCHEMA_VERSION + 1, "2026-08-25T12:00:00Z"),
            )
    settings = _events_config(database, busy_timeout_ms=1)
    gh = FakeGitHub(
        issues=[issue(101, body=spec_body("auto-ok"), labels=["P1"])],
        board_items=[board_item(101)],
    )

    try:
        code, out = loop.run(gh, argv=["--events-config", str(settings), "--dry-run"])
    finally:
        if locker is not None:
            locker.rollback()
            locker.close()

    assert code == 0
    assert out.count("== select ==") == 1
    degraded = [
        line for line in loop.last_stderr.splitlines() if '"event": "driver_queue_degraded"' in line
    ]
    assert len(degraded) == 1


@pytest.mark.anyio
async def test_signed_pr_delivery_reconciles_live_state_and_conditionally_acknowledges_after_inflight(
    loop, monkeypatch
):
    import httpx

    database = loop.tmp_path / "integration.sqlite3"
    QueueStore.migrate(database, busy_timeout_ms=100)
    receiver_store = QueueStore.open(database, busy_timeout_ms=100)
    receiver_store.register_repositories((RepositoryIdentity(1, "owner", "repo"),))
    assert receiver_store.acquire_scan_lease(
        1,
        worker_id="seed",
        lease_until=FROZEN + timedelta(minutes=1),
        now=FROZEN,
    )
    receiver_store.finish_scan(1, worker_id="seed", succeeded=True, now=FROZEN)
    settings = _events_config(database, busy_timeout_ms=100)
    loaded_config = events_config.load(settings)
    secret = b"integration-secret"
    raw = json.dumps(
        {
            "action": "synchronize",
            "repository": {"id": 1},
            "pull_request": {"number": 201},
        },
        separators=(",", ":"),
    ).encode()
    signature = "sha256=" + hmac.new(secret, raw, hashlib.sha256).hexdigest()
    app = create_app(config=loaded_config, store=receiver_store, webhook_secret=secret)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/github/webhook",
            content=raw,
            headers={
                "X-GitHub-Delivery": "phase-3-integration",
                "X-GitHub-Event": "pull_request",
                "X-Hub-Signature-256": signature,
            },
        )
    assert response.status_code == 202

    gh = FakeGitHub(
        issues=[issue(101, body=spec_body("auto-ok"), labels=["P1"])],
        prs=[pr(201, closes=[101], checks=[("test", "fail")])],
        board_items=[board_item(101)],
    )
    real_resolver = events_driver.LiveTargetResolver

    class RacingResolver:
        def __init__(self, **kwargs):
            self.real = real_resolver(**kwargs)

        def resolve(self, repository, current_claim):
            resolved = self.real.resolve(repository, current_claim)
            receiver_store.enqueue_synthetic(
                "test-race",
                "newer-generation",
                (Invalidation(1, "pull_request", "201", "newer"),),
                now=FROZEN + timedelta(seconds=1),
            )
            return resolved

    monkeypatch.setattr(events_driver, "LiveTargetResolver", RacingResolver)
    agent = StubAgent(stream=agent_stream(final="Fixed CI.", cost=0.5))

    code, out = loop.run(
        gh,
        agent=agent,
        argv=["--events-config", str(settings)],
    )

    assert code == 0
    assert "Priority 1: Unblock - fix_ci" in out
    assert len(agent.calls) == 1
    assert not (loop.state_dir / "inflight.json").exists()
    row = receiver_store.connection.execute(
        "SELECT generation,lease_owner FROM dirty_targets WHERE target_kind='pull_request' AND target_key='201'"
    ).fetchone()
    assert row["generation"] == 2
    assert row["lease_owner"] is None


def test_selected_ack_database_failure_falls_back_before_starting_one_agent(
    loop, monkeypatch
):
    database = loop.tmp_path / "ack-failure.sqlite3"
    QueueStore.migrate(database, busy_timeout_ms=100)
    store = QueueStore.open(database, busy_timeout_ms=100)
    store.register_repositories((RepositoryIdentity(1, "owner", "repo"),))
    assert store.acquire_scan_lease(
        1,
        worker_id="seed",
        lease_until=FROZEN + timedelta(minutes=1),
        now=FROZEN,
    )
    store.finish_scan(1, worker_id="seed", succeeded=True, now=FROZEN)
    store.enqueue_synthetic(
        "test",
        "ack-failure",
        (Invalidation(1, "issue", "101", "test"),),
        now=FROZEN,
    )
    settings = _events_config(database, busy_timeout_ms=100)
    gh = FakeGitHub(
        issues=[issue(101, body=spec_body("auto-ok"), labels=["P1"])],
        board_items=[board_item(101)],
    )
    agent = StubAgent(stream=agent_stream(final="Fallback run."))
    monkeypatch.setattr(
        QueueStore,
        "acknowledge",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            QueueUnavailable("ack unavailable")
        ),
    )

    code, out = loop.run(
        gh,
        agent=agent,
        argv=["--events-config", str(settings)],
    )

    assert code == 0
    assert out.count("== select ==") == 1
    assert len(agent.calls) == 1
    assert not (loop.state_dir / "inflight.json").exists()
    degraded = [
        line
        for line in loop.last_stderr.splitlines()
        if '"event": "driver_queue_degraded"' in line
    ]
    assert len(degraded) == 1
    row = store.connection.execute(
        "SELECT lease_owner FROM dirty_targets WHERE target_kind='issue' AND target_key='101'"
    ).fetchone()
    assert row["lease_owner"] is not None


def test_selected_ack_failure_at_attempt_two_does_not_loop_break_before_backend(
    loop, monkeypatch
):
    database = loop.tmp_path / "ack-attempt.sqlite3"
    QueueStore.migrate(database, busy_timeout_ms=100)
    store = QueueStore.open(database, busy_timeout_ms=100)
    store.register_repositories((RepositoryIdentity(1, "owner", "repo"),))
    assert store.acquire_scan_lease(
        1,
        worker_id="seed",
        lease_until=FROZEN + timedelta(minutes=1),
        now=FROZEN,
    )
    store.finish_scan(1, worker_id="seed", succeeded=True, now=FROZEN)
    store.enqueue_synthetic(
        "test",
        "ack-attempt",
        (Invalidation(1, "issue", "101", "test"),),
        now=FROZEN,
    )
    settings = _events_config(database, busy_timeout_ms=100)
    gh = FakeGitHub(
        issues=[
            issue(
                101,
                body=spec_body("auto-ok"),
                labels=["P1", "agent-session:attempt-2"],
            )
        ],
        board_items=[board_item(101)],
    )
    agent = StubAgent(stream=agent_stream(final="Fallback run."))
    monkeypatch.setattr(
        QueueStore,
        "acknowledge",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            QueueUnavailable("ack unavailable")
        ),
    )

    code, out = loop.run(
        gh,
        agent=agent,
        argv=["--events-config", str(settings)],
    )

    assert code == 0
    assert len(agent.calls) == 1
    assert "MAX_PHASE_ATTEMPTS" not in out
    attempt_ops = [operation for operation in gh.label_ops if operation[0] == "attempt"]
    assert attempt_ops == [("attempt", "101", "3")]
    assert not loop.rows("parked.jsonl")[-1]["reason"].startswith(
        "parked by loop breaker:"
    )


@pytest.mark.parametrize("failure_point", ["release", "finish_scan"])
def test_selection_database_failure_releases_acquired_lock_before_legacy_fallback(
    loop, monkeypatch, failure_point
):
    database = loop.tmp_path / f"selection-{failure_point}.sqlite3"
    QueueStore.migrate(database, busy_timeout_ms=100)
    store = QueueStore.open(database, busy_timeout_ms=100)
    store.register_repositories((RepositoryIdentity(1, "owner", "repo"),))
    settings = _events_config(database, busy_timeout_ms=100)
    issues = [
        issue(101, body=spec_body("auto-ok"), labels=["P1"]),
        issue(102, body=spec_body("auto-ok"), labels=["P1"]),
    ]
    gh = FakeGitHub(issues=issues)
    if failure_point == "release":
        assert store.acquire_scan_lease(
            1,
            worker_id="seed",
            lease_until=FROZEN + timedelta(minutes=1),
            now=FROZEN,
        )
        store.finish_scan(1, worker_id="seed", succeeded=True, now=FROZEN)
        store.enqueue_synthetic(
            "test",
            "two-claims",
            (
                Invalidation(1, "issue", "101", "test"),
                Invalidation(1, "issue", "102", "test"),
            ),
            now=FROZEN,
        )

        class Resolver:
            def __init__(self, **_kwargs):
                pass

            def resolve(self, _repository, current_claim):
                current_issue = next(
                    item
                    for item in issues
                    if str(item["number"]) == current_claim.target_key
                )
                return ResolvedTarget(current_claim, (current_issue,), (), ())

        monkeypatch.setattr(events_driver, "LiveTargetResolver", Resolver)
        real_release = QueueStore.release

        def failing_release(self, current_claim):
            if current_claim.target_key == "102":
                raise QueueUnavailable("release unavailable")
            return real_release(self, current_claim)

        monkeypatch.setattr(QueueStore, "release", failing_release)
    else:
        real_finish = QueueStore.finish_scan

        def failing_finish(self, repository_id, **kwargs):
            if kwargs["worker_id"] != "seed":
                raise QueueUnavailable("finish unavailable")
            return real_finish(self, repository_id, **kwargs)

        monkeypatch.setattr(QueueStore, "finish_scan", failing_finish)

    real_select = agent_session_driver.select_queue
    fallback_calls = 0

    def fallback_select(ctx):
        nonlocal fallback_calls
        fallback_calls += 1
        assert locks.CURRENT_LOCK_ISSUE is None
        return real_select(ctx)

    monkeypatch.setattr(agent_session_driver, "select_queue", fallback_select)
    agent = StubAgent(stream=agent_stream(final="Fallback run."))

    code, _out = loop.run(
        gh,
        agent=agent,
        argv=["--events-config", str(settings)],
        board=False,
    )

    assert code == 0
    assert fallback_calls == 1
    assert len(agent.calls) == 1


@pytest.mark.parametrize(
    ("override_args", "labels"),
    [
        (["--issue", "101"], ["P1"]),
        (
            ["--retry", "101"],
            ["P1", agent_session_driver.PARK_LABEL],
        ),
    ],
)
def test_manual_override_uses_targeted_scan_without_a_dirty_claim(
    loop, override_args, labels
):
    database = loop.tmp_path / f"manual-{override_args[0][2:]}.sqlite3"
    QueueStore.migrate(database, busy_timeout_ms=100)
    store = QueueStore.open(database, busy_timeout_ms=100)
    store.register_repositories((RepositoryIdentity(1, "owner", "repo"),))
    assert store.acquire_scan_lease(
        1,
        worker_id="seed",
        lease_until=FROZEN + timedelta(minutes=1),
        now=FROZEN,
    )
    store.finish_scan(1, worker_id="seed", succeeded=True, now=FROZEN)
    settings = _events_config(database, busy_timeout_ms=100)
    gh = FakeGitHub(
        issues=[issue(101, body=spec_body("auto-ok"), labels=labels)],
        board_items=[board_item(101)],
    )
    agent = StubAgent(stream=agent_stream(final="Manual run."))

    code, _out = loop.run(
        gh,
        agent=agent,
        argv=["--events-config", str(settings), *override_args],
    )

    assert code == 0
    assert len(agent.calls) == 1


def test_manual_override_does_not_acknowledge_an_unrelated_dirty_claim(loop):
    database = loop.tmp_path / "manual-unrelated.sqlite3"
    QueueStore.migrate(database, busy_timeout_ms=100)
    store = QueueStore.open(database, busy_timeout_ms=100)
    store.register_repositories((RepositoryIdentity(1, "owner", "repo"),))
    assert store.acquire_scan_lease(
        1,
        worker_id="seed",
        lease_until=FROZEN + timedelta(minutes=1),
        now=FROZEN,
    )
    store.finish_scan(1, worker_id="seed", succeeded=True, now=FROZEN)
    store.enqueue_synthetic(
        "test",
        "unrelated",
        (Invalidation(1, "issue", "102", "test"),),
        now=FROZEN,
    )
    settings = _events_config(database, busy_timeout_ms=100)
    gh = FakeGitHub(
        issues=[
            issue(101, body=spec_body("auto-ok"), labels=["P1"]),
            issue(102, body="Unrelated.", labels=["P1"]),
        ],
        board_items=[board_item(101), board_item(102)],
    )
    agent = StubAgent(stream=agent_stream(final="Manual run."))

    code, _out = loop.run(
        gh,
        agent=agent,
        argv=["--events-config", str(settings), "--issue", "101"],
    )

    assert code == 0
    assert len(agent.calls) == 1
    row = store.connection.execute(
        "SELECT generation,lease_owner FROM dirty_targets "
        "WHERE target_kind='issue' AND target_key='102'"
    ).fetchone()
    assert (row["generation"], row["lease_owner"]) == (1, None)


def test_agent_driven_park_creates_approval_watch_and_queue_failure_does_not_change_outcome(
    loop, monkeypatch
):
    database = loop.tmp_path / "watch.sqlite3"
    QueueStore.migrate(database, busy_timeout_ms=100)
    store = QueueStore.open(database, busy_timeout_ms=100)
    store.register_repositories((RepositoryIdentity(1, "owner", "repo"),))
    assert store.acquire_scan_lease(
        1,
        worker_id="seed",
        lease_until=FROZEN + timedelta(minutes=1),
        now=FROZEN,
    )
    store.finish_scan(1, worker_id="seed", succeeded=True, now=FROZEN)
    store.enqueue_synthetic(
        "test",
        "park",
        (Invalidation(1, "issue", "102", "test"),),
        now=FROZEN,
    )
    settings = _events_config(database, busy_timeout_ms=100)
    gh = FakeGitHub(
        issues=[issue(102, body="Vague.", labels=["P1"])],
        board_items=[board_item(102)],
    )
    agent = StubAgent(
        stream=agent_stream(final="Need a human decision."),
        manifest=[{"kind": "label", "issue": 102, "add": [agent_session_driver.PARK_LABEL]}],
    )

    code, _out = loop.run(gh, agent=agent, argv=["--events-config", str(settings)])

    assert code == 0
    watches = store.list_watches(1)
    assert [(item.issue_number, item.predicate, item.parked_at) for item in watches] == [
        (102, "human_approval_since_park", FROZEN)
    ]
    assert loop.rows("runs.jsonl")[0]["outcome"] == "parked"

    store.remove_watch(1, 102)
    store.enqueue_synthetic(
        "test",
        "park-again",
        (Invalidation(1, "issue", "102", "test"),),
        now=FROZEN,
    )
    monkeypatch.setattr(
        QueueStore,
        "upsert_watch",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(QueueUnavailable("watch unavailable")),
    )
    loop.run(gh, agent=agent, argv=["--events-config", str(settings), "--retry", "102"])
    assert loop.rows("runs.jsonl")[-1]["outcome"] == "parked"


def test_agent_driven_watch_uses_actual_park_transition_time(loop, monkeypatch):
    database = loop.tmp_path / "watch-time.sqlite3"
    QueueStore.migrate(database, busy_timeout_ms=100)
    store = QueueStore.open(database, busy_timeout_ms=100)
    store.register_repositories((RepositoryIdentity(1, "owner", "repo"),))
    settings = _events_config(database, busy_timeout_ms=100)
    later = FROZEN + timedelta(minutes=10)
    gh = FakeGitHub(
        issues=[issue(102, body="Vague.", labels=["P1"])],
        board_items=[board_item(102)],
    )
    agent = StubAgent(
        stream=agent_stream(final="Need a human decision."),
        manifest=[
            {"kind": "label", "issue": 102, "add": [agent_session_driver.PARK_LABEL]}
        ],
        side_effect=lambda: monkeypatch.setattr(output, "now", lambda: later),
    )

    code, _out = loop.run(gh, agent=agent, argv=["--events-config", str(settings)])

    assert code == 0
    watches = store.list_watches(1)
    assert watches, (loop.last_stderr, loop.rows("parked.jsonl"))
    (watch,) = watches
    assert watch.parked_at == later
    assert loop.rows("parked.jsonl")[-1]["parked_at"] == "20260810T121000Z"


def test_full_scan_repairs_missing_and_stale_approval_watches(loop):
    database = loop.tmp_path / "repair.sqlite3"
    QueueStore.migrate(database, busy_timeout_ms=100)
    store = QueueStore.open(database, busy_timeout_ms=100)
    store.register_repositories((RepositoryIdentity(1, "owner", "repo"),))
    store.upsert_watch(
        ApprovalWatch(1, 999, "human_approval_since_park", FROZEN - timedelta(days=1))
    )
    settings = _events_config(database, busy_timeout_ms=100)
    gh = FakeGitHub(
        issues=[
            issue(
                102,
                body="Vague.",
                labels=["P1", agent_session_driver.PARK_LABEL],
            )
        ],
        board_items=[board_item(102)],
    )
    loop.seed_runs(
        [
            {
                "issue": 102,
                "repo": REPO,
                "phase": "triage",
                "started": FROZEN_TS,
                "outcome": "parked",
                "reason": "awaiting decision",
            }
        ]
    )

    code, _out = loop.run(
        gh,
        argv=["--events-config", str(settings), "--dry-run"],
    )

    assert code == 0
    watches = store.list_watches(1)
    assert [(item.issue_number, item.predicate) for item in watches] == [
        (102, "human_approval_since_park")
    ]


def test_failed_full_scan_unpark_preserves_approval_watch(loop):
    database = loop.tmp_path / "failed-unpark.sqlite3"
    QueueStore.migrate(database, busy_timeout_ms=100)
    store = QueueStore.open(database, busy_timeout_ms=100)
    store.register_repositories((RepositoryIdentity(1, "owner", "repo"),))
    parked_at = FROZEN - timedelta(hours=1)
    store.upsert_watch(
        ApprovalWatch(1, 102, "human_approval_since_park", parked_at)
    )
    settings = _events_config(database, busy_timeout_ms=100)

    class FailedUnparkGitHub(FakeGitHub):
        def _python(self, argv):
            if "unpark" in argv:
                self.label_calls.append(tuple(argv[2:]))
                return subprocess.CompletedProcess(
                    argv, 1, stdout="", stderr="label removal failed"
                )
            return super()._python(argv)

    gh = FailedUnparkGitHub(
        issues=[
            issue(
                102,
                body="Vague.",
                labels=["P1", agent_session_driver.PARK_LABEL],
                comments=[
                    comment(
                        HUMAN_LOGIN,
                        "Please continue.",
                        created_at="2026-08-10T11:30:00Z",
                    )
                ],
            )
        ],
        board_items=[board_item(102)],
    )

    code, _out = loop.run(
        gh,
        argv=["--events-config", str(settings), "--dry-run"],
    )

    assert code == 0
    assert agent_session_driver.PARK_LABEL in gh.labels_of(102)
    assert store.list_watches(1) == (
        ApprovalWatch(1, 102, "human_approval_since_park", parked_at),
    )


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
def test_malformed_full_scan_unpark_verification_preserves_approval_watch(
    loop, label_payload
):
    database = loop.tmp_path / "malformed-unpark.sqlite3"
    QueueStore.migrate(database, busy_timeout_ms=100)
    store = QueueStore.open(database, busy_timeout_ms=100)
    store.register_repositories((RepositoryIdentity(1, "owner", "repo"),))
    parked_at = FROZEN - timedelta(hours=1)
    original_watch = ApprovalWatch(
        1, 102, "human_approval_since_park", parked_at
    )
    store.upsert_watch(original_watch)
    settings = _events_config(database, busy_timeout_ms=100)

    class MalformedUnparkGitHub(FakeGitHub):
        def _python(self, argv):
            if "unpark" in argv:
                self.label_calls.append(tuple(argv[2:]))
                return subprocess.CompletedProcess(
                    argv, 1, stdout="", stderr="label removal failed"
                )
            return super()._python(argv)

        def _gh(self, argv):
            if (
                argv[1:3] == ["issue", "view"]
                and "--json" in argv
                and argv[argv.index("--json") + 1] == "labels"
            ):
                return subprocess.CompletedProcess(
                    argv, 0, stdout=json.dumps(label_payload), stderr=""
                )
            return super()._gh(argv)

    gh = MalformedUnparkGitHub(
        issues=[
            issue(
                102,
                body="Vague.",
                labels=["P1", agent_session_driver.PARK_LABEL],
                comments=[
                    comment(
                        HUMAN_LOGIN,
                        "Please continue.",
                        created_at="2026-08-10T11:30:00Z",
                    )
                ],
            )
        ],
        board_items=[board_item(102)],
    )

    code, _out = loop.run(
        gh,
        argv=["--events-config", str(settings), "--dry-run"],
    )

    assert code == 0
    assert store.list_watches(1) == (original_watch,)


def test_failed_full_issue_snapshot_retains_watches_and_last_success(loop):
    database = loop.tmp_path / "failed-scan.sqlite3"
    QueueStore.migrate(database, busy_timeout_ms=100)
    store = QueueStore.open(database, busy_timeout_ms=100)
    store.register_repositories((RepositoryIdentity(1, "owner", "repo"),))
    previous_success = FROZEN - timedelta(hours=2)
    assert store.acquire_scan_lease(
        1,
        worker_id="seed",
        lease_until=previous_success + timedelta(minutes=1),
        now=previous_success,
    )
    store.finish_scan(1, worker_id="seed", succeeded=True, now=previous_success)
    store.upsert_watch(
        ApprovalWatch(1, 102, "human_approval_since_park", previous_success)
    )
    settings = _events_config(database, busy_timeout_ms=100)

    class FailedIssueSnapshotGitHub(FakeGitHub):
        def _gh(self, argv):
            if argv[1:3] == ["issue", "list"]:
                return subprocess.CompletedProcess(
                    argv,
                    1,
                    stdout="",
                    stderr="HTTP 500: issue snapshot unavailable",
                )
            return super()._gh(argv)

    gh = FailedIssueSnapshotGitHub()

    code, out = loop.run(
        gh,
        argv=["--events-config", str(settings), "--dry-run"],
    )

    assert code == 0
    assert out.count("== select ==") == 1
    assert [watch.issue_number for watch in store.list_watches(1)] == [102]
    repository = store.status(now=FROZEN).repositories[0]
    assert repository.last_scan_success_at == previous_success
    assert repository.scan_lease_owner is None
    assert repository.scan_lease_until is None


@pytest.mark.parametrize(
    ("issue_count", "expected_complete"),
    [(499, True), (500, False)],
)
def test_full_issue_snapshot_treats_the_cli_limit_as_ambiguous(
    loop, issue_count, expected_complete
):
    database = loop.tmp_path / f"capped-scan-{issue_count}.sqlite3"
    QueueStore.migrate(database, busy_timeout_ms=100)
    store = QueueStore.open(database, busy_timeout_ms=100)
    store.register_repositories((RepositoryIdentity(1, "owner", "repo"),))
    previous_success = FROZEN - timedelta(hours=2)
    assert store.acquire_scan_lease(
        1,
        worker_id="seed",
        lease_until=previous_success + timedelta(minutes=1),
        now=previous_success,
    )
    store.finish_scan(1, worker_id="seed", succeeded=True, now=previous_success)
    stale_watch = ApprovalWatch(
        1, 999_999, "human_approval_since_park", previous_success
    )
    store.upsert_watch(stale_watch)
    settings = _events_config(database, busy_timeout_ms=100)
    issues = [issue(number, labels=[]) for number in range(1, issue_count + 1)]
    if not expected_complete:
        issues[0] = issue(1, body=spec_body("auto-ok"), labels=["P1"])
    gh = FakeGitHub(issues=issues)
    agent = StubAgent(stream=agent_stream(final="Capped snapshot must not run."))

    code, _out = loop.run(
        gh,
        agent=agent,
        argv=["--events-config", str(settings)],
        board=False,
    )

    assert code == 0
    assert len(agent.calls) == 0
    repository = store.status(now=FROZEN).repositories[0]
    if expected_complete:
        assert repository.last_scan_success_at == FROZEN
        assert store.list_watches(1) == ()
    else:
        assert repository.last_scan_success_at == previous_success
        assert store.list_watches(1) == (stale_watch,)
        assert locks.CURRENT_LOCK_ISSUE is None
    assert repository.scan_lease_owner is None
    assert repository.scan_lease_until is None


def test_loop_breaker_park_does_not_create_approval_watch(loop):
    database = loop.tmp_path / "loop-breaker.sqlite3"
    QueueStore.migrate(database, busy_timeout_ms=100)
    store = QueueStore.open(database, busy_timeout_ms=100)
    store.register_repositories((RepositoryIdentity(1, "owner", "repo"),))
    settings = _events_config(database, busy_timeout_ms=100)
    gh = FakeGitHub(
        issues=[
            issue(
                103,
                body=spec_body("auto-ok"),
                labels=["P1", "agent-session:attempt-3"],
            )
        ],
        board_items=[board_item(103)],
    )

    code, _out = loop.run(
        gh,
        argv=["--events-config", str(settings), "--dry-run"],
    )

    assert code == 0
    assert store.list_watches(1) == ()


def test_request_review_records_a_reviewer_request_and_spends_nothing(loop):
    """The one phase the driver executes itself, with no model call.

    Written because extracting it out of `invoke_agent` (#261 T2) broke two things the
    suite could not see: a function-local import, and the write-manifest path the branch
    records its `pr_edit` entry to. `ruff` caught both; the tests did not, because nothing
    exercised the branch at all. That is the gap, and this closes it.
    """
    head = "abc1234def5678000000000000000000000000ff"
    gh = FakeGitHub(
        issues=[issue(101, body=spec_body("auto-ok"), labels=["P1"])],
        prs=[
            pr(
                201,
                body=gate_body(101, verdict="pending", ci_row="2/2 pass @ abc1234"),
                closes=[101],
                head_oid=head,
                checks=[("lint", "pass"), ("test", "pass")],
                threads=[],
                review_requests=0,
                reviews=0,
            )
        ],
        board_items=[board_item(101)],
    )
    agent = StubAgent()

    code, out = loop.run(gh, agent=agent, argv=["--issue", "101"])

    assert code == 0
    if "request_review" not in out:
        pytest.skip("the ladder did not route this fixture to request_review")

    assert agent.calls == [], "request_review must not invoke a model"
    assert "Executing request_review deterministically" in out
    row = loop.rows("runs.jsonl")[0]
    assert row["phase"] == "request_review"
    assert row["cost_usd"] == 0.0
    assert row["session_id"] == "deterministic"
