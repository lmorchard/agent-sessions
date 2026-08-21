# design.md — superseded sections

> **Archived 2026-08-19 from [../design.md](../design.md). Provenance, not guidance.**
>
> Three sections, each superseded by a decision recorded in `design.md`'s own **Resolved
> decisions**, and two of which said so in their own headings while sitting in the live document.
> A reader arriving at `design.md` had to get several screens in before learning that what they
> had just read no longer described the system.
>
> Moved rather than deleted because the *reasoning* in each is still the record of how a decision
> was reached, and `design.md`'s value is precisely that it preserves reasoning trails. What it
> should not do is present a superseded trail at the same altitude as the current design.
>
> - **The two-skill system** — the original sketch. It shipped as one skill with a multi-mode
>   dispatcher. The grilling-derived mapping of how `intake` works is the durable part, and
>   `docs/orientation.md` carries the live version.
> - **The open decision** — whether the phase-3 gate list gets a finite exit condition.
>   Dissolved 2026-08-10 when phase 3 stopped being pursued.
> - **Dropped in this reconciliation** — a one-time move-7 bookkeeping list of items verified
>   closed or unactionable. Its whole function was to stop them being re-added once; it has
>   discharged that.

## The two-skill system (the original sketch — architecture superseded)

**Read this for the reasoning, not the shape.** It shipped as **one skill with a multi-mode
dispatcher**, not two skills — see [What is built](../design.md#what-is-built), which explains why. The grilling
mapping below still describes how `intake` actually works, which is why the section is kept.


### intake skill (grilling-derived, human-in-loop)

Lives at the weak-oracle front end. Job: turn a wishlist stub into a spec whose criteria
are runnable checks, plus an escalation tier — and emit a filable issue.

Built on Matt Pocock's [grilling skill](https://github.com/mattpocock/skills/blob/main/skills/productivity/grilling/SKILL.md),
which is a near-perfect engine. Its mechanics map directly:

- **"Probe the environment for factual matters rather than asking"** = the
  research-subagents-then-plan instinct. The skill dispatches Explore/research agents to
  answer *factual* questions about the codebase (does this pattern exist? current shape?
  is there a test harness?) and spends the human's attention only on *decisions*.
- **"Provide your recommended answer alongside each question"** = kills the overhead risk.
  Inverts authoring effort: instead of "what are the acceptance criteria?" (blank page),
  the skill — having researched — *proposes* criteria as runnable checks and the human
  ratifies/corrects. Fast triage, not a dreaded form.
- **"One question at a time, walk the decision tree resolving dependencies"** = the spine:
  definition → scope boundaries → each criterion → (derived) tier.
- **"Don't act until shared understanding is confirmed"** = the human-in-loop gate.

What intake *adds* on top of grilling (the thin, opinionated layer):

1. **A fixed target schema** instead of open-ended "shared understanding" — driving toward
   *definition + verifiable criteria + escalation tier*; done when those slots are filled.
2. **Verifiability as the per-branch success test** — refuses to close a criterion while
   it's still a wish; its recommended answer is *always* a runnable check, and "how would
   you actually know?" is the standing follow-up.
3. **An output artifact** — emits the filable issue body + labels, tier *inferred* from
   whether every criterion resolved to a check (all checks → `auto-ok`; any "human decides"
   → `needs-review`).

Scope guardrail: intake is for **heavier issues only**. Small/mechanical ones skip it.

### execution skill (self-driving, autonomous middle)

Phase 1 above. Consumes a well-specified issue; runs the loop; stops at the merge gate.

### shared contract

The seam between intake's *output* and execution's *input*: the acceptance-criteria format
+ escalation labels. Design once, both read from it. (In the spirit of decafclaw's
"don't hand-maintain parallel field lists that rot in lockstep.")

---

### The open decision (Superseded)

*Superseded 2026-08-10 by Decision 1 (see Resolved decisions) — phase 3 is not pursued, dissolving this question. The reasoning below is preserved as load-bearing context.*

**Les's call: does the phase-3 gate list get a finite exit condition?** It has grown by roughly one gate per session —
first the CI hole, then the merge-block hook, then the amendment policy (**now settled**, see
Resolved decisions) and the sweep. Each addition has been a correct call individually. A finite
exit condition would be better than a list that grows as fast as it is worked. *Not* an argument to
rewrite the phased rollout, and note the premise is weaker than it looks: the PRs **do** land, by
hand and quickly.

Two inputs for that decision, both verified from primary sources in move 7
([prior-art.md](../prior-art.md#leads-1-3--surveyed-and-verified-move-7-2026-07-28)):

- **ITIL supplies the finite exit condition this list lacks.** A "standard change" is pre-authorized
  on three conditions together: documented procedure, risk formally accepted **in advance**, and
  **prior runs have proven the outcome predictable.** The governance body pre-approves the
  *template*, not the instance. Our `auto-ok` is stamped **per issue** on its own criteria, so we
  have no notion of *"this class of change is safe because N instances landed cleanly"* — which is
  precisely an evidence-based stopping rule rather than a growing list of gates.
- **Renovate treats "up-to-date and green" as a *precondition* of automerging**, not as a validity
  check applied after a verdict is published. Our gate derives a verdict and *then* asks whether the
  commit still ships; theirs cannot reach the question. That ordering is cheap to adopt and would
  make one whole class of `ci-stale` unreachable.

---

### Dropped in this reconciliation — verified closed or unactionable

- ~~The wrong correction still sits in decafclaw #710's body.~~ **Resolved** — the retraction is in
  the body now, and names the fabrication as fabricated.
- ~~Board transitions silently no-op on decafclaw.~~ **Resolved** in move 2b: `github-projects.md`
  now locates the declaration by content and reports `board: not configured` when there is none.
- ~~Running the project gates dirties decafclaw's tree.~~ **Resolved** by decafclaw #717 — verified
  `npm ci` in decafclaw's `Makefile`. The generalisable hazard (a verification target running a
  command whose job is to mutate) is kept in `findings.md`.
- ~~A larger `intake` vehicle so multi-phase `execute` gets a real run.~~ **Duplicate** of item 7.
- ~~The standing evidence gap.~~ **Not a task** — it is a standing limit, recorded as one in
  [findings.md](../findings.md#the-standing-limit-this-projects-own-oracle-is-too-expensive). At
  ~$50 and half a session per rule, the unmeasured rules will not all get measured, and listing
  them as work would imply otherwise.
- ~~An interactive-intake check of the empty-state observation.~~ **Dropped: the referent is gone.**
  The phrase survives nowhere else in the repo except an example branch name in
  `session-setup.md`. Nobody can act on it. A clean example of why prose is a bad backlog.
