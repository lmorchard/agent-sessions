# Spec: Rewrite agent-session-driver.sh in Python (Issue #170)

## The Problem
The `agent-session-driver.sh` orchestration script (~1,700 lines of bash) relies heavily on external subprocesses (`jq`, `grep`, `sed`, `awk`, `gh`) and shell utilities. This incurs severe process fork/exec overhead (~20–25s per test suite run for `test-driver.sh` and `test-park-state.sh`), creating a performance bottleneck and brittle string parsing.

## The Solution
1. **Python Orchestration (`driver/agent_session_driver.py`)**: Rewrite the driver entirely in native Python, leveraging existing Python modules (`gate.py`, `gh_query.py`, `agent_runner.py`, `discussion_manager.py`).
2. **Native Pytest Suites (`driver/test_driver.py`, `driver/test_park_state.py`)**: Replace bash fixture test suites (`test-driver.sh`, `test-park-state.sh`) with robust, parallelizable `pytest` test suites.
3. **Compatibility Wrapper**: Keep `driver/agent-session-driver.sh` as a thin executable Python script (or bash wrapper) so existing Makefile targets and CI workflows invoke it seamlessly without breaking interface contracts.

## Acceptance Criteria
- **CRITERION 1:** GIVEN the Python driver `agent_session_driver.py`, WHEN invoked with `--dry-run` or normal run flags, THEN it correctly parses arguments, selects eligible issues, and executes reconciliation logic.
  **CHECK:** `pytest driver/test_driver.py` passes all test cases covering argument parsing, selection, locking, attempts, and execution loop.
- **CRITERION 2:** GIVEN park state behavior (issue #5), WHEN an issue encounters errors or needs human attention, THEN park labels are correctly managed and verified.
  **CHECK:** `pytest driver/test_park_state.py` passes all frozen acceptance checks for park state.
- **CRITERION 3:** GIVEN the test suite execution, WHEN running `make check`, THEN all Python tests (`gate-test`, `driver-test`, `park-test`, etc.) pass with zero failures and significantly improved execution speed.
  **CHECK:** `make check` exits 0.
