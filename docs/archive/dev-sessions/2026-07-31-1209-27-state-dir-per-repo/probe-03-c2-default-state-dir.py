#!/usr/bin/env python3
"""C2's freeze-time probe -- the one the issue filed UNRUN.

The spec's stated reason for leaving it unrun: "a probe that omits --state-dir
today defaults to ./.driver-state, which is the live directory -- it would read
the live marker and die at the orphan guard, so the assertion would fail for a
compounded reason rather than the one it names."

The condition it asks for ("once no run is in flight") is obtained here by CWD
rather than by waiting: the driver's default is `./.driver-state`, relative to
cwd, so running from a fresh temp dir gives an empty state dir with no marker.
Nothing is read from or written to either the main checkout's live
`./.driver-state` or the worktree's.

A stubbed `gh` keeps it offline. XDG_STATE_HOME points at a temp dir, so the
assertion is about where the driver resolves state to, not about the host.

Run:  python3 docs/dev-sessions/2026-07-31-1209-27-state-dir-per-repo/probe-03-c2-default-state-dir.py
"""
import os
import pathlib
import stat
import subprocess
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[3]
DRIVER = REPO / "driver" / "agent-session-driver.sh"

GH_STUB = """#!/usr/bin/env bash
case "$*" in
  "issue list"*) printf '%s' '[]' ;;
  "pr list"*)    printf '%s' '[]' ;;
  *)             exit 0 ;;
esac
"""

with tempfile.TemporaryDirectory() as tmp:
    tmp = pathlib.Path(tmp)
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(GH_STUB)
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    xdg = tmp / "xdg"
    xdg.mkdir()
    cwd = tmp / "cwd"
    cwd.mkdir()

    env = {**os.environ,
           "PATH": f"{bin_dir}:{os.environ['PATH']}",
           "XDG_STATE_HOME": str(xdg)}

    # No --state-dir, deliberately: that is the whole criterion.
    p = subprocess.run(
        ["bash", str(DRIVER), "--repo", "lmorchard/agent-sessions", "--dry-run"],
        capture_output=True, text=True, cwd=cwd, env=env,
    )
    out = p.stdout + p.stderr
    print(out.strip()[:1200])
    print(f"--- exit {p.returncode} ---")
    print()

    want = xdg / "agent-session" / "lmorchard-agent-sessions"
    exists = want.is_dir()
    reported = str(want) in out
    legacy = (cwd / ".driver-state").is_dir()

    print(f"XDG per-repo dir exists ({want}): {exists}")
    print(f"resolved path appears in output:  {reported}")
    print(f"(for contrast) ./.driver-state created in cwd: {legacy}")
    print("VERDICT:", "C2 SATISFIED" if (exists and reported)
          else "C2 FAILS -- for the reason it names, not a compounded one "
               "(no orphan guard was reachable: the state dir started empty)")
