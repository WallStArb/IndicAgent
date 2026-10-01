"""FRED reference data (St. Louis Fed). All FRED HTTP logic lives here.

Used for macro series (credit spreads, Treasury yields, real yields; todo 480), never prices.
The API key travels as a query parameter, so no error string leaves this module with it in.
"""

from __future__ import annotations

import math
from datetime import date

import httpx

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


async def fetch_observations(
    series_id: str, api_key: str, timeout_sec: float
) -> tuple[list[tuple[date, float]], str | None]:
    """Full history of one series as served today: (rows, None) or ([], error)."""
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "asc",
        "observation_start": "1776-07-04",  # FRED's own earliest date: everything
    }
    try:
        async with httpx.AsyncClient(timeout=timeout_sec) as client:
            response = await client.get(_OBSERVATIONS_URL, params=params)
        response.raise_for_status()
        rows = parse_observations(response.json())
    except Exception as error:
        # httpx puts the request URL, key included, in its messages: report the type and a
        # redacted message only.
        message = str(error).replace(api_key, "<redacted>") if api_key else str(error)
        return [], f"{type(error).__name__}: {message}"[:200]
    if not rows:
        return [], "no observations returned"
    return rows, None


async def fetch_unit(series_id: str, api_key: str, timeout_sec: float) -> tuple[str, str | None]:
    """The unit FRED declares for a series ("Percent", "Index", ...), lower-cased with spaces
    as underscores: (unit, None) or ("", error). Declared by the provider, never inferred from
    a value."""
    params = {"series_id": series_id, "api_key": api_key, "file_type": "json"}
    try:
        async with httpx.AsyncClient(timeout=timeout_sec) as client:
            response = await client.get(_SERIES_URL, params=params)
        response.raise_for_status()
        unit = response.json()["seriess"][0]["units"]
    except Exception as error:
        message = str(error).replace(api_key, "<redacted>") if api_key else str(error)
        return "", f"{type(error).__name__}: {message}"[:200]
    return unit.strip().lower().replace(" ", "_"), None
