"""The D1 and D2 record types the 1d daily rule shares (phase 185 plans 17 and 38, D-06, D-21).

Observation (one D1 observation of a 1d bar), SplitRecord (a recorded corporate action that
rescales earlier observations) and CanonicalBar (the derived canonical 1d bar, its identity
the (vendor, kind) pair since plan 191-13), plus the ibkr_named and ibkr_venue source labels
(raw-side vocabulary). The rule itself is d2-v2 in daily_rule.py; d2-v1 (derive_daily, its
venue-route choice and RULE_VERSION "d2-v1") was deleted in plan 185-42. Stored rows and
digests may still carry the d2-v1 label as history.

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

    evidence_request_ids names the requests whose answers showed the new scale (a vendor
    refetch records the split after its own fetch, so its observations predate recorded_at by
    milliseconds yet carry the new scale). d2-v2 counts them as current.
    """

    effective_date: date
    recorded_at: datetime
    factor: float
    evidence_request_ids: tuple[str, ...] = ()
    # Todo 587 (inferred_by calendar_audit): the observation routes measured unadjusted over this
    # split. Non-empty makes the split a rescale, never a staleness trigger: those routes'
    # observations dated on or before effective_date (the last day on the old scale) are divided
    # by the factor. Empty (every other split) keeps the D-21 stale semantics.
    rescale_routes: frozenset[str] = frozenset()
    # Todo 587, calendar_audit only: the calendar's split-adjusted log close step across the date,
    # the day's real move. D7 split_continuity judges canonical's step at the split in excess of
    # it (a reverse split on a spin-off day, EXPE 2011-12-21, is continuous yet drops 48%). The
    # rule never reads it.
    calendar_adjusted_step: float = 0.0


@dataclass(frozen=True)
class CanonicalBar:
    """The derived canonical 1d bar: values, (vendor, kind) identity, lineage, flags."""

    bar_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int | None
    vendor: str
    kind: str
    request_ids: tuple[str, ...]
    flags: tuple[str, ...]
