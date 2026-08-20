DRIVER := driver/agent-session-driver.sh
SKILL  := $(CURDIR)/skills/agent-session
REPO   ?= lmorchard/decafclaw
REPO_PATH ?= $(HOME)/devel/decafclaw
BOARD  ?= lmorchard/6

.PHONY: help doctor doctor-self check venv clean clean-venvs prune-state evidence board-audit driver-check driver-test gate-test park-test docs-check assertion-lint commit-lint guard-lint dry-run run loop watch watch-self run-self dry-run-self skill-readonly backend-permission-probe opencode-policy-contract lint typecheck

help:
	@echo "check            run every check -- the targets listed below, in one go"
	@echo "doctor           check the driver's GitHub credentials against a live repo"
	@echo "doctor-self      the same, against this repo and its own board"
	@echo "venv             populate .venv once -- check does this before it fans out"
	@echo "lint             run ruff linter"
	@echo "typecheck        run mypy type checker"
	@echo "clean            remove tool caches and __pycache__; leaves all run state"
	@echo "clean-venvs      remove per-worktree virtualenvs"
	@echo "prune-state      drop old run dirs; dry run unless CONFIRM=1. WORKSPACES=1"
	@echo "                 also prunes per-issue worktrees, skipping any that are dirty"
	@echo "evidence         what has actually run: phases, repos, outcomes, from the ledgers"
	@echo "board-audit      audit this repo's live GitHub project (read-only)"
	@echo "driver-check     scan the Bash compatibility launcher for merge commands"
	@echo "driver-test      Python harness and fixture tests (alias of gate-test)"
	@echo "gate-test        pytest over the Python harness and detector suites"
	@echo "park-test        frozen acceptance checks for #5 (park state as a label)"
	@echo "skill-readonly   assert native agent tools cannot write to the skill directory"
	@echo "backend-permission-probe  run one live, harmless backend permission probe"
	@echo "opencode-policy-contract  verify config isolation against installed OpenCode"
	@echo "evidence         report outcomes across every per-repo run ledger (read-only)"
	@echo "                 REPO_FILTER=owner/name narrows it to one repo"
	@echo "docs-check       detect doc rot: links, tables, counts, risk-policy drift"
	@echo "assertion-lint   detect presence-grep assertions -- a spelling check, not a test"
	@echo "guard-lint       detect pinned test count guards in issue bodies"
	@echo "commit-lint      detect a commit message that QUOTES a closing keyword"
	@echo "dry-run          selection only against $(REPO); no claude invocation"
	@echo "run              one real unattended run (nothing merges)"
	@echo "loop             burn down up to 2 eligible issues (nothing merges)"
	@echo "watch            digest the newest run's stream.jsonl on a loop; reads, never writes"
	@echo "watch-self       the same, pinned to this repo's runs"
	@echo "run-self         drive THIS repo (needs --allow-nested-skill-dir)"
	@echo "dry-run-self     selection only against this repo's own board"
	@echo "                 ISSUE=n pin one issue, bypassing selection (run, run-self)"
	@echo "                 ISSUES=n BUDGET=n override queue depth (loop, run) /"
	@echo "                 per-issue ceiling; BUDGET is per issue, not per invocation"
	@echo ""
	@echo "  REPO=$(REPO)  REPO_PATH=$(REPO_PATH)  BOARD=$(BOARD)"

check: driver-check
	@$(MAKE) venv
	@$(MAKE) -j check-parallel
	@echo "all checks passed"

# Every job under `check-parallel` enters through `uv run`, which populates .venv on
# demand -- so on a cold checkout seven of them race for it and one dies with
# "Failed to install: ruff-<version>.whl". That message names a wheel, so it reads as a
# network fault; nothing in it points at make parallelism, and rerunning "fixes" it
# because the venv is warm by then. A gate you have learned to rerun is not a gate.
# Populate it once, serially, first. tests/scripts/test_check_venv_warmup.py freezes the
# ordering, and `check` reaches this through a recipe line rather than a prerequisite so
# that `make -j check` cannot reorder it.
venv:
	@uv sync --quiet

.PHONY: venv check-parallel

check-parallel: gate-test skill-readonly docs-check assertion-lint commit-lint lint typecheck

lint:
	@uv run ruff check .

# `mypy src` was correct when src/ was the only Python tree. tests/{driver,scripts}/
# came later and were never added, so four errors sat hidden -- three of them one
# defect: tests/scripts/test_docs_check.py had cloned a detector instead of calling it,
# which surfaced here as `"str" not callable`. Nothing recorded the narrow scope as a
# decision, so this is repairing an omission rather than reversing one.
typecheck:
	@uv run mypy src tests

