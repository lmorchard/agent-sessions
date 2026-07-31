#!/usr/bin/env python3
"""plan step 4: re-confirm the spec's fact 3 still holds against current code.

`--classify-only <n>` resolves a run dir by issue number alone, so two repos'
runs on the same issue number are indistinguishable. Invokes the SHIPPED driver,
not the lookup expression copied out of it -- the spec explicitly flags that the
replica probe done at intake is not evidence about the driver.

A stubbed `gh` on PATH keeps this offline AND inert: the recovery path ends in
`apply_park_state`, which would otherwise add a real `driver-parked` label to a
real issue.

Run:  python3 docs/dev-sessions/2026-07-31-1209-27-state-dir-per-repo/probe-02-classify-only-ambiguous.py
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
  "pr list"*) printf '%s' '[]' ;;
  *)          exit 0 ;;
esac
"""

with tempfile.TemporaryDirectory() as tmp:
    tmp = pathlib.Path(tmp)
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(GH_STUB)
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    state = tmp / "state"
    # Two runs on issue #4, from two different repos, under one state dir --
    # exactly the shape today's layout produces.
    older = state / "runs" / "4-20260728T000000Z"   # pretend: decafclaw
    newer = state / "runs" / "4-20260729T013605Z"   # pretend: agent-sessions
    for d in (older, newer):
        d.mkdir(parents=True)
        (d / "stream.jsonl").write_text(
            '{"type":"result","subtype":"success","is_error":false,'
            '"total_cost_usd":0.5,"session_id":"stub","result":"done"}\n'
        )

    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    resolved = {}
    for repo in ("lmorchard/decafclaw", "lmorchard/agent-sessions"):
        p = subprocess.run(
            ["bash", str(DRIVER), "--repo", repo, "--classify-only", "4",
             "--state-dir", str(state)],
            capture_output=True, text=True, cwd=REPO, env=env,
        )
        line = next(
            (l.strip() for l in (p.stdout + p.stderr).splitlines()
             if l.strip().startswith("run dir")),
            "(no run dir line)",
        )
        resolved[repo] = line
        print(f"--repo {repo:30s} -> {line}")

    distinct = len(set(resolved.values())) == 2
    print()
    print(f"resolved distinct run dirs per repo: {distinct}")
    print("VERDICT:", "no gap" if distinct
          else "GAP PRESENT (C3 would fail) -- both repos resolve the same dir, "
               "and nothing in the path names a repo")
