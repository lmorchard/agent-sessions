# Plan: Rewrite agent-session-driver.sh in Python

## Steps

1. **Design & Implement Python Driver (`driver/agent_session_driver.py`)**:
   - Translate all argument parsing, validation, state dir setup, orphan protection, locking, selection logic, run execution loop, budgeting, retry handling, and classify-only mode from bash into Python.
   - Import and use `gate.py`, `gh_query.py`, `agent_runner.py`, `discussion_manager.py`, and `label_manager.py`.

2. **Port Test Suites to Pytest (`driver/test_driver.py`, `driver/test_park_state.py`)**:
   - Translate `test-driver.sh` test cases into `driver/test_driver.py`.
   - Translate `test-park-state.sh` test cases into `driver/test_park_state.py`.
   - Utilize `pytest`, `tmp_path`, `monkeypatch`, and mocking for `gh`, `claude`, and process execution.

3. **Wire up Driver Wrapper (`driver/agent-session-driver.sh`)**:
   - Replace or update `driver/agent-session-driver.sh` to execute `agent_session_driver.py` directly (`#!/usr/bin/env python3`).

4. **Update Makefile & Verify**:
   - Update `Makefile` target `driver-test` and `park-test` to point to pytest.
   - Run `make check` and verify all tests pass cleanly.
