# Driver: report marker-less issues instead of silently dropping them

**Source:** https://github.com/lmorchard/agent-sessions/issues/13

*(Captured verbatim from the issue body at session setup, marker line stripped. The issue is the
authoritative copy; this is the run's snapshot of it.)*

---

The select stage drops issues that carry no `<!-- agent-session:spec -->` marker **without saying so**.
Observed against this repo's own board:

```
repo lmorchard/agent-sessions: read 10 open issues
board lmorchard/9: read 10 items (advisory only; does not gate)
  SKIP    #9  tier: needs-review
  SKIP    #7  tier: needs-review
  ELIGIBLE #6  ...
  ELIGIBLE #5  ...
  SKIP    #4  already has an open PR: ...
  SKIP    #3  tier: needs-review
  SKIP    #2  tier: needs-review
  SKIP    #1  tier: needs-review
eligible: 2
```

**Ten read, eight accounted for.** #11 and #12 produce no line at all. An untriaged issue renders as
*nothing* — the "a null must never render as a positive" shape this repo has now hit five times
(`clean` vs `clean-by-substitute`, the 30-item board truncation, zero CI checks, the ci-sha no-op,
the denial detector matching its own regex).

## This is not a new principle — it is an existing one applied one stage too late

`agent-session-driver.sh`'s own select-stage comment already commits to it:

> *Emits one line per excluded candidate with its reason. A queue read that yields zero must say why,
> or "no eligible work" and "my query is broken" print identically.*

The marker filter runs **upstream** of the candidate list, so marker-less issues never reach the code
that honours that promise. The `no issues carry the marker` message only prints when the count is
*zero* — the partial case is silent.

## Why this matters now

Unattended runs file their own follow-ups. The #4 run filed #11 correctly (three real Copilot
findings it was structurally barred from fixing under the freeze), and #12 was filed by hand. Neither
carries a marker, so **neither is visible to the driver and neither will be triaged unless a human
remembers.** That is the prose-backlog failure this board was created to fix, one level up.

Decided in conversation: run-filed follow-ups get triaged in a **later batch pass**, *not* stamped by
`pr.md` — `triage` already exists for exactly this, PR time is the worst-informed and most expensive
moment to derive criteria, and `pr.md` already links the follow-up from the gate's `reason` field.
**That decision only works if something makes "there are untriaged issues" visible**, which is what
this issue is for.

## Stakes are low, which is why this is a reporting fix and not a gating one

A marker-less issue **cannot be driven** — no marker means it is dropped at selection, so it can never
be attempted unattended. The failure mode is *work sitting unnoticed*, not *work getting driven
badly*. So the fix is to report, not to block.

## Shape of the fix

Report the count and the numbers, e.g.:

```
repo lmorchard/agent-sessions: read 10 open issues (8 carry the marker; 2 do not: #11, #12 -- run triage)
```

Touches `driver/agent-session-driver.sh` only. Not `driver/gate.py` — the marker filter lives in
`tier_batch`, which already drops these deliberately and distinguishes *dropped* from `missing`; the
reporting belongs in the bash select stage that owns the operator-facing output.


---

*Everything below was added by `agent-session triage`, 2026-07-29. The text above is the original
author's, unmodified.*

## Current state — the path assertion, verified

The body's claim that this touches `driver/agent-session-driver.sh` only was checked rather than
taken on trust, and it **holds**:

- The marker filter is in Python — `driver/gate.py:213-228` (`tier_batch`, *"Others are dropped"*) —
  called from exactly one place, `driver/agent-session-driver.sh:372`.
- The bash select stage already holds everything the report needs *before* that call: `issues_json` is
  fetched at `agent-session-driver.sh:360-361` with `--json number,title,body,labels`, and `total` is
  computed at `:362`.
- The zero-case message at `:375-376` sits inside `if [ -z "$candidates" ]`, which is exactly why the
  partial case is silent.

**One correction to the body's opening premise.** This issue's *own* body contains the literal
`<!-- agent-session:spec -->` as a quotation in its first sentence, and `gate.py:225` tests membership
with a plain substring (`marker not in body`). So #13 was never invisible — it already printed
`SKIP #13 tier: no '## Tier:' line in body`. The genuinely invisible issues were #11 and #12. Verified:
`gh issue list --json number,body` gave `{"total":9,"with_marker":7,"without":[12,11]}` while the
driver printed 7 lines for 9 issues. The self-matching hazard is filed separately.

