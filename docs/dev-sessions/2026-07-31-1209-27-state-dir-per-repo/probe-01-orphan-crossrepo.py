#!/usr/bin/env python3
"""plan step 4: re-confirm the spec's fact 1 still holds against current code.

A live in-flight marker naming repo A must not refuse a run against repo B. Runs
against a throwaway --state-dir, so it neither reads nor writes live state.

Run:  python3 docs/dev-sessions/2026-07-31-1209-27-state-dir-per-repo/probe-01-orphan-crossrepo.py
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[3]
DRIVER = REPO / "driver" / "agent-session-driver.sh"

with tempfile.TemporaryDirectory() as state:
    state = pathlib.Path(state)
    rundir = state / "runs" / "657-20260729T000000Z"
    rundir.mkdir(parents=True)

    # A genuinely live process, so the guard's `kill -0` succeeds. Its own child,
    # so nothing on the host is signalled.
    live = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
    try:
        (rundir / "child.pid").write_text(f"{live.pid}\n")
        (state / "inflight.json").write_text(
            json.dumps(
                {
                    "issue": 657,
                    "started": "20260729T000000Z",
                    "run_dir": str(rundir),
                    "url": "https://github.com/lmorchard/decafclaw/issues/657",
                }
            )
            + "\n"
        )
        print("marker repo A:", (state / "inflight.json").read_text().strip())
        print(f"live child pid: {live.pid}")
        print("--- invoking the driver for repo B = lmorchard/agent-sessions ---")
        p = subprocess.run(
            [
                "bash",
                str(DRIVER),
                "--repo",
                "lmorchard/agent-sessions",
                "--dry-run",
                "--state-dir",
                str(state),
            ],
            capture_output=True,
            text=True,
            cwd=REPO,
            env={**os.environ},
        )
        out = p.stdout + p.stderr
        print(out.strip()[:2000])
        print(f"--- exit {p.returncode} ---")
        refused = "refusing to start a second run" in out
        orphan = "ORPHAN STILL RUNNING" in out
        print(f"refused={refused}  reported_orphan={orphan}")
        print("VERDICT:", "GAP PRESENT (C1 would fail)" if (refused or orphan) else "no gap")
    finally:
        live.kill()
        live.wait()
