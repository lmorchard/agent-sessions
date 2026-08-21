"""Reading JSON-lines streams, with one tolerance policy instead of six.

Why this module exists
----------------------
`run_progress.read_records` was the considered version and said why: *a stream being
appended to has a partial final line more often than not, so a reader that raises on it
is a reader that dies exactly when it is wanted.* Five other places re-derived that
policy, and they did not all reach it. `backend_permission_probe.observed_denials`
collected whatever `json.loads` returned and then called `.get` on it, so one line
holding a bare string or number in an agent's transcript raised `AttributeError` inside
the permission probe -- the tool whose whole job is to report on a backend that is
behaving oddly.

Lives beside `labels.py` and for the same reason: `scripts/` already imports from
`driver/`, never the reverse, so anything both sides need lives on the driver side.

**Three readers deliberately do not use this, and each is right not to.**

- `writes.parse_manifest` *raises* on a malformed line, with the line number. A manifest
  is a fixed-size document an agent just wrote, not a stream being appended to, and a
  dropped entry there is a park comment that silently never posts.
- `agent_runner.stream_has_events` counts any syntactically valid line, bare scalars
  included, because it answers "did the agent emit anything at all" rather than "what
  did it emit". Dropping non-records would make a scalar-only stream read as empty,
  which is the distinction it exists to make.
- `agent_runner.read_stream_json_lines` is the raw-transcript pass-through.

That list is the point of writing this down: the duplication was never uniform, so a
sweep that consolidated all of it would have been wrong in three places.
"""

from __future__ import annotations

import json
from pathlib import Path


def parse_records(text: str) -> tuple[list[dict], int]:
    """Every complete record in `text`, and a count of the lines that were not one.

    Skipped covers both halves of "not a record": a line that does not parse, and a
    line that parses to something other than an object. The second is the one that
    bites -- a bare scalar on its own line is valid JSON, and treating it as a record
    means `.get` on a `str` several frames later, where nothing names the real cause.

    The count is returned rather than logged because a caller that reports "0 runs"
    needs to distinguish *nothing to report* from *nothing readable*; this project's
    rule is that a null must not render as a positive.
    """
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
        if isinstance(record, dict):
            records.append(record)
        else:
            skipped += 1
    return records, skipped


def read_records(path: Path | str) -> tuple[list[dict], int]:
    """`parse_records` over a file. A file that cannot be read is `([], 0)`.

    Absent file, absent run directory, unreadable: all "nothing yet", because the
    driver can ask before the run has made anything at all.

    Explicit encoding, matching `scripts/assertion_lint.py`: without it the decoding
    depends on the host locale, and a stream written on one machine could read
    differently on another. `errors="replace"` rather than `"ignore"` -- a partial
    trailing write can split a multi-byte character mid-sequence, and replacing it
    leaves a line that fails to parse and is counted, where ignoring it can leave one
    that parses with a silently corrupted string.
    """
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [], 0
    return parse_records(text)
