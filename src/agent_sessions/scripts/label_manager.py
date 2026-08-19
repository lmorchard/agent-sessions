#!/usr/bin/env python3
"""Workflow label manager for agent-sessions.

Enforces state invariants and valid transitions on GitHub issue and PR labels.
"""

import argparse
import subprocess
import sys

# Standard label vocabulary
SPEC_LABEL = "agent-session:spec"
AUTO_OK_LABEL = "agent-session:auto-ok"
NEEDS_REVIEW_LABEL = "agent-session:needs-review"
PARK_LABEL = "agent-session:needs-human"
INTERACTIVE_LABEL = "agent-session:needs-human-interactive"
MERGE_READY_LABEL = "agent-session:merge-ready"
ATTEMPT_LABELS = [
    "agent-session:attempt-1",
    "agent-session:attempt-2",
    "agent-session:attempt-3",
]


def run_gh(cmd: list[str], repo: str | None = None) -> str:
    full_cmd = ["gh"] + cmd
    if repo:
        full_cmd.extend(["--repo", repo])
    res = subprocess.run(full_cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"gh command failed: {' '.join(full_cmd)}\n{res.stderr.strip()}")
    return res.stdout.strip()


def ensure_label_exists(name: str, color: str, description: str, repo: str | None = None) -> None:
    """Create `name` if absent. Tolerates "already exists" and nothing else.

    The bare `except RuntimeError: pass` made a 403 from a read-only token look exactly
    like the intended already-exists case, so a token that could not create labels
    reported success and the caller went on to reference a label that was never made.
    """
    try:
        run_gh(["label", "create", name, "--color", color, "--description", description], repo=repo)
    except RuntimeError as e:
        if "already exists" not in str(e).lower():
            raise


def removable(issue: int, wanted: list[str], repo: str | None = None, override: str | None = None) -> list[str]:
    """`wanted`, narrowed to labels the issue actually carries.

    `gh issue edit --remove-label X` exits 0 when the *issue* lacks X but the repo
    has it, which is the case findings.md records. It **errors** when the repo has
    no such label at all -- and a target repo only has the labels something already
    created, so removing `agent-session:needs-human-interactive` from a repo that
    has never parked interactively fails the whole edit, including the add.

    A label present on the issue necessarily exists in the repo, so filtering this
    way is both correct and strictly cheaper than the unconditional list.
    """
    current = set(get_current_labels(issue, repo=repo, override=override))
    return [label for label in wanted if label in current]


def edit_issue_labels(issue: int, add: list[str] | None = None, remove: list[str] | None = None, repo: str | None = None) -> None:
    cmd = ["issue", "edit", str(issue)]
    if add:
        for a in add:
            cmd.extend(["--add-label", a])
    if remove:
        for r in remove:
            cmd.extend(["--remove-label", r])
    run_gh(cmd, repo=repo)


def get_current_labels(issue: int, repo: str | None = None, override: str | None = None) -> list[str]:
    """The issue's current labels. Raises rather than reporting "no labels" on failure.

    This used to `except Exception: return []`, which made a rate limit, an auth error
    and a genuinely unlabelled issue indistinguishable -- and every caller reads the
    result as fact:

    - `validate_transition` computes `is_parked` from it, so an empty list means "not
      parked" and the guard permits re-speccing or re-attempting a parked issue;
    - `removable` narrows every remove list with it, so an empty list silently skips
      removals the command was asked to perform.

    Both failure modes are a null rendering as a positive, which is this project's
    defect class 2. Propagating lets `main` exit non-zero, and lets the driver's callers
    -- which wrap these invocations in `except Exception` -- degrade to a no-op instead
    of a wrong action.
    """
    if override is not None:
        return [l.strip() for l in override.split(",") if l.strip()]
    out = run_gh(["issue", "view", str(issue), "--json", "labels", "--jq", ".labels[].name"], repo=repo)
    return [l.strip() for l in out.splitlines() if l.strip()]


