# Frozen acceptance checks

**Source:** https://github.com/lmorchard/agent-sessions/issues/23
**Frozen at:** `c0a6500` (2026-07-30)
**Check files — read-only from Phase 1 onward:**
- `driver/test-driver.sh`

Criteria and checks are copied **verbatim** from the issue body. The spec's `file:line`
refs were a snapshot taken at intake and have since drifted; the drift is recorded under
"Line-reference drift" below and changes no criterion.

## C1

CRITERION: GIVEN an open PR whose body mentions `#N` in prose with no closing keyword, whose branch
name contains N, and whose `closingIssuesReferences` is empty, WHEN the select stage runs on an
`auto-ok` issue N, THEN the driver SHALL report `ELIGIBLE #N` and SHALL NOT report
`SKIP    #N  already has an open PR`.

CHECK: a new node in `driver/test-driver.sh` following the **field-honouring** `gh`-stub +
`--dry-run` pattern at `:456-487` — stub `pr list` with PR 21 verbatim (body table containing `#11`,
`headRefName: docs/triage-11-12-13`, `closingIssuesReferences: []`), an issue fixture with #11
`auto-ok`, then assert the output contains `ELIGIBLE #11` and does not contain the skip line. Graded
by running the shipped driver as a subprocess, so deleting the behaviour flips it — **not** a
`grep -q "<literal>" "$DRIVER"` spelling check.

Run as: `make driver-test`, reading the `C1(a)` / `C1(b)` / `C1(c)` assertion lines by name, under
the node `select: an open PR blocks an issue only when it closes it`.

AT FREEZE: **fails**, for the expected reason — the loose matcher fires on the `#11` in the body
table and on the `11` in the branch name, so the run reports the skip instead of the eligibility.
Observed verbatim:

```
  ok    probe: the stub served the issue to the select stage (C1 fixture)
  FAIL  C1(a) an issue merely mentioned by an open PR is still eligible
     expected: ELIGIBLE #11
     actual:   == select ==|repo stub/repo: read 1 open issues|  SKIP    #11  already has an open PR: https://github.com/stub/repo/pull/21|                the issue a triage sweep merely mentioned|eligible: 0||dry run -- no claude invocation.
  FAIL  C1(b) no open-PR skip line names the merely-mentioned issue
     expected:
     actual:     SKIP    #11  already has an open PR: https://github.com/stub/repo/pull/21
  FAIL  C1(c) the run reports one eligible issue
     expected: eligible: 1
     actual:   eligible: 0
```

The liveness probe passed at freeze, which is what makes those three failures attributable to the
matcher rather than to a broken stub or a driver that died at validation. The driver printed a
*decision* about #11 naming the stub's own PR URL — output only the PR matcher can produce.

## C2

CRITERION: WHEN `fetch_open_prs` queries GitHub, the driver SHALL request `closingIssuesReferences`,
so the authoritative issue link is available to the matcher without a second API call.

CHECK: the same test node, using the `:456-487` stub that **honours** the requested `--json` field
list — serve a PR whose body and branch carry no number at all but whose `closingIssuesReferences` is
`[{"number":11}]`, and assert `SKIP    #11  already has an open PR`. Only a driver that actually asks
for the field can see it, because the stub filters on the requested list.

Run as: `make driver-test`, reading the `C2(a)` / `C2(b)` assertion lines by name, in the same node.

AT FREEZE: **fails**, for the expected reason — `fetch_open_prs` requests
`number,title,body,headRefName,url` only, so the field-honouring stub strips
`closingIssuesReferences` before the driver ever sees it, and the fixture (which carries the issue
number nowhere a proxy can reach — not body, not title, not branch) matches nothing. Observed
verbatim:

```
  ok    probe: the stub served the issue to the select stage (C2 fixture)
  FAIL  C2(a) a PR linked only by closingIssuesReferences blocks the issue
     expected: SKIP    #11  already has an open PR
     actual:   == select ==|repo stub/repo: read 1 open issues|  ELIGIBLE #11  tier: auto-ok|                the issue a triage sweep merely mentioned|eligible: 1||dry run -- no claude invocation.
  FAIL  C2(b) no ELIGIBLE line names the linked issue
     expected:
     actual:     ELIGIBLE #11  tier: auto-ok
```

