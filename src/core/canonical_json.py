"""The canonical JSON text of a plain object: the one serialization every identity hash is
taken over.

Keys sorted, compact separators, non-ASCII kept as is, and no fallbacks: a NaN or an object JSON
cannot represent raises (`ValueError`, `TypeError`) instead of hashing a stringified guess, so a
hash never depends on an implicit conversion. Changing this function moves every recorded hash.
"""

from __future__ import annotations

import json
from typing import Any


def canonical_json(obj: Any) -> str:
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
