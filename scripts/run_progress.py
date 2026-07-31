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

import argparse
import json
import os
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

STREAM_NAME = "stream.jsonl"

#: `last` is one line in a digest that is often read from a log; an assistant text
#: block can be many paragraphs, so it is collapsed and cut to this width.
LAST_TEXT_WIDTH = 100


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
        # Explicit encoding, matching `scripts/assertion_lint.py`: without it the
        # decoding depends on the host locale, and a stream written on one machine
        # could read differently on another. `errors="replace"` stays -- a partial
        # trailing write can split a multi-byte character mid-sequence.
        text = Path(path).read_text(encoding="utf-8", errors="replace")
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


def _as_number(value: object) -> float | int | None:
    """A numeric field, or None if the stream carried something else.

    The module's contract is to degrade to "less information", never to a
    traceback. `read_records` already honours that for a malformed *line*; this
    honours it for a malformed *value*, which is the same failure one field in.
    A `total_cost_usd` of `null`, `"12.01"` or `{}` reaches `format_progress`'s
    `f"${...:.2f}"` otherwise, and a watcher that dies on the thing it is
    watching is worse than no watcher. Booleans are excluded deliberately --
    `True` is an `int` in Python and `$1.00` would be a fabricated reading.
    Raised by the Copilot review on PR #46.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


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
                snap.cost_usd = _as_number(record.get("total_cost_usd"))
            if "duration_ms" in record:
                snap.duration_ms = _as_number(record.get("duration_ms"))
            if "is_error" in record:
                snap.is_error = record.get("is_error")

    return snap


# --- locating a run --------------------------------------------------------


def default_state_dir(repo: str) -> Path:
    """Where the driver keeps `repo`'s state -- mirrored from the driver itself.

    `agent-session-driver.sh:347` derives
    `${XDG_STATE_HOME:-$HOME/.local/state}/agent-session/${REPO//\\//-}`, and this
    reimplements that line. Issue #42 quotes the older `.driver-state/runs/...`
    path, which #27 superseded; implementing what the issue says would point
    `make watch` at a directory the driver no longer writes.
    """
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "agent-session" / repo.replace("/", "-")


def find_latest_run(state_dir: Path | str) -> Path | None:
    """The most recently modified run directory under `state_dir/runs`, if any.

    Absent state dir, absent `runs/`, or no children at all are all the same
    answer -- None, never an exception: an operator starting a watch before the
    first run exists is the normal case, not an error.
    """
    runs = Path(state_dir) / "runs"
    try:
        children = [child for child in runs.iterdir() if child.is_dir()]
    except OSError:
        return None
    if not children:
        return None
    return max(children, key=lambda child: child.stat().st_mtime)


# --- rendering -------------------------------------------------------------


def _format_duration(seconds: float) -> str:
    total = max(int(seconds), 0)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{secs:02d}s"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def _elapsed_seconds(snap: Progress) -> float | None:
    """How long the run has been going, from the two sources that are honest.

    The `result` record's `duration_ms` when the run has emitted one; otherwise
    the `NN-YYYYMMDDTHHMMSSZ` timestamp the driver puts in the directory name.
    **Never the directory's ctime** -- that updates on every write to the stream,
    so a busy run reads as roughly zero seconds old. Got wrong once already.
    """
    if snap.duration_ms is not None:
        try:
            return float(snap.duration_ms) / 1000.0
        except (TypeError, ValueError):
            pass
    _, _, stamp = snap.run_dir.name.rpartition("-")
    try:
        started = datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - started).total_seconds()


def _one_line(text: str, width: int = LAST_TEXT_WIDTH) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= width:
        return collapsed
    return collapsed[: width - 3] + "..."


def format_progress(snap: Progress) -> str:
    """A plain-text digest: no ANSI, no cursor control, no spinner.

    These runs are backgrounded as often as they are watched live, so the output
    has to survive being read out of a log file with `cat`. Lines with no data
    behind them are omitted rather than printed empty.
    """
    lines = []
    if not snap.started:
        # C3, at the presentation layer: a run that has written nothing must not
        # be rendered as a run idling at zero turns.
        why = (
            "not started -- nothing complete written yet"
            if snap.skipped
            else "not started -- no stream.jsonl yet"
        )
        lines.append(f"run {snap.run_dir.name}   {why}")
    else:
        fields = [f"turns {snap.turns}"]
        if snap.cost_usd is not None:
            fields.append(f"${snap.cost_usd:.2f}")
        elapsed = _elapsed_seconds(snap)
        if elapsed is not None:
            fields.append(_format_duration(elapsed))
        lines.append(f"run {snap.run_dir.name}   " + "   ".join(fields))

    if snap.tools:
        tally = "  ".join(
            f"{name} {count}"
            for name, count in sorted(snap.tools.items(), key=lambda kv: (-kv[1], kv[0]))
        )
        lines.append(f"  tools  {tally}")
    if snap.last_text:
        lines.append(f"  last   {_one_line(snap.last_text)}")
    if snap.skipped:
        noun = "line" if snap.skipped == 1 else "lines"
        lines.append(f"  note   {snap.skipped} unparseable {noun} (a live stream is truncated mid-record)")
    return "\n".join(lines)


# --- CLI -------------------------------------------------------------------


def _resolve_run_dir(args) -> Path | None:
    """Explicit RUNDIR, then --state-dir's newest run, then --repo's."""
    if args.rundir:
        candidate = Path(args.rundir)
        return candidate if candidate.is_dir() else None
    if args.state_dir:
        return find_latest_run(Path(args.state_dir))
    if args.repo:
        return find_latest_run(default_state_dir(args.repo))
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="run_progress.py",
        description="Digest a run's stream.jsonl -- turns, tools, last words, cost.",
        epilog="Reads only. This never creates or writes anything under the state dir.",
    )
    parser.add_argument(
        "rundir", nargs="?", metavar="RUNDIR", help="a run directory; overrides the lookups below"
    )
    parser.add_argument("--state-dir", metavar="DIR", help="a driver state dir; watches its newest run")
    parser.add_argument("--repo", metavar="OWNER/NAME", help="derive the state dir the driver would use")
    parser.add_argument("--watch", action="store_true", help="reprint on an interval until interrupted")
    parser.add_argument(
        "--interval", type=float, default=10, metavar="SECONDS", help="watch interval (default: 10)"
    )
    args = parser.parse_args(argv)

    # Fail fast rather than inside the loop: `time.sleep` raises ValueError on a
    # negative, so `--interval -1` would crash the watcher on its second pass,
    # after printing one plausible-looking digest. Zero is rejected too -- a
    # busy-loop polling a file is not a watch interval. Raised by the Copilot
    # review on PR #46.
    if args.interval <= 0:
        parser.error(f"--interval must be greater than 0 (got {args.interval})")

    # A --watch that cannot find a run WAITS for one; only a one-shot read fails.
    # Polling for something that does not exist yet is what watching is for, and
    # `make watch` is most useful started in the terminal beside `make run`,
    # before the run has created its directory.
    #
    # The exception is an explicit RUNDIR: a path that is not a directory is a
    # typo, and a typo cannot fix itself, so that one fails even under --watch
    # rather than looping forever on a misspelling.
    fatal_if_unresolved = not args.watch or bool(args.rundir)
    try:
        while True:
            # Re-resolved every tick, not just once: under --repo a watch left
            # running across the end of one run should pick up the next.
            run_dir = _resolve_run_dir(args)
            if run_dir is None:
                if fatal_if_unresolved:
                    print(f"run_progress.py: {_no_run_message(args)}", file=sys.stderr)
                    return 2
                # Not "0 turns" and not silence -- the same distinction C3 draws
                # inside a run, drawn one level up for the run itself.
                print(f"waiting -- {_no_run_message(args)}")
            else:
                print(format_progress(read_progress(run_dir)))
            if not args.watch:
                return 0
            sys.stdout.flush()
            time.sleep(args.interval)
    except KeyboardInterrupt:
        # An operator ending a watch is not a crash; a traceback here would be
        # noise on top of whatever they were actually reading.
        return 130


def _no_run_message(args) -> str:
    """Why no run resolved. Carries no `prog:` prefix -- it is also printed as the
    body of a `waiting -- ...` line, where a program name reads as an error."""
    if args.rundir:
        return f"not a directory: {args.rundir}"
    if args.state_dir:
        return f"no run directories under {Path(args.state_dir) / 'runs'}"
    if args.repo:
        looked = default_state_dir(args.repo) / "runs"
        return f"no run directories under {looked} (for --repo {args.repo})"
    return "give a RUNDIR, or --state-dir DIR, or --repo OWNER/NAME"


if __name__ == "__main__":
    raise SystemExit(main())
