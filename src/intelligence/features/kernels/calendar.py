"""Calendar and session-time kernels (D-25)."""

from __future__ import annotations

import calendar
import math
from datetime import date, datetime
from typing import TYPE_CHECKING

import numpy as np

from src.intelligence.feature_cache import FeatureCache
from src.intelligence.features.contract.registry import Kernel
from src.intelligence.features.kernels._primitives import unique_datetimes

if TYPE_CHECKING:
    from src.intelligence.feature_factory import FeatureFactoryConfig


# Calendar constant: average days per quarter (365.25 / 4). Not a tunable — fixed by definition.
_QUARTER_LENGTH_DAYS: float = 91.25


def _session_time_pos(bar_ts: datetime, config: FeatureFactoryConfig) -> float:
    """Continuous [0, 1] position within the NY regular session for bar_ts's date.

    Formula: clamp((total_minutes - start_minutes) / (end_minutes - start_minutes), 0.0, 1.0).
    0.0 before/at session open, 1.0 at/after session close. Pure timestamp arithmetic — no
    OHLCV. Deviation from source spec (discrete bar_index/total_session_bars) documented in
    142.5-01-PLAN.md: continuous fraction is TF-independent (session bar count varies by TF).
    """
    total_minutes = bar_ts.hour * 60 + bar_ts.minute
    start_minutes = config.ny_session_start_utc_hour * 60 + config.ny_session_start_utc_minute
    end_minutes = config.ny_session_end_utc_hour * 60
    session_length = end_minutes - start_minutes
    if session_length <= 0:
        return 0.0
    frac = (total_minutes - start_minutes) / session_length
    return max(0.0, min(1.0, frac))


def _cyc(value: float, period: float) -> tuple[float, float]:
    """(sin, cos) of the angle 2*pi*value/period, evaluated in that operand order."""
    angle = 2.0 * math.pi * value / period
    return math.sin(angle), math.cos(angle)


def _hour_of_day_sin(bar_ts: datetime) -> float:
    """Circular hour-of-day encoding: sin(2*pi*(hour + minute/60)/24)."""
    hour = bar_ts.hour + bar_ts.minute / 60.0
    return _cyc(hour, 24.0)[0]


def _hour_of_day_cos(bar_ts: datetime) -> float:
    """Circular hour-of-day encoding: cos(2*pi*(hour + minute/60)/24)."""
    hour = bar_ts.hour + bar_ts.minute / 60.0
    return _cyc(hour, 24.0)[1]


def _week_of_month_sin(bar_ts: datetime) -> float:
    """Circular week-of-month encoding: sin(2*pi*week/5). week = (day-1)//7 + 1."""
    week = (bar_ts.day - 1) // 7 + 1
    return _cyc(week, 5.0)[0]


def _week_of_month_cos(bar_ts: datetime) -> float:
    """Circular week-of-month encoding: cos(2*pi*week/5). week = (day-1)//7 + 1."""
    week = (bar_ts.day - 1) // 7 + 1
    return _cyc(week, 5.0)[1]


def _day_of_month_sin(bar_ts: datetime) -> float:
    """Circular day-of-month encoding: sin(2*pi*day/31)."""
    return _cyc(bar_ts.day, 31.0)[0]


def _day_of_month_cos(bar_ts: datetime) -> float:
    """Circular day-of-month encoding: cos(2*pi*day/31)."""
    return _cyc(bar_ts.day, 31.0)[1]


def _week_of_year_sin(bar_ts: datetime) -> float:
    """Circular week-of-year encoding: sin(2*pi*isocalendar_week/52)."""
    _, week, _ = bar_ts.isocalendar()
    return _cyc(week, 52.0)[0]


def _week_of_year_cos(bar_ts: datetime) -> float:
    """Circular week-of-year encoding: cos(2*pi*isocalendar_week/52)."""
    _, week, _ = bar_ts.isocalendar()
    return _cyc(week, 52.0)[1]


