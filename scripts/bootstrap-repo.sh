#!/usr/bin/env bash
#
# Bootstrap a target repository for use with the agent-sessions driver.
# Creates necessary labels and preconditions.

set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: bootstrap-repo.sh <owner/name>

Bootstraps a repository with the necessary GitHub labels for the
agent-sessions driver.

Arguments:
  <owner/name>   The target repository (e.g., lmorchard/decafclaw)
USAGE
}

REPO="${1:-}"
if [ -z "$REPO" ] || [ "$REPO" = "-h" ] || [ "$REPO" = "--help" ]; then
  usage
  exit 1
fi

case "$REPO" in
  */*/*|.|..|*/.|*/..|./*|../*) 
    echo "Error: repo must be in 'owner/name' format" >&2
    exit 1 
    ;;
esac

create_label() { # $1 = name, $2 = color, $3 = description
  local err
  if err="$(gh label create "$1" --repo "$REPO" --color "$2" --description "$3" 2>&1)"; then
    echo "    Created label '$1'"
  elif echo "$err" | grep -qi "already exists"; then
    echo "    (Label '$1' already exists)"
  else
    echo "    WARNING: could not create label '$1': $err" >&2
  fi
}

echo "==> Bootstrapping repository: $REPO"

# The label set is read from the driver, not restated here. It used to be a hand-written
# list, and it had drifted: `agent-session:needs-human-interactive` carried the attempt
# counter's colour, and `agent-session:auto-ok` and `agent-session:needs-review` were
# missing entirely, so a freshly bootstrapped repo was still missing two of the labels the
# driver applies. tests/scripts/test_bootstrap_repo.py holds it to the vocabulary.
while IFS=$'\t' read -r name color description; do
  [ -n "$name" ] || continue
  create_label "$name" "$color" "$description"
done < <(uv run python -c '
from agent_sessions.driver import labels

SPEC = [
    (labels.SPEC_LABEL, "0E8A16", "Issue is fully specified and ready for execution"),
    (labels.AUTO_OK_LABEL, "0E8A16", "Verifiable criteria satisfied and ready for execution"),
    (labels.NEEDS_REVIEW_LABEL, "FBCA04", "Requires human review"),
    (labels.PARK_LABEL, "FBCA04", "the agent-session driver parked this issue"),
    (labels.INTERACTIVE_LABEL, "D4C5F9", "interactive CLI session required"),
    (labels.MERGE_READY_LABEL, "2E8A16", "Eligible for auto-merge"),
]
for name, color, description in SPEC:
    print(f"{name}\t{color}\t{description}")
')

echo "==> Ensuring 'Lab Notebook' discussion category exists..."
# Reported, not created: createDiscussionCategory is not a mutation in GitHub's GraphQL
# schema, so a category has to be made by hand in repository settings. This says whether
# it is there. It used to be reached by a relative path under the old top-level driver
# directory, which the Python conversion left pointing at nothing -- the same dead-path
# class as #261's C7. Reached as a module now, so there is no path left to go stale.
uv run python -m agent_sessions.driver.discussion_manager ensure-category --repo "$REPO" || true

echo "==> Done. $REPO is ready for agent-sessions."
