#!/usr/bin/env python3
"""The write manifest: agent-authored GitHub writes, driver-executed.

The agent runs with a read-scoped credential (see `credentials`), so it cannot call
`gh issue comment` or `gh pr create` itself. Instead it records what it wants
written, and the driver validates the record and executes it with the write token.

The driver is a validator, not a pipe. Content is still the agent's words -- that
trust model is unchanged -- but the *capability* is the driver's, and it will only
spend that capability on a kind named in `KINDS`, aimed at the configured repo.
There is deliberately no kind that merges.

"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import TypedDict

from agent_sessions.driver import credentials

DEFAULT_BASE = "main"

#: Branches a manifest may never push to. The agent works on feature branches; a
#: push to the integration branch is the shape of an accidental self-merge.
PROTECTED_BRANCHES = frozenset({"main", "master", "trunk"})

_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,254}$")
_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._:/-]{0,49}$")
_LOGIN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}$")
_COLOR_RE = re.compile(r"^[0-9A-Fa-f]{6}$")


class ManifestError(Exception):
    """The manifest file could not be read as a manifest at all."""


#: kind -> (required fields, optional fields). Anything outside the union of the
#: two is rejected, so a field nobody has thought about cannot ride along.
KINDS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "issue_comment": (("issue", "body"), ()),
    "issue_body": (("issue", "body"), ()),
    "issue_create": (("title", "body"), ("labels",)),
    "label": (("issue",), ("add", "remove")),
    "label_create": (("name",), ("color", "description")),
    "push": (("branch",), ()),
    # `labels`/`reviewers` ride along here because a manifest cannot label a PR
    # it created in the same run: the number is not known until the driver has
    # made it. `gh pr create` takes both, so the round trip is unnecessary.
    "pr_create": (("head", "title", "body"), ("base", "draft", "labels", "reviewers")),
    "pr_edit": (("pr",), ("add_label", "remove_label", "add_reviewer")),
    # The board itself is *not* a manifest field: it comes from the driver's own
    # `--board`, so a manifest cannot aim a write at some other project. Only the
    # opaque ids a status move needs are the agent's to supply, and `project_id` is
    # the residual -- a manifest naming a different project's node id would be
    # honoured. Named rather than gated away; adding an issue to a board and moving
    # its status are not destructive, and the driver refuses both when no board is
    # configured at all.
    "project_item_add": (("url",), ()),
    "project_item_edit": (("project_id", "item_id", "field_id", "option_id"), ()),
}

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,100}$")

#: Kinds that need `--board` to have been configured on the driver.
BOARD_KINDS = frozenset({"project_item_add", "project_item_edit"})

#: One valid entry per kind. Doubles as the documentation in
#: `skills/agent-session/references/write-manifest.md` and as the corpus the tests
#: sweep, so a kind added without an example fails the suite rather than shipping
#: unexercised.
EXAMPLES: dict[str, dict] = {
    "issue_comment": {"kind": "issue_comment", "issue": 42, "body": "Parked: needs a decision on X."},
    "issue_body": {"kind": "issue_body", "issue": 42, "body": "# Title\n\nAugmented spec."},
    "issue_create": {"kind": "issue_create", "title": "New issue", "body": "Spec.", "labels": ["agent-session:spec"]},
    "label": {"kind": "label", "issue": 42, "add": ["agent-session:needs-human"], "remove": ["agent-session:auto-ok"]},
    "label_create": {"kind": "label_create", "name": "agent-session:spec", "color": "0E8A16", "description": "Specced"},
    "push": {"kind": "push", "branch": "feat/191-read-scoped-token"},
    "pr_create": {
        "kind": "pr_create",
        "head": "feat/191-read-scoped-token",
        "base": "main",
        "title": "driver: contain the agent by credential",
        "body": "PR body, including the gate block.",
        "labels": ["agent-session:gate"],
        "reviewers": ["copilot-pull-request-reviewer"],
    },
    "pr_edit": {"kind": "pr_edit", "pr": 7, "add_label": ["agent-session:gate"], "add_reviewer": ["copilot-pull-request-reviewer"]},
    "project_item_add": {"kind": "project_item_add", "url": "https://github.com/owner/target/issues/42"},
    "project_item_edit": {
        "kind": "project_item_edit",
        "project_id": "PVT_kwHOAAxyz",
        "item_id": "PVTI_lADOAAxyz",
        "field_id": "PVTSSF_lADOAAxyz",
        "option_id": "47fc9ee4",
    },
}


# -- loading ----------------------------------------------------------------


def load(path: Path | str) -> list[dict]:
    """Read a manifest. Missing or empty means the agent wanted nothing written.

    Three shapes are accepted because an agent appending to a file mid-run is the
    normal case: `{"writes": [...]}`, a bare array, and one JSON object per line.
    """
    p = Path(path)
    if not p.is_file():
        return []
    text = p.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return []

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        entries = []
        for lineno, line in enumerate(text.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise ManifestError(f"{p}:{lineno}: not JSON and not JSON lines: {e}") from e
        return entries

    if isinstance(data, dict):
        if "writes" in data:
            data = data["writes"]
        elif "kind" in data:
            # A one-line JSONL file is also valid JSON: a single object. Reading it
            # as an envelope with no `writes` key silently drops the only entry,
            # which is how a park comment goes missing without anything failing.
            data = [data]
        else:
            raise ManifestError(f"{p}: object manifest needs a 'writes' key, or a 'kind' to be one entry")
    if not isinstance(data, list):
        raise ManifestError(f"{p}: expected a list of writes, got {type(data).__name__}")
    return data


# -- validation -------------------------------------------------------------


def _issue_number(value) -> str | None:
    """A positive integer, as a string. Anything else could carry a flag."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value) if value > 0 else None
    if isinstance(value, str) and value.isdigit() and int(value) > 0:
        return str(int(value))
    return None


