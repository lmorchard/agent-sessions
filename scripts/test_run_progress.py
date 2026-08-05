"""Frozen acceptance tests for scripts/run_progress.py (issue #42).

Written **before** the implementation exists, and deliberately without sight of
the plan: they grade the *criteria* (C1/C2/C3), not any particular way of
satisfying them. Until `run_progress.py` lands, collection fails with
`ModuleNotFoundError` — that is the intended starting state.

They **import** the module rather than shelling out to it, for the same reason
`test_docs_check.py` and `driver/test_gate.py` do: a subprocess test grades the
CLI's spelling, while an import grades the thing that ships.

Every fixture is a throwaway run directory in `tmp_path`, built from record
shapes measured off a live `stream.jsonl` — one JSON object per line, with the
`system` and `user` records that a real stream carries and this reporter must
ignore. Nothing here reads a real run, so a test can never go red because some
run on disk changed.
"""

import json
import sys
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import run_progress  # noqa: E402


# --- fixture builders ------------------------------------------------------
#
# Record shapes are trimmed to the fields the reporter can legitimately depend
# on, plus enough surrounding noise (uuid, session_id, extra result fields) that
# a reporter which assumed an exact key set would be caught.

def text_block(s: str) -> dict:
    return {"type": "text", "text": s}


def tool_block(name: str) -> dict:
    return {"type": "tool_use", "id": f"toolu_{name}", "name": name, "input": {}}


def assistant(*blocks: dict) -> dict:
    return {
        "type": "assistant",
        "uuid": "u-assistant",
        "session_id": "s-1",
        "message": {"role": "assistant", "content": list(blocks)},
    }


def result(cost: float) -> dict:
    return {
        "type": "result",
        "subtype": "success",
        "total_cost_usd": cost,
        "duration_ms": 1000,
        "num_turns": 3,
        "is_error": False,
    }


NOISE_SYSTEM = {"type": "system", "subtype": "init", "session_id": "s-1"}
NOISE_USER = {"type": "user", "uuid": "u-user", "message": {"role": "user", "content": []}}


def write(run_dir: Path, records: list[dict], trailing: str = "") -> Path:
    """Build a run directory containing a stream.jsonl of `records`.

    `trailing` is appended verbatim after the last complete line, which is how
    the C2 partial-write fixture is made.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(r) + "\n" for r in records) + trailing
    (run_dir / "stream.jsonl").write_text(body)
    return run_dir


LAST_TEXT = "and here is the third assistant turn"

#: Three assistant records, the middle one carrying two `tool_use` blocks, for a
#: tally of Bash=2 / Read=1. The middle record deliberately has **no** text, so a
#: reporter that returned "the last record's text" instead of "the most recent
#: text block" would still pass — it is the third record that must win.
C1_RECORDS = [
    NOISE_SYSTEM,
    assistant(text_block("first assistant turn"), tool_block("Bash")),
    NOISE_USER,
    assistant(tool_block("Bash"), tool_block("Read")),
    NOISE_USER,
    assistant(text_block(LAST_TEXT)),
    result(1.5),
]


# --- C1: the four reported quantities --------------------------------------

def test_reports_turns_tools_last_text_and_cost(tmp_path):
    """C1 — turn count, tool tally, most recent assistant text, latest cost."""
    snap = run_progress.read_progress(write(tmp_path / "run", C1_RECORDS))

    # The positive control for C3's flag: it must discriminate, not be constant.
    assert snap.started is True
    assert snap.turns == 3
    assert dict(snap.tools) == {"Bash": 2, "Read": 1}
    assert snap.last_text == LAST_TEXT
    assert snap.cost_usd == 1.5
    # A clean stream has nothing unparseable in it; C2 is where this goes up.
    assert snap.skipped == 0


def test_latest_result_record_supplies_the_cost(tmp_path):
    """C1 — real streams carry more than one `result`; the criterion says *latest*."""
    records = [*C1_RECORDS, assistant(text_block("resumed")), result(2.75)]
    snap = run_progress.read_progress(write(tmp_path / "run", records))

    assert snap.cost_usd == 2.75
    assert snap.turns == 4


# --- C2: the file is being appended to while we read it --------------------

def test_partial_final_line_reports_every_complete_record(tmp_path):
    """C2 — a truncated tail must cost only itself, and must not raise."""
    # Mid-record truncation with no trailing newline: exactly what a reader sees
    # when it opens the file between the writer's two write() calls.
    run_dir = write(tmp_path / "run", C1_RECORDS, trailing='{"type": "assis')

    # No pytest.raises guard: an exception here fails the test as an error, which
    # is the "SHALL NOT raise" half of the criterion.
    snap = run_progress.read_progress(run_dir)

    assert snap.started is True
    assert snap.turns == 3
    assert dict(snap.tools) == {"Bash": 2, "Read": 1}
    assert snap.last_text == LAST_TEXT
    assert snap.cost_usd == 1.5
    # Counted, not silently swallowed — a caller should be able to tell the
    # difference between "nothing was lost" and "one record was unreadable".
    assert snap.skipped == 1


# --- C3: a null must not render as a positive ------------------------------
#
# This project's most-repeated lesson (findings.md, and docs_check.py's
# `skips`): "0 turns" and "hasn't started" are different facts, and reporting
# the first when the second is true reads as an idle run to whoever is watching.

def test_empty_stream_is_not_started(tmp_path):
    """C3 — a zero-byte stream.jsonl is 'not started', not an idle run."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "stream.jsonl").write_text("")

    snap = run_progress.read_progress(run_dir)

    assert snap.started is False
    assert snap.last_text is None
    assert snap.cost_usd is None


def test_missing_stream_is_not_started(tmp_path):
    """C3 — same verdict when the file was never created, and no raise."""
    empty_run = tmp_path / "run"
    empty_run.mkdir()
    snap = run_progress.read_progress(empty_run)
    assert snap.started is False
    assert snap.last_text is None
    assert snap.cost_usd is None

    # The run directory itself may not exist yet either — the driver can ask
    # before the run has made anything at all.
    absent = run_progress.read_progress(tmp_path / "nonexistent-run")
    assert absent.started is False


def test_missing_state_dir_is_configuration_error(tmp_path, capsys, monkeypatch):
    """C2 — a non-existent state directory is a configuration error, not a wait."""
    import run_progress
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    
    # State dir does not exist -> configuration error
    args = ["--repo", "lmorchard/missing"]
    
    # Check that main returns 2
    exit_code = run_progress.main(args)
    assert exit_code == 2
    
    captured = capsys.readouterr()
    assert "waiting --" not in captured.err
    assert "waiting --" not in captured.out
    assert "error: state directory" in captured.err
    assert "does not exist (misconfigured repo?)" in captured.err

    # Same for watch mode - should fail fast on misconfiguration
    exit_code = run_progress.main(["--repo", "lmorchard/missing", "--watch"])
    assert exit_code == 2
    captured = capsys.readouterr()
    assert "waiting --" not in captured.err
    assert "waiting --" not in captured.out
    assert "error: state directory" in captured.err

    # Create the state directory but leave it empty of runs -> wait
    state_dir = run_progress.default_state_dir("lmorchard/empty")
    state_dir.mkdir(parents=True)
    
    # One-shot mode fails with 2 but doesn't complain about misconfiguration
    exit_code = run_progress.main(["--repo", "lmorchard/empty"])
    assert exit_code == 2
    
    captured = capsys.readouterr()
    assert "error: state directory" not in captured.err
    assert "no run directories" in captured.err
