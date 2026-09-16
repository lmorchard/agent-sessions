# Handoff: the #261 full-repo maintainability and documentation audit

> **STATUS: #261 is CLOSED (2026-08-24) and its stack landed as PRs #262-#268 and #270, all
> merged. Do not redo any of it.** This brief is kept as the *input* to that stack, in the
> pairing this archive's [README](README.md) describes -- not as a description of the repository.
>
> - **The "Start here" contradiction is resolved.** `CLAUDE.md` now names
>   `src/agent_sessions/driver/lifecycle.py` explicitly in the risk partition, and
>   `docs_check.is_shim` was fixed in the same change. The decision this brief correctly declined
>   to make itself was made by a human.
> - **The two branches it calls "unpushed" are merged** -- `chore/docs-archive-and-build-paths`
>   became PR #262 and `fix/261-hook-and-permission-floor` became PR #263.
> - **H9's worktree half is done** (#272, PR #276), including both of its must-not-remove
>   exceptions -- which `make prune-worktrees` rediscovered mechanically, from dirtiness alone.
>   That target is the repeatable path H9 asked for, and it uses the PR-state oracle this brief
>   was right to insist on.
> - **S4 / #249 is still open.** The permanently-skipping assertion-count probe it predicted is
>   still what `docs-check` discloses on every run; PR #274 is the fix.
> - **The gotchas are the part still worth reading**, and the maintained copies live in
>   [../findings.md](../findings.md) under Verified gotchas. Where the two disagree, that file
>   wins.
> - Every count, path, queue snapshot and "still unexercised" note below is **as of 2026-08-19**
>   and has not been re-verified since. Read it for what was decided and why, never for where the
>   code is.

Execute on issue #261 in the `agent-sessions` repo (`/Users/lorchard/devel/agent-sessions`).

#261 is a full-repo maintainability and documentation audit. Its body plus **three follow-up
comments** carry the findings, and a fourth comment records what has already landed. Read all of
them: `gh issue view 261 --repo lmorchard/agent-sessions --comments`.

Read these first, in this order, before touching anything: `CLAUDE.md` (conventions and the
risk partition — load-bearing, not advisory), `docs/findings.md` (recurring defect classes and the
verified command gotchas; several gotchas are the opposite of what the flag names suggest), then
`docs/design.md`. Then skim `Makefile` — its comments encode why each instrument exists and some are
the only record of a decision.

## Ground rules

**Work in a git worktree, never the main clone.** Other agents use that checkout and it may be on
someone else's branch mid-task. `git worktree add .worktrees/<name> -b <branch> main`. Do not
`git switch` in the main clone. Do not touch a file you did not intend to — check `git status` in the
main clone before you start and leave anything you find there alone.

**`make check` must pass before every commit.** It is the aggregate: `driver-check`, `gate-test`,
`skill-readonly`, `docs-check`, `assertion-lint`, `commit-lint`, `lint`, `typecheck`. It prints
`all checks passed` only on success, and that banner cannot lie — the recipe line after the
sub-make does not run on failure.

**Most of this work is risk-gated.** `CLAUDE.md`'s allowlist is an allowlist, not a denylist: a path
it does not name is `needs-review`. Drivable: `tests/**`, `docs/`, `Makefile`, `scripts/**`. Gated:
every unlisted `src/**` path, `skills/**` (hard — the implementer's work product would be the
instructions grading it), `.github/**`, `src/agent_sessions/driver/gate.py` (the oracle),
`src/agent_sessions/driver/agent_session_driver.py`. You may still do gated work — a human is at the
merge gate — but say so in the PR and do not batch gated changes with drivable ones.

**Do not weaken a test to make something pass.** Do not add a check you have not seen fail. Several
findings in #261 are precisely "someone wrote a guard and never proved it could fail".

## What has already landed — do not redo it

Two branches exist locally, **unpushed**, both green, and they merge cleanly with each other
(verified with `git merge-tree`; the only shared file is `docs/design.md`, in different regions).
Base new work on `main`, or stack on these if you need what they contain.

`chore/docs-archive-and-build-paths` (3 commits)
- The GitHub App private key: `*.private-key.pem` ignore rule committed (it had existed only as an
  unstaged edit), key moved to `~/.config/agent-session/`, `.env` repointed. Never committed —
  verified across every reachable git object.