def _num(value) -> str:
    """`_issue_number` after validation, where None can no longer happen."""
    number = _issue_number(value)
    if number is None:
        raise ManifestError(f"issue/pr number {value!r} reached command construction unvalidated")
    return number


def _bad_ref(value) -> bool:
    return not (isinstance(value, str) and _REF_RE.match(value) and ".." not in value and not value.endswith(".lock"))


def _bad_str_list(value, pattern: re.Pattern) -> bool:
    if not isinstance(value, list):
        return True
    return any(not (isinstance(v, str) and pattern.match(v)) for v in value)


def _validate_entry(entry, repo: str, index: int, board: str) -> list[str]:
    where = f"writes[{index}]"
    if not isinstance(entry, dict):
        return [f"{where}: expected an object, got {type(entry).__name__}"]

    kind = entry.get("kind")
    if kind not in KINDS:
        return [f"{where}: unknown kind {kind!r}; allowed kinds are {', '.join(sorted(KINDS))}"]

    required, optional = KINDS[kind]
    allowed = {"kind", *required, *optional}
    errs = [f"{where}: unknown field {f!r} for kind {kind!r}" for f in sorted(set(entry) - allowed)]
    errs += [f"{where}: kind {kind!r} requires {f!r}" for f in required if f not in entry]
    if errs:
        return errs

    for field in ("issue", "pr"):
        if field in entry and _issue_number(entry[field]) is None:
            errs.append(f"{where}: {field!r} must be a positive integer, got {entry[field]!r}")

    for field in ("body", "title", "description", "name"):
        if field in entry:
            value = entry[field]
            if not isinstance(value, str) or not value.strip():
                errs.append(f"{where}: {field!r} must be a non-empty string")

    for field in ("head", "base", "branch"):
        if field in entry and _bad_ref(entry[field]):
            errs.append(f"{where}: {field!r} is not a safe git ref: {entry[field]!r}")

    for field in ("add", "remove", "labels", "add_label", "remove_label"):
        if field in entry and _bad_str_list(entry[field], _LABEL_RE):
            errs.append(f"{where}: {field!r} must be a list of plain label names, got {entry[field]!r}")

    for field in ("add_reviewer", "reviewers"):
        if field in entry and _bad_str_list(entry[field], _LOGIN_RE):
            errs.append(f"{where}: {field!r} must be a list of GitHub logins, got {entry[field]!r}")

    if "color" in entry and not (isinstance(entry["color"], str) and _COLOR_RE.match(entry["color"])):
        errs.append(f"{where}: 'color' must be a six-digit hex triplet, got {entry['color']!r}")

    for field in ("project_id", "item_id", "field_id", "option_id"):
        if field in entry and not (isinstance(entry[field], str) and _ID_RE.match(entry[field])):
            errs.append(f"{where}: {field!r} must be a GitHub node id, got {entry[field]!r}")

    if "url" in entry and not (
        isinstance(entry["url"], str) and entry["url"].startswith(f"https://github.com/{repo}/")
    ):
        errs.append(f"{where}: 'url' must point into {repo}, got {entry.get('url')!r}")

    if "draft" in entry and not isinstance(entry["draft"], bool):
        errs.append(f"{where}: 'draft' must be a boolean")

    if kind == "push" and entry.get("branch") in PROTECTED_BRANCHES:
        errs.append(f"{where}: refusing to push to the protected branch {entry['branch']!r}")

    if kind == "label" and not (entry.get("add") or entry.get("remove")):
        errs.append(f"{where}: a label entry must add or remove at least one label")

    if kind == "pr_edit" and not any(entry.get(f) for f in ("add_label", "remove_label", "add_reviewer")):
        errs.append(f"{where}: a pr_edit entry must change at least one thing")

    if kind in BOARD_KINDS and not board:
        errs.append(f"{where}: kind {kind!r} needs a board, and the driver has none configured")

    return errs


