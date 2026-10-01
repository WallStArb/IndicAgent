"""FRED (St. Louis Fed) as an `EconomicSource`. All FRED request shapes live here.

Used for economic series (credit spreads, Treasury yields, real yields; todo 480), never prices.
The API key travels as a query parameter; `get_json` redacts it from every error.
"""

from __future__ import annotations

import asyncio
import math
from datetime import date

import httpx

from src.core.http_json import HttpJsonError, get_json
from src.providers.economic_source import Series, SourceError

SOURCE = "fred"
_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"
_SERIES_URL = "https://api.stlouisfed.org/fred/series"
# FRED marks a day with no observation as "."; that is missing, never zero (no_fill).
_MISSING = "."


def parse_observations(payload: dict) -> list[tuple[date, float]]:
    """(observation date, value) rows in date order, missing days dropped.

    Raises ValueError on a payload without observations or a non-finite value: a malformed
    response must fail the series, not store a partial history.
    """
    if "observations" not in payload:
        raise ValueError(f"no observations in response: {str(payload)[:120]}")
    rows: list[tuple[date, float]] = []
    for obs in payload["observations"]:
        raw = obs["value"]
        if raw == _MISSING:
            continue
        value = float(raw)
        if not math.isfinite(value):
            raise ValueError(f"non-finite value on {obs['date']}")
        rows.append((date.fromisoformat(obs["date"]), value))
    rows.sort(key=lambda r: r[0])
    if len({d for d, _ in rows}) != len(rows):
        raise ValueError("duplicate observation dates")
    return rows


def normalize_unit(declared: str) -> str:
    """FRED's declared unit ("Percent", "Index 2015=100") as a code: lower case, underscores."""
    return declared.strip().lower().replace(" ", "_")


class FredSource:
    """`EconomicSource` for FRED: one entry is one series id."""

    name = SOURCE

    def __init__(self, api_key: str, max_attempts: int) -> None:
        self._api_key = api_key
        self._max_attempts = max_attempts

    def validate(self, entry_id: str) -> None:
        if not entry_id:
            raise ValueError("empty FRED series id")

    async def fetch(self, entry_id: str, client: httpx.AsyncClient) -> dict[str, Series]:
        if not self._api_key:
            raise SourceError("FRED_API_KEY is not set")
        base = {"series_id": entry_id, "api_key": self._api_key, "file_type": "json"}
        observations = {
            **base,
            "sort_order": "asc",
            "observation_start": "1776-07-04",  # FRED's own earliest date: everything
        }
        try:
            # Two independent requests: run them together.
            payload, meta = await asyncio.gather(
                get_json(
                    client,
                    _OBSERVATIONS_URL,
                    observations,
                    secret=self._api_key,
                    max_attempts=self._max_attempts,
                ),
                get_json(
                    client, _SERIES_URL, base, secret=self._api_key, max_attempts=self._max_attempts
                ),
            )
            rows = parse_observations(payload)
            unit = normalize_unit(meta["seriess"][0]["units"])
        except (HttpJsonError, ValueError, KeyError, IndexError) as error:
            raise SourceError(f"{type(error).__name__}: {error}"[:200]) from None
        if not rows:
            raise SourceError("no observations returned")
        return {entry_id: Series(unit, rows)}
