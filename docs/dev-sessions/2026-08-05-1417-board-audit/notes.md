# Board audit session notes

## State at the authentication pause

- Worktree: `/Users/lorchard/devel/agent-sessions/.worktrees/feat-board-audit`
- Branch: `feat/board-audit`
- Approved design: `876976a docs: specify the project board audit`
- Approved plan: `cc24285 docs: plan the project board audit`
- Phase 1: `9be7868 Phase 1: classify board audit findings`
- Phase 2: `d8b3d3d Phase 2: read GitHub state for board audit`
- Reviewed Phase 2 fix: `1c3aa04 fix: translate gh launch failures`
- Phase 3 local wiring: `a84781e Phase 3: expose the live board audit`

Phase 1 passed its task review without findings. Phase 2's first review found that a missing or
unexecutable `gh` binary raised `OSError` outside the operational-failure path; `1c3aa04` added a
red-green regression and the scoped re-review approved it. Phase 3's committed Make/test change
passed its task review without findings.

Fresh controller verification after Phase 2 reported 59 board-audit tests and 184 aggregate Python
tests passing. The Phase 3 implementation report records 60 board-audit tests, `make check` green,
the aggregate Python suite passing, and the Bash driver fixture suite passing. Rerun `make check`
before final handoff rather than treating these historical results as current.

## External blocker and safety state

`gh auth status` reports that the active `lmorchard` token is invalid and recommends:

```text
gh auth login -h github.com
```

The live detector failed closed with `board fields query failed: unknown owner type`. Direct field
and item reads returned the same owner error. No project, field, option, or item ID was accepted as
evidence, and **no GitHub write was attempted**. Issues #12 and #88 were not mutated.

## Cold-resume sequence

1. After Les re-authenticates, run `gh auth status` and require a valid active `lmorchard` account.
2. Run `make board-audit` before any write. Continue only if its strict findings are exactly closed
   #58 and #62 outside `Done`, plus closed #71 with no status. If the live set differs, stop and put
   the evidence to Les.
3. Resolve the project, Status field, `Done` option, and the three item IDs from fresh reads. Do not
   reuse IDs from earlier context.
4. Move only project Status metadata for #58, #62, and #71 to `Done`.
5. Rerun `make board-audit`; require exit 0 with warnings only. Do not close #12 or change #88.
6. Finish the unchecked Task 3 boxes, then execute Task 4, the whole-branch review, and branch
   handoff.

The controller has modified `plan.md` with verified checkbox evidence and created this `notes.md`;
both are intentionally uncommitted until final verification.

## 2026-08-05 authentication resume

Les refreshed GitHub authentication. The restricted sandbox still reported the old invalid-token
state, but the approved network-capable check confirmed the active `lmorchard` keyring credential
and the required `project` / `repo` scopes.

The first authenticated live audit then failed closed before any write:

```text
FAIL: item-list record 18 status must be a string or null
board-audit: scanned 0 issue item(s); 1 failure(s); 0 warning(s)
```

The raw project payload proves that `gh project item-list` omits the `status` key for unassigned
items; it does not emit an explicit JSON null. That shape occurs for three target-repository items:
#71 (closed), #72 (open), and #74 (open). The approved spec says a target issue with no status is a
strict finding, but Phase 2's plan mistakenly required the key to be present with an explicit null.
The parser therefore rejects the live representation before the classifier can enforce the spec.

No GitHub write has occurred. Before resuming implementation, Les needs to confirm that the spec
governs and the parser should normalize an omitted `status` key to `None`. After that reviewed fix,
rerun the audit. The original write authorization still covers only #58, #62, and #71. #72 and #74
need an explicit board-status decision; `Backlog` is the likely conservative choice for these open
issues, but it has not been authorized.

Les then authorized the parser correction, #58/#62/#71 → `Done`, and #72/#74 → `Backlog`.
`733b188 fix: normalize omitted project status` implemented the correction test-first; its scoped
re-review approved it, and a fresh controller run reported all 60 board-audit tests passing.

The first complete authenticated audit produced eight strict findings, not the five expected:

- approved already: #58 and #62 closed in `In review`; #71 closed with no status; #72/#74 open with
  no status;
- newly surfaced: #19 closed in `Backlog`; #60 and #77 closed in `Ready`.

It also produced contextual warnings for title drift on #3 and #88, plus #12 `In review` without an
open closing PR. Per the plan's exact-set gate, no project status was changed. A new decision from
Les is required before expanding the writes to #19/#60/#77 → `Done`.

Les authorized the expansion: #19/#60/#77 may also move to `Done`. The complete write allowlist is
therefore #19/#58/#60/#62/#71/#77 → `Done` and #72/#74 → `Backlog`. Warnings #3/#12/#88 remain
read-only observations.

The resumed Phase 3 worker verified the exact eight-item strict set, resolved fresh IDs, and issued
exactly eight successful project Status edits:

- #19/#58/#60/#62/#71/#77 → `Done`
- #72/#74 → `Backlog`

No issue/PR content, labels, comments, titles, other fields, or other items were changed. The first
post-write audit noticed newly added #96 without status and stopped; the worker did not touch it. An
independent controller rerun moments later found #96 at `Backlog`, assigned by another process, and
reported 25 audited items, zero failures, and warnings only for #3/#12/#88. Phase 3 is therefore
complete without expanding this session's write set.

## Final verification and handoff — 2026-08-05

### Committed implementation

- `876976a docs: specify the project board audit`
- `cc24285 docs: plan the project board audit`
- `9be7868 Phase 1: classify board audit findings`
- `d8b3d3d Phase 2: read GitHub state for board audit`
- `1c3aa04 fix: translate gh launch failures`
- `a84781e Phase 3: expose the live board audit`
- `733b188 fix: normalize omitted project status`

