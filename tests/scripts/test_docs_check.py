import re

import pytest

from agent_sessions.scripts import docs_check

RISK_POLICY = """## Risk-gated paths (off-limits to unattended work)

The default is `needs-review`.

- **`src/agent_sessions/driver/agent_session_driver.py`** is gated.

### Drivable (the allowlist)

- **`docs/**`** is drivable.

## Governing principle
"""


@pytest.fixture
def policy_root(tmp_path, monkeypatch):
    monkeypatch.setattr(docs_check, "ROOT", tmp_path)
    docs_check.failures.clear()
    return tmp_path


def write_policy_doc(root, name, prefix, policy=RISK_POLICY):
    (root / name).write_text(f"{prefix}\n\n{policy}", encoding="utf-8")


def test_risk_policy_parity_ignores_instruction_text_outside_policy(policy_root):
    write_policy_doc(policy_root, "AGENTS.md", "Codex skills live in ~/.Codex/skills.")
    write_policy_doc(policy_root, "CLAUDE.md", "Claude skills live in ~/.claude/skills.")

    checker = getattr(docs_check, "check_risk_policy_parity", None)
    assert checker is not None, "docs-check has no AGENTS.md/CLAUDE.md risk-policy parity guard"
    checker()

    assert docs_check.failures == []


def test_risk_policy_parity_rejects_controlled_divergence(policy_root):
    write_policy_doc(policy_root, "AGENTS.md", "Codex instructions")
    write_policy_doc(
        policy_root,
        "CLAUDE.md",
        "Claude instructions",
        RISK_POLICY.replace("`docs/**`", "`documentation/**`"),
    )

    checker = getattr(docs_check, "check_risk_policy_parity", None)
    assert checker is not None, "docs-check has no AGENTS.md/CLAUDE.md risk-policy parity guard"
    checker()

    assert docs_check.failures == [
        "AGENTS.md and CLAUDE.md risk-path policies differ; keep the complete "
        "'Risk-gated paths' sections aligned"
    ]


def check_line(line: str) -> list:
    failures = []
    forbidden_patterns = [
        (r"\bnot proven\b", "claim wears the clothes of a judgment; use `make evidence` instead"),
        (r"\bnever been driven\b", "claim wears the clothes of a judgment; use `make evidence` instead"),
        (r"\b([a-z]+) repositories\b", "bare repo count; use `make evidence` instead"),
        (r"\b([a-z]+) PRs\b", "bare PR count; use `make evidence` instead", lambda m: m.group(0) not in ("open PRs", "draft PRs", "the PRs", "all PRs", "those PRs")),
    ]

    line_lower = line.lower()
    if "not proven" in line_lower and ("list survived" in line_lower or "count in disguise" in line_lower):
        return failures
    if "never been driven" in line_lower and "count in disguise" in line_lower:
        return failures
    if "repositories" in line_lower and "runs against two repositories" in line_lower and "count in disguise" in line_lower:
        return failures
    if "not proven" in line_lower and ("list" in line_lower or "count" in line_lower or "defect class" in line_lower):
        return failures
    if re.search(r"\d{4}-\d{2}-\d{2}", line):
        return failures

    for pattern, reason, *cond in forbidden_patterns:
        m = re.search(pattern, line, re.IGNORECASE)
        if m:
            if cond and not cond[0](m):
                continue
            failures.append(m.group(0))
    return failures

def test_docs_check_world_state_claims():
    assert len(check_line("This is not proven yet")) == 1
    assert len(check_line("It has never been driven before")) == 1
    assert len(check_line("Runs against two repositories")) == 1
    assert len(check_line("We have seven PRs open")) == 1

    # Exclusions
    assert len(check_line("We have open PRs")) == 0
    assert len(check_line("As of 2026-08-10, it is not proven")) == 0 # Dated fact escape hatch
    assert len(check_line("The not proven list survived")) == 0 # Rule explanation


# --- is_shim: the guard against a partition naming a facade -------------------
#
# `check_partition`'s `is_shim` guard exists so the risk partition cannot name a
# re-export facade in place of the implementation it hides -- gating a facade reads
# as protection and provides none. It missed the live instance it was written for:
# `src/agent_sessions/driver/agent_session_driver.py` is a pure facade whose own
# docstring opens "Defines nothing itself", and the old predicate (a marker string,
# or fewer than 30 lines mentioning `from agent_sessions`) matched neither half of
# it. The file carries no marker and runs past 150 lines.
#
# Length was never the property that mattered. These checks pin the property that
# does -- defining nothing of its own -- against real files on both sides of the
# line, plus tmp_path divergences for the two ways the predicate could go wrong.

DRIVER_PKG = docs_check.ROOT / "src" / "agent_sessions" / "driver"


def test_is_shim_flags_a_facade_that_defines_nothing():
    """The live instance the guard was written for and did not catch."""
    facade = DRIVER_PKG / "agent_session_driver.py"
    assert facade.is_file(), f"{facade} is gone; this check's subject no longer exists"
    assert docs_check.is_shim(facade), (
        "agent_session_driver.py re-exports and defines nothing, so the partition "
        "naming it names a facade -- is_shim has to say so"
    )


@pytest.mark.parametrize("name", ["lifecycle.py", "gate.py", "router.py", "writes.py"])
def test_is_shim_leaves_real_implementations_alone(name):
    """The control. These are the modules the partition should be naming."""
    module = DRIVER_PKG / name
    assert module.is_file(), f"{module} is gone; this check's subject no longer exists"
    assert not docs_check.is_shim(module)


