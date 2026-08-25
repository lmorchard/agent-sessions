"""Small structured logger that deliberately accepts only operational fields."""

from __future__ import annotations

import json
import sys
from typing import Any

_SAFE = {"delivery_guid", "event_type", "action", "repository_id", "disposition", "elapsed_ms", "message"}


def emit(event: str, **fields: Any) -> None:
    payload = {"event": event, **{key: value for key, value in fields.items() if key in _SAFE}}
    print(json.dumps(payload, sort_keys=True), file=sys.stderr)
