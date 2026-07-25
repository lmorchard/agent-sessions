# Notes: the board-driver (move 3)

Spec: [spec.md](spec.md) · Plan: [plan.md](plan.md)

## Phase 0 — permission mechanics, measured

Three `claude -p` probes against `/tmp/permtest`, ~$0.50 total. **The oracle was the filesystem,
not the model's own account of what it was allowed to do** — the model reports what it believes
happened, and that belief is exactly what's in question.

| Probe | Result |
|---|---|
| `dontAsk` + `--allowedTools 'Bash(echo:*)'`, run `echo` and `ls -la` | **Both allowed.** `ls` is not in the allowlist and was not denied. |
| Same, plus `--disallowedTools 'Bash(mkdir:*)'`; run `echo`, `mkdir A`, `touch B` | `echo` allowed; `mkdir` denied *by rule*; `touch` denied by *don't-ask mode*. Filesystem confirmed neither `A` nor `B` was created. |
| `--allowedTools 'Bash(gh:*)'` + `--disallowedTools 'Bash(gh pr merge:*)'`; run `gh pr merge 99999 --squash` and `gh --version` | Merge **denied**, `--version` allowed. |

What this establishes, and how it corrects `design.md`:

1. **The agreed floor is real** — `dontAsk` + a scoped allowlist does deny non-allowlisted mutating
   commands. Good: the whole safety story rested on this and it had never been tested here.
2. **But `design.md`'s "denies anything outside allow-rules" needs a qualifier.** `ls` passed. Commands
   Claude Code classifies read-only are auto-allowed regardless of the allowlist. The floor is
   "no unlisted *mutation*", not "no unlisted command".
3. **Deny rules take precedence over allow rules and match multi-word command prefixes.**
   `Bash(gh pr merge:*)` blocks the merge even with `Bash(gh:*)` broadly allowed. This is the
   mechanism behind "nothing merges", and it is a mechanism rather than an exhortation.
4. **Denial messages are distinguishable and greppable** — the rule-specific form names the command
   ("Permission to use Bash with command `<cmd>` has been denied"), the mode-level form does not.
   So the driver can *report* denials instead of stalling silently, which is the failure mode
   `dontAsk` invites.
5. The `Bash(cmd:*)` colon syntax works for both flags, though `--help` writes it `Bash(git *)`.

## Design-time findings

### `--bare` is unusable here

`claude --help` (2.1.220): under `--bare`, *"Anthropic auth is strictly `ANTHROPIC_API_KEY` or
`apiKeyHelper` via `--settings` (OAuth and keychain are never read)."* No key is set on this machine,
so `--bare` fails to authenticate rather than running reproducibly. It also skips CLAUDE.md
auto-discovery, which `express.md` declares as an input.

`design.md`'s capability ladder recommends `--bare` for reproducible CI. That recommendation is
wrong for this host, and — the more useful point — it is *not free* for the GHA host either, since a
keyed GHA runner using `--bare` would lose the CLAUDE.md the skill needs.

### `--max-budget-usd` exists

A real CLI-enforced per-run ceiling, absent from the ladder, which knew only about reading
`total_cost_usd` back out afterwards. Reading it after the fact tells you what you spent; the flag
stops you spending it. The driver uses both.

### `gh project item-list` silently truncates at 30

The board has 185 items. Without `--limit`, the first queue read returned **one** Ready item; with
`--limit 500`, three. No error, no warning — it simply described a smaller board, and I nearly
concluded #585 was not ready.

Same shape as the `clean`-vs-`clean-by-substitute` finding from move 2: **a null rendered as a
negative**. The driver now passes an explicit high `--limit` everywhere and *prints the item count it
read*, so a truncation is visible in the log rather than inferred from an empty queue.

### Board `Ready` and marker+`auto-ok` do not overlap

| Filter | Result |
|---|---|
| Board `Status = Ready` | #450, #667, #668 — **none carry the marker** |
| Open + marker + anchored `auto-ok` | **#585 only** |
| Open + marker + `needs-review` | #625, #566 |
| Intersection | **empty** |

#585 sits in **Backlog**. The handoff's "#585 remains ready" meant *spec-ready*, not *in the Ready
column* — a genuine ambiguity in the word, and it would have produced a driver that reported no work
forever while looking like it worked.

