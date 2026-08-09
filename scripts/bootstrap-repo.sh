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

echo "==> Bootstrapping repository: $REPO"

echo "--> Creating 'agent-session:spec' label..."
gh label create "agent-session:spec" \
  --repo "$REPO" \
  --color 0E8A16 \
  --description "Issue is fully specified and ready for execution" \
  2>/dev/null || echo "    (Label already exists)"

echo "--> Creating 'agent-session:needs-human' label..."
gh label create "agent-session:needs-human" \
  --repo "$REPO" \
  --color FBCA04 \
  --description "The agent-session driver parked this issue for human ratification" \
  2>/dev/null || echo "    (Label already exists)"

echo "--> Creating 'agent-session:needs-human-interactive' label..."
gh label create "agent-session:needs-human-interactive" \
  --repo "$REPO" \
  --color D93F0B \
  --description "Issue requires an interactive terminal session for visual/aesthetic iteration" \
  2>/dev/null || echo "    (Label already exists)"

echo "--> Creating 'agent-session:gate' label..."
gh label create "agent-session:gate" \
  --repo "$REPO" \
  --color 0E8A16 \
  --description "PR has a merge gate block and is ready for grading" \
  2>/dev/null || echo "    (Label already exists)"

echo "--> Creating 'agent-session:merge-ready' label..."
gh label create "agent-session:merge-ready" \
  --repo "$REPO" \
  --color 2E8A16 \
  --description "Issue is eligible for auto-merge, waiting for human or auto-merge script" \
  2>/dev/null || echo "    (Label already exists)"

echo "==> Done. $REPO is ready for agent-sessions."
