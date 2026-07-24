# GitHub Projects integration

Optional. The skill moves issues across a GitHub Projects v2 board at mode boundaries
(`intake`/`triage` → Ready, session setup → In Progress, `pr` → In Review). It only runs when
the project's `CLAUDE.md` declares the board — otherwise every mode skips this silently.

Moving an issue across the board is *not* the board-driver. The driver (pick the next Ready
issue, run the loop unattended, act on the merge gate) lives above this skill.

## CLAUDE.md schema

Add a section like this to the project's `CLAUDE.md`:

```markdown
## GitHub Project

- **Owner:** `<your-user-or-org-login>` (e.g., `acme-co`)
- **Number:** `<project-number>` (the integer in the board URL, e.g., `5`)
- **Status field:** `Status` (the single-select field used for column tracking)
- **Columns:**
  - `ready: Ready`
  - `in_progress: In Progress`
  - `in_review: In Review`
  - `done: Done`
```

The skill reads these as declarative names and resolves the underlying GraphQL IDs at runtime
— don't hand-write IDs into `CLAUDE.md`, they're noisy and tied to the field schema.

If any of `Owner`, `Number`, `Status field`, or the four `Columns` entries are missing, treat
the integration as not configured and skip all transitions.

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

If the issue isn't on the board yet (common right after `intake` creates it), add it first:

```bash
gh project item-add <number> --owner <owner> --url <issue-url>
```

## Transition command

Single edit, one option at a time:

```bash
gh project item-edit \
  --project-id <project-id> \
  --id <item-id> \
  --field-id <status-field-id> \
  --single-select-option-id <target-option-id>
```

## When each mode transitions

| Mode | Transition | Notes |
|---|---|---|
| `intake` / `triage` | → `ready` | After the issue is created or augmented with criteria + tier. Add to the project first if missing. |
| session setup (`plan` / `express`) | → `in_progress` | After worktree setup, before planning. See `references/session-setup.md`. |
| `pr` | → `in_review` | After the PR is opened. The linked issue is the one referenced via `Closes #N`. |
| (merge) | → `done` | Out of scope — `Closes #N` auto-closes the issue and most boards auto-move to Done on close. |

## When to skip

- No `## GitHub Project` section in `CLAUDE.md` — silent skip, no warning.
- `gh` CLI lacks the `project` scope — surface once with the fix (`gh auth refresh -s
  project`), then skip subsequent transitions this session rather than re-prompting.
- Issue is already at the target column — no-op.
- The mode ran without an issue URL — nothing to transition.

## Failure handling

Project transitions are non-load-bearing. If one fails (network, permissions, board structure
changed), report the failure and continue. Don't block the mode — the skill's job is the
verification loop, not board hygiene.

## Notes on use

- **Declarative names, not IDs.** The CLAUDE.md schema uses human names so it survives schema
  changes; the agent re-resolves IDs each session.
- **Resolve once, reuse.** ID resolution is the slow part of Projects API work. Cache in
  memory for the session; don't hit the API per transition.
- **One-time setup helper.** First-time CLAUDE.md authoring: run `gh project list --owner
  <owner>` for the number and `gh project field-list` to confirm column names, then paste the
  resolved names in.
