## Goal

Make assertion-count verification complete under `make check` and in the standalone
`docs-check` target.

## Evidence

`make check` runs `gate-test` and `docs-check` in parallel. During the maintainability
review, the aggregate command passed while `docs-check` printed:

```text
SKIP  assertion counts: could not run make gate-test (NOT verified -- this is a skip, not a pass)
```

The same skip reproduces under standalone `make docs-check`. The collection helper
passes literal `driver/test_*.py` and `scripts/test_*.py` arguments through
`subprocess.run` without shell expansion; the equivalent direct command exits 4 with
`file or directory not found`. The parallel gate makes the skip easy to miss among
interleaved output, but concurrency is not the only failing condition.

## Bounded scope

- Make the collection mechanism resolve the intended test files and remain reliable
  when `gate-test` runs concurrently.
- Keep `make check` parallel unless evidence shows serialization is the smallest safe
  solution.
- Preserve `docs-check`'s explicit distinction between a verified count and a skip.
- Do not pin a test count in documentation or introduce a hand-maintained test-file
  census.

## Acceptance criteria

- **C1 — runnable after its regression oracle is added.** Regression tests SHALL call
  the assertion-count probe both alone and concurrently with `gate-test`, and fail if
  `live_bash_assertions()` returns `None` or emits the assertion-count skip. Run:

  ```text
  uv run pytest -q scripts/test_docs_check.py scripts/test_gate_test_wiring.py
  ```

- **C2 — runnable.** The aggregate gate SHALL finish with no assertion-count skip and
  shall retain parallel execution:

  ```text
  make check
  ```

- **C3 — runnable.** The independent target SHALL still perform the assertion-count
  verification:

  ```text
  make docs-check
  ```

- **G1 — runnable.** The gate-test wiring assertions SHALL still discover new matching
  test files without a Makefile edit:

  ```text
  uv run pytest -q scripts/test_gate_test_wiring.py
  ```

## Tier

`needs-review`. The relevant implementation paths are drivable, but the discriminating
concurrency oracle does not exist yet and must be built before an autonomous run could
freeze this issue's criteria.

## Overlap

Issue #152 concerns policy separation, and issue #195 concerns distribution. Neither
owns check-process composition. This issue is limited to the observed parallel skip.
