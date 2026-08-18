## Goal

Put GitHub and project-board reads behind explicit adapters, while keeping requested
writes behind the validated manifest, so the coordinator depends on named operations
instead of scattered `gh` subprocess calls.

## Evidence

`src/agent_sessions/driver/gh_query.py` already owns several PR and rate-limit reads,
and `src/agent_sessions/driver/writes.py` validates requested writes. The coordinator
still issues direct GitHub commands for issue comments and labels, review threads, CI,
review state, board metadata and status, repository identity, and post-run PR refreshes
across `agent_session_driver.py:90-987` and inside `main()`.

Those calls use different error behavior: some raise, some return sentinel values, and
some catch broad exceptions. Moving them mechanically without preserving the command,
stderr, operation name, and retry context would make failures harder to diagnose.

## Bounded scope

- Define explicit read, operational-write, and board adapter interfaces for the
  GitHub operations the coordinator uses. Reuse `gh_query.py` and the write-manifest
  executor where they already own the operation.
- Inject adapters into lifecycle code so tests can supply fakes without monkeypatching
  global `subprocess.run`.
- Preserve error provenance in a structured exception or result that names the
  operation, command, exit status, and stderr when available.
- Keep agent-requested writes behind `writes.py`; do not add a new manifest kind or
  widen `writes.KINDS`.
- Do not change queue policy, gate classification, retry policy, credential scope, or
  board semantics.

## Acceptance criteria

- **C1 — runnable.** A repository scan SHALL find no direct `gh` subprocess construction
  in the coordinator outside the adapter composition boundary. Implement this as an AST
  assertion rather than a text-presence grep, then run:

  ```text
  uv run pytest -q driver/test_driver.py driver/test_gh_query.py driver/test_writes.py
  ```

- **C2 — runnable.** Adapter tests SHALL cover a successful result, a command failure
  with stderr, malformed JSON, and retry exhaustion; each failure SHALL retain its
  operation and command provenance. Run:

  ```text
  uv run pytest -q driver/test_gh_query.py driver/test_driver.py
  ```

- **C3 — runnable.** The full-loop suite SHALL use fake adapters and preserve selection,
  parking, write application, and outcome records:

  ```text
  uv run pytest -q driver/test_full_loop.py
  ```

- **G1 — runnable.** The write allowlist and merge prohibition SHALL remain intact:

  ```text
  uv run pytest -q driver/test_writes.py
  make driver-check
  ```

## Tier

`needs-review`. The work edits the protected coordinator and new, unlisted `src/**`
paths, which receive the repository's default gated tier.

## Overlap

Issue #152 owns the broader policy-from-code question. This issue preserves current
policy and isolates transport. Issue #195 owns distribution and the project-owned versus
harness-owned partition; no distribution format is chosen here.
