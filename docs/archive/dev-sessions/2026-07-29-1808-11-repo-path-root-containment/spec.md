# Spec — issue #11

**Source:** https://github.com/lmorchard/agent-sessions/issues/11
**Title:** Driver: `--repo-path /` bypasses the nested-skill-dir containment guard
**Tier:** `auto-ok` (from the body's `## Tier:` heading; the `auto-ok` label agrees)

Captured verbatim from the issue body below, with the `<!-- agent-session:spec -->` marker line
stripped. The mid-body `*Filed by ...*` line is the author's own text and is kept.

---

> **Scope fence, added by `agent-session triage` 2026-07-29 — read this before acting on the text
> below.** This issue was filed with **three** follow-ups. It is now **follow-up 1 only** — the
> `--repo-path /` containment bypass. **Follow-ups 2 and 3 have moved to #18** (`needs-review`), and
> the "Meta" question is not an issue at all. Their text is left in place below because the author's
> filing is preserved verbatim, **not because it is in scope.** See "What we're NOT doing".

---

Follow-ups from the Copilot review on #10 (issue #4, the nested `--skill-dir` guard). All three are real; none was actionable inside that run, for reasons that are themselves worth recording.

## 1. `--repo-path /` bypasses the containment guard

`repo_real=/` makes the `case` pattern `//*`, which matches no ordinary absolute path — so every path is inside `/` and none is detected.

**Why it was deferred rather than fixed.** The fix is one or two lines. But `driver/test-driver.sh` was frozen at `207ead9` before implementation and is read-only for the rest of that run, so the fix could not have carried a check. Shipping an unexercised code path is the defect class this repo already catalogs — `docs/findings.md` records three guards that could not fail, and the issue text for #4 opens by demanding mutation-testability for exactly this reason. Landing an untested fix to satisfy a reviewer is a smaller version of the implementer deciding what "done" means.

So: freeze a check for it **first**, then fix. That is the ordering the whole system exists to enforce, and this is a clean instance of it.

Reachability is near-nil today, which is why deferring is cheap: `set -u` makes an unset variable an error rather than an empty expansion, and `--repo-path ""` is already caught by the `[ -n "$REPO_PATH" ]` test. Reaching `/` means typing `/`.

**Suggested check (write before the fix):** a case with `--repo-path /` and a `--skill-dir` anywhere absolute, asserting the warning fires.

## 2. The hermetic-invocation `PATH` assumption is environment-dependent

The eleven new cases pin `PATH=/usr/bin:/bin` and rely on `gh` being absent from it, so a configuration that survives validation dies at the required-command loop. Verified true on the authoring host (`/usr/bin` carries `jq`, `git`, `python3`, and no `gh`). It is not guaranteed elsewhere — a host with `/usr/bin/gh` would let the driver proceed toward real GitHub operations and a state-dir write.

**Why it was not fixed:** same freeze. It is also arguably a comment on whether a frozen check is *right*, which `phases/pr.md` explicitly says a reviewer's opinion does not authorize editing — it routes through the amendment path, human adjudication and tier downgrade included.

**Suggested fix:** make the hermeticity explicit rather than ambient — point `PATH` at a scratch directory containing only symlinks to the interpreters the driver needs, so `gh`'s absence is constructed instead of assumed.

## 3. G2 hardcodes `$HOME/devel/decafclaw`

The "an unrelated checkout is not containment" guard names a path that exists only on one machine. On a host without it the driver dies earlier at `--repo-path does not exist`, so the guard would assert the wrong thing.

**Why it was not fixed:** substituting a `mktemp -d` asserts the identical property and would be a *clarification*, not an amendment (the verdict is unchanged at both the freeze tree and the implementation tree). But `references/frozen-checks.md` requires a human to adjudicate even a clarification, and that run was unattended. It was kept verbatim and recorded in its `checks.md` instead.

**This becomes live the moment a GHA host exists** (roadmap item 4 in `docs/design.md`) — there is no CI in this repo today, so nothing but a developer machine runs the suite.

## Meta: the shape these three share

Two of the three are frozen-file problems that a mid-run agent is structurally barred from fixing, and the third is barred by the freeze from being fixed *with a check*. That is the freeze mechanism working, not failing — but it does mean **a review that lands after the freeze can only ever produce follow-ups for anything touching the oracle.** Worth deciding deliberately whether that is the intended cost, or whether the review should be solicited earlier (e.g. against the freeze commit itself, before implementation).

---
*Filed by an unattended `agent-session express` run on #4. Threads left unresolved on #10 per `phases/pr.md`: a thread is resolved only when the run fixed what it raised.*


---

*Everything below was added by `triage`. The text above is the original author's, unmodified.*

## Verifiable acceptance criteria

- CRITERION: IF `--repo-path` resolves to `/` and `--skill-dir` is an absolute path beneath it, THEN
  the driver SHALL emit the nested-`--skill-dir` containment warning, and SHALL NOT proceed past
  validation to the required-command loop.
  CHECK: a new case in `driver/test-driver.sh` invoking the driver with `--repo-path /` and an
  absolute `--skill-dir`, asserting that output **contains** `--skill-dir is inside --repo-path` and
  **does not contain** `required command not found: gh`.
  VERIFIED DISCRIMINATING: ran
  `PATH=/usr/bin:/bin ./driver/agent-session-driver.sh --repo lmorchard/agent-sessions --skill-dir /Users/lorchard/devel/agent-sessions/skills/agent-session --repo-path / --state-dir /tmp/probe-b`
  → `verdict="no-warn gh-check" rc=2`, first line `error: required command not found: gh`; **no
  warning emitted.** Live control, same invocation with `--repo-path /Users`
  → `verdict="warned stopped-early" rc=2`, first line
  `WARNING: --skill-dir is inside --repo-path: ...`. The control is what makes this evidence rather
  than a broken probe: the warning path is live and reachable, so the subject's silence is the bug.
  **Caveat the freeze must respect: `rc=2` is identical in both branches.** A check asserting exit 2
  alone does not discriminate — only the message and the stop-point do. Asserting the exit code would
  be one of `docs/findings.md` class 5's non-discriminating halves.
  Cheapest way to make the check green is normalizing `repo_real` so `/` stops producing the `//*`
  pattern at `agent-session-driver.sh:158` — which is the work. Deleting the `case` block instead
  would make the *control* case fail, so that shortcut is closed.

## Regression guards

These pass today and must keep passing. They do not affect the tier.

- GUARD: `make driver-check` — the driver still has no executable merge path.
  RAN: `driver-check: no executable merge path in driver/agent-session-driver.sh`, exit 0.
- GUARD: the three existing false-positive nest cases still report `no-warn gh-check`. **This is the
  guard the fix most plausibly breaks:** any normalization of `repo_real` risks reopening the
  `/a/b`-vs-`/a/bc` string-prefix hole, and a containment check that refuses ordinary layouts trains
  the operator to reach for `--allow-nested-skill-dir` by reflex.
  RAN: a sibling-case replica (`--repo-path .../agent-sessions/driver`) gives `no-warn gh-check`
  today. The `/a/bc`-vs-`/a/b` case needs a `mkdir` and is **UNRUN** — the freeze must include it.
- GUARD: the driver-side bash suite (`make driver-test`) loses no test and gains no newly-failing or
  newly-skipped one. Stated as an invariant, not a pinned count. **UNRUN** — the triage scan ran
  under a no-full-suites cap and `test-driver.sh` has no case selector. Must be run once before
  merge; nothing here establishes that it is green.

## Tier: `auto-ok`

Derived, not argued. **Trigger 1 does not fire:** the criterion's oracle exists now (the driver *is*
the oracle, and it was run), the check fails today with a live control proving the probe works, and
the cheapest way to make it green is the fix itself.

