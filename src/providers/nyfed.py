"""NY Fed Markets Data API as an `EconomicSource`: published reference rates (todo 480).

No key needed. One request returns a rate type's full history, one record per effective date with
the rate, its distribution percentiles, volume and a revision flag. Each published field becomes
its own series, `NYFED_<TYPE>_<FIELD>`, so the consumer reads one number per series like FRED's.
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime

import httpx

from src.core.http_json import HttpJsonError, get_json
from src.providers.economic_source import Series, SourceError

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

# The unit of each field, declared here once and never inferred from a value. Rates, percentiles,
# the target range, intraday extremes, the standard deviation and the averages are percent
# (percentage points); volume is US dollars in billions; the SOFR Index is an index (`index`, FRED's code for the same
# quantity).
SUFFIX_UNIT = {
    "RATE": "percent",
    "P01": "percent",
    "P25": "percent",
    "P75": "percent",
    "P99": "percent",
    "VOLUME_BN": "billions_usd",
    "INTRADAY_HIGH": "percent",
    "INTRADAY_LOW": "percent",
    "STD_DEV": "percent",
    "TARGET_FROM": "percent",
    "TARGET_TO": "percent",
    "AVG_30D": "percent",
    "AVG_90D": "percent",
    "AVG_180D": "percent",
    "INDEX": "index",
}


def series_unit(series: str) -> str:
    """The declared unit of a `NYFED_<TYPE>_<FIELD>` series id."""
    suffix = next(s for s in SUFFIX_UNIT if series.endswith(f"_{s}"))
    return SUFFIX_UNIT[suffix]


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


class NyFedSource:
    """`EconomicSource` for the NY Fed: one entry is a rate type, expanded to a series per field."""

    name = SOURCE

    def __init__(self, max_attempts: int) -> None:
        self._max_attempts = max_attempts

    def validate(self, entry_id: str) -> None:
        if entry_id not in RATE_PATHS:
            raise ValueError(f"{entry_id}: not a NY Fed rate type {sorted(RATE_PATHS)}")

    async def fetch(self, entry_id: str, client: httpx.AsyncClient) -> dict[str, Series]:
        url = f"{_BASE_URL}/{RATE_PATHS[entry_id]}/search.json"
        params = {"startDate": _HISTORY_START, "endDate": datetime.now(UTC).date().isoformat()}
        try:
            payload = await get_json(client, url, params, max_attempts=self._max_attempts)
            series = parse_rate_records(entry_id, payload["refRates"])
        except (HttpJsonError, ValueError, KeyError) as error:
            raise SourceError(f"{type(error).__name__}: {error}"[:200]) from None
        if not series:
            raise SourceError("no records returned")
        return {sid: Series(series_unit(sid), rows) for sid, rows in series.items()}
