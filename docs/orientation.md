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
**Python driver harness** that picks issues off a board and runs the skill on them unattended.
A thin Bash launcher preserves the original command-line entry point. Neither piece merges
anything, ever.

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
| **risk-gated path** | Code an unattended run isn't allowed to touch: auth, secrets, data migration, deploy/CI config, dependencies — plus whatever the project's own `AGENTS.md` names. In *this* repo the list is an allowlist, so anything unlisted is gated by default. |
| **gate** | The list of conditions the `pr` mode evaluates at the end of a run, and the machine-readable block it writes into the PR body reporting the result. |
| **verdict** | The gate's output: `eligible-for-auto-merge`, `human-merge-required`, or `pending`. The first one is **a finding the system reports, not an action it takes.** |
| **mode** | One of the skill's six entry points (`intake`, `triage`, `plan`, `execute`, `pr`, `express`). You name the one you want; the skill reads only that mode's file. |
| **driver** | `src/agent_sessions/driver/agent_session_driver.py` — the coordinator above the skill that picks eligible work, invokes the skill headlessly, and records the outcome. `driver/agent-session-driver.sh` is its compatibility launcher. |
| **park** | What the driver does to an issue whose run didn't reach a verdict: adds an `agent-session:needs-human` label so future selection skips it until someone or something clears it. |
| **move** | A unit of build history in the older docs ("move 7 did X"). Roughly a work session. Numbering stopped being maintained; treat it as a chronological label, not a scheme. |

---

## What's actually in the repo

Two artifacts with different audiences and different ways of being graded. Conflating them is
what makes "so is this a skill-authoring project?" a confusing question — it's both.

| | `skills/agent-session/` | Python harness + compatibility, test, and detector assets |
|---|---|---|
| What it is | the reusable artifact: a Claude Code skill running the per-issue loop | this repo's own automation, the unattended burndown loop |
| Made of | markdown | Python, with a thin Bash compatibility launcher |
| How you tell it works | micro-tests against a no-guidance control, plus dogfooding | fixture tests and mutation testing |
| Who it's for | any project that installs the skill | only this repo |

Older design history describes this as a Bash orchestrator plus a Python parser. That language
split is historical: the 2026-08-09 conversion moved orchestration into the Python package and left
the Bash file as a compatibility launcher.

The skill is **not installed** in `~/.claude/skills/`. You exercise it by pointing a session at a
mode's phase file. That's deliberate — it keeps the version under test the version in the repo.

Top-level layout:

- `skills/agent-session/` — the skill: `SKILL.md` (the dispatcher), `phases/` (one file per mode),
  `references/` (the shared engine). Detailed below.
- `src/agent_sessions/driver/` — the unattended loop's Python implementation. Detailed below.
- `driver/` — the Bash compatibility launcher, integration assets, fixtures, and harness tests.
- `src/agent_sessions/scripts/` — the shipping repo-health detectors and progress reader.
- `scripts/` — root-level detector tests and test-support assets. Detailed below.
- `docs/dev-sessions/` — one directory per work session, each with its spec, plan, frozen checks
  and notes. This is the real archaeological record, and it is frozen by design: the content is
  history, not maintained documentation.

### `SKILL.md` and `phases/` — one file per mode

`SKILL.md` is a dispatcher and almost nothing else. It parses the mode argument, reads **only**
that mode's phase file, and refuses to guess when the argument is missing or ambiguous. Modes
never co-reside in context, which is why adding one costs nothing.

Each phase file is worth knowing by what it *refuses* as much as by what it does — the refusals
are where the governing principle actually bites.

| File | What the mode does | What it refuses to do |
|---|---|---|
| `phases/intake.md` | Interviews one request or issue into criteria + checks + guards + a tier, then files or updates the issue | Accept a check whose oracle doesn't exist yet, accept a check that already passes, or fudge a weak check to keep `auto-ok` |
| `phases/triage.md` | Batch version: a subagent per issue proposes criteria **and runs them**, you ratify in one pass, issues are augmented in place | Let a scanning subagent run the full suite (N of them in parallel thrash the machine), or let an unrun check read as verified |
| `phases/plan.md` | Freezes the checks as Phase 0, then plans vertical slices against current code, each phase naming the criteria it advances | Plan against a spec whose criteria are bare prose; write the rest of the plan before the freeze |
| `phases/execute.md` | Implements phase by phase, one commit per phase, ticking a checkbox only from observed output; ends by dispatching the independent verifier | Edit a frozen check to make it pass; skip the independent verification because the diff was small |
| `phases/pr.md` | Rebase, re-verify, self-review, push, open the PR, run the review cycle, derive the verdict row by row | Merge; squash away the freeze commit; resolve a review thread it merely disagreed with |
| `phases/express.md` | Chains plan → execute → pr unattended; its Phase 0 checks marker, readiness and size before starting | Invent criteria for an unmarked issue; take on an XL issue just because `express` was the mode asked for |

