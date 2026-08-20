# Plan: the board-driver (move 3)

Spec: [spec.md](spec.md). Short by design — this is one script plus a test, not a multi-phase
feature. Phases are ordered so each is verifiable before the next depends on it.

## Phase 0 — permission mechanics, measured not assumed

**Done, ahead of the script**, because `dontAsk` turns a wrong permission syntax into a mid-run
stall and the whole "nothing merges" guarantee rests on one pattern matching.

Three `claude -p` probes against `/tmp/permtest`, with the filesystem as the oracle rather than the
model's own account of what it was allowed to do. Results in [notes.md](notes.md); they corrected
`design.md` and fixed the script's flag syntax.

## Phase 1 — the script skeleton and `select`

`driver/agent-session-driver.sh`. Arg parsing, state dir, logging, then the `select` stage.

- One `gh issue list --limit 500 --json number,title,body` call; filter in `jq`.
- Tier read from an **anchored** `^## Tier:` line. Anchoring is load-bearing: #585's own tier
  paragraph contains the string `needs-review`, so an unanchored match reads both tiers.
- Exclusion reasons emitted per candidate. Board column fetched with an explicit `--limit` and
  reported as advisory.

Verified by: `--dry-run` against decafclaw — C2.

## Phase 2 — `classify`, against fixtures first

The gate-block parser and the outcome mapping. Written and tested against **fixture text**, not a
live PR, so the classifier is exercised on `pending` / `human-merge-required` /
`eligible-for-auto-merge` / missing-block without needing four real runs to produce them.

`driver/test-driver.sh` holds the fixtures. Verified by C3.

## Phase 3 — `invoke`, `record`, `report`

The `claude -p` call with the flags Phase 0 settled, the run directory, `runs.jsonl`,
`parked.jsonl`, the closing summary. Denial detection greps the saved stream for the two denial
messages Phase 0 identified.

## Phase 4 — the merge self-check and the Makefile

`make driver-check` (greps the driver's own source for merge verbs) and `make driver-test`
(fixtures), plus `make check` running both. The repo has no Makefile yet; this creates it.

Verified by C1.

## Phase 5 — the real run against #585

Full unattended run. The deliverable is as much the *account* of where it needed a human as the PR
itself. Nothing merges.

Verified by C4 + G1 + G2.

## Phase 6 — record

`design.md` move-3 section (including the three corrections to the capability ladder),
`handoff-board-driver.md` turned from task into record, `notes.md`, journal entry.

## Ordering constraint

Phase 5 comes last and only once C1–C3 pass. A first real run whose classifier has never been
exercised would spend real money to test parsing, and would misreport the outcome if the parser is
wrong — which is the one failure this driver cannot afford, since the classifier's output is the
only thing anybody reads.