board-audit:
	@uv run python -m agent_sessions.scripts.board_audit --owner lmorchard --project 9 --repo lmorchard/agent-sessions

# C1. This checks only the compatibility launcher; issue #248 owns coverage of
# the shipping Python coordinator. Kept separate so it can be cited directly.
driver-check:
	@matches=$$(grep -nE '^[^#]*(gh pr merge|gh api[^|]*merge|--auto\b)' $(DRIVER) \
	    | grep -v 'DENIED_TOOLS=' | grep -v 'Bash(gh pr merge' || true); \
	if [ -n "$$matches" ]; then \
	  echo "FAIL: driver contains an executable merge path:"; echo "$$matches"; exit 1; \
	fi; \
	echo "driver-check: no executable merge path in compatibility launcher $(DRIVER)"

# The harness and detector suites are Python tests; `gate-test` imports shipping
# modules rather than carrying hand-copied implementations.
driver-test: gate-test

# `--dist loadgroup` is load-bearing, not tuning. tests/scripts/test_gate_test_wiring.py
# marks its module `xdist_group` because one of its checks writes a probe test file into
# the working tree while the other collects that same tree -- and xdist honours the
# marker only under `--dist loadgroup`. Under a bare `-n auto` the marker did nothing.
# Tests carrying no group are still distributed by load, so this costs nothing.
gate-test:
	@uv run --quiet pytest -n auto --dist loadgroup tests/driver/test_*.py tests/scripts/test_*.py

# H7. This was an alias of `gate-test`, so `help`'s promise of "frozen acceptance
# checks for #5 (park state as a label)" delivered the entire suite -- the help line
# actively misdescribed it. Repointed at the suite it names rather than deleted, since
# a named shortcut to one frozen set is worth having and the description is now true.
# `driver-test` stays an alias: CLAUDE.md cites it by name, including in the
# risk-partition discussion.
park-test:
	@uv run --quiet pytest -n auto tests/driver/test_park_state.py

# Replaces move 3's `skill-untouched` guard, which pinned skills/ to a snapshot to
# prove the driver needed no skill edit. That claim is now verified and permanently
# recorded (git history + docs/build-log.md), so the snapshot is obsolete rather than
# inconvenient -- but the boundary it protected is still live, so this asserts the
# ongoing invariant instead of the frozen fact.
#
# The invariant: each backend grants the hosted run read access to the skill
# directory, so without a deny rule its native editing tools could change the
# instructions grading it. The named tests capture the Popen boundary and assert
# each backend's complete runtime policy.
skill-readonly:
	@uv run pytest -q \
	  tests/driver/test_agent_runner.py::test_claude_command_restores_mandatory_permission_policy \
	  tests/driver/test_agent_runner.py::test_caller_rules_cannot_replace_mandatory_denials \
	  tests/driver/test_agent_runner.py::test_opencode_command_applies_mandatory_permission_policy

# Live evidence for the backend permission boundary. Deliberately excluded from
# `check`: it invokes a configured model and requires the operator to inspect the
# recorded denial events. See issue #250.
backend-permission-probe:
	@test -n "$(BACKEND)" || { echo "BACKEND=claude|opencode is required"; exit 2; }
	@test -n "$(EVIDENCE_DIR)" || { echo "EVIDENCE_DIR=/path is required"; exit 2; }
	@uv run python -m agent_sessions.scripts.backend_permission_probe \
	  --backend "$(BACKEND)" --output-dir "$(EVIDENCE_DIR)" $(if $(MODEL),--model "$(MODEL)",)

# Model-free feature gate for the exact supported OpenCode binary. It seeds
# adversarial target config and target/home custom-tool fixtures, then proves the
# runner-owned agent and native denials remain effective. Kept outside `check`
# because OpenCode is not a repository dependency.
opencode-policy-contract:
	@uv run python -m agent_sessions.scripts.opencode_policy_contract

# Housekeeping, split three ways so destructiveness is opt-in by name. None of them
# touches `runs.jsonl`, `parked.jsonl`, `inbox.md` or `inflight.json` -- the ledger is
# this project's per-run provenance and the other three are live operator state.
# tests/scripts/test_prune_run_state.py asserts that rather than trusting it.
clean:
	@rm -rf .pytest_cache .ruff_cache .mypy_cache
	@find . -name __pycache__ -type d -prune -not -path './.venv/*' -exec rm -rf {} +
	@echo "clean: caches removed. State and .driver-state/ untouched -- see prune-state."

# The per-worktree virtualenvs. ~1 GB across this repo's worktrees, and `uv sync`
# rebuilds one in seconds, so this is the cheapest space in the tree.
clean-venvs:
	@find . -maxdepth 3 -name .venv -type d -prune -exec rm -rf {} + 2>/dev/null || true
	@echo "clean-venvs: virtualenvs removed. Run 'make venv' to rebuild."