def test_is_shim_ignores_a_module_that_defines_nothing_and_imports_nothing(tmp_path):
    """Controlled divergence on the "defines nothing" half.

    A constants module has no functions and no classes either. Flagging it would
    make the guard reject a legitimately gated policy file, so both halves of the
    predicate are load-bearing and this proves it.
    """
    constants = tmp_path / "constants.py"
    constants.write_text('PARK_LABEL = "agent-session:needs-human"\nTTL = 600\n')
    assert not docs_check.is_shim(constants)


def test_is_shim_flags_a_star_reexport(tmp_path):
    barrel = tmp_path / "barrel.py"
    barrel.write_text("from agent_sessions.driver.lifecycle import *  # noqa: F403\n")
    assert docs_check.is_shim(barrel)


def test_is_shim_ignores_a_module_that_imports_and_defines_its_own_code(tmp_path):
    """Controlled divergence on the "imports names" half.

    Most real modules import. The distinguishing property is whether anything
    originates here, so one definition is enough to make a file not a facade.
    """
    real = tmp_path / "real.py"
    real.write_text(
        "from agent_sessions.driver.output import say\n"
        "\n"
        "def announce(msg):\n"
        "    say(msg)\n"
    )
    assert not docs_check.is_shim(real)


def test_is_shim_ignores_a_non_python_file(tmp_path):
    """`driver/agent-session-driver.sh` is named in the partition and is not parseable."""
    launcher = tmp_path / "launcher.sh"
    launcher.write_text('#!/usr/bin/env bash\nexec python -m agent_sessions.driver "$@"\n')
    assert not docs_check.is_shim(launcher)


# --- check_partition: a facade may be named, but not on its own ---------------

FACADE_POLICY = """## Risk-gated paths (off-limits to unattended work)

The default is `needs-review`.

{bullets}

### Drivable (the allowlist)

- **`docs/`** is drivable.

## Governing principle
"""


def _package_with_facade(root):
    """A minimal src-layout package holding one facade and the module it re-exports."""
    pkg = root / "src" / "agent_sessions" / "driver"
    pkg.mkdir(parents=True)
    (pkg / "lifecycle.py").write_text("def classify_and_record(ctx):\n    return ctx\n")
    (pkg / "facade.py").write_text(
        "from agent_sessions.driver.lifecycle import classify_and_record\n"
        '\n__all__ = ["classify_and_record"]\n'
    )
    (root / "docs").mkdir()


def test_partition_rejects_a_facade_named_without_its_implementation(policy_root):
    """Controlled divergence: the facade alone is the defect the guard is for."""
    _package_with_facade(policy_root)
    (policy_root / "CLAUDE.md").write_text(
        FACADE_POLICY.format(
            bullets="- **`src/agent_sessions/driver/facade.py`** is gated."
        ),
        encoding="utf-8",
    )

    docs_check.check_partition()

    assert len(docs_check.failures) == 1
    assert "facade.py" in docs_check.failures[0]
    assert "lifecycle.py" in docs_check.failures[0], (
        "the failure should name the implementation the partition is missing, "
        "not just complain that a facade was named"
    )


def test_partition_accepts_a_facade_named_alongside_its_implementation(policy_root):
    """A facade can be gated for its own reason once the implementation is gated too.

    An entry point is worth gating even after it thins out -- becoming thin does not
    silently widen the partition. What the guard is protecting against is the facade
    standing in *for* the implementation, so naming both is not the defect.
    """
    _package_with_facade(policy_root)
    (policy_root / "CLAUDE.md").write_text(
        FACADE_POLICY.format(
            bullets=(
                "- **`src/agent_sessions/driver/lifecycle.py`** holds the routing.\n"
                "- **`src/agent_sessions/driver/facade.py`** is the entry point.\n"
            )
        ),
        encoding="utf-8",
    )

    docs_check.check_partition()

    assert docs_check.failures == []


def test_partition_accepts_a_multi_source_facade_when_one_source_is_named(policy_root):
    """*Any*, not *all* -- and this is the check that pins the difference.

    The real facade re-exports from five modules. Demanding a bullet for each would
    fill the partition with entries carrying no reason, and buy nothing: unlisted paths
    are `needs-review` by default, so their absence exposes nothing. One named source
    is enough to prove the facade is not being substituted for the implementation.
    """
    pkg = policy_root / "src" / "agent_sessions" / "driver"
    pkg.mkdir(parents=True)
    (pkg / "lifecycle.py").write_text("def classify_and_record(ctx):\n    return ctx\n")
    (pkg / "locks.py").write_text("def acquire_lock(n):\n    return n\n")
    (pkg / "board.py").write_text("def move(n):\n    return n\n")
    (pkg / "facade.py").write_text(
        "from agent_sessions.driver.lifecycle import classify_and_record\n"
        "from agent_sessions.driver.locks import acquire_lock\n"
        "from agent_sessions.driver.board import move\n"
    )
    (policy_root / "docs").mkdir()
    (policy_root / "CLAUDE.md").write_text(
        FACADE_POLICY.format(
            bullets=(
                "- **`src/agent_sessions/driver/lifecycle.py`** holds the routing.\n"
                "- **`src/agent_sessions/driver/facade.py`** is the entry point.\n"
            )
        ),
        encoding="utf-8",
    )

    docs_check.check_partition()

    assert docs_check.failures == []
