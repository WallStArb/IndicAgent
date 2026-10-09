"""The unified canonical 1d rule d2-v3 (phase 185 plans 36 and 52; data layer integrity design
sections 2 and 4 and its Amendment 2026-10-07,
docs/plans/2026-10-06-data-layer-integrity-design.md).

One pure function replaces both D2's derive_daily (d2-v1) and the Tradier loader's inline rule
(tradier-v1): D1 observations of both vendors, the bar_source_policy rows and the current
corporate actions in; canonical 1d bars, their flags and the refused interior dates out.

Per bar date, the policy row that covers it (a symbol row beats the timeframe default; no row
raises) names the primary and fallback source:

- primary: the latest current-scale observation of the primary vendor. Tradier observations are
  route TRADIER (source label tradier); IBKR observations are route SMART TRADES, then the
  LEGACY_IMPORT copy of the stored corpus as a lower rank (source label ibkr_named when IBKR is
  primary). Venue routes are never read (the D-17 venue study failed).
- a primary with only stale-scale observations (d2-v3, plan 185-52, todo 517): when the policy
  names a fallback and the fallback has a current-scale answer for the date, that answer is
  served (source label ibkr_fallback, the date listed in restated) if the basis over the
  basis_window_sessions common sessions nearest the date (as for an interior hole, below) is
  within basis_tolerance_bp of 1. Otherwise, or with no current fallback answer, the latest
  stale observation is served with the pre_split_unrefetched flag (quarantined per APR), never a
  silently mixed scale. This is the path that keeps a name's Tradier history before
  D = 2026-10-07 tradeable after a later split: Tradier is never asked again, IBKR's split
  re-fetch answers on the new scale;
- otherwise the fallback (IBKR under the Tradier default), current scale only, source label
  ibkr_fallback:
  - head, a date before Tradier's first observation: admitted only when the seam (the median
    IBKR/Tradier close ratio over the first basis_window_sessions common sessions from Tradier's
    head) is within basis_tolerance_bp of 1, the interior test's tolerance; then one
    fallback_seam flag on the first Tradier bar records it. Otherwise every head date is listed
    in refused_head and has no canonical bar: a 2:1 basis at the seam would be a false return
    (plan 185-38; 185-36 found XLY, XAR, XHS and XSW at about 5,000 bp);
  - interior hole: admitted only when the median IBKR/Tradier close ratio over the
    basis_window_sessions common sessions nearest the hole (by session distance, both sides,
    ties to the earlier session) is within basis_tolerance_bp of 1. Otherwise the date has no
    canonical bar and is listed in refused_interior. Tradier observations end at 2026-10-06 (the
    loader is deleted, plan 185-48), so no Tradier re-ask exists; IBKR's latest answer is.

Scale (D-21): an observation is stale for a date when some recorded split takes effect after
the date and the observation was fetched before that split's recorded_at, unless its request is
the split's evidence (the refetch that revealed it). LEGACY_IMPORT observations are always stale
for a split-affected date: they re-import the stored corpus. The splits are the rows of
corporate_action_current, so a voided or superseded split never reaches the rule.

Basis: the ratio of IBKR's current-scale close to Tradier's close on the current scale. Where
Tradier has only stale observations, its latest stale close divided by the factors of the splits
that make it stale (corporate_action.factor = old-scale price / new-scale price) is that
measurement. The rescaled Tradier close is a measurement only and is never served (a vendor scale
correction was rejected in plan 185-49). A wrong recorded factor therefore shows as a basis break
and restates nothing. A common session is a date where IBKR has a current-scale observation and
Tradier a current or restated close; the session axis is the sorted set of dates either vendor
answered.

Volume: the chosen observation's volume, never rescaled or spliced. A fallback bar (head,
interior or restated) keeps IBKR's raw volume in market_data_ohlcv and reads NULL through
market_data_ohlcv_tradeable (migration 446), so no IBKR SMART volume is spliced into a Tradier
volume series (IBKR SMART counts about half of Tradier's consolidated volume; todo 518). A
missing provider volume carries the no_provider_volume flag.

Pure: no database, no APR reads (thresholds are parameters), deterministic under input order.
"""