## Verifiable acceptance criteria

- CRITERION: WHEN the select stage reads a set of open issues of which at least one carries the spec
  marker and at least one does not, the driver SHALL emit the issue number of every marker-less issue
  in its select-stage output, and SHALL NOT list any of them as `ELIGIBLE`.
  CHECK: a new case in `driver/test-driver.sh` following the offline-`gh`-stub + `--dry-run` pattern
  already shipping at `test-driver.sh:456-487`, with `--state-dir "$(mktemp -d)"`. Fixture: two open
  issues whose numbers are **derived at run time** (`$RANDOM`-based), one carrying the marker and a
  `## Tier: auto-ok` line, one carrying neither. Asserts, against the driver's stdout: (a) the
  marker-less number appears; (b) no line containing `ELIGIBLE` contains that number; (c) the run
  reports `eligible: 1`.
  VERIFIED DISCRIMINATING: ran that exact shape twice. With fixed numbers 101/202/303 (3 issues, 1
  specced): `read 3 open issues` then a single `ELIGIBLE #101` line, and the probe printed
  `MISS: 202 never reported`, `MISS: 303 never reported`, **exit 1**. With `$RANDOM`-derived
  10805/7286: `read 2 open issues` / `ELIGIBLE #10805` / `eligible: 1`, probe printed
  `C1-FAIL: marker-less #7286 unreported`, **exit 1**. The live form reproduces too:
  `--repo lmorchard/agent-sessions --dry-run` printed `read 9 open issues` followed by seven lines.
  Satisfiable-without-the-work: **no.** Three degenerate shortcuts are each closed — printing a
  literal fails (the numbers are random per run); marking everything eligible fails (assertion b);
  widening the marker filter so marker-less issues become candidates fails (assertion c). This grades
  *generated stdout against fixture-derived values*, so it is **not** the
  `grep -q "<literal>" "$DRIVER"` source-spelling shape that `docs/findings.md` class 5 catalogs eight
  live instances of.
  Oracle exists now: yes, and it was run. No new fixture *file* is needed — the stub is inline and
  `export -f gh` is inherited by the driver's bash (verified: with the stub the driver reported
  `read 3 open issues` from the fixture; without it, `read 0`).
  **Implementation note the freeze must respect:** `agent-session-driver.sh:210` runs
  `mkdir -p "$STATE_DIR/runs"` unconditionally, so the case must pass `--state-dir` into a tmpdir
  rather than let it default to `./.driver-state`, exactly as `test-driver.sh` already does.

**Rejected as criteria, recorded so nobody re-proposes them.** (a) The live-board form — invoking
`--repo lmorchard/agent-sessions --dry-run` and asserting #11 and #12 appear — fails the
satisfiable-without-the-work test outright: the cheapest way to make it green is for a triage pass to
stamp #11 and #12 with markers, after which it passes with **zero code change**. It also depends on
mutable network state. Do not freeze it. (b) "the output mentions triage / names a remedy" — satisfied
by typing the word.

## Regression guards

Pass today, must keep passing, and do not affect the tier.

- GUARD: the zero-marker path is unchanged — same stub, a fixture of one marker-less issue only,
  asserting stdout still contains `no issues carry the marker`. Protects the existing zero-case message
  from being swallowed by the new partial-case branch, which is the fix's most likely collateral.
  RAN: passes today.
- GUARD: `printf '%s' '<mixed fixture>' | python3 driver/gate.py tier-batch --marker '<!-- agent-session:spec -->'`
  emits exactly the marker-carrying rows and nothing else. Protects the "reporting, not gating"
  boundary **and** the path assertion above: if this output ever grows a dropped-issue row, the fix has
  left `driver/agent-session-driver.sh` and the tier below is void.
  RAN: `101<TAB>auto-ok<TAB>specced`, exit 0 — one row for the two-issue fixture. Passes today.
- GUARD: `bash -n driver/agent-session-driver.sh` exits 0 — cheap syntax guard on the file being
  edited. RAN: exit 0. Passes today.
