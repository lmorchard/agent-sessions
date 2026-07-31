#!/usr/bin/env python3
"""The spec's fact 1, demonstrated in BOTH spellings of "repo A is live".

Written at plan step 4 to reproduce the issue's fact 1 exactly as the issue
reproduced it -- "in isolation against a throwaway --state-dir" -- where it did
fail before the change. Extended after the change, because that one scenario is
NOT the one the fix alters, and reading it as C1 would be reading it wrong:

  form A -- both runs pointed at ONE EXPLICIT --state-dir.
    Still refuses, by design, before and after. `--state-dir X` means exactly X,
    so this is two runs sharing one inflight.json, which the spec rejects in as
    many words: "keeping one shared directory with a repo-aware guard ... cannot
    work, because a single inflight.json cannot represent two concurrent runs."
    The issue used an explicit --state-dir purely to stay off live state, not to
    claim that a deliberately shared directory should stop colliding.

  form B -- NO --state-dir, i.e. what real invocations do (neither `make run` nor
    `make run-self` passes one). This is the criterion. Before the change both
    repos resolved to the same cwd-relative ./.driver-state and it refused;
    after, each resolves to its own XDG per-repo directory and it does not.

Form B is what C1 freezes. Form A is retained here as the negative control: if it
ever stopped refusing, the fix would have bought C1 by making the orphan guard
permissive, which the issue's "What we're NOT doing" forbids.

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

def plant(state: pathlib.Path, live_pid: int) -> None:
    """A live in-flight run for repo A, laid out as run_issue() writes one."""
    rundir = state / "runs" / "657-20260729T000000Z"
    rundir.mkdir(parents=True, exist_ok=True)
    (rundir / "child.pid").write_text(f"{live_pid}\n")
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


def run(args, cwd, env) -> str:
    p = subprocess.run(["bash", str(DRIVER), *args],
                       capture_output=True, text=True, cwd=cwd, env=env)
    out = p.stdout + p.stderr
    print(out.strip()[:1400])
    print(f"--- exit {p.returncode} ---")
    return out


def verdict(out: str) -> tuple:
    refused = "refusing to start a second run" in out
    orphan = "ORPHAN STILL RUNNING" in out
    print(f"refused={refused}  reported_orphan={orphan}")
    return refused, orphan


with tempfile.TemporaryDirectory() as tmp:
    tmp = pathlib.Path(tmp)

    # A genuinely live process, so the guard's `kill -0` succeeds. Its own child,
    # so nothing on the host is signalled.
    live = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
    try:
        # --- form A: one explicit --state-dir, shared. Must still refuse. -------
        shared = tmp / "shared"
        shared.mkdir()
        plant(shared, live.pid)
        print("=" * 72)
        print("form A: repo A live in an EXPLICIT --state-dir, repo B given the same one")
        print("=" * 72)
        a_refused, a_orphan = verdict(
            run(["--repo", "lmorchard/agent-sessions", "--dry-run",
                 "--state-dir", str(shared)],
                cwd=REPO, env={**os.environ})
        )
        print("EXPECTED: refuses -- two runs cannot share one inflight.json.")
        print("form A VERDICT:",
              "correct (negative control holds)" if (a_refused and a_orphan)
              else "REGRESSION -- the orphan guard went permissive")

        # --- form B: no --state-dir. This is C1. --------------------------------
        xdg = tmp / "xdg"
        cwd = tmp / "cwd"
        cwd.mkdir()
        # Repo A's marker in both places repo A's own driver could have written it:
        # the pre-change cwd-relative default, and the per-repo XDG path.
        plant(cwd / ".driver-state", live.pid)
        plant(xdg / "agent-session" / "lmorchard-decafclaw", live.pid)
        print()
        print("=" * 72)
        print("form B: repo A live, NO --state-dir -- what a real invocation does")
        print("=" * 72)
        b_refused, b_orphan = verdict(
            run(["--repo", "lmorchard/agent-sessions", "--dry-run"],
                cwd=cwd, env={**os.environ, "XDG_STATE_HOME": str(xdg)})
        )
        print("EXPECTED after the change: neither refuses nor reports an orphan.")
        print("form B VERDICT:",
              "C1 SATISFIED" if not (b_refused or b_orphan)
              else "GAP PRESENT (C1 fails)")
    finally:
        live.kill()
        live.wait()