# Dry run by default; CONFIRM=1 to remove. WORKSPACES=1 additionally prunes the per-issue
# git worktrees, which is where the volume actually is -- 3.1 GB against runs/'s 79 MB when
# this was written. Workspaces are pruned by *dirtiness*, never by age: one holding
# uncommitted content is kept and reported. That is deliberately the opposite of the
# driver's own --clean-workspaces, which force-removes.
KEEP_DAYS ?= 30

prune-state:
	@uv run python scripts/prune_run_state.py --keep-days $(KEEP_DAYS) \
	  $(if $(WORKSPACES),--workspaces,) $(if $(CONFIRM),--confirm,)

# The report CLAUDE.md tells you to cite instead of writing a number down. Reads every
# per-repo runs.jsonl under the live state root; pass --repo owner/name or --state-dir to
# narrow it. It used to read `.driver-state/`, which #27 superseded, so it rendered a
# cold archive whose rows predate the `phase` field it groups by.
evidence:
	@uv run python -m agent_sessions.scripts.evidence $(if $(REPO_FILTER),--repo $(REPO_FILTER),)

# Documentation rot is mechanical, so detect it mechanically. Every doc defect this
# project hit was a fact derivable from a live source, or prose duplicating one --
# never a judgment. An instruction-file rule saying "don't do that" would be an
# exhortation, and this project is 3 for 3 on those measuring away. See
# src/agent_sessions/scripts/docs_check.py.
docs-check:
	@uv run python -m agent_sessions.scripts.docs_check

# `grep -q 'x' "$(DRIVER)"` passes when x appears in a COMMENT -- findings.md calls
# that "a spelling check, not a test", and the warning against it sat in a comment
# next to eight live instances for two days without preventing a ninth. So: a
# detector, not an exhortation. Same reasoning as docs-check above.
#
# Scope is tests/driver/test_*.py. See issue #28 and
# src/agent_sessions/scripts/assertion_lint.py.
assertion-lint:
	@uv run python -m agent_sessions.scripts.assertion_lint

# GitHub closes an issue on `Closes #N` in a commit message, and commit messages
# are NOT rendered as markdown -- so backticks around one are literal characters,
# not quoting, and the issue closes anyway. That is how issue #7 was closed by
# accident on 2026-07-31, by a commit body describing a test fixture.
#
# The PR's own metadata said nothing was wrong: gh reported its
# closingIssuesReferences as [23]. Only the commit body carried the reference,
# which is what made it invisible.
#
# Scope is the commits this branch adds on top of origin/main. History is
# immutable and already holds the one known instance, so re-reporting it forever
# would train the operator to ignore the check --
# `uv run python -m agent_sessions.scripts.commit_lint --all` is how the regression
# guard gets run by hand. Same detector-not-
# exhortation reasoning as docs-check and assertion-lint above. See issue #47.
commit-lint:
	@uv run python -m agent_sessions.scripts.commit_lint

# `gh issue list` defaults to 30 records, so this used to scan the newest 30 open
# issues and print "no pinned test count guards found" -- a clean bill over an
# arbitrary slice, indistinguishable from a clean bill over the backlog. The limit is
# now explicit on both sides: `gh` is asked for a bounded page, and `guard_lint` is told
# what was asked for so a full page fails as possibly-truncated rather than passing.
# `number` is in the projection so findings cite a real issue, not an array index.
GUARD_LINT_LIMIT ?= 500

guard-lint:
	@gh issue list --limit $(GUARD_LINT_LIMIT) --json number,body \
	  | uv run python -m agent_sessions.scripts.guard_lint --limit $(GUARD_LINT_LIMIT)

# Credential preflight. Not in `check`: it makes live GitHub calls and depends on
# the operator's own tokens, so it is a thing you run when setting a machine up or
# when the driver starts failing for reasons that look like nothing.
doctor:
	@uv run --quiet python -m agent_sessions.scripts.doctor --repo $(REPO) --repo-path $(REPO_PATH) --board $(BOARD)

doctor-self:
	@uv run --quiet python -m agent_sessions.scripts.doctor --repo lmorchard/agent-sessions --repo-path $(CURDIR) --board lmorchard/9

# The targeting flags must match `run` exactly -- a dry run that inspects a
# different working tree is answering "what would happen?" about somewhere else.
# scripts/test_dry_run_parity.py derives both sides from `make -n` and compares.
dry-run:
	@bash $(DRIVER) --repo $(REPO) --board $(BOARD) \
	  --skill-dir $(SKILL) --repo-path $(REPO_PATH) --dry-run

