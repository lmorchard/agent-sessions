# agent-sessions — conventions

**Read [CLAUDE.md](CLAUDE.md).** It is this repository's single instruction file, and it
applies whatever harness you are running under. Everything that used to be duplicated
here — the risk-gated path allowlist, the governing principle, the skill architecture,
the documentation rules, the working conventions — lives there and only there.

This file exists because some harnesses look for `AGENTS.md` by name. It is a pointer,
not a second source of truth.

## Why it is a pointer and not a copy

The two files were byte-identical, and `docs_check.check_risk_policy_parity` guarded
only the `Risk-gated paths` section. That section stayed in sync. Everything outside it
drifted, in three ways that are worth naming because they are what a copy does:

- a find-and-replace rewrote a real filesystem path into one that exists nowhere,
  resolving on one machine only because its filesystem is case-insensitive;
- a second invented a `codex -p` flag meaning "print". `-p` is `--profile`, so it would
  not have errored — it would have silently eaten the next argument. Non-interactive
  Codex is `codex exec`;
- one section lost a rule from this file alone, and the surviving copy was the stale one.

The guarded part held and the unguarded remainder did not. There is no bound on how much
unguarded remainder there will be, so the fix is to have no remainder.

`docs_check` now accepts this shape and checks the two ways it can be wrong: a pointer
that names no instruction file, and a pointer whose target has no policy to point at. A
file that keeps its own `## Risk-gated paths` section is not treated as a pointer, however
prominently it also links here — that half-migrated state is the one this replaced.
