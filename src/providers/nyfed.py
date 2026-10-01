"""NY Fed Markets Data API: published reference rates (todo 480). All NY Fed HTTP logic is here.

No key needed. One request returns a rate type's full history, one record per effective date with
the rate, its distribution percentiles, volume and a revision flag. Each published field becomes
its own series, `NYFED_<TYPE>_<FIELD>`, so the consumer reads one number per series like FRED's.
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime

import httpx

_BASE_URL = "https://markets.newyorkfed.org/api/rates"
_HISTORY_START = "2000-01-01"  # before the earliest series (EFFR, 2000-07): everything
SOURCE = "nyfed"
# The NY Fed writes the string "NA" for a statistic it did not publish that day (SOFR percentiles,
# 2021-08-05 and one other day): missing, never zero. Any other non-number still fails the series.
_NOT_PUBLISHED = "NA"

# NY Fed's record `type` -> endpoint path.
RATE_PATHS = {
    "SOFR": "secured/sofr",
    "TGCR": "secured/tgcr",
    "BGCR": "secured/bgcr",
    "SOFRAI": "secured/sofrai",
    "EFFR": "unsecured/effr",
    "OBFR": "unsecured/obfr",
}
# NY Fed JSON field -> series suffix. A record carries only the fields that exist for its type.
FIELD_SUFFIX = {
    "percentRate": "RATE",
    "percentPercentile1": "P01",
    "percentPercentile25": "P25",
    "percentPercentile75": "P75",
    "percentPercentile99": "P99",
    "volumeInBillions": "VOLUME_BN",
    "intraDayHigh": "INTRADAY_HIGH",
    "intraDayLow": "INTRADAY_LOW",
    "stdDeviation": "STD_DEV",
    "targetRateFrom": "TARGET_FROM",
    "targetRateTo": "TARGET_TO",
    "average30day": "AVG_30D",
    "average90day": "AVG_90D",
    "average180day": "AVG_180D",
    "index": "INDEX",
}


def series_id(rate_type: str, suffix: str) -> str:
    return f"NYFED_{rate_type}_{suffix}"


def parse_rate_records(rate_type: str, records: list[dict]) -> dict[str, list[tuple[date, float]]]:
    """series id -> (effective date, value) rows in date order, from one rate type's records.

    A field absent from a record is missing for that date, never zero (no_fill). Raises
    ValueError on a record of another type, a non-finite value, or two records for one date:
    the append-only store cannot tell which is right.
    """
    out: dict[str, dict[date, float]] = {}
    for record in records:
        if record["type"] != rate_type:
            raise ValueError(f"record of type {record['type']} in a {rate_type} response")
        day = date.fromisoformat(record["effectiveDate"])
        for field, suffix in FIELD_SUFFIX.items():
            raw = record.get(field)
            if raw is None or raw == _NOT_PUBLISHED:
                continue
            value = float(raw)
            if not math.isfinite(value):
                raise ValueError(f"non-finite {field} on {day}")
            by_day = out.setdefault(series_id(rate_type, suffix), {})
            if day in by_day:
                raise ValueError(f"two {rate_type} records for {day}")
            by_day[day] = value
    return {sid: sorted(by_day.items()) for sid, by_day in out.items()}


async def fetch_rate_series(
    rate_type: str, timeout_sec: float
) -> tuple[dict[str, list[tuple[date, float]]], str | None]:
    """Full history of one rate type as served today: ({series id: rows}, None) or ({}, error)."""
    url = f"{_BASE_URL}/{RATE_PATHS[rate_type]}/search.json"
    params = {"startDate": _HISTORY_START, "endDate": datetime.now(UTC).date().isoformat()}
    try:
        async with httpx.AsyncClient(timeout=timeout_sec) as client:
            response = await client.get(url, params=params)
        response.raise_for_status()
        series = parse_rate_records(rate_type, response.json()["refRates"])
    except Exception as error:
        return {}, f"{type(error).__name__}: {error}"[:200]
    if not series:
        return {}, "no records returned"
    return series, None
