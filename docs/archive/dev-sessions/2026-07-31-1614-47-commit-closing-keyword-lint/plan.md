# Plan — #47: a commit message that quotes a closing keyword closes the issue

**Issue:** https://github.com/lmorchard/agent-sessions/issues/47
**Tier:** `auto-ok` — both criteria reduce to pytest assertions over text and a real fixture repo;
the work lands in `scripts/` and `Makefile`, both on the drivable allowlist.
**Frozen at:** 945467b. Check file, read-only from Phase 1 onward: `scripts/test_commit_lint.py`.

## Phase 0 — freeze (done)

`checks.md` written, `scripts/test_commit_lint.py` authored by an independent context, both
criteria observed failing for the correct reason, guards observed passing. Commit 945467b.

## Phase 1 — the detector, end to end

**Advances:** C1, C2.

One vertical slice, because the criteria are not separable in practice: C2's entry point is
meaningless without C1's text rule, and C1's rule is untestable at the exit-status level without
C2's range scan. Splitting them would produce a phase whose only deliverable is an unreachable
function.

Write `scripts/commit_lint.py` to the interface the frozen tests declare:

- `scan_message(message) -> [(line, matched_text)]` — pure function over one raw commit message.
  A closing keyword is `close[sd]?` / `fix(e[sd])?` / `resolve[sd]?`, case-insensitive, followed
  by whitespace and `#<digits>`. Reported iff the match falls inside a backtick-delimited span.
- `scan_range(rev_range, repo=None) -> [(sha, line, matched_text)]` — `git log <rev_range>` with
  a record-separated `%H`/`%B` format, one entry per *occurrence*.
- `main(argv=None) -> int` — default range `origin/main..HEAD`; non-zero iff any occurrence.

**Quoting rule, stated precisely** (this is the load-bearing design decision):

- A line whose stripped content starts with three backticks toggles fenced-block state. Every
  match on a line *inside* a fence is quoted. The fence delimiter lines themselves are not scanned.
- Outside a fence, a match is quoted iff it falls inside an inline `` `…` `` span on the same line.
- **Not** implemented, each a deliberate non-feature with a reason:
  - *Four-space-indented blocks.* No delimiter to key on, and indentation in a commit message
    means many things; guessing would cost false positives on ordinary pasted logs. Measured:
    zero in this repo's history.
  - *`~~~` fences.* The criterion says "inside backticks"; `~~~` is not backticks, and a commit
    message is not markdown anyway.
  - *Inline spans crossing a line break.* Line-scoped by construction. The real defect is
    single-line, and an unterminated backtick would otherwise invert every later line.
  - *Global backtick parity* as the mechanism. It happens to give the right answer on all of the
    frozen fixtures, and it is fragile in exactly the way that matters: one stray backtick
    anywhere flips the classification of everything after it, in both directions. A state machine
    that resets per line cannot fail that way.

**Verification:**

- [x] `uv run pytest scripts/test_commit_lint.py` — **22 collected, 22 passed, exit 0.** Not exit 5.
- [x] `python3 scripts/commit_lint.py --all` — **exactly one occurrence**, `2cbe106` line 14,
      `Closes #7`, exit 1. `2cbe106`'s own genuine `Closes #23` is not among them. Guard G1.
- [x] `git diff 945467b -- scripts/test_commit_lint.py` — **empty**. Tamper check clean.

## Phase 2 — wire it into the gate

**Advances:** C2.

Without this, C2's "`make check` exits non-zero with such a commit present, 0 without" has nothing
to exercise, and C1's frozen test never runs in the suite.

- Add `commit-lint` to the `.PHONY` list, to `help`, and as a recipe running
  `python3 scripts/commit_lint.py` — stdlib-only and plain `python3`, matching `docs-check` and
  `assertion-lint` so it stays portable to a GHA runner.
- Add `commit-lint` to the `check` aggregate.
- Add `scripts/test_commit_lint.py` to the `gate-test` pytest invocation.

**Verification:**

- [x] `make check` exits 0 on this branch, ending `all checks passed`, with
      `commit-lint: no quoted closing keywords in origin/main..HEAD`.
- [x] `make check` exits non-zero over a range containing a quoted keyword. Demonstrated by hand
      on a scratch empty commit quoting a reference to a nonexistent issue, then discarded
      (`git reset --soft`; branch restored to `21db545`, working tree untouched). **Both**
      mechanisms fired: `make commit-lint` reported it directly, and `make check` aborted earlier
      still at `gate-test`, because the frozen real-history test also caught it. Also covered by
      the frozen entry-point tests against a throwaway `git init` repo.
- [x] `make gate-test` collects and passes the new file — **85 passed** (63 before).

## Phase 3 — record the finding

**Advances:** none directly. Named so the phase/criteria mapping stays honest rather than padded:
this phase advances no `Cn`, and that is a deliberate exception, not a hole.

`docs/findings.md` already tracks the self-matching defect class the issue names. Append this
instance to the ledger only — no new rule, because the detector *is* the remedy and this project
is 3-for-3 on added rules measuring away.

**Verification:**

- [x] `python3 scripts/docs_check.py` exits 0 (G2) — `links resolve, tables well-formed, counts match`.

## Phase 4 — unplanned: fix what the independent verifier found

**Advances:** C1 (correctness of the rule the criterion names).

Not in the original plan; added because verification found three real defects, two of them false
positives on legitimate commits. Detail in `notes.md`. The fix pairs backtick delimiters instead of
counting parity, at both fence and inline scope.

**Verification:**

- [x] `uv run pytest scripts/test_commit_lint.py scripts/test_commit_lint_edges.py` — **37 passed**
      (22 frozen, unchanged and untouched; 15 new).
- [x] `python3 scripts/commit_lint.py --all` still reports exactly the one known occurrence.
- [x] `make check` green.
- [x] The frozen check file was **not** edited — regressions live in a new
      `scripts/test_commit_lint_edges.py`. Tamper diff re-confirmed empty after the fix.

## Criteria coverage

| Criterion | Advanced by |
|---|---|
| C1 | Phase 1, Phase 4 |
| C2 | Phase 1, Phase 2 |

Both directions: every `Cn` appears in some phase; every phase advances at least one `Cn` except
Phase 3, which is flagged above as a deliberate documentation-only phase rather than left to look
like scope creep.

## Scope discipline

Out of scope, noted rather than fixed:

- **`scripts/test_assertion_lint.py` is not in `gate-test`.** Discovered while reading the
  Makefile: `gate-test` runs `driver/test_gate.py`, `scripts/test_docs_check.py` and
  `scripts/test_run_progress.py`, so `assertion_lint`'s own tests never run under `make check`.
  Issue #47's spec asserts they do. This is a real pre-existing gap and a one-token fix, but it is
  not this issue's work — surface it, don't drive-by it.
- **PR bodies.** Explicitly out per the spec: GitHub renders them, so backticks work there.
- **Rewriting `2cbe106`.** Explicitly out per the spec.
