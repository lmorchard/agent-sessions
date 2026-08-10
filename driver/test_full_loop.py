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

Three properties of the fake that are load-bearing, each earned from `findings.md`:

**The fake honours `--json` field lists.** `gh issue list --json labels` was once
mutation-tested by *dropping* `labels` from the driver's field list; the whole frozen
suite stayed green, because its stub served a fixed payload. *"A stub that ignores the
requested field list cannot see a missing field."* So `_project` returns only what the
caller asked for: stop requesting a field and the payload loses it, exactly as `gh`
would do.

**An unrecognised command is recorded, not raised.** The driver wraps nearly every
`subprocess.run` in `except Exception`, so a fake that raised would be swallowed and
the pass would quietly take the fallback branch. Unknown commands land in
`FakeGitHub.unhandled`, which every pass asserts is empty — a new external call
cannot slip in behind an exception handler.

**Writes mutate the fixture.** `label_manager park` really adds the park label to the
fixture issue, so a second pass sees what the first pass did. That is what makes
`test_agent_park_comment_under_driver_identity` (#183) a chain rather than a tableau.

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

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from agent_sessions.driver import agent_runner, agent_session_driver, credentials

REPO = "owner/repo"
BOARD = "owner/9"

#: The driver stamps run dirs and `runs.jsonl` rows with `datetime.now`. Frozen so
#: rows can be asserted whole rather than by pattern.
FROZEN = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
FROZEN_TS = "20260810T120000Z"

#: `git commit-tree` of the empty tree — the driver's lock object.
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
LOCK_SHA = "1111111111111111111111111111111111111111"

DISCUSSION_URL = "https://github.com/owner/repo/discussions/1"

#: Head sha the fake stamps on a PR the driver opens from a manifest, so a gate
#: block written against it can be graded as current.
NEW_PR_HEAD = "beef1234beef1234beef1234beef1234beef1234"

#: The account the driver holds its own tokens on. A PAT-backed machine user, so a
#: human-looking login with no `*[bot]` suffix — which is the whole of issue #183, and
#: the reason `DRIVER_GH_LOGIN` has to be configuration rather than a guess.
DRIVER_LOGIN = "agent-session-bot"

#: A real person. Their comment is the one that unparks an issue.
HUMAN_LOGIN = "lmorchard"

GOLDEN = Path(__file__).parent / "fixtures" / "select_golden.txt"


class FrozenDatetime:
    """Stand-in for the driver's `datetime`, so timestamps are byte-stable."""

    @classmethod
    def now(cls, tz=None):
        return FROZEN


# --- fixture GitHub state --------------------------------------------------
#
# One dict per entity, carrying every field any query could ask for. The `--json`
# projection in `_project` is what decides which of them a given call sees, so a
# fixture record is deliberately *wider* than any single response.


def issue(number, *, body="", labels=(), title=None, comments=()):
    return {
        "number": number,
        "title": title if title is not None else f"Issue {number}",
        "body": body,
        "labels": [{"name": n} for n in labels],
        "url": f"https://github.com/{REPO}/issues/{number}",
        "comments": list(comments),
    }


def pr(
    number,
    *,
    body="",
    closes=(),
    head_oid="",
    checks=(),
    threads=(),
    review_requests=0,
    reviews=0,
    head_ref=None,
):
    return {
        "number": number,
        "title": f"PR {number}",
        "body": body,
        "headRefName": head_ref if head_ref is not None else f"feature/pr-{number}",
        "url": f"https://github.com/{REPO}/pull/{number}",
        "closingIssuesReferences": [{"number": n} for n in closes],
        "headRefOid": head_oid,
        "checks": [{"name": name, "bucket": bucket} for name, bucket in checks],
        "reviewThreads": [{"isResolved": resolved} for resolved in threads],
        "reviewRequests": [{"login": f"reviewer-{i}"} for i in range(review_requests)],
        "reviews": [{"state": "COMMENTED"} for _ in range(reviews)],
    }


def comment(login, body="a comment"):
    return {"author": {"login": login}, "body": body, "createdAt": "2026-08-10T11:00:00Z"}


def board_item(number, *, status="Ready", priority=""):
    return {"status": status, "priority": priority, "content": {"number": number}}


def spec_body(tier_line, extra=""):
    """A specced issue body. `tier_line` is the `## Tier:` heading's remainder."""
    return f"<!-- agent-session:spec -->\n\n## Tier: {tier_line}\n{extra}"


def gate_body(issue_number, *, verdict, ci_row, reason="all gate rows satisfied"):
    """A PR body carrying a merge-gate block.

    Note the driver hands `gate.classify` the *whole PR body*, not the extracted
    block, which is why the yaml lines must sit at column zero — `gate_field` anchors
    on `^key:`. Pinned here as behaviour, not endorsed; #184 is where that boundary
    gets a type.
    """
    return f"""Fixes #{issue_number}

## Merge gate

```yaml
verdict: {verdict}
reason: {reason}
tier: auto-ok
checks: 3/3 pass
guards: none
tamper: clean -- empty diff
project-gates: green: make check
ci: {ci_row}
threads: 0 unresolved
risk-paths: none
```
"""


class _Result:
    """The shape of `subprocess.CompletedProcess` that the driver actually reads."""

    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class FakeGitHub:
    """Fixture GitHub, plus a local git remote, behind one `subprocess.run`.

    Reads are served from the fixture records; writes mutate them, so a second pass
    over the same instance sees the first pass's effects.
    """

    def __init__(self, *, issues=(), prs=(), board_items=(), viewer_login=DRIVER_LOGIN, held_locks=None, logins=None):
        self.issues = [dict(i) for i in issues]
        self.prs = [dict(p) for p in prs]
        self.board_items = list(board_items)
        self.viewer_login = viewer_login
        #: token -> login, so `gh api user` answers for whichever credential was
        #: presented. Without this the identity assertion cannot be tested at all:
        #: a fake that returns one login regardless proves only that a call happened.
        self.logins = dict(logins or {READ_TOKEN: viewer_login, WRITE_TOKEN: viewer_login})
        #: ref -> (sha, unix time). A ref present here makes `ls-remote` report a lock.
        self.held_locks = dict(held_locks or {})

        self.gh_calls: list[list[str]] = []
        self.git_calls: list[list[str]] = []
        #: (argv, env) for every command, so a test can ask *which credential* paid
        #: for a write -- the property #191 exists to establish.
        self.calls_with_env: list[tuple[list[str], dict]] = []
        #: gh write commands only, in order, as (verb, argv).
        self.write_calls: list[tuple[str, list[str]]] = []
        self.next_pr_number = 900
        self.label_calls: list[tuple[str, ...]] = []
        self.discussion_calls: list[list[str]] = []
        self.unhandled: list[list[str]] = []
        #: A `--json` field the fixture record does not carry: a gap in this file,
        #: not in the driver. Asserted empty so it cannot pass as an empty value.
        self.field_gaps: list[tuple[str, str]] = []

    # -- fixture accessors ------------------------------------------------

    def issue_by_number(self, number):
        for i in self.issues:
            if str(i["number"]) == str(number):
                return i
        return None

    def pr_by_number(self, number):
        for p in self.prs:
            if str(p["number"]) == str(number):
                return p
        return None

    def labels_of(self, number):
        return [label["name"] for label in self.issue_by_number(number)["labels"]]

    def add_label(self, number, name):
        iss = self.issue_by_number(number)
        if name not in [label["name"] for label in iss["labels"]]:
            iss["labels"].append({"name": name})

    def remove_label(self, number, name):
        iss = self.issue_by_number(number)
        iss["labels"] = [label for label in iss["labels"] if label["name"] != name]

    def add_comment(self, number, login, body="a comment"):
        self.issue_by_number(number)["comments"].append(comment(login, body))

    @property
    def label_ops(self) -> list[tuple[str, str | None, str | None]]:
        """`label_manager` invocations as (subcommand, issue, count), in order."""
        ops = []
        for rest in self.label_calls:
            sub = issue_num = count = None
            i = 0
            while i < len(rest):
                tok = rest[i]
                if tok in ("--repo", "--current-labels"):
                    i += 2
                elif tok == "--issue":
                    issue_num = rest[i + 1]
                    i += 2
                elif tok == "--count":
                    count = rest[i + 1]
                    i += 2
                elif tok.startswith("-"):
                    i += 1
                else:
                    if sub is None:
                        sub = tok
                    i += 1
            ops.append((sub, issue_num, count))
        return ops

    # -- the subprocess.run replacement -----------------------------------

    def run(self, cmd, **kwargs):
        argv = [str(c) for c in cmd]
        env = dict(kwargs.get("env") or {})
        self.calls_with_env.append((argv, env))
        self._active_token = env.get("GH_TOKEN", os.environ.get("GH_TOKEN", ""))
        if argv[0] == "gh":
            res = self._gh(argv)
        elif argv[0] == "git":
            res = self._git(argv)
        elif argv[0] == sys.executable:
            res = self._python(argv)
        else:
            self.unhandled.append(argv)
            res = _Result(127, "", f"fake: unhandled program {argv[0]}")
        if kwargs.get("check") and res.returncode != 0:
            raise subprocess.CalledProcessError(res.returncode, argv, res.stdout, res.stderr)
        return res

    # -- helpers ----------------------------------------------------------

    def _json_fields(self, argv):
        """The `--json a,b,c` list. Absent means the caller wants no projection."""
        if "--json" not in argv:
            return None
        return [f for f in argv[argv.index("--json") + 1].split(",") if f]

    def _project(self, record, fields, subject):
        """`record` reduced to `fields`, the way `gh --json` reduces its output.

        This is the half that makes the fake able to see a *missing* field: the
        driver only gets what it asked for.
        """
        if fields is None:
            return dict(record)
        out = {}
        for f in fields:
            if f not in record:
                self.field_gaps.append((subject, f))
                continue
            out[f] = record[f]
        return out

    @staticmethod
    def _graphql_var(argv, key):
        for i, tok in enumerate(argv):
            if tok == "-F" and argv[i + 1].startswith(f"{key}="):
                return argv[i + 1].split("=", 1)[1]
        return ""

    # -- gh ---------------------------------------------------------------

    def _gh(self, argv):
        self.gh_calls.append(argv)
        rest = argv[1:]

        if rest[:2] == ["issue", "list"]:
            fields = self._json_fields(argv)
            return _Result(0, json.dumps([self._project(i, fields, f"issue {i['number']}") for i in self.issues]))

        if rest[:2] == ["issue", "view"]:
            number = rest[2]
            iss = self.issue_by_number(number)
            if iss is None:
                return _Result(1, "", f"fake: no fixture issue #{number}")
            fields = self._json_fields(argv)
            return _Result(0, json.dumps(self._project(iss, fields, f"issue {number}")))

        if rest[:2] == ["pr", "list"]:
            fields = self._json_fields(argv)
            return _Result(0, json.dumps([self._project(p, fields, f"pr {p['number']}") for p in self.prs]))

        if rest[:2] == ["pr", "view"]:
            number = rest[2]
            pull = self.pr_by_number(number)
            if pull is None:
                return _Result(1, "", f"fake: no fixture PR #{number}")
            fields = self._json_fields(argv)
            return _Result(0, json.dumps(self._project(pull, fields, f"pr {number}")))

        if rest[:2] == ["pr", "checks"]:
            number = rest[2]
            pull = self.pr_by_number(number)
            if pull is None:
                return _Result(1, "", f"fake: no fixture PR #{number}")
            fields = self._json_fields(argv)
            checks = [self._project(c, fields, f"pr {number} check") for c in pull["checks"]]
            return _Result(0, json.dumps(checks))

        if rest[:2] == ["project", "item-list"]:
            return _Result(0, json.dumps({"items": self.board_items}))

        if rest[:2] == ["api", "graphql"]:
            # The GraphQL query text is not parsed; only the `-F pr=` variable is
            # read and the response envelope is hand-shaped. A change to which
            # *fields* the query requests is therefore invisible here — unlike the
            # `--json` paths above. Noted rather than solved.
            number = self._graphql_var(argv, "pr")
            pull = self.pr_by_number(number)
            nodes = [{"isResolved": t["isResolved"]} for t in (pull["reviewThreads"] if pull else [])]
            return _Result(
                0,
                json.dumps({"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": nodes}}}}}),
            )

        if rest[:2] == ["api", "user"]:
            # The driver's startup identity assertion: one call per token, each under
            # the environment that token lives in. Answering from `logins` rather than
            # a constant is what lets a test present a *human* token and see the
            # refusal, which is the property #191's bot-account mode exists for.
            login = self.logins.get(self._active_token)
            if login is None:
                return _Result(1, "", "fake: gh api user with an unknown credential")
            if "--jq" in argv:
                return _Result(0, login + "\n")
            return _Result(0, json.dumps({"login": login}))

        if rest[:2] == ["repo", "view"]:
            return _Result(0, "R_fixture_repo_id\n")

        if rest[:2] == ["discussion", "list"]:
            return _Result(0, "[]")

        if rest[:2] == ["discussion", "create"]:
            return _Result(0, DISCUSSION_URL + "\n")

        if rest[:2] == ["discussion", "comment"]:
            self.discussion_calls.append(argv)
            return _Result(0, "")

        # -- writes, which only reach here via the driver's manifest (#191) ----

        if rest[:2] == ["issue", "comment"]:
            number = rest[2]
            if self.issue_by_number(number) is None:
                return _Result(1, "", f"fake: no fixture issue #{number}")
            self.write_calls.append(("issue_comment", argv))
            self.add_comment(number, self.viewer_login, self._body_of(argv))
            return _Result(0, "")

        if rest[:2] == ["issue", "edit"]:
            number = rest[2]
            iss = self.issue_by_number(number)
            if iss is None:
                return _Result(1, "", f"fake: no fixture issue #{number}")
            self.write_calls.append(("issue_edit", argv))
            for i, tok in enumerate(argv):
                if tok == "--add-label":
                    self.add_label(number, argv[i + 1])
                elif tok == "--remove-label":
                    self.remove_label(number, argv[i + 1])
                elif tok == "--body-file":
                    iss["body"] = Path(argv[i + 1]).read_text(encoding="utf-8")
            return _Result(0, "")

        if rest[:2] == ["pr", "create"]:
            self.write_calls.append(("pr_create", argv))
            number = self.next_pr_number
            self.next_pr_number += 1
            body = self._body_of(argv)
            self.prs.append(
                pr(
                    number,
                    body=body,
                    closes=[int(n) for n in re.findall(r"(?i)closes #(\d+)", body)],
                    head_oid=NEW_PR_HEAD,
                    head_ref=argv[argv.index("--head") + 1] if "--head" in argv else None,
                    checks=[("test", "pass")],
                )
            )
            return _Result(0, f"https://github.com/{REPO}/pull/{number}\n")

        if rest[:2] == ["pr", "edit"]:
            number = rest[2]
            if self.pr_by_number(number) is None:
                return _Result(1, "", f"fake: no fixture PR #{number}")
            self.write_calls.append(("pr_edit", argv))
            return _Result(0, "")

        if rest[:2] == ["label", "create"]:
            self.write_calls.append(("label_create", argv))
            return _Result(0, "")

        self.unhandled.append(argv)
        return _Result(1, "", f"fake: unhandled gh command {rest}")

    @staticmethod
    def _body_of(argv):
        if "--body-file" in argv:
            return Path(argv[argv.index("--body-file") + 1]).read_text(encoding="utf-8")
        return ""

    # -- git --------------------------------------------------------------

    def _git(self, argv):
        # `git -C <path> ...` -- the path is dropped from the record so assertions
        # do not depend on a tmp_path.
        rest = argv[3:] if argv[1:2] == ["-C"] else argv[1:]
        self.git_calls.append(rest)

        if rest[:1] == ["rev-parse"]:
            return _Result(0, ".git\n")
        if rest[:2] == ["remote", "get-url"]:
            return _Result(0, f"git@github.com:{REPO}.git\n")
        if rest[:1] == ["commit-tree"]:
            return _Result(0, LOCK_SHA + "\n")
        if rest[:1] == ["ls-remote"]:
            ref = rest[-1]
            held = self.held_locks.get(ref)
            return _Result(0, f"{held[0]}\t{ref}\n" if held else "")
        if rest[:1] == ["fetch"]:
            return _Result(0, "")
        if rest[:1] == ["log"]:
            sha = rest[-1]
            for held_sha, held_time in self.held_locks.values():
                if held_sha == sha:
                    return _Result(0, f"{held_time}\n")
            return _Result(0, "0\n")
        if rest[:1] == ["push"]:
            return _Result(0, "")

        self.unhandled.append(argv)
        return _Result(1, "", f"fake: unhandled git command {rest}")

    # -- python subprocesses (label_manager) -------------------------------

    def _python(self, argv):
        script = Path(argv[1]).name if len(argv) > 1 else ""
        if script != "label_manager.py":
            self.unhandled.append(argv)
            return _Result(127, "", f"fake: unhandled python script {script}")

        rest = tuple(argv[2:])
        self.label_calls.append(rest)
        sub, number, count = self.label_ops[-1]
        if self.issue_by_number(number) is None:
            return _Result(1, "", f"fake: no fixture issue #{number}")

        if sub == "park":
            self.add_label(number, agent_session_driver.PARK_LABEL)
        elif sub == "unpark":
            self.remove_label(number, agent_session_driver.PARK_LABEL)
            self.remove_label(number, agent_session_driver.INTERACTIVE_LABEL)
        elif sub == "merge-ready":
            self.add_label(number, agent_session_driver.MERGE_READY_LABEL)
        elif sub == "attempt":
            for n in (1, 2, 3):
                self.remove_label(number, f"agent-session:attempt-{n}")
            self.add_label(number, f"agent-session:attempt-{count}")
        elif sub == "clear-attempts":
            for n in (1, 2, 3):
                self.remove_label(number, f"agent-session:attempt-{n}")
        return _Result(0, "")


