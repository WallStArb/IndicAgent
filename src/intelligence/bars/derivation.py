"""The D2 canonical 1d derivation rule (phase 185 plan 17, D-06, D-21).

derive_daily chooses, per (symbol, bar date), the canonical 1d bar from D1
TRADES observations:

- precedence within a date: the latest real SMART fetch, then (before the
  SMART head only, gated by the caller's venue flag) the max-volume venue
  route, legacy imports last (fallback only);
- split scale (D-21): IBKR TRADES history is split-adjusted at fetch time, so
  an observation fetched before a split's recorded_at, for a date before its
  effective date, is on the old scale. Such a date is served by the newest
  post-recording observation when one exists, otherwise by the best stale
  observation carrying the pre_split_unrefetched flag -- never a silently
  mixed scale. Legacy observations always count as pre-split (they re-import
  the stored corpus, whose pre-split rows are old-scale wherever they were
  never re-fetched).

Volume contract: a canonical bar stores the provider's fetched volume. None is
allowed only where the provider itself returned none; such a bar carries the
no_provider_volume flag rather than passing silently.

Pure: observations and split records in, canonical bars out. No database, no
config service, no I/O. The caller (services/bar_derivation.py --stage daily)
filters to TRADES observations, loads splits from corporate_action_current and
reads the venue gate from APR; ADJUSTED_LAST observations here are a caller
bug and raise ValueError.
"""

from __future__ import annotations

import calendar
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

RULE_VERSION = "d2-v1"

SOURCE_NAMED = "ibkr_named"
SOURCE_VENUE = "ibkr_venue"

_SMART_ROUTE = "SMART"
_FLAG_PRE_SPLIT = "pre_split_unrefetched"
_FLAG_NO_VOLUME = "no_provider_volume"


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
    """One recorded corporate action that rescales earlier observations."""

    effective_date: date
    recorded_at: datetime
    factor: float


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


def _epoch_seconds(dt: datetime) -> int:
    """Epoch seconds for an aware datetime (naive is treated as UTC)."""
    if dt.tzinfo is None:
        return calendar.timegm(dt.timetuple())
    return int(dt.timestamp())


def split_staleness_threshold(bar_date: date, splits: Sequence[SplitRecord]) -> datetime | None:
    """The latest recorded_at among splits that rescale ``bar_date``.

    A date is rescaled by every split whose effective date is strictly after
    it, so only an observation fetched at or after the latest such recording
    is on the current scale. None means no split affects the date.
    """
    thresholds = [s.recorded_at for s in splits if bar_date < s.effective_date]
    return max(thresholds) if thresholds else None


def _class_rank(obs: Observation) -> int:
    """0 real SMART, 1 venue, 2 legacy: the D-06 precedence order."""
    if obs.legacy:
        return 2
    return 0 if obs.route == _SMART_ROUTE else 1


def _pick(candidates: Sequence[Observation]) -> Observation:
    """Best candidate: class first, then latest fetch, then request id."""
    return min(
        candidates,
        key=lambda o: (_class_rank(o), -_epoch_seconds(o.fetched_at), o.request_id),
    )


def _choose_venue_route(venue_observations: Sequence[Observation], smart_head: date) -> str | None:
    """The single pre-head venue route with the largest total fetched volume.

    Volume sums over the pre-head span only; a NULL volume counts as zero.
    Ties break to the alphabetically first route so the choice is
    deterministic under input shuffling.
    """
    totals: dict[str, int] = {}
    for obs in venue_observations:
        if obs.bar_date < smart_head:
            totals[obs.route] = totals.get(obs.route, 0) + (obs.volume or 0)
    if not totals:
        return None
    return min(totals, key=lambda route: (-totals[route], route))


def derive_daily(
    observations: Sequence[Observation],
    splits: Sequence[SplitRecord],
    *,
    venue_bars_enabled: bool,
) -> list[CanonicalBar]:
    """The canonical 1d bars for one symbol, sorted by bar_date.

    Only TRADES observations may be passed (ADJUSTED_LAST raises ValueError;
    the caller filters). venue_bars_enabled is the APR D-17 gate read by the
    caller; venue observations before the SMART head are ignored while it is
    false. On or after the SMART head venue observations are never used.
    """
    for obs in observations:
        if obs.what_to_show != "TRADES":
            raise ValueError(
                f"observation {obs.request_id} is {obs.what_to_show!r}; derive_daily "
                "takes TRADES observations only (the caller must filter)"
            )

    real_smart = [o for o in observations if not o.legacy and o.route == _SMART_ROUTE]
    legacy = [o for o in observations if o.legacy]
    venue_all = [o for o in observations if not o.legacy and o.route != _SMART_ROUTE]

    smart_head = min((o.bar_date for o in real_smart), default=None)
    venue: list[Observation] = []
    if venue_bars_enabled and smart_head is not None:
        route = _choose_venue_route(venue_all, smart_head)
        if route is not None:
            venue = [o for o in venue_all if o.route == route and o.bar_date < smart_head]

    candidates: dict[date, list[Observation]] = {}
    for obs in real_smart + venue + legacy:
        candidates.setdefault(obs.bar_date, []).append(obs)

    bars: list[CanonicalBar] = []
    for bar_date in sorted(candidates):
        pool = candidates[bar_date]
        threshold = split_staleness_threshold(bar_date, splits)
        if threshold is None:
            chosen = _pick(pool)
            flags: tuple[str, ...] = ()
        else:
            current = [
                o
                for o in pool
                if not o.legacy and _epoch_seconds(o.fetched_at) >= _epoch_seconds(threshold)
            ]
            if current:
                chosen = _pick(current)
                flags = ()
            else:
                chosen = _pick(pool)
                flags = (_FLAG_PRE_SPLIT,)
        if chosen.volume is None:
            flags = flags + (_FLAG_NO_VOLUME,)
        source = SOURCE_VENUE if _class_rank(chosen) == 1 else SOURCE_NAMED
        bars.append(
            CanonicalBar(
                bar_date=bar_date,
                open=chosen.open,
                high=chosen.high,
                low=chosen.low,
                close=chosen.close,
                volume=chosen.volume,
                source=source,
                request_ids=(chosen.request_id,),
                flags=flags,
            )
        )
    return bars
