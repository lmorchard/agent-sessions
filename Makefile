DRIVER := driver/agent-session-driver.sh
SKILL  := $(CURDIR)/skills/agent-session
REPO   ?= lmorchard/decafclaw
REPO_PATH ?= $(HOME)/devel/decafclaw
BOARD  ?= lmorchard/6

.PHONY: help check driver-check driver-test gate-test park-test docs-check assertion-lint commit-lint dry-run run loop watch run-self dry-run-self skill-readonly

help:
	@echo "check            run every check -- the targets listed below, in one go"
	@echo "driver-check     assert the driver has no executable merge path"
	@echo "driver-test      bash fixture tests (runs gate-test first)"
	@echo "gate-test        pytest over the Python modules -- imports them, never restates"
	@echo "park-test        frozen acceptance checks for #5 (park state as a label)"
	@echo "skill-readonly   assert the hosted run cannot write to the skill directory"
	@echo "docs-check       detect doc rot: dead links, split tables, stale counts"
	@echo "assertion-lint   detect presence-grep assertions -- a spelling check, not a test"
	@echo "commit-lint      detect a commit message that QUOTES a closing keyword"
	@echo "dry-run          selection only against $(REPO); no claude invocation"
	@echo "run              one real unattended run (nothing merges)"
	@echo "loop             burn down up to 2 eligible issues (nothing merges)"
	@echo "watch            digest the newest run's stream.jsonl on a loop; reads, never writes"
	@echo "run-self         drive THIS repo (needs --allow-nested-skill-dir; ISSUE=n to pin)"
	@echo "dry-run-self     selection only against this repo's own board"
	@echo "                 ISSUES=n BUDGET=n override queue depth / per-issue ceiling"
	@echo ""
	@echo "  REPO=$(REPO)  REPO_PATH=$(REPO_PATH)  BOARD=$(BOARD)"

check: driver-check driver-test park-test skill-readonly docs-check assertion-lint commit-lint
	@echo "all checks passed"

# C1. Kept separate from driver-test so it can be cited as its own check.
driver-check:
	@matches=$$(grep -nE '^[^#]*(gh pr merge|gh api[^|]*merge|--auto\b)' $(DRIVER) \
	    | grep -v 'DENIED_TOOLS=' | grep -v 'Bash(gh pr merge' || true); \
	if [ -n "$$matches" ]; then \
	  echo "FAIL: driver contains an executable merge path:"; echo "$$matches"; exit 1; \
	fi; \
	echo "driver-check: no executable merge path in $(DRIVER)"

# Two suites, one parser. driver/test_gate.py IMPORTS driver/gate.py rather than
# restating it -- which is the whole point of extracting it. test-driver.sh used
# to hand-copy the parsers, the copies drifted, and the suite ended up grading a
# replica that called a stale-CI PR eligible for auto-merge where the shipped
# code voided it.
#
# `uv` runs the tests; the driver itself calls plain `python3`, because gate.py is
# stdlib-only and must stay portable to a GHA runner.
driver-test: gate-test
	@bash driver/test-driver.sh

gate-test:
	@uv run --quiet pytest driver/test_gate.py scripts/test_docs_check.py scripts/test_run_progress.py scripts/test_commit_lint.py scripts/test_commit_lint_edges.py

# The frozen acceptance checks for issue #5, wired in AFTER the work landed --
# deliberately, because guard G1 was "make check green" and it had to pass at the
# freeze, when every one of these failed. They invoke the shipped driver as a
# subprocess against stubbed `gh` and `claude`, so deleting the behaviour flips them.
park-test:
	@bash driver/test-park-state.sh

# Replaces move 3's `skill-untouched` guard, which pinned skills/ to a snapshot to
# prove the driver needed no skill edit. That claim is now verified and permanently
# recorded (git history + docs/build-log.md), so the snapshot is obsolete rather than
# inconvenient -- but the boundary it protected is still live, so this asserts the
# ongoing invariant instead of the frozen fact.
#
# The invariant: --add-dir grants the hosted run access to the skill directory, so
# without a deny rule the run could edit the instructions grading it. That is the
# implementer authoring its own oracle -- the one failure this system exists to
# prevent. Verified that `Edit(//abs/**)` blocks and `Edit(/abs/**)` does NOT.
skill-readonly:
	@for tool in Edit Write NotebookEdit; do \
	  grep -qF ",$$tool(/\$$SKILL_DIR/**)" $(DRIVER) || { \
	    echo "FAIL: $(DRIVER) does not deny $$tool on the skill dir."; \
	    echo "      The hosted run could edit the instructions that grade it."; exit 1; }; \
	done; \
	if grep -nE '^[^#]*Edit\(//' $(DRIVER); then \
	  echo "FAIL: hardcoded // path in a deny rule; must interpolate SKILL_DIR"; exit 1; \
	fi; \
	echo "skill-readonly: driver denies Edit/Write/NotebookEdit on the skill dir"

