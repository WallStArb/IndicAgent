"""The contract every economic series source implements (todo 480).

A source turns one configured entry (a FRED series id, a NY Fed rate type) into one or more series,
each with its declared unit. It fetches and normalizes only: availability, revisions and persistence
belong to the writer. Adding a source is a new module implementing `EconomicSource` and one line in
the writer's registry; nothing branches on source names.
"""

from __future__ import annotations

from datetime import date
from typing import NamedTuple, Protocol

import httpx


class Series(NamedTuple):
    unit: str  # declared by the source, never inferred from a value
    rows: list[tuple[date, float]]  # (observation date, value), date order, missing days absent


class SourceError(Exception):
    """One entry could not be fetched or parsed; the run continues and fails at the end."""


class EconomicSource(Protocol):
    name: str

    def validate(self, entry_id: str) -> None:
        """Raise ValueError if `entry_id` cannot be fetched from this source."""

    async def fetch(self, entry_id: str, client: httpx.AsyncClient) -> dict[str, Series]:
        """{series id: Series} as served today; raises SourceError."""