def _month_sin(bar_ts: datetime) -> float:
    """Circular month-of-year encoding: sin(2*pi*month/12). NEW pair — only
    _month_position (linear) existed before this plan."""
    return _cyc(bar_ts.month, 12.0)[0]


def _month_cos(bar_ts: datetime) -> float:
    """Circular month-of-year encoding: cos(2*pi*month/12). NEW pair — only
    _month_position (linear) existed before this plan."""
    return _cyc(bar_ts.month, 12.0)[1]


def _in_ny_session(bar_ts: datetime, config: FeatureFactoryConfig) -> float:
    """1.0 if bar_ts is within NY RTH, else 0.0."""
    total_minutes = bar_ts.hour * 60 + bar_ts.minute
    start_minutes = config.ny_session_start_utc_hour * 60 + config.ny_session_start_utc_minute
    end_minutes = config.ny_session_end_utc_hour * 60
    return 1.0 if start_minutes <= total_minutes < end_minutes else 0.0


def _in_overlap(bar_ts: datetime, config: FeatureFactoryConfig) -> float:
    """1.0 if bar_ts is in London-NY overlap, else 0.0."""
    return (
        1.0 if config.overlap_start_utc_hour <= bar_ts.hour < config.overlap_end_utc_hour else 0.0
    )


def _dow_encoding(bar_ts: datetime) -> tuple[float, float]:
    """Cyclic weekday encoding: (sin(2*pi*weekday/5), cos(2*pi*weekday/5)).

    weekday() returns 0=Monday, 4=Friday. Weekends treated as Friday.
    """
    weekday = min(bar_ts.weekday(), 4)
    return _cyc(weekday, 5.0)


def _month_position(bar_ts: datetime) -> float:
    """day_of_month / days_in_month: position within the month in (0, 1]."""
    days = calendar.monthrange(bar_ts.year, bar_ts.month)[1]
    return bar_ts.day / days


def _in_london_kz(bar_ts: datetime, config: FeatureFactoryConfig) -> float:
    """1.0 if bar_ts is in the London killzone, else 0.0."""
    return (
        1.0
        if config.london_kz_start_utc_hour <= bar_ts.hour < config.london_kz_end_utc_hour
        else 0.0
    )


def _power_hour(bar_ts: datetime, config: FeatureFactoryConfig) -> float:
    """1.0 if bar_ts is in power hour, else 0.0."""
    return (
        1.0
        if config.power_hour_start_utc_hour <= bar_ts.hour < config.power_hour_end_utc_hour
        else 0.0
    )


def _opening_range(bar_ts: datetime, config: FeatureFactoryConfig) -> float:
    """1.0 if bar_ts is in the first 30 min of NY session, else 0.0."""
    total_minutes = bar_ts.hour * 60 + bar_ts.minute
    return (
        1.0
        if config.opening_range_start_minute <= total_minutes < config.opening_range_end_minute
        else 0.0
    )


def _quarter_position(bar_ts: datetime) -> float:
    """Position within the quarter: 0.0 at quarter start, approaching 1.0 at end.

    Formula: (month_in_quarter * 30 + day) / QUARTER_LENGTH_DAYS
    """
    month_in_q = (bar_ts.month - 1) % 3
    day_in_q = month_in_q * 30 + bar_ts.day
    return min(1.0, day_in_q / _QUARTER_LENGTH_DAYS)


def _days_to_month_end_fraction(bar_ts: datetime) -> float:
    """Fraction of month remaining: 0.0 at month end, approaching 1.0 at start."""
    days_in_month = calendar.monthrange(bar_ts.year, bar_ts.month)[1]
    days_remaining = days_in_month - bar_ts.day
    return days_remaining / days_in_month


def _quarter_cycle_encoding(bar_ts: datetime) -> tuple[float, float]:
    """First circular harmonic of _quarter_position(): (sin(2*pi*qp), cos(2*pi*qp)).

    Reuses _quarter_position() directly rather than recomputing the
    within-quarter position (Phase 151 Plan 01, todo 104).
    """
    qp = _quarter_position(bar_ts)
    return _cyc(qp, 1.0)


