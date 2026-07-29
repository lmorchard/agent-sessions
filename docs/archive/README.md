# Archive — closed documents

Nothing in here is appended to any more. **Two different kinds of thing live here, and they do not
have the same trust level** — worth knowing before citing anything.

## 1. The build log — authoritative for history, not for state

**[build-log.md](build-log.md)** is the chronological account of moves 1–5. It is *closed*, not
*superseded*: it remains **the record of what actually happened** — what was run, what it cost, what
broke, and which PR carries the evidence.

It is still cited. [../findings.md](../findings.md) states its rules tersely and points back here for
the incidents that produced them. When a rule like *"state tamper rules as invariants over what a
check asserts, never as whitelists of allowed line forms"* needs its evidence, the story is in the
build log. **Do not discount it just because it sits in an archive.**

What *has* decayed is every time-sensitive claim inside it — test counts, queue snapshots, "still
unexercised" notes, pending lists. Its own header enumerates the specific ones. So:

> **Authoritative about what happened. Not authoritative about what is true now.**

Closed rather than continued because moves 6 and 7 were never written into it — their account went
into the session `notes.md`, and nothing missed it. It had stopped being written two moves before
anyone noticed. Per-run provenance now lives machine-readably in `.driver-state/runs.jsonl`, a move's
narrative in its session `notes.md`, decisions in the issue body on the board, and durable rules in
`findings.md`.

## 2. The handoff briefs — not authoritative at all

Each was a **task brief** written for a fresh Claude Code context to pick up one move. All five
describe finished work.

| Brief | Drove | Outcome |
|---|---|---|
| `handoff-execution-modes.md` | move 1 | the back half — `plan` / `execute` / `pr` / `express` |
| `handoff-express.md` | move 2 | first end-to-end `express` run (decafclaw #586 → PR #665) |
| `handoff-board-driver.md` | move 3 | `driver/agent-session-driver.sh` |
| `handoff-measurement.md` | move 5 | 170 reps; the discriminate rule measured and cut |
| `handoff-restructure.md` | moves 6 **and** 7 | the docs split; then the board, the triage corpus, the gate-parser extraction |

**These are superseded, and several are actively wrong now:**

- `handoff-restructure.md`'s §2b inventory of forward-looking items was already 5-of-11 stale when
  written, and four more entries were found stale during move 6.
- Its §2 describes the amendment policy as an open ambiguity. **It is settled** — both trees; see
  [../design.md](../design.md).
- The "corrections to inherit" lists were folded into [../findings.md](../findings.md) § Verified
  gotchas, which is the maintained version.

They are kept for two reasons. They are the *inputs* to the moves the build log records the *outputs*
of, and it links to them by name — keeping both preserves that pairing. And they are the clearest
evidence for a claim this project makes repeatedly: **fresh context is load-bearing, not hygiene.**
Each brief opens with "corrections to inherit" — things the previous session asserted and later found
false — and reading them in sequence shows how often confident reasoning had to be walked back.

---

For current state read [../design.md](../design.md). For the durable lessons,
[../findings.md](../findings.md). For how to run any of it, [../usage.md](../usage.md).