from __future__ import annotations

import calendar
import math
import statistics
from bisect import bisect_left
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import Any

from src.intelligence.bars.derivation import CanonicalBar, Observation, SplitRecord
from src.intelligence.bars.sources import ROUTE_TRADIER, SOURCE_IBKR_FALLBACK

RULE_VERSION = "d2-v3"

TIMEFRAME = "1d"
ROUTE_SMART = "SMART"
ROUTE_LEGACY = "LEGACY_IMPORT"
VENDOR_TRADIER = "tradier"
VENDOR_IBKR = "ibkr"

FLAG_FALLBACK_SEAM = "fallback_seam"
FLAG_PRE_SPLIT = "pre_split_unrefetched"
FLAG_NO_VOLUME = "no_provider_volume"

# Informational flag fields per rule; identifiers, not tunables.
FLAG_FIELDS: dict[str, tuple[str, ...]] = {
    FLAG_FALLBACK_SEAM: ("close",),
    FLAG_PRE_SPLIT: ("open", "high", "low", "close"),
    FLAG_NO_VOLUME: ("volume",),
}

_PRIMARY_LABEL = {VENDOR_TRADIER: "tradier", VENDOR_IBKR: "ibkr_named"}
_ROUTE_VENDOR = {ROUTE_TRADIER: VENDOR_TRADIER, ROUTE_SMART: VENDOR_IBKR, ROUTE_LEGACY: VENDOR_IBKR}
_BP = 1e4


@dataclass(frozen=True)
class PolicyRow:
    """One bar_source_policy decision (migration 446), [valid_from, valid_to)."""

    timeframe: str
    symbol: str | None
    valid_from: date
    valid_to: date | None
    ingress_mode: str
    primary_source: str
    fallback_source: str | None

    def covers(self, bar_date: date) -> bool:
        return self.valid_from <= bar_date and (self.valid_to is None or bar_date < self.valid_to)


@dataclass(frozen=True)
class DerivedFlag:
    """A flag the rule raises on one canonical bar; detail is JSON-safe."""

    bar_date: date
    rule: str
    fields: tuple[str, ...]
    detail: dict[str, Any] = field(compare=True, hash=False)


@dataclass(frozen=True)
class DailyV2Result:
    """Canonical bars sorted by date, their flags, and how each fallback date was decided."""

    bars: list[CanonicalBar]
    flags: list[DerivedFlag]
    refused_interior: list[date]
    head: list[date] = field(default_factory=list)
    admitted_interior: list[date] = field(default_factory=list)
    # Dates answered only on a stale scale by a vendor the rule may not use stale.
    stale_only: list[date] = field(default_factory=list)
    # Head dates refused because the seam is outside the basis tolerance (or unmeasurable).
    refused_head: list[date] = field(default_factory=list)
    # Dates whose primary answered only on a stale scale and whose fallback's current-scale
    # answer was served instead (d2-v3).
    restated: list[date] = field(default_factory=list)


def resolve_policy(rows: Sequence[PolicyRow], symbol: str, bar_date: date) -> PolicyRow:
    """The 1d policy row for (symbol, date): a symbol row beats the default; none raises."""
    covering = [r for r in rows if r.timeframe == TIMEFRAME and r.covers(bar_date)]
    for scope in (symbol, None):
        matched = [r for r in covering if r.symbol == scope]
        if len(matched) > 1:
            raise LookupError(
                f"bar_source_policy rows overlap for ({TIMEFRAME}, {scope}) on {bar_date}"
            )
        if matched:
            return matched[0]
    raise LookupError(f"no bar_source_policy row covers ({TIMEFRAME}, {symbol}) on {bar_date}")