def validate(entries: list, repo: str, board: str = "") -> list[str]:
    """Every problem with the manifest, or an empty list.

    `repo` is not a field an entry may carry -- `_validate_entry`'s unknown-field
    check rejects it -- so every command is pinned to the driver's own target.
    """
    errs: list[str] = []
    for i, entry in enumerate(entries):
        errs.extend(_validate_entry(entry, repo, i, board))
    return errs


# -- command construction ---------------------------------------------------


def _body_file(entry: dict, scratch: Path, index: int) -> str:
    """Bodies travel by file: they can be large, can start with a dash, and have no
    business showing up in the process table."""
    scratch.mkdir(parents=True, exist_ok=True)
    path = scratch / f"write-{index}-{entry['kind']}.md"
    path.write_text(entry["body"], encoding="utf-8")
    return str(path)


def commands(
    entry: dict, *, repo: str, repo_path: Path | str, scratch: Path, index: int = 0, board: str = ""
) -> list[list[str]]:
    """The argv list(s) for one validated entry."""
    kind = entry["kind"]
    scratch = Path(scratch)

    if kind == "push":
        branch = entry["branch"]
        return [["git", "-C", str(repo_path), "push", "--set-upstream", "origin", f"{branch}:refs/heads/{branch}"]]

    if kind == "issue_comment":
        return [["gh", "issue", "comment", _num(entry["issue"]), "--repo", repo, "--body-file", _body_file(entry, scratch, index)]]

    if kind == "issue_body":
        return [["gh", "issue", "edit", _num(entry["issue"]), "--repo", repo, "--body-file", _body_file(entry, scratch, index)]]

    if kind == "issue_create":
        argv = ["gh", "issue", "create", "--repo", repo, "--title", entry["title"], "--body-file", _body_file(entry, scratch, index)]
        for label in entry.get("labels", []):
            argv += ["--label", label]
        return [argv]

    if kind == "label":
        argv = ["gh", "issue", "edit", _num(entry["issue"]), "--repo", repo]
        for label in entry.get("add", []):
            argv += ["--add-label", label]
        for label in entry.get("remove", []):
            argv += ["--remove-label", label]
        return [argv]

    if kind == "label_create":
        argv = ["gh", "label", "create", entry["name"], "--repo", repo, "--force"]
        if entry.get("color"):
            argv += ["--color", entry["color"]]
        if entry.get("description"):
            argv += ["--description", entry["description"]]
        return [argv]

    if kind == "pr_create":
        argv = [
            "gh", "pr", "create", "--repo", repo,
            "--head", entry["head"],
            "--base", entry.get("base") or DEFAULT_BASE,
            "--title", entry["title"],
            "--body-file", _body_file(entry, scratch, index),
        ]
        for label in entry.get("labels", []):
            argv += ["--label", label]
        for login in entry.get("reviewers", []):
            argv += ["--reviewer", login]
        if entry.get("draft"):
            argv.append("--draft")
        return [argv]

    if kind == "pr_edit":
        argv = ["gh", "pr", "edit", _num(entry["pr"]), "--repo", repo]
        for label in entry.get("add_label", []):
            argv += ["--add-label", label]
        for label in entry.get("remove_label", []):
            argv += ["--remove-label", label]
        for login in entry.get("add_reviewer", []):
            argv += ["--add-reviewer", login]
        return [argv]

    if kind == "project_item_add":
        owner, number = board.split("/", 1)
        return [["gh", "project", "item-add", number, "--owner", owner, "--url", entry["url"]]]

    if kind == "project_item_edit":
        return [[
            "gh", "project", "item-edit",
            "--project-id", entry["project_id"],
            "--id", entry["item_id"],
            "--field-id", entry["field_id"],
            "--single-select-option-id", entry["option_id"],
        ]]

    raise ManifestError(f"no command builder for kind {kind!r}")


