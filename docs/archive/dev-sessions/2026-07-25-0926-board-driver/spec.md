# Spec: the board-driver (move 3)

The unattended loop that picks the next eligible issue, runs `agent-session express` on it, and
stops at the merge gate. It lives **above** the skill: orchestration that invokes the skill, each
run a fresh context. Nothing in `skills/agent-session/` changes for it to work.

Task brief: [../../handoff-board-driver.md](../../handoff-board-driver.md). State of the skill:
[../../design.md](../../../design.md).

## Non-negotiables

- **Nothing merges.** No `gh pr merge`, no `--auto`, not by the script and not by the run it hosts.
  `eligible-for-auto-merge` is a finding the driver *records*.
- **The driver never derives the gate.** It reads the `<!-- agent-session:gate -->` block from the
  PR body. Re-deriving it would make the driver a second, unvalidated verifier.
- **The driver never writes to an issue or a PR.** Its only side effects are local: a state
  directory and stdout.
- **No skill edits.** If the driver seems to need one, the boundary is wrong.

## Findings that shaped the design

Four things verified at design time that contradicted or extended the brief. Recording them
because three of them would have produced a plausible driver that was quietly wrong.

### 1. `--bare` is unusable on this machine

`design.md`'s capability ladder recommends `claude -p --bare` for reproducibility. `claude --help`
(2.1.220): under `--bare`, *"Anthropic auth is strictly `ANTHROPIC_API_KEY` or `apiKeyHelper` via
`--settings` (OAuth and keychain are never read)."* No `ANTHROPIC_API_KEY` is set here, so `--bare`
would fail to authenticate rather than run reproducibly.

`--bare` also skips CLAUDE.md auto-discovery, and `express.md` declares `CLAUDE.md` as an input
(board declaration, Makefile conventions). So even with a key it would need `--add-dir` to feed the
context back in.

**Decision: no `--bare`.** The ladder entry is corrected in `design.md`.

### 2. `--max-budget-usd` exists

`--max-budget-usd <amount>` (`-p` only) is a real per-run cost ceiling enforced by the CLI. Not in
the ladder, which only knew about reading `total_cost_usd` back out of the JSON afterwards. Reading
it after the fact tells you what you spent; the flag stops you spending it.

**Decision: use both.** The flag as the ceiling, the JSON field as the record.

### 3. `gh project item-list` silently truncates at 30

The board has 185 items. Without `--limit`, the first queue read returned **one** Ready item; with
`--limit 500` it returns three. The truncated read was not an error and printed no warning — it just
described a smaller board.

This is the shape `design.md` keeps finding: a null rendered as a negative. A driver that omits
`--limit` reports a short queue and looks like it is working.

**Decision: every paginated `gh` call passes an explicit high `--limit`, and the driver prints the
item count it read** so a truncation is visible in the log rather than inferred from an empty queue.

### 4. Board `Ready` and marker+`auto-ok` do not overlap

Measured against decafclaw, 2026-07-25:

| Filter | Result |
|---|---|
| Board `Status = Ready` | #450, #667, #668 — **none carry `<!-- agent-session:spec -->`** |
| Open + marker + `## Tier: \`auto-ok\`` | **#585 only** |
| Open + marker + `needs-review` | #625, #566 |
| Intersection of column and marker | **empty** |

#585 — the brief's designated first vehicle — sits in **Backlog**. The brief's "#585 remains ready"
meant *spec-ready*, not *in the Ready column*.

The two signals answer different questions. The **column** answers *does a human want this done*.
The **marker + tier** answers *can this be attempted unattended*. Nobody has been maintaining the
first for spec'd issues, and the second is the skill's own contract. A driver gating on the
intersection would correctly report zero work forever.

Also observed: #671 read `Ready` on one query and `In progress` about a minute later, stable across
three re-reads. Cause unattributed. The operational consequence stands regardless — **the board has
concurrent actors, so a queue read is a snapshot, not a claim.**

## The four questions, answered

### Q1 — local `claude -p` loop vs. scheduled GHA

**Neither is a property of the driver.** The driver is a POSIX shell script whose host dependencies
are `gh`, `claude`, `git`, `jq`. Local is host #1. GHA is host #2 and gets no code of its own.

The GHA host is **not built now**, for three reasons:

1. The re-verification tax is real — `origin/main` moved three times during the single #649 run, once
   into the function under change. Early runs need to be watchable and interruptible.
2. A GHA host must provision decafclaw's whole toolchain (`uv`, node, `make check-js`) plus a token
   that can push branches. That is a separate project with its own failure surface, not a port.
3. **The port is not free anyway.** A GHA host would have an `ANTHROPIC_API_KEY` and so *could* use
   `--bare` — but `--bare` drops the CLAUDE.md that `express` needs. The second host therefore needs
   a different context strategy no matter what, and the cheapest way to learn which context the run
   actually depends on is to run it locally first, without `--bare`, and see.