def _epoch(dt: datetime) -> float:
    if dt.tzinfo is None:
        return float(calendar.timegm(dt.timetuple())) + dt.microsecond / 1e6
    return dt.timestamp()


def _stale_for(obs: Observation, split: SplitRecord) -> bool:
    if obs.bar_date >= split.effective_date:
        return False
    if obs.legacy:
        return True
    return _epoch(obs.fetched_at) < _epoch(split.recorded_at) and (
        obs.request_id not in split.evidence_request_ids
    )


def _is_current(obs: Observation, splits: Sequence[SplitRecord]) -> bool:
    return not any(_stale_for(obs, split) for split in splits)


def _restated_close(obs: Observation, splits: Sequence[SplitRecord]) -> float | None:
    """A stale close on the current scale (measurement only), or None when it has none."""
    if obs.legacy:
        return None
    scale = 1.0
    for split in sorted(splits, key=lambda s: (s.effective_date, _epoch(s.recorded_at))):
        if _stale_for(obs, split):
            if not (math.isfinite(split.factor) and split.factor > 0):
                return None
            scale *= split.factor
    return obs.close / scale


def _best(candidates: Sequence[Observation]) -> Observation:
    """SMART before LEGACY_IMPORT, then the latest fetch, then the larger request id."""
    return max(candidates, key=lambda o: (not o.legacy, _epoch(o.fetched_at), o.request_id))


@dataclass
class _VendorDay:
    current: Observation | None = None
    stale: Observation | None = None


def _tradier_basis_close(day: _VendorDay, splits: Sequence[SplitRecord]) -> float | None:
    if day.current is not None:
        return day.current.close
    if day.stale is not None:
        return _restated_close(day.stale, splits)
    return None


def _by_vendor_day(
    observations: Sequence[Observation], splits: Sequence[SplitRecord]
) -> dict[str, dict[date, _VendorDay]]:
    pools: dict[str, dict[date, tuple[list[Observation], list[Observation]]]] = {
        VENDOR_TRADIER: {},
        VENDOR_IBKR: {},
    }
    for obs in observations:
        if obs.what_to_show != "TRADES":
            raise ValueError(
                f"observation {obs.request_id} is {obs.what_to_show!r}; derive_daily_v2 takes "
                "TRADES observations only (the caller must filter)"
            )
        vendor = _ROUTE_VENDOR.get(obs.route)
        if vendor is None:
            continue
        current, stale = pools[vendor].setdefault(obs.bar_date, ([], []))
        (current if _is_current(obs, splits) else stale).append(obs)
    return {
        vendor: {
            day: _VendorDay(
                current=_best(current) if current else None,
                stale=_best(stale) if stale else None,
            )
            for day, (current, stale) in days.items()
        }
        for vendor, days in pools.items()
    }


def current_closes(
    observations: Sequence[Observation], splits: Sequence[SplitRecord]
) -> tuple[dict[date, float], dict[date, float]]:
    """(Tradier, IBKR SMART) close per date: each vendor's latest current-scale answer.

    LEGACY_IMPORT is left out: it re-imports the stored corpus and is no IBKR measurement.
    """
    smart_only = [o for o in observations if o.route != ROUTE_LEGACY]
    days = _by_vendor_day(smart_only, splits)
    return tuple(  # type: ignore[return-value]
        {d: v.current.close for d, v in days[vendor].items() if v.current is not None}
        for vendor in (VENDOR_TRADIER, VENDOR_IBKR)
    )


def basis_closes(
    observations: Sequence[Observation], splits: Sequence[SplitRecord]
) -> tuple[dict[date, float], dict[date, float]]:
    """current_closes, with Tradier's stale-only dates restated by the recorded factors.

    The closes the rule measures the vendor basis on (module docstring, Basis); D7's
    vendor_basis_run reads the same, so a basis run inside a restated span stays visible after
    Tradier's history goes stale.
    """
    smart_only = [o for o in observations if o.route != ROUTE_LEGACY]
    days = _by_vendor_day(smart_only, splits)
    tradier = {
        d: close
        for d, v in days[VENDOR_TRADIER].items()
        if (close := _tradier_basis_close(v, splits)) is not None
    }
    ibkr = {d: v.current.close for d, v in days[VENDOR_IBKR].items() if v.current is not None}
    return tradier, ibkr


