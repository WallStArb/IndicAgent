"""Massive load checks, systemic half (admission design section 8a, stages A and B): pure math.

Design: docs/plans/2026-11-10-massive-admission-db-design.md section 8a (the twelve-row table and
the three 2026-11-10 amendments), section 3 (the 1d kind decision) and section 8 step 6. Pure Ring 1:
arrays and dataclasses in, verdicts out; no file, no database. The runner is
`scripts/ops/bars/ops_massive_load_checks.py`.

Thresholds here are SPEC CONSTANTS quoted from the design table, not tunables (a switch on any of
them would change what a check means, so each moves with a design amendment, never a config write).
Era is the calendar year of the session (a definition of this runner: the design says "per era"
without naming the width).

Every check function states the count it judged on and raises on an empty input
(``VacuousCheckError``): a check that matched nothing must fail loudly, never pass.

Session offset method (the design asks for "no systematic offset against the NYSE grid"): the
minute with the most total volume within 30 minutes of the session open is the opening auction
minute, so it must sit at offset 0; the peak within 30 minutes of the close is the closing
auction, stamped on the last session minute (offset -1) or on the close minute itself (offset 0,
the closing print of an early-close day). A one-hour DST error or a time-zone slip lands at plus or
minus 60 minutes, far outside. An era is a systemic offset only when a MAJORITY of its drawn days fail; failing days are always listed.
"""

from __future__ import annotations

import math
import random
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np

# --- spec constants (design section 8a) --------------------------------------------------------
#: Record sanity: high/low consistency must hold on this share of bars.
SANITY_MIN_CONSISTENT_SHARE = 0.999
#: Day file against minute file: close mismatch on more than this share of names in any era decides
#: the 1d kind (section 3 and 8a).
DAY_CLOSE_MISMATCH_MAX_SHARE = 0.01
#: Volume bands: median IBKR/Massive ratio per era and exchange.
VOLUME_MEDIAN_BAND = (0.8, 1.25)
#: Volume bands: a name outside this band counts against the 2 percent allowance.
VOLUME_NAME_BAND = (0.5, 2.0)
VOLUME_MAX_OUTSIDE_SHARE = 0.02
#: Publish lag: the last N sessions.
PUBLISH_LAG_SESSIONS = 20
#: Session check: the volume peak search half-window, in minutes, and the offsets a peak may take.
SESSION_PEAK_HALF_WINDOW_MIN = 30
SESSION_OPEN_OFFSETS = frozenset({0})
SESSION_CLOSE_OFFSETS = frozenset({-1, 0})
#: Day against minute: price equality tolerance (served prices carry at most 4 decimals, so a
#: float-noise bound; a real print difference is at least 1e-4) and volume tolerance in shares
#: (the day file is rounded half to even to whole shares; fractional minute sums are rounded alike).
PRICE_EQUAL_ABS_TOL = 1e-6
VOLUME_EQUAL_ABS_TOL = 0.5

_NY = ZoneInfo("America/New_York")
_NS_PER_MIN = 60 * 1_000_000_000


class VacuousCheckError(ValueError):
    """A check matched nothing; an empty join is a failure, never a pass."""


def era_of(day: date) -> int:
    """The era of a session: its calendar year."""
    return day.year


# --- record sanity -----------------------------------------------------------------------------
@dataclass(frozen=True)
class SanityCounts:
    n_rows: int
    n_ohlc_inconsistent: int  # high < max(open, close) or low > min(open, close) or high < low
    n_nonpositive_price: int
    n_negative_volume: int
    n_duplicate_keys: int  # extra rows beyond the first per (ticker, window_start)

    @property
    def consistent_share(self) -> float:
        return 1.0 - self.n_ohlc_inconsistent / self.n_rows

    def __add__(self, other: SanityCounts) -> SanityCounts:
        return SanityCounts(
            self.n_rows + other.n_rows,
            self.n_ohlc_inconsistent + other.n_ohlc_inconsistent,
            self.n_nonpositive_price + other.n_nonpositive_price,
            self.n_negative_volume + other.n_negative_volume,
            self.n_duplicate_keys + other.n_duplicate_keys,
        )