def _tdom_encoding(bar_ts: datetime) -> tuple[float, float]:
    """Cyclic trading-day-of-month encoding: (sin(2*pi*t/W), cos(2*pi*t/W)).

    t = count of Mon-Fri weekdays from the 1st of the month through
    bar_ts.date() inclusive. W = total Mon-Fri weekday count in that
    calendar month. Closed-form weekday arithmetic; deliberately ignores
    market holidays (Phase 151 Plan 01, todo 104 -- source doc rejects a
    nonstationary holiday table). Guard W <= 0 -> (0.0, 0.0).
    """
    year, month = bar_ts.year, bar_ts.month
    days_in_month = calendar.monthrange(year, month)[1]
    first_weekday = calendar.weekday(year, month, 1)  # 0=Monday
    # Weekday count in [1, day] inclusive: number of days in that range whose
    # (first_weekday + offset) % 7 < 5 (Mon-Fri).
    t = sum(1 for d in range(1, bar_ts.day + 1) if (first_weekday + d - 1) % 7 < 5)
    w = sum(1 for d in range(1, days_in_month + 1) if (first_weekday + d - 1) % 7 < 5)
    if w <= 0:
        return 0.0, 0.0
    return _cyc(t, w)


def _minute_of_hour_encoding(bar_ts: datetime) -> tuple[float, float]:
    """Cyclic minute-of-hour encoding: (sin(2*pi*minute/60), cos(2*pi*minute/60)).

    Constant at 1h/1d by construction (minute is always 0 for hourly/daily
    bars) -- expected and correct, not a bug (Phase 151 Plan 01, todo 104).
    """
    return _cyc(bar_ts.minute, 60.0)


def _opex_flag(bar_ts: datetime) -> float:
    """1.0 iff bar_ts falls on the monthly options-expiration Friday, else 0.0.

    Formula (Phase 151 Plan 05, todos 066/104): dow == Friday (weekday() == 4)
    AND week_of_month == 3, where week_of_month = (day - 1) // 7 + 1. Matches
    docs/research/signal-temporal-atomic-primitives.md's prescribed formula
    literally. Deliberately no market-holiday table -- the source doc rejects
    one as nonstationary institutional data (same rationale as _tdom_encoding
    above).
    """
    week_of_month = (bar_ts.day - 1) // 7 + 1
    return 1.0 if (bar_ts.weekday() == 4 and week_of_month == 3) else 0.0


def _quad_witching_flag(bar_ts: datetime) -> float:
    """1.0 iff bar_ts is a quarterly quad-witching Friday, else 0.0.

    Formula: _opex_flag(bar_ts) == 1.0 AND bar_ts.month % 3 == 0 (quarter-end
    month). Calls _opex_flag directly rather than restating its condition
    (Phase 151 Plan 05).
    """
    return 1.0 if (_opex_flag(bar_ts) == 1.0 and bar_ts.month % 3 == 0) else 0.0


def _days_since_quarter_end(bar_ts: datetime) -> float:
    """Raw calendar days since the most recent quarter end (Mar 31, Jun 30,
    Sep 30, Dec 31), including the prior year's Dec 31 for January dates.

    Formula (Phase 176 Plan 03, todo 353): find the latest quarter-end date
    on or before bar_ts.date(), return the day-count difference as a float.
    True calendar-day counting via bar_ts.date() arithmetic only -- deliberately
    does NOT reuse _QUARTER_LENGTH_DAYS (91.25), which encodes
    _quarter_position's 30-day-per-month approximation; conflating the two
    would make this field exactly collinear with quarter_position instead of
    the measured 0.935 correlation.
    """
    d = bar_ts.date()
    candidates = [
        date(year, month, day)
        for year in (d.year, d.year - 1)
        for month, day in ((3, 31), (6, 30), (9, 30), (12, 31))
    ]
    most_recent_quarter_end = max(c for c in candidates if c <= d)
    return float((d - most_recent_quarter_end).days)


