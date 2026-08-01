# Orientation — what this project is, for someone who just got here

Written 2026-08-01, for an engineer who might work in this repo. It assumes you know GitHub,
CI and [Claude Code](https://claude.com/claude-code), and assumes nothing about this project.

The other docs are written for people who already have the vocabulary. This one supplies it.

---

## The short version

This repo is trying to hand routine project-board work to an AI coding agent without having to
trust the agent's own report that it succeeded. The bet is that you can decide *in advance*,
per issue, whether success will be checkable by something that can't be argued with — and that
this decision is the thing that makes unattended work safe, not any property of the agent.

Two pieces implement that bet: a **Claude Code skill** that runs the per-issue loop, and a
**driver script** that picks issues off a board and runs the skill on them unattended. Neither
one merges anything, ever.

It works, and it is used on itself: much of this repo's own commit history was written by the
system it describes. Every resulting pull request was merged by a human, by hand.

---

## The problem it's built around

Burning down a backlog by hand is the same loop over and over: pick an issue, write a spec, plan
it, do the work, run the tests, open a PR, address review comments, merge. Most of those steps
are tedious rather than hard, and an agent can do them.

Turning an agent loose on a backlog goes wrong in a specific way, though — usually not by
writing bad code. It goes wrong by the agent **deciding it succeeded when it didn't**: writing a
test that passes for the wrong reason, grading its own work, or quietly reinterpreting what
"done" meant partway through.

So the question this repo is organised around is not *can an agent do the work?* It is **how do
we know whether it did?**

## The one idea everything follows from

> An agent is only as autonomous as its verifier is trustworthy.

If "done" can be checked by something unarguable — a test, a lint rule, a command with a
specific expected output — an agent can attempt the issue unattended, because success isn't a
matter of opinion. If the only honest check is *a human looks at it and decides*, then a human
belongs there. That isn't a failure; it's useful information about the issue.

The payoff is that this becomes **a property of the issue, not of the agent**. You can sort a
backlog into "safe to attempt unattended" and "needs a person" before any work starts, and that
sorting falls out of a question you should be asking anyway: *how would we actually know this
was done?*

Two consequences do most of the work in the design, and they're the parts most easily lost:

- **The check has to exist before the work starts, and be frozen.** An agent that can edit its
  own acceptance criteria mid-task has no acceptance criteria.
- **Whoever grades the work can't be whoever did it.** Here the grader is a separate agent with
  no ability to write files, so it structurally cannot fix what it's grading.

---

## The vocabulary

These terms are used everywhere in the other docs, usually without definition. This table is the
one place they're all defined.

| Term | What it means here |
|---|---|
| **oracle** | Whatever decides if the work is correct. A test suite is a strong oracle; "Les looks at it" is a weak one. Most of this project is about moving decisions from weak oracles to strong ones — or admitting when you can't. |
| **criterion** | One acceptance condition, written so it names a specific runnable check. Numbered `C1`…`Cn`. A criterion describes work not yet done, so **its check must fail before the work starts** — one that already passes can't tell "done" from "untouched." |
| **guard** | A check for something the work must *not break*, as opposed to something it must newly make true. A guard **passes** before the work. Guards catch one specific cheat: making a criterion go green by deleting the coverage that contradicted it. |
| **check** | The actual runnable thing a criterion names — a test id, a `make` target, a grep with an expected result. |
| **freeze** | The commit that writes the criteria down, made before any implementation. After it, those files are read-only for the rest of the run, and a `git diff` against the freeze commit is the tamper test. |
| **`checks.md`** | The frozen manifest a run produces: criteria copied verbatim with stable ids, the freeze commit sha, and an append-only amendments log. This file is the contract. |
| **amendment** | Changing what a frozen check *asserts*. Allowed, but costly on purpose: stop, get a human, log it, and downgrade the run to `needs-review`. A merely cosmetic rewording is a *clarification* and is free. |
| **marker** | A hidden HTML comment (`<!-- agent-session:spec -->`) stamped into an issue body once it has been through intake or triage. The working modes refuse to run without it, so an under-specified issue can't be picked up by accident. |
| **tier** | `auto-ok` or `needs-review`, written into the issue body. Derived, not chosen: everything checkable and nothing risky touched → `auto-ok`; any human-judgment criterion *or* any risk-gated path → `needs-review`. It controls **where a run surfaces to a human**, not whether it runs. |
| **risk-gated path** | Code an unattended run isn't allowed to touch: auth, secrets, data migration, deploy/CI config, dependencies — plus whatever the project's own `CLAUDE.md` names. In *this* repo the list is an allowlist, so anything unlisted is gated by default. |
| **gate** | The list of conditions the `pr` mode evaluates at the end of a run, and the machine-readable block it writes into the PR body reporting the result. |
| **verdict** | The gate's output: `eligible-for-auto-merge`, `human-merge-required`, or `pending`. The first one is **a finding the system reports, not an action it takes.** |
| **mode** | One of the skill's six entry points (`intake`, `triage`, `plan`, `execute`, `pr`, `express`). You name the one you want; the skill reads only that mode's file. |
| **driver** | `driver/agent-session-driver.sh` — the loop above the skill that picks an eligible issue, invokes the skill headlessly, and records the outcome. |
| **park** | What the driver does to an issue whose run didn't reach a verdict: adds a `driver-parked` label so future selection skips it until someone or something clears it. |
| **move** | A unit of build history in the older docs ("move 7 did X"). Roughly a work session. Numbering stopped being maintained; treat it as a chronological label, not a scheme. |

---

## What's actually in the repo

Two artifacts with different audiences and different ways of being graded. Conflating them is
what makes "so is this a skill-authoring project?" a confusing question — it's both.

| | `skills/agent-session/` | `driver/` + `Makefile` + `scripts/` |
|---|---|---|
| What it is | the reusable artifact: a Claude Code skill running the per-issue loop | this repo's own automation, the unattended burndown loop |
| Made of | markdown | bash, plus stdlib Python for parsing and classification |
| How you tell it works | micro-tests against a no-guidance control, plus dogfooding | fixture tests and mutation testing |
| Who it's for | any project that installs the skill | only this repo |

The skill is **not installed** in `~/.claude/skills/`. You exercise it by pointing a session at a
mode's phase file. That's deliberate — it keeps the version under test the version in the repo.

Layout worth knowing:

- `skills/agent-session/SKILL.md` — the dispatcher.
- `skills/agent-session/phases/` — one file per mode.
- `skills/agent-session/references/` — the shared engine. `acceptance-criteria.md` and
  `frozen-checks.md` are the two novel ones; the rest are templates.
- `driver/agent-session-driver.sh` — selection, invocation, outcome recording.
- `driver/gate.py` — parses the gate block and classifies the outcome. This is the module that
  decides what a run's result *was*, which is why it's treated specially (see below).
- `scripts/` — repo-health detectors: doc-rot, assertion linting, commit-message linting, a live
  progress reader over a run's transcript.
- `docs/dev-sessions/` — one directory per work session, each with its spec, plan, frozen checks
  and notes. This is the real archaeological record.

---

## How one issue actually flows

**1. Intake.** `intake` interviews you about one issue, one question at a time, always with a
recommended answer so you're ratifying rather than facing a blank page. It researches the
codebase itself rather than asking you factual questions. It's driving toward: every requirement
reduced to a criterion plus a named check. It will refuse a check whose harness doesn't exist
yet, and refuse a check that already passes. Output: the issue is filed or updated with criteria,
guards, a tier and the marker, with your original text preserved verbatim.

`triage` is the batch version — one read-only agent per issue, each proposing criteria and
actually running them, then you ratify in one pass. Expect most issues to come out
`needs-review`. That's the mechanism working.

**2. The work.** `express` runs the back half unattended: freeze the checks, plan against current
code, implement, verify, open a PR. You can also drive it in stages (`plan` → `execute` → `pr`)
if you want checkpoints. The verification is done by a separate agent that never saw the plan and
can't write files.

**3. The gate.** `pr` derives a verdict from a fixed condition list — every criterion passing by
name, guards passing, a clean tamper diff, project gates green, CI green on the pushed head, no
unresolved review threads, tier `auto-ok`, no risk-gated paths — and writes it into the PR body.

**4. Merge.** A human does this. Always, so far, and by design: the deny rule on the merge command
is a mechanism, not an intention.

The driver wraps steps 2–3: it finds an eligible issue (open, marker present, tier `auto-ok`, no
open PR referencing it, not parked — all read from GitHub, no local state), runs `express`, reads
the gate block rather than re-deriving it, and records the outcome. [usage.md](usage.md) has the
full outcome table and the recovery paths.

---

## Where the project actually is

The enumerable facts deliberately don't live in prose here, because in this repo they have rotted
every single time someone tried that. Commands that print the current answer:

```sh
gh project item-list 9 --owner lmorchard          # the backlog
gh pr list --state all --limit 100                # what the system has produced
cat "${XDG_STATE_HOME:-$HOME/.local/state}"/agent-session/*/runs.jsonl \
  | jq -r '[.issue,.repo,.outcome,.cost_usd] | @tsv'   # every run, across repos
make check                                        # is the repo healthy right now
```

The durable claims, which are what you actually want from this section:

**Proven.** Every one of the driver's routing paths has real-run evidence. Its PRs land, and a
human merges each one by hand. It has run against more than one repository, including a
multi-issue loop. The project now tracks its own backlog with its own tooling. Gate parsing and
outcome classification are an importable Python module whose tests import it rather than restate
it — which matters, because an earlier version hand-copied the classifier into the test suite and
the copy silently diverged.

Runs are not cheap and the cost is not tightly bounded: there's a per-issue ceiling (`BUDGET` in
the `Makefile`), and at least one run has come close enough to it to be filed as a bug. If you're
about to turn this loose, read the spend column in `runs.jsonl` first.

