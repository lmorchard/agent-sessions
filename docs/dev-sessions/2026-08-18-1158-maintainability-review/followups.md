# Maintainability Review Follow-ups

These drafts record the maintainability work deferred by the 2026-08-18 safety-first
review. The linked body files are the exact content submitted to GitHub; no existing
issue was edited.

## Live backlog comparison

On 2026-08-18, this query returned the open backlog:

```text
gh issue list --repo lmorchard/agent-sessions --state open --limit 200 --json number,title,body,labels
```

No open issue owned any of the five concrete topics. The closest overlaps were:

- #152, policy separation: referenced from the coordinator, adapter, verifier, and
  backend-permission drafts; none chooses the policy format that #152 leaves open.
- #195, distribution: referenced from the same drafts; none decides how a second
  repository receives project-specific policy.
- #3, GHA host: referenced from the backend-permission draft; it owns the remote host,
  not permission parity between locally selectable backends.

## Refactor: decompose driver main into lifecycle operations

- **Goal:** introduce testable lifecycle operations and a typed run context without
  changing routing behavior.
- **Evidence:** `agent_session_driver.main()` owns configuration through final reporting
  in one function.
- **Scope:** coordinator structure only; preserve the CLI, state formats, policy, and
  bounded modules.
- **Checks:** existing full-loop and workspace integration suites, new operation-level
  tests, and `make check`; architectural boundary quality requires human judgment.
- **Tier:** `needs-review` because the protected coordinator is in scope.
- **Overlap:** #152 owns policy separation; #195 owns distribution.
- **Frozen body:** [followup-coordinator-decomposition.md](followup-coordinator-decomposition.md)
- **GitHub:** https://github.com/lmorchard/agent-sessions/issues/246

## Refactor: consolidate GitHub I/O behind explicit adapters

- **Goal:** make GitHub and board operations explicit dependencies while keeping
  requested writes behind the manifest.
- **Evidence:** the coordinator contains direct `gh` subprocesses beside `gh_query.py`
  and `writes.py`.
- **Scope:** read, operational-write, and board transport plus error provenance; no
  queue, gate, credential, or manifest-vocabulary changes.
- **Checks:** adapter failure-path tests, an AST boundary assertion, the full-loop suite,
  write tests, and `make driver-check`.
- **Tier:** `needs-review` because the protected coordinator and unlisted package paths
  are in scope.
- **Overlap:** #152 owns policy separation; #195 owns distribution.
- **Frozen body:** [followup-github-adapters.md](followup-github-adapters.md)
- **GitHub:** https://github.com/lmorchard/agent-sessions/issues/247

## Verifier: make driver-check inspect the shipping Python boundaries

- **Goal:** verify the executable Python path and registered writes rather than the
  compatibility launcher alone.
- **Evidence:** `make driver-check` searches only the shell launcher; `gate.py` also
  retains a stale present-tense Bash-orchestration module description.
- **Scope:** an offline, mutation-backed verifier plus the docstring correction; no
  runtime behavior changes.
- **Checks:** `make driver-check`, mutation tests, gate and full-loop tests, and
  `make check`; current-versus-historical docstring framing requires human judgment.
- **Tier:** `needs-review` because the protected gate oracle is in scope.
- **Overlap:** #152 owns policy separation; #195 owns distribution.
- **Frozen body:** [followup-driver-check.md](followup-driver-check.md)
- **GitHub:** https://github.com/lmorchard/agent-sessions/issues/248

## Fix: prevent docs-check assertion verification from skipping under make check

- **Goal:** make assertion-count verification complete under both `make check` and
  standalone `make docs-check`.
- **Evidence:** both targets explicitly skip; the helper passes literal pytest glob
  arguments without shell expansion, and the direct equivalent exits 4.
- **Scope:** repair file discovery and preserve parallel reliability without a
  hand-maintained census.
- **Checks:** a new concurrency regression, `make check`, `make docs-check`, and the
  gate-test wiring suite.
- **Tier:** `needs-review` because the needed discriminating concurrency oracle does not
  yet exist.
- **Overlap:** neither #152 nor #195 owns this verifier-composition defect.
- **Frozen body:** [followup-docs-check-parallel.md](followup-docs-check-parallel.md)
- **GitHub:** https://github.com/lmorchard/agent-sessions/issues/249

**Erratum, 2026-08-18:** The frozen body misstates the tier rationale when it says
the relevant implementation paths are drivable. `make docs-check` invokes
`agent_sessions.scripts.docs_check`, whose shipping implementation is
`src/agent_sessions/scripts/docs_check.py`. The risk partition classifies every
unlisted `src/**` path as `needs-review`; therefore #249 is also gated by its
implementation path. Its tier remains correct.

The frozen overlap sentence also narrows #249 to the “observed parallel skip.” The
issue's actual scope is the standalone collection defect plus reliable verification
under parallel `make check`, as its goal, evidence, bounded scope, and criteria state.
The body file and GitHub issue remain unchanged as the immutable filing record.

## Safety: define permission parity for non-Claude agent backends

- **Goal:** define a backend-independent permission floor and fail closed when a backend
  cannot enforce it.
- **Evidence:** Claude now receives mandatory runtime rules; OpenCode runs with `--auto`
  and consumes none of them.
- **Scope:** backend execution policy only; preserve parsing, timeouts, costs, and Claude's
  current floor.
- **Checks:** live harmless denial probes approved by a human, command-capture tests,
  fail-closed launch tests, `make skill-readonly`, and `make check`.
- **Tier:** `needs-review` because this is authorization work on an unlisted shipping
  path and includes a human threat-model decision.
- **Overlap:** #152 owns policy separation, #195 owns distribution, and #3 owns the GHA
  host.
- **Frozen body:** [followup-backend-permissions.md](followup-backend-permissions.md)
- **GitHub:** https://github.com/lmorchard/agent-sessions/issues/250
