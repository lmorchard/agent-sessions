#!/usr/bin/env python3
"""The spec's fact 3, in BOTH spellings, for the same reason as probe-01.

`--classify-only <n>` resolves a run dir by issue number and mtime, so two repos'
runs on one issue number are indistinguishable when they share a directory.
Invokes the SHIPPED driver, not the lookup expression copied out of it -- the spec
flags the intake-time replica probe as not being evidence about the driver
(findings.md class 1 instance 9).

  form A -- one explicit shared --state-dir. Ambiguous before AND after: the flag
    means exactly the directory given, so pointing two repos at one `runs/`
    namespace reintroduces the collision by construction. That is the operator's
    choice, not the default, and it is named as a residual risk rather than fixed
    -- fixing it would mean `--state-dir X` no longer meaning X, which another
    issue's FROZEN check file depends on (driver/test-park-state.sh:275-282).

  form B -- no --state-dir. This is C3, and it is the real spelling of the
    documented recovery path: each repo resolves its own runs/, so the lookup has
    exactly one candidate.

A stubbed `gh` on PATH keeps both offline AND inert: the recovery path ends in
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

    REPOS = ("lmorchard/decafclaw", "lmorchard/agent-sessions")
    STREAM = ('{"type":"result","subtype":"success","is_error":false,'
              '"total_cost_usd":0.5,"session_id":"stub","result":"done"}\n')

    def seed(d: pathlib.Path) -> None:
        d.mkdir(parents=True, exist_ok=True)
        (d / "stream.jsonl").write_text(STREAM)

    def resolve(repo: str, extra, cwd, env) -> str:
        p = subprocess.run(
            ["bash", str(DRIVER), "--repo", repo, "--classify-only", "4", *extra],
            capture_output=True, text=True, cwd=cwd, env=env,
        )
        return next(
            (l.strip() for l in (p.stdout + p.stderr).splitlines()
             if l.strip().startswith("run dir")),
            "(no run dir line)",
        )

    base_env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}

    # --- form A: one explicit shared --state-dir --------------------------------
    shared = tmp / "shared"
    seed(shared / "runs" / "4-20260728T000000Z")   # pretend: decafclaw
    seed(shared / "runs" / "4-20260729T013605Z")   # pretend: agent-sessions

    print("=" * 72)
    print("form A: both repos pointed at ONE explicit --state-dir")
    print("=" * 72)
    a = {r: resolve(r, ["--state-dir", str(shared)], REPO, base_env) for r in REPOS}
    for r, line in a.items():
        print(f"--repo {r:30s} -> {line}")
    a_distinct = len(set(a.values())) == 2
    print("EXPECTED: ambiguous -- one runs/ namespace, resolved by mtime.")
    print("form A VERDICT:",
          "unexpectedly distinct" if a_distinct
          else "ambiguous, as designed (residual risk, named not fixed)")

    # --- form B: no --state-dir. This is C3. ------------------------------------
    xdg = tmp / "xdg"
    cwd = tmp / "cwd"
    cwd.mkdir()
    want = {
        "lmorchard/decafclaw":
            xdg / "agent-session" / "lmorchard-decafclaw" / "runs" / "4-20260730T101010Z",
        "lmorchard/agent-sessions":
            xdg / "agent-session" / "lmorchard-agent-sessions" / "runs" / "4-20260731T202020Z",
    }
    for d in want.values():
        seed(d)

    print()
    print("=" * 72)
    print("form B: NO --state-dir -- the documented recovery path's real spelling")
    print("=" * 72)
    env_b = {**base_env, "XDG_STATE_HOME": str(xdg)}
    b = {r: resolve(r, [], cwd, env_b) for r in REPOS}
    ok = True
    for r, line in b.items():
        mine = str(want[r]) in line
        theirs = any(str(p) in line for q, p in want.items() if q != r)
        print(f"--repo {r:30s} -> {line}")
        print(f"{'':38s}    resolves its own={mine}  the other's={theirs}")
        ok = ok and mine and not theirs
    print("EXPECTED after the change: each repo resolves its own run dir.")
    print("form B VERDICT:", "C3 SATISFIED" if ok else "GAP PRESENT (C3 fails)")