What keeps the port cheap, as a constraint on the script: no `$HOME` assumptions, every path a flag
or environment variable, no interactive prompts, all mutable state under one `--state-dir`, and
nothing read from the developer's shell profile.

### Q2 — how it reads and filters the queue

**Marker + tier is the gate; the board column is advisory context.**

Eligible = issue is **open** AND body contains `<!-- agent-session:spec -->` AND body has a line
matching `^## Tier: \`auto-ok\`` AND no open PR references it AND it is not parked.

- The tier is read from the **issue body**, which `design.md` already fixed as authoritative; labels
  are a convenience index and decafclaw has no tier labels at all.
- The tier match is **anchored to the heading line**. Unanchored, #585's own prose ("was originally
  `needs-review` only because…") matches both tiers. If a body yields an anchored match for more
  than one tier, the driver **skips and reports the conflict** rather than picking — the same rule
  `design.md` sets for a tier/label disagreement.
- The board column is fetched and **printed alongside each candidate**, including the disagreement
  ("#585: eligible; board column is Backlog, not Ready"). Reported, not resolved.

`select` is read-only and independently runnable via `--dry-run`. It emits **one line per excluded
candidate with its reason**. A queue read that yields zero must say why; otherwise "no eligible
work" and "my query is broken" print identically — which is exactly how finding 3 nearly landed.

### Q3 — what it does with each verdict

**Verdicts do not control flow.** Both terminal verdicts mean the same thing to the driver: the
issue is done as far as the driver is concerned, a PR is open, a human owns it from here. Record and
continue.

Control flow is governed only by budgets and failures:

- `--max-issues N` (**default 1**) — issues attempted per invocation.
- `--max-budget-usd` per run, and a cumulative stop before *starting* another issue.
- `--timeout` per run.
- A run that fails to produce a classifiable outcome stops the loop.

The reasoning: making `human-merge-required` stop the loop conflates *this issue needs a human* with
*the loop should end*. Given the ~1-in-8 conversion rate, a loop that stops on the first one barely
runs. And since nothing merges, `eligible-for-auto-merge` and `human-merge-required` are the same
driver action — park the PR, move on. The distinction is for the human reading the report.

Default of 1 is deliberate for move 3: the definition of done is one issue, and a driver that
attempts more before its classifier has ever been exercised is guessing about its own reliability.

### Q4 — failure and cost ceilings

**The exit code is not the oracle.** `claude -p` exits 0 both when `express` completes and when it
stops for a designed escalation — a readiness failure, a check that passes at freeze, an amendment,
an oracle that no longer exists. Those stops are *specified behaviour*, so they will happen, and the
driver must distinguish them from success without a retry.

Classification order, after every run:

1. **Is there a PR for this issue?** If yes, read `<!-- agent-session:gate -->` from its body.
   - `verdict: eligible-for-auto-merge` → outcome `gate-eligible`
   - `verdict: human-merge-required` → outcome `gate-human`, carrying `reason`
   - `verdict: pending` → outcome `incomplete`. **Not actionable** — `pr-body-template.md` says
     `pending` means the run had not derived the verdict yet.
   - gate block absent → outcome `no-gate`; the PR exists but the interface doesn't.
2. **No PR** → outcome `parked`, reason = the run's final assistant text (its own account of why it
   stopped).
3. **Non-zero exit / timeout / budget-exhausted** → outcome `failed`, with the exit code.

**Park, don't retry.** A designed stop is information, not a transient error. Retrying a readiness
failure produces the same readiness failure and spends money doing it. No outcome triggers a retry.

**Park list.** Parked and failed issue numbers are recorded in the state directory with their reason
and timestamp, and excluded by `select` on later invocations unless `--retry <n>` names one.

The board hook cannot do this job: `github-projects.md` declares project transitions
"non-load-bearing — report the failure and continue," so a driver depending on a column move to
deduplicate would re-pick an issue whenever the transition failed. Local state is load-bearing and
honest about it. The wart: the state is per-machine, so a GHA host starts with an empty park list.
Named here rather than discovered later; the durable fix is a label or column and it is out of scope.

## How "nothing merges" is enforced

Two mechanisms and one stated limit.

1. **The script contains no merge command** — checked, not promised. A self-check greps the driver's
   own source for `gh pr merge`, `pr merge`, and `--auto` and fails if any appears.
2. **`--disallowedTools 'Bash(gh pr merge:*)'`** blocks the obvious call from inside the hosted run.

**The limit:** (2) is prefix-matched, so it is not airtight against `gh api`, a differently-spaced
invocation, or a subagent composing the call another way. The airtight mechanism is a `PreToolUse`
hook, which `design.md`'s ladder notes can hard-block even under `bypassPermissions`. For move 3 —
`--max-issues 1`, a human watching — `--disallowedTools` is proportionate. **The hook is a
precondition for any unwatched host**, and this is the design's one deliberate soft spot.

