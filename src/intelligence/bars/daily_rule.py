"""The unified canonical 1d rule d2-v4 (phase 185 plans 36 and 52; data layer integrity design
sections 2 and 4 and its Amendment 2026-10-07,
docs/plans/2026-10-06-data-layer-integrity-design.md; d2-v4 is D-191-Q of
docs/plans/2026-10-12-unified-raw-bar-table-design.md, todo 545 step 3).

One pure function replaces both D2's derive_daily (d2-v1) and the Tradier loader's inline rule
(tradier-v1): D1 observations of both vendors, the bar_source_policy rows and the current
corporate actions in; canonical 1d bars, their flags and the refused interior dates out.

Per bar date, the policy row that covers it (a symbol row beats the timeframe default; no row
raises) names the primary and fallback source:

- primary: the latest current-scale observation of the primary vendor. Tradier observations are
  route TRADIER (canonical identity (tradier, consolidated)); IBKR observations are route SMART
  TRADES, then the LEGACY_IMPORT copy of the stored corpus as a lower rank (identity
  (ibkr, named) when IBKR is primary); Alpaca observations are route ALPACA, the split-adjusted
  SIP daily answer (identity (alpaca, sip_rth), the raw kind, as canonical 5m carries it).
  Venue routes are never read (the D-17 venue study failed). A primary that names a fallback
  is Tradier or Alpaca, and its fallback is IBKR; Tradier's head and interior rules below apply
  to either (the "primary vendor" of the date's policy row).
- a primary with only stale-scale observations (d2-v3, plan 185-52, todo 517): when the policy
  names a fallback and the fallback has a current-scale answer for the date, that answer is
  served (identity (ibkr, fallback), the date listed in restated) if the basis over the
  basis_window_sessions common sessions nearest the date (as for an interior hole, below) is
  within basis_tolerance_bp of 1. Otherwise, or with no current fallback answer, the latest
  stale observation is served with the pre_split_unrefetched flag (quarantined per APR), never a
  silently mixed scale. This is the path that keeps a name's Tradier history before
  D = 2026-10-07 tradeable after a later split: Tradier is never asked again, IBKR's split
  re-fetch answers on the new scale;
- otherwise the fallback (IBKR under the Tradier default), current scale only, identity
  (ibkr, fallback):
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

Alpaca guards (d2-v4, D-191-Q). Alpaca is keyed by ticker, IBKR by contract, so two things an
Alpaca daily answer can carry never reach canonical:

- a zero-volume (or volume-less) Alpaca bar is no trade: Alpaca serves carry-forward placeholders
  across dead-ticker gaps. It is dropped before anything else reads it (no basis measurement, no
  head) and listed in zero_volume; the session falls to the IBKR fallback under the ordinary
  interior or head rule, or has no bar;
- an Alpaca bar before the name's listing. No point-in-time listing date exists for the universe
  (instrument_metadata.listing_date covers 63 of 166 rows and is overwritten in place;
  listing_venue.valid_from and ohlcv_provider_head are IBKR's own first bar). The listing is
  therefore read from the contract-keyed vendor: the Alpaca span starts at alpaca_start, the
  first session both vendors answered where IBKR's current close agrees with Alpaca's within
  basis_tolerance_bp on that session and in the median over the basis_window_sessions common
  sessions from it (the head seam test). A splice of a predecessor that trades on before the
  contract's regular-way start (AA, 2016-10-18 to 10-31: IBKR's when-issued bars at 16 against
  the old Alcoa at 80 under the same ticker) fails the session test, so it is cut too, which a
  bare "IBKR has a bar" anchor would not do. Alpaca dates before alpaca_start are listed in
  pre_start and never served; a name with no agreeing session has no Alpaca span (alpaca_start
  None), and its IBKR fallback is the series. Tradier, also ticker-keyed, keeps d2-v3 unguarded.
  The same test refuses a basis difference that is not identity: IBKR (like Tradier) adjusts its
  history for spin-offs, Alpaca's split adjustment does not (measured 2026-10-27: IBKR/Alpaca
  0.9718 on ILMN before 2024-06-25, 0.7557 on WDC before 2025-02-24, 0.8265 then 0.9898 on J),
  so an Alpaca span starts after the last such event in IBKR's adjusted history. Serving
  Alpaca's unadjusted level there would put the spin-off on the ex-date as a false return.

Session dates: the raw read dates each series by its own stamp convention
(RAW_DAILY_SESSION_ZONE, raw_session_date): IBKR and Tradier stamp 1d at 00:00 UTC, Alpaca at
midnight New York (04:00 or 05:00 UTC). Observations carry the session date, the rule compares
sessions only, and every canonical bar is one row per session at 00:00 UTC.

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

Inputs from raw (phase 191 plan 08): the stage reads the current ohlcv_raw 1d rows of
RAW_DAILY_SERIES, one per (date, vendor, kind), and observation_from_raw turns each into the
rule's Observation: Tradier consolidated is route TRADIER, IBKR smart_trades is route SMART, or
LEGACY_IMPORT when the request that first served the value was the corpus import, Alpaca sip_rth
is route ALPACA (iex_rth is raw only and never read). fetched_at is
the raw row's served_at (when the current value was first served; an unchanged re-serve does not
move it), request_id the request that first served it. Raw is last-wins (D-191-N), so a date
carries one value per series and the rule's choice among observations collapses to that value.

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
from zoneinfo import ZoneInfo

from src.intelligence.bars.derivation import CanonicalBar, Observation, SplitRecord
from src.intelligence.bars.sources import ROUTE_ALPACA, ROUTE_TRADIER
from src.intelligence.bars.vendor_basis import BP

RULE_VERSION = "d2-v4"

TIMEFRAME = "1d"
ROUTE_SMART = "SMART"
ROUTE_LEGACY = "LEGACY_IMPORT"
VENDOR_TRADIER = "tradier"
VENDOR_IBKR = "ibkr"
VENDOR_ALPACA = "alpaca"

FLAG_FALLBACK_SEAM = "fallback_seam"
FLAG_PRE_SPLIT = "pre_split_unrefetched"
FLAG_NO_VOLUME = "no_provider_volume"

# Informational flag fields per rule; identifiers, not tunables.
FLAG_FIELDS: dict[str, tuple[str, ...]] = {
    FLAG_FALLBACK_SEAM: ("close",),
    FLAG_PRE_SPLIT: ("open", "high", "low", "close"),
    FLAG_NO_VOLUME: ("volume",),
}

# The canonical (vendor, kind) identity each policy primary serves under (plan 191-13). The
# single definition: integrity_checks imports these rather than retyping the pairs.
PRIMARY_PAIR = {
    VENDOR_TRADIER: ("tradier", "consolidated"),
    VENDOR_IBKR: ("ibkr", "named"),
    VENDOR_ALPACA: ("alpaca", "sip_rth"),
}
FALLBACK_PAIR = ("ibkr", "fallback")
# The one fallback each primary may name; IBKR, the contract-keyed vendor, names none.
FALLBACK_FOR = {VENDOR_TRADIER: VENDOR_IBKR, VENDOR_ALPACA: VENDOR_IBKR}

# The raw 1d series d2-v4 reads, as (vendor, kind). Listing-venue kinds, smart_adjusted and
# Alpaca's iex_rth are never inputs (the D-17 venue study failed; adjusted bars are never
# canonical; iex_rth is not a consolidated basis, D-191-A).
RAW_DAILY_SERIES: tuple[tuple[str, str], ...] = (
    (VENDOR_TRADIER, "consolidated"),
    (VENDOR_IBKR, "smart_trades"),
    (VENDOR_ALPACA, "sip_rth"),
)
# The zone whose calendar date of a series' 1d stamp is the NYSE session date: IBKR and Tradier
# stamp 00:00 UTC, Alpaca midnight New York. An identifier of each vendor's convention, not a
# tunable; the daily read dates rows with it, so canonical keeps one row per session.
RAW_DAILY_SESSION_ZONE: dict[tuple[str, str], str] = {
    (VENDOR_TRADIER, "consolidated"): "UTC",
    (VENDOR_IBKR, "smart_trades"): "UTC",
    (VENDOR_ALPACA, "sip_rth"): "America/New_York",
}
_ROUTE_VENDOR = {
    ROUTE_TRADIER: VENDOR_TRADIER,
    ROUTE_SMART: VENDOR_IBKR,
    ROUTE_LEGACY: VENDOR_IBKR,
    ROUTE_ALPACA: VENDOR_ALPACA,
}
_VENDORS = (VENDOR_TRADIER, VENDOR_IBKR, VENDOR_ALPACA)


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
    # d2-v4 Alpaca guards (module docstring): zero-volume Alpaca dates, Alpaca dates before the
    # span start, and the span start (None: no agreeing session, no Alpaca span).
    zero_volume: list[date] = field(default_factory=list)
    pre_start: list[date] = field(default_factory=list)
    alpaca_start: date | None = None


def observation_from_raw(
    *,
    request_id: str | None,
    vendor: str,
    kind: str,
    bar_date: date,
    open: float,
    high: float,
    low: float,
    close: float,
    volume: int | None,
    served_at: datetime | None,
    legacy: bool,
) -> Observation:
    """One current ohlcv_raw 1d row as the rule's Observation (module docstring, Inputs).

    A row without served_at has no arrival time to judge its scale by; the ingress contract
    refuses such a write and the 1d backfill stamped every row, so one here is a defect and
    raises rather than guessing current or stale. A NULL request_id (a legacy migrated row)
    becomes the empty id: it is no split's evidence.
    """
    if served_at is None:
        raise ValueError(f"raw 1d row ({vendor}, {kind}) on {bar_date} has no served_at")
    if (vendor, kind) == (VENDOR_TRADIER, "consolidated"):
        route = ROUTE_TRADIER
    elif (vendor, kind) == (VENDOR_IBKR, "smart_trades"):
        route = ROUTE_LEGACY if legacy else ROUTE_SMART
    elif (vendor, kind) == (VENDOR_ALPACA, "sip_rth"):
        route = ROUTE_ALPACA
    else:
        raise ValueError(f"raw ({vendor!r}, {kind!r}) is not a d2-v4 input series")
    return Observation(
        request_id=request_id or "",
        route=route,
        bar_date=bar_date,
        open=open,
        high=high,
        low=low,
        close=close,
        volume=volume,
        fetched_at=served_at,
        legacy=route == ROUTE_LEGACY,
    )


def raw_session_date(vendor: str, kind: str, stamp: datetime) -> date:
    """The NYSE session date of a raw 1d row: its stamp's calendar date in the series' zone
    (RAW_DAILY_SESSION_ZONE). The daily read computes the same in SQL; this is the definition."""
    try:
        zone = RAW_DAILY_SESSION_ZONE[(vendor, kind)]
    except KeyError:
        raise ValueError(f"raw ({vendor!r}, {kind!r}) is not a d2-v4 input series") from None
    if stamp.tzinfo is None:
        raise ValueError("a raw 1d stamp must be timezone-aware")
    return stamp.astimezone(ZoneInfo(zone)).date()


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


def _basis_close(day: _VendorDay, splits: Sequence[SplitRecord]) -> float | None:
    """A primary vendor's close on the current scale for the basis (module docstring, Basis)."""
    if day.current is not None:
        return day.current.close
    if day.stale is not None:
        return _restated_close(day.stale, splits)
    return None


