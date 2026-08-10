# The write manifest

**You cannot write to GitHub. Record what you want written instead.**

Under the board-driver your `gh` credential is read-scoped (issue #191). Every read
works — `gh issue view`, `gh pr view`, `gh pr checks`, `gh api graphql` queries. Every
write is refused by the API, and retrying, re-authenticating or reaching for `curl`
will not change that. This is deliberate: an agent that *cannot* merge is contained in
a way an agent that has been *told not to* is not.

So you record the writes, and the driver performs them with its own credential after
your run ends.

## How

Append one JSON object per line to the file named in `$AGENT_SESSION_WRITES`. The
driver also states the path in your prompt.

```bash
cat >> "$AGENT_SESSION_WRITES" <<'JSON'
{"kind": "issue_comment", "issue": 42, "body": "Parked: two readings of the requirement."}
{"kind": "label", "issue": 42, "add": ["agent-session:needs-human"]}
JSON
```

One object per line, appended. Do not rewrite the file — you will drop entries you
recorded earlier in the run.

**A write you do not record does not happen.** There is no fallback path and nothing
infers your intent from your final report. Record the entry at the moment you would
have run the `gh` command, not at the end when you are summarising.

## Rules the driver enforces

- **Unknown kinds are rejected**, and a manifest with *any* invalid entry applies
  *none* of them. One malformed line loses the whole run's writes, so get the shape
  right the first time.
- **Every write is pinned to the driver's own repo and board.** There is no `repo`
  field; adding one is an error.
- **There is no kind that merges a PR or enables auto-merge.** Reporting the gate
  verdict is the end of your job, as it always was.
- **`push` cannot target `main`, `master` or `trunk`**, and is never a force push.
- Execution runs in the order you recorded, and **stops at the first failure** — so
  record `push` before the `pr_create` that references the branch.

Results land in `writes-result.json` in the run directory.

## Kinds

| kind | required | optional |
|---|---|---|
| `issue_comment` | `issue`, `body` | — |
| `issue_body` | `issue`, `body` | — |
| `issue_create` | `title`, `body` | `labels` |
| `label` | `issue`, and at least one of `add`/`remove` | — |
| `label_create` | `name` | `color` (hex triplet), `description` |
| `push` | `branch` | — |
| `pr_create` | `head`, `title`, `body` | `base` (default `main`), `draft`, `labels`, `reviewers` |
| `pr_edit` | `pr`, and at least one of `add_label`/`remove_label`/`add_reviewer` | — |
| `project_item_add` | `url` | — |
| `project_item_edit` | `project_id`, `item_id`, `field_id`, `option_id` | — |

`add`, `remove`, `labels`, `add_label`, `remove_label` and `add_reviewer` are lists of
strings. `issue` and `pr` are positive integers.

The authoritative list is `KINDS` in `src/agent_sessions/driver/writes.py`, with one
worked example per kind in `EXAMPLES` alongside it. Read those if this table and the
code disagree.

## Worked example: opening a PR

```bash
cat >> "$AGENT_SESSION_WRITES" <<'JSON'
{"kind": "push", "branch": "feat/191-read-scoped-token"}
{"kind": "pr_create", "head": "feat/191-read-scoped-token", "base": "main", "title": "driver: contain the agent by credential", "body": "Closes #191\n\n## Merge gate\n\n```yaml\nverdict: pending\n...\n```\n", "labels": ["agent-session:gate"], "reviewers": ["copilot-pull-request-reviewer"]}
JSON
```

Note the labels and reviewers ride on `pr_create`. **Never try to `pr_edit` a PR the
same manifest created** — you do not know its number until the driver has made it, and
a guessed number edits somebody else's PR.