- 26 pre-2026-08-09 dev-sessions moved to `docs/archive/dev-sessions/` via the new
  `scripts/archive-dev-session.py`. Tracked files under `docs/dev-sessions/` went 326 → 21.
- `pyproject.toml`: `testpaths = ["tests"]` (a bare `pytest` used to collect nothing and exit 0),
  `pythonpath = ["src"]` added, dead ruff per-file-ignores removed, ruff `exclude` extended to
  `docs/archive`.

`fix/261-hook-and-permission-floor` (7 commits) — closes S1, S2, C1, C2, C3, C4, C9, D1, D2,
G1-partial, T1-partial. Highlights:
- The PreToolUse merge-block hook is installed again and fails closed. Assets moved into
  `src/agent_sessions/driver/`; `driver/` now holds only the compatibility launcher.
- `tests/conftest.py` now pins `XDG_STATE_HOME`, so the suites no longer write into `$HOME`. A full
  `make check` adds zero run dirs (it used to accumulate; the directory had 897).
- `make evidence` reads the live per-repo ledgers instead of the pre-#27 archive.
- All six `label_manager` remove-lists narrowed through `removable()`.
- New `src/agent_sessions/driver/output.py` owns `say`/`log`/`die` and `now()`, the driver's clock.

## Start here — I created this contradiction and did not resolve it

`CLAUDE.md:76` and `AGENTS.md:76` gate `src/agent_sessions/driver/agent_session_driver.py` as
*"the current home of the outcome **routing**"*. That has been false since #256 moved the routing to
`lifecycle.classify_and_record`, and the `a278ede` commit on the fix branch sharpened it: that file's
docstring now opens *"Defines nothing itself."* So the gate's stated reason is attached to a facade.

The allowlist still **holds** — unlisted `lifecycle.py` defaults to `needs-review`, so nothing is
exposed — but the reason is wrong, and `docs_check.check_partition`'s `is_shim` guard exists
specifically to catch a partition naming a re-export facade and **misses this instance** (the file has
no `"Shim re-exporting"` marker and is over the 30-line threshold).

Two things, and the second is a decision for Les, not for you:
1. Fix `is_shim` so it catches this shape, with a controlled-divergence test proving the guard's
   polarity. `docs_check.py` is gated.
2. Ask Les whether `lifecycle.py` should be named explicitly in the partition. Do not decide it.

Both governance files must stay byte-identical — `docs_check.check_risk_policy_parity` enforces the
risk section, and they are currently identical throughout. Edit both.

## Then, roughly in this order

**Correctness, gated `src/**`:**
- **C5.** `gate.extract_gate` and `gate.budget_reclass` are tested but unreachable from a run.
  `lifecycle.py` feeds `gate.classify` a whole PR body instead of the extracted block, and
  reimplements the 95% budget rule inline. So the tested path and the run path differ **at the
  oracle**. Fix both call sites with a fixture proving before/after on a real PR body. Note the
  budget change *moves* a threshold into gated `gate.py` — a tightening, say so.
- **C7.** `guard_lint.py`, `session_artifact_stats.py`, `run_swarm.py` compute the repo root as
  `.parent.parent`, which resolves to `src/agent_sessions`. Correct is `parents[3]`.
  `session_artifact_stats` and `run_swarm` are both broken if reached and unreachable through any
  entry point (`run_swarm` also looks for `driver/agent_runner.py`, deleted by the conversion).
  **Deleting them is probably smaller than fixing them** — but `skills/agent-session/phases/execute.md`
  references `run_swarm`, and that is a gated skill edit. Put the delete-or-fix call to Les.
- **C10.** `Makefile`'s `guard-lint` pipes `gh issue list` with no `--limit`, so it scans the newest
  30 and prints "no pinned test count guards found" — a null rendering as a positive.
  `board_audit.bounded_records` is the pattern to copy: explicit limit, and raise at the limit.
- **C11.** `tests/scripts/test_docs_check.py` hand-clones `check_world_state_claims` and asserts
  against the copy; the shipped function is never called and the copy has already drifted (the
  shipped regex is `\b(one|two|…|\d+) repositories\b`, the copy `\b([a-z]+) repositories\b`). Delete
  the clone, drive the real function against `tmp_path` fixtures — the `policy_root` fixture already
  monkeypatches `docs_check.ROOT`. **Expect it to fail first; that is the finding.**
