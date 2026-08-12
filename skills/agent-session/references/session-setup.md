# Session setup

Read by `plan` and `express` — whichever mode starts a run from an issue. Establishes the
branch, worktree, session directory, and the spec/tier the run will be graded against.

Shared rather than duplicated in both phase files: two copies of a setup procedure drift,
and a drifted worktree path means a run that tests the wrong branch.

## Outputs

- Feature branch + worktree at the project's worktree location, dependencies installed, baseline
  test status reported (green → proceed; red → surface for the human to decide)
- Session directory at `{base}/{timestamp}-{slug}/` with `spec.md` populated from the issue,
  and `checks.md` / `plan.md` / `notes.md` empty
- The **tier** and its reason, read from the spec and reported

## Process

1. **Determine the session base directory.** Check the project's `CLAUDE.md` for a "Dev
   Sessions" section or a non-default session directory and respect it. Otherwise default to
   `docs/dev-sessions/` — one place to look for session artifacts regardless of which skill
   drove the session.

2. **Look for an existing session to resume.** Search the base directory for the most recent
   timestamped session matching the current branch. If found, read `spec.md`, `checks.md`,
   `plan.md`, and `notes.md`, report the current state, and ask whether to resume or start
   fresh. If resuming, suggest the next mode and stop here.

3. **Fetch the issue and detect the marker.** `gh issue view <n> --json title,body,labels`.
   - **`agent-session:spec` label present** — the issue carries a spec with verifiable
     criteria. Capture the body (strip the marker line and any trailing `_Filed by_` footer).
   - **Marker absent** — the issue has not been through the front of the funnel. It has no
     criteria to verify against, so there is nothing for the back half to grade. **Stop and
     route to `intake`** (see "The marker is the precondition" below).

4. **Read the tier.** Take it from the spec's **Tier** section in the issue body — that is
   authoritative, because it carries the reason. A tier label on the issue is a convenience
   index for querying, not the source of truth. If the label and the body disagree, **stop and
   surface the conflict** rather than picking one; a wrong tier misroutes autonomy in both
   directions.

5. **Branch.** Derive the branch name from the issue (e.g. `fix/129-empty-state`). Strip
   prefixes like `feature/`, `fix/`, `chore/` when deriving the session `{slug}`.

6. **Fetch `origin/main`** without modifying or rebasing the current checkout.

7. **Set up an isolated worktree.** First, determine the worktree location: run `git worktree list` to see if the repo already keeps worktrees somewhere (such as `.claude/worktrees/`, `worktrees/`, or a sibling dir). If an existing location is found, declare this as your explicit worktree directory preference. Prefer `superpowers:using-git-worktrees` with that declared preference if available — it handles directory priority, gitignore verification, dependency install detection, and a baseline test run. Fallback:
   a. **Use the project's existing worktree location.** Use the location found above; only fall back to `.worktrees/` with no precedent.
   b. Confirm it's ignored. If it isn't, put the `.gitignore` line on the feature branch or pick an
      already-ignored location — don't commit setup changes to the default branch.
   c. If an open PR exists for `{branch-name}`, reuse or set up the worktree on that branch, fetch PR details (`gh pr view`) and review comments (`gh api repos/{owner}/{repo}/pulls/{number}/comments`), and proceed to address any unresolved review comments/threads, or pick up from the `Handoff / Parked State` described in the PR body. If no open PR exists but a remote or local branch for `{branch-name}` exists, reuse it and check the issue comments for handoff context. Only if no prior state exists should you start fresh from `origin/main`.
   d. `git worktree add {location}/{branch-name} -b {branch-name} origin/main`
   e. `cd` into the worktree.
   f. Run project setup auto-detected from project files (venv / `npm install` / `go mod download` / `cargo build`).
   g. Run the test suite for a clean baseline. **Report failures rather than proceeding silently** — a red baseline makes every later check ambiguous, since you can no longer tell your failure from the pre-existing one.

8. **Determine Ceremony Threshold.** 
   - **Small/Tactical:** Skip creating a session directory or any markdown files. Track state in-context with `todowrite`.
   - **Large/Architectural:** Create the session directory at `{base}/{timestamp}-{slug}/`, **inside the worktree** (untracked files in the main checkout are not visible from worktrees). Write the captured spec to `spec.md`. Leave `checks.md`, `plan.md`, and `notes.md` empty — `plan` populates `checks.md` at the freeze.

9. **Project board hook.** If a board is configured (`references/github-projects.md`), move
   the issue to `in_progress`. If not, report `board: not configured` in step 10 rather than
   skipping silently — an operator who expects the issue to move can't otherwise tell "no board"
   from "the transition failed."

10. **Report** the worktree path, session directory, and the tier + its reason.

## The marker is the precondition

The back-half modes verify against criteria that were authored *before* implementation by
someone other than the implementer. An issue with no marker has no such criteria, so running
`plan`/`execute` against it would mean the implementer authors its own oracle — the exact
failure this skill exists to prevent.

So: no marker → run `/agent-session intake <issue-url>` first. Do not improvise criteria
here to keep the run moving. (This is the deliberate difference from `dev-session`'s
`express`, which drops into an interactive brainstorm at this point.)