**Trigger 2 does not fire.** The fix touches `driver/agent-session-driver.sh:157-165` plus a new case
in `driver/test-driver.sh`. `CLAUDE.md` gates `skills/**` and `driver/gate.py`, and states that "the
rest of `driver/` ... is drivable"; neither file is `gate.py`. No auth, secrets, data
migration/deletion, deploy/infra/CI config or dependency change is involved, and the change writes no
issue or PR content.

Reachability of the bug is near-nil today, as the author notes — `set -u` makes an unset variable an
error and `--repo-path ""` is already caught — so this is cheap, low-stakes work whose value is that
it lands *with a check*, which is the ordering the whole system exists to enforce.

## Design decisions

- **Decision:** this issue is narrowed to follow-up 1; follow-ups 2 and 3 move to #18.
  - **Why:** the three do not share a tier. Follow-up 1 has a validated discriminating criterion and
    no open design question; the other two are ungradeable without a foreign host and share an
    unresolved question about how hermeticity is constructed. Carried as one issue, the ready third
    inherits `needs-review` for no reason.
  - **Rejected:** splitting three ways (2 and 3 edit adjacent lines and share one question, so you
    would ratify the same decision twice); and keeping all three at `needs-review`.

- **Decision:** the author's full original text stays in the body, fenced rather than trimmed.
  - **Why:** `triage` preserves author text verbatim — augment, never regenerate. The fence at the
    top plus "What we're NOT doing" is what keeps an unattended run from acting on the out-of-scope
    two-thirds.
  - **Rejected:** deleting sections 2, 3 and Meta, which would discard the author's reasoning about
    *why* each was deferred — the most valuable part of the filing.

## What we're NOT doing

- **Follow-up 2 (the `PATH=/usr/bin:/bin` hermeticity assumption) and follow-up 3 (G2 hardcoding
  `$HOME/devel/decafclaw`).** Both live on **#18**. Their text remains above for provenance only.
- **The "Meta" question** — whether review should be solicited earlier, against the freeze commit
  itself. Any change edits `skills/agent-session/phases/pr.md`, i.e. `skills/**`, which `CLAUDE.md`
  makes `needs-review` however cleanly it reduces. It is a conversation for Les, deliberately not
  filed as an issue.
- Asserting the exit code as the criterion. It is `2` on both branches; see the caveat above.
