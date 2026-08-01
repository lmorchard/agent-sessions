# Dogfood fixtures — NOT a real freeze

**These manifests contain a deliberately bad check. Do not reuse them.**

`round-1/checks.md` and `round-2/checks.md` are fixtures built to test the freeze-time
check-reviewer added to `skills/agent-session/references/frozen-checks.md` in this session. They
are **not** a frozen manifest for issue #62 and must not be treated as one — #62's real freeze
happens in #62's own session, against its own criteria.

**What is seeded.** In both rounds, exactly one check is planted: **C1's CHECK line**,
`uv run pytest scripts/test_docs_check.py -k worktree` reports `0 failed`. It is satisfiable
without doing the work — `def test_worktree_x(): assert True` greens it. The shape was chosen
because it is one this project has actually hit (`findings.md`: pytest exits 5 on empty
collection, "it bit twice in one session"), and deliberately **not** a presence-grep: measured
across all 15 `checks.md` manifests in this repo on 2026-08-01, every grep-invoking check is an
absence assertion expecting `0` and not one presence-asserting grep exists, so seeding a presence
grep would have tested a shape that does not occur here.

C1's criterion prose, and all guards, are real: taken from issue #62's triaged body, run for real
against this tree, with observed output recorded rather than imagined.

**The seed was not disclosed to any reviewer.** The `## Adjudication` sections in each manifest
were appended after the reviewers ran, which is what the procedure prescribes.

The reviewers were told not to read anything under `docs/dev-sessions/` other than their own
manifest, so this README could not leak into round 2.