The two signals answer different questions: the **column** answers *does a human want this done*, the
**marker + tier** answers *can this be attempted unattended*. Les's call: marker+tier gates, column
is advisory and the disagreement gets *reported* rather than resolved — consistent with the existing
tier-vs-label rule.

Also observed: #671 read `Ready` on one query and `In progress` a minute later, stable across three
re-reads. Cause unattributed. Consequence regardless: **the board has concurrent actors, so a queue
read is a snapshot, not a claim.**

## Build findings

### The anchored tier match is load-bearing, and the test discriminates

`^## Tier:` anchoring is not tidiness. #585's own tier paragraph reads *"was originally
`needs-review` only because…"*, so an unanchored search finds both tier strings in the body.

Verified by building the unanchored variant and running it on #585's real body: it returns
`conflict`. Unanchored, the driver's very first run would have skipped its only eligible issue as
ambiguous, and the honest-looking report would have been "0 eligible."

Recording the probe because `design.md`'s move-1 lesson applies: *a result is only evidence about a
rule once the instrument can actually fail.*

### The variadic-flag bug — caught before the real run, not during it

`--allowedTools`, `--disallowedTools` and `--add-dir` are all **variadic** (`<tools...>`,
`<directories...>`). A positional prompt after any of them is consumed as another value for the last
variadic option, and the run dies with *"Input must be provided either through stdin or as a prompt
argument."*

The driver put `--add-dir` last, so **every real run would have failed this way.** Found by
verifying stream-json result extraction on a one-word prompt before committing 40 minutes to a real
one. The three permission probes had worked only by accident of ordering — a non-variadic
`--output-format` happened to sit between `--allowedTools` and the prompt.

Fix: the prompt goes in on **stdin**, which is immune to option ordering.

Generalisable: **a flag list that works is not evidence the flag list is right** when one of the
flags is variadic. The cheap guard is to exercise the exact invocation shape on a trivial prompt
first — the smallest possible run of the real command, not a smaller command.

### The hosted run is not hermetic

The verification stream showed a `SessionStart` hook firing and injecting this machine's global
context (the superpowers preamble). That is the price of not using `--bare`, and it is the same
caveat `design.md` already records for micro-tests — *"a clean no-guidance control is unreachable on
this machine"* — now applying to the driver itself.

Not a bug, but it bounds what a local run proves about a GHA run, and it is a second reason the GHA
host is not a free port.

## The four questions

Answered in [spec.md](spec.md). In brief:

1. **Local vs GHA** — a category error: the driver is a script, and local vs GHA is a *host*. Local
   is host #1, GHA gets no code of its own, and it is not built now (re-verification tax wants
   watchable runs; the runner needs decafclaw's whole toolchain; and `--bare` makes the port
   non-trivial regardless).
2. **Queue** — marker + anchored `auto-ok` tier gates; board column advisory; every exclusion
   reported with its reason.
3. **Verdicts** — never control flow. Both terminal verdicts mean *park the PR and move on*; only
   budgets and failures stop the loop. `--max-issues` defaults to 1.
4. **Failures/ceilings** — the exit code is not the oracle (a designed escalation stop also exits 0);
   the PR's gate block is. Park, never retry. `--max-budget-usd` + `timeout` + a local park list.

## Skill wording — one addition, and why it isn't a restatement

The driver's prompt ends with:

> There is no human watching this run. If express directs you to stop and surface something, stop and
> state plainly what needs a decision and why. Do not substitute your own judgment for the decision
> just because nobody is here to answer: a parked issue is a normal, expected outcome for this driver,
> and an unattended guess is not.

Per `CLAUDE.md`'s calibration, I checked whether this restates something already reachable — the trap
that caught the goal-ambiguity tier trigger and the withheld-decision exception, both added from real
failures and then measured away.

`express.md` already ends its escalation list with *"In every case: stop and surface. Asking is
cheap."* So the *concept* is reachable. But the **premise changes**: `express.md` assumes a human is
present to ask, and "asking is cheap" is false when nobody is there. The failure mode this addresses
is specifically the model proceeding *because* asking is impossible — which the existing sentence
does not cover, and arguably invites.

So it is new context rather than a closer restatement. **This is prompt wording in the driver, not
skill wording**, so it is outside the micro-test rule's scope — and `skills/agent-session/` was not
touched at all (guard G1, enforced by `make skill-untouched`).

## The real run against #585

Three attempts, and the two failures were worth more than the success.