def record_sanity(
    ticker_code: np.ndarray,
    window_start: np.ndarray,
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray,
) -> SanityCounts:
    """Sanity counts of one file's rows (``ticker_code`` identifies the ticker per row).

    Not-a-number prices count as non-positive (a comparison with NaN is false, so the negation
    form is used throughout)."""
    n = len(window_start)
    if n == 0:
        raise VacuousCheckError("record_sanity: no rows")
    consistent = (
        (high >= np.maximum(open_, close)) & (low <= np.minimum(open_, close)) & (high >= low)
    )
    positive = (open_ > 0) & (high > 0) & (low > 0) & (close > 0)
    order = np.lexsort((window_start, ticker_code))
    c, w = ticker_code[order], window_start[order]
    dups = int(np.count_nonzero((c[1:] == c[:-1]) & (w[1:] == w[:-1])))
    return SanityCounts(
        n_rows=n,
        n_ohlc_inconsistent=int(np.count_nonzero(~consistent)),
        n_nonpositive_price=int(np.count_nonzero(~positive)),
        n_negative_volume=int(np.count_nonzero(~(volume >= 0))),
        n_duplicate_keys=dups,
    )


def sanity_verdict(counts: SanityCounts) -> str:
    """``ok`` or ``stop``: high/low consistent on 99.9 percent of bars, and strictly positive
    prices, non-negative volume and unique keys with no exception (design 8a, record sanity)."""
    if counts.n_rows <= 0:
        raise VacuousCheckError("sanity_verdict: no rows judged")
    ok = (
        counts.consistent_share >= SANITY_MIN_CONSISTENT_SHARE
        and counts.n_nonpositive_price == 0
        and counts.n_negative_volume == 0
        and counts.n_duplicate_keys == 0
    )
    return "ok" if ok else "stop"


# --- session -----------------------------------------------------------------------------------
def dst_transition_sessions(start: date, end: date) -> list[date]:
    """Calendar days in [start, end] whose New York UTC offset differs from the previous day's."""
    days: list[date] = []
    prev = datetime.combine(start - timedelta(days=1), time(12), tzinfo=_NY).utcoffset()
    day = start
    while day <= end:
        cur = datetime.combine(day, time(12), tzinfo=_NY).utcoffset()
        if cur != prev:
            days.append(day)
        prev = cur
        day += timedelta(days=1)
    return days


def post_dst_sessions(sessions: Sequence[date]) -> list[date]:
    """The first session on or after each DST transition inside the session range."""
    if not sessions:
        return []
    ordered = sorted(sessions)
    out = []
    for change in dst_transition_sessions(ordered[0], ordered[-1]):
        first = next((s for s in ordered if s >= change), None)
        if first is not None:
            out.append(first)
    return out


def early_close_sessions(bounds: Mapping[date, tuple[datetime, datetime]]) -> list[date]:
    """Sessions shorter than the regular 6.5 hours (the irregular 15:56 close included)."""
    full = timedelta(hours=6, minutes=30)
    return sorted(d for d, (o, c) in bounds.items() if c - o < full - timedelta(minutes=3))


def seeded_session_draw(
    sessions: Sequence[date],
    *,
    per_era: int,
    seed: int,
    early_closes: Iterable[date],
    post_dst: Iterable[date],
) -> list[date]:
    """A seeded draw of ``per_era`` sessions per era, plus (forced into the draw) one early close and
    one post-DST session of every era that has them. Deterministic given (sessions, per_era,
    seed): each era uses its own ``random.Random(f"{seed}:{era}")``. Sorted, unique."""
    by_era: dict[int, list[date]] = {}
    for day in sorted(set(sessions)):
        by_era.setdefault(era_of(day), []).append(day)
    early_by_era: dict[int, list[date]] = {}
    for day in sorted(set(early_closes)):
        early_by_era.setdefault(era_of(day), []).append(day)
    dst_by_era: dict[int, list[date]] = {}
    for day in sorted(set(post_dst)):
        dst_by_era.setdefault(era_of(day), []).append(day)
    chosen: set[date] = set()
    for era, days in by_era.items():
        rng = random.Random(f"{seed}:{era}")
        chosen.update(rng.sample(days, min(per_era, len(days))))
        inside = set(days)
        for forced in (early_by_era.get(era, []), dst_by_era.get(era, [])):
            candidates = [d for d in forced if d in inside]
            if candidates:
                chosen.add(rng.choice(candidates))
    return sorted(chosen)


