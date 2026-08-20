"""Tests for the write manifest (issue #191).

The agent has no GitHub write capability, so it records what it wants written and
the driver executes it. This file pins the two properties that makes that safe: the
driver is a *validator*, not a pipe, and there is no manifest entry that can merge.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_sessions.driver import writes

REPO = "owner/target"


def comment_entry(**over):
    return {"kind": "issue_comment", "issue": 42, "body": "parked: needs a decision", **over}


BOARD = "owner/9"


def build(entry, scratch, repo=REPO, repo_path="/repo", board=BOARD):
    return writes.commands(entry, repo=repo, repo_path=repo_path, scratch=Path(scratch), board=board)


def flat(argv_lists):
    return [tok for argv in argv_lists for tok in argv]


# -- loading ----------------------------------------------------------------


def test_load_missing_file_is_an_empty_manifest(tmp_path: Path):
    assert writes.load(tmp_path / "nope.json") == []


def test_load_empty_file_is_an_empty_manifest(tmp_path: Path):
    p = tmp_path / "writes.json"
    p.write_text("", encoding="utf-8")
    assert writes.load(p) == []


def test_load_object_form(tmp_path: Path):
    p = tmp_path / "writes.json"
    p.write_text(json.dumps({"writes": [comment_entry()]}), encoding="utf-8")
    assert writes.load(p) == [comment_entry()]


def test_load_array_form(tmp_path: Path):
    p = tmp_path / "writes.json"
    p.write_text(json.dumps([comment_entry()]), encoding="utf-8")
    assert writes.load(p) == [comment_entry()]


def test_load_jsonl_form(tmp_path: Path):
    """The append-friendly form. An agent adding a line cannot corrupt earlier ones."""
    p = tmp_path / "writes.jsonl"
    p.write_text(json.dumps(comment_entry()) + "\n" + json.dumps(comment_entry(issue=43)) + "\n", encoding="utf-8")
    assert [e["issue"] for e in writes.load(p)] == [42, 43]


def test_load_rejects_unparseable_content(tmp_path: Path):
    p = tmp_path / "writes.json"
    p.write_text("{not json at all", encoding="utf-8")
    with pytest.raises(writes.ManifestError):
        writes.load(p)


# -- validation: the kind allowlist -----------------------------------------


def test_every_documented_kind_validates():
    for entry in writes.EXAMPLES.values():
        assert writes.validate([entry], repo=REPO, board=BOARD) == [], f"the documented example for {entry['kind']} does not validate"


def test_unknown_kind_is_rejected():
    errs = writes.validate([{"kind": "merge_pr", "pr": 7}], repo=REPO)
    assert errs and "merge_pr" in errs[0]


def test_no_kind_can_merge_a_pull_request(tmp_path: Path):
    """The strongest statement this module makes: merging is not expressible."""
    for kind, spec in writes.KINDS.items():
        argv = flat(build(writes.EXAMPLES[kind], tmp_path))
        assert "merge" not in argv, f"{kind} can reach a merge endpoint: {argv}"
        assert not any("/merge" in tok for tok in argv), f"{kind} can reach a merge endpoint: {argv}"
        assert spec is not None


def test_entry_must_be_an_object():
    assert writes.validate(["gh pr merge 7"], repo=REPO)


def test_missing_required_field_is_rejected():
    errs = writes.validate([{"kind": "issue_comment", "issue": 42}], repo=REPO)
    assert errs and "body" in errs[0]


def test_empty_body_is_rejected():
    assert writes.validate([comment_entry(body="   ")], repo=REPO)


def test_unknown_field_is_rejected():
    """An allowlist that ignores extra keys is a denylist wearing a hat."""
    errs = writes.validate([comment_entry(force=True)], repo=REPO)
    assert errs and "force" in errs[0]


# -- validation: the target cannot be moved ---------------------------------


def test_an_entry_naming_another_repo_is_rejected():
    errs = writes.validate([comment_entry(repo="attacker/elsewhere")], repo=REPO)
    assert errs


def test_issue_number_must_be_numeric():
    for bad in ("--repo", "42 --repo other/x", "", None, -1, 0, 1.5):
        assert writes.validate([comment_entry(issue=bad)], repo=REPO), f"accepted issue={bad!r}"


def test_numeric_string_issue_is_accepted():
    assert writes.validate([comment_entry(issue="42")], repo=REPO) == []


def test_every_gh_command_is_pinned_to_the_configured_repo(tmp_path: Path):
    for kind, entry in writes.EXAMPLES.items():
        for argv in build(entry, tmp_path):
            if argv[0] != "gh":
                continue
            if argv[1] == "project":
                # `gh project` is owner-scoped, not repo-scoped. Its pinning is that
                # the board comes from driver config, not from the manifest.
                assert "--repo" not in argv
                assert BOARD.split("/")[0] in argv or "--project-id" in argv
                continue
            assert "--repo" in argv, f"{kind} issued a gh command with no --repo: {argv}"
            assert argv[argv.index("--repo") + 1] == REPO, f"{kind} targeted the wrong repo: {argv}"


# -- validation: refs, labels, reviewers ------------------------------------


def test_push_to_a_protected_branch_is_rejected():
    for branch in sorted(writes.PROTECTED_BRANCHES):
        errs = writes.validate([{"kind": "push", "branch": branch}], repo=REPO)
        assert errs, f"accepted a push to {branch}"


def test_push_is_never_a_force_push(tmp_path: Path):
    argv = flat(build({"kind": "push", "branch": "feat/191-tokens"}, tmp_path))
    assert "--force" not in argv and "-f" not in argv
    assert not any(tok.startswith("+") for tok in argv), f"a leading + is a force refspec: {argv}"


def test_push_names_an_explicit_refspec(tmp_path: Path):
    """`push origin <branch>` would follow the remote's push.default; an explicit
    src:dst refspec cannot land the branch anywhere but its own name."""
    argv = flat(build({"kind": "push", "branch": "feat/x"}, tmp_path))
    assert "feat/x:refs/heads/feat/x" in argv


def test_malformed_refs_are_rejected():
    for bad in ("--force", "a..b", "-x", "", "has space", "ends.lock"):
        assert writes.validate([{"kind": "push", "branch": bad}], repo=REPO), f"accepted branch={bad!r}"


def test_label_names_that_look_like_flags_are_rejected():
    assert writes.validate([{"kind": "label", "issue": 42, "add": ["--delete-branch"]}], repo=REPO)


def test_a_label_entry_that_changes_nothing_is_rejected():
    assert writes.validate([{"kind": "label", "issue": 42}], repo=REPO)
    assert writes.validate([{"kind": "label", "issue": 42, "add": [], "remove": []}], repo=REPO)


def test_reviewer_names_that_look_like_flags_are_rejected():
    assert writes.validate([{"kind": "pr_edit", "pr": 7, "add_reviewer": ["--add-label"]}], repo=REPO)


def test_label_colour_must_be_a_hex_triplet():
    assert writes.validate([{"kind": "label_create", "name": "x", "color": "; rm -rf /"}], repo=REPO)


# -- command construction ---------------------------------------------------


def test_bodies_travel_by_file_not_by_argv(tmp_path: Path):
    """A body can be tens of kilobytes and can start with a dash. `--body-file`
    sidesteps both, and keeps the text out of the process table."""
    body = "-- looks like a flag\n" + "x" * 5000
    argv = flat(build(comment_entry(body=body), tmp_path))
    assert "--body-file" in argv
    assert body not in argv
    written = (tmp_path / Path(argv[argv.index("--body-file") + 1]).name).read_text(encoding="utf-8")
    assert written == body


def test_issue_comment_command(tmp_path: Path):
    argv = build(comment_entry(), tmp_path)[0]
    assert argv[:3] == ["gh", "issue", "comment"]
    assert argv[3] == "42"


def test_pr_create_command(tmp_path: Path):
    entry = {"kind": "pr_create", "head": "feat/x", "base": "main", "title": "T", "body": "B"}
    argv = build(entry, tmp_path)[0]
    assert argv[:3] == ["gh", "pr", "create"]
    assert argv[argv.index("--head") + 1] == "feat/x"
    assert argv[argv.index("--base") + 1] == "main"
    assert argv[argv.index("--title") + 1] == "T"


def test_pr_create_defaults_its_base(tmp_path: Path):
    entry = {"kind": "pr_create", "head": "feat/x", "title": "T", "body": "B"}
    argv = build(entry, tmp_path)[0]
    assert argv[argv.index("--base") + 1] == writes.DEFAULT_BASE


def test_label_command_carries_adds_and_removes(tmp_path: Path):
    entry = {"kind": "label", "issue": 42, "add": ["a", "b"], "remove": ["c"]}
    argv = build(entry, tmp_path)[0]
    assert argv.count("--add-label") == 2
    assert argv[argv.index("--remove-label") + 1] == "c"


def test_push_runs_in_the_repo_path(tmp_path: Path):
    argv = build({"kind": "push", "branch": "feat/x"}, tmp_path, repo_path="/somewhere/repo")[0]
    assert argv[:3] == ["git", "-C", "/somewhere/repo"]


# -- execution --------------------------------------------------------------


class FakeRunner:
    def __init__(self, fail_on=None):
        self.calls: list[list[str]] = []
        self.envs: list[dict] = []
        self.fail_on = fail_on

    def __call__(self, cmd, **kwargs):
        self.calls.append([str(c) for c in cmd])
        self.envs.append(kwargs.get("env") or {})

        class R:
            returncode = 1 if self.fail_on and self.fail_on in " ".join(str(c) for c in cmd) else 0
            stdout = "https://github.com/owner/target/pull/9\n"
            stderr = "boom" if returncode else ""

        return R()


def test_execute_runs_each_entry_in_manifest_order(tmp_path: Path):
    runner = FakeRunner()
    entries = [
        {"kind": "push", "branch": "feat/x"},
        {"kind": "pr_create", "head": "feat/x", "title": "T", "body": "B"},
    ]
    res = writes.execute(entries, repo=REPO, repo_path="/repo", scratch=tmp_path, runner=runner)
    assert [c[0] for c in runner.calls] == ["git", "gh"]
    assert res["ok"] is True
    assert [r["kind"] for r in res["results"]] == ["push", "pr_create"]


def test_a_single_invalid_entry_executes_nothing(tmp_path: Path):
    """All-or-nothing. A malformed manifest means something is wrong upstream, and
    half-applying it leaves the issue in a state nobody designed."""
    runner = FakeRunner()
    entries = [comment_entry(), {"kind": "merge_pr", "pr": 7}]
    res = writes.execute(entries, repo=REPO, repo_path="/repo", scratch=tmp_path, runner=runner)
    assert runner.calls == []
    assert res["ok"] is False
    assert res["errors"]


def test_execute_stops_at_the_first_failure(tmp_path: Path):
    runner = FakeRunner(fail_on="push")
    entries = [
        {"kind": "push", "branch": "feat/x"},
        {"kind": "pr_create", "head": "feat/x", "title": "T", "body": "B"},
    ]
    res = writes.execute(entries, repo=REPO, repo_path="/repo", scratch=tmp_path, runner=runner)
    assert [c[0] for c in runner.calls] == ["git"], "opened a PR for a branch that never pushed"
    assert res["ok"] is False
    assert res["results"][1]["status"] == "skipped"


def test_execute_passes_the_write_environment_through(tmp_path: Path):
    runner = FakeRunner()
    env = {"GH_TOKEN": "write-token"}
    writes.execute([comment_entry()], repo=REPO, repo_path="/repo", scratch=tmp_path, runner=runner, env=env)
    assert runner.envs[0]["GH_TOKEN"] == "write-token"


def test_execute_records_the_created_pr_url(tmp_path: Path):
    runner = FakeRunner()
    entry = {"kind": "pr_create", "head": "feat/x", "title": "T", "body": "B"}
    res = writes.execute([entry], repo=REPO, repo_path="/repo", scratch=tmp_path, runner=runner)
    assert res["results"][0]["stdout"].strip().endswith("/pull/9")


def test_an_empty_manifest_is_a_success(tmp_path: Path):
    res = writes.execute([], repo=REPO, repo_path="/repo", scratch=tmp_path, runner=FakeRunner())
    assert res["ok"] is True
    assert res["results"] == []


def test_execute_resolves_subprocess_run_at_call_time(tmp_path: Path, monkeypatch):
    """Binding `subprocess.run` as a default argument makes this module unmockable,
    and the driver's own suite monkeypatches exactly that attribute. Caught once."""
    calls = []

    class R:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake(cmd, **kwargs):
        calls.append([str(c) for c in cmd])
        return R()

    monkeypatch.setattr(writes.subprocess, "run", fake)
    writes.execute([comment_entry()], repo=REPO, repo_path="/repo", scratch=tmp_path)
    assert calls, "execute went around the patched subprocess.run"


