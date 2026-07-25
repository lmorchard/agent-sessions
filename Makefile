DRIVER := driver/agent-session-driver.sh
SKILL  := $(CURDIR)/skills/agent-session
REPO   ?= lmorchard/decafclaw
REPO_PATH ?= $(HOME)/devel/decafclaw
BOARD  ?= lmorchard/6

.PHONY: help check driver-check driver-test dry-run run skill-readonly

help:
	@echo "check            run every check (driver-check + driver-test + skill-readonly)"
	@echo "driver-check     assert the driver has no executable merge path"
	@echo "driver-test      fixture tests for the classifier and tier filter"
	@echo "skill-readonly   assert the hosted run cannot write to the skill directory"
	@echo "dry-run          selection only against $(REPO); no claude invocation"
	@echo "run              one real unattended run (nothing merges)"
	@echo ""
	@echo "  REPO=$(REPO)  REPO_PATH=$(REPO_PATH)  BOARD=$(BOARD)"

check: driver-check driver-test skill-readonly
	@echo "all checks passed"

# C1. Kept separate from driver-test so it can be cited as its own check.
driver-check:
	@matches=$$(grep -nE '^[^#]*(gh pr merge|gh api[^|]*merge|--auto\b)' $(DRIVER) \
	    | grep -v 'DENIED_TOOLS=' | grep -v 'Bash(gh pr merge' || true); \
	if [ -n "$$matches" ]; then \
	  echo "FAIL: driver contains an executable merge path:"; echo "$$matches"; exit 1; \
	fi; \
	echo "driver-check: no executable merge path in $(DRIVER)"

driver-test:
	@bash driver/test-driver.sh

# Replaces move 3's `skill-untouched` guard, which pinned skills/ to a snapshot to
# prove the driver needed no skill edit. That claim is now verified and permanently
# recorded (git history + design.md), so the snapshot is obsolete rather than
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

dry-run:
	@bash $(DRIVER) --repo $(REPO) --board $(BOARD) --dry-run

run:
	@bash $(DRIVER) --repo $(REPO) --board $(BOARD) \
	  --skill-dir $(SKILL) --repo-path $(REPO_PATH) \
	  --max-issues 1
