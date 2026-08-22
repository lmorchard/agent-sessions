#!/usr/bin/env python3
"""Detect assertions that grade the spelling of their subject rather than its behaviour.

Why this exists
---------------
An assertion of the form::

    if grep -q 'trap cleanup EXIT INT TERM' "$DRIVER"; then
      ok "cleanup trap installed on EXIT/INT/TERM"

passes if the literal appears **anywhere** in the driver -- including inside a
comment. `findings.md` (defect class 5) calls that *"a spelling check, not a
test"*: it grades the spelling of the subject rather than its behaviour, and a
comment describing the behaviour satisfies it just as well as the behaviour.

The original defect shipped in the former Bash fixture suites, while a warning
against it sat in a nearby comment without preventing it. That is this project's
most-repeated lesson: an exhortation measures away, a detector does not
(`findings.md` defect class 4, and the instruction files' rationale for
`docs_check.py`).

Two rules
---------
**1. The presence grep.** A line is reported iff it lies in a file matching `SCOPE`
and `grep -q`, `-qE` or `-qF` appears on it with **no `#` earlier on the line**.

`-q` is the whole tell. It discards the match and yields only an exit status, so
the assertion can mean nothing except "the literal is present somewhere". `-c`
produces a *number*, and a number gets compared against an expectation -- delete
the code being counted and the comparison flips. That is why::

    ACTUAL="$(grep -cE '^parked_numbers\\(\\)' "$DRIVER")"
    check "the driver still defines its helper" "1" "$ACTUAL"

is fine and the `-q` form is not.

**2. The same defect in Python**, which is what this detector is now mostly for::

    assert "some literal" in SOME_CHECKED_IN_FILE.read_text()

Reported iff the module also reads a checked-in artifact. See
`scan_source_assertions` for the two stages and for the imprecision each one buys.

**Rule 1 now has no live subject, and that is why rule 2 exists.** The Bash fixture
suites it was written for were deleted by the 2026-08-09 Python conversion, and
measured on this branch there is not one occurrence of the idiom anywhere under
`tests/` outside this detector's own fixtures -- nor can there be, since Python tests
do not shell out to grep. A detector reporting a clean bill over a defect class that
cannot reach it is defect class 6, inside a detector. Rule 1 is kept as a cheap
regression guard should a shell fixture return; rule 2 is the one with subjects, and
it had two live instances when it was added -- both written during #261's own audit,
by the session auditing for them.

Two deliberate non-features on rule 1, both because a false positive trains the
operator to wave the mechanism through (`findings.md`):

  * **The grep's target is not inspected.** Matching on `-q` alone is mechanical;
    deciding what a grep "really means" from its operand is the precision problem
    that got issue #12's general check-linter declined on measured data.
  * **No carve-out for `grep -q` reading stdin** (`| grep -q`, `<<<`), even though
    grepping captured *output* is a legitimate behavioural assertion. Measured:
    neither suite contains one. An untested exception would be speculation and a
    standing bypass; `grep -c ... = 1` covers the case if it ever arises.

Scope
-----
`SCOPE` and `SOURCE_ASSERTION_SCOPE` below are the single source of that fact. This
paragraph used to say `driver/test_*.py`, which #257/#258 falsified when they moved
the suites under `tests/` -- a docstring wrong about its own detector's scope.

The Makefile is out of scope: this detector guards harness assertions, while
`skill-readonly` verifies captured command arguments at the `Popen` boundary.

**The two scopes differ, and the reason is the difference between the rules.**
`commit_lint.py` records it from the outside: *"`assertion_lint` had to solve the
same self-matching problem by narrowing its glob."* Rule 1 is textual, so it cannot
scan a suite whose fixtures contain the idiom -- and this detector's fixtures do.
Rule 2 is an AST question: a fixture is a string constant, a real assertion is an
`Assert` node, and no amount of quoting confuses the two. So rule 2 scans every Python
file under `tests/driver/` and `tests/scripts/` -- harness modules and `conftest.py`
included, not only `test_*.py` -- and rule 1 stays narrow. Widening *rule 1* was
put to a human and declined on measurement (#261, X1): six hits, all six in this
detector's own fixtures, zero real findings.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

#: The linted files, as a glob relative to ROOT. See "Scope" above.
SCOPE = "tests/driver/test_*.py"

#: `grep -q`, `-qE` or `-qF` with no `#` earlier on the line. `[^#]*` cannot
#: consume a `#`, so a commented-out grep can never match -- that false positive
#: is the one that caught issue #28's own author while measuring the defect.
PRESENCE_GREP = re.compile(r"^[^#]*\bgrep\s+-q[EF]?\b")

failures: list[str] = []


#: The files the source-text rule scans. Wider than `SCOPE` above, and it can be:
#: that rule is textual and cannot scan a suite whose fixtures contain the idiom, while
#: this one is an AST question -- a fixture is a string constant, a real assertion is an
#: `Assert` node, and the two are never confused. So the self-matching problem that keeps
#: `SCOPE` narrow simply does not arise here.
#: `*.py`, not `test_*.py`: #261's X3 moved ~700 lines of the full-loop rig into
#: `tests/driver/loop_harness.py`, and under the narrower glob that code left this
#: detector's scope without anyone deciding it should. Harness code is exactly where the
#: rule's target idiom lives, so the scope follows the assertions rather than the
#: filename convention. Nothing under `tests/` is out of bounds for an AST rule.
SOURCE_ASSERTION_SCOPE = ("tests/driver/*.py", "tests/scripts/*.py")

#: Module-level names that conventionally point at a checked-in location. Stage one of
#: the rule: a module that reads one of these is reading an artifact under version
#: control, where "does this literal appear?" grades spelling. A module reading a path
#: built from `tmp_path`, a run directory or a fixture is reading *output*, where the
#: same assertion is ordinary and correct.
REPO_ANCHORS = frozenset({
    "REPO_ROOT", "ROOT", "REPO", "SRC", "SKILL", "SKILL_DIR", "DRIVER", "DRIVER_PKG",
    "MAKEFILE", "SCRIPT", "SCRIPTS", "PHASES", "WORKFLOWS",
})

#: Calls that yield a file's text.
_TEXT_READERS = frozenset({"read_text", "read"})


def _reads_checked_in_artifact(tree: ast.Module) -> bool:
    """True if the module reads text out of a path rooted at a repo anchor."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        reads = (isinstance(func, ast.Attribute) and func.attr in _TEXT_READERS) or (
            isinstance(func, ast.Name) and func.id == "open"
        )
        if not reads:
            continue
        if any(isinstance(sub, ast.Name) and sub.id in REPO_ANCHORS for sub in ast.walk(node)):
            return True
    return False


