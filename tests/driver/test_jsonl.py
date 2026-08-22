"""The one tolerance policy, and the two ways a line can fail to be a record — #261 T3.

Six readers re-derived this policy and did not all reach it. What earns a suite of its
own is the distinction the old copies kept losing: *unparseable* and *parsed but not an
object* are both "not a record", and only one of them looks like an error at the point
it happens. A reader that keeps the second returns a `str` where the caller expects a
`dict`, and the `AttributeError` surfaces frames away from the line that caused it.
"""

from __future__ import annotations

import json

import pytest

from agent_sessions.driver import jsonl


def test_records_are_returned_and_nothing_else_is():
    text = "\n".join([
        json.dumps({"issue": 1}),
        '"a bare string"',
        "42",
        "[1, 2]",
        json.dumps({"issue": 2}),
    ])
    records, skipped = jsonl.parse_records(text)
    assert records == [{"issue": 1}, {"issue": 2}]
    assert skipped == 3


def test_the_partial_final_line_a_live_stream_always_has():
    """The case the policy exists for: appended-to files are read mid-write."""
    text = json.dumps({"issue": 1}) + "\n" + '{"issue": 2, "reason": "half a li'
    records, skipped = jsonl.parse_records(text)
    assert records == [{"issue": 1}]
    assert skipped == 1


def test_blank_lines_are_neither_records_nor_skips():
    records, skipped = jsonl.parse_records("\n\n  \n" + json.dumps({"a": 1}) + "\n\n")
    assert (records, skipped) == ([{"a": 1}], 0)


def test_an_absent_file_is_nothing_yet_rather_than_an_error(tmp_path):
    """The driver asks before the run has made anything, and must not raise."""
    assert jsonl.read_records(tmp_path / "never-written.jsonl") == ([], 0)


def test_a_directory_in_place_of_a_file_is_also_nothing_yet(tmp_path):
    assert jsonl.read_records(tmp_path) == ([], 0)


def test_a_split_multibyte_character_is_counted_not_swallowed(tmp_path):
    """`errors="replace"`, and this is the difference it makes.

    A trailing write cut mid-sequence leaves bytes that are not valid UTF-8. Replacing
    them puts U+FFFD inside the line, which then fails to parse and is *counted*.
    Ignoring them would drop the bytes and can leave a line that parses cleanly into a
    record whose string field is quietly missing characters.
    """
    path = tmp_path / "runs.jsonl"
    path.write_bytes(json.dumps({"reason": "ok"}).encode() + b'\n{"reason": "caf\xc3')
    records, skipped = jsonl.read_records(path)
    assert records == [{"reason": "ok"}]
    assert skipped == 1


@pytest.mark.parametrize("reader", [jsonl.parse_records, jsonl.read_records])
def test_both_entry_points_agree_on_an_empty_input(reader, tmp_path):
    if reader is jsonl.parse_records:
        assert reader("") == ([], 0)
    else:
        empty = tmp_path / "empty.jsonl"
        empty.write_text("", encoding="utf-8")
        assert reader(empty) == ([], 0)