### Attempt 1 — driver fault, $0

Died instantly: `prompt.txt: No such file or directory`. The state dir defaulted to the relative
`./.driver-state`, and the invoke stage runs in a subshell that `cd`s to `--repo-path` first, so the
path pointed somewhere else by the time it was read.

The driver's own handling was correct — exit 1 → `failed` → parked → stop the loop rather than
retry. But it exposed something: **`failed` could not distinguish "the run failed" from "the driver
is broken."** Both park the issue, and parking hides a driver bug behind a skip reason on a perfectly
good issue. Now a separate `driver-fault` outcome, discriminated by *no session id and no spend*,
which means the invocation never reached the model. It is never parked.

### Attempt 2 — the run completed, the driver was killed, and $9.44 vanished from the record

98 turns, 19 minutes, **$9.44**, and it got all the way to opening
[PR #699](https://github.com/lmorchard/decafclaw/pull/699). Then the driver process was killed
during the review cycle. Cause unattributed — the kill surfaced *inside* the run as
`[Request interrupted by user for tool use]`, which is how a SIGTERM to the host process appears to
`claude -p`, so the inner run's account of why it stopped is not reliable evidence about the cause.

The damage was entirely in the records: a completed run, real money spent, an open PR, and an
**empty `runs.jsonl`**. Everything the driver writes, it writes *after* classification, so a driver
that dies before classifying leaves no trace of a run that happened.

Three fixes, all from the accident rather than from imagination:

1. **`inflight.json`**, written before the invocation and removed after recording. A leftover one is
   reported loudly on the next startup, with the recovery command.
2. **`--classify-only <n>`** — recover an outcome from live state with no invocation: cost and
   session id from the saved stream, verdict from the PR. This is the by-hand recovery the accident
   forced, made repeatable.
3. The `driver-fault` outcome above.

**What the accident validated for free:** running the recovery gave outcome `incomplete`, because
#699's gate block honestly reads `verdict: pending / reason: review cycle has not run yet`. The
design rule that **`pending` is not actionable** is exactly what stops a driver reading a killed run
as a success. That was a fixture test five minutes earlier; now it has a real case, and the real case
is the one shape I could not have manufactured.

### Guard G2 FAILED — and the guard was right

G2 said decafclaw's local `main` would be unchanged, on the reasoning that express works in a
worktree. It moved: `4f9a426` → `e81f1ba`. Reflog shows `git pull -q --ff-only origin main` at
09:43:36, inside the run.

Not reframing this to pass. Two honest readings, both worth keeping:

- **The risk is low.** It was `--ff-only`, which refuses rather than rewriting when history has
  diverged, and `4f9a426` is an ancestor of `e81f1ba`, so nothing was lost.
- **The guard was still correct to fire**, because the finding is real: **express mutates the host
  checkout, not only its worktree.** On a host whose `main` carries unpushed local commits,
  `--ff-only` *fails* — so express's setup could break for a reason having nothing to do with the
  issue, and the driver would record that as a park with a misleading reason.

And G2 is itself an instance of the defect class `design.md` already names twice — G1's `3234 passed`
and G6's `130→140`: **a brittle absolute encoding a relative invariant.** The real invariant is
"`main` is only ever fast-forwarded, never rewritten," which held. I pinned a sha instead. Third
occurrence of the pattern, first one that was mine.

### The re-verification tax is the norm, not bad luck

`origin/main` moved **twice more** during these attempts, and the branch was one commit behind again
before the resume even started. Combined with #649's three landings, that is **four consecutive runs
paying the tax**. Every landing invalidates the freeze sha and forces a rebase + re-anchor +
re-verify. The re-anchoring machinery held every time, which is the good news; the wall-clock cost is
structural on an active repo, which is the planning input.

### Zero permission denials

Across ~700 stream lines of real work — git, gh, make, uv, pytest, subagent dispatch, PR creation —
the scoped allowlist produced **no denials at all**. The `dontAsk` stall I flagged as the main
operational risk did not materialise. Notably, compound commands pass: `git fetch origin -q && git
log --oneline main..origin/main | head -20; echo ...` was allowed, so the layer evaluates the
constituent commands rather than rejecting any line containing an operator.

That is a better result than I expected and it lowers the cost of the safety floor considerably —
though it is one repo's toolchain, so the allowlist is validated, not proven.
