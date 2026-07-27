"""
Shared utilities for API route modules.

Centralises: Settings access (cached), contract resolution, JSONB parsing,
DB-error-to-HTTPException translation.
"""

import functools
import json
import re
from collections.abc import Awaitable, Callable
from functools import lru_cache
from typing import Any

import structlog
from fastapi import HTTPException


@lru_cache(maxsize=1)
def get_settings():
    """Return cached Settings instance. Import is deferred to avoid circular imports."""
    from ..config.settings import Settings

    return Settings()


def resolve_contract(symbol: str) -> str:
    """Map base symbol (ES) to active contract code (ESH6).

    Accepts both base symbols and full contract codes. If the symbol already
    contains a digit it is returned unchanged. Falls back to regex matching for
    cases like "VX" -> "VXH6" (VIX futures use a different base prefix).

    Uses get_active_contracts() (60s TTL cache) as the source list - no
    direct DB query here.
    """
    if any(ch.isdigit() for ch in symbol):
        return symbol
    from ..config.settings import get_active_contracts

    settings = get_settings()
    contracts = get_active_contracts(settings)
    for c in contracts:
        if c.base == symbol:
            return c.symbol
    # Regex fallback: "VX" matches "VXH6" when base is "VIX"
    for c in contracts:
        m = re.match(r"^([A-Z0-9]{1,4}?)[A-Z]\d+$", c.symbol)
        if m and m.group(1) == symbol:
            return c.symbol
    return symbol


def translate_db_errors[T](
    func: Callable[..., Awaitable[T]],
) -> Callable[..., Awaitable[T]]:
    """Route decorator (todo 142): a route's own `HTTPException` (404, 400, etc.) must never
    be re-caught and re-wrapped as a 500 by a broader except-Exception block -- the exact bug
    todo 137 found in `market_data.py` and fixed with a 2-line `except HTTPException: raise`
    guard, then hand-copied identically into `narrative.py`/`ai_stats.py`/`validation.py`/
    `signals.py` with no shared mechanism stopping a 6th route from needing the same fix.
    Also standardizes the client-facing error detail to a generic, non-leaking message
    (matching `narrative.py`'s pre-existing convention) -- the real exception is logged
    server-side only, under the route module's own `structlog` logger name."""

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> T:
        try:
            return await func(*args, **kwargs)
        except HTTPException:
            raise
        except Exception as error:
            logger = structlog.get_logger(func.__module__)
            logger.error(f"{func.__name__}.error", error=str(error))
            raise HTTPException(status_code=500, detail="Database error") from error

    return wrapper


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