def volume_peak_offset_minutes(
    window_start_ns: np.ndarray,
    volume: np.ndarray,
    anchor_ns: int,
    *,
    half_window_min: int = SESSION_PEAK_HALF_WINDOW_MIN,
) -> int:
    """Offset in minutes (from ``anchor_ns``) of the minute with the most total volume within
    ``half_window_min`` minutes either side. Raises when the window holds no volume."""
    minute = (window_start_ns - anchor_ns) // _NS_PER_MIN
    sel = (minute >= -half_window_min) & (minute < half_window_min)
    if not sel.any() or not np.any(volume[sel] > 0):
        raise VacuousCheckError("volume_peak_offset_minutes: no volume near the anchor")
    profile = np.bincount(
        (minute[sel] + half_window_min).astype(np.int64),
        weights=volume[sel],
        minlength=2 * half_window_min,
    )
    return int(np.argmax(profile)) - half_window_min


@dataclass(frozen=True)
class SessionDayResult:
    day: date
    era: int
    open_offset_min: int
    close_offset_min: int  # relative to the session close (the last session minute is -1)

    @property
    def passed(self) -> bool:
        return (
            self.open_offset_min in SESSION_OPEN_OFFSETS
            and self.close_offset_min in SESSION_CLOSE_OFFSETS
        )


def session_day_result(
    day: date,
    window_start_ns: np.ndarray,
    volume: np.ndarray,
    open_ns: int,
    close_ns: int,
) -> SessionDayResult:
    """Open offset against the session open; close offset against the session close."""
    return SessionDayResult(
        day=day,
        era=era_of(day),
        open_offset_min=volume_peak_offset_minutes(window_start_ns, volume, open_ns),
        close_offset_min=volume_peak_offset_minutes(window_start_ns, volume, close_ns),
    )


def session_verdict_by_era(results: Sequence[SessionDayResult]) -> dict[int, dict[str, object]]:
    """Per era: the median offsets, the failing days and ``ok``/``stop`` (a majority of failing days = stop)."""
    if not results:
        raise VacuousCheckError("session_verdict_by_era: no days judged")
    out: dict[int, dict[str, object]] = {}
    for era in sorted({r.era for r in results}):
        rows = [r for r in results if r.era == era]
        med_open = float(np.median([r.open_offset_min for r in rows]))
        med_close = float(np.median([r.close_offset_min for r in rows]))
        failing = [r for r in rows if not r.passed]
        systemic = len(failing) * 2 > len(rows)  # a majority of the era's days
        out[era] = {
            "n_days": len(rows),
            "median_open_offset_min": med_open,
            "median_close_offset_min": med_close,
            "failing_days": [r.day.isoformat() for r in failing],
            "verdict": "stop" if systemic else "ok",
        }
    return out


# --- publish lag and manifest ------------------------------------------------------------------
def publish_lag_hours(last_modified: datetime, close_utc: datetime) -> float:
    """Hours after the session close at which the file first appeared (negative: before the close,
    which a day file or minute file of the same date must never be)."""
    if last_modified.tzinfo is None or close_utc.tzinfo is None:
        raise ValueError("publish_lag_hours: timezone-aware datetimes required")
    return (last_modified - close_utc).total_seconds() / 3600.0


