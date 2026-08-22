"""Fixture GitHub, a stubbed agent, and the rig that drives one `main()` pass.

Lifted out of `test_full_loop.py` so a second suite can drive the strong fake instead
of writing a third weak one — issue #261, X2/X3. A plain module rather than a
`conftest.py`: these are classes and builders a test file has to *name*, and a second
conftest also collides with `tests/conftest.py` under mypy. The `loop` fixture that
wraps `LoopHarness` stays in `test_full_loop.py`, three lines any other suite can
repeat; the harness is the part worth not repeating.

Three properties of the fake are load-bearing, each earned from `findings.md`:

**The fake honours `--json` field lists.** `gh issue list --json labels` was once
mutation-tested by *dropping* `labels` from the driver's field list; the whole frozen
suite stayed green, because its stub served a fixed payload. *"A stub that ignores the
requested field list cannot see a missing field."* So `_project` returns only what the
caller asked for: stop requesting a field and the payload loses it, exactly as `gh`
would do.

**An unrecognised command is recorded, not raised.** The driver wraps nearly every
`subprocess.run` in `except Exception`, so a fake that raised would be swallowed and
the pass would quietly take the fallback branch. Unknown commands land in
`FakeGitHub.unhandled`, which `LoopHarness.run` asserts is empty on every pass — a new
external call cannot slip in behind an exception handler.

**Writes mutate the fixture.** `label_manager park` really adds the park label to the
fixture issue, so a second pass sees what the first pass did. That is what makes
`test_agent_park_comment_under_driver_identity` (#183) a chain rather than a tableau.

`tests/conftest.py`'s `recording_gh` is the small sibling of this file, not a rival:
same no-unmodelled-call property, no fixture state, for suites that need a `gh` that
cannot lie rather than a GitHub that can be read back.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from agent_sessions.driver import agent_runner, agent_session_driver, credentials, locks, output

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


def frozen_now():
    """Stand-in for `output.now`, so every recorded timestamp is byte-stable.

    Replaces a `FrozenDatetime` class that stood in for a stdlib `datetime` re-exported
    through `agent_session_driver`. The clock is now a named function in `output`, which
    every driver module calls, so freezing it is one `setattr` on the module that owns it
    rather than a patch on a barrel five other modules had to import to reach.
    """
    return FROZEN


# --- fixture GitHub state --------------------------------------------------
#
# One dict per entity, carrying every field any query could ask for. The `--json`
# projection in `_project` is what decides which of them a given call sees, so a
# fixture record is deliberately *wider* than any single response.


def issue(number, *, body="", labels=(), title=None, comments=(), updated_at="2026-08-10T12:00:00Z"):
    return {
        "number": number,
        "title": title if title is not None else f"Issue {number}",
        "body": body,
        "labels": [{"name": n} for n in labels],
        "url": f"https://github.com/{REPO}/issues/{number}",
        "comments": list(comments),
        "updatedAt": updated_at,
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
    changed_files=1,
    base_ref="main",
    files=None,
    comments=(),
    commits=(),
    merge_state_status="CLEAN",
    mergeable="MERGEABLE",
):
    check_rollup = []
    for name, bucket in checks:
        conc = "SUCCESS" if bucket == "pass" else ("NEUTRAL" if bucket in ("skipping", "neutral") else "FAILURE")
        st = "IN_PROGRESS" if bucket == "pending" else "COMPLETED"
        check_rollup.append({"__typename": "CheckRun", "name": name, "status": st, "conclusion": conc})

    return {
        "number": number,
        "title": f"PR {number}",
        "body": body,
        "comments": list(comments),
        "commits": list(commits),
        "headRefName": head_ref if head_ref is not None else f"feature/pr-{number}",
        "baseRefName": base_ref,
        "url": f"https://github.com/{REPO}/pull/{number}",
        "closingIssuesReferences": [{"number": n} for n in closes],
        "headRefOid": head_oid,
        "changedFiles": changed_files,
        "files": files if files is not None else [{"path": "some_file.py"}],
        "checks": [{"name": name, "bucket": bucket} for name, bucket in checks],
        "statusCheckRollup": check_rollup,
        "reviewThreads": [{"isResolved": resolved} for resolved in threads],
        "reviewRequests": [{"login": f"reviewer-{i}"} for i in range(review_requests)],
        "reviews": [{"state": "COMMENTED"} for _ in range(reviews)],
        "reviewDecision": "",
        "mergeStateStatus": merge_state_status,
        "mergeable": mergeable,
    }


def comment(login, body="a comment", created_at="2026-08-10T11:00:00Z"):
    return {"author": {"login": login}, "body": body, "createdAt": created_at}


def board_item(number, *, status="Ready", priority=""):
    return {"status": status, "priority": priority, "content": {"number": number}}


def spec_body(tier_line, extra=""):
    """A specced issue body. `tier_line` is the `## Tier:` heading's remainder."""
    return f"<!-- agent-session:spec -->\n\n## Tier: {tier_line}\n{extra}"


