# Driver: one state dir per repo, under XDG, so concurrent runs against different repos work

Captured verbatim from https://github.com/lmorchard/agent-sessions/issues/27 (the
`<!-- agent-session:spec -->` marker line stripped). This is a snapshot; the issue is
authoritative.

**Goal:** let the driver run against two repositories concurrently, by making state-directory scoping
structural (one directory per repo, outside every working tree) rather than something the driver
computes.

**Source:** hit for real on 2026-07-29 — a live `make run` against `lmorchard/decafclaw` #657 refused
a `make run-self ISSUE=13` against `lmorchard/agent-sessions`, one minute later, with
`error: refusing to start a second run while an orphan is live`.

## Current state — three facts, each verified by running something

**1. The orphan guard ignores the repo it already records.** The in-flight marker carries the repo in
its `url` field (`agent-session-driver.sh:527-529`), but the guard at `:710-724` reads only `.issue`,
`.started` and `.run_dir`. Reproduced in isolation against a throwaway `--state-dir`: a live marker
naming `https://github.com/lmorchard/decafclaw/issues/657` refused a run requesting
`--repo lmorchard/agent-sessions`, a different repository.

**2. `docs/findings.md:547` claims behaviour the code does not have** — *"Startup now detects a live
orphan and refuses to start a second run **against the same repo**."* The code refuses regardless of
repo. Defect class 1 in miniature: a guard exists, so the claim reads true.

**3. `--classify-only <n>` is already repo-ambiguous, and the collision is live rather than
theoretical.** The lookup at `:732` is `ls -td "$STATE_DIR/runs/$n-"* | head -1` — keyed on issue
number alone, newest wins. Run against a fixture holding two `4-*` run dirs, it silently picks the
newer with no way to say which repo it belongs to. There is a real `runs/4-20260729T013605Z` for
agent-sessions #4 today, and decafclaw also has issues #4, #5, #6 and #7 — agent-sessions spans #1–23,
so **every issue number this repo will ever use collides.** `--classify-only` is the documented
recovery path.

What is *already* right: `runs.jsonl` records a `repo` field on every row, so the ledger is repo-aware.
Only the filesystem layout and the guard are not.

## The shape of the fix

Default the state directory to an XDG path with a per-repo subdirectory:

```
${XDG_STATE_HOME:-$HOME/.local/state}/agent-session/<owner>-<name>/
  runs.jsonl
  inflight.json
  runs/<issue>-<ts>/
```

`--state-dir` keeps working as an explicit override. Everything the alternative designs needed
scoping *logic* for then falls out of the layout: the orphan guard is per-repo because the marker is,
and `--classify-only` stops being ambiguous because each repo has its own `runs/`. No
repo-comparison code is added anywhere.

## Verifiable acceptance criteria

- **C1.** GIVEN a live in-flight marker for repo A, WHEN the driver starts against repo B,
  THEN it SHALL NOT refuse, and SHALL NOT report an orphan.
  **CHECK:** a new case in `driver/test-driver.sh` using the offline `gh`-stub + `--dry-run` pattern at
  `:456-487` — write a marker for `lmorchard/decafclaw` whose `child.pid` is a live process, invoke
  `--repo lmorchard/agent-sessions --dry-run`, and assert the output contains neither
  `refusing to start a second run` nor `ORPHAN STILL RUNNING`.
  **VERIFIED DISCRIMINATING:** yes, ran the failing form. With a live marker for decafclaw #657 and
  `--repo lmorchard/agent-sessions`, the driver printed `ORPHAN STILL RUNNING (pid …, reparented)` and
  died with `error: refusing to start a second run while an orphan is live`. Run against a temp
  `--state-dir`, so it neither read nor wrote live state.

- **C2.** WHEN no `--state-dir` is given, the driver SHALL resolve its state directory to
  `${XDG_STATE_HOME:-$HOME/.local/state}/agent-session/<owner>-<name>/` for the requested repo, and
  SHALL report the resolved path.
  **CHECK:** a case setting `XDG_STATE_HOME` to a temp dir, invoking `--dry-run` with the `gh` stub and
  **no** `--state-dir`, asserting that `$XDG_STATE_HOME/agent-session/lmorchard-agent-sessions/`
  exists afterwards and that the resolved path appears in the output.
  **UNRUN, with the reason named:** a probe that omits `--state-dir` today defaults to
  `./.driver-state`, which is the live directory — it would read the live marker and die at the orphan
  guard, so the assertion would fail for a compounded reason rather than the one it names. It fails by
  construction: `agent-session-driver.sh:41` is `STATE_DIR="./.driver-state"`, a fixed relative path
  with no repo component. **Run it at freeze, once no run is in flight, and record the output.**

- **C3.** GIVEN run directories for the same issue number under two different repos, WHEN
  `--classify-only <n>` runs against one repo, THEN it SHALL resolve a run directory belonging to that
  repo.
  **CHECK:** a case creating `<state>/lmorchard-decafclaw/runs/4-<ts1>/` and
  `<state>/lmorchard-agent-sessions/runs/4-<ts2>/`, then asserting `--classify-only 4` against each
  repo resolves the matching one.
  **VERIFIED DISCRIMINATING:** the ambiguity is real today — running the shipped lookup expression
  from `:732` against a fixture holding `4-20260728T000000Z` and `4-20260729T013605Z` resolved the
  newer one, with nothing in the path identifying a repo. *(That probe ran the expression copied out
  of the driver, which is a replica; the frozen check must invoke the driver itself. `docs/findings.md`
  class 1 instance 9 is what happens when a replica is trusted.)*