def manifest_completeness(
    sessions: Sequence[date], manifest: Mapping[str, Mapping[date, Mapping[str, object]]]
) -> dict[str, dict[str, object]]:
    """Per dataset: every session has a row with a positive row count, a 64-hex sha256 and a clean
    gzip; the missing and the malformed sessions are listed. ``manifest`` maps dataset to
    session date to its manifest row. An empty session list raises."""
    if not sessions:
        raise VacuousCheckError("manifest_completeness: no sessions")
    out: dict[str, dict[str, object]] = {}
    for dataset, rows in manifest.items():
        missing = [d.isoformat() for d in sessions if d not in rows]
        bad = []
        for d in sessions:
            row = rows.get(d)
            if row is None:
                continue
            sha = str(row.get("sha256", ""))
            rows_n = row.get("rows")
            if (
                len(sha) != 64
                or not isinstance(rows_n, int)
                or rows_n <= 0
                or row.get("gzip_ok") is not True
            ):
                bad.append(d.isoformat())
        out[dataset] = {
            "n_sessions": len(sessions),
            "n_present": len(sessions) - len(missing),
            "missing": missing,
            "malformed": bad,
            "complete": not missing and not bad,
        }
    return out


# --- survivorship ------------------------------------------------------------------------------
@dataclass(frozen=True)
class SurvivorshipRow:
    symbol: str
    first_bar: date | None
    last_bar: date | None
    listing_end: date | None
    reading: str  # absent | present_active | ends_at_listing_end | ends_before | ends_after | no_listing_end_ended


def survivorship_reading(
    first_bar: date | None,
    last_bar: date | None,
    listing_end: date | None,
    archive_end: date,
    *,
    slack_sessions_days: int = 7,
) -> str:
    """Disclosure only, never a gate. ``slack_sessions_days`` is calendar slack for a last print
    that precedes the delisting stamp (a reporting convention, not a pass threshold)."""
    if first_bar is None or last_bar is None:
        return "absent"
    if listing_end is None:
        return (
            "present_active"
            if last_bar >= archive_end - timedelta(days=slack_sessions_days)
            else "no_listing_end_ended"
        )
    if last_bar > listing_end + timedelta(days=slack_sessions_days):
        return "ends_after"
    if last_bar >= listing_end - timedelta(days=slack_sessions_days):
        return "ends_at_listing_end"
    return "ends_before"


# --- stage B: day file against minute file -----------------------------------------------------
@dataclass(frozen=True)
class TickerOhlcv:
    """Per-ticker aggregate arrays aligned with ``tickers`` (NaN where the ticker has no row)."""

    tickers: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray


def aggregate_by_ticker(
    tickers: np.ndarray,
    ticker_code: np.ndarray,
    window_start: np.ndarray,
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray,
    mask: np.ndarray,
) -> TickerOhlcv:
    """Per ticker first open, max high, min low, last close, summed volume of the rows under
    ``mask`` (time-ordered inside a ticker). A ticker with no masked row holds NaN."""
    n = len(tickers)
    out = {k: np.full(n, np.nan) for k in ("o", "h", "l", "c", "v")}
    idx = np.flatnonzero(mask)
    if len(idx):
        order = np.lexsort((window_start[idx], ticker_code[idx]))
        idx = idx[order]
        code = ticker_code[idx]
        starts = np.flatnonzero(np.r_[True, code[1:] != code[:-1]])
        last = np.r_[starts[1:], len(idx)] - 1
        t = code[starts]
        out["o"][t] = open_[idx][starts]
        out["h"][t] = np.maximum.reduceat(high[idx], starts)
        out["l"][t] = np.minimum.reduceat(low[idx], starts)
        out["c"][t] = close[idx][last]
        out["v"][t] = np.add.reduceat(volume[idx], starts)
    return TickerOhlcv(tickers, out["o"], out["h"], out["l"], out["c"], out["v"])


@dataclass(frozen=True)
class DayVsMinuteCounts:
    """Mismatch counts of one session, day file against one minute aggregate (RTH or all hours)."""

    n_names: int  # names in the day file that also have an aggregate row
    n_day_only: int  # day-file names with no aggregate row (listed, never assumed)
    mismatch_open: int
    mismatch_high: int
    mismatch_low: int
    mismatch_close: int
    mismatch_volume: int

    def __add__(self, other: DayVsMinuteCounts) -> DayVsMinuteCounts:
        return DayVsMinuteCounts(*(a + b for a, b in zip(self._t(), other._t(), strict=True)))

    def _t(self) -> tuple[int, ...]:
        return (
            self.n_names,
            self.n_day_only,
            self.mismatch_open,
            self.mismatch_high,
            self.mismatch_low,
            self.mismatch_close,
            self.mismatch_volume,
        )


