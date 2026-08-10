# Operator's guide

How to actually run this, what the results mean, and what to do when a run goes sideways.

For *why* it works this way, see [design.md](design.md). For the traps, see
[findings.md](findings.md).

---

## Part 1 — Running the skill by hand

The skill lives at `skills/agent-session/` and is **not installed** as a registered skill. You
run it by pointing a Claude Code session at a mode's phase file. Modes take an explicit
argument; the dispatcher will not guess one from vague phrasing.

### The normal path for one issue

**1. Spec it.** `intake` interviews you — one question at a time, always with a recommended
answer, so you're ratifying rather than facing a blank page. It researches the codebase itself
instead of asking you factual questions.

What it's driving toward: every requirement reduced to a **criterion plus a named check**. Not
*"the export should be faster"* but *"WHEN a user exports over 10k rows THE SYSTEM SHALL stream
the file"*, checked by a specific test that you can run.

Two things it will refuse to do, and both refusals are the point:

- It won't accept a check whose test harness doesn't exist yet. If the check needs a fixture or
  corpus that must first be *built*, the issue is `needs-review` — because the oracle isn't
  there to be trusted yet.
- It won't accept a check that already passes. A criterion describes work not yet done, so its
  check must **fail today**. One that passes cannot tell "done" from "untouched."

Output: the issue is filed or updated with criteria, guards, a tier, and a hidden
`<!-- agent-session:spec -->` marker. **Your original text is preserved verbatim.**

**2. Do it.** `express` runs the whole back half unattended: freeze, plan, implement, verify,
PR. Or drive it in stages with `plan` → `execute` → `pr` if you want checkpoints.

