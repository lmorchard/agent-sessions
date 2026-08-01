# Session notes — #50, gate-test globs

Unattended `express` run, driven by the board-driver. Tier `auto-ok`, so the run went straight
through plan → freeze → execute → verify → PR and stopped at the merge gate.

## What this is

`make gate-test` named its five test files one path at a time. `scripts/test_assertion_lint.py` was
written, passed, and was never added to the list, so the detector for defect class 5 had tests that
had never run and `make check` was green either way. Replaced the list with globs over
`driver/test_*.py` and `scripts/test_*.py`.

## This is the second run on this issue

PR #56 was the first. It was killed externally at ~33 minutes, after pushing and opening the PR but
before it could settle `ci`, `threads` and `verdict`; Les closed it unmerged with the note that it
was *"superseded by a fresh run of #50"* and that **the replacement should be expected to rediscover
Copilot's three threads**. That instruction shaped this run's freeze, so it is worth recording what
came of it.

All three were real, and all three are handled in `scripts/test_gate_test_wiring.py` **before** the
first implementation line was written — they went into `checks.md`'s hazard list and into the
check-author's brief, rather than being found by a second review:

| Copilot's finding on #56 | How this run's frozen check handles it |
|---|---|
| `bash -c` returns only the *last* command's status, so an early failure in a multi-line recipe is masked | the extracted recipe runs under `bash -e -o pipefail` |
| a fixed probe filename lets two concurrent runs in one tree race, each deleting the other's probe | the probe name embeds `os.getpid()` plus 4 random bytes |
| overwriting `PYTEST_ADDOPTS` breaks the check for anyone who already has it set | it is appended to, never replaced |

Copilot's first point was the load-bearing one: it *"suggests the frozen check may not
discriminate."* On #56 that could not be fixed in place, because the file it named **was** that run's
frozen oracle — amendment-policy work, which is why Les routed it to a fresh run instead of patching
a dead branch. Here the same content is frozen correctly the first time, at a new freeze, so no
amendment was needed and the tier never moved.

## Decisions this run made that the spec left open

The spec settled *"globs, not an appended filename"* and stopped there. The glob **mechanism** was
open, and three were available:

- **Shell globs — chosen.** An unmatched shell glob is passed through literally and pytest errors
  on it.
- **`$(wildcard …)` — rejected.** Matching nothing expands to *nothing*, leaving a bare `pytest`
  that silently falls back to `pyproject.toml`'s `testpaths` — a different set of tests. Loud beats
  silent for a recipe whose whole job is "don't quietly run less than you should".
- **Bare `pytest` on `testpaths` — rejected, and it was the close call.** It has no census at all,
  and it would have made C1 compare two genuinely independent mechanisms instead of two spellings of
  one. Against it: it moves the test wiring into `pyproject.toml`, which is **not** on CLAUDE.md's
  drivable allowlist and is the dependency file besides, and it hides the recipe's behaviour from
  where a reader looks for it. The independent verifier noted unprompted that this alternative would
  also pass both checks — correctly, since the checks grade the outcome rather than the mechanism.

## The honest weakness, stated rather than left to be found

**C1 is near-tautological against the implementation chosen.** The recipe now literally *is* the two
globs, and C1's other side expands the same two patterns, so it compares a set against itself. Both
the verifier here and the reviewer on #56 said so independently.

It is not vacuous — the recipe side is read out of the `Makefile` with `make -n` and executed
verbatim rather than restated, so C1 fires if anyone later re-pins a list, adds an `--ignore`, or
changes `python_files`. But its discriminating power against *this particular diff* is low, and that
is by design: the spec says in so many words that C1 alone is satisfiable by appending one filename,
which is exactly why C2 exists. **C2 is where the teeth are.**

## A defect found in this run's own manifest, deliberately not fixed in it

The verifier found that G1's command as transcribed here carries a `-q` that `pyproject.toml`'s
`addopts` already supplies, making it `-qq` — which suppresses the summary line, so **the command as
frozen cannot print the counts the guard is phrased to ask for.** The issue's own G1 has no `-q`;
this manifest added it.

It changes no verdict at either tree, so by `frozen-checks.md`'s four-cell test it is at most a
clarification and costs the tier nothing. It was still not edited: a guard command in an append-only
manifest is not rewritten mid-run whether the rewrite would improve it or weaken it, and the run that
would benefit from the edit is the run doing the editing. Recorded here for the next manifest.

## Follow-ups, not done here (scope discipline)

- **`docs/findings.md` gets no entry from this run.** The defect is a real instance of the
  "hand-maintained census" shape that the assertion counts already illustrate, and it might deserve a
  line in the evidence ledger — but the spec's scope is the wiring fix, nothing mechanical requires
  it, and `make check` is green without it. Worth a human's call, not an unattended one.
- **The stray-probe hazard is accepted, not closed.** C2 writes a failing test file into the real
  `scripts/`; teardown is a `finally`, which survives assertion failure, exception and
  `KeyboardInterrupt` but not `SIGKILL` — and this issue's *previous* run was killed externally, so
  that is not hypothetical. The frozen CHECK wording requires a *failing* probe, so the safer
  passing-probe variant would need an amendment. A survivor is named
  `test_zz_gate_wiring_probe_<pid>_<hex>.py` and is greppable.
- **`make check` is slower.** `gate-test` runs nine more tests, and C2 spawns two full `make
  gate-test` subprocesses, each of which also runs C1's two collection subprocesses. Bounded at
  depth 2 — collection imports modules without executing test bodies.

## Board

`In review` → `In progress` at setup. It was already sitting at `In review`, left there by PR #56;
the stale `driver-parked` label from before the issue was triaged is also still on it. Neither was
this run's to clean up beyond the sanctioned setup transition.