# --- the stubbed agent ------------------------------------------------------


def agent_stream(*, final="the agent's report", cost=1.23, session="sess-abc", subtype="success"):
    """A `claude` stream-json transcript, as `parse_result_stream` expects it."""
    return [
        {"type": "system", "subtype": "init", "session_id": session},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "working"}]}},
        {
            "type": "result",
            "subtype": subtype,
            "is_error": False,
            "total_cost_usd": cost,
            "session_id": session,
            "result": final,
        },
    ]


class StubAgent:
    """Stands in for `agent_runner.run_agent`, writing a fixture stream to disk.

    `manifest` is how a real agent asks for a GitHub write since #191: it has a
    read-scoped token, so it records entries and the driver performs them. Tests
    that assert on writes should use it, because that is the shipping path.

    `side_effect` remains for the cases that need the world to change *behind* the
    driver's back — a human commenting mid-run — which is not a manifest write.
    """

    def __init__(self, *, stream=None, returncode=0, side_effect=None, manifest=None):
        self.stream = agent_stream() if stream is None else stream
        self.returncode = returncode
        self.side_effect = side_effect
        self.manifest = manifest
        self.calls: list[list[str]] = []

    def __call__(self, argv):
        self.calls.append(list(argv))
        #: The driver's environment at the moment of invocation. `agent_runner`
        #: derives the child's environment from this, so it is what a test needs to
        #: see to know whether the agent could have written to GitHub.
        self.env_at_call = dict(os.environ)
        raw = Path(argv[argv.index("--raw-output") + 1])
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_text("".join(json.dumps(e) + "\n" for e in self.stream), encoding="utf-8")
        if self.manifest is not None:
            writes_file = Path(argv[argv.index("--writes-file") + 1])
            writes_file.parent.mkdir(parents=True, exist_ok=True)
            body = self.manifest if isinstance(self.manifest, str) else "".join(
                json.dumps(e) + "\n" for e in self.manifest
            )
            writes_file.write_text(body, encoding="utf-8")
        if self.side_effect is not None:
            self.side_effect()
        return self.returncode