**3. Merge it.** You do this. See [the merge gate](#the-merge-gate).

### Doing a whole backlog

`triage` is the batch form. It fans out one read-only agent per issue, each of which assesses
the issue, proposes criteria, and **runs every check it proposes** so you know which ones
actually discriminate. Then you ratify in one fast pass and it writes back.

Expect a low conversion rate. Across two real corpora, most issues came out `needs-review` —
which is the mechanism working, not failing.

### Criteria vs. guards

Worth knowing because it's easy to conflate:

- A **criterion** says what the work must *newly make true*. It must **fail** before the work.
- A **guard** says what the work must *not break*. It must **pass** before the work.

Guards don't affect the tier. They exist to catch one specific cheat: making a criterion go
green by deleting the coverage that contradicted it, which leaves every criterion passing and
the suite green. Only a guard notices.

### What a run leaves behind

A session directory under `docs/dev-sessions/<timestamp>-<slug>/`:

| File | What it is |
|---|---|
| `spec.md` | the spec, including recorded design decisions |
| `plan.md` | the plan, Phase 0 being the freeze |
| `checks.md` | **the frozen manifest** — criteria copied verbatim with stable `C1…Cn` ids, the freeze commit sha, and an append-only `Amendments` section |
| `notes.md` | the account of the run and what it found |

`checks.md` is the important one. It's the contract.

---

## Part 2 — The freeze, and why you can't edit it

Before any implementation, the checks are written down and committed. That commit is the
**freeze**. From then on, for the rest of that run, the frozen files are read-only.

If a frozen check turns out to be genuinely wrong — a typo'd path, a renamed fixture, an
assertion that doesn't match its own criterion — there are two paths:

**Clarification** — the wording never matched its own intent, and fixing it changes what passes
nowhere. Logged, no tier change.

**Amendment** — it changes what a check *asserts*. Stop, get a human to confirm, log it in
`checks.md`, and **downgrade the run to `needs-review`.**

The test is mechanical: **re-run both wordings against both trees** — the freeze commit *and*
the current implementation. If any verdict changes at either, it's an amendment.

Both trees matter, and the reason is not obvious. At the freeze commit the work doesn't exist,
so *almost any* real check fails there — including a replacement deliberately shaped to fit the
implementation. So the freeze tree only tells you the new check still has teeth. Only the
implementation tree asks *did swapping this change whether the work passes*, which is the
question the downgrade exists to ask.

Note what's deliberately **not** sufficient: *"the check never matched its intent."* That's a
story always available to whoever wrote the check — and that whoever is the implementer.

---

## Part 3 — The merge gate

`pr` ends by deriving a verdict from a fixed list of conditions and writing a machine-readable
block into the PR body. It never merges.

| Verdict | Meaning |
|---|---|
| `eligible-for-auto-merge` | every condition satisfied. **A finding, not an instruction.** |
| `human-merge-required` | at least one condition needs a person |
| `pending` | the run didn't get far enough to grade. **Not actionable** — don't read it as either. |

The conditions include: every criterion passing *by name*, guards passing, a clean tamper diff
against the freeze commit, local project gates green, **CI green on the pushed head**, no
unresolved review threads, tier `auto-ok`, and no risk-gated paths touched.

Two subtleties that were learned the hard way:

- **Review threads are only resolved if the run fixed what they raised.** An agent that can
  resolve threads it merely disagrees with makes the "no unresolved threads" condition
  self-satisfiable, and therefore meaningless.
- **The CI condition is a claim about a commit.** If the head moves after CI was graded, the
  verdict rests on code that no longer ships, and the driver reports `ci-stale`.

---

## Part 4 — Running the driver

The driver picks eligible issues and runs `express` on them unattended.

```bash
make dry-run      # selection only — no agent invoked, no cost
make run          # one issue
make loop         # up to two
make check        # the driver's own test suites

make dry-run-self # selection against this repo's own board
make run-self     # drive this repo (ISSUE=n to pin one)
```

Override the target with `REPO=`, `REPO_PATH=`, `BOARD=`; the per-issue ceiling with `BUDGET=`;
queue depth with `ISSUES=`.

### The driver's own GitHub account

**The driver does not use your credentials, for reads or for writes.** It runs under a machine
user you create for it, with two fine-grained PATs on that one account:

| Variable | Where it lives | What it is |
|---|---|---|
| `DRIVER_GH_LOGIN` | `.env` | the account both tokens must belong to |
| `AGENT_GH_READ_TOKEN` | `.env` | read-only PAT — Metadata, Contents, Issues, Pull requests, Actions, Checks |
| `DRIVER_GH_WRITE_TOKEN` | **your shell, never `.env`** | write PAT — Contents, Issues, Pull requests |

The agent gets the read token and cannot write to GitHub at all. It records the writes it wants —
comments, labels, the branch push, the PR — into `writes.jsonl` in the run directory, and the driver
validates that file and performs them with the write token after the run ends.

**All three are required and there is no fallback.** The driver refuses to start if any is missing,
if the two tokens are identical, or if either token turns out to belong to somebody other than
`DRIVER_GH_LOGIN` — checked against a live `gh api user`, once per token, before anything is spent.
A successful start prints the account it resolved:

```
identity: acting as your-agent-account (agent reads, driver writes)
```

Two failure modes that check catches, both of which are silent otherwise:

- **A missing `DRIVER_GH_WRITE_TOKEN`** — an unexported variable, or a cron with a clean
  environment. The old behaviour was to fall back to your `gh` keyring, which meant the driver's
  commits and comments arrived under your name.
- **The wrong token in a slot** — a personal PAT pasted into the read variable. Invisible without
  asking GitHub whose token it is.

### Where to keep the write token

Three ways, best first. The driver reads a **user-level credentials file** at
`${XDG_CONFIG_HOME:-~/.config}/agent-session/credentials.env` (override with
`DRIVER_CREDENTIALS_FILE`), loaded after `.env` so project settings still win. It must be mode
`0600` or the driver refuses to start.

**1. A command, with the secret in your keychain.** Any credential variable can be supplied as
`<VAR>_CMD` instead — the driver runs it and takes stdout. The command is not a secret, so it can
live in either config file:

```bash
# once, interactively — the value never reaches your shell history if you let it prompt
security add-generic-password -s agent-session-write -a "$USER" -w

# ~/.config/agent-session/credentials.env  (chmod 0600)
DRIVER_GH_WRITE_TOKEN_CMD=security find-generic-password -s agent-session-write -w
```

Works the same with `op read op://vault/item/field`, `pass show ...`, or anything else that prints
a token. Run without a shell, so a config file is not a code-execution surface.

**2. The credentials file, holding the token directly.** Durable, out of shell history, outside any
repo, `chmod 0600`. Plaintext on disk.

**3. `export DRIVER_GH_WRITE_TOKEN=...`** — fine for one-off runs; it ends up in `~/.zsh_history`
or a dotfile.

The driver **refuses to start if it finds any write-capable variable** (`GH_TOKEN`, `GITHUB_TOKEN`,
`GH_ENTERPRISE_TOKEN`, `GITHUB_ENTERPRISE_TOKEN`, `DRIVER_GH_WRITE_TOKEN`) in a config file inside
the repo the agent works in. A `.env` from before #191 usually holds `GITHUB_TOKEN`; move it out.

### What the credential split does and does not contain

Worth being exact, because the refusal above is easy to over-read.

**It does contain the GitHub API.** The agent's token is read-only, so `gh issue comment`, `gh pr
merge` and `git push` over HTTPS are refused by GitHub regardless of what the agent decides to run,
how it phrases it, or whether it is being cooperative. That is the property a tool allowlist could
not give, and it holds.

**It does not contain the local machine.** The agent runs as your user with a shell. It can read
`~/.zshrc`, `~/.config/agent-session/credentials.env`, your `gh` keyring — anything you can read.
No storage location on this host hides the write token from it. There is exactly one asymmetry, and
it is small: on macOS a process's environment is not visible through `ps`, even to its owner, so a
token that exists only in the driver's environment is not readable that way. That is a side effect
of the platform, not a design.

So the `.env`-inside-the-repo refusal, and the `0600` check, are **hygiene**: they stop the token
being committed, backed up, or left in the directory the agent is already working in. They are not
a wall.

The wall would be a separate uid, a container, or a different machine — none of which this project
has. Until then the honest statement is: *the agent cannot act on GitHub as anyone but its own
read-only self, and a determined agent on this host could still find the driver's token.* Those are
different claims and only the first one is enforced.

**`git push` is only covered on HTTPS remotes.** `GH_TOKEN` reaches git through the `gh` credential
helper, which fires for HTTPS only; on an SSH origin the host key authenticates and the agent can
push regardless. The driver says so at startup when it sees one.

The manifest vocabulary has no entry that merges a PR or enables auto-merge, so "nothing merges by
machine" holds even if a run decides to try.

### What "eligible" means

Open **and** carries the marker **and** its anchored `## Tier:` line says `auto-ok` **and** no
open PR references it **and** it doesn't carry the `driver-parked` label.

Every one of those is read from GitHub, which is the point: selection consults **no local state**,
so it answers the same way on any machine. The park bit used to be the exception — a gitignored
`parked.jsonl` relative to cwd, append-only with no un-park record, so it was both per-machine and
wrong about every issue it named (#5).

The board column is **advisory** — it's reported but doesn't gate. That's deliberate: the column
answers *does a human want this*, the marker answers *can this be attempted unattended*, and on
a real board those two sets can have an empty intersection.

`dry-run` prints one line per excluded issue *with its reason*, because a queue read that yields
zero must say why — otherwise "no work available" and "my query is broken" look identical.

### Outcomes

| Outcome | Meaning | Parked? |
|---|---|---|
| `gate-eligible` | reached `eligible-for-auto-merge` | no |
| `gate-human` | reached `human-merge-required` | no |
| `ci-stale` | the gate's CI row describes a commit that's no longer the head | no |
| `incomplete` | verdict still `pending` — the run stopped early | yes |
| `no-gate` | a PR exists but carries no gate block | yes |
| `parked` | no PR was opened | yes |
| `failed` | the run genuinely failed | yes |
| `budget-exhausted` | ≥95% of budget spent with no verdict | **no** — and it stops the loop |
| `driver-fault` | the invocation never reached the agent | **no** |

Parking **adds the `driver-parked` label** to the issue; reaching a verdict (`gate-eligible` or
`gate-human`) **removes** it. So a parked issue is skipped by future selection until either a later
run reaches a verdict, `--retry <n>` ignores the label for one invocation, or you take the label off
by hand — which you can do from the issue page, because the state is visible there rather than
buried in a state file.

`budget-exhausted` and `driver-fault` are deliberately never parked: both are recoverable
configuration problems, and parking would hide them behind a skip reason on a perfectly good
issue. `budget-exhausted` also stops the loop, because the next issue would inherit the same
too-small ceiling.

**Neither terminal verdict controls flow.** `gate-eligible` and `gate-human` both mean *record
it and move on*. Only budgets and failures stop the loop.

### When a run dies

The driver writes `inflight.json` **before** invoking, so an interrupted run leaves evidence.
Everything else it writes, it writes afterwards — which is why that marker exists at all.

- **The run finished but the driver died before recording:** `--classify-only <n>` recovers the
  outcome from live PR state. No agent invocation, no cost.
- **The child is still alive** (a host crash can reparent it and leave it running *and
  spending*): startup detects a live orphan and refuses to start a second run. Kill it or wait,
  then `--classify-only`. Scoped to the repo, and not by comparing repos — the state directory is
  one per repo (see below), so another repo's run does not read this marker at all.

Those two states need opposite actions, which is why conflating them was the original bug.

### Where the state directory is

**One directory per repo**, so runs against two repos never collide:

```
${XDG_STATE_HOME:-$HOME/.local/state}/agent-session/<owner>-<name>/
```

The driver logs the resolved path at startup — read that line rather than reconstructing it.
`--state-dir <path>` overrides it and is used **exactly as given**, with no repo subdirectory
appended; two runs handed the same explicit path will collide at the orphan guard, which is
correct, because one `inflight.json` cannot describe two runs.

A cross-repo view of the ledger is one glob:

```sh
cat "${XDG_STATE_HOME:-$HOME/.local/state}"/agent-session/*/runs.jsonl | jq -r '[.issue,.repo,.outcome] | @tsv'
```

`./.driver-state/` in this checkout is the **pre-#27 archive** — every run before the default
moved. It is never written again and is kept deliberately; several figures in
[findings.md](findings.md) rest on it.

### Per-run artifacts

Under `<state-dir>/runs/<issue>-<timestamp>/`:

| File | What it is |
|---|---|
| `stream.jsonl` | the full agent transcript — large |
| `final.txt` | the run's closing summary |
| `gate.yaml` | the gate block as parsed |
| `prompt.txt` | exactly what the run was asked |
| `writes.jsonl` | the GitHub writes the agent recorded, one JSON object per line |
| `writes-result.json` | what the driver made of them — validation errors, per-entry status, output |
| `denials.txt` | permission denials, if any |
| `child.pid` | for orphan detection |

`writes-result.json` is the first thing to read when a run "did nothing": a manifest with one
malformed entry applies **none** of them, so a park comment can go missing while the run itself
looks fine. The driver prints `WRITE REJECTED` and folds the reason into the `runs.jsonl` row, but
the per-entry detail is here.

Plus two append-only logs in the state dir, both **history rather than state**:

| File | What it is |
|---|---|
| `runs.jsonl` | one record per run — outcome, cost, session id, PR. Supplies the skip line's reason. |
| `parked.jsonl` | one record per park *event*. Nothing reads it; selection reads the label. |

That distinction is the fix in #5. Every `parked.jsonl` line was true when written — *at time T,
issue N was parked* — and the bug was reading an append-only history as current state.

---

## Part 5 — Gotchas that will bite you

The full list is in [findings.md](findings.md). The ones most likely to matter on day one:

- **A nonzero exit does not mean the run failed.** A stream can carry a successful result *and*
  a trailing error record. The gate block is the oracle; the exit code isn't.
- **Never `git add -A`.** A run leaves a worktree in the repo root. This has gone wrong twice,
  once reaching another project's `main`. Stage explicit paths.
- **Permission denials are triggered by shell *syntax*, not command names** — output redirects
  and control flow, not un-allowlisted binaries. You can't fix them by adding names to the
  allowlist.
- **Driving this repo requires `--allow-nested-skill-dir`**, because the skill directory sits
  inside the repo. `make run-self` passes it.
- **Read column names off the board, never from a doc.** `gh project create` produces
  `Todo / In Progress / Done`; the templates produce `Backlog / Ready / In progress / In review /
  Done`. Casing differs too.

---

## Part 6 — What this deliberately won't do

- **Merge anything.** Enforced by a deny rule on the merge command, not by good intentions —
  though that rule is prefix-matched, so a `PreToolUse` hook is a precondition for any host
  nobody is watching.
- **Write to its own instructions.** A hosted run gets read access to the skill directory and an
  explicit deny on writing it. An implementer that can edit the rules grading it is the single
  failure this whole system exists to prevent.
- **Touch risk-gated paths unattended.** Authentication, secrets, data migration, CI config,
  dependency changes — plus whatever the project's own `CLAUDE.md` marks off-limits. These stay
  `needs-review` however good the tests are.