def validate_transition(command: str, current_labels: list[str], args: argparse.Namespace) -> str | None:
    if getattr(args, "force", False):
        return None

    is_parked = PARK_LABEL in current_labels or INTERACTIVE_LABEL in current_labels

    if command == "spec":
        if is_parked:
            return (
                f"Transition Error: Cannot apply '{SPEC_LABEL}' to issue #{args.issue} "
                f"because it is currently parked with '{PARK_LABEL}'. "
                f"The human must remove the parking label (or run 'unpark') after reviewing feedback "
                f"before the spec can be ratified."
            )
    elif command == "attempt":
        if is_parked:
            return (
                f"Transition Error: Cannot start attempt {args.count} on issue #{args.issue} "
                f"because it is currently parked with '{PARK_LABEL}'. "
                f"The issue must be unparked before execution attempts can resume."
            )
    elif command == "merge-ready":
        if is_parked:
            return (
                f"Transition Error: Cannot set '{MERGE_READY_LABEL}' on issue #{args.issue} "
                f"because it is currently parked. Unpark the issue first."
            )

    return None


def cmd_spec(args: argparse.Namespace) -> None:
    ensure_label_exists(SPEC_LABEL, "0E8A16", "Verifiable EARS criteria & tier applied", repo=args.repo)
    tier_label = AUTO_OK_LABEL if getattr(args, "tier", "auto-ok") == "auto-ok" else NEEDS_REVIEW_LABEL
    other_tier = NEEDS_REVIEW_LABEL if getattr(args, "tier", "auto-ok") == "auto-ok" else AUTO_OK_LABEL
    ensure_label_exists(tier_label, "0E8A16" if getattr(args, "tier", "auto-ok") == "auto-ok" else "FBCA04", "Tier label", repo=args.repo)
    to_remove = removable(args.issue, [PARK_LABEL, INTERACTIVE_LABEL, other_tier] + ATTEMPT_LABELS,
                          repo=args.repo, override=getattr(args, "current_labels", None))
    edit_issue_labels(args.issue, add=[SPEC_LABEL, tier_label], remove=to_remove, repo=args.repo)
    print(f"Applied {SPEC_LABEL} ({tier_label}) to #{args.issue} and cleared parking/attempt labels.")


def cmd_auto_ok(args: argparse.Namespace) -> None:
    ensure_label_exists(AUTO_OK_LABEL, "0E8A16", "Verifiable criteria satisfied and ready for execution", repo=args.repo)
    edit_issue_labels(args.issue, add=[AUTO_OK_LABEL], remove=[NEEDS_REVIEW_LABEL], repo=args.repo)
    print(f"Applied {AUTO_OK_LABEL} to #{args.issue}.")


def cmd_needs_review(args: argparse.Namespace) -> None:
    ensure_label_exists(NEEDS_REVIEW_LABEL, "FBCA04", "Requires human review", repo=args.repo)
    edit_issue_labels(args.issue, add=[NEEDS_REVIEW_LABEL], remove=[AUTO_OK_LABEL], repo=args.repo)
    print(f"Applied {NEEDS_REVIEW_LABEL} to #{args.issue}.")


def cmd_park(args: argparse.Namespace) -> None:
    target_label = INTERACTIVE_LABEL if args.interactive else PARK_LABEL
    other_label = PARK_LABEL if args.interactive else INTERACTIVE_LABEL
    ensure_label_exists(PARK_LABEL, "FBCA04", "the agent-session driver parked this issue", repo=args.repo)
    if args.interactive:
        ensure_label_exists(INTERACTIVE_LABEL, "D4C5F9", "interactive CLI session required", repo=args.repo)

    to_remove = removable(args.issue, [other_label], repo=args.repo,
                          override=getattr(args, "current_labels", None))
    edit_issue_labels(args.issue, add=[target_label], remove=to_remove, repo=args.repo)
    print(f"Parked #{args.issue} with {target_label}.")


def cmd_unpark(args: argparse.Namespace) -> None:
    to_remove = removable(args.issue, [PARK_LABEL, INTERACTIVE_LABEL], repo=args.repo,
                          override=getattr(args, "current_labels", None))
    if not to_remove:
        print(f"Unparked #{args.issue}: nothing to clear.")
        return
    edit_issue_labels(args.issue, remove=to_remove, repo=args.repo)
    print(f"Unparked #{args.issue} and cleared parking labels.")


def cmd_attempt(args: argparse.Namespace) -> None:
    if args.count < 1 or args.count > 3:
        raise ValueError("Attempt count must be between 1 and 3.")

    attempt_label = f"agent-session:attempt-{args.count}"
    ensure_label_exists(attempt_label, "D93F0B", "Execution attempt counter", repo=args.repo)

    other_attempts = [l for l in ATTEMPT_LABELS if l != attempt_label]
    to_remove = removable(args.issue, [PARK_LABEL, INTERACTIVE_LABEL] + other_attempts,
                          repo=args.repo, override=getattr(args, "current_labels", None))
    edit_issue_labels(args.issue, add=[attempt_label], remove=to_remove, repo=args.repo)
    print(f"Set {attempt_label} on #{args.issue}.")