def gate_body(issue_number, *, verdict, ci_row, reason="all gate rows satisfied", prose=""):
    """A PR body carrying a merge-gate block.

    The yaml lines sit at column zero because `gate_field` anchors on `^key:`.

    This docstring used to add that the driver hands `gate.classify` the *whole* PR
    body rather than the extracted block, "pinned here as behaviour, not endorsed;
    #184 is where that boundary gets a type." #184 landed the schema half and closed
    without touching the extraction, so the note outlived its pointer. The driver now
    extracts the block first (#261, C5), and
    `test_prose_above_the_gate_block_cannot_supply_a_gate_row` is what holds that.

    `prose` puts text *above* the `## Merge gate` heading, which is where an ordinary
    PR summary lives and where the old behaviour let a stray `key: value` line win.
    """
    lead = f"{prose}\n\n" if prose else ""
    return lead + f"""Fixes #{issue_number}

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



class FakeResponse:
    def __init__(self, status_code, json_data):
        self.status_code = status_code
        self._json_data = json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP Error: {self.status_code}")

    def json(self):
        return self._json_data

class FakeGitHub:

    """Fixture GitHub, plus a local git remote, behind one `subprocess.run`.

    Reads are served from the fixture records; writes mutate them, so a second pass
    over the same instance sees the first pass's effects.
    """

    def __init__(self, *, issues=(), prs=(), board_items=(), viewer_login=DRIVER_LOGIN, held_locks=None,
                 logins=None, committable=()):
        self.issues = [dict(i) for i in issues]
        self.prs = [dict(p) for p in prs]
        self.board_items = list(board_items)
        self.viewer_login = viewer_login
        #: token -> login, so `gh api user` answers for whichever credential was
        #: presented. Without this the identity assertion cannot be tested at all:
        #: a fake that returns one login regardless proves only that a call happened.
        self.logins = dict(logins or {READ_TOKEN: viewer_login, WRITE_TOKEN: viewer_login})
        #: Paths `git check-ignore` reports as NOT ignored, i.e. committable. Empty by
        #: default: a `.env` beside the driver is git-ignored in every real checkout.
        self.committable = {str(c) for c in committable}
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

    def add_comment(self, number, login, body="a comment", created_at="2026-08-10T11:00:00Z"):
        iss = self.issue_by_number(number)
        iss["comments"].append(comment(login, body, created_at))
        iss["updatedAt"] = created_at

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
            # Widening the annotation to `str | None` would let a malformed call through
            # as a silent `(None, ...)` row that no expected-list would ever match on
            # purpose. Every `label_manager` invocation carries a subcommand; if one does
            # not, that is the finding.
            assert sub is not None, f"label_manager invoked with no subcommand: {rest}"
            ops.append((sub, issue_num, count))
        return ops

    # -- the subprocess.run replacement -----------------------------------


    def requests_post(self, url, **kwargs):
        if url == "https://api.github.com/graphql":
            json_payload = kwargs.get("json", {})
            variables = json_payload.get("variables", {})

            if "pullRequest(number:$pr)" in json_payload.get("query", ""):
                pr_number = variables.get("pr")
                pull = self.pr_by_number(pr_number)
                nodes = [{"isResolved": t["isResolved"]} for t in (pull["reviewThreads"] if pull else [])]
                return FakeResponse(200, {"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": nodes}}}}})
            elif "issue(number:$issue)" in json_payload.get("query", ""):

                # For test purposes, return an empty comments nodes list
                return FakeResponse(200, {"data": {"repository": {"issue": {"comments": {"nodes": []}}}}})
        raise NotImplementedError(f"Mock for {url} not implemented")

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

        if rest[:2] == ["project", "view"]:
            return _Result(0, json.dumps({"id": "PVT_kwHNVLfOAXqLIg"}))

        if rest[:2] == ["project", "field-list"]:
            return _Result(0, json.dumps({"fields": [{"id": "PVTSSF_lAHNVLfOAXqLIs4WQWjt", "name": "Status", "options": [{"id": "a8efeb1f", "name": "In progress"}]}]}))

        if rest[:2] == ["project", "item-edit"]:
            return _Result(0, "")

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

        if rest[:2] == ["api", "rate_limit"]:
            return _Result(
                0,
                json.dumps({
                    "resources": {
                        "graphql": {"limit": 5000, "remaining": 5000, "reset": 1700000000}
                    }
                }),
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
        if rest[:1] == ["show-ref"]:
            return _Result(1, "")
        if rest[:1] == ["worktree"]:
            if len(rest) >= 3 and rest[1] in ("add", "remove"):
                for arg in rest[2:]:
                    p = Path(arg)
                    if p.is_absolute() or "state/workspaces" in arg or "workspaces" in arg:
                        if rest[1] == "add":
                            p.mkdir(parents=True, exist_ok=True)
                        break
            return _Result(0, "")
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
        if rest[:1] == ["check-ignore"]:
            target = rest[-1]
            return _Result(1 if target in self.committable else 0, "")

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
    credentials.BOT_LOGINS_VAR, credentials.CONFIG_FILE_VAR,
    credentials.READ_TOKEN_VAR + credentials.CMD_SUFFIX,
    credentials.WRITE_TOKEN_VAR + credentials.CMD_SUFFIX,
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
        monkeypatch.setattr(output, "now", frozen_now)
        # The driver releases its lock from an atexit hook keyed on a module global in
        # `locks`. Patch it there, on the owning module.
        #
        # This used to patch `agent_session_driver.CURRENT_LOCK_ISSUE` and claim the same
        # effect. It had none: that module does `from ...locks import CURRENT_LOCK_ISSUE`,
        # which binds a *copy* of a `str | None`, while `locks.acquire_lock` and
        # `locks.release_lock` read and write `locks.CURRENT_LOCK_ISSUE` through `global`.
        # Nothing in `src/` ever read the re-exported name. The visible symptom was real
        # `Releasing lock for #N...` lines at pytest exit -- the atexit hook firing after
        # monkeypatch had restored the true `subprocess.run` -- harmless only because these
        # tmp_path repos have no `origin` to push a ref deletion to.
        monkeypatch.setattr(locks, "CURRENT_LOCK_ISSUE", None)

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
        import requests
        self.monkeypatch.setattr(requests, "post", gh.requests_post)
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


