# GitHub Projects integration

Optional. The skill moves issues across a GitHub Projects v2 board at mode boundaries
(`intake`/`triage` → Ready, session setup → In Progress, `open_pr` → In Review). It only runs when
the project's instruction file (`CLAUDE.md`, or `AGENTS.md` where that is what the project keeps) declares the board — otherwise every mode skips this silently.

Moving an issue across the board is *not* the board-driver. The driver (pick the next Ready
issue, run the loop unattended, act on the merge gate) lives above this skill.

## Instruction-file schema

Add a section like this to the project's instruction file — `CLAUDE.md`, or `AGENTS.md` where
that is what the project keeps. **Read whichever one the project actually has**; naming only one
of them is how a Codex-hosted run ends up unable to see its own board configuration:

```markdown
## GitHub Project

- **Owner:** `<your-user-or-org-login>` (e.g., `acme-co`)
- **Number:** `<project-number>` (the integer in the board URL, e.g., `5`)
- **Status field:** `Status` (the single-select field used for column tracking)
- **Columns:**
  - `ready: Ready`
  - `in_progress: In progress`
  - `in_review: In review`
  - `done: Done`
```

*(The example uses the casing GitHub's own templates ship — lowercase `progress`/`review`. An
earlier version of this file wrote `In Progress` / `In Review` three lines above a warning that real
boards don't use that casing.)*

The skill reads these as declarative names and resolves the underlying GraphQL IDs at runtime
— don't hand-write IDs into the instruction file, they're noisy and tied to the field schema.

**Locate the declaration by content, not by heading.** Projects document their board under
whatever heading they already use (`## Project board`, `## Workflow`, a line in `## Conventions`).
Requiring one exact heading means silently no-opping on a project that documented the same facts
somewhere else — which is worse than having no integration, because it looks identical to working.
Search for a `github.com/users/<owner>/projects/<n>` or `github.com/orgs/...` URL and the column
names near it, not for a fixed section title.

If the owner, number, status field, or column names genuinely can't be determined, treat the
integration as not configured — but **say so once** in the run's report (`board: not configured`).
A silent skip is indistinguishable from a failed transition, so an operator expecting the issue to
move has no way to tell which happened. That confusion is not hypothetical: it's how this gap was
found.

**Read column names from the board, not from the doc.** `gh project field-list` is authoritative;
a hand-written doc drifts. Casing matters — a real board's options were `In progress` / `In review`
where an earlier schema example read `In Progress` / `In Review`, and an exact-match transition
would have failed on it.

### What you will actually find — board vocabularies vary, and not subtly

Measured across six real boards under one account:

| Shape | Status options | Seen on |
|---|---|---|
| **Template** (GitHub's project templates) | `Backlog` · `Ready` · `In progress` · `In review` · `Done` | the three actively-managed project boards |
| **Bare default** | `Todo` · `In Progress` · `Done` | older boards, **and every board created by `gh project create`** |

Two consequences:

- **A CLI-created board does not match this skill's transition vocabulary.** `gh project create`
  applies no template, so a board made that way has no `Ready` and no `In review` — two of the
  three states the skill moves through. Casing differs on the third (`In Progress` vs
  `In progress`).
- **A target column may simply not exist.** That is different from "no board configured," and it
  needs the same treatment: **say so once** rather than attempting a transition that cannot
  succeed. A transition to a non-existent option fails or no-ops, and per the rule above, a silent
  no-op is indistinguishable from working.

So resolve the *option set* before the first transition, not the option you happen to want next —
and if the board is missing states the run will need, report that at the start rather than
discovering it at PR-open.

`gh project field-list` does **not** expose option colors or descriptions; those need GraphQL
(`projectV2.field(name:) { ... on ProjectV2SingleSelectField { options { name color description } } }`).

## ID resolution (once per session)

Projects v2 needs four IDs to move an item: project ID, item ID, field ID, single-select
option ID. Resolve them once, hold in memory:

```bash
# Project ID + status field + option IDs (one shot per session)
gh project field-list <number> --owner <owner> --format json

# Item ID for a specific issue (the project-item ID, not the issue number)
gh project item-list <number> --owner <owner> --format json \
  | jq '.items[] | select(.content.url == "<issue-url>")'
```

**The lookups above are reads, and you can run them. The two operations below are writes, and
you cannot.** Under the board-driver your credential is read-scoped: board mutations go through
the write manifest and the driver performs them after your run. See
`references/write-manifest.md`, which this file previously never mentioned while three other
phases correctly pointed *here* for the details.

If the issue isn't on the board yet (common right after `intake` creates it), record a
`project_item_add` entry:

```json
{"kind": "project_item_add", "url": "<issue-url>"}
```

## Transition

Record a `project_item_edit` entry. Single edit, one option at a time:

```json
{"kind": "project_item_edit", "project_id": "<project-id>", "item_id": "<item-id>",
 "field_id": "<status-field-id>", "option_id": "<target-option-id>"}
```

Both kinds need a board configured on the driver; on a driver started without one they are
rejected rather than silently skipped, so resolve the IDs with the read queries above and record
the entry only when the instruction file declares a board.

## When each mode transitions

| Mode | Transition | Notes |
|---|---|---|
| `intake` / `triage` | → `ready` | After the issue is created or augmented with criteria + tier. Add to the project first if missing. |
| session setup (`plan` / `express`) | → `in_progress` | After worktree setup, before planning. See `references/session-setup.md`. |
| `open_pr` | → `in_review` | After the PR is opened. The linked issue is the one referenced via `Closes #N`. |
| (merge) | → `done` | Out of scope — `Closes #N` auto-closes the issue and most boards auto-move to Done on close. |

## When to skip

- No board declaration findable in the instruction file — skip, and report `board: not configured` once.
  Not a *silent* skip: see "Locate the declaration by content" above.
- `gh` CLI lacks the `project` scope — surface once with the fix (`gh auth refresh -s
  project`), then skip subsequent transitions this session rather than re-prompting.
- Issue is already at the target column — no-op.
- The mode ran without an issue URL — nothing to transition.

## Failure handling

Project transitions are non-load-bearing. If one fails (network, permissions, board structure
changed), report the failure and continue. Don't block the mode — the skill's job is the
verification loop, not board hygiene.

## Notes on use

- **Declarative names, not IDs.** The schema above uses human names so it survives schema
  changes; the agent re-resolves IDs each session.
- **Resolve once, reuse.** ID resolution is the slow part of Projects API work. Cache in
  memory for the session; don't hit the API per transition.
- **One-time setup helper.** First-time authoring: run `gh project list --owner
  <owner>` for the number and `gh project field-list` to confirm column names, then paste the
  resolved names in.
