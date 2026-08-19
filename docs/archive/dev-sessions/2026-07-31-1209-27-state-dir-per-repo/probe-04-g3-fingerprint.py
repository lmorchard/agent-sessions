#!/usr/bin/env python3
"""G3: the existing ./.driver-state/ archive must survive this change untouched.

Fingerprints every file under the MAIN checkout's .driver-state/, EXCLUDING the
live bookkeeping of the run supervising this session:

  - inflight.json          -- written before this run and removed after it records
  - runs/27-*              -- this run's own transcript directory
  - runs.jsonl rows for issue 27 -- appended when this run is classified

That bookkeeping is written by the driver, not by the change, and G3 is scoped to
"not modified or deleted by the change or by the migration". Everything else --
the ten prior run directories and every pre-existing ledger row -- must be
byte-identical before and after.

Run with `--write` at freeze to record the baseline, then bare to compare:

  python3 .../probe-04-g3-fingerprint.py --write
  python3 .../probe-04-g3-fingerprint.py
"""
import hashlib
import json
import os
import pathlib
import subprocess
import sys

SESSION = pathlib.Path(__file__).resolve().parent
BASELINE = SESSION / "g3-baseline.json"

# The MAIN checkout, not this worktree: .driver-state/ is gitignored and lives
# only there. Resolved from the worktree's git commondir, as the line below now
# actually does -- it previously hardcoded one machine's path while this comment
# claimed otherwise, and left WORKTREE computed but unused. Raised by the Copilot
# review on PR #44. `--git-common-dir` is the point: inside a linked worktree
# `--git-dir` gives the worktree's own gitdir, and only the common dir points at
# the main checkout's .git.
WORKTREE = SESSION.parents[2]
_common = subprocess.run(
    ["git", "-C", str(WORKTREE), "rev-parse", "--path-format=absolute", "--git-common-dir"],
    capture_output=True, text=True, check=True,
).stdout.strip()
MAIN = pathlib.Path(_common).parent
STATE = pathlib.Path(os.environ.get("AGENT_SESSION_ARCHIVE") or (MAIN / ".driver-state"))


def excluded(rel: pathlib.PurePath) -> bool:
    parts = rel.parts
    if parts[0] == "inflight.json":
        return True
    if len(parts) >= 2 and parts[0] == "runs" and parts[1].startswith("27-"):
        return True
    return False


def fingerprint() -> dict:
    out = {}
    for p in sorted(STATE.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(STATE)
        if excluded(rel):
            continue
        data = p.read_bytes()
        if rel.name == "runs.jsonl":
            # Drop rows for issue 27: the supervising driver appends one when it
            # classifies this very run. Every other row must be untouched.
            kept = []
            for line in data.decode().splitlines():
                if not line.strip():
                    continue
                try:
                    if json.loads(line).get("issue") == 27:
                        continue
                except json.JSONDecodeError:
                    pass
                kept.append(line)
            data = ("\n".join(kept) + "\n").encode()
            out[str(rel)] = {"sha256": hashlib.sha256(data).hexdigest(), "rows": len(kept)}
        else:
            out[str(rel)] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    return out


if not STATE.is_dir():
    sys.exit(f"G3 FAIL: {STATE} does not exist -- the archive is gone")

now = fingerprint()

if "--write" in sys.argv:
    BASELINE.write_text(json.dumps(now, indent=2, sort_keys=True) + "\n")
    print(f"baseline written: {BASELINE}")
    print(f"{len(now)} files fingerprinted under {STATE}")
    runs = sorted({p.split('/')[1] for p in now if p.startswith('runs/')})
    print(f"run directories covered ({len(runs)}): {', '.join(runs)}")
    ledger = now.get("runs.jsonl")
    if ledger:
        print(f"runs.jsonl: {ledger['rows']} pre-existing rows, sha256 {ledger['sha256'][:16]}…")
    sys.exit(0)

if not BASELINE.exists():
    sys.exit(f"G3 INDETERMINATE: no baseline at {BASELINE}; run with --write first")

base = json.loads(BASELINE.read_text())
missing = sorted(set(base) - set(now))
added = sorted(set(now) - set(base))
changed = sorted(k for k in set(base) & set(now) if base[k]["sha256"] != now[k]["sha256"])

for label, items in (("MISSING", missing), ("CHANGED", changed)):
    for k in items:
        print(f"  {label}: {k}")
for k in added:
    print(f"  added (not a G3 violation on its own): {k}")

if missing or changed:
    sys.exit(f"G3 FAIL: {len(missing)} missing, {len(changed)} changed")
print(f"G3 PASS: all {len(base)} fingerprinted files byte-identical under {STATE}")
