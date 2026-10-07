"""The D1 and D2 record types the 1d daily rule shares (phase 185 plans 17 and 38, D-06, D-21).

Observation (one D1 observation of a 1d bar), SplitRecord (a recorded corporate action that
rescales earlier observations) and CanonicalBar (the derived canonical 1d bar), plus the
ibkr_named and ibkr_venue source labels. The rule itself is d2-v2 in daily_rule.py; d2-v1
(derive_daily, its venue-route choice and RULE_VERSION "d2-v1") was deleted in plan 185-42.
Stored rows and digests may still carry the d2-v1 label as history.

Pure: no database, no config service, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

SOURCE_NAMED = "ibkr_named"
SOURCE_VENUE = "ibkr_venue"


@dataclass(frozen=True)
class Observation:
    """One D1 observation of a 1d bar (route and fetch time decide its weight)."""

    request_id: str
    route: str
    bar_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int | None
    fetched_at: datetime
    legacy: bool
    what_to_show: str = "TRADES"


@dataclass(frozen=True)
class SplitRecord:
    """One recorded corporate action that rescales earlier observations.

    evidence_request_ids names the requests whose answers showed the new scale (a Tradier
    refetch records the split after its own fetch, so its observations predate recorded_at by
    milliseconds yet carry the new scale). d2-v2 counts them as current.
    """

    effective_date: date
    recorded_at: datetime
    factor: float
    evidence_request_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class CanonicalBar:
    """The derived canonical 1d bar: values, source label, lineage, flags."""

    bar_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int | None
    source: str
    request_ids: tuple[str, ...]
    flags: tuple[str, ...]
