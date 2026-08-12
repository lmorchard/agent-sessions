import json
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

def test_main_with_fixture(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.is_file", lambda self: True)

    runs = [
        {"issue": 1, "repo": "foo/bar", "phase": "triage", "outcome": "gate-human", "reason": "", "started": "20260101T000000Z"},
        {"issue": 2, "repo": "foo/bar", "phase": "execute", "outcome": "parked", "reason": "parked by agent during execute: needs answer", "started": "20260102T000000Z"},
        {"issue": 3, "repo": "foo/bar", "phase": "execute", "outcome": "budget-exhausted", "reason": "", "started": "20260103T000000Z"},
        {"issue": 4, "repo": "foo/bar", "outcome": "failed", "reason": "something", "started": "20260104T000000Z"},
    ]

    def mock_open(file, mode, encoding):
        from io import StringIO
        return StringIO("\n".join(json.dumps(r) for r in runs))

    monkeypatch.setattr("builtins.open", mock_open)

    import sys
    from io import StringIO

    captured = StringIO()
    monkeypatch.setattr(sys, "stdout", captured)

    assert evidence.main() == 0

    out = captured.getvalue()
    assert "triage" in out
    assert "execute" in out
    assert "unknown" in out
    assert "Judgment Parks:   2" in out
    assert "Mechanical Parks: 2" in out
    assert "Ratio (J/M):      1.00" in out
