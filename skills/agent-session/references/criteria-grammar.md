# Criteria grammar — EARS & Given-When-Then

Reference for the two forms `acceptance-criteria.md` requires. Pick per criterion: EARS for
event/state/condition-triggered behavior; Given-When-Then for scenario/flow behavior. Both
force a *condition → observable response* shape that maps cleanly to a check.

## EARS (Easy Approach to Requirements Syntax)

Five patterns + one combined. The keyword signals the pattern; every pattern ends in
`the <system> SHALL <observable response>`. (Source: [alistairmavin.com/ears](https://alistairmavin.com/ears/).)

| Pattern | Template | Use for |
|---|---|---|
| Ubiquitous | `The <system> SHALL <response>.` (no keyword) | always-active invariants |
| Event-driven | `WHEN <trigger>, the <system> SHALL <response>.` | response to a triggering event |
| State-driven | `WHILE <precondition>, the <system> SHALL <response>.` | behavior active during a state |
| Optional | `WHERE <feature is included>, the <system> SHALL <response>.` | behavior gated on a feature/config |
| Unwanted | `IF <trigger>, THEN the <system> SHALL <response>.` | error / invalid / abuse handling |
| Complex | `WHILE <precondition>, WHEN <trigger>, the <system> SHALL <response>.` | combined state + event |

Examples:
- Event-driven: `WHEN the mute control is selected, the player SHALL suppress all audio output.`
- State-driven: `WHILE no card is inserted, the ATM SHALL display "insert card".`
- Unwanted: `IF the card number fails the Luhn check, THEN the form SHALL display a validation error and SHALL NOT submit.`

Rules: one clause per keyword (at most one WHILE, one WHEN, etc.); the response is
observable (something a check can inspect); "SHALL" is the obligation, "SHALL NOT" a
prohibition. Keep each criterion single-response where practical — split compound ones.

## Given-When-Then (Gherkin / BDD)

```
GIVEN <initial context / precondition>
WHEN  <action or event>
THEN  <expected observable outcome>
```
Add `AND` / `BUT` to extend any step. One scenario = one behavior.

Example:
```
GIVEN an export is in progress
WHEN  the user disconnects
THEN  the server cancels the export within 2s
AND   frees its buffers
```

## Picking between them

- Single trigger → single response, especially error/state cases → **EARS** (terser).
- Multi-step context or a flow with setup → **Given-When-Then** (the steps carry the setup).
- Either way: the criterion is not finished until it pairs with a runnable CHECK
  (`acceptance-criteria.md`). The grammar makes it *checkable-shaped*; the CHECK makes it
  *checked*.