#: Calls whose result is a sequence of tokens rather than a blob of text. Membership
#: against one of these is a *parsed* assertion -- the remedy this rule recommends -- so
#: flagging it would make the instrument punish its own fix.
_TOKENISERS = frozenset({"split", "splitlines", "keys", "values", "readlines"})


def _sequence_returning_helpers(tree: ast.Module) -> set[str]:
    """Module-level functions annotated as returning a sequence.

    `assert "--dry-run" in _expanded(target)` where `_expanded(...) -> list[str]` is a
    token membership test, not a substring match. The annotation is right there; not
    reading it made the rule flag a correct assertion and, worse, invite a "fix" that
    broke it -- which is what happened the first time this ran.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.returns is None:
            continue
        rendered = ast.unparse(node.returns)
        if rendered.split("[")[0].strip().lower() in ("list", "set", "tuple", "sequence", "frozenset", "dict"):
            names.add(node.name)
    return names


def _function_scopes(tree: ast.Module) -> list[ast.AST]:
    """Every function body, plus the module itself for top-level asserts."""
    scopes: list[ast.AST] = [tree]
    scopes += [
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    return scopes


def _produces_tokens(node: ast.AST) -> bool:
    if isinstance(node, (ast.List, ast.Set, ast.Tuple, ast.Dict, ast.ListComp, ast.SetComp, ast.DictComp)):
        return True
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in _TOKENISERS:
            return True
        if isinstance(func, ast.Name) and func.id in ("list", "set", "sorted", "tuple", "dict"):
            return True
    return False


def _token_container_names_shallow(scope: ast.AST) -> set[str]:
    """Local names bound to a sequence of tokens within this scope."""
    names: set[str] = set()
    for node in ast.walk(scope):
        if isinstance(node, ast.Assign) and _produces_tokens(node.value):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and node.value is not None and _produces_tokens(node.value):
            if isinstance(node.target, ast.Name):
                names.add(node.target.id)
        elif isinstance(node, (ast.For, ast.comprehension)):
            target = getattr(node, "target", None)
            if isinstance(target, ast.Name):
                names.add(target.id)
    return names


def _is_token_container(node: ast.AST, local_names: set[str], helpers: set[str]) -> bool:
    if _produces_tokens(node):
        return True
    if isinstance(node, ast.Name) and node.id in local_names:
        return True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in helpers:
        return True
    return False


def scan_source_assertions(path: Path) -> list[tuple[int, str]]:
    """Every `assert "<literal>" in <text>` in a module that reads a checked-in artifact.

    The `grep -q` rule above is the Bash form of this defect. The Bash fixture suites are
    gone, so that rule now guards a doorway with no door; this is the same class in the
    language the suites are written in, and it had two live instances when it was added.

    Returns `(1-based line number, the unparsed assertion)`, in file order. Takes an
    explicit path and does not consult `ROOT`, matching `scan_file`.

    **The known imprecision, stated rather than hidden.** Stage one is a property of the
    *module*, not of the assertion, so a file that reads a checked-in artifact for one
    purpose and asserts against generated output for another is flagged. Measured on this
    repo when the rule was written: four flagged, two real. The alternative -- tracing each
    assertion's right-hand side back to its source -- was measured at one real in ten, and
    a rule that is wrong nine times out of ten teaches the operator to wave it through.
    The remedy for a false positive here is to assert on parsed structure rather than a
    substring, which is a stronger assertion anyway: `"--issue 704" in text` is satisfied
    by `--issue 7040`, and reading the flag's value is not.

    So membership against a *sequence of tokens* -- something split, a comprehension, a
    literal list -- is deliberately not reported. Without that carve-out the rule would
    flag the exact form it tells you to write, which is the fastest way to have an
    instrument switched off. It was added the first time this rule flagged a fix made in
    response to it.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return []

    if not _reads_checked_in_artifact(tree):
        return []

    helpers = _sequence_returning_helpers(tree)
    module_containers = _token_container_names_shallow(tree)

    # Each assertion is judged in its innermost function scope, with the module's names
    # still visible. `ast.walk` is breadth-first, so a deeper scope always claims an
    # assertion after a shallower one -- which is what makes the last write correct, and
    # is also why an earlier version reported every assertion twice.
    owner: dict[int, ast.AST] = {}
    nodes: dict[int, ast.Assert] = {}
    for scope in _function_scopes(tree):
        for node in ast.walk(scope):
            if isinstance(node, ast.Assert):
                owner[id(node)] = scope
                nodes[id(node)] = node

    cache: dict[int, set[str]] = {}
    found = []
    for key, node in nodes.items():
        scope = owner[key]
        if id(scope) not in cache:
            cache[id(scope)] = module_containers | _token_container_names_shallow(scope)
        test = node.test
        if not (isinstance(test, ast.Compare) and len(test.ops) == 1
                and isinstance(test.ops[0], ast.In)):
            continue
        left, right = test.left, test.comparators[0]
        if not (isinstance(left, ast.Constant) and isinstance(left.value, str)):
            continue
        if _is_token_container(right, cache[id(scope)], helpers):
            continue
        found.append((node.lineno, ast.unparse(test)))
    return sorted(found)