### Fresh evidence

- `git diff --check origin/main...HEAD` and the equivalent check over the unstaged session
  documents both exited 0.
- `make check` exited 0: the Python suite reported **185 passed in 14.59s**; the Bash driver
  fixture suite reported **113 passed, 0 failed**; the remaining aggregate checks completed.
- The read-only `make board-audit` exited 0. It scanned 25 issue items with no strict failures.
  Its current contextual warnings were:
  - #3 project title differs from the issue title.
  - #12 is `In review` without an open pull request that closes it.
  - #88 project title differs from the issue title.

The scan count and wording above are session evidence, not a maintained claim about the live board;
rerun `make board-audit` whenever the current state matters.

### Scope and safety review

The complete committed diff from `origin/main` changes only `Makefile`, the new audit module and
its tests, and this session's `research.md`, `spec.md`, and `plan.md`. The final session-artifact
commit adds only `spec.md`, `plan.md`, and `notes.md`. No changes touch `.github/`, `skills/`,
`driver/gate.py`, or `driver/agent-session-driver.sh`.

The detector's four `gh` calls are read-only: `project field-list`, `project item-list`, `issue
list`, and `pr list`. The final source review found no `item-edit`, item-add/archive/delete, issue
or PR editing, REST mutation, or `--fix` path. `board-audit` remains outside `make check`.

### External mutations in this session

After fresh live reads and Les's approval, exactly eight project Status metadata edits succeeded:

- #19, #58, #60, #62, #71, and #77 → `Done`.
- #72 and #74 → `Backlog`.

No issue or PR content, labels, titles, comments, fields other than Status, or other project items
were changed. #3, #12, and #88 remain warnings for human judgment. #96 appeared between the
post-write reads and was already `Backlog`; it was not changed by this session.

### Review history

- Phase 1 received an independent task review with no findings.
- Phase 2 review found the `OSError` escape when `gh` was missing; `1c3aa04` added the regression
  and the scoped re-review approved it.
- Phase 3's Make wiring and the omitted-status correction in `733b188` each received scoped
  independent re-review with no remaining findings.
- Final branch review found no scope drift, gated-path change, or write-capable detector command.

### Cold resume / PR handoff

The first check on resume is `git status --short`: it should be clean after the session-artifact
commit. Before opening or updating a PR, compare `git diff --check origin/main...HEAD` and
`git diff --stat origin/main...HEAD`, then rerun `make check`. Run `make board-audit` separately
when a fresh live-board observation is needed; its warnings are observations, not authorized fixes.

## Final-review fix — 2026-08-05

The final reviewer found that `parse_board_items` treated every non-`Issue` item other than
`DraftIssue` as unsupported. GitHub Projects permits `ProjectV2ItemContent` to be a `DraftIssue`,
`Issue`, or `PullRequest`, so a valid pull-request card broke an audit specified to inspect issue
items only.

`fix: ignore project pull request items` changes the explicit out-of-scope set to `DraftIssue` and
`PullRequest`; malformed content and unknown types still fail closed. The test-first fix adds a
pure mixed-card regression, an unknown-type control, and a shipped CLI-stub regression containing
a complete pull-request card. The focused suite was RED with `AuditError` for `PullRequest`, then
GREEN after the parser change; the full board-audit test file and `make check` also passed.

The separate read-only live `make board-audit` exited 0 with no strict failures. Its current
warnings were title drift for #88, title drift for #3, and #12 in `In review` without an open
pull request that closes it. This final fix made no external writes.

## Final handoff verification — 2026-08-05

The scoped re-review approved the pull-request-card fix with no new findings. A fresh controller
run of `make check` passed: the Python suite reported **188 passed**; the Bash driver fixture suite
reported **113 passed, 0 failed**; the park-state suite reported **48 passed, 0 failed**; and the
remaining aggregate checks completed. `git status --short` and `git diff --check
origin/main...HEAD` were clean before this notes update.

The first authenticated live audit then caught new board drift: closed issue #65 remained in
`Backlog`. After Les explicitly approved that single metadata change, its project Status was moved
to `Done`. A direct read confirmed the new value, and the subsequent read-only audit exited 0:
19 issue items scanned, no strict failures, and the same contextual warnings for #3, #12, and #88.

This brings the session's project Status edits to nine: the eight listed above plus #65 → `Done`.
No other external state was changed.

## Post-PR rebase — 2026-08-05

PR #100 initially reported a merge conflict after `main` advanced to include several other merged
branches. The only textual conflict was in `Makefile`: current `main` had added `watch-self` to
`.PHONY`, while this branch added `board-audit` at the same line. The resolution retains both
targets; no production Python or test code conflicted.

After rebasing onto current `origin/main`, `make check` exited 0: the Python suite reported **199
passed**; the Bash driver fixture suite reported **111 passed, 0 failed**; the park-state suite
reported **48 passed, 0 failed**; and all aggregate checks completed. `git diff --check
origin/main...HEAD` exited 0. The separate authenticated `make board-audit` also exited 0 with 19
issue items scanned, no strict failures, and the same contextual warnings for #3, #12, and #88.

The first post-rebase GitHub Actions run then exposed a platform-specific test-harness defect.
`test_make_board_audit_binds_this_repository` ran `make -n board-audit` from inside `make check`;
GNU Make on the Linux runner wrapped the dry-run command with nested `Entering directory` and
`Leaving directory` lines, while the local Make did not. The production target was correct, but
the test compared all stdout tokens exactly and failed on the wrapper text.

The CI log supplied the RED case. The focused fix invokes Make with `--no-print-directory`, keeping
the exact command assertion while suppressing platform-dependent nesting chatter. The focused test
passed, followed by a fresh successful `make check` with the same post-rebase suite results above.
