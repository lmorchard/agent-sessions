> **Archived 2026-08-19. Kept as provenance, not as a finding.**
>
> This is #2's output. It reports `adjacent-risk: none` for every row it enumerates —
> including `threads`, which `findings.md` documents at length as the canonical adjacency
> instance, and `project-gates`, which `prior-art.md` independently nominates as another.
> A sweep whose question was *"what could satisfy this row that is not the thing it names?"*
> and that answered "nothing" against a corpus containing two known instances is a vacuous
> check in a file — `findings.md` defect class 6, in the artifact produced for the issue
> that defines it.
>
> It also reads its conditions out of a `phases/pr.md` that no longer exists, and lists a
> Makefile check set predating `lint` and `typecheck`, so it could not be re-run as written.
>
> Archived rather than deleted: **that the sweep ran and produced nothing is itself the
> useful finding**, and deleting it would leave #2 looking closed on evidence that had
> quietly disappeared.

# Gate Row Adjacency Sweep

Generated for Issue #2.

## Fields from `references/pr-body-template.md`
- Field: `tier` -> `adjacent-risk: none`
- Field: `checks` -> `adjacent-risk: none`
- Field: `guards` -> `adjacent-risk: none`
- Field: `tamper` -> `adjacent-risk: none`
- Field: `freeze` -> `adjacent-risk: none`
- Field: `project-gates` -> `adjacent-risk: none`
- Field: `ci` -> `adjacent-risk: none`
- Field: `threads` -> `adjacent-risk: none`
- Field: `risk-paths` -> `adjacent-risk: none`
- Field: `amendments` -> `adjacent-risk: none`
- Field: `verdict` -> `adjacent-risk: none`
- Field: `reason` -> `adjacent-risk: none`

## Merge conditions from `phases/pr.md`
- Merge condition: Every criterion with a check: `pass` -> `adjacent-risk: none`
- Merge condition: Every human-judgment criterion: graded by a human -> `adjacent-risk: none`
- Merge condition: Every guard still `pass` -> `adjacent-risk: none`
- Merge condition: Tamper diff clean, or every difference logged as an amendment -> `adjacent-risk: none`
- Merge condition: Local project gates green -> `adjacent-risk: none`
- Merge condition: CI checks on the pushed head all pass -> `adjacent-risk: none`
- Merge condition: No unresolved review threads -> `adjacent-risk: none`
- Merge condition: Tier is `auto-ok` (and not downgraded by an amendment) -> `adjacent-risk: none`
- Merge condition: PR touches no risk-gated path -> `adjacent-risk: none`

## Verification conditions from `references/frozen-checks.md`
- Verification condition: Every criterion in `checks.md` with a check: that check ran and passed, per the independent verifier's report — individually observed, by its own command. -> `adjacent-risk: none`
- Verification condition: Every human-judgment criterion: its named evidence was presented and a human graded it. -> `adjacent-risk: none`
- Verification condition: **Every guard still passes**, by its own command. A guard that flipped from pass to fail is a regression this work caused, and it blocks the gate exactly like a failing criterion. -> `adjacent-risk: none`
- Verification condition: The tamper diff is empty, or every difference is explained by a logged amendment. Where `Check files` is empty, the substitutes ran instead and the verdict says `clean-by-substitute`. -> `adjacent-risk: none`
- Verification condition: The project's own gates (`make lint`, `make test`, `make check`) are green. -> `adjacent-risk: none`

## Makefile check prerequisites
- Makefile check: `driver-check` -> `adjacent-risk: none`
- Makefile check: `driver-test` -> `adjacent-risk: none`
- Makefile check: `park-test` -> `adjacent-risk: none`
- Makefile check: `skill-readonly` -> `adjacent-risk: none`
- Makefile check: `docs-check` -> `adjacent-risk: none`
- Makefile check: `assertion-lint` -> `adjacent-risk: none`
- Makefile check: `commit-lint` -> `adjacent-risk: none`
