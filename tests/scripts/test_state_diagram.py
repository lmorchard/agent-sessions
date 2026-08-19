from pathlib import Path

from agent_sessions.scripts import state_diagram


def test_generate_diagram():
    diag = state_diagram.generate_diagram()
    assert "flowchart TD" in diag
    assert "1. Issue Selection & Intake" in diag
    assert "2. PR Reconciler & Phases" in diag
    assert "3. Gate Classification & Verdicts" in diag
    assert "4. Park & Recovery" in diag
    assert "reconciler.handle_pr_reconcile()" in diag
    assert "gate.classify()" in diag


def test_extract_diagram_block():
    content = "before\n<!-- BEGIN ISSUE_PR_STATE_DIAGRAM -->hello<!-- END ISSUE_PR_STATE_DIAGRAM -->after"
    extracted = state_diagram.extract_diagram_block(content)
    assert extracted == "hello"


def test_update_and_check_readme(tmp_path: Path):
    readme = tmp_path / "README.md"
    readme.write_text(
        "Intro\n\n<!-- BEGIN ISSUE_PR_STATE_DIAGRAM -->\nold\n<!-- END ISSUE_PR_STATE_DIAGRAM -->\nOutro\n",
        encoding="utf-8",
    )

    assert not state_diagram.check_readme(readme)

    ok = state_diagram.update_readme(readme)
    assert ok

    assert state_diagram.check_readme(readme)
    updated = readme.read_text(encoding="utf-8")
    assert "flowchart TD" in updated
    assert "Intro" in updated
    assert "Outro" in updated


def test_main_check_live_readme():
    assert state_diagram.main(["--check"]) == 0
