# Archive — spent task briefs

Each of these was a **handoff**: a task brief written for a fresh Claude Code context to pick up
one move of the project. All five describe work that is finished.

| Brief | Drove | Outcome |
|---|---|---|
| `handoff-execution-modes.md` | move 1 | the back half — `plan` / `execute` / `pr` / `express` |
| `handoff-express.md` | move 2 | first end-to-end `express` run (decafclaw #586 → PR #665) |
| `handoff-board-driver.md` | move 3 | `driver/agent-session-driver.sh` |
| `handoff-measurement.md` | move 5 | 170 reps; the discriminate rule measured and cut |
| `handoff-restructure.md` | moves 6 **and** 7 | the docs split; then the board, the triage corpus, the gate-parser extraction |

## Why they are kept rather than deleted

They are the *inputs* to the moves that [../build-log.md](../build-log.md) records the *outputs* of,
and the build log links to them by name. Keeping them preserves that pairing.

They are also the clearest evidence for a claim the project makes repeatedly: **fresh context is
load-bearing, not hygiene.** Each brief opens with "corrections to inherit" — things the previous
session asserted and later found false — and reading them in sequence shows how often confident
reasoning had to be walked back.

## Do not treat these as current

**Nothing here is authoritative.** Every brief was accurate when written and several have been
overtaken:

- `handoff-restructure.md`'s §2b inventory of forward-looking items was already 5-of-11 stale when
  written, and four more entries were found stale during move 6.
- Its §2 describes the amendment policy as an open ambiguity. **It is settled** — both trees; see
  [../design.md](../design.md).
- The "corrections to inherit" lists were folded into
  [../findings.md](../findings.md) § Verified gotchas, which is the maintained version.

For current state, read [../design.md](../design.md). For durable lessons,
[../findings.md](../findings.md). For how to run any of it, [../usage.md](../usage.md).
