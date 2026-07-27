#!/usr/bin/env bash
# Tally verdict labels per arm from the raw rep JSON. Counts FIRST LINE only -- the label --
# so a rep that merely mentions another label in its reasoning is not double-counted.
set -euo pipefail
cd "$(dirname "$0")/results"
printf '%-8s %5s %8s %8s %8s %8s\n' arm n FREEZE REPLACE STALE other
for tag in Z C P T Zv2 Cv2 Tv2 Zv3 Cv3 Pv3 Tv3 Rv3 Nv3 Mv3 Dv3 Ev3; do
  files=$(ls "$tag"-[0-9]*.json 2>/dev/null || true)
  [ -n "$files" ] || continue
  n=0 f=0 r=0 s=0 o=0
  for j in $files; do
    n=$((n + 1))
    # First NON-EMPTY line: some reps emit a leading blank line, and head -1 on those
    # scored as "other" -- which silently undercounted a real verdict.
    case "$(jq -r '.result' "$j" | grep -m1 .)" in
      *FREEZE-AS-WRITTEN*) f=$((f + 1)) ;;
      *REPLACE-CHECK*)     r=$((r + 1)) ;;
      *CLOSE-AS-STALE*)    s=$((s + 1)) ;;
      *)                   o=$((o + 1)) ;;
    esac
  done
  printf '%-8s %5s %8s %8s %8s %8s\n' "$tag" "$n" "$f" "$r" "$s" "$o"
done
