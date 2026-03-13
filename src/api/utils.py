"""
Shared utilities for API route modules.

Centralises: Settings access (cached), contract resolution, JSONB parsing.
"""

import json
import re
from functools import lru_cache
from typing import Any


@lru_cache(maxsize=1)
def get_settings():
    """Return cached Settings instance. Import is deferred to avoid circular imports."""
    from ..config.settings import Settings

    return Settings()


def resolve_contract(symbol: str) -> str:
    """Map base symbol (ES) to active contract code (ESH6).

    Accepts both base symbols and full contract codes. If the symbol already
    contains a digit it is returned unchanged. Falls back to regex matching for
    cases like "VX" → "VXH6" (VIX futures use a different base prefix).
    """
    if any(ch.isdigit() for ch in symbol):
        return symbol
    settings = get_settings()
    for c in settings.contracts:
        if c.base == symbol:
            return c.symbol
    # Regex fallback: "VX" matches "VXH6" when base is "VIX"
    for c in settings.contracts:
        m = re.match(r"^([A-Z0-9]{1,4}?)[A-Z]\d+$", c.symbol)
        if m and m.group(1) == symbol:
            return c.symbol
    return symbol


def parse_jsonb(value: Any, *, default: Any = None) -> Any:
    """Parse asyncpg JSONB field to Python object.

    Returns `default` when value is None or unparseable.
    Pass default={} for tier expansion (features route).
    Pass default=None for optional JOIN data (signals route).
    """
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return default
    return value  # already dict (asyncpg may parse automatically)
