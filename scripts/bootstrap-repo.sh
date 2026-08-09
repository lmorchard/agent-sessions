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

create_label "agent-session:spec" "0E8A16" "Issue is fully specified and ready for execution"
create_label "agent-session:needs-human" "FBCA04" "The agent-session driver parked this issue for human ratification"
create_label "agent-session:needs-human-interactive" "D93F0B" "Issue requires an interactive terminal session for visual/aesthetic iteration"
create_label "agent-session:gate" "0E8A16" "PR has a merge gate block and is ready for grading"
create_label "agent-session:merge-ready" "2E8A16" "Issue is eligible for auto-merge, waiting for human or auto-merge script"

echo "==> Ensuring 'Lab Notebook' discussion category exists..."
if err="$(gh api graphql -F repositoryId="$(gh repo view "$REPO" --json id --jq .id)" -f query='mutation($repositoryId: ID!) { createDiscussionCategory(input: { repositoryId: $repositoryId, name: "Lab Notebook", emoji: "📓" }) { discussionCategory { id name } } }' 2>&1)"; then
  echo "    Created 'Lab Notebook' discussion category"
elif echo "$err" | grep -qi "already exists" || echo "$err" | grep -qi "name already exists"; then
  echo "    (Discussion category 'Lab Notebook' already exists)"
else
  echo "    WARNING: could not create discussion category 'Lab Notebook': $err" >&2
fi

echo "==> Done. $REPO is ready for agent-sessions."
