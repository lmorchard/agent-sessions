#!/usr/bin/env bash
#
# Run N reps of one arm and write each rep's raw JSON to results/<arm>-<i>.json.
#
# cwd is /tmp/mt-cwd deliberately: a `claude -p` launched inside this repo would read this
# repo's CLAUDE.md and design.md, which describe the very rule under test. The global
# ~/.claude/CLAUDE.md still leaks into every run and cannot be suppressed, so every effect
# measured here is a LOWER BOUND.
#
# Usage: run.sh <Z|C|T> [reps] [v1|v2]

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ARM="${1:?usage: run.sh <Z|C|P|T> [reps] [v1|v2|v3]}"
REPS="${2:-5}"
VER="${3:-v1}"
NEUTRAL_CWD="/tmp/mt-cwd"
TAG="$ARM"
[ "$VER" = "v1" ] || TAG="$ARM$VER"

mkdir -p "$HERE/results" "$NEUTRAL_CWD"
python3 "$HERE/build-prompt.py" "$ARM" "$VER" > "$HERE/results/prompt-$TAG.txt"

for i in $(seq 1 "$REPS"); do
  out="$HERE/results/$TAG-$i.json"
  [ -s "$out" ] && { echo "skip $TAG-$i (exists)"; continue; }
  ( cd "$NEUTRAL_CWD" && claude -p \
      --output-format json \
      --allowedTools '' \
      --disallowedTools 'Bash,Read,Write,Edit,Glob,Grep,Task,WebFetch,WebSearch,NotebookEdit,TodoWrite' \
      < "$HERE/results/prompt-$TAG.txt" ) > "$out"
  printf '%s-%s  %s  $%s  turns=%s\n' "$TAG" "$i" \
    "$(jq -r '.result | split("\n")[0]' "$out")" \
    "$(jq -r '.total_cost_usd' "$out")" \
    "$(jq -r '.num_turns' "$out")"
done
