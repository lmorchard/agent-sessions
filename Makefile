DRIVER := driver/agent-session-driver.sh
SKILL  := $(CURDIR)/skills/agent-session
REPO   ?= lmorchard/decafclaw
REPO_PATH ?= $(HOME)/devel/decafclaw
BOARD  ?= lmorchard/6

.PHONY: help check driver-check driver-test dry-run run skill-untouched

help:
	@echo "check            run every check (driver-check + driver-test + skill-untouched)"
	@echo "driver-check     assert the driver has no executable merge path"
	@echo "driver-test      fixture tests for the classifier and tier filter"
	@echo "skill-untouched  assert the driver needed no change to skills/ (guard G1)"
	@echo "dry-run          selection only against $(REPO); no claude invocation"
	@echo "run              one real unattended run (nothing merges)"
	@echo ""
	@echo "  REPO=$(REPO)  REPO_PATH=$(REPO_PATH)  BOARD=$(BOARD)"

check: driver-check driver-test skill-untouched
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

# G1. The boundary claim is that the board-driver needs no skill change. This is
# what makes the claim checkable rather than asserted. Anchored to the commit the
# move-3 session started from, since HEAD moves as the session commits.
SESSION_BASE ?= df77e8f
skill-untouched:
	@diff=$$(git diff --stat $(SESSION_BASE) -- skills/ || true); \
	if [ -n "$$diff" ]; then \
	  echo "FAIL: skills/ changed since $(SESSION_BASE) -- the driver was supposed to need no skill edit:"; \
	  echo "$$diff"; exit 1; \
	fi; \
	echo "skill-untouched: skills/ unchanged since $(SESSION_BASE)"

dry-run:
	@bash $(DRIVER) --repo $(REPO) --board $(BOARD) --dry-run

run:
	@bash $(DRIVER) --repo $(REPO) --board $(BOARD) \
	  --skill-dir $(SKILL) --repo-path $(REPO_PATH) \
	  --max-issues 1
