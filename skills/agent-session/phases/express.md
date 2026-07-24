# express

Consume a specified issue autonomously: setup → plan → execute → PR → stop at the merge gate.

The interactive front end is `intake`, not this mode. Express assumes the spec already exists
and trusts it — so its first job is to confirm that assumption instead of papering over it.

**The tier sets the autonomy.** Reads `references/session-setup.md`,
`references/frozen-checks.md`, and the `plan` / `execute` / `pr` phase files in sequence.

## Inputs

- GitHub issue URL (argument)
- Project context: `CLAUDE.md`, board config if any

## Outputs

- Everything the chained modes produce: worktree, session dir, `checks.md` + freeze commit,
  `plan.md`, code, commits, PR
- The PR URL and the **gate verdict** + reason — the primary consumable output
- What was fixed, skipped, deferred, or amended along the way

## Phase 0: Preconditions

Fetch the issue. Three checks, in order — each is a stop, not a warning:

1. **Marker.** Does the body carry `<!-- agent-session:spec -->` with criteria that name checks?
   If not, **stop and route to `/agent-session intake <url>`**. There is nothing here to verify
   against, and inventing criteria now would mean the implementer authored its own oracle.
   Don't run a brainstorm to fill the gap — that's intake's job and it's human work.

2. **Readiness.** Run the readiness checklist from `references/spec-template.md` against the
   issue's spec. A spec that fails the gate can't be executed autonomously; route to `intake`.

3. **Size.** The tier says whether the work is *safe* unattended; it says nothing about whether
   one run can *finish* it. A well-specified XL issue spanning several subsystems is still a bad
   express fit — **push back and recommend `plan` + `execute` interactively**, rather than
   proceeding because express was asked for.

Then read the **tier** from the spec's Tier section (authoritative; the label is an index) and
state it, its reason, and what it means for this run before starting.

## Phase 1: Setup

Run `references/session-setup.md` in full, autonomously: branch, worktree, session directory,
`spec.md` from the issue, board → `in_progress`. Report the paths and continue.

## Phase 2: Autonomous run

Announce that autonomous execution is starting, then run these in sequence with a brief status
line at each transition:

| Step | Run | Express override |
|---|---|---|
| 2a. Plan + freeze | `phases/plan.md` | Phase 0 freeze is mandatory — no override |
| 2b. Plan self-review | `plan.md`'s self-review step | Replaces the human plan review: fix and continue |
| 2c. Execute | `phases/execute.md` | Per-phase manual pauses deferred to 2f; per-criterion checks are not deferrable |
| 2d. Independent verification | `execute.md`'s verifier + tamper diff | Never skipped, never self-reported |
| 2e. Rebase + re-verify | `pr.md`'s **Rebase and re-verify** | Must precede 2f — a pre-rebase diff hides your changes among upstream's and corrupts both self-review and squash |
| 2f. Branch self-review | `pr.md`'s **Self-review** section | Catches what the bot reviewer misses |
| 2g. Tamper check, squash, open PR | `pr.md`'s **Squash and open** | Tamper check runs *before* the squash destroys its baseline; board hook runs here |
| 2h. Review cycle | `pr.md`'s **Review cycle** | Always run; don't wait for confirmation |
| 2i. Merge gate | `pr.md`'s **Merge gate** | Report the verdict and stop |

## What the tier changes

Everything above runs either way — a PR is reversible, so producing one unattended is safe even
for `needs-review`. What the tier changes is where the run **surfaces to a human**:

- **`auto-ok`** — run straight through 2a–2i without stopping. Report the gate verdict.
- **`needs-review`** — same run, plus a stop at each point the tier's reason implies:
  - *A human-judgment criterion.* Produce its `EVIDENCE TO PRESENT`, then stop and ask the human
    to grade it. Don't grade it yourself and don't record it as pending-and-fine; an ungraded
    judgment criterion means the gate can't close.
  - *A risk-gated path* (auth, secrets, data migration/deletion, deploy/infra/CI, dependency
    changes). Present that part of the diff for human review before opening the PR.
- **Either tier** — an amendment to a frozen check always stops for confirmation, and always
  downgrades this run to `needs-review` (see `references/frozen-checks.md`).

The gate itself is always a stop. `eligible-for-auto-merge` is a finding this mode reports, not
an action it takes.

## When to break out of autonomous mode

- Plan self-review uncovers a design decision the spec doesn't cover.
- A check passes at freeze (the behavior already exists — stale issue, or the check doesn't test
  its criterion).
- A check's oracle no longer exists.
- An `auto-ok` issue turns out to carry a "tune by eye" criterion — subjective feel can't reduce
  to a check, so that's an intake bug, not something to lock in visual defaults for.
- Execute hits a fundamental plan error: wrong API, missing dependency, structural mismatch.
- A frozen check appears to be wrong.
- Self-review finds a bug whose fix would change the spec's intent.

In every case: stop and surface. Asking is cheap; a run built on a wrong foundation is expensive
and, worse, arrives wearing green checks.
