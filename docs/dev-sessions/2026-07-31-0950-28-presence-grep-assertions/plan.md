# Presence-grep assertions: fix the eight, add the detector — Implementation Plan

**Goal:** Remove the eight `grep -q '<literal>' "$DRIVER"` assertions from `driver/test-driver.sh`
and add a detector, wired into `make check`, that keeps the class from coming back.

**Source issue:** https://github.com/lmorchard/agent-sessions/issues/28 — **Tier:** `auto-ok`
(every criterion is a runnable command or a pytest suite whose harness exists; paths touched are
`driver/test-driver.sh`, `scripts/`, `Makefile`, all on CLAUDE.md's drivable allowlist).

**Approach:** Build the detector first and let it land red on the eight real instances — that is
stronger evidence than a synthetic fixture that it finds the actual defect. Then wire it into
`make check`, then fix the eight, then mutation-test the wiring end to end.

**Criteria:** C1 no comment-satisfiable assertion survives in `test-driver.sh` · C2 the detector
reports the presence-grep shape, spares the count-comparison shape, and is clean on the real
`test-park-state.sh` · C3 a seeded violation turns `make check` red.

Full text and checks live in `checks.md`. **Frozen at `48c8104`.**

---

## Phase 0: Freeze the acceptance checks — DONE

`checks.md` written; `scripts/test_assertion_lint.py` authored by a check-author subagent that was
given the criterion and the house pattern but not the implementation approach.

**Verification — automated:**
- [x] C1 fails for the expected reason: reports `8` (want `0`)
- [x] C2 fails for the expected reason: `ModuleNotFoundError: No module named 'assertion_lint'`,
      exit `2` — a collection error, distinguishable from exit `5` (`no tests ran`)
- [x] C3 fails for the expected reason: mutation appended, `make check` still exits `0`
- [x] Guards pass: G1 `88 passed, 0 failed`; G2 `all checks passed`; G3 exit `0`
- [x] Freeze commit `48c8104`; sha recorded in `checks.md` by follow-up `579b0cb`

---

## Phase 1: The detector

Build `scripts/assertion_lint.py` to the interface the frozen test defines. Nothing is wired in
yet, so `make check` stays green through this phase.

**Advances:** C2 (fully).

**Files:**
- Create: `scripts/assertion_lint.py`
- Read-only: `scripts/test_assertion_lint.py` — **frozen at `48c8104`.** If it looks wrong, that
  is a STOP and an amendment, never an edit.

**Key changes** — the interface is fixed by the frozen test, not chosen here:

```python
ROOT: Path                                      # repo root; monkeypatchable, docs_check pattern
failures: list[str]                             # module-level accumulator
SCOPE = "driver/test-*.sh"                      # the declared scope; the Makefile is excluded
scan_file(path: Path) -> list[tuple[int, str]]  # (1-based line no., line minus trailing newline)
lint_files() -> None                            # walk ROOT for SCOPE, append to failures
main() -> int                                   # print failures, exit 1 if any
```

`scan_file` takes an explicit path and **must not consult `ROOT`** — that is what lets the third
conjunct read the live `driver/test-park-state.sh` while the test's autouse fixture has `ROOT`
pointed at `tmp_path`.

The rule, stated as a single mechanical predicate:

> A line is reported iff it lies in a file matching `SCOPE`, and `grep -q`, `grep -qE` or
> `grep -qF` appears on it with **no `#` earlier on the line**.

```python
PRESENCE_GREP = re.compile(r'^[^#]*\bgrep\s+-q[EF]?\b')
```

Two things this deliberately does NOT do, both because a false positive trains the operator to
wave the mechanism through:

- **It does not look at the grep's target.** `-q` is the tell: it discards the match and yields
  only an exit status, so the assertion can only mean "the literal is present somewhere". `-c`
  produces a number that gets compared, which is why the count-comparison fixture is spared.
- **It carves out no exception for `grep -q` reading stdin** (`| grep -q`, `<<<`), even though
  grepping captured *output* is legitimate. Measured on this branch: neither suite contains one,
  so the exception would be untested speculation and a standing bypass. If a real need appears,
  `grep -c … = 1` covers it, and widening the rule is a human's call.

**Verification — automated:**
- [ ] C2's check passes: `uv run pytest scripts/test_assertion_lint.py` — **7 passed**, exit `0`.
      The count is load-bearing: at freeze this file failed on collection, so a pass without a
      count would not show the assertions ran.
- [ ] Cross-check the detector against C1's independent frozen command — run the detector over the
      real `driver/test-driver.sh` and confirm it reports **exactly the eight lines**
      213 244 245 255 260 267 272 337, the same set
      `grep -cE '^[^#]*grep -q[EF]? .*"\$DRIVER"' driver/test-driver.sh` counts. Two independently
      authored patterns agreeing on the same eight lines is what distinguishes a working detector
      from one shaped to its own fixtures.
- [ ] Guards unaffected (nothing wired yet): `make check` → `all checks passed`

---

## Phase 2: Wire the detector into `make check`

Add an `assertion-lint` target and put it in `check`. **This phase deliberately leaves the tree
red** — the detector now sees the eight live instances. That red is the evidence the detector
fires on real code and not only on fixtures; Phase 3 clears it.

**Advances:** C3 (partially — proves the wiring conducts a failure; the mutation test that closes
C3 is Phase 4, because it can only be run against a tree that is otherwise green).

**Files:**
- Modify: `Makefile` — new `.PHONY` target `assertion-lint`, added to `check`'s prerequisites and
  to the `help` block, following the shape of `docs-check`.

```makefile
# A test that greps its subject for a literal is a spelling check, not a test:
# `grep -q 'x' "$(DRIVER)"` passes when x appears in a COMMENT. See issue #28 and
# findings.md defect class 5. Scope is driver/test-*.sh; the Makefile's own
# grep -qF guards are excluded on purpose -- skill-readonly asserts a deny rule is
# literally present, so there presence IS the property being tested.
assertion-lint:
	@python3 scripts/assertion_lint.py
```

**Verification — automated:**
- [ ] `make check` exits **non-zero**, and the output names the eight offending lines in
      `driver/test-driver.sh`
- [ ] `make assertion-lint` alone exits non-zero with the same eight
- [ ] G1 still passes underneath the red: `make driver-test` → `0 failed`, count ≥ 88

---

## Phase 3: Fix the eight

Convert each presence-grep assertion in `driver/test-driver.sh` into a comment-excluded **count
comparison** — the shape C2's negative fixture explicitly spares, and the shape already used at
`Makefile:75` and `test-driver.sh:286`.

**Advances:** C1 (fully). Restores G1 and G2 to green.

**Files:**
- Modify: `driver/test-driver.sh` — the eight assertions at lines 213, 244, 245, 255, 260, 267,
  272, 337 (244/245 are one compound `if`, so seven assertion sites).

One helper, defined once near the top of the file, then used at each site:

```bash
# Count non-comment occurrences of a literal in the driver. `grep -q` was the old
# spelling and it passes when the literal appears in a COMMENT -- a spelling check,
# not a test (findings.md defect class 5, issue #28). Stripping comment lines first
# and comparing a COUNT means deleting the code flips the assertion, and describing
# it in a comment does not satisfy it.
_code_hits() { # $1 = literal -> occurrences on non-comment lines of the driver
  grep -v '^[[:space:]]*#' "$DRIVER" | grep -cF "$1"
}
```

Each site becomes `check "<same name>" "<measured count>" "$(_code_hits '<same literal>')"`.
Expected counts are **measured against the driver during execution, not guessed**; a site whose
measured count is not what the assertion implies is a finding to surface, not a number to paste.

The negated pair at 244/245 needs both halves kept — the park list must contain
`parked|failed|incomplete|no-gate)` and must NOT contain the `budget-exhausted` variant — so it
stays one `if` over two counts, asserting `1` and `0` respectively.

**Scope note, recorded rather than silently chosen:** the *behavioural* conversion at
`test-driver.sh:177-192` (assert through the shipped parser) is strictly better where it is
reachable, and it is the precedent the issue cites. It is not applied to these eight because each
would need a driver subprocess with stubbed `gh`/`claude`, a state dir and an orphan pid — a
larger piece of work than this issue scopes, and C1 asks only that the comment-satisfiability be
removed. Noted for a future session; not done here.

**Verification — automated:**
- [ ] C1's check passes: `grep -cE '^[^#]*grep -q[EF]? .*"\$DRIVER"' driver/test-driver.sh` → `0`
- [ ] G1 passes: `make driver-test` (recipe: `@bash driver/test-driver.sh`) → `0 failed`, count
      **≥ 88** — the freeze floor, not the issue's stale 64. This is the guard that catches the
      delete-instead-of-fix cheat.
- [ ] Each converted assertion is shown to still discriminate: for at least one site, temporarily
      break the literal and watch that specific `check` fail, then restore. A converted assertion
      that cannot fail is the same defect wearing a new shape.
- [ ] G2 passes: `make check` → `all checks passed`
- [ ] C2 still passes: `uv run pytest scripts/test_assertion_lint.py` → 7 passed

---

## Phase 4: Close C3 with the mutation test

Run C3's frozen mutation end to end against a green tree.

**Advances:** C3 (fully).

**Files:** none permanently — the mutation is applied and reverted.

**Verification — automated:**
- [ ] Append `if grep -q 'STATE_DIR' "$DRIVER"; then :; fi` to `driver/test-driver.sh`;
      `make check` exits **non-zero** and names that line
- [ ] `git checkout -- driver/test-driver.sh`; `make check` → `all checks passed`; `git status`
      clean
- [ ] `git diff --stat` shows no residue of the mutation in the committed tree

*(`driver/test-park-state.sh` is not used for the mutation: it is issue #5's frozen acceptance
file, read-only per its own header, and it is C2's live negative fixture.)*

---

## Phase 5: Close the ledger row this run falsifies

**Advances:** no criterion — and that is a deliberate, named exception to bidirectional coverage,
not an oversight.

`docs/findings.md:176-181` records these eight assertions as **"still shipping (verified
2026-07-27)"**, with line numbers 196/202/227/269/274/281/286/351 that have already drifted from
today's 213/244/245/255/260/267/272/337. Phase 3 makes the "still shipping" claim false. CLAUDE.md's
*"When you change something, ask what it just invalidated"* section exists for exactly this shape —
a claim the run falsifies itself, by doing ordinary work, with no other trigger to catch it. `docs/`
is drivable.

**Files:**
- Modify: `docs/findings.md` — the one ledger bullet at 176-181. Rewrite it as closed-and-dated,
  keeping the lesson (which is still true) and dropping the drifted line numbers in favour of the
  detector that now enforces it. **No other bullet is touched**; this is not a docs sweep.

**Verification — automated:**
- [ ] G3 passes: `python3 scripts/docs_check.py` exits `0`
- [ ] G2 passes: `make check` → `all checks passed`
- [ ] `git diff docs/findings.md` touches only the one bullet