def test_a_single_entry_jsonl_file_is_not_read_as_an_empty_envelope(tmp_path: Path):
    """One JSON line is also a valid JSON object. Treating it as an envelope with no
    `writes` key silently drops the only entry -- a park comment vanishing with
    nothing failing. Caught by the full-loop suite, pinned here."""
    p = tmp_path / "writes.jsonl"
    p.write_text(json.dumps({"kind": "push", "branch": "feat/x"}) + "\n", encoding="utf-8")
    assert writes.load(p) == [{"kind": "push", "branch": "feat/x"}]


def test_an_object_that_is_neither_an_envelope_nor_an_entry_is_an_error(tmp_path: Path):
    p = tmp_path / "writes.json"
    p.write_text(json.dumps({"note": "I meant well"}), encoding="utf-8")
    with pytest.raises(writes.ManifestError):
        writes.load(p)


def test_a_board_write_is_rejected_when_no_board_is_configured(tmp_path: Path):
    for kind in sorted(writes.BOARD_KINDS):
        assert writes.validate([writes.EXAMPLES[kind]], repo=REPO, board=""), f"{kind} ran with no board"


def test_the_board_is_driver_configuration_not_a_manifest_field(tmp_path: Path):
    """A manifest that names its own board could aim a write at another project."""
    entry = dict(writes.EXAMPLES["project_item_add"], board="attacker/1")
    assert writes.validate([entry], repo=REPO, board=BOARD)

    argv = build(writes.EXAMPLES["project_item_add"], tmp_path)[0]
    assert argv[argv.index("--owner") + 1] == BOARD.split("/")[0]
    assert argv[3] == BOARD.split("/")[1]


def test_a_board_item_url_must_point_into_the_configured_repo():
    entry = dict(writes.EXAMPLES["project_item_add"], url="https://github.com/attacker/elsewhere/issues/1")
    assert writes.validate([entry], repo=REPO, board=BOARD)