def _median_ratio(dates: Sequence[date], ratios: dict[date, float]) -> float | None:
    return statistics.median(ratios[d] for d in dates) if dates else None


def _nearest(
    hole_index: int, common_index: Sequence[int], common_dates: Sequence[date], n: int
) -> list[date]:
    """The n common sessions nearest the hole by session distance; ties to the earlier one."""
    right = bisect_left(common_index, hole_index)
    left = right - 1
    chosen: list[date] = []
    while len(chosen) < n and (left >= 0 or right < len(common_index)):
        left_gap = hole_index - common_index[left] if left >= 0 else None
        right_gap = common_index[right] - hole_index if right < len(common_index) else None
        if right_gap is None or (left_gap is not None and left_gap <= right_gap):
            chosen.append(common_dates[left])
            left -= 1
        else:
            chosen.append(common_dates[right])
            right += 1
    return chosen


def _bar(obs: Observation, source: str, flags: tuple[str, ...]) -> CanonicalBar:
    if obs.volume is None:
        flags = flags + (FLAG_NO_VOLUME,)
    return CanonicalBar(
        bar_date=obs.bar_date,
        open=obs.open,
        high=obs.high,
        low=obs.low,
        close=obs.close,
        volume=obs.volume,
        source=source,
        request_ids=(obs.request_id,),
        flags=flags,
    )


def _check_policy(policy: PolicyRow) -> None:
    if policy.ingress_mode != "observed":
        raise ValueError(
            f"1d policy is {policy.ingress_mode!r}; d2-v3 derives only an observed timeframe"
        )
    if policy.primary_source not in _PRIMARY_LABEL:
        raise ValueError(f"1d primary source {policy.primary_source!r} has no d2-v3 rule")
    if policy.fallback_source is not None and (
        policy.primary_source,
        policy.fallback_source,
    ) != (VENDOR_TRADIER, VENDOR_IBKR):
        raise ValueError(
            f"fallback {policy.fallback_source!r} under primary {policy.primary_source!r} has "
            "no d2-v3 rule (only IBKR may fall back for Tradier)"
        )


