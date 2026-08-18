## Goal

Define a mandatory permission floor for every supported agent backend and fail closed
when a backend cannot enforce it, before non-Claude backends are treated as equivalent
hosts.

## Evidence

`agent_runner.run_agent()` now composes immutable allow and deny rules for Claude at the
process boundary. The OpenCode branch launches `opencode run ... --auto` and does not
consume `--allowed-tools`, `--disallowed-tools`, or the skill-directory deny rules. Both
branches receive the read-scoped GitHub environment, but local file and command
containment are not equivalent.

The review deliberately restored the known Claude contract only. It did not establish
what OpenCode's current permission mechanism guarantees or whether it can express the
same destructive-command and skill-directory restrictions.

## Bounded scope

- Document the backend-independent permission invariants: read-scoped GitHub identity,
  no merge or destructive repository operations, and no writes to the skill directory.
- Map each supported backend to a concrete enforcement mechanism verified against the
  installed backend version.
- Apply backend-specific policy at the execution boundary, and refuse to launch a
  backend that cannot meet the mandatory floor.
- Preserve backend-specific output parsing, model selection, timeout handling, and cost
  extraction.
- Do not solve harness distribution, introduce a new host, or weaken Claude's current
  rules to match a less capable backend.

## Acceptance criteria

- **C1 — human judgment.** A reviewer SHALL approve the backend-independent threat model
  and the evidence that each backend mechanism enforces it. Command-line option names
  or documentation alone are insufficient; the evidence must include a live denial
  against a harmless temporary target for each supported backend.
- **C2 — runnable.** Command-capture tests SHALL assert the backend-specific policy and
  the read-scoped child environment for every supported backend:

  ```text
  uv run pytest -q driver/test_agent_runner.py
  ```

- **C3 — runnable.** A backend with no verified policy adapter SHALL return a nonzero
  configuration error before `subprocess.Popen` is called. The named test SHALL live in
  `driver/test_agent_runner.py` and run under the command above.
- **G1 — runnable.** Claude's mandatory denials and caller-additive behavior SHALL remain
  intact:

  ```text
  make skill-readonly
  ```

- **G2 — runnable.** Backend stream parsing and success detection SHALL remain green:

  ```text
  uv run pytest -q driver/test_agent_runner.py
  make check
  ```

## Tier

`needs-review`. This is authorization and containment work on an unlisted shipping
`src/**` path, and C1 requires a human to ratify the threat model and live evidence.

## Overlap

Issue #152 owns the general policy-from-code question; this issue defines and enforces
the backend execution contract without choosing a repository-wide policy format. Issue
#195 owns distribution to a second repository. Issue #3 owns the GHA host, not local
backend parity.
