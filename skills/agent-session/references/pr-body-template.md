# PR body template

Adapted from `dev-session`'s: the Test Plan becomes **per-criterion check results**, and the
body carries a machine-readable **gate block** the board-driver can read without re-deriving
the gate.

```markdown
## Summary
- [What this PR does, drawn from spec.md]
- [Why — the constraint or problem behind it]

## Design Decisions
[Key decisions from spec.md a reviewer should understand without reading the spec.]

## Changes
[What changed, organized by component if multi-component.]

## Acceptance criteria
| id | criterion | check | result |
|---|---|---|---|
| C1 | [one-line gist] | `pytest tests/test_export.py::test_large_export_is_streamed` | pass |
| C2 | [gist] | `pytest tests/test_dedup.py::test_dedup_preserves_distinct_ids` | pass |
| C3 | [gist] | none — human judgment | evidence attached below, ungraded |

Verified by an independent verifier (fresh context, `checks.md` only). Frozen at `a1b2c3d`;
tamper diff clean.

[For each human-judgment criterion: attach or link its EVIDENCE TO PRESENT here.]

## Merge gate

<!-- agent-session:gate -->
```yaml
tier: auto-ok
checks: C1 pass · C2 pass · C3 human-graded-pending
guards: G1 pass · G2 pass
tamper: clean
freeze: a1b2c3d
project-gates: make check green
threads: 0 unresolved
risk-paths: none
amendments: none
verdict: human-merge-required
reason: C3 awaits human grading
```

## References
- Spec: `docs/dev-sessions/{session-dir}/spec.md`
- Checks: `docs/dev-sessions/{session-dir}/checks.md`
- Plan: `docs/dev-sessions/{session-dir}/plan.md`
- Closes #N
```

## The gate block

Field values, so the block stays parseable:

| Field | Values |
|---|---|
| `tier` | `auto-ok` \| `needs-review` \| `needs-review (downgraded: <reason>)` |
| `checks` | `Cn pass` \| `Cn fail` \| `Cn human-graded` \| `Cn human-graded-pending`, `·`-separated |
| `guards` | `Gn pass` \| `Gn REGRESSED`, `·`-separated; `none` if the spec listed no guards |
| `tamper` | `clean` \| `amended (see amendments)` \| `DIRTY — unexplained diff in <path>` |
| `freeze` | the freeze commit sha |
| `project-gates` | `make check green` \| `red: <what failed>` |
| `threads` | `N unresolved` |
| `risk-paths` | `none` \| the risk-gated paths this PR touches |
| `amendments` | `none` \| `Cn: <old> → <new>` |
| `verdict` | `eligible-for-auto-merge` \| `human-merge-required` |
| `reason` | required when the verdict is `human-merge-required` |

**The block reports; it does not act.** Nothing in this skill merges a PR or enables
auto-merge — `eligible-for-auto-merge` means a human or the board-driver *may* merge, and both
are outside the skill.

Keep the block in the PR **body**, refreshed on the final force-push so it reflects the merged
state rather than the pre-review state. If review-cycle fixes change any field, update it.

## Notes on use

- **Title under 70 chars.** Details in the body.
- **Summary explains WHY.** The diff shows what changed. If you're summarizing the diff, ask
  "why was this needed?" and write that instead.
- **Never report a check as `pass` from the implementer's own run.** The result column comes
  from the independent verifier's report.
- **`Closes #N`** auto-closes the linked issue on merge. One per related issue.
