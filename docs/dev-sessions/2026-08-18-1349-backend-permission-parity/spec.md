# Safety: define permission parity for non-Claude agent backends

Source: <https://github.com/lmorchard/agent-sessions/issues/250>

## Goal

Every supported agent backend must receive the same mandatory permission floor at
the process boundary. A backend whose adapter is absent, unsupported, or unable to
construct that floor must fail before the agent process starts.

This change establishes parity between Claude and OpenCode. It does not claim that
either backend provides operating-system isolation from a same-user shell.

## Approved threat model

The harness owns four invariants for every supported backend:

1. The child receives the read-scoped GitHub credential and no write-capable GitHub
   credential.
2. The backend's native command policy denies the destructive command families that
   the Claude runner already protects: PR merge, force push, and repository deletion.
   OpenCode must also deny the merge command families covered by Claude's
   `PreToolUse` merge hook.
3. The skill directory remains readable, but the backend's native edit, write, and
   patch tools may not modify it.
4. Mandatory rules are runner-owned. Target-repository OpenCode configuration is not
   loaded, and caller options may not replace or weaken the floor.

The current Claude runner allows `Bash(*)`. OpenCode must retain a general shell to
perform repository work. A same-user shell can therefore attempt direct filesystem
writes outside either backend's native edit tools. That is an accepted, shared
residual risk. Proving that the skill directory is unwritable through every process
requires OS-level isolation and belongs in a separate host-security design.

The system-managed OpenCode configuration is part of the trusted host boundary. It
has higher precedence than runner-supplied inline configuration. An administrator
who changes that managed configuration is changing the host, not acting through a
target repository or an agent run.

## Architecture

`agent_runner` will keep backend-specific adapters at the process boundary. Each
adapter returns the command, standard-input payload, and environment additions needed
to enforce the approved floor. Output parsing, model selection, timeouts, progress,
and cost extraction remain unchanged.

### Claude adapter

The Claude adapter preserves the restored contract:

- `--permission-mode dontAsk`;
- the immutable default allowlist;
- immutable destructive-command denials;
- native `Edit`, `Write`, and `NotebookEdit` denials for the resolved skill path;
- the runner-owned settings file containing the merge-block hook; and
- caller-supplied denials appended after the mandatory rules.

The implementation may extract this existing command construction into a small
adapter function, but must not broaden the allowed tools or weaken a denial.

### OpenCode adapter

The OpenCode adapter will:

- retain `--auto`, because OpenCode still enforces explicit `deny` rules in that
  mode;
- add `--pure` so external plugins cannot alter tool behavior;
- construct a runner-owned JSON policy in memory;
- disable project configuration discovery, replace any inherited
  `OPENCODE_CONFIG_CONTENT`, strip inherited config-path and permission overrides,
  and point both XDG and OpenCode's legacy home loader at a clean per-run root; and
- keep `--dir` pointed at the target repository.

The inline policy will use OpenCode's ordered, last-match-wins rules:

- `edit`: allow normal repository work, then deny the resolved skill path;
- `external_directory`: deny external paths by default, then allow the resolved
  skill path so the agent can read its instructions; and
- `bash`: allow normal commands, then deny the destructive command families named
  in the approved threat model; and
- `task`: deny delegation because OpenCode 1.18.18 does not propagate the selected
  agent's configured mandatory policy to subagents.

OpenCode deep-merges named agents, and a missing or disabled selected agent falls back
to the default. The runner will therefore generate an unpredictable agent name per
run, set `disable: false`, define the mandatory policy globally and on that primary
agent, and select it explicitly. Project configuration is disabled rather than
trusted to narrow the policy: target `opencode.json`, `.opencode` agents, and
executable custom tools do not load. Managed system configuration and the host user's
selected backend executable remain trusted host boundaries. The version-specific
`OPENCODE_TEST_HOME` hook points the legacy `~/.opencode` component loader at the
clean root without changing the child process's `HOME`.

Path rules must cover the skill directory itself and its descendants. Command rules
must cover both the bare command and commands with arguments. The implementation will
derive the OpenCode rules from one named mandatory policy rather than duplicating
security literals across command construction and tests.

The adapter targets the installed and verified OpenCode 1.18.18 behavior exactly.
Before constructing the agent command, the runner will resolve `opencode` once to an
absolute path, read that executable's version with a short timeout, and parse it
strictly. Missing, malformed, or different versions return configuration error 2
before `subprocess.Popen` starts the agent. Supporting any new version requires
updating the adapter, model-free contract, and live evidence; it must not silently
inherit the old policy.