- GUARD: the driver-side bash suite (`make driver-test`) loses no test and gains no newly-failing or
  newly-skipped one. Stated as an invariant, not a pinned count. **UNRUN** — the triage scan operated
  under a no-full-suites cap and `test-driver.sh` has no per-case selector. **Must be run once before
  merge; nothing here establishes that it is green.**

## Tier: `auto-ok`

Derived, not argued.

**Trigger 1 does not fire.** The criterion is machine-graded on generated stdout, its oracle exists
now (it was run; exit 1), and its cheapest green is the work itself.

**Trigger 2 does not fire, and this is the load-bearing part.** `CLAUDE.md` gates `skills/**` and
`driver/gate.py`, and states that "the rest of `driver/` ... is drivable." The fix is confined to
`driver/agent-session-driver.sh:360-377` — verified above by reading the call graph, with the
`tier-batch` guard standing over the boundary. No auth, secrets, data migration/deletion,
deploy/infra/CI config or dependency change. The change writes no issue or PR content; it only prints
to the operator's stdout, so the driver's "issue metadata, never content" line is not approached.

**Contingency, stated up front:** if implementation turns out to need a `driver/gate.py` change after
all — for instance if someone prefers `tier_batch` to emit a `dropped` row rather than having bash take
the complement — then trigger 2 fires and the tier becomes `needs-review`. **Stop and surface rather
than proceeding.** The `tier-batch` guard is what detects that drift.

## Design decisions

- **Decision:** the report is a parenthetical appended to the existing `read N open issues` line, as
  the body proposes.
  - **Why:** it keeps one line per stage, and it is the author's own stated shape.
  - **Rejected:** a separate line — arguably easier to read, but it adds a stage line that prints
    nothing in the common case where every issue is specced.

- **Decision:** print **every** marker-less number. No cap, no `+N more`.
  - **Why:** a cap reintroduces precisely the failure this issue is an instance of — a null rendering
    as a positive. `docs/findings.md` class 2 instance 2 is `gh project item-list`'s silent 30-item
    truncation, which made a 185-item board read as smaller than it was. Truncating the *fix* for that
    class would be the same bug one level up.
  - **Rejected:** capping at some N with a "+N more" suffix. If the list ever gets genuinely unwieldy
    that is a signal to run `triage`, which is the message the line is meant to send.

- **Decision:** derive the marker-less set as the **complement of `tier_batch`'s emitted numbers**, not
  by re-deriving the marker test in `jq`.
  - **Why:** a second implementation of the predicate is the hand-copied-predicate drift this repo has
    already been burned by (`test-driver.sh:19-25`, and `docs/findings.md` class 1 instance 9). The
    complement re-implements nothing.
  - **Rejected:** `jq 'select((.body//"")|contains($m)|not)|.number'` over `issues_json` — correct
    today, and a second place for the predicate to drift.

- **Decision:** the output format is recorded here as a decision, **not** as a criterion.
  - **Why:** the criterion grades content (the numbers appear, none is eligible), which is
    machine-checkable. A criterion over *phrasing* is either a literal grep — a spelling check — or a
    human read, and the human read would force `needs-review`. Pinning the format in the body gives the
    implementer no ambiguity without costing the tier.
  - **Rejected:** making the wording a criterion.

## What we're NOT doing

- **Gating on the marker.** The fix reports; it does not block. A marker-less issue cannot be driven
  anyway, so the failure mode is work sitting unnoticed, not work being driven badly.
- **Changing `driver/gate.py`.** `tier_batch` already distinguishes *dropped* from *missing*
  deliberately. If the implementation appears to need this, stop — see the tier contingency.
- **Fixing the self-quoting-marker hazard** — that an issue which merely *quotes*
  `<!-- agent-session:spec -->` is indistinguishable from one that was specced. Real, and this issue's
  own body is an instance, but it touches `driver/gate.py` and is filed separately.
- **Pinning the report's exact wording as a check.** See Design decisions.

## Open questions

- Where the frozen check lives: a new case in `driver/test-driver.sh`, or the session's frozen
  `checks.md`. This is not a test-coverage issue — the deliverable is driver behaviour, not a test — so
  the normal freeze split applies. **Default if unanswered:** a new case in `driver/test-driver.sh`,
  alongside the existing stub-based cases it reuses.
