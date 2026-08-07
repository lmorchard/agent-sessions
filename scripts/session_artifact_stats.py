#!/usr/bin/env python3
"""Compute session artifact statistics split on presence of checks.md.

Reproduces the table in docs/findings.md item 4, ensuring the counts are
derived mechanically rather than transcribed.
"""

from __future__ import annotations

import sys
from pathlib import Path
import statistics


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    dev_sessions_path = root / "docs" / "dev-sessions"
    if len(sys.argv) > 1:
        dev_sessions_path = Path(sys.argv[1]).resolve()

    if not dev_sessions_path.exists():
        print(f"Error: {dev_sessions_path} does not exist", file=sys.stderr)
        return 1

    without_checks: list[int] = []
    with_checks: list[int] = []

    # Find session directories. A session directory is a direct or indirect child
    # containing markdown/text files or specifically dev-session dirs.
    # In agent-sessions, dev-sessions/ has subdirs like YYYY-MM-DD-HHMM-slug.
    for child in sorted(dev_sessions_path.iterdir()):
        if not child.is_dir():
            continue
        # Skip special measurement/microtest subfolders if they don't represent sessions,
        # or treat session dirs as any directory containing markdown files.
        # Let's count all markdown files within each session directory.
        md_files = list(child.rglob("*.md"))
        if not md_files:
            continue

        total_lines = 0
        has_checks = (child / "checks.md").exists() or any(
            f.name == "checks.md" for f in md_files
        )

        for mf in md_files:
            try:
                total_lines += len(mf.read_text(encoding="utf-8", errors="ignore").splitlines())
            except Exception:
                pass

        if has_checks:
            with_checks.append(total_lines)
        else:
            without_checks.append(total_lines)

    def stats(values: list[int]) -> tuple[int, int, float, int, int]:
        n = len(values)
        if n == 0:
            return 0, 0, 0.0, 0, 0
        med = int(round(statistics.median(values)))
        mean = round(statistics.mean(values), 1)
        return n, med, mean, min(values), max(values)

    n_no, med_no, mean_no, min_no, max_no = stats(without_checks)
    n_yes, med_yes, mean_yes, min_yes, max_yes = stats(with_checks)

    print("| population | n | median lines | mean | min | max |")
    print("|---|---|---|---|---|---|")
    print(f"| without `checks.md` (`dev-session` era) | {n_no} | **{med_no}** | {mean_no} | {min_no} | {max_no} |")
    print(f"| with `checks.md` (`agent-session` runs) | {n_yes} | **{med_yes}** | {mean_yes} | {min_yes} | {max_yes} |")

    return 0


if __name__ == "__main__":
    sys.exit(main())