# -- execution --------------------------------------------------------------


class ExecuteResult(TypedDict):
    """What `execute` returns. Declared because two modules index into it by hand.

    `ok` is false for a manifest that failed validation *and* for one that failed
    part-way through, and the two are told apart by whether `errors` is empty --
    `pr_checks.writes_summary` is the only reader that makes the distinction, and it
    made it against a bare `dict`, where a key typo is a `KeyError` at runtime rather
    than a type error at check time.
    """

    ok: bool
    errors: list[str]
    results: list[dict]


def execute(
    entries: list,
    *,
    repo: str,
    repo_path: Path | str,
    scratch: Path,
    runner=None,
    env: dict[str, str] | None = None,
    board: str = "",
) -> ExecuteResult:
    """Validate the whole manifest, then run it in order with the write credential.

    All-or-nothing on validation: a manifest with one bad entry means something is
    wrong upstream, and half-applying it leaves the issue in a state nobody
    designed. Execution stops at the first failure for the same reason -- opening a
    PR for a branch that never pushed is worse than not opening it.
    """
    # Resolved at call time, not bound as a default: `subprocess.run` is what the
    # driver's own suite monkeypatches, and a default argument would have captured
    # the real one at import and gone straight to the network.
    if runner is None:
        runner = subprocess.run

    errors = validate(entries, repo, board)
    results = [{"kind": (e.get("kind") if isinstance(e, dict) else None), "status": "skipped"} for e in entries]
    if errors:
        return {"ok": False, "errors": errors, "results": results}

    stopped = False
    for i, entry in enumerate(entries):
        if stopped:
            continue
        record: dict = {"kind": entry["kind"], "status": "ok", "returncode": 0, "stdout": "", "stderr": ""}
        cmd_env = env
        if entry.get("kind") in BOARD_KINDS:
            creds = credentials.resolve(env)
            cmd_env = credentials.board_env(env or dict(os.environ), creds)
        for argv in commands(entry, repo=repo, repo_path=repo_path, scratch=Path(scratch), index=i, board=board):
            res = runner(argv, capture_output=True, text=True, env=cmd_env)
            record["returncode"] = res.returncode
            record["stdout"] = getattr(res, "stdout", "") or ""
            record["stderr"] = getattr(res, "stderr", "") or ""
            record["command"] = argv
            if res.returncode != 0:
                record["status"] = "failed"
                stopped = True
                break
        results[i] = record

    return {"ok": not stopped, "errors": [], "results": results}