- **S4.** `docs_check.py`'s assertion-count probe passes `scripts/test_*.py`, a path with no Python.
  This is a *second* cause on top of tracked issue #249 (unexpanded globs). Fixing only #249's half
  leaves pytest exiting 4 and the check permanently skipping. Add this to #249 rather than filing new.

**Tests, drivable:**
- **X4.** `--classify-only` has zero coverage — the recovery path an operator reaches for *after* a
  run dies. And `locks.py`'s stale-lock steal and TTL split (600s for triage/groom/refine, 7200s
  otherwise) are untested, including a `--force-with-lease` that loses the race. This is the
  distributed mutual-exclusion primitive: get it wrong and two drivers run the same issue and spend
  budget twice. `FakeGitHub.held_locks` already takes a timestamp.
- **X2.** `tests/driver/test_workspace_driver_integration.py` and `tests/driver/test_driver.py` use a
  catch-all `MockResult` (`stdout = "{}"`, `returncode = 0`) that answers every unmodelled `gh` call
  with success. `test_full_loop.py`'s docstring names this exact anti-pattern as why `FakeGitHub`
  exists. Move `FakeGitHub`/`StubAgent`/`LoopHarness` into `tests/driver/conftest.py` and rewrite the
  six sites against it. Expect failures once unmodelled calls stop being free.
- **X3.** 21 tracked test files still hand-roll `sys.path.insert(...)`. Branch A's
  `pythonpath = ["src"]` makes them all deletable.
- **X5.** No `git init` fixture isolates git config (no `GIT_CONFIG_GLOBAL=/dev/null`, no
  `commit.gpgsign=false`), so a machine with global signing breaks eight tests in a way that reads as
  a code failure. `test_discussion_manager.py` builds expected titles from the real wall clock and
  fails across a UTC midnight. `xdist_group` in `test_gate_test_wiring.py` is inert — it needs
  `--dist loadgroup`, and `gate-test` runs `-n auto` with no `--dist`.
  **Do not weaken `test_new_test_file_runs_under_gate_test_with_no_makefile_edit`** — it is 85% of the
  suite's wall clock because it invokes `make gate-test` twice for real, and it is the only thing
  standing between you and a test file that silently never runs.

**Structure, gated:**
- **T3** is the highest-value cluster. `gate.py:252-303` and `:306-403` encode the same seven row
  predicates twice, differing only in what they emit — change one and the verdict disagrees with its
  own provenance record, on the oracle. `router.py` re-derives filtering `lifecycle.select_queue`
  just did, and reimplements `parking.is_specced` with inlined literals while shadowing
  `PARK_LABEL`/`MERGE_READY_LABEL`; label constants are triplicated, so a rename needs four edits and
  **fails open**. `parking.py` has six copies of the same seven-line `label_manager` subprocess block
  (four discarding the failure) when `label_manager.main(argv) -> int` is importable.
- **T2.** Two named extractions from `invoke_agent` (286 lines): the three GitHub reads at
  `:700-813` → `gather_extra_context`, and the `request_review` branch at `:849-899` →
  `run_request_review`. That is ~170 of the 286 lines. Do not go further; #246's four-function shape
  is sound.
- **T4.** Dead code: `SelectionResult.board_items`/`.open_issues`, `InvocationResult.writes_file`/
  `.run_repo_path`, `parking.clear_attempt_labels`, `router.p4_escalate` (declared, never appended
  to, and `design.md` documents it as a real priority), `agent_runner`'s `ImportError` fallback and
  unused `_main(argv)`, `discussion_manager`'s unused `emoji`.

