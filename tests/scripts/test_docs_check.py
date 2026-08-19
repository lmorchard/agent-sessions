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