# --- the harness ------------------------------------------------------------

#: Environment the driver reads for defaults. Cleared so a developer's shell or a
#: `.env` in the invoking directory cannot reach into a pass.
_DRIVER_ENV = (
    "REPO", "DRIVER_REPO", "SKILL_DIR", "DRIVER_SKILL_DIR", "REPO_PATH", "DRIVER_REPO_PATH",
    "ISSUE", "MAX_ISSUES", "MAX_BUDGET_USD", "MAX_BUDGET", "MAX_PHASE_ATTEMPTS", "RUN_TIMEOUT",
    "TIMEOUT", "STATE_DIR", "BOARD", "DRIVER_BOARD", "BACKEND", "DRIVER_BACKEND", "MODEL",
    "HIGH_TIER_MODEL", "LOW_TIER_MODEL", "RETRY", "XDG_STATE_HOME",
    "GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN",
    credentials.READ_TOKEN_VAR, credentials.WRITE_TOKEN_VAR, credentials.LOGIN_VAR,
    credentials.BOT_LOGINS_VAR,
)

#: The contained configuration, which every pass runs under unless it says otherwise.
#: Without it the driver refuses to start at all -- there is no degraded mode -- so a
#: pass that wants the refusal has to unset one of these deliberately.
READ_TOKEN = "read-scoped-token"
WRITE_TOKEN = "write-capable-token"