**Docs, drivable:**
- **D5, `findings.md`** — the biggest remaining doc job. Five dead paths, two of which are runnable
  commands that fail (`python3 scripts/commit_lint.py --all`, `python3 scripts/session_artifact_stats.py`).
  Six references to `phases/pr.md` **with step numbers**; the file split into `open_pr.md` +
  `grade_gate.md` and the steps were renumbered, so these cannot be fixed by find-and-replace — each
  needs re-locating by hand. The counts at the front misbehave in exactly the way the file itself
  warns about: "Seven patterns" over eight sections, "nine of the eleven… two are open" over a
  twelve-row table, and both "open" items (#2, #79) are **closed**, which makes the bolded "the sweep
  that has never been done" false. Per `CLAUDE.md`, prefer deleting a count and citing the command
  over updating the number. ~250 lines are now purely historical and belong in `docs/archive/`.
- **D6.** `docs/sweep-adjacent-evidence.md` reports `adjacent-risk: none` for all 26 rows including
  `threads`, which `findings.md` documents at length as the canonical adjacency instance. Archive it
  (do not delete — that the sweep ran and found nothing is the useful finding).
- **D3/D4.** `orientation.md`'s file tables are partly fixed; `README.md` is untouched — `:49`
  inverts the documented gate ownership and misplaces the harness, `:57` says "Six modes" when
  `SKILL.md` lists ten and twelve phase files exist, `:156` documents an uninstalled slash command.
- **D2.** `design.md`'s roadmap table is deleted, but ~180 lines of superseded roadmap/status/
  inventory still want moving to `docs/archive/` — two sections say "superseded" in their own titles.
- **D7.** `docs/agent-ledger.md` is still the placeholder while `grade_gate.md:110` writes it on
  every `eligible-for-auto-merge` verdict and the ledger shows eleven such verdicts. **This is a
  harness defect, not a doc defect** — `grade_gate` has no commit, no push and no `push` manifest
  entry, so the append dies in the worktree. Keep the file (`intake.md:9` reads it) and fix the
  mechanism.
- **D8.** `prior-art.md`: two one-line fixes. `:198` says the driver lacks a revision-first queue
  policy that `router.py`'s P1 Unblock ladder implements; `:225`'s "eight PRs deep with nothing
  merged" reads as current when it is 138 merged as of 2026-08-19 — date it rather than update it.
- **G2.** `CLAUDE.md:111,113` still place the detector tests at `scripts/` root level. #257/#258 moved
  them to `tests/scripts/`. The *Drivable* bullet was updated and the prose two paragraphs above was
  not — the exact "ask what it just invalidated" shape. Edit both governance files identically.

**Skill (`skills/**`, all hard-gated — expect these to route to Les):** K1–K8 in the second issue
comment. The sharpest: `triage.md` writes two label names the harness has never heard of
(`agent-session:needs-details`, `agent-session:interactive`), and because `writes.py` issues both adds
in one `gh issue edit` with no ensure-exists, the edit fails and **the issue is never parked**.
Fourteen references to a `pr` mode with no phase file. Two modes the driver actively requests
(`fix_conflict`, `refine`) missing from `SKILL.md`'s dispatcher. `rethink.md`'s step marked
**CRITICAL** is a no-op in the common case, because `is_specced` reads the label and `rethink` only
retires the body marker.

**Build/CI/hygiene:**
- **H1.** `make loop ISSUES=7` is silently ignored — `Makefile:185`'s `@$(MAKE) run ISSUES=...`
  recursive assignment beats the outer one, and `make help` claims it works, on the one target whose
  purpose is queue depth. `BUDGET` is per-issue, so a swallowed `ISSUES=5` is a wrong-sized spend.
  Use `LOOP_ISSUES ?= 2` and `$(or $(ISSUES),$(LOOP_ISSUES))`. The frozen suites do not cover this:
  `test_run_issue_flag` never discovers `loop` (its recipe does not invoke `$(DRIVER)`) and
  `test_dry_run_parity` explicitly exempts `--max-issues`. **The duplication in the run/dry-run
  quartet is not the bug — the uncovered slice is. Do not collapse it into a pattern rule.**
- **H2.** `.github/workflows/check.yml` uses mutable major tags 3–8 versions behind
  (`checkout@v4`/v7, `setup-python@v5`/v7, `setup-uv@v2`/v10), and has no `permissions:`,
  `concurrency:` or `timeout-minutes:`. `CLAUDE.md` gates `.github/**` *because it defines the
  environment the checks run in*, which makes this the loudest internal inconsistency in the repo.
  Pin by SHA with the version in a trailing comment. **Keep `fetch-depth: 0`** — `commit-lint`
  scopes to `origin/main..HEAD`.
- **H3.** `make typecheck` runs `mypy src`, not `mypy src tests`, hiding four errors — one is
  `"str" not callable` in `test_docs_check.py`, which is C11 surfacing as a type error.
- **H5.** No `make clean`. `~/.local/state/agent-session/lmorchard-decafclaw/` is 3.2 GB across 287
  run dirs with no retention. Propose `clean` / `clean-venvs` / `prune-state KEEP_DAYS ?= 30`, and
  **do not let any of them touch `runs.jsonl`** — that ledger is the project's per-run provenance.
- **H9.** `.local/` and `runs/` are untracked and unignored. ~1.5 GB reclaimable across 20 merged
  worktrees. **Two worktrees must NOT be removed**: `~/devel/agent-sessions-194` has four uncommitted
  files including a `GATE_FIELD_SPECS` refactor of the oracle, and
  `.worktrees/fix-triage-interactive-label` has a 158-line `scripts/parallelize.py` that exists in no
  commit on any ref. This repo **squash-merges**, so `git merge-base --is-ancestor` reports NO for
  almost every merged branch — use GitHub PR state as the oracle, and note that
  `git worktree remove` deletes the checkout, not the branch.

## Decisions that are Les's, not yours

Do not resolve these alone. Ask, or leave them and say why.

- Whether `AGENTS.md` becomes a pointer to `CLAUDE.md`. They are currently byte-identical, which
  sharpens rather than settles it: it needs `docs_check.check_risk_policy_parity` taught the pointer
  shape, and it turns on whether a Codex-hosted run needs its instruction file to stand alone.
- Whether `lifecycle.py` is named explicitly in the risk partition (see "Start here").
- **K9, the Ceremony Threshold.** Small/tactical work skips `checks.md` and the freeze, while
  `execute.md:113` says the independent verification is never skipped *and* that most unattended
  issues are that size. The verifier's only input is `checks.md`. So for the modal run the gate
  reduces to CI + threads + tier — a materially weaker gate than the skill documents. Either define
  a minimum oracle for the small case or say plainly that the frozen-check machinery is the
  exception. This was decided in passing and wants ratifying or reversing.
- **K9, OpenCode subagents.** `agent_runner.py` sets `"task": "deny"` for OpenCode because 1.18.18
  does not propagate policy to delegated agents. Subagents are how the check-author, check-reviewer,
  independent verifier and documentarians are dispatched, so on that backend none can run and nothing
  documents the fallback.
- **C8.** `validate_tdd` returns "compliant" for a stream it never read, and `run_swarm` double-guards
  the same null in the same unsafe direction. Whether to make it tri-state or delete it with
  `run_swarm` is a policy call.
- **X1.** Widening `assertion-lint`'s scope beyond `tests/driver/test_*.py`, and adding a rule for
  `assert <literal> in <source_text>`. The docstring's own warning — false positives train the
  operator to wave the check through — is why this is judgment.
- Whether `scripts/bootstrap-repo.sh` stays. Nothing references it, it was added on an abandoned
  branch, and PR #177's automatic label provisioning may supersede it — but it is also the setup path
  `usage.md` arguably should document.

## Gotchas that cost me time

- **`assertion-lint` matches literals and cannot tell a mention from an instance.** Writing
  `grep -q` in a docstring *while explaining that defect* trips it. `CLAUDE.md` already handles this
  by spelling a count as `N`; do the same — describe the idiom without quoting it.
- **`docs-check` only sees inline Markdown links** -- the bracketed-text-then-parenthesised-
  target form, written here in words because writing it in syntax makes the detector try to
  resolve the example and fail, which is how this line was found. The skill cites everything in
  backticks, which is why eleven of sixteen falsified skill references went undetected. Extending it
  to backticked paths, mode names and label names would close a whole class, and is probably the
  single highest-leverage instrument change available.
- **Moving anything under `docs/` can pull it out from under ruff's `exclude`.** Archiving a session
  put a frozen probe script back under the linter and broke `make lint`.
- **`codex` has `-p`, but it means `--profile`**, not print. It will not error; it will silently
  consume the next token.
- **`gh pr checks --json state` returns `SUCCESS`, not `pass`** — the normalised value is in
  `bucket`. `gh project item-list` truncates at 30 by default, as does `field-list`.
- Patching a re-exported name is a recurring trap here. Three separate instances turned up: a
  monkeypatch on a module global that bound a copy, a log capture that only worked because the target
  was a call-time trampoline, and a frozen clock reached through a barrel. **Patch the module that
  owns the thing.**

## When you finish a unit of work

Commit per logical step with a message that says what was wrong and how it was verified, not just
what changed — the existing commits on both branches are the house style. Reference `#261` and name
the finding IDs. Run `make check`. Do not push, do not open a PR, and do not merge anything without
asking Les. Post a progress comment on #261 when a batch lands, and record any finding you discover
that is not already in the issue.

If you find something in #261 that is wrong, say so — I got at least three things wrong in it and
corrected them in the progress comment. Verify before acting on any claim in there, including mine.
