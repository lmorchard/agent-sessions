# Research

## Starting state

- PR #251 merged into `origin/main` as `6269aac` before this session began.
- The isolated branch is `fix/250-backend-permission-parity` at that commit.
- Baseline `make check` passed with 488 tests. `docs-check` disclosed the known
  assertion-count skip tracked by #249.
- Issue #250 moved from Ready to In Progress on project 9.

## Current backend behavior

`agent_runner.run_agent()` applies `DEFAULT_ALLOWED_TOOLS`, destructive-command
denials, and skill-directory editing denials only in the Claude branch. The OpenCode
branch runs:

```text
opencode run <prompt> --format json --auto --dir <repo>
```

Both branches receive the read-scoped GitHub environment. OpenCode does not receive a
runner-owned permission configuration.

The installed OpenCode is 1.18.18. Its `run --help` output describes `--auto` as
dangerous because it approves permissions that are not explicitly denied.

## OpenCode permission mechanism

The current official [OpenCode permission documentation](https://opencode.ai/docs/permissions)
states that explicit `deny` rules still apply under `--auto`. OpenCode supports:

- global and tool-specific `allow`, `ask`, and `deny` actions;
- ordered wildcard rules, with the last matching rule winning;
- `bash` rules matched against parsed commands;
- one `edit` permission covering write, edit, and patch operations; and
- `external_directory` rules for paths outside the working repository.

The official [configuration documentation](https://opencode.ai/docs/config/) places
inline `OPENCODE_CONFIG_CONTENT` after project config and `.opencode` directories in
the normal precedence order, but configuration is deep-merged rather than replaced.
Later scalar values win without moving an existing permission key, so inline policy
alone is not a trustworthy isolation boundary. Managed system configuration remains
higher precedence.

`--pure` disables external plugins and is available on the installed CLI, but it does
not disable target `{tool,tools}/*.{js,ts}` modules. OpenCode 1.18.18 also supports
`OPENCODE_DISABLE_PROJECT_CONFIG=true`, which suppresses target project config,
instructions, agents, and components. Version 1.18.18 separately scans
`Global.Path.home/.opencode`; its `OPENCODE_TEST_HOME` hook is needed to point that
loader at the same clean per-run root without changing `HOME`. Combining both roots
with `--pure`, scrubbed inherited overrides, and runner-owned inline policy is the
smallest supported configuration-isolation boundary found here.

The final model-free contract resolves the effective agent against isolated XDG and
legacy-home roots. It confirms that the installed 1.18.18 binary accepts the policy,
retains the ordered `edit`, `external_directory`, `bash`, and `task` rules, and does
not execute seeded target or inherited-home custom tools.

## Threat-model discrepancy

Issue #250 says the skill directory must be unwritable. The current Claude policy
denies `Edit`, `Write`, and `NotebookEdit` for that path, but it also allows
`Bash(*)`. The merge hook blocks merge commands only. A shell command can therefore
target the skill directory despite the native editing-tool denials.

OpenCode can reproduce the native editing-tool boundary with `edit` and
`external_directory` rules. Reproducing it would create backend parity, but it would
not prove the issue's absolute “no writes” wording. Enforcing that absolute invariant
requires a stronger boundary, such as OS-level isolation, or a shell policy narrow
enough to impair the build workflow. Both exceed the issue's stated scope.

## Candidate approaches

1. **Match and name the existing floor.** Inject runner-owned OpenCode permissions,
   retain `--auto`, add `--pure`, and define the skill guarantee as denial through
   native editing tools. Record same-user shell access as residual risk shared by both
   backends.
2. **Disable OpenCode until hard isolation exists.** Fail before launch. This is the
   strongest immediate safety posture but removes a supported backend.
3. **Strengthen both backends in this issue.** Add OS-level or comprehensive shell
   containment. This conflicts with the bounded scope and would become a host-design
   project rather than backend parity.

Les approved approach 1 on 2026-08-18. The design therefore names the native-tool
boundary precisely and carries same-user shell access as an explicit residual risk.

## Live denial evidence — 2026-08-18

The reusable probe ran these commands:

```text
make backend-permission-probe BACKEND=claude EVIDENCE_DIR=/tmp/agent-sessions-issue-250/claude
make opencode-policy-contract
make backend-permission-probe BACKEND=opencode MODEL=opencode/big-pickle EVIDENCE_DIR=/tmp/agent-sessions-issue-250/opencode-isolated-proof
```

Claude Code 2.1.235 completed successfully. Its raw stream shows the native `Read`
tool returning the read marker, the native `Write` tool receiving a directory-scoped
permission denial, and the exact `gh pr merge --help` Bash call receiving a
permission-rule denial. The protected marker remained byte-for-byte unchanged and
stderr was empty.

OpenCode 1.18.18 completed successfully with the explicitly selected installed
`opencode/big-pickle` model. Its raw stream shows the native `read` tool returning
the marker, the native `edit` tool receiving a rule-based denial, and the exact
`gh pr merge --help` call receiving a rule-based denial. The protected marker
remained byte-for-byte unchanged and stderr was empty.

The first OpenCode attempt used the host default and stopped before a tool call with
Google Vertex `invalid_grant` / `invalid_rapt`; this host has no OpenCode-managed
credential. Selecting the installed OpenCode-hosted model isolated the permission
test from that unrelated application-credential failure.

### Live-found OpenCode path mismatch

The first authenticated OpenCode probe exposed a real policy defect: the protected
edit succeeded even though `opencode debug agent build` showed the absolute deny
rules in the resolved policy. OpenCode's permission-evaluation log supplied the
missing boundary detail:

- `external_directory` evaluated
  `/private/tmp/agent-sessions-issue-250/opencode-retry/skill/*`; but
- `edit` evaluated
  `private/tmp/agent-sessions-issue-250/opencode-retry/skill/protected-marker.txt`.

OpenCode 1.18.18 strips the leading slash from the `edit` resource while retaining it
for `external_directory`. A model-free `opencode --pure debug agent build --tool
edit` call proved that adding the stripped-path deny blocks the same temporary edit.
The runner now emits both canonical and stripped edit patterns. A focused regression
test failed before that change and passed afterward; the final live probe then denied
both edit and Bash operations.

### Adversarial target-policy and executable-config review

A final adversarial check added an `opencode.json` to the temporary target repository
that allowed edits globally and on the default `build` agent. OpenCode appended the
target's agent-specific allow after the runner's global denials, so the target could
weaken the mandatory floor even though the inline configuration loaded later.

A first repair repeated the permissions on a fixed `agent-session` primary agent, but
independent review found that target config could still deep-merge the agent, preserve
permission-key order, set `disable: true` and trigger default-agent fallback, delegate
to an unprotected subagent, or execute a project custom-tool module outside native
permission checks. The mocked command-boundary test could not detect those semantics.

The corrected runner disables project configuration discovery, scrubs inherited
OpenCode config and permission overrides, points both XDG and the legacy home loader
at a clean per-run root, selects a random per-run agent with `disable: false`, and
denies `task`. The repeatable
`make opencode-policy-contract` gate seeds same-name disable and permission-reordering
attempts plus executable target and inherited-home `.opencode/tools` fixtures.
Against OpenCode 1.18.18 it resolved the exact runner agent, retained the
task/edit/Bash denials, and did not load either custom tool. The final model probe under
`/tmp/agent-sessions-issue-250/opencode-isolated-proof/` recorded both denial events
as structured summary fields and preserved the marker.
