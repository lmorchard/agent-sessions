#!/usr/bin/env python3
"""Read a run's `stream.jsonl` and say what the run is doing, while it does it.

Why this exists
---------------
`make run` / `make run-self` print nothing between "== invoke #N ==" and the exit
line. A fifty-minute run is a black box -- with megabytes of live signal sitting
on disk the whole time, in the `stream.jsonl` the driver already writes. So this
is a **reader**, not new instrumentation: the signal is already complete, and
emitting progress from inside the run would let the run narrate its own progress.
See issue #42.

Stdlib only, so plain `python3` can run it the way `make docs-check` runs
`docs_check.py` -- no virtualenv between an operator and "is it still alive?".

Three details are load-bearing, each of them a way a naive reader gets it wrong:

  * **A partial final line is normal, not an error.** A live stream is appended
    to while we read it, so the reader routinely opens the file between the
    writer's two `write()` calls. Parsing per-line and counting what failed costs
    one record; `[json.loads(l) for l in f]` costs the whole read, exactly when
    it is wanted most. The skipped count is reported rather than swallowed, so a
    caller can tell "nothing was lost" from "one record was unreadable".

  * **"Not started" is not "0 turns".** A run that has written nothing and a run
    idling at zero turns are opposite situations, and rendering the first as the
    second tells the operator the run is stuck when it is merely young. `started`
    is False if and only if no complete record was read. This project's
    most-repeated lesson (findings.md; `docs_check.py`'s skipped-vs-passed rule):
    a null must not render as a positive.

  * **Every field is `.get()`-guarded.** A truncated or unfamiliar record must
    degrade to "less information", never to a traceback -- same reason as above.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

STREAM_NAME = "stream.jsonl"


@dataclass
class Progress:
    """A snapshot of one run, as of whatever had been flushed when we read it."""

    run_dir: Path
    #: False iff nothing parseable has been written yet -- see the module docstring.
    started: bool = False
    #: Assistant turns; `system` and `user` records are not turns.
    turns: int = 0
    #: tool_use block names, tallied across every assistant record.
    tools: Counter = field(default_factory=Counter)
    #: The most recent `text` block, which is not always the last record's text.
    last_text: str | None = None
    cost_usd: float | None = None
    duration_ms: int | None = None
    is_error: bool | None = None
    #: Complete records read, and lines that would not parse.
    records: int = 0
    skipped: int = 0


def read_records(path: Path | str) -> tuple[list[dict], int]:
    """Parse every complete record; count the ones that aren't.

    A stream being appended to has a partial final line more often than not, so a
    reader that raises on it is a reader that dies exactly when it is wanted. A
    missing file is not an error either -- the driver can ask before the run has
    made anything at all -- and reports as `([], 0)`.
    """
    try:
        text = Path(path).read_text(errors="replace")
    except OSError:
        # Absent file, absent run directory, unreadable: all "nothing yet".
        return [], 0

    records: list[dict] = []
    skipped = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            skipped += 1
            continue
        # A bare scalar on its own line is syntactically valid JSON but is not a
        # record; treating it as one would mean .get() on a str further down.
        if isinstance(record, dict):
            records.append(record)
        else:
            skipped += 1
    return records, skipped


def _blocks(record: dict) -> list:
    """The content blocks of a record, or nothing at all.

    `message` may be absent, and `content` is a bare string on some record
    shapes rather than a list of blocks -- neither may raise.
    """
    message = record.get("message")
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    if not isinstance(content, list):
        return []
    return content


def read_progress(run_dir: Path | str) -> Progress:
    """Digest `run_dir/stream.jsonl` into a Progress snapshot."""
    run_dir = Path(run_dir)
    records, skipped = read_records(run_dir / STREAM_NAME)

    snap = Progress(
        run_dir=run_dir,
        started=bool(records),
        records=len(records),
        skipped=skipped,
    )

    for record in records:
        if not isinstance(record, dict):
            continue
        kind = record.get("type")

        if kind == "assistant":
            snap.turns += 1
            for block in _blocks(record):
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    name = block.get("name")
                    if isinstance(name, str):
                        snap.tools[name] += 1
                elif block.get("type") == "text":
                    text = block.get("text")
                    # Most recent *text block*, not the last record's text: a
                    # record can carry tool calls and no text at all, and the
                    # useful answer to "what is it doing?" is the last thing it
                    # actually said.
                    if isinstance(text, str):
                        snap.last_text = text

        elif kind == "result":
            # Last result wins. A resumed run emits more than one, and the
            # criterion asks for the *latest* cost.
            if "total_cost_usd" in record:
                snap.cost_usd = record.get("total_cost_usd")
            if "duration_ms" in record:
                snap.duration_ms = record.get("duration_ms")
            if "is_error" in record:
                snap.is_error = record.get("is_error")

    return snap
