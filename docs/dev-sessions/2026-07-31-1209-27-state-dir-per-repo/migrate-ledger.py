#!/usr/bin/env python3
"""Split ./.driver-state/runs.jsonl into the per-repo ledgers, non-destructively.

The issue's second design decision: "Split the existing runs.jsonl rows by their
`repo` field into the two new per-repo ledgers, and leave ./.driver-state/ in
place as an archive." Every row already carries `repo`, so the split is mechanical.

This is a ONE-TIME HOST-LOCAL operation, not driver code. No criterion asks for
migration logic, and a one-shot migration living permanently in the driver would
be dead weight -- so it lives here, as a re-runnable, auditable artifact.

Nothing is deleted or modified under ./.driver-state/. Guard G3 is the check for
that (probe-04-g3-fingerprint.py); this script only ever READS the archive.

Idempotent: a destination ledger that already holds rows is reported and skipped,
never appended to, so a second run cannot duplicate history.

    python3 .../migrate-ledger.py            # report what would happen
    python3 .../migrate-ledger.py --apply    # write the per-repo ledgers

Undo: delete the per-repo directories it names. The archive is untouched.
"""
import json
import os
import pathlib
import subprocess
import sys

# The pre-#27 archive lives in the MAIN checkout -- `.driver-state/` is gitignored,
# so it exists only there and not in a linked worktree. Derived from git rather
# than hardcoded to one developer's home, which is what this line used to do and
# which made the script fail for everyone else even when their archive existed.
# Raised by the Copilot review on PR #44. `--git-common-dir` rather than
# `--git-dir`: inside a linked worktree only the common dir points at the main
# checkout. `AGENT_SESSION_ARCHIVE` overrides it for anyone whose archive is
# somewhere else.
def _archive_default() -> pathlib.Path:
    here = pathlib.Path(__file__).resolve().parent
    common = subprocess.run(
        ["git", "-C", str(here), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return pathlib.Path(common).parent / ".driver-state" / "runs.jsonl"


ARCHIVE = pathlib.Path(os.environ["AGENT_SESSION_ARCHIVE"]) if os.environ.get(
    "AGENT_SESSION_ARCHIVE"
) else _archive_default()
XDG = pathlib.Path(os.environ.get("XDG_STATE_HOME") or (pathlib.Path.home() / ".local/state"))
ROOT = XDG / "agent-session"
APPLY = "--apply" in sys.argv


def slug(repo: str) -> str:
    return repo.replace("/", "-")


if not ARCHIVE.is_file():
    sys.exit(f"no archive at {ARCHIVE}")

rows, malformed, unattributed = {}, 0, 0
for line in ARCHIVE.read_text().splitlines():
    if not line.strip():
        continue
    try:
        row = json.loads(line)
    except json.JSONDecodeError:
        malformed += 1
        continue
    repo = row.get("repo")
    if not repo:
        # Named rather than dropped silently: a row with no repo cannot be
        # attributed, and pretending otherwise would put it in the wrong ledger.
        unattributed += 1
        continue
    rows.setdefault(repo, []).append(line)

total = sum(len(v) for v in rows.values())
print(f"archive: {ARCHIVE}")
print(f"  {total} attributable rows across {len(rows)} repo(s)")
if malformed:
    print(f"  {malformed} malformed line(s) -- left in the archive only")
if unattributed:
    print(f"  {unattributed} row(s) with no `repo` field -- left in the archive only, "
          f"they cannot be attributed")
print(f"destination root: {ROOT}")
print()

wrote = skipped = 0
for repo, lines in sorted(rows.items()):
    dest = ROOT / slug(repo) / "runs.jsonl"
    existing = 0
    if dest.is_file():
        existing = len([l for l in dest.read_text().splitlines() if l.strip()])
    label = f"{repo:34s} -> {dest}"
    if existing:
        print(f"  SKIP  {label}")
        print(f"        already holds {existing} row(s); not appending "
              f"({len(lines)} archive rows for this repo)")
        skipped += 1
        continue
    if APPLY:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("\n".join(lines) + "\n")
        print(f"  WROTE {label}")
        print(f"        {len(lines)} row(s)")
        wrote += 1
    else:
        print(f"  would write {label}")
        print(f"        {len(lines)} row(s)")

print()
if APPLY:
    print(f"applied: {wrote} ledger(s) written, {skipped} skipped. "
          f"{ARCHIVE.parent} was only read.")
    # Re-read what was written, so the count is observed rather than assumed.
    for repo in sorted(rows):
        dest = ROOT / slug(repo) / "runs.jsonl"
        if dest.is_file():
            n = len([l for l in dest.read_text().splitlines() if l.strip()])
            print(f"  verified {dest}: {n} row(s)")
else:
    print("dry run -- nothing written. Re-run with --apply.")