def derive_daily_v2(
    observations: Sequence[Observation],
    policy_rows: Sequence[PolicyRow],
    splits: Sequence[SplitRecord],
    *,
    symbol: str,
    basis_window_sessions: int,
    basis_tolerance_bp: float,
) -> DailyV2Result:
    """The canonical 1d bars of one symbol under d2-v3 (module docstring)."""
    if basis_window_sessions < 1:
        raise ValueError("basis_window_sessions must be at least 1")
    days = _by_vendor_day(observations, splits)
    tradier, ibkr = days[VENDOR_TRADIER], days[VENDOR_IBKR]
    tradier_head = min(tradier, default=None)

    axis = sorted(set(tradier) | set(ibkr))
    position = {d: i for i, d in enumerate(axis)}
    ratios = {
        d: ibkr_current.close / tradier_close
        for d in axis
        if d in tradier
        and d in ibkr
        and (ibkr_current := ibkr[d].current) is not None
        and (tradier_close := _tradier_basis_close(tradier[d], splits)) is not None
        # A non-positive close is a provider defect the scrub flags; it measures no basis.
        and tradier_close > 0
    }
    common_dates = sorted(ratios)
    common_index = [position[d] for d in common_dates]
    seam_window = (
        [d for d in common_dates if d >= tradier_head][:basis_window_sessions]
        if tradier_head is not None
        else []
    )
    seam_median = _median_ratio(seam_window, ratios)
    head_admitted = seam_median is not None and (abs(seam_median - 1.0) * _BP <= basis_tolerance_bp)

    bars: list[CanonicalBar] = []
    flags: list[DerivedFlag] = []
    head: list[date] = []
    refused_head: list[date] = []
    admitted: list[date] = []
    refused: list[date] = []
    stale_only: list[date] = []
    restated: list[date] = []

    def within_tolerance(day: date) -> bool:
        window = _nearest(position[day], common_index, common_dates, basis_window_sessions)
        median = _median_ratio(window, ratios)
        return median is not None and abs(median - 1.0) * _BP <= basis_tolerance_bp

    for day in axis:
        policy = resolve_policy(policy_rows, symbol, day)
        _check_policy(policy)
        primary = days[policy.primary_source].get(day)
        if primary is not None and primary.current is not None:
            bars.append(_bar(primary.current, _PRIMARY_LABEL[policy.primary_source], ()))
            continue
        fallback = days[policy.fallback_source].get(day) if policy.fallback_source else None
        if primary is not None and primary.stale is not None:
            if fallback is not None and fallback.current is not None and within_tolerance(day):
                restated.append(day)
                bars.append(_bar(fallback.current, SOURCE_IBKR_FALLBACK, ()))
            else:
                bars.append(
                    _bar(primary.stale, _PRIMARY_LABEL[policy.primary_source], (FLAG_PRE_SPLIT,))
                )
            continue
        if fallback is None:
            continue
        if fallback.current is None:
            stale_only.append(day)
            continue
        if tradier_head is None:
            # No Tradier answer at all: nothing to splice against, the fallback is the series.
            head.append(day)
        elif day < tradier_head:
            if not head_admitted:
                refused_head.append(day)
                continue
            head.append(day)
        else:
            if not within_tolerance(day):
                refused.append(day)
                continue
            admitted.append(day)
        bars.append(_bar(fallback.current, SOURCE_IBKR_FALLBACK, ()))

    if head and tradier_head is not None:
        bars = _with_seam(
            bars, flags, head, tradier_head, common_dates, ratios, basis_window_sessions
        )

    for bar in bars:
        for rule in bar.flags:
            if rule != FLAG_FALLBACK_SEAM:
                flags.append(
                    DerivedFlag(bar.bar_date, rule, FLAG_FIELDS[rule], {"source": bar.source})
                )
    flags.sort(key=lambda f: (f.bar_date, f.rule))
    return DailyV2Result(
        bars=bars,
        flags=flags,
        refused_interior=refused,
        head=head,
        admitted_interior=admitted,
        stale_only=stale_only,
        refused_head=refused_head,
        restated=restated,
    )


def _with_seam(
    bars: list[CanonicalBar],
    flags: list[DerivedFlag],
    head: list[date],
    tradier_head: date,
    common_dates: list[date],
    ratios: dict[date, float],
    window_sessions: int,
) -> list[CanonicalBar]:
    """Mark the first Tradier bar after an admitted head with the measured seam."""
    first = next(
        (i for i, b in enumerate(bars) if b.source == "tradier" and b.bar_date >= tradier_head),
        None,
    )
    if first is None:
        return bars
    overlap = [d for d in common_dates if d >= tradier_head][:window_sessions]
    median = _median_ratio(overlap, ratios)
    seam_bar = bars[first]
    flags.append(
        DerivedFlag(
            seam_bar.bar_date,
            FLAG_FALLBACK_SEAM,
            FLAG_FIELDS[FLAG_FALLBACK_SEAM],
            {
                "fallback_source": VENDOR_IBKR,
                "head_first": head[0].isoformat(),
                "head_last": head[-1].isoformat(),
                "n_head_bars": len(head),
                "window_sessions": window_sessions,
                "n_common": len(overlap),
                "median_ratio": median,
                "deviation_bp": None if median is None else abs(median - 1.0) * _BP,
            },
        )
    )
    seam = replace(seam_bar, flags=seam_bar.flags + (FLAG_FALLBACK_SEAM,))
    return [*bars[:first], seam, *bars[first + 1 :]]