class LoopHarness:
    def __init__(self, tmp_path, monkeypatch, capsys):
        self.tmp_path = tmp_path
        self.monkeypatch = monkeypatch
        self.capsys = capsys

        self.state_dir = tmp_path / "state"
        self.repo_path = tmp_path / "target-repo"
        self.skill_dir = tmp_path / "skill"
        self.repo_path.mkdir()
        self.skill_dir.mkdir()

        # `load_env_file(".env")` reads the *current directory*; chdir somewhere with
        # no .env so the repo's own configuration cannot leak into a pass.
        monkeypatch.chdir(tmp_path)
        for var in _DRIVER_ENV:
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv(credentials.READ_TOKEN_VAR, READ_TOKEN)
        monkeypatch.setenv(credentials.WRITE_TOKEN_VAR, WRITE_TOKEN)
        monkeypatch.setenv(credentials.LOGIN_VAR, DRIVER_LOGIN)
        monkeypatch.setattr(agent_session_driver, "datetime", FrozenDatetime)
        # The driver releases its lock from an atexit hook keyed on this global.
        # monkeypatch restores it to None, so no pass can leave a live lock behind.
        monkeypatch.setattr(agent_session_driver, "CURRENT_LOCK_ISSUE", None)

    def seed_runs(self, rows):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with open(self.state_dir / "runs.jsonl", "a", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")

    def run(self, gh, *, agent=None, argv=(), board=True):
        """One `main()` pass. Returns (exit_code, stdout)."""
        agent = StubAgent() if agent is None else agent
        self.agent = agent
        self.monkeypatch.setattr(subprocess, "run", gh.run)
        self.monkeypatch.setattr(agent_runner, "run_agent", agent)

        full_argv = [
            "--repo", REPO,
            "--repo-path", str(self.repo_path),
            "--skill-dir", str(self.skill_dir),
            "--state-dir", str(self.state_dir),
            *(["--board", BOARD] if board else []),
            *argv,
        ]
        self.capsys.readouterr()  # drop anything an earlier pass printed
        code = agent_session_driver.main(full_argv)
        out = self.capsys.readouterr().out

        assert gh.unhandled == [], (
            "the pass issued a command the fake does not model, so the driver took an "
            f"exception fallback instead of the path under test: {gh.unhandled}"
        )
        assert gh.field_gaps == [], (
            "the driver asked for a --json field no fixture record carries; the fixture "
            f"needs widening or the field name is wrong: {gh.field_gaps}"
        )
        return code, out

    # -- reading the state dir --------------------------------------------

    def rows(self, name):
        path = self.state_dir / name
        if not path.is_file():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def run_dir(self, number, ts=FROZEN_TS):
        return self.state_dir / "runs" / f"{number}-{ts}"


@pytest.fixture
def loop(tmp_path, monkeypatch, capsys):
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
            "started": FROZEN_TS,
            "exit": 0,
            "cost_usd": 1.23,
            "session_id": "sess-abc",
            "outcome": "gate-eligible",
            "reason": "all gate rows satisfied",
            "pr": f"https://github.com/{REPO}/pull/201",
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
    # `main()` passes the whole PR body to `gate.classify`, so `gate.yaml` is the
    # whole body rather than just the block. Pinned as behaviour; #184 is the fix.
    assert (rundir / "gate.yaml").read_text(encoding="utf-8") == gh.pr_by_number(201)["body"]

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

    # The attempt counter goes up before the run and is cleared by the park, so a
    # human comment resumes from zero rather than from a spent budget.
    assert gh.label_ops == [("attempt", "102", "1"), ("park", "102", None), ("clear-attempts", "102", None)]
    assert agent_session_driver.PARK_LABEL in gh.labels_of(102)
    assert "agent-session:attempt-1" not in gh.labels_of(102)

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
        {"issue": 302, "repo": REPO, "outcome": "parked", "reason": "triage could not tell which subsystem this is about"}
    ])

    code, out = loop.run(gh, argv=["--dry-run"])
    assert code == 0

    if os.environ.get("UPDATE_SELECT_GOLDEN") == "1":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(out, encoding="utf-8")
        pytest.fail(
            f"rewrote {GOLDEN.relative_to(Path(__file__).parent.parent)} from this run. "
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
    the attempt counters reset, and the loop breaker can never fire.
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




def test_a_write_token_in_a_dotenv_the_agent_can_read_stops_the_run(loop):
    """The split collapses if the write credential sits in a file inside the tree the
    agent holds Read over. Fail closed rather than ship theatre."""
    (loop.repo_path / ".env").write_text(f"{credentials.WRITE_TOKEN_VAR}=whatever\n", encoding="utf-8")
    loop.monkeypatch.chdir(loop.repo_path)
    gh = FakeGitHub(issues=[issue(110, body=spec_body("auto-ok"), labels=["P1"])], board_items=[board_item(110)])

    with pytest.raises(SystemExit) as excinfo:
        loop.run(gh, argv=["--dry-run"])

    assert excinfo.value.code == 2


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

