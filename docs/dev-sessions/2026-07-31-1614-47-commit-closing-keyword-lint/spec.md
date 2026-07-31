<!-- agent-session:spec -->

**Goal:** stop a commit message that *quotes* a closing keyword from closing a real issue.

**Source:** it already happened. **Issue #7 was closed as COMPLETED on 2026-07-31 by accident**, and
nobody noticed until the queue count changed.

## What happened

PR #38's commit `2cbe106` explains why the fix had to be a selection/discovery split. To do that it
describes a frozen test fixture, and that fixture's payload contains the literal text `Closes #7`:

```
the frozen fixture at test-park-state.sh:89 -- `Closes #7`, branch `fix/7-stub`,
```

**Commit messages are not rendered as markdown**, so the backticks are literal characters rather than
quoting. GitHub read `Closes #7` as a closing keyword and closed the issue — which was a real backlog
item (*"Get a real multi-phase execute run, vehicle decafclaw #625"*), not a completed one.

**The two mechanisms disagree, which is what makes it invisible.** `gh` reports PR #38's
`closingIssuesReferences` as `[23]` — the PR never claimed to close #7. Only the commit body did. So
the PR's own metadata, the place anyone would look, says nothing is wrong.

Exposure across all history: **exactly one instance**, this one. Every other `Closes #N` in the log is
a genuine one. (A first pass over the last 40 commits reported clean and was wrong — the offending
commit is 44 back. Scan `--all`.)

## The class

This is the **self-matching shape** this repo keeps hitting, with GitHub as the detector:

- the denial detector counted its own regex — 3 reported, 1 genuine
- `docs-check` flagged `CLAUDE.md`'s own *example* of a stale count, on day one
- issue #19: an issue body that merely *quotes* `<!-- agent-session:spec -->` reads as specced
- **here: a commit body that quotes `Closes #N` closes #N**

Each time, a detector could not distinguish a mention from a claim. The novelty is that this one is
*GitHub's* detector, so we cannot fix the parser — only what we hand it.

## Verifiable acceptance criteria

- **C1.** GIVEN a commit-message body containing a closing keyword inside backticks, WHEN the detector
  runs, THEN it SHALL report that commit; AND GIVEN a body whose only closing keyword is an ordinary
  trailing `Closes #N`, it SHALL NOT report it.
  **CHECK:** `uv run pytest scripts/test_commit_lint.py` — fixtures for both, asserting the quoted form
  is reported and the genuine form is not. The negative case is the load-bearing half: a detector that
  flags every `Closes #N` would fire on every legitimate commit in this repo and be disabled within a
  day, which is what happened to the whole-repo cleanliness idea in #36.
  **DEMONSTRATED FAILING:** no such detector exists — `ls scripts/*.py` shows `assertion_lint`,
  `docs_check`, `run_progress` and their tests, none of which reads a commit message. And the real
  demonstration is #7: the defect shipped, closed a live issue, and `make check` stayed green.
  **ORACLE EXISTS NOW:** `scripts/test_assertion_lint.py` is the pattern — a pure function over text,
  fixtures in `tmp_path`, already run by `make gate-test`.

- **C2.** WHEN the detector runs over the commits on the current branch that are not yet on
  `origin/main`, THEN a quoted closing keyword SHALL fail the check with a non-zero exit.
  **CHECK:** the same test file, plus running the detector over a fixture range; and `make check`
  exits non-zero with such a commit present, 0 without — the shape #28's C3 already proved works.
  **DEMONSTRATED FAILING:** nothing scans commit ranges today.

## Regression guards

- **G1.** Every genuine `Closes #N` in this repo's history stays unreported. Run the detector over
  `--all`: it SHALL report **exactly one occurrence** — the quoted `Closes #7` in commit `2cbe106`.
  Verified 2026-07-31: history carries ten genuine closing references (`#4`, `#5`, `#11`, `#18`, `#20`,
  `#23`, `#36`, plus `#15`/`#16`/`#22` sharing commit `d5bdd30`), and none of them may be reported.
  **The reported occurrence must be distinguishable from `2cbe106`'s own genuine `Closes #23`** — that
  one commit body carries both, so a guard counting flagged *commits* rather than flagged *occurrences*
  passes while the detector fires for the wrong reason. **This is the guard that stops the fix being
  useless**, because the cheap way to green C1 is to flag every closing keyword.

  *(Corrected 2026-07-31 before the run: the original enumeration named seven genuine references and
  missed `#11`, `#15` and `#16`, and counted reports per commit — which `2cbe106` carrying both a
  quoted and a genuine keyword makes non-discriminating.)*
- **G2.** `make check` stays green on a clean history, and `python3 scripts/docs_check.py` exits 0.
  Pass today.
- **G3.** The detector does not flag *itself*. Its own source and tests will contain quoted closing
  keywords as fixtures — `assertion_lint.py` solved the identical problem by scoping what it lints, and
  it is the third time this trap has appeared. Verified today: `assertion_lint` contains its own
  pattern 6 times and reports itself 0 times.

## Tier: `auto-ok`

**Trigger 1 does not fire.** C1 and C2 name specific assertions over text fixtures; the oracle is
pytest, already wired into `make gate-test`, with three in-repo precedents.

**Trigger 2 does not fire.** The work lands in `scripts/` and `Makefile`, both on the drivable
allowlist. Not `driver/gate.py`, not `skills/**`. It writes nothing to GitHub.

## Design decisions

- **Decision:** a detector, not a rule telling authors to escape closing keywords.
  - **Why:** this project is 3-for-3 on added rules measuring away, and the two detectors it shipped
    today (`assertion-lint`, `docs-check`) both caught real defects immediately. An author who is
    quoting a fixture is not thinking about GitHub's parser — that is exactly when a rule fails and a
    check does not.
  - **Rejected:** a line in `pr.md`; and doing nothing on the grounds that it has happened once.
- **Decision:** scan the branch's unmerged commits, not all history.
  - **Why:** history is immutable and already contains the one instance; re-reporting it forever would
    train the operator to ignore the check.

## What we're NOT doing

- **Rewriting `2cbe106`.** The history is pushed and merged; #7 is reopened, which is the actual
  remedy.
- **Trying to make GitHub's parser smarter.** Not ours. Only what we hand it.
- **Covering PR bodies.** GitHub *does* respect backticks there, since PR bodies are rendered — this
  is specific to commit messages, and widening it would produce false positives on every PR body that
  quotes a gate block.

## Open questions

- **What is the safe way to quote one?** `Closes #<!-- -->7` works in rendered contexts but not in a
  commit message. **Default:** the detector's message should suggest rewording — *"the fixture's
  payload includes a closing keyword"* — rather than proposing an escape that does not exist.
- **Should it also catch `#N` bare references that GitHub back-links but does not close?** **Default:**
  no. Those are noise, not damage, and #23's fix already made bare `#N` harmless to selection.
