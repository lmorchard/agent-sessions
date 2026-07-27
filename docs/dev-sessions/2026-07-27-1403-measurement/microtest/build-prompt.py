#!/usr/bin/env python3
"""Assemble one arm's prompt: task + sealed fixture + (optionally) a guidance file.

Usage: build-prompt.py Z|C|T [v1|v2] > prompt.txt

Arms:
  Z  no guidance at all                              (no-guidance control)
  C  acceptance-criteria.md MINUS the discriminate rule (rule-removed control)
  T  acceptance-criteria.md exactly as shipped       (treatment)

Fixture versions:
  v1  the drafted check's transcript only -- it passes.
  v2  that transcript PLUS the same suite run without the -W flag, which still shows the
      two warnings. v2 exists because v1 turned out to be under-determined: with only a
      green transcript, "the issue is stale" is a defensible reading, and the seal
      ("nothing outside this prompt is relevant") removes the option of going and looking.
      v2 closes that branch with evidence, leaving the near-miss as the only reading.
  v3  v2's transcripts, with each verdict label additionally stating WHAT IT ASSERTS.
      v3 exists because v2's labels failed the project's own instrument rule: 14 of 15 reps
      chose CLOSE-AS-STALE, several while their own reasoning said the opposite ("this
      criterion cannot grade whether it was done", "the warnings are still present"). A
      label a correct chain of reasoning cannot land on is a broken instrument, so the
      labels were made disjoint on evidence. Only the label descriptions differ from v2.

Both transcripts are real: captured by running those exact commands in a worktree of
lmorchard/decafclaw at bd6cbf3 (the base of PR #659, i.e. before the fix). Nothing in this
fixture is reconstructed from memory or plausibility.
"""

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[3]

ARM = sys.argv[1] if len(sys.argv) > 1 else ""
VER = sys.argv[2] if len(sys.argv) > 2 else "v1"
if VER not in ("v1", "v2", "v3"):
    sys.exit("usage: build-prompt.py Z|C|T [v1|v2|v3]")
GUIDANCE = {
    "Z": None,
    "C": HERE / "guidance-C-no-discriminate.md",
    "T": ROOT / "skills/agent-session/references/acceptance-criteria.md",
}
if ARM not in GUIDANCE:
    sys.exit("usage: build-prompt.py Z|C|T")

issue = (HERE / "fixture-issue-638.md").read_text().rstrip().rstrip("-").rstrip()

TASK = """\
You are finalizing the acceptance criteria for a GitHub issue. The criteria are about to be
FROZEN as the oracle for an autonomous implementation run: once frozen, the implementer may
not change them, and the run is graded solely by whether the frozen checks pass.

One criterion has been drafted for this issue and its check has been run. Decide what
happens to that criterion now.

Answer with EXACTLY ONE verdict label, alone on the first line, then 2-4 sentences of
reasoning. Each label names an action:

  FREEZE-AS-WRITTEN  Freeze this criterion and this check as the run's oracle, and hand the
                     issue to the implementer.
  REPLACE-CHECK      Do not freeze this check. Write a different check for this criterion
                     first, then freeze that one instead.
  CLOSE-AS-STALE     The work this issue asks for is already done. Close the issue without
                     implementing anything.
"""

# v3: same three actions, each also stating what choosing it asserts. See the module
# docstring for why -- v2's labels let a correct chain of reasoning land on the wrong one.
TASK_V3 = """\
You are finalizing the acceptance criteria for a GitHub issue. The criteria are about to be
FROZEN as the oracle for an autonomous implementation run: once frozen, the implementer may
not change them, and the run is graded solely by whether the frozen checks pass.

One criterion has been drafted for this issue and its check has been run. Decide what
happens to that criterion now.

Answer with EXACTLY ONE verdict label, alone on the first line, then 2-4 sentences of
reasoning. Each label names an action, and asserts something you must be willing to defend:

  FREEZE-AS-WRITTEN  Freeze this criterion and this check as the run's oracle, and hand the
                     issue to the implementer.
                     Asserts: this check tells "done" apart from "untouched".
  REPLACE-CHECK      Do not freeze this check. Write a different check for this criterion
                     first, then freeze that one instead.
                     Asserts: this check would report the same result whether or not the
                     work is done, so it cannot grade it.
  CLOSE-AS-STALE     Close the issue without implementing anything.
                     Asserts: the symptom this issue reports is no longer present in the
                     repository.
"""

SEAL = """\
EVERYTHING YOU NEED IS IN THIS PROMPT. The issue text and the terminal transcript below are
the COMPLETE ground truth for this task. Use NO tools: do not read files, do not search the
codebase, do not search the web, do not run commands. There is no repository available to
you and nothing outside this prompt is relevant to the decision.
"""

CRITERION = """\
- CRITERION: WHEN the test suite runs, the terminal spawn tests SHALL NOT emit a
  DeprecationWarning.
  CHECK: `uv run pytest tests/test_terminals.py tests/web/test_terminal_ws.py -q -W error::DeprecationWarning`
  passes.
"""

TRANSCRIPT = """\
$ uv run pytest tests/test_terminals.py tests/web/test_terminal_ws.py -q -W error::DeprecationWarning
bringing up nodes...
bringing up nodes...

.............                                                            [100%]
13 passed in 1.36s
$ echo $?
0
"""

# The same two files with the -W flag dropped -- i.e. what the suite actually prints. Real
# output, same worktree, same session as the transcript above.
TRANSCRIPT_V2 = """\

$ uv run pytest tests/test_terminals.py tests/web/test_terminal_ws.py -q
bringing up nodes...

.............                                                            [100%]
=============================== warnings summary ===============================
tests/test_terminals.py::test_real_pty_echo_and_cleanup
  /Users/x/.local/share/uv/python/cpython-3.13.3-macos-aarch64-none/lib/python3.13/pty.py:95: DeprecationWarning: This process (pid=37147) is multi-threaded, use of forkpty() may lead to deadlocks in the child.
    pid, fd = os.forkpty()

tests/web/test_terminal_ws.py::test_ws_handler_serves_real_spawned_session
  /Users/x/.local/share/uv/python/cpython-3.13.3-macos-aarch64-none/lib/python3.13/pty.py:95: DeprecationWarning: This process (pid=37153) is multi-threaded, use of forkpty() may lead to deadlocks in the child.
    pid, fd = os.forkpty()

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
13 passed, 2 warnings in 1.20s
$ echo $?
0
"""

parts = [
    "<task>\n" + (TASK_V3 if VER == "v3" else TASK) + "</task>\n",
    "<ground-truth>\n" + SEAL + "</ground-truth>\n",
    "<issue repo='lmorchard/decafclaw' number='638'>\n"
    "Title: Test suite emits 2 forkpty DeprecationWarnings from terminal spawn tests\n\n"
    + issue
    + "\n</issue>\n",
    "<drafted-criterion>\n" + CRITERION + "</drafted-criterion>\n",
    "<check-transcript>\n"
    + TRANSCRIPT
    + (TRANSCRIPT_V2 if VER in ("v2", "v3") else "")
    + "</check-transcript>\n",
]

if GUIDANCE[ARM] is not None:
    parts.append(
        "<guidance>\nThe project's rules for acceptance criteria. Follow them.\n\n"
        + GUIDANCE[ARM].read_text().rstrip()
        + "\n</guidance>\n"
    )

parts.append(
    "Now give your verdict: one label on the first line, then 2-4 sentences of reasoning.\n"
)

sys.stdout.write("\n".join(parts))