def scan_file(path: Path) -> list[tuple[int, str]]:
    """Every presence-grep assertion in one file.

    Returns `(1-based line number, the source line minus its trailing newline)`
    for each offending line, in file order.

    Takes an explicit path and deliberately does **not** consult `ROOT`, so a
    caller can scan a real repo file while `ROOT` points somewhere else.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    return [
        (n, line)
        for n, line in enumerate(text.splitlines(), start=1)
        if PRESENCE_GREP.search(line)
    ]


def source_assertion_files() -> list[Path]:
    """Every file the source-text rule scans, deduplicated across its globs."""
    seen: dict[str, Path] = {}
    for pattern in SOURCE_ASSERTION_SCOPE:
        for path in ROOT.glob(pattern):
            seen[str(path)] = path
    return sorted(seen.values())


def lint_files() -> None:
    """Scan every in-scope file under `ROOT`, appending to `failures`."""
    for path in sorted(ROOT.glob(SCOPE)):
        rel = path.relative_to(ROOT)
        for lineno, line in scan_file(path):
            failures.append(f"{rel}:{lineno}: presence-grep assertion: {line.strip()}")

    for path in source_assertion_files():
        rel = path.relative_to(ROOT)
        for lineno, text in scan_source_assertions(path):
            failures.append(
                f"{rel}:{lineno}: literal asserted against checked-in text: {text}"
            )


def main() -> int:
    lint_files()

    scanned = sorted(p.relative_to(ROOT) for p in ROOT.glob(SCOPE))
    source_scanned = source_assertion_files()

    # A null must not render as a positive -- this project's most-repeated lesson. Zero
    # files scanned is a broken scope, not a clean bill, and **both** scopes are checked:
    # the source-text rule is the one with live subjects, so a glob that silently stopped
    # matching would be the more expensive of the two to lose.
    if not scanned:
        print(f"FAIL: assertion-lint matched no files for scope {SCOPE!r}")
        return 1
    if not source_scanned:
        print(f"FAIL: assertion-lint matched no files for scope {SOURCE_ASSERTION_SCOPE!r}")
        return 1

    for f in failures:
        print(f"  FAIL  {f}")

    if failures:
        print(
            f"\nassertion-lint: {len(failures)} assertion(s) that grade spelling rather "
            f"than behaviour. A literal found in a COMMENT satisfies them. Compare a "
            f"`grep -c` count against an expectation, assert against parsed structure "
            f"rather than raw text, or assert the behaviour through the shipped code. "
            f"See issue #28 and #261's X1."
        )
        return 1

    print(
        f"assertion-lint: no presence-grep assertions in {len(scanned)} file(s) "
        f"matching {SCOPE}; no literals asserted against checked-in text in "
        f"{len(source_scanned)} file(s)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