**Not proven, and the docs say so:**

- **Conditional auto-merge** (the "phase 3" you'll see referenced) is designed and deliberately
  not built. Nothing merges by machine today.
- **Multi-phase execution with real write-capable implementer subagents.** Every run so far has
  been small. This is blocked on a permission grant that hasn't been given.
- **The `ci-stale` outcome has never fired on a real PR** — fixture tests only.

The honest summary of the shape: the machinery is real and load-bearing, the evidence base is
shallow — young, and almost entirely one person driving a couple of repositories — and the project
is unusually explicit about which of its own claims are unverified. That explicitness is the culture,
not modesty — see [findings.md](findings.md), which is largely a list of times this system fooled
itself.

---

## Things that will surprise you when you start working here

**The risk-gated path list is an allowlist, not a denylist.** A directory that nobody has
classified is `needs-review` by default. This was decided after the partition went stale by
omission twice in two days. Read the list in [../CLAUDE.md](../CLAUDE.md) before assuming
anything is drivable.

**Two paths are off-limits to unattended work for a structural reason, not a stylistic one.**
`skills/**`, because there the implementer's work product *is* the instructions grading it. And
`driver/gate.py`, because it's the code that classifies whether the run succeeded. Everything
else in `driver/`, plus `docs/`, `scripts/` and the `Makefile`, is drivable.

**No document may state a fact a command can print.** Cite the command instead. If you must state
a countable fact, date it, so it becomes history rather than an error. `make docs-check` enforces
the checkable part of this and is in `make check`.

**Don't hand-maintain a state section.** State lives on the board, in `runs.jsonl`, and in the
README's one-paragraph summary. An instruction to keep a status block current is exactly what
produced a status block three sessions stale.

**Rules in prose have a bad track record here — detectors have a good one.** Every
behaviour-shaping rule this project has added and then actually measured has measured away as no
better than no rule at all; the tally and the method are in
[findings.md](findings.md#4-add-then-measure-away--3-for-3). When you're tempted to add a
"remember to…" line, ask whether it can be a check instead.

**Verify before acting on any claim, including this document's.** It's the project's most
repeated lesson and it applies recursively.

---

## Where to read next

Roughly in the order you'll want them:

- [usage.md](usage.md) — the operator's guide. Commands, what each outcome means, what a run
  leaves on disk, how to recover an interrupted one. Read this if you want to *run* it.
- [design.md](design.md) — what the system is and why it has this shape, with the reasoning trail
  preserved. Read this if you want to *change* it.
- [findings.md](findings.md) — the durable lessons: recurring defect classes, what was measured
  and what it showed, and a list of verified command-line gotchas. **Read the gotchas before
  writing any flag list or gate condition** — several are the opposite of what they look like.
- [../CLAUDE.md](../CLAUDE.md) — conventions for working in this repo, and the risk-gated
  partition.
- [prior-art.md](prior-art.md) — survey of related work, with each claim marked verified or not.
- [archive/build-log.md](archive/build-log.md) — chronological account of the early work, closed.
  Read it for the incidents behind the rules, not for state.

Lineage: this is a sequel to a personal `dev-session` skill, which structures *building one
thing*. `agent-session` front-loads the inputs an autonomous loop needs, so the middle can run
unattended with a human only at the two ends where judgment actually lives.