def _earnings_season_flag(bar_ts: datetime, config: FeatureFactoryConfig) -> float:
    """1.0 iff bar_ts falls within [config.earnings_season_start_days,
    config.earnings_season_end_days] calendar days after the most recent
    quarter end, else 0.0. Both boundaries inclusive.

    Formula (Phase 176 Plan 03, todo 353): calls _days_since_quarter_end(bar_ts)
    directly rather than restating the quarter-end arithmetic (reuse
    discipline, mirrors _quad_witching_flag calling _opex_flag). Window
    boundaries (feature.earnings_season.start_days,
    feature.earnings_season.end_days) come from D-04's corrected
    re-verification: 1.90x in-season/off-season ratio, Welch p=5.05e-05, 67%
    of symbols (155/233) -- the todo's original superseded figures (a much
    larger ratio, a much smaller p-value, and a higher symbol percentage from
    an earlier flawed window) must not be cited. Market-wide calendar proxy
    only, no per-company earnings-date table by design (same
    nonstationary-institutional-data rejection rationale as _opex_flag's
    no-market-holiday-table decision).
    """
    days = _days_since_quarter_end(bar_ts)
    return (
        1.0 if config.earnings_season_start_days <= days <= config.earnings_season_end_days else 0.0
    )


# ---------------------------------------------------------------------------
# Kernels. Each distinct int64 ns bar start becomes a UTC datetime once and goes through the same
# scalar helper compute() calls, so every value is bit-identical to the per-bar call; rows that
# share a timestamp share the value. Memory is 0: a row reads only its own timestamp.
# ---------------------------------------------------------------------------

_SESSION_OUTPUTS = (
    "in_ny_session",
    "in_london_kz",
    "in_overlap",
    "power_hour",
    "opening_range",
    "session_time_pos",
)
_CYCLE_OUTPUTS = (
    "dow_sin",
    "dow_cos",
    "month_position",
    "quarter_position",
    "days_to_month_end",
    "quarter_cycle_sin",
    "quarter_cycle_cos",
    "tdom_sin",
    "tdom_cos",
    "minute_of_hour_sin",
    "minute_of_hour_cos",
    "hour_of_day_sin",
    "hour_of_day_cos",
    "week_of_month_sin",
    "week_of_month_cos",
    "day_of_month_sin",
    "day_of_month_cos",
    "week_of_year_sin",
    "week_of_year_cos",
    "month_sin",
    "month_cos",
)
_EVENT_OUTPUTS = (
    "opex_flag",
    "quad_witching_flag",
    "earnings_season_flag",
    "days_since_quarter_end",
)


def _compute_session(inputs, config):
    inverse, dts = unique_datetimes(inputs["ts_dt"])
    out = {name: np.empty(len(dts)) for name in _SESSION_OUTPUTS}
    for i, bar_ts in enumerate(dts):
        out["in_ny_session"][i] = _in_ny_session(bar_ts, config)
        out["in_london_kz"][i] = _in_london_kz(bar_ts, config)
        out["in_overlap"][i] = _in_overlap(bar_ts, config)
        out["power_hour"][i] = _power_hour(bar_ts, config)
        out["opening_range"][i] = _opening_range(bar_ts, config)
        out["session_time_pos"][i] = _session_time_pos(bar_ts, config)
    return {name: values[inverse] for name, values in out.items()}