def _by_vendor_day(
    observations: Sequence[Observation], splits: Sequence[SplitRecord]
) -> dict[str, dict[date, _VendorDay]]:
    pools: dict[str, dict[date, tuple[list[Observation], list[Observation]]]] = {
        vendor: {} for vendor in _VENDORS
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
        if (close := _basis_close(v, splits)) is not None
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


def _bar(obs: Observation, pair: tuple[str, str], flags: tuple[str, ...]) -> CanonicalBar:
    if obs.volume is None:
        flags = flags + (FLAG_NO_VOLUME,)
    return CanonicalBar(
        bar_date=obs.bar_date,
        open=obs.open,
        high=obs.high,
        low=obs.low,
        close=obs.close,
        volume=obs.volume,
        vendor=pair[0],
        kind=pair[1],
        request_ids=(obs.request_id,),
        flags=flags,
    )


def _check_policy(policy: PolicyRow) -> None:
    if policy.ingress_mode != "observed":
        raise ValueError(
            f"1d policy is {policy.ingress_mode!r}; d2-v4 derives only an observed timeframe"
        )
    if policy.primary_source not in PRIMARY_PAIR:
        raise ValueError(f"1d primary source {policy.primary_source!r} has no d2-v4 rule")
    if (
        policy.fallback_source is not None
        and FALLBACK_FOR.get(policy.primary_source) != policy.fallback_source
    ):
        raise ValueError(
            f"fallback {policy.fallback_source!r} under primary {policy.primary_source!r} has "
            "no d2-v4 rule (only IBKR may fall back, for Tradier or Alpaca)"
        )


def _is_trade(obs: Observation) -> bool:
    return obs.volume is not None and obs.volume > 0


def _basis_ratios(
    primary: dict[date, _VendorDay], ibkr: dict[date, _VendorDay], splits: Sequence[SplitRecord]
) -> dict[date, float]:
    """IBKR's current close over the primary's basis close, per common session (sorted)."""
    return {
        d: ibkr_current.close / primary_close
        for d in sorted(primary)
        if d in ibkr
        and (ibkr_current := ibkr[d].current) is not None
        and (primary_close := _basis_close(primary[d], splits)) is not None
        # A non-positive close is a provider defect the scrub flags; it measures no basis.
        and primary_close > 0
    }


def _within(ratio: float | None, tolerance_bp: float) -> bool:
    return ratio is not None and abs(ratio - 1.0) * BP <= tolerance_bp


def _alpaca_start(
    ratios: dict[date, float], window_sessions: int, tolerance_bp: float
) -> date | None:
    """The first common session where IBKR agrees with Alpaca on the session itself and in the
    median of the window_sessions common sessions from it (module docstring, Alpaca guards)."""
    common = list(ratios)
    for i, day in enumerate(common):
        if _within(ratios[day], tolerance_bp) and _within(
            _median_ratio(common[i : i + window_sessions], ratios), tolerance_bp
        ):
            return day
    return None


@dataclass(frozen=True)
class _Screened:
    """The vendor-day pools after the Alpaca guards, and what the guards kept out."""

    days: dict[str, dict[date, _VendorDay]]
    zero_volume: list[date]
    pre_start: list[date]
    alpaca_start: date | None


def _screen(
    observations: Sequence[Observation],
    splits: Sequence[SplitRecord],
    window_sessions: int,
    tolerance_bp: float,
) -> _Screened:
    is_alpaca = [_ROUTE_VENDOR.get(o.route) == VENDOR_ALPACA for o in observations]
    traded = {
        o.bar_date for o, a in zip(observations, is_alpaca, strict=True) if a and _is_trade(o)
    }
    zero_volume = sorted(
        {o.bar_date for o, a in zip(observations, is_alpaca, strict=True) if a} - traded
    )
    days = _by_vendor_day(
        [o for o, a in zip(observations, is_alpaca, strict=True) if not a or _is_trade(o)],
        splits,
    )
    alpaca = days[VENDOR_ALPACA]
    start = _alpaca_start(
        _basis_ratios(alpaca, days[VENDOR_IBKR], splits), window_sessions, tolerance_bp
    )
    days[VENDOR_ALPACA] = {d: v for d, v in alpaca.items() if start is not None and d >= start}
    pre_start = sorted(d for d in alpaca if start is None or d < start)
    return _Screened(days, zero_volume, pre_start, start)


def servable_primary_dates(
    observations: Sequence[Observation],
    splits: Sequence[SplitRecord],
    *,
    basis_window_sessions: int,
    basis_tolerance_bp: float,
) -> dict[str, frozenset[date]]:
    """Per primary that names a fallback (Tradier, Alpaca): the dates it can serve on the
    current scale, after the Alpaca guards. Where it cannot, an (ibkr, fallback) bar conforms to
    the policy (integrity_checks.policy_conformance)."""
    days = _screen(observations, splits, basis_window_sessions, basis_tolerance_bp).days
    return {
        vendor: frozenset(d for d, v in days[vendor].items() if v.current is not None)
        for vendor in FALLBACK_FOR
    }


@dataclass(frozen=True)
class _BasisFrame:
    """One primary vendor against the IBKR fallback: its head, the common sessions on the pair's
    own session axis (the dates either answered), and the head seam verdict."""

    head: date | None
    position: dict[date, int]
    ratios: dict[date, float]
    common_dates: list[date]
    common_index: list[int]
    head_admitted: bool

    @classmethod
    def build(
        cls,
        primary: dict[date, _VendorDay],
        ibkr: dict[date, _VendorDay],
        splits: Sequence[SplitRecord],
        window_sessions: int,
        tolerance_bp: float,
    ) -> _BasisFrame:
        head = min(primary, default=None)
        position = {d: i for i, d in enumerate(sorted(set(primary) | set(ibkr)))}
        ratios = _basis_ratios(primary, ibkr, splits)
        common_dates = sorted(ratios)
        seam = [d for d in common_dates if d >= head][:window_sessions] if head else []
        return cls(
            head=head,
            position=position,
            ratios=ratios,
            common_dates=common_dates,
            common_index=[position[d] for d in common_dates],
            head_admitted=_within(_median_ratio(seam, ratios), tolerance_bp),
        )

    def within_tolerance(self, day: date, window_sessions: int, tolerance_bp: float) -> bool:
        window = _nearest(self.position[day], self.common_index, self.common_dates, window_sessions)
        return _within(_median_ratio(window, self.ratios), tolerance_bp)


def derive_daily_v2(
    observations: Sequence[Observation],
    policy_rows: Sequence[PolicyRow],
    splits: Sequence[SplitRecord],
    *,
    symbol: str,
    basis_window_sessions: int,
    basis_tolerance_bp: float,
) -> DailyV2Result:
    """The canonical 1d bars of one symbol under d2-v4 (module docstring)."""
    if basis_window_sessions < 1:
        raise ValueError("basis_window_sessions must be at least 1")
    screened = _screen(observations, splits, basis_window_sessions, basis_tolerance_bp)
    days = screened.days
    frames = {
        vendor: _BasisFrame.build(
            days[vendor], days[VENDOR_IBKR], splits, basis_window_sessions, basis_tolerance_bp
        )
        for vendor in FALLBACK_FOR
    }
    axis = sorted(set().union(*(days[vendor] for vendor in _VENDORS)))

    bars: list[CanonicalBar] = []
    flags: list[DerivedFlag] = []
    head: list[date] = []
    seam_heads: dict[str, list[date]] = {vendor: [] for vendor in FALLBACK_FOR}
    refused_head: list[date] = []
    admitted: list[date] = []
    refused: list[date] = []
    stale_only: list[date] = []
    restated: list[date] = []

    for day in axis:
        policy = resolve_policy(policy_rows, symbol, day)
        _check_policy(policy)
        vendor = policy.primary_source
        primary = days[vendor].get(day)
        if primary is not None and primary.current is not None:
            bars.append(_bar(primary.current, PRIMARY_PAIR[vendor], ()))
            continue
        fallback = days[policy.fallback_source].get(day) if policy.fallback_source else None
        frame = frames.get(vendor)
        if primary is not None and primary.stale is not None:
            if (
                fallback is not None
                and fallback.current is not None
                and frame is not None
                and frame.within_tolerance(day, basis_window_sessions, basis_tolerance_bp)
            ):
                restated.append(day)
                bars.append(_bar(fallback.current, FALLBACK_PAIR, ()))
            else:
                bars.append(_bar(primary.stale, PRIMARY_PAIR[vendor], (FLAG_PRE_SPLIT,)))
            continue
        if fallback is None or frame is None:
            continue
        if fallback.current is None:
            stale_only.append(day)
            continue
        if frame.head is None:
            # No primary answer at all: nothing to splice against, the fallback is the series.
            head.append(day)
        elif day < frame.head:
            if not frame.head_admitted:
                refused_head.append(day)
                continue
            head.append(day)
            seam_heads[vendor].append(day)
        else:
            if not frame.within_tolerance(day, basis_window_sessions, basis_tolerance_bp):
                refused.append(day)
                continue
            admitted.append(day)
        bars.append(_bar(fallback.current, FALLBACK_PAIR, ()))

    for vendor, vendor_head in seam_heads.items():
        if vendor_head:
            bars = _with_seam(
                bars, flags, vendor, vendor_head, frames[vendor], basis_window_sessions
            )

    for bar in bars:
        for rule in bar.flags:
            if rule != FLAG_FALLBACK_SEAM:
                flags.append(
                    DerivedFlag(
                        bar.bar_date,
                        rule,
                        FLAG_FIELDS[rule],
                        {"vendor": bar.vendor, "kind": bar.kind},
                    )
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
        zero_volume=screened.zero_volume,
        pre_start=screened.pre_start,
        alpaca_start=screened.alpaca_start,
    )


def _with_seam(
    bars: list[CanonicalBar],
    flags: list[DerivedFlag],
    vendor: str,
    head: list[date],
    frame: _BasisFrame,
    window_sessions: int,
) -> list[CanonicalBar]:
    """Mark the first primary bar after an admitted head with the measured seam."""
    primary_head = frame.head
    assert primary_head is not None  # a seam head exists only before a primary head
    first = next(
        (
            i
            for i, b in enumerate(bars)
            if (b.vendor, b.kind) == PRIMARY_PAIR[vendor] and b.bar_date >= primary_head
        ),
        None,
    )
    if first is None:
        return bars
    overlap = [d for d in frame.common_dates if d >= primary_head][:window_sessions]
    median = _median_ratio(overlap, frame.ratios)
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
                "deviation_bp": None if median is None else abs(median - 1.0) * BP,
            },
        )
    )
    seam = replace(seam_bar, flags=seam_bar.flags + (FLAG_FALLBACK_SEAM,))
    return [*bars[:first], seam, *bars[first + 1 :]]
