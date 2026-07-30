# Frozen acceptance checks

**Source:** https://github.com/lmorchard/agent-sessions/issues/13
**Frozen at:** (recorded in the follow-up commit — a commit cannot contain its own hash)
**Check files — read-only from Phase 1 onward:**
- `driver/test-driver.sh`

The implementation target is `driver/agent-session-driver.sh`, which is a *different* file from the
check file above. So check and implementation are disjoint here and the plain tamper diff applies —
this is **not** the "work must edit its own oracle" case, and no scoped-invariant substitute is
needed.

## C1

CRITERION: WHEN the select stage reads a set of open issues of which at least one carries the spec
marker and at least one does not, the driver SHALL emit the issue number of every marker-less issue
in its select-stage output, and SHALL NOT list any of them as `ELIGIBLE`.

CHECK: a new case in `driver/test-driver.sh` following the offline-`gh`-stub + `--dry-run` pattern
already shipping at `test-driver.sh:456-487`, with `--state-dir "$(mktemp -d)"`. Fixture: two open
issues whose numbers are **derived at run time** (`$RANDOM`-based), one carrying the marker and a
`## Tier: auto-ok` line, one carrying neither. Asserts, against the driver's stdout: (a) the
marker-less number appears; (b) no line containing `ELIGIBLE` contains that number; (c) the run
reports `eligible: 1`.

*(CHECK text copied verbatim from the issue body. Two observations recorded at freeze, neither
altering what the check asserts — so both are clarifications, not amendments, and neither costs the
tier:*

1. *The line ref `test-driver.sh:456-487` has **drifted**. That range now holds the nested-skill-dir
   (`_nest_run`) cases. The offline-`gh`-stub + `--dry-run` pattern the CHECK describes is at
   `test-driver.sh:529-573` as of freeze. The pattern is what the CHECK names; the range is a stale
   pointer to it.*
2. *The issue's supporting note says `export -f gh` is inherited by the driver's bash. The pattern
   actually shipping uses a **stub script on `PATH`** that honors the requested `--json` field list
   (`test-driver.sh:548-562`). The shipping form is followed, being both hermetic and, per the
   comment at `:538-539`, the only form under which a missing `--json` field can change what the
   driver sees.*

*Assertions (a), (b) and (c) — the whole of what grades — are unchanged.)*

**Implemented at** `driver/test-driver.sh:575-702` — the C1 case at `:592-677`, G1 at `:679-700`.

AT FREEZE: **fails on assertion (a).** Observed, `make driver-test`, before any implementation edit:

```
select: a mixed queue must account for its marker-less issues
  ok    probe: the stub served both issues to the select stage
  FAIL  (a) the marker-less issue number appears in select output
     expected: 6580 somewhere in stdout
     actual:   == select ==|repo stub/repo: read 2 open issues|  ELIGIBLE #5012  tier: auto-ok|                marked and tiered|eligible: 1||dry run -- no claude invocation.
  ok    (b) no ELIGIBLE line names the marker-less issue
  ok    (c) the run still reports one eligible issue
select: the zero-marker message is not swallowed by partial reporting
  ok    G1 an all-marker-less queue still says no issues carry the marker
syntax
  ok    driver parses

68 passed, 1 failed
```

**Failure is attributable to absent behavior, not to harness error.** Four pieces of evidence:

1. The **liveness probe passes** — `repo stub/repo: read 2 open issues`. The stub served, the driver
   passed validation, wrote its state dir and entered the select stage holding *both* fixture issues.
   An absent needle from a driver that died at validation would look identical without this probe.
2. The dumped stdout is a **complete, well-formed select block** — header, count line, one `ELIGIBLE`
   with its title, `eligible: 1`, dry-run trailer. No `jq` error, no `command not found`, no
   truncation.
3. `ELIGIBLE #5012` proves the *marked* fixture parsed through `tier-batch` to `auto-ok`, so the
   marker and `## Tier:` line are being read correctly. #6580 is missing because `tier_batch` drops
   it (`gate.py:225`) and the marker-less set never reaches the per-candidate loop at
   `agent-session-driver.sh:381` — not because the fixture is malformed.
4. **Run-time derivation confirmed across runs.** The check-author observed `3984`/`9339` and then
   `5889`/`8306`; the independent freeze run above observed `6580`/`5012`. Same single failure each
   time. A literal in the driver's source cannot satisfy this needle.

**(b) and (c) pass vacuously today** — the driver says nothing at all about the marker-less issue, so
"don't call it eligible" and "the count is 1" are already true. Recorded plainly because it matters
downstream: (b) and (c) are not evidence of the fix, they are the **guards against an over-correcting
fix** that makes the marker-less issue a candidate. Only (a) discriminates.

## Guards

(Pass today; must keep passing. Not criteria — they can't fail at freeze.)

- **G1**: the zero-marker path is unchanged — same stub, a fixture of one marker-less issue only,
  asserting stdout still contains `no issues carry the marker`. Protects the existing zero-case
  message from being swallowed by the new partial-case branch, which is the fix's most likely
  collateral. Lives as a case in `driver/test-driver.sh` (frozen).
- **G2**: `printf '%s' '<mixed fixture>' | python3 driver/gate.py tier-batch --marker '<!-- agent-session:spec -->'`
  emits exactly the marker-carrying rows and nothing else. Protects the "reporting, not gating"
  boundary **and** the issue's path assertion: if this output ever grows a dropped-issue row, the fix
  has left `driver/agent-session-driver.sh` and the tier is void.
  **DISCHARGED BY PROXY, not invoked in its literal form** — say so rather than let the substitution
  pass as the thing itself. This run's sandbox denies direct interpreter invocation
  (`python3 driver/gate.py ...` was refused), so the literal pipeline could not be run. Three
  substitutes carry it, and all three are runnable here:
  - `test_gate.py:237` `test_tier_batch_drops_marker_less_issues` asserts exactly G2's property
    against the shipped function. Run by `make gate-test`.
  - `test-driver.sh:133-135` drives `tier-batch` through the same real CLI the driver uses.
  - The path half is discharged *more* strongly than the command form does it:
    `git diff --stat` must show `driver/gate.py` untouched. A command asserting the output shape can
    only infer that the file did not change; the diff states it.
- **G3**: `bash -n driver/agent-session-driver.sh` exits 0 — cheap syntax guard on the file being
  edited. Discharged directly: `test-driver.sh:577-578` runs precisely `bash -n "$DRIVER"`, and it
  printed `ok driver parses` in the freeze run above. (Invoking it standalone was also sandbox-denied;
  the suite runs the identical command, so this is coverage, not a substitute.)
- **G4**: the driver-side bash suite (`make driver-test`) loses no test and gains no newly-failing or
  newly-skipped one. Stated as an invariant, not a pinned count.
  **The issue marked G4 UNRUN and required it be run once before merge. It was run at session setup,
  before any edit: `make check` passed in full — `driver-test` 64 passed / 0 failed, `park-test`
  21 passed / 0 failed, plus `driver-check`, `skill-readonly`, `docs-check`. That discharges the
  issue's standing requirement and establishes the pre-edit baseline as green.**

## Amendments

(Append-only. Empty — no amendment was made.)

## Pre-squash tamper verdict

(Recorded in `pr.md`'s Squash-and-open step, before the squash collapses the freeze commit.)