# Documentation rot is mechanical, so detect it mechanically. Every doc defect this
# project hit was a fact derivable from a live source, or prose duplicating one --
# never a judgment. A CLAUDE.md rule saying "don't do that" would be an exhortation,
# and this project is 3 for 3 on those measuring away. See scripts/docs_check.py.
docs-check:
	@python3 scripts/docs_check.py

# `grep -q 'x' "$(DRIVER)"` passes when x appears in a COMMENT -- findings.md calls
# that "a spelling check, not a test", and the warning against it sat in a comment
# next to eight live instances for two days without preventing a ninth. So: a
# detector, not an exhortation. Same reasoning as docs-check above.
#
# Scope is driver/test-*.sh. This Makefile's own `grep -qF` guards are excluded on
# purpose -- skill-readonly asserts a deny rule is literally PRESENT in the driver,
# so there presence is the property being tested, not a stand-in for behaviour.
# See issue #28 and scripts/assertion_lint.py.
assertion-lint:
	@python3 scripts/assertion_lint.py

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
# would train the operator to ignore the check -- `python3 scripts/commit_lint.py
# --all` is how the regression guard gets run by hand. Same detector-not-
# exhortation reasoning as docs-check and assertion-lint above. See issue #47.
commit-lint:
	@python3 scripts/commit_lint.py

dry-run:
	@bash $(DRIVER) --repo $(REPO) --board $(BOARD) --dry-run

# BUDGET is per issue, not per invocation. $12 is measured too low: real runs have
# cost $4.41-$11.87, #710 exhausted $12 mid-review-cycle, and the two runs in move 5
# came in at $11.76 and $11.20. $25 leaves headroom for the re-verification tax.
BUDGET ?= 25
ISSUES ?= 1
INTERVAL ?= 10

run:
	@bash $(DRIVER) --repo $(REPO) --board $(BOARD) \
	  --skill-dir $(SKILL) --repo-path $(REPO_PATH) \
	  --max-issues $(ISSUES) --max-budget-usd $(BUDGET)

# The multi-issue burndown. Same target as `run` with a bigger queue depth --
# separate only because it was assembled by hand twice and is worth discovering.
loop:
	@$(MAKE) run ISSUES=$(or $(ISSUES_OVERRIDE),2)

# `run` and `run-self` print nothing between "== invoke #N ==" and the exit line,
# so a run is a black box for as long as it lasts -- while megabytes of live signal
# sit in the run's stream.jsonl the whole time. This reads that signal; it never
# writes to the state dir, and nothing about the run changes because it is watched.
# Not in `check`: it is an interactive loop with no end condition. See issue #42.
#
# REPO= picks whose runs are watched, INTERVAL= how often. It follows the newest
# run under that repo's state dir, so it can be started before the run is.
watch:
	@python3 scripts/run_progress.py --repo $(REPO) --watch --interval $(INTERVAL)

# Drive THIS repo. Needs --allow-nested-skill-dir, because $(SKILL) lives inside
# $(CURDIR) and #10's guard now refuses that configuration by default (exit 2).
#
# Passing the flag here is deliberate, not an erosion of the guard: the guard
# exists to catch a *typo* in --skill-dir, and a named target is not a typo. The
# nested configuration is safe here for two independent reasons, neither of which
# depends on remembering anything:
#   1. skills/** and driver/gate.py are risk-gated in CLAUDE.md, so intake tiers
#      any issue touching them needs-review and selection skips it;
#   2. DENIED_TOOLS blocks Edit/Write/NotebookEdit on $(SKILL) regardless of
#      nesting, so a run could not write the skill even if it were selected.
# Verified 2026-07-29: without the flag this exits 2; with it, selection runs.
run-self:
	@bash $(DRIVER) --repo lmorchard/agent-sessions --board lmorchard/9 \
	  --skill-dir $(SKILL) --repo-path $(CURDIR) --allow-nested-skill-dir \
	  --max-issues $(ISSUES) --max-budget-usd $(BUDGET) $(if $(ISSUE),--issue $(ISSUE),)

dry-run-self:
	@bash $(DRIVER) --repo lmorchard/agent-sessions --board lmorchard/9 --dry-run
