import json
import os
from pathlib import Path

from agent_sessions.scripts import evidence


def test_is_judgment_park():
    assert evidence.is_judgment_park("gate-human", "")
    assert evidence.is_judgment_park("parked", "parked by agent during triage: foo")
    assert evidence.is_judgment_park("parked", "parked by agent during refine: bar")
    assert not evidence.is_judgment_park("parked", "no PR opened")
    assert not evidence.is_judgment_park("failed", "")
    assert not evidence.is_judgment_park("incomplete", "")

def test_is_mechanical_park():
    assert evidence.is_mechanical_park("failed", "")
    assert evidence.is_mechanical_park("driver-fault", "")
    assert evidence.is_mechanical_park("budget-exhausted", "")
    assert evidence.is_mechanical_park("no-gate", "")
    assert evidence.is_mechanical_park("ci-stale", "")
    assert evidence.is_mechanical_park("parked", "no PR opened")
    assert not evidence.is_mechanical_park("parked", "parked by agent during execute: foo")
    assert not evidence.is_mechanical_park("gate-eligible", "")
    assert evidence.is_mechanical_park("incomplete", "") # Loop-breaker or unpark-for-reevaluation is mechanical

def _write_ledger(state_dir: Path, rows: list[dict]) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "runs.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )


ROWS = [
    {"issue": 1, "repo": "foo/bar", "phase": "triage", "outcome": "gate-human", "reason": "", "started": "20260101T000000Z"},
    {"issue": 2, "repo": "foo/bar", "phase": "execute", "outcome": "parked", "reason": "parked by agent during execute: needs answer", "started": "20260102T000000Z"},
    {"issue": 3, "repo": "foo/bar", "phase": "execute", "outcome": "budget-exhausted", "reason": "", "started": "20260103T000000Z"},
    {"issue": 4, "repo": "foo/bar", "outcome": "failed", "reason": "something", "started": "20260104T000000Z"},
]


def test_main_reads_an_explicit_state_dir(tmp_path: Path, capsys) -> None:
    """Real files in tmp_path, not a patched `builtins.open`.

    The previous version replaced `builtins.open` process-wide and made
    `Path.is_file` return True unconditionally, so any file read during the call got the
    fixture and the discovery path was never exercised at all -- which is how a hardcoded
    `.driver-state` survived #27 superseding it.
    """
    state_dir = tmp_path / "state"
    _write_ledger(state_dir, ROWS)

    assert evidence.main(["--state-dir", str(state_dir)]) == 0

    out = capsys.readouterr().out
    assert str(state_dir / "runs.jsonl") in out, "the report should name the ledger it read"
    assert "triage" in out
    assert "execute" in out
    assert "unknown" in out, "a row without a phase should group as unknown, not vanish"
    assert "Judgment Parks:   2" in out
    assert "Mechanical Parks: 2" in out
    assert "Ratio (J/M):      1.00" in out
    assert "Total runs:       4" in out


def test_discovery_defaults_to_every_repo_under_the_live_state_root(tmp_path: Path, monkeypatch) -> None:
    """The defect this closes: the default must be the driver's real state root.

    `isolate_state_dir` in conftest already points XDG_STATE_HOME at tmp_path, so this
    exercises the same derivation a real run uses.
    """
    root = Path(os.environ["XDG_STATE_HOME"]) / "agent-session"
    _write_ledger(root / "owner-one", ROWS[:2])
    _write_ledger(root / "owner-two", ROWS[2:])
    (root / "no-ledger-here").mkdir(parents=True, exist_ok=True)

    found = evidence.discover_ledgers()

    assert found == [
        root / "owner-one" / "runs.jsonl",
        root / "owner-two" / "runs.jsonl",
    ], "discovery should find every per-repo ledger and skip directories without one"


def test_a_repo_selects_exactly_one_ledger(tmp_path: Path) -> None:
    root = Path(os.environ["XDG_STATE_HOME"]) / "agent-session"
    _write_ledger(root / "owner-one", ROWS)

    assert evidence.discover_ledgers(repo="owner/one") == [root / "owner-one" / "runs.jsonl"]


def test_the_legacy_state_dir_is_no_longer_the_default(tmp_path: Path, monkeypatch) -> None:
    """The polarity check for the actual bug.

    A `.driver-state/runs.jsonl` in the working directory must not be picked up, or the
    report silently renders the pre-#27 archive again.
    """
    monkeypatch.chdir(tmp_path)
    _write_ledger(tmp_path / ".driver-state", ROWS)

    assert evidence.discover_ledgers() == [], (
        "discovery found something under .driver-state/, which #27 superseded"
    )


def test_missing_ledgers_report_where_they_looked(tmp_path: Path, capsys) -> None:
    assert evidence.main([]) == 1
    out = capsys.readouterr().out
    assert "No runs.jsonl found" in out
    assert "agent-session" in out, "the message should name the path it expected"


def test_unparsed_lines_are_counted_not_dropped(tmp_path: Path, capsys) -> None:
    """A null must not render as a positive: a dropped row has to be visible."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "runs.jsonl").write_text(
        json.dumps(ROWS[0]) + "\n" + "{not json\n" + "[1, 2, 3]\n", encoding="utf-8"
    )

    assert evidence.main(["--state-dir", str(state_dir)]) == 0

    out = capsys.readouterr().out
    assert "Total runs:       1" in out
    assert "Unparsed lines:   2" in out