## Regression guards

- **G1.** `make driver-test` — no assertion lost, newly skipped, or newly failing. Stated as an
  invariant, not a count.
- **G2.** `make driver-check` — the driver still has no executable merge path.
- **G3.** The existing `./.driver-state/` is not modified or deleted by the change or by the migration.
  It holds the only record of ten prior runs, and `runs.jsonl` there is the source for several figures
  in `docs/findings.md`.
- **G4.** `.driver-state/` stays in `.gitignore`. It becomes vestigial, and removing it would re-open
  the `git add -A` window that has bitten this project twice, for no benefit.

## Tier: `auto-ok`

**Trigger 1 does not fire.** The design decision below is made, C1's oracle exists and was run, and
none of the criteria is satisfiable without the work. C2 is UNRUN for a stated environmental reason
rather than an unresolved question — the assertion it names is exact.

**Trigger 2 does not fire.** The work touches `driver/agent-session-driver.sh`, `driver/test-driver.sh`
and `Makefile`, all named drivable in `CLAUDE.md`'s allowlist. Not `driver/gate.py`, not `skills/**`.
No auth, secrets, data migration/deletion, deploy/infra/CI config or dependency change. It writes no
issue or PR content.

## Design decisions

- **Decision:** the state directory goes under **XDG**, not inside the target repo's clone.
  - **Why:** `~/devel/decafclaw/.gitignore` has **no** `.driver-state` entry, so an in-clone state
    directory would appear as untracked content in every repo the driver touches. `docs/findings.md`
    records that the `.gitignore` entry *"needed the entry before the first run, not after"* — so
    in-clone manufactures that window in every target repo and needs a PR against each one to close it.
    A dirty target tree is also read as signal by two downstream mechanisms: the tamper check's
    "no collateral edits" substitute, and `phases/pr.md` step 4's `git diff origin/main..HEAD`. The
    driver already treats the target tree as something to *watch* — it snapshots `main` before and
    after and warns if it moved (`:548`, `:570`) — and writing into it works against that.
  - **Also:** express runs operate inside `.worktrees/<branch>`, which makes "which tree owns the state"
    ambiguous; and a GHA runner clones fresh every time, so in-clone state could never persist, which
    defeats the ledger.
  - **Rejected:** `$REPO_PATH/.driver-state`; and keeping one shared directory with a repo-aware guard —
    that cannot work, because a single `inflight.json` cannot represent two concurrent runs. The second
    run would overwrite the first's marker, destroying the only evidence a crashed run existed, which is
    the $9.44 failure that marker was added for.

- **Decision:** migrate non-destructively. Split the existing `runs.jsonl` rows by their `repo` field
  into the two new per-repo ledgers, and leave `./.driver-state/` in place as an archive.
  - **Why:** every row already carries `repo`, so the split is mechanical; and nothing is deleted, so
    the ten existing run directories stay readable where they are.
  - **Rejected:** moving the run directories (breaks nothing but gains nothing), and starting fresh
    (discards the provenance several `findings.md` figures rest on).

- **Decision:** keep writing the `repo` field, and keep the per-repo layout predictable, so a
  cross-repo view is `cat "$XDG_STATE_HOME"/agent-session/*/runs.jsonl | jq …`.
  - **Why:** the single ledger is the one thing this change costs, and one glob restores it. Naming the
    mitigation is cheaper than arguing about the cost.

- **Decision:** print the resolved state directory at startup.
  - **Why:** `./.driver-state` was self-evident; an XDG path is not. One log line, and the driver
    already prints a run directory.

## What we're NOT doing

- **Adding any repo-comparison logic to the orphan guard.** The layout makes it unnecessary. If a fix
  finds itself comparing repos, the layout change did not land.
- **Splitting `runs.jsonl`'s schema or dropping the `repo` field.** It stays, precisely so the ledgers
  can be concatenated.
- **Supporting two concurrent runs against the *same* repo.** The guard should still refuse that, and
  C1 must not be satisfied by making the guard permissive — it asserts a *different* repo proceeds, and
  a case asserting the same-repo refusal still holds should be kept.
- **Deleting or rewriting `./.driver-state/`.** See G3.

## Open questions

- **What did this just invalidate?** — answered here rather than left to be discovered. **Issue #6's
  C1 check hardcodes the ledger path**: `jq -r 'select(.outcome=="ci-stale") | .issue'
  .driver-state/runs.jsonl`. After this change that path becomes a frozen archive that never gains a
  row, so the check would read a file that can no longer answer its question. Whichever of the two
  lands second must update the other. **Default if unanswered:** land this one after #6, or update
  #6's check to the per-repo path as part of this work and say so in the PR.
- **Does `findings.md:547`'s wording get corrected in this PR or separately?** **Default:** in this PR
  — it is one clause, and the claim becomes true exactly when this lands.
- **Slug format for the per-repo directory:** `lmorchard-agent-sessions` (flat, one level) versus
  `lmorchard/agent-sessions` (nested). **Default:** flat with a `-`, since it keeps the directory one
  level deep and cannot collide for GitHub's naming rules.