def cmd_clear_attempts(args: argparse.Namespace) -> None:
    to_remove = removable(args.issue, ATTEMPT_LABELS, repo=args.repo,
                          override=getattr(args, "current_labels", None))
    if not to_remove:
        print(f"No attempt labels on #{args.issue}.")
        return
    edit_issue_labels(args.issue, remove=to_remove, repo=args.repo)
    print(f"Cleared attempt labels on #{args.issue}.")


def cmd_merge_ready(args: argparse.Namespace) -> None:
    ensure_label_exists(MERGE_READY_LABEL, "2E8A16", "Eligible for auto-merge", repo=args.repo)
    to_remove = removable(args.issue, [PARK_LABEL, INTERACTIVE_LABEL] + ATTEMPT_LABELS,
                          repo=args.repo, override=getattr(args, "current_labels", None))
    edit_issue_labels(args.issue, add=[MERGE_READY_LABEL], remove=to_remove, repo=args.repo)
    print(f"Set {MERGE_READY_LABEL} on #{args.issue} and cleared parking/attempt labels.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage workflow labels for agent-sessions")
    parser.add_argument("--repo", help="Target repository (owner/repo)")
    parser.add_argument("--current-labels", help="Comma-separated current labels (avoids gh view query)")
    parser.add_argument("--force", action="store_true", help="Bypass transition safety checks")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # spec
    p_spec = subparsers.add_parser("spec", help="Mark issue as specified (spec)")
    p_spec.add_argument("--issue", type=int, required=True, help="Issue number")
    p_spec.add_argument("--tier", choices=["auto-ok", "needs-review"], default="auto-ok", help="Tier label")

    # auto-ok
    p_aok = subparsers.add_parser("auto-ok", help="Set auto-ok tier label")
    p_aok.add_argument("--issue", type=int, required=True, help="Issue number")

    # needs-review
    p_nr = subparsers.add_parser("needs-review", help="Set needs-review tier label")
    p_nr.add_argument("--issue", type=int, required=True, help="Issue number")

    # park
    p_park = subparsers.add_parser("park", help="Park issue (needs-human)")
    p_park.add_argument("--issue", type=int, required=True, help="Issue number")
    p_park.add_argument("--interactive", action="store_true", help="Requires interactive session")

    # unpark
    p_unpark = subparsers.add_parser("unpark", help="Unpark issue")
    p_unpark.add_argument("--issue", type=int, required=True, help="Issue number")

    # attempt
    p_attempt = subparsers.add_parser("attempt", help="Set attempt count label")
    p_attempt.add_argument("--issue", type=int, required=True, help="Issue number")
    p_attempt.add_argument("--count", type=int, required=True, choices=[1, 2, 3], help="Attempt count")

    # clear-attempts
    p_clear = subparsers.add_parser("clear-attempts", help="Clear attempt labels")
    p_clear.add_argument("--issue", type=int, required=True, help="Issue number")

    # merge-ready
    p_mr = subparsers.add_parser("merge-ready", help="Set merge-ready label")
    p_mr.add_argument("--issue", type=int, required=True, help="Issue number")

    args = parser.parse_args(argv)

    try:
        current = get_current_labels(args.issue, repo=args.repo, override=args.current_labels)
    except RuntimeError as e:
        # Fail closed: without the issue's labels neither the transition guard nor the
        # remove-list narrowing can be trusted, so do not proceed on a guess.
        print(f"Error: could not read labels for #{args.issue}: {e}", file=sys.stderr)
        return 1

    err = validate_transition(args.command, current, args)
    if err:
        print(f"Error: {err}", file=sys.stderr)
        return 1

    try:
        if args.command == "spec":
            cmd_spec(args)
        elif args.command == "auto-ok":
            cmd_auto_ok(args)
        elif args.command == "needs-review":
            cmd_needs_review(args)
        elif args.command == "park":
            cmd_park(args)
        elif args.command == "unpark":
            cmd_unpark(args)
        elif args.command == "attempt":
            cmd_attempt(args)
        elif args.command == "clear-attempts":
            cmd_clear_attempts(args)
        elif args.command == "merge-ready":
            cmd_merge_ready(args)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
