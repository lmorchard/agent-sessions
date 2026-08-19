"""Console output and the driver's clock, in one place with no driver dependencies.

Why this module exists.

Before it, the driver had **five spellings of one output helper set**: `say` defined
four times (`lifecycle`, `parking`, `pr_checks`, and `board` as a trampoline), `log`
twice, `die` twice. Three of those were byte-identical to each other, and `board`'s were
trampolines that reached back through `agent_session_driver` -- the re-export barrel --
to arrive at `lifecycle`'s copies. So writing one line to stdout could take three hops
through an import cycle, and which implementation you got depended on which module you
happened to be in.

Worse, the barrel was also the driver's **clock**. Eight call sites across five modules
read `agent_session_driver.datetime`, not because they wanted the barrel but because
patching that one attribute freezes time for all of them. That is a real and useful
seam -- the full-loop suite depends on it to get deterministic timestamps in
`runs.jsonl` -- but housing it in a module that exists only to re-export other modules
meant every one of those five modules needed a function-local import of the barrel to
break the cycle it created.

So the seam gets a name. `now()` is the clock; patch it, not a stdlib re-export smuggled
through a barrel. This module imports nothing from `agent_sessions.driver`, which is what
lets everything else import it at module scope.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone


def now() -> datetime:
    """The current UTC time, and the driver's single injection point for it.

    Every timestamp the driver records goes through here. Tests freeze time by replacing
    this function (see `tests/driver/test_full_loop.py`), which is why callers must not
    reach for `datetime.now` directly -- doing so silently opts out of the freeze and
    produces a run record that cannot be asserted on.
    """
    return datetime.now(timezone.utc)


def stamp(fmt: str = "%Y%m%dT%H%M%SZ") -> str:
    """`now()` formatted. The default is the run-id format used throughout the ledger."""
    return now().strftime(fmt)


def say(msg: str) -> None:
    """Operator-facing output: the run's narrative, on stdout."""
    sys.stdout.write(f"{msg}\n")


def log(msg: str) -> None:
    """Timestamped progress, on stderr, so it interleaves without polluting stdout."""
    sys.stderr.write(f"{stamp('%H:%M:%SZ')}  {msg}\n")


def die(msg: str, code: int = 2) -> None:
    """Report a fatal configuration or precondition failure and stop."""
    sys.stderr.write(f"error: {msg}\n")
    sys.exit(code)