# BUDGET is per issue, not per invocation. $12 is measured too low: real runs have
# cost $4.41-$11.87, #710 exhausted $12 mid-review-cycle, and #52 hit $23.63.
# $35 leaves headroom for the re-verification tax and thorough review rounds.
BUDGET ?= 35
ISSUES ?= 1
INTERVAL ?= 10

# ISSUE=n pins one issue and bypasses selection. It was wired into `run-self` and
# not here, silently -- `make run ISSUE=704` ran #704 by luck, because selection
# happened to agree. The moment you reach for ISSUE= is the moment you want
# determinism, so getting selection's choice instead is worst exactly then. See #71.
#
# scripts/test_run_issue_flag.py holds the frozen checks, and it grades both recipes
# from one derivation -- so the asymmetry cannot come back on either side.
run:
	@bash $(DRIVER) --repo $(REPO) --board $(BOARD) \
	  --skill-dir $(SKILL) --repo-path $(REPO_PATH) \
	  --max-issues $(ISSUES) --max-budget-usd $(BUDGET) $(if $(ISSUE),--issue $(ISSUE),)

# The multi-issue burndown. Same target as `run` with a bigger queue depth --
# separate only because it was assembled by hand twice and is worth discovering.
#
# `ISSUES=$(or $(ISSUES_OVERRIDE),2)` used to sit on the sub-make line, where a
# recursive command-line assignment beats the caller's: `make loop ISSUES=7` ran two
# issues, silently, while `make help` promised the override worked. And since
# `BUDGET ?= 35` is *per issue*, a swallowed `ISSUES=5` is a wrong-sized spend rather
# than a wrong-sized queue. #71, one variable over. Resolving `$(or ...)` here in the
# parent make reads the outer `ISSUES` at expansion time, so nothing is overridden on
# the child's command line. tests/scripts/test_loop_queue_depth.py freezes it, and
# covers the slice the run/dry-run suites deliberately leave alone.
#
# `$(or $(ISSUES),$(LOOP_ISSUES))` was the obvious first attempt and it is wrong:
# `ISSUES ?= 1` above means $(ISSUES) is never empty, so `$(or ...)` cannot tell "the
# caller asked for a depth" from "the file's default applied", and a bare `make loop`
# collapsed to one issue. That regression is what C2 in the frozen suite exists to
# catch, and it caught it. `$(origin)` is the thing that distinguishes them.
LOOP_ISSUES ?= 2
ifneq ($(filter command environment,$(firstword $(origin ISSUES))),)
  LOOP_ISSUES := $(ISSUES)
endif

loop:
	@$(MAKE) run ISSUES=$(LOOP_ISSUES)

# `run` and `run-self` print nothing between "== invoke #N ==" and the exit line,
# so a run is a black box for as long as it lasts -- while megabytes of live signal
# sit in the run's stream.jsonl the whole time. This reads that signal; it never
# writes to the state dir, and nothing about the run changes because it is watched.
# Not in `check`: it is an interactive loop with no end condition. See issue #42.
#
# INTERVAL= picks how often to poll. Auto-detects the newest run across state dirs;
# use watch-self or pass --repo <owner/name> to target a specific repository.
watch:
	@uv run python -m agent_sessions.scripts.run_progress --watch --interval $(INTERVAL)

watch-self:
	@uv run python -m agent_sessions.scripts.run_progress --repo lmorchard/agent-sessions --watch --interval $(INTERVAL)

# Drive THIS repo. Needs --allow-nested-skill-dir, because $(SKILL) lives inside
# $(CURDIR) and #10's guard now refuses that configuration by default (exit 2).
#
# Passing the flag here is deliberate, not an erosion of the guard: the guard
# exists to catch a *typo* in --skill-dir, and a named target is not a typo. The
# nested configuration is safe here for two independent reasons, neither of which
# depends on remembering anything:
#   1. skills/** and the shipping coordinator, gate, and compatibility launcher
#      are risk-gated in the instruction files, so intake tiers any issue touching
#      them needs-review and selection skips it;
#   2. agent_runner's mandatory Claude policy blocks Edit/Write/NotebookEdit on
#      $(SKILL) regardless of nesting, so a run could not write the skill even if
#      it were selected.
# Verified 2026-07-29: without the flag this exits 2; with it, selection runs.
run-self:
	@bash $(DRIVER) --repo lmorchard/agent-sessions --board lmorchard/9 \
	  --skill-dir $(SKILL) --repo-path $(CURDIR) --allow-nested-skill-dir \
	  --max-issues $(ISSUES) --max-budget-usd $(BUDGET) $(if $(ISSUE),--issue $(ISSUE),)

dry-run-self:
	@bash $(DRIVER) --repo lmorchard/agent-sessions --board lmorchard/9 \
	  --skill-dir $(SKILL) --repo-path $(CURDIR) --allow-nested-skill-dir --dry-run