The liveness probe passed at freeze. The failure is the un-requested field, not a stub bug: the same
stub served the C1 fixture and *did* produce a match there, through the fields the driver does ask
for.

## Guards

(Pass today; must keep passing. Not criteria — they can't fail at freeze.)

- **G1**: the extracted `pr_for_issue 7` still returns its PR for the **frozen** fixture at
  `driver/test-park-state.sh:89` — body `Closes #7`, branch `fix/7-stub`, and **no
  `closingIssuesReferences` field at all** (its stub ignores the requested field list).
  Expected `42<TAB>https://github.com/stub/repo/pull/42`. Passed at freeze.
  **This is the load-bearing guard.** A closing-refs-only fix applied to the *discovery* call sites
  makes that frozen fixture resolve to nothing, flipping its cases to `parked: no PR opened`.
  `test-park-state.sh` is frozen and read-only, so tripping this is a **STOP**, not an edit.
- **G2**: the extracted `pr_for_issue 8` returns empty for the same frozen fixture — the gate still
  gates. Protects against "fixing" C1 by deleting the match, since an over-broad matcher and a
  deleted matcher both green C1. Passed at freeze.
- **G3**: `bash -n driver/agent-session-driver.sh` exits 0. Asserted by the suite's existing
  `driver parses` node. Passed at freeze.
- **G4**: no existing `driver-test` or `park-test` assertion is lost, newly skipped, or newly
  failing. An invariant, not a count — run as `make check`. Passed at freeze (the issue recorded it
  UNRUN; this run is the once-before-merge run it asked for).

G1 and G2 are asserted inside `driver/test-driver.sh` by extracting the real function out of the
shipped driver (`eval "$(sed -n '/^pr_for_issue()/,/^}/p' ...)"`, the `test-park-state.sh:180`
pattern) **and** the fixture out of the frozen file (`sed -n '/^PR_LIST_JSON=/p'`), not by copying
either. A copy would drift, which is the defect this suite was already burned by once. Both
extractions fail closed: a rename reports as a `bad`, never as a silent skip.

**Freeze run, verbatim** (`make driver-test`) — the guards, and the totals that make the criterion
failures countable:

```
  ok    G1 the frozen 'Closes #7' PR is still matched to #7
  ok    G2 and #8, which that PR does not mention, is still unmatched
syntax
  ok    driver parses

74 passed, 5 failed
```

The 5 failures are exactly C1(a,b,c) and C2(a,b). Nothing else in the suite regressed at the freeze,
and `make park-test` (21 passed, 0 failed) and `make docs-check` were green at the same commit —
that is G4's freeze reading.

## Line-reference drift (recorded, changes no criterion)

The issue's `file:line` refs were a snapshot; re-verified 2026-07-30 against `origin/main` @ `0b7aabf`:

| Spec says | Actually at | What it is |
|---|---|---|
| `agent-session-driver.sh:324-332` | `:337-344` | `pr_for_issue` |
| `agent-session-driver.sh:319` | `:332-335` | `fetch_open_prs` |
| `agent-session-driver.sh:384` / `:391` | `:433` / `:440` | the **selection gate** call site + its skip reason |
| `agent-session-driver.sh:622` | `:671` | post-run PR **discovery** (normal path) |
| `agent-session-driver.sh:746` | `:795` | post-run PR **discovery** (`--classify-only` recovery path) |
| `test-driver.sh:444-455` / `:456-487` | `:550-561` / `:562-594` | the field-honouring-stub comment + node |
| `test-park-state.sh:89` | `:89` | unchanged — the frozen `PR_LIST_JSON` fixture |
| `test-park-state.sh:180` | `:180` | unchanged — the function-extraction pattern |

The code at each new location is the code the spec describes. One selection call site, two discovery
call sites — the split the spec's design decision depends on is intact.

## Amendments

(Append-only. Empty unless an amendment was made.)

None.

## Tamper verdict

(Recorded by the independent verifier.)