Note that (2) is also why the driver's prompt says "do not merge" only once. `pr.md` and
`pr-body-template.md` already state it three times between them, and this project has now twice
added a rule that restated something already reachable and then measured it away. The guarantee
should live in the mechanism, not in a fourth restatement.

## Permissions

`--permission-mode dontAsk` with a scoped `--allowedTools`, per the agreed floor. Explicitly **not**
`--dangerously-skip-permissions` / `bypassPermissions`.

The honest characterisation: `express` legitimately needs to run a build, write code, dispatch
subagents, and open a PR, so the allowlist is wide. What it buys is a real floor (no merge verbs, no
tool families `express` has no business using) rather than a tight sandbox.

**The operational risk, named up front:** `dontAsk` *denies* anything outside the allow-rules, so an
incomplete allowlist does not degrade gracefully — the run stalls mid-way on a command nobody
anticipated. The driver therefore captures and reports denials explicitly. With `--max-issues 1` and
a watching human, the first run's denials are the cheapest way to learn the true required set;
guessing the complete list in advance is the more expensive path.

## Interface

```
agent-session-driver.sh --repo <owner/name> [options]

  --repo <owner/name>     target repository (required)
  --skill-dir <path>      agent-session skill directory (required)
  --repo-path <path>      local checkout of the target repo; the run's cwd (required).
                          `express` creates its own worktree inside this, per
                          session-setup.md — the driver does not manage worktrees.
  --issue <n>             skip selection, attempt exactly this issue
  --max-issues <n>        issues per invocation (default 1)
  --max-budget-usd <amt>  per-run ceiling (default 10)
  --timeout <seconds>     per-run wall clock (default 5400)
  --state-dir <path>      run log + park list (default ./.driver-state)
  --board <owner/number>  optional, for advisory column reporting
  --dry-run               run selection only; no claude invocation
  --retry <n>             un-park issue n for this invocation
```

## Outputs

Under `--state-dir`:

- `runs.jsonl` — one record per attempted issue: issue, started/ended, exit code, cost, session id,
  outcome, reason, PR URL.
- `parked.jsonl` — parked/failed issues with reason and timestamp.
- `runs/<issue>-<timestamp>/` — the raw `claude` JSON, the extracted gate block, the final text.

To stdout: the selection report (with exclusion reasons), a status line per stage, and a closing
summary naming each issue's outcome and the total cost.

## Acceptance criteria

Criteria in this project's own sense: each names a runnable check, and each fails today.

**C1 — the driver contains no merge path.**
- CHECK: `make -C . driver-check` (greps `driver/agent-session-driver.sh` for `gh pr merge`,
  `pr merge`, `--auto`) exits 0 and reports zero matches.
- Discriminating: the target does not exist today.

**C2 — `select` finds #585 and explains every exclusion.**
- CHECK: `--dry-run --repo lmorchard/decafclaw` prints `#585` as eligible, prints `#625` and `#566`
  as excluded with reason `tier: needs-review`, and prints the item count it read from the board.
- Discriminating: the script does not exist today.

**C3 — the classifier reads the verdict from the gate block, not the exit code.**
- CHECK: given a fixture PR body containing `verdict: human-merge-required` and `reason: <text>`,
  the classify stage emits outcome `gate-human` with that reason; given `verdict: pending` it emits
  `incomplete`. Run as a unit test against fixture text, not against a live PR.
- Discriminating: the script does not exist today.

**C4 — a real end-to-end run against #585 produces a recorded verdict and no merge.**
- CHECK: after the run, `runs.jsonl` carries one record for 585 with a non-`pending` outcome and a
  PR URL; `gh pr view <n> --json state,mergedAt` shows `OPEN` with `mergedAt` null.
- Discriminating: no such PR exists today.

### Regression guards (pass today; must keep passing)

- **G1:** `skills/agent-session/` is byte-identical to its state at the start of this session —
  `git diff --stat df77e8f -- skills/` empty. Anchored to the session's starting commit, not to
  `HEAD`, since `HEAD` moves as this session commits. The boundary claim is that the driver needs no
  skill change; this guard is what makes that claim checkable rather than asserted.
- **G2:** decafclaw's `main` is not modified by the driver — `express` works in a worktree, so
  `git -C <repo-path> rev-parse main` is unchanged before and after the run.

## Out of scope

- Merging anything, or enabling auto-merge (phase 3 in `design.md`'s rollout).
- The GHA host (Q1).
- A `PreToolUse` merge-block hook — required before an unwatched host, not before this one.
- Driving `intake` or `triage`. The driver consumes marker-carrying issues; producing them stays
  human-initiated.
- Acting on `needs-review` issues. They are excluded by the filter, not routed.
