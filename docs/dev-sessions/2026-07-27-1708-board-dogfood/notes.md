# Move 7 — notes

## Step 2 — `skills/` marked risk-gated (done)

Added a **"Risk-gated paths (off-limits to unattended work)"** section to `CLAUDE.md` declaring
`skills/**`. No new mechanism: `acceptance-criteria.md`'s trigger 2 is already
project-configurable and fires on *"anything the project's CLAUDE.md marks off-limits."* No skill
file was touched to achieve the partition, which was the point.

**Verification deliberately routed through the triage fan-out rather than a self-check.** The brief
asks to "confirm the tier falls out rather than being argued into place" — a claim I cannot honestly
test on myself, having just written the CLAUDE.md line. Instead the triage subagents (fresh
contexts, given only `acceptance-criteria.md` and the repo) tier every issue independently. Whether
a skill-touching issue comes back `needs-review` citing trigger 2, unprompted, is the real test.
The scanners were **not** told that `skills/` is risk-gated.

## Step 3 — board + issues (done)

Board: <https://github.com/users/lmorchard/projects/9>. Nine issues filed and added, from the
reconciled roadmap only.

Filed **without** criteria, tier or marker. Supplying those would have left `triage` nothing to do
and made the "second corpus" fake — the corpus has to start in the pre-triage state to measure
anything.

| # | Title |
|---|---|
| 1 | Driver: add a PreToolUse merge-block hook before any unwatched host |
| 2 | Sweep every gate row for evidence adjacent to what it names |
| 3 | GHA host, and a park mechanism that survives a host change |
| 4 | Driver: refuse to run when `--repo-path` contains `--skill-dir` |
| 5 | `parked.jsonl` is append-only with no un-park record, so it lies |
| 6 | `ci-stale` has never fired on a real PR |
| 7 | Get a real multi-phase `execute` run (vehicle: decafclaw #625) |
| 8 | Decide the standing posture for modes that dispatch subagents |
| 9 | Extract gate-block parsing into a Python module its tests import |

### Finding — the skill's column vocabulary does not match GitHub's default board

`gh project field-list 9` returns **`Todo` / `In Progress` / `Done`** — GitHub's default template.
`references/github-projects.md` describes transitioning through **`Ready` → `In progress` →
`In review`**. There is no `Ready` and no `In review` on a default board.

Not blocking here: selection gates on marker + anchored tier and treats the column as advisory, and
this move does no invocation. But **a transition to a non-existent column cannot succeed**, and
every *new* board starts from this template. decafclaw's board was built up by hand over time,
which is why this never surfaced.

The skill already says to read names from `gh project field-list` rather than the doc, so it will
*read* correctly — the gap is what it does when its target state has no matching option. Recorded
rather than fixed; it is a skill-wording question and therefore `needs-review` by the rule this
move just added.

## Step 5 — host-agnosticism, tested for the first time (done)

`agent-session-driver.sh`'s header claims *"deliberately host-agnostic: no `$HOME` assumptions,
every path a flag"* and it had **only ever run against one repo with one board.**

```
make dry-run REPO=lmorchard/agent-sessions BOARD=lmorchard/9
```
```
== select ==
repo lmorchard/agent-sessions: read 9 open issues
board lmorchard/9: read 9 items (advisory only; does not gate)
no issues carry the marker -- nothing for this driver to consider.
dry run -- no claude invocation.
```

**The claim holds for the selection path.** A second repo and a second board resolved with no code
change, both counts printed (the `item-list` truncation lesson applied), and the empty result is
correctly attributed to *no markers* rather than to an empty board — a null reported as a null.

Worth re-running after triage writes markers back: this run exercised selection's *reject*
path only. Seeing it actually surface eligible issues is the stronger test.