`pr.md` carries by far the most scar tissue, and that's instructive rather than incidental:
nearly every paragraph past its gate table is there because some real run reached a wrong verdict
that specific way.

### `references/` — the shared engine

Split front/back, matching the two halves of the loop. Nothing here is a mode; these are the
files more than one mode reads, kept in one place because two copies of a rule drift and a
drifted rule is a correctness bug.

**Front half — making criteria checkable** (read by `intake`, `triage`):

| File | What it holds |
|---|---|
| `acceptance-criteria.md` | **The core of the front half.** The one rule (every criterion names its own verifier); the concrete-test → property → human-judgment escalation ladder; the two tests every check must pass (its oracle exists *now*, and it can't pass without the work); criteria vs. guards; how the tier derives; and the exact `## Tier:` heading format downstream parsers anchor on |
| `criteria-grammar.md` | Syntax reference only: the EARS patterns plus Given-When-Then, and how to pick between them. Both forms exist to force a condition → observable-response shape that maps onto an assertion |
| `spec-template.md` | The spec skeleton, plus the **readiness checklist** that gates on verifiability rather than on placeholders — with a separate variant for an issue augmented in place, since those never had the template's sections to begin with |

**Back half — keeping the checks trustworthy** (read by `plan`, `execute`, `pr`):

| File | What it holds |
|---|---|
| `frozen-checks.md` | **The core of the back half.** The `checks.md` manifest; the freeze procedure, including a read-only check-reviewer asking one question per check (*what could make this green that isn't the work?*); the read-only rule; the independent verifier; the tamper diff; what substitutes when the criteria are commands rather than test files; and the clarification-vs-amendment test with its four-cell table |
| `session-setup.md` | Branch, worktree, session directory, `spec.md` from the issue, and the tier read from the issue **body** rather than its label. Shared by `plan` and `express` so a drifted worktree path can't make one of them test the wrong branch |
| `plan-template.md` | The `plan.md` skeleton: Phase 0 is the freeze, every phase names the criteria it advances, every checkbox cites a check by its exact command |
| `pr-body-template.md` | The PR body skeleton, including a field-by-field spec for the `agent-session:gate` block — this is the schema `src/agent_sessions/driver/gate.py` parses |

**Either half:**

| File | What it holds |
|---|---|
| `documentarian-prompt.md` | How to frame a research subagent so it maps what exists instead of proposing a fix: describe, don't propose; cite `file:line`; answer only what was asked; say plainly when something doesn't exist. Carries the oracle-existence question that feeds the tier |
| `github-projects.md` | Optional board transitions, plus the measured warning that board vocabularies differ — a board made by `gh project create` has no `Ready` and no `In review`, which is two of the three columns the skill moves through |

If you only read two files in this directory, read `acceptance-criteria.md` and
`frozen-checks.md`. Everything else is a template, a syntax reference, or an integration detail.

### `src/agent_sessions/driver/`, `src/agent_sessions/scripts/`, `driver/`, and `scripts/`

| File | What it is |
|---|---|
| `src/agent_sessions/driver/agent_session_driver.py` | Coordinates configuration, credentials, GitHub reads, workspaces, agent invocation, outcome routing, persistence, and reporting |
| `src/agent_sessions/driver/router.py` | Selects issues and routes phases as a pure function over fetched GitHub state |
| `src/agent_sessions/driver/gate.py` | Parses the gate block and classifies the outcome. Importable **so its tests exercise the shipping code** — extraction was the fix for a hand-copied classifier in the test suite that had silently diverged from the driver it was supposed to be testing |
| `src/agent_sessions/driver/writes.py` | Validates the write manifest against a closed kind allowlist, then constructs and executes the permitted write commands |
| `driver/agent-session-driver.sh` | Thin Bash compatibility launcher for the packaged Python coordinator |
| `driver/test_*.py` | The fixture and integration suites for the harness |
| `src/agent_sessions/scripts/docs_check.py` | Doc-rot detector: dead relative links, tables split by prose, stated assertion counts that no longer match the suite, and divergent risk-path policy in the two instruction files |
| `src/agent_sessions/scripts/assertion_lint.py` | Catches presence-grep assertions in harness tests — a `grep -q` for a literal that a *comment* would satisfy just as well as the behaviour |
| `src/agent_sessions/scripts/commit_lint.py` | Catches a closing keyword a commit message only quotes. Commit messages aren't markdown, so backticks don't quote anything, and GitHub closed a live backlog item off a sentence that was merely describing a test fixture |
| `src/agent_sessions/scripts/run_progress.py` | A reader over a run's `stream.jsonl`, so a fifty-minute unattended run isn't a black box. Deliberately a *reader* — letting the run narrate its own progress is the same defect one level up |
| `scripts/test_*.py` | Root-level tests for the shipping detectors, plus test-support code |

The detector modules under `src/agent_sessions/scripts/` exist because written rules had already
failed to prevent the defects they catch. That is the project's most-repeated lesson, in file
form. The shipping modules are default-gated as unlisted `src/**`; their root-level tests and
support under `scripts/` are explicitly drivable.

`make help` lists the targets; `make check` is the aggregate that runs the suites and the
detectors together, and it's the row the merge gate cites as *local project gates*. One boundary
is narrower than its name suggests: `make driver-check` currently checks only the Bash
compatibility launcher. Issue #248 owns the missing shipping-Python coverage.

### The seams — text formats one component writes and another parses

The components are coupled by strings embedded in GitHub artifacts, not by an API. That's what
makes the system work across a headless run, a fresh context and a human's browser tab — and it's
also where the sharpest failures live, because a malformed seam usually looks fine to a reader.

| Seam | Written by | Read by | How it breaks |
|---|---|---|---|
| `<!-- agent-session:spec -->` | `intake` / `triage`, into the issue body | `session-setup`, `express` Phase 0, driver selection | An issue that merely *quotes* the marker reads as specced — a detector can't tell a mention from a claim |
| `## Tier: auto-ok` | `intake` / `triage` | `session-setup`, driver selection | Anchored on `^## Tier:`, token taken from the heading line only. No colon, the token only in the prose beneath, or both tokens on one line each break it a different way. **Exactly one such heading per body** |
| `C1…Cn` ids | `plan`, at the freeze | `plan.md`, the commits, the verifier's report, the PR table, the gate block | Ids must stay stable for the whole run; everything downstream cites them |
| The freeze commit sha | `plan`, re-anchored by `pr` after a rebase | The tamper diff | A rebase rewrites it and a squash orphans it. A baseline absent from `origin` turns the tamper check into a self-report |
| `<!-- agent-session:gate -->` | `pr` | `src/agent_sessions/driver/gate.py`, and humans | The block is machine-readable, so a verdict written before it was derived is one an automated reader can act on. It opens as `pending` for exactly that reason |
| `agent-session:needs-human` label | The driver | The driver's own selection | Selection reads the **label**, not the append-only park log — reading a history as current state was the original bug here |

Agent-requested writes pass through the closed kind allowlist in
`src/agent_sessions/driver/writes.py`. It permits issue comments, bodies, and creation; label
changes and creation; branch pushes; PR creation and edits; and project-item additions and edits.
The manifest has no kind for merging a pull request. The coordinator also performs fixed
operational writes outside that manifest: queue-control labels, board-status updates, distributed
lock refs, and Lab Notebook reports. Those writes are coordinator-owned, not agent-requested.

### The cast of subagents — and what each is deliberately not told

Verifier independence isn't a policy in this system, it's a dispatch pattern. The last column is
the one that matters — what each subagent is *not* given is the mechanism.

| Subagent | Dispatched by | Given | Deliberately withheld |
|---|---|---|---|
| Documentarian | `intake`, `triage`, `plan` | The repo and 3–5 neutral "how does X work today?" questions | The feature being designed — a researcher told the goal starts proposing the fix |
| Triage scanner | `triage`, one per issue | One issue body, the repo, read-only tools, and permission to run **targeted commands only** | Nothing withheld; the constraint here is what it may *run*, not what it may see |
| Check-author | `plan`, Phase 0 | The spec and the criteria | The implementation plan — a test author who's read the plan tests the plan rather than the criterion |
| Check-reviewer | `plan`, Phase 0, **before** the freeze commit | `checks.md` and the repo, with no Edit or Write tools | The plan *and* the criteria's rationale — a reviewer told what the author meant reads each check as that intent instead of as what it literally asserts |
| Implementer | `execute`, one per phase | The plan, and the frozen files named by path as read-only | Nothing; a failing frozen check is a report-back, not a fix-up |
| Verifier | End of `execute`, again in `pr` | `checks.md` and the repo | The plan, the notes, and any account of why a failure might be acceptable — that context is exactly what produces a rationalised pass |

The check-reviewer and the verifier look similar enough to want merging, and merging them would
break the whole thing. The reviewer grades **check against criterion** while no implementation
exists to shape the answer; the verifier grades **implementation against check**, and is
trustworthy precisely because it never saw the plan.

The reviewer also sits *before* the freeze commit on purpose. Up to that moment, strengthening a
weak check is free. After it, the same fix costs an amendment and the run's tier.

---

## How one issue actually flows

The shape, before the detail. Follow the artifacts rather than the modes — each stage's output is
the next stage's contract, and the human appears at exactly two places:

```
  human ──┐                                                        ┌── human
          ▼                                                        ▼
      ┌────────┐   issue body    ┌───────┐  checks.md   ┌─────────┐   PR + gate   ┌───────┐
      │ intake │ ─ marker ─────▶ │ plan  │ ─ freeze ──▶ │ execute │ ─ block ────▶ │ merge │
      │ triage │   criteria      │       │   commit     │   pr    │   verdict     │       │
      └────────┘   tier          └───────┘              └─────────┘               └───────┘
                                     │                       ▲
                                     └── check-author ────────┘
                                         check-reviewer   verifier
                                         (before freeze)  (never saw the plan)
```

`express` is the middle two boxes run end to end without stopping. The driver wraps the same
span and adds selection and outcome recording around it.

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

### What the driver adds around steps 2–3

Four steps, and two of them carry the interesting properties:

1. **Select.** Open, carries the marker, its anchored `## Tier:` line says `auto-ok`, no open PR
   references it, no `agent-session:needs-human` label. Every eligibility field in that list comes
   from GitHub. A dry run prints one line per *excluded* issue with its reason, because a queue read
   that yields nothing has to distinguish "no work available" from "my query is broken."
2. **Invoke** `express` headlessly, writing `inflight.json` *before* the call so an interrupted run
   leaves evidence, and streaming the transcript to disk so `run_progress.py` can report on a live
   run from outside it.
3. **Classify** by *reading* the gate block the run wrote, never by re-deriving the verdict. The
   driver is a recorder here, not a second opinion — which is also why
   `src/agent_sessions/driver/gate.py` is treated as the oracle and kept off-limits to unattended
   work.
4. **Record**, and park anything that didn't reach a verdict by labelling the issue, so future
   selection skips it until a human or a later run clears it.

GitHub holds the mutable queue state: issue and PR state, labels, comments, reviews, checks, and
project fields. The driver also keeps operational artifacts outside that queue. Its state directory
holds `runs.jsonl`, `inflight.json`, per-run transcripts and manifests, and workspaces for provenance
and recovery; distributed issue locks use remote `refs/locks/issue-*`. Local history can explain a
skip or recover a run, but it does not replace GitHub's current queue state.

[usage.md](usage.md) has the full outcome table, the state directory layout, and the recovery
paths for a run that died mid-flight.

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

- **Conditional auto-merge** (the "phase 3" you'll see referenced) is not pursued. The project shifted its objective to maximizing the "attention ratio" — letting the agent do everything up to the merge gate perfectly, so human attention is spent only on hard problems rather than mechanical failures.
- **Multi-phase execution with real write-capable implementer subagents.** (See `make evidence` for actual execution history. Unresolved containment risks remain.)
- **The `ci-stale` outcome fires on real PRs when the PR head diverges from the `ci:` gate row** (verified live in #6).

The honest summary of the shape: the machinery is real and load-bearing, the evidence base is
shallow — young, and almost entirely one person driving a couple of repositories — and the project
is unusually explicit about which of its own claims are unverified. That explicitness is the culture,
not modesty — see [findings.md](findings.md), which is largely a list of times this system fooled
itself.

---

## Things that will surprise you when you start working here

**The risk-gated path list is an allowlist, not a denylist.** A directory that nobody has
classified is `needs-review` by default. This was decided after the partition went stale by
omission twice in two days. Read the list in [../AGENTS.md](../AGENTS.md) before assuming
anything is drivable.

**The called-out boundaries are off-limits to unattended work for structural reasons, not stylistic
ones.** `skills/**`, because there the implementer's work product *is* the instructions grading it;
`src/agent_sessions/driver/gate.py`, because it classifies whether the run succeeded; and
`src/agent_sessions/driver/agent_session_driver.py`, because it routes the result. The compatibility
launcher also remains gated. Only the harness tests and compatibility assets under `driver/**`, plus
`docs/`, root-level test and support assets under `scripts/**`, and the `Makefile`, are explicitly
drivable. Shipping detectors under `src/agent_sessions/scripts/` remain default-gated, as does every
other unlisted `src/**` path. Read the partition in [../AGENTS.md](../AGENTS.md) before assuming a
path is drivable.

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
- [../AGENTS.md](../AGENTS.md) — conventions for working in this repo, and the risk-gated
  partition.
- [prior-art.md](prior-art.md) — survey of related work, with each claim marked verified or not.
- [archive/build-log.md](archive/build-log.md) — chronological account of the early work, closed.
  Read it for the incidents behind the rules, not for state.

Lineage: this is a sequel to a personal `dev-session` skill, which structures *building one
thing*. `agent-session` front-loads the inputs an autonomous loop needs, so the middle can run
unattended with a human only at the two ends where judgment actually lives.