def compare_day_to_minutes(
    day_by_ticker: Mapping[str, tuple[float, float, float, float, float]],
    agg: TickerOhlcv,
) -> DayVsMinuteCounts:
    """Compare each day-file row (open, high, low, close, volume) with the aggregate of the same
    ticker. A day-file name with no aggregate is counted in ``n_day_only``."""
    if not day_by_ticker:
        raise VacuousCheckError("compare_day_to_minutes: empty day file")
    pos = {str(t): i for i, t in enumerate(agg.tickers)}
    n = day_only = 0
    mism = [0, 0, 0, 0, 0]
    for name, vals in day_by_ticker.items():
        i = pos.get(name)
        if i is None or math.isnan(agg.close[i]):
            day_only += 1
            continue
        n += 1
        got = (agg.open[i], agg.high[i], agg.low[i], agg.close[i], agg.volume[i])
        for k in range(4):
            if abs(vals[k] - got[k]) > PRICE_EQUAL_ABS_TOL:
                mism[k] += 1
        if abs(vals[4] - got[4]) > VOLUME_EQUAL_ABS_TOL:
            mism[4] += 1
    return DayVsMinuteCounts(n, day_only, *mism)


def day_vs_minute_verdict(
    rth_by_era: Mapping[int, DayVsMinuteCounts],
) -> dict[str, object]:
    """Section 3 / 8a: if the day file's close differs from the RTH minute aggregate on more than
    1 percent of names in any era, 1d is built from RTH minutes (``rth_minutes``); otherwise the
    served day file is the 1d kind (``served``). Per-era shares are returned. An era with no
    matched name raises."""
    shares: dict[int, float] = {}
    for era, counts in sorted(rth_by_era.items()):
        if counts.n_names <= 0:
            raise VacuousCheckError(f"day_vs_minute_verdict: era {era} matched no name")
        shares[era] = counts.mismatch_close / counts.n_names
    failing = [e for e, s in shares.items() if s > DAY_CLOSE_MISMATCH_MAX_SHARE]
    return {
        "close_mismatch_share_by_era": shares,
        "eras_over_limit": failing,
        "decision": "rth_minutes" if failing else "served",
    }


# --- stage B: volume bands ---------------------------------------------------------------------
@dataclass(frozen=True)
class VolumeBandRow:
    era: int
    exchange: str
    n_names: int
    median_ratio: float
    n_outside_name_band: int
    median_in_band: bool
    outside_share: float
    verdict: str  # ok | stop


def volume_bands(
    name_ratios: Mapping[tuple[int, str], Mapping[str, float]],
) -> list[VolumeBandRow]:
    """Per (era, listing exchange): the median over names of the per-name median IBKR/Massive
    volume ratio must sit in 0.8..1.25 and at most 2 percent of names outside 0.5..2.0. Input maps
    (era, exchange) to {name: ratio}. A cell with no name raises (never vacuous)."""
    rows: list[VolumeBandRow] = []
    for (era, exchange), ratios in sorted(name_ratios.items()):
        vals = np.array([r for r in ratios.values() if r > 0 and math.isfinite(r)])
        if len(vals) == 0:
            raise VacuousCheckError(f"volume_bands: ({era}, {exchange}) has no usable name")
        median = float(np.median(vals))
        outside = int(np.count_nonzero((vals < VOLUME_NAME_BAND[0]) | (vals > VOLUME_NAME_BAND[1])))
        share = outside / len(vals)
        in_band = VOLUME_MEDIAN_BAND[0] <= median <= VOLUME_MEDIAN_BAND[1]
        rows.append(
            VolumeBandRow(
                era,
                exchange,
                len(vals),
                median,
                outside,
                in_band,
                share,
                "ok" if in_band and share <= VOLUME_MAX_OUTSIDE_SHARE else "stop",
            )
        )
    return rows


def count_by(items: Iterable[str]) -> dict[str, int]:
    """Sorted counts, for summary JSON."""
    return dict(sorted(Counter(items).items()))
