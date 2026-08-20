#!/usr/bin/env python3
"""Move finished dev-session directories under docs/archive/ and repair inbound links.

Session artifacts are frozen provenance: the point is never to delete them, only to
get them out of the way of the sessions still being worked. `docs/dev-sessions/` is
where a session lives; `docs/archive/dev-sessions/` is where it retires to.

Why this is a script and not `git mv`. Session directories are referenced from at
least three different relative depths -- `dev-sessions/X` from `docs/`,
`../dev-sessions/X` from `docs/archive/`, and `docs/dev-sessions/X` from the repo
root and from prose -- so a bare move leaves dead links that `make docs-check`
correctly fails on. Rather than three sed patterns that each know a depth, this
rewrites per file: for every tracked Markdown file it substitutes the path spelling
that file would have used.

Generic references to `docs/dev-sessions/` itself are deliberately left alone. That
directory still exists and still receives new sessions; only paths naming a *moved*
session are rewritten.

Usage:
    scripts/archive-dev-session.py --before 2026-08-09          # what the epoch rule selects
    scripts/archive-dev-session.py --before 2026-08-09 --apply
    scripts/archive-dev-session.py 2026-07-25-0926-board-driver --apply

Dry-run is the default; nothing moves without --apply. Run `make docs-check`
afterwards -- it link-checks the frozen trees, which is what proves the rewrite.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE = Path("docs/dev-sessions")
ARCHIVE = Path("docs/archive/dev-sessions")

# A session directory is named <YYYY-MM-DD>-<rest>; the date prefix is what --before reads.
SESSION_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def tracked_markdown() -> list[Path]:
    out = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "*.md"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [Path(line) for line in out.splitlines() if line]


def sessions_before(cutoff: str) -> list[str]:
    """Sessions dated before `cutoff`, from both trees.

    Scanning the archive too keeps `--before` meaningful after a partial run: the
    selection stays the same set whether or not the move already happened, so the
    rewrite pass can be re-driven without hand-listing 26 directory names.
    """
    names: list[str] = []
    for tree in (LIVE, ARCHIVE):
        base = ROOT / tree
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if not child.is_dir():
                continue
            m = SESSION_DATE.match(child.name)
            if not m:
                print(f"warning: {child.name} has no YYYY-MM-DD prefix; skipping", file=sys.stderr)
                continue
            if m.group(1) < cutoff and child.name not in names:
                names.append(child.name)
    return sorted(names)


def rewrites_for(doc: Path, session: str) -> list[tuple[re.Pattern[str], str]]:
    """Path spellings of `session` that `doc` could contain, as (pattern, replacement).

    These are regexes rather than plain strings so the rewrite can be idempotent, which
    matters because a partially-applied run has to be safe to re-drive. The trap: the
    `docs/`-relative form `dev-sessions/X` is a *substring* of its own corrected form
    `archive/dev-sessions/X`, so a plain `str.replace` re-run yields
    `archive/archive/dev-sessions/X`. The negative lookbehind is what makes re-running
    a no-op instead of corruption. The other two forms are naturally idempotent -- their
    search text disappears once rewritten -- but they get the same treatment for
    uniformity.
    """
    pairs: list[tuple[re.Pattern[str], str]] = [
        # docs/dev-sessions/X -> docs/archive/dev-sessions/X
        (re.compile(rf"(?<!archive/){re.escape(LIVE.as_posix())}/{re.escape(session)}"),
         f"{ARCHIVE.as_posix()}/{session}"),
    ]

    parent = doc.parent
    if parent == Path("docs"):
        # dev-sessions/X -> archive/dev-sessions/X, but not docs/dev-sessions/X, which
        # the pair above owns, and not an already-corrected archive/dev-sessions/X.
        pairs.append(
            (re.compile(rf"(?<!archive/)(?<!docs/)dev-sessions/{re.escape(session)}"),
             f"archive/dev-sessions/{session}")
        )
    elif parent.is_relative_to(Path("docs/archive")):
        # Both trees moved together, so a ../ walk up to dev-sessions/ shortens a level.
        pairs.append(
            (re.compile(rf"\.\./dev-sessions/{re.escape(session)}"),
             f"dev-sessions/{session}")
        )

    return pairs


MD_LINK = re.compile(r"\]\(([^)\s#]+)([^)]*)\)")


def fix_outbound_links(session: str, apply: bool) -> list[tuple[Path, str, str]]:
    """Repair links *out of* a moved session that broke because it sank a level deeper.

    The inbound rewrites above are only half the job. A session doc saying
    `../../design.md` meant `docs/design.md` from `docs/dev-sessions/X/`; from
    `docs/archive/dev-sessions/X/` that same text now means `docs/archive/design.md`.
    `make docs-check` catches this, which is how it was found.

    Rather than adjust `../` counts by arithmetic, resolve each link against the *old*
    directory and, if it hit a real file, re-derive the path from the *new* directory to
    that same target. Depth-independent, and it fixes `../../archive/handoff-x.md` ->
    `../handoff-x.md` (a link that shortens) as readily as one that lengthens.
    """
    old_dir = ROOT / LIVE / session
    new_dir = ROOT / ARCHIVE / session
    if not new_dir.is_dir():
        return []

    changes: list[tuple[Path, str, str]] = []
    for path in sorted(new_dir.rglob("*.md")):
        rel_within = path.relative_to(new_dir)
        text = path.read_text(encoding="utf-8")

        def repair(m: re.Match[str]) -> str:
            target, suffix = m.group(1), m.group(2)
            if "://" in target or target.startswith("/"):
                return m.group(0)
            here_new = (new_dir / rel_within).parent
            if (here_new / target).exists():
                return m.group(0)  # still resolves; leave it alone
            here_old = (old_dir / rel_within).parent
            resolved = (here_old / target).resolve()
            if not resolved.exists():
                return m.group(0)  # was already broken; not ours to invent a fix for
            fixed = Path(os.path.relpath(resolved, here_new)).as_posix()
            changes.append((path.relative_to(ROOT), target, fixed))
            return f"]({fixed}{suffix})"

        new_text = MD_LINK.sub(repair, text)
        if apply and new_text != text:
            path.write_text(new_text, encoding="utf-8")
    return changes


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sessions", nargs="*", help="session directory names under docs/dev-sessions/")
    ap.add_argument("--before", metavar="YYYY-MM-DD", help="select every session dated before this")
    ap.add_argument("--apply", action="store_true", help="perform the move; otherwise dry-run")
    args = ap.parse_args(argv)

    if args.before and not SESSION_DATE.match(args.before):
        print(f"error: --before wants YYYY-MM-DD, got {args.before!r}", file=sys.stderr)
        return 2

    selected = list(args.sessions)
    if args.before:
        selected.extend(s for s in sessions_before(args.before) if s not in selected)
    if not selected:
        print("error: nothing selected; pass session names or --before YYYY-MM-DD", file=sys.stderr)
        return 2

    # Idempotent: a session already under docs/archive/ needs no move, but its inbound
    # links may still be unrepaired -- which is exactly the state a half-finished run
    # leaves behind. Treat it as move-complete and let the rewrite pass do its half.
    to_move = [s for s in selected if (ROOT / LIVE / s).is_dir()]
    already = [s for s in selected if (ROOT / ARCHIVE / s).is_dir()]
    missing = [s for s in selected if s not in to_move and s not in already]
    if missing:
        for s in missing:
            print(f"error: {s} is under neither {LIVE} nor {ARCHIVE}", file=sys.stderr)
        return 2

    print(f"{len(to_move)} session(s) to move, {len(already)} already archived:")
    for s in to_move:
        print(f"  {LIVE / s}  ->  {ARCHIVE / s}")

    # Plan the link rewrites before moving anything, so a dry-run reports the real set.
    planned: list[tuple[Path, list[tuple[re.Pattern[str], str]]]] = []
    for doc in tracked_markdown():
        text = (ROOT / doc).read_text(encoding="utf-8")
        hits = [pair for s in selected for pair in rewrites_for(doc, s) if pair[0].search(text)]
        if hits:
            planned.append((doc, hits))

    if planned:
        print(f"\nlink rewrites in {len(planned)} file(s):")
        for doc, hits in planned:
            for pattern, new in hits:
                print(f"  {doc}: /{pattern.pattern}/  ->  {new}")
    else:
        print("\nno inbound links to rewrite")

    if not args.apply:
        print("\ndry run; re-run with --apply to perform the move")
        return 0

    # Rewrite first, move second. The reverse order reads each planned file back from a
    # path the move just invalidated -- which is how the first run of this script died
    # after its `git mv` pass and before its rewrite pass.
    for doc, hits in planned:
        path = ROOT / doc
        text = path.read_text(encoding="utf-8")
        for pattern, new in hits:
            text = pattern.sub(new, text)
        path.write_text(text, encoding="utf-8")

    (ROOT / ARCHIVE).mkdir(parents=True, exist_ok=True)
    for s in to_move:
        subprocess.run(
            ["git", "-C", str(ROOT), "mv", str(LIVE / s), str(ARCHIVE / s)],
            check=True,
        )

    outbound: list[tuple[Path, str, str]] = []
    for s in selected:
        outbound.extend(fix_outbound_links(s, apply=True))

    print(f"\nmoved {len(to_move)} session(s); rewrote links in {len(planned)} file(s)")
    if outbound:
        print(f"repaired {len(outbound)} outbound link(s) from the moved sessions:")
        for path, old, new in outbound[:10]:
            print(f"  {path}: {old}  ->  {new}")
        if len(outbound) > 10:
            print(f"  ... and {len(outbound) - 10} more")
    print("now run: make docs-check")
    return 0


if __name__ == "__main__":
    sys.exit(main())