### Caller options

The current `--allowed-tools` and `--disallowed-tools` options are Claude syntax and
remain Claude-only. Supplying either option with the OpenCode backend will return
configuration error 2 rather than pretending that a Claude rule was translated.
OpenCode caller-level policy customization is outside this issue.

## Failure handling

Policy construction and backend validation happen before output files are opened for
the agent process. Expected configuration failures write one clear error to the
requested stderr path and return 2. They include:

- unsupported or unparseable backend version;
- failure to execute the backend version probe;
- backend-specific options supplied to the wrong backend; and
- failure to serialize a valid mandatory policy.

No configuration failure may call `subprocess.Popen`. Runtime launch failures retain
the existing return code 1 behavior, and timeouts retain 124.

## Verification

### Automated tests

Command-capture tests in `driver/test_agent_runner.py` will assert the complete
process-boundary contract for both backends:

- Claude's immutable allowlist and denials remain intact;
- OpenCode receives `--auto`, `--pure`, the resolved repository directory, the
  explicitly selected runner-owned agent, and the exact runner-owned inline policy;
- both child environments contain the read-scoped GitHub credential and omit every
  write-capable credential;
- inherited OpenCode config paths, inline policy, and permission overrides cannot
  enter the child environment;
- project configuration discovery is disabled and both OpenCode user-component roots
  are clean and per-run;
- delegation is denied until OpenCode offers an independently enforceable subagent
  boundary;
- the version gate accepts only the verified version and rejects missing, malformed,
  different, and timed-out versions while launching the same absolute executable;
- every rejected configuration returns 2 without calling `subprocess.Popen`.

The `make skill-readonly` target will cover the native skill-editing boundary for both
backends. Existing parser, success-detection, model, timeout, and cost tests remain
unchanged except where their command-capture fixture must supply a verified version.

`make opencode-policy-contract` is the model-free feature gate for the installed
supported binary. It seeds a target with same-name agent disable/reordering attempts
and executable custom-tool fixtures in both the target and an inherited adversarial
home, then verifies exact-agent resolution, delegation denial, edit denial, Bash
denial, and the absence of custom-tool execution. It remains outside `make check`
because OpenCode is not a repository dependency.

### Live denial evidence

Before the implementation is considered complete, each installed backend will run a
harmless probe against a temporary repository and temporary skill directory. The
probe will:

1. read a marker from the skill directory, proving required access remains available;
2. attempt a native edit of another marker in that directory, which must be denied and
   leave the file unchanged; and
3. attempt the harmless `gh pr merge --help` form from a denied destructive command
   family, which must be rejected by the backend before `gh` runs.

The session notes will record the installed backend versions, exact commands, relevant
denial output, and final filesystem state. A live probe is evidence for human review,
not a networked test added to `make check`.

The required local checks are:

```text
uv run pytest -q driver/test_agent_runner.py
make skill-readonly
make opencode-policy-contract
make check
```

## Acceptance criteria

- **C1 — human judgment.** A reviewer SHALL approve this backend-independent threat
  model and the recorded live denial evidence for Claude and OpenCode. Documentation
  or option names alone are insufficient.
- **C2 — runnable.** Command-capture tests SHALL assert the complete backend policy and
  read-scoped child environment for Claude and OpenCode:

  ```text
  uv run pytest -q driver/test_agent_runner.py
  ```

- **C3 — runnable.** An unsupported backend adapter or backend version SHALL return 2
  before `subprocess.Popen` is called. The named tests SHALL live in
  `driver/test_agent_runner.py` and run under C2's command.
- **G1 — runnable.** The native skill-editing denials SHALL remain intact for both
  backends:

  ```text
  make skill-readonly
  ```

- **G2 — runnable.** Backend stream parsing, success detection, and the repository
  gate SHALL remain green:

  ```text
  make check
  ```

## Out of scope

- OS-level sandboxing or proof against arbitrary same-user shell writes;
- OpenCode 2.x policy support;
- a public policy-plugin interface or repository-wide policy file;
- runner distribution to another repository or a new host;
- new agent backends; and
- changes to output parsing, orchestration, routing, model choice, or cost accounting.

## Tier

`needs-review`. This is authorization and containment work on an unlisted shipping
`src/**` path, and C1 requires a human to ratify the live evidence.

## Related work

Issue #152 owns the general policy-from-code question. Issue #195 owns distribution
to a second repository. Issue #3 owns the GHA host. A future host-security issue should
own OS-level isolation if the accepted same-user shell risk becomes unacceptable.