def _compute_cycles(inputs, config):
    inverse, dts = unique_datetimes(inputs["ts_dt"])
    out = {name: np.empty(len(dts)) for name in _CYCLE_OUTPUTS}
    for i, bar_ts in enumerate(dts):
        out["dow_sin"][i], out["dow_cos"][i] = _dow_encoding(bar_ts)
        out["month_position"][i] = _month_position(bar_ts)
        out["quarter_position"][i] = _quarter_position(bar_ts)
        out["days_to_month_end"][i] = _days_to_month_end_fraction(bar_ts)
        out["quarter_cycle_sin"][i], out["quarter_cycle_cos"][i] = _quarter_cycle_encoding(bar_ts)
        out["tdom_sin"][i], out["tdom_cos"][i] = _tdom_encoding(bar_ts)
        out["minute_of_hour_sin"][i], out["minute_of_hour_cos"][i] = _minute_of_hour_encoding(
            bar_ts
        )
        out["hour_of_day_sin"][i] = _hour_of_day_sin(bar_ts)
        out["hour_of_day_cos"][i] = _hour_of_day_cos(bar_ts)
        out["week_of_month_sin"][i] = _week_of_month_sin(bar_ts)
        out["week_of_month_cos"][i] = _week_of_month_cos(bar_ts)
        out["day_of_month_sin"][i] = _day_of_month_sin(bar_ts)
        out["day_of_month_cos"][i] = _day_of_month_cos(bar_ts)
        out["week_of_year_sin"][i] = _week_of_year_sin(bar_ts)
        out["week_of_year_cos"][i] = _week_of_year_cos(bar_ts)
        out["month_sin"][i] = _month_sin(bar_ts)
        out["month_cos"][i] = _month_cos(bar_ts)
    return {name: values[inverse] for name, values in out.items()}


def _compute_events(inputs, config):
    inverse, dts = unique_datetimes(inputs["ts_dt"])
    out = {name: np.empty(len(dts)) for name in _EVENT_OUTPUTS}
    for i, bar_ts in enumerate(dts):
        out["opex_flag"][i] = _opex_flag(bar_ts)
        out["quad_witching_flag"][i] = _quad_witching_flag(bar_ts)
        out["earnings_season_flag"][i] = _earnings_season_flag(bar_ts, config)
        out["days_since_quarter_end"][i] = _days_since_quarter_end(bar_ts)
    return {name: values[inverse] for name, values in out.items()}


def _compute_above_wk_vwap(inputs, config):
    """Replay of FeatureCache's weekly VWAP exactly as compute_batch drives it.

    compute_batch reads the flag before it advances the cache with the same bar, and never
    advances for row 0, so the value at row i reflects bars 1..i-1 and row 0 holds the cache's
    initial 0.0. One implementation of the weekly VWAP math.
    """
    n = len(inputs["ts_dt"])
    dts = inputs["ts_dt"]
    cache = FeatureCache()
    out = np.empty(n)
    for i in range(n):
        out[i] = cache.above_wk_vwap
        if i >= 1:
            cache.advance_bar(
                dts[i],
                float(inputs["high"][i]),
                float(inputs["low"][i]),
                float(inputs["close"][i]),
                float(inputs["volume"][i]),
            )
    return {"above_wk_vwap": out}


KERNELS = (
    Kernel(
        name="calendar_session",
        outputs=_SESSION_OUTPUTS,
        inputs=("ts_dt",),
        memory=lambda config: 0,
        compute=_compute_session,
    ),
    Kernel(
        name="calendar_cycles",
        outputs=_CYCLE_OUTPUTS,
        inputs=("ts_dt",),
        memory=lambda config: 0,
        compute=_compute_cycles,
    ),
    Kernel(
        name="calendar_events",
        outputs=_EVENT_OUTPUTS,
        inputs=("ts_dt",),
        memory=lambda config: 0,
        compute=_compute_events,
    ),
    Kernel(
        name="calendar_above_wk_vwap",
        outputs=("above_wk_vwap",),
        inputs=("ts_dt", "high", "low", "close", "volume"),
        memory=lambda config: 0,
        compute=_compute_above_wk_vwap,
        path_dependent=True,
        path_dependent_reason=(
            "weekly accumulator state and row-0 exclusion depend on the series start; the weekly "
            "reset bounds it in calendar time, but the bound in bars depends on tf, which a "
            "kernel does not receive"
        ),
    ),
)
