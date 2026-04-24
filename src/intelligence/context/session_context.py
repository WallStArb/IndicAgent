from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from src.core.models import (
    CONTINUOUS_SESSIONS,
    EXCHANGE_SESSIONS,
    MARKET_OVERLAPS,
    SESSION_REGISTRY,
    TradingSession,
)

from ..plugins import InputSpec
from ..utils.gradient_utils import linear_ramp, session_progress, threshold_decay

# --- Legacy ET session windows (local wall-clock, preserved for backward compat) ---

_ET_TZ = ZoneInfo("America/New_York")  # replaces hardcoded _ET_OFFSET = timedelta(hours=-5)

_SESSIONS = {
    "asia": ((20, 0), (4, 0)),  # wraps midnight in ET
    "london": ((3, 0), (12, 0)),
    "ny": ((9, 30), (16, 0)),
    "overlap": ((8, 0), (12, 0)),  # London/NY overlap (legacy range, preserved)
}

_KILLZONES = {
    "london_kz": ((2, 0), (5, 0)),
    "ny_kz": ((7, 0), (10, 0)),
}


def _et_from_utc(ts: datetime) -> datetime:
    return ts.astimezone(_ET_TZ)


def _time_to_frac(et_dt: datetime) -> float:
    """Convert ET hour:minute to fraction of 24h [0, 1)."""
    return (et_dt.hour * 60 + et_dt.minute) / 1440.0


def _window_to_frac(start: tuple[int, int], end: tuple[int, int]) -> tuple[float, float]:
    """Convert (hour, minute) window to fractional 24h bounds."""
    return (start[0] * 60 + start[1]) / 1440.0, (end[0] * 60 + end[1]) / 1440.0


def _in_window(et_dt: datetime, start: tuple[int, int], end: tuple[int, int]) -> bool:
    t = (et_dt.hour, et_dt.minute)
    if start <= end:
        return start <= t < end
    return t >= start or t < end


def _window_progress(et_dt: datetime, start: tuple[int, int], end: tuple[int, int]) -> float:
    """Continuous progress fraction through a session window.

    Handles midnight-wrapping windows (e.g. Asia 20:00-04:00 ET) by normalising
    the current time into the window's fractional range.
    Returns 0.0 outside the window. Inside the window, returns a value in [0.2, 1.0]
    that peaks at the midpoint and has a floor of 0.2 at the edges.
    This preserves the "session is active" signal while providing gradient depth.
    """
    current_frac = _time_to_frac(et_dt)
    start_frac, end_frac = _window_to_frac(start, end)

    _SESSION_FLOOR = 0.2  # minimum when inside window

    # Midnight-wrapping window (e.g. Asia 20:00-04:00)
    if start_frac > end_frac:
        if current_frac >= start_frac:
            # Inside first part of wrapping window
            span = (end_frac + 1.0) - start_frac
            if span <= 0:
                return 0.0
            position = (current_frac - start_frac) / span
            peak = max(0.0, 1.0 - abs(2.0 * position - 1.0))
            return _SESSION_FLOOR + (1.0 - _SESSION_FLOOR) * peak
        elif current_frac < end_frac:
            # Inside second part of wrapping window
            span = (end_frac + 1.0) - start_frac
            if span <= 0:
                return 0.0
            position = (current_frac + 1.0 - start_frac) / span
            peak = max(0.0, 1.0 - abs(2.0 * position - 1.0))
            return _SESSION_FLOOR + (1.0 - _SESSION_FLOOR) * peak
        else:
            return 0.0

    span = end_frac - start_frac
    if span <= 0:
        return 0.0
    if current_frac < start_frac or current_frac > end_frac:
        return 0.0
    position = (current_frac - start_frac) / span
    peak = max(0.0, 1.0 - abs(2.0 * position - 1.0))
    return _SESSION_FLOOR + (1.0 - _SESSION_FLOOR) * peak


def _minutes_until(et_dt: datetime, target_hour: int, target_min: int) -> float:
    target = et_dt.replace(hour=target_hour, minute=target_min, second=0, microsecond=0)
    if target <= et_dt:
        target = target + timedelta(days=1)
    return (target - et_dt).total_seconds() / 60.0


def _extract_ts(df: Any) -> datetime | None:
    if df is None or len(df) == 0:
        return None
    if "timestamp" in df.columns:
        val = df["timestamp"].iloc[-1]
        if hasattr(val, "to_pydatetime"):
            return val.to_pydatetime()
        if isinstance(val, datetime):
            return val if val.tzinfo else val.replace(tzinfo=UTC)
    return None


@dataclass
class SessionContextPlugin:
    """Time-of-day session context — global exchanges, DST-correct, 27 outputs."""

    name: str = "ctx_SessionContext"
    outputs: frozenset[str] = frozenset(
        {
            # --- Legacy 12 outputs (preserved) ---
            "session_asia",
            "session_london",
            "session_ny",
            "session_london_ny_overlap",
            "session_after_hours",
            "in_london_killzone",
            "in_ny_killzone",
            "minutes_to_ny_open",
            "minutes_to_london_open",
            "bars_since_session_start",
            "is_monday",
            "is_friday",
            # --- Exchange active flags (6) ---
            "session_nyse_active",
            "session_lse_active",
            "session_tse_active",
            "session_hkex_active",
            "session_sse_active",
            "session_asx_active",
            # --- Trading break flags (3) ---
            "session_tse_in_break",
            "session_hkex_in_break",
            "session_sse_in_break",
            # --- Market overlap flags (2) ---
            "session_tokyo_london_overlap",
            "session_ny_sydney_overlap",
            # --- Instrument sub-session (4) ---
            "session_elapsed_frac",
            "is_opening_range",
            "is_lunch_consolidation",
            "is_power_hour",
        }
    )
    min_lookback: int = 1
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"context"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe="1m", lookback=10),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None:
            return {}

        ts = _extract_ts(df)
        if ts is None:
            return {k: 0.0 for k in self.outputs}

        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)

        et = _et_from_utc(ts)

        # --- Legacy outputs — now continuous gradient (bell-shaped via session_progress) ---
        sess_asia = _window_progress(et, *_SESSIONS["asia"])
        sess_london = _window_progress(et, *_SESSIONS["london"])
        sess_ny = _window_progress(et, *_SESSIONS["ny"])
        sess_after = 1.0 - min(1.0, sess_asia + sess_london + sess_ny)

        in_london_kz = _window_progress(et, *_KILLZONES["london_kz"])
        in_ny_kz = _window_progress(et, *_KILLZONES["ny_kz"])

        mins_to_ny = _minutes_until(et, 9, 30)
        mins_to_london = _minutes_until(et, 3, 0)
        bars_since = float(len(df))

        # --- Exchange active flags — gradient progress through session window ---
        exchange_flags: dict[str, float] = {}
        break_flags: dict[str, float] = {}
        for ex_id, session in EXCHANGE_SESSIONS.items():
            if session.is_open(ts):
                # Compute progress fraction through the exchange session
                open_frac = session.elapsed_fraction(ts)
                if open_frac is not None and 0.0 < open_frac < 1.0:
                    # Bell-shaped: peak at midpoint of session
                    exchange_flags[f"session_{ex_id}_active"] = max(
                        0.0, 1.0 - abs(2.0 * open_frac - 1.0)
                    )
                else:
                    exchange_flags[f"session_{ex_id}_active"] = 1.0
            else:
                exchange_flags[f"session_{ex_id}_active"] = 0.0
            if session.trading_breaks:
                # Progress through break: use elapsed_fraction if in break
                if session.in_trading_break(ts):
                    # Approximate midpoint of break for gradient
                    break_frac = session.elapsed_fraction(ts)
                    if break_frac is not None:
                        break_flags[f"session_{ex_id}_in_break"] = max(
                            0.0, 1.0 - abs(2.0 * break_frac - 1.0)
                        )
                    else:
                        break_flags[f"session_{ex_id}_in_break"] = 1.0
                else:
                    break_flags[f"session_{ex_id}_in_break"] = 0.0

        # --- Market overlap flags — overlap intensity from min of both exchange progresses ---
        overlap_flags: dict[str, float] = {}
        for overlap_name, (ex_a, ex_b) in MARKET_OVERLAPS.items():
            sess_a = SESSION_REGISTRY.get(ex_a)
            sess_b = SESSION_REGISTRY.get(ex_b)
            if sess_a and sess_b and sess_a.is_open(ts) and sess_b.is_open(ts):
                frac_a = sess_a.elapsed_fraction(ts)
                frac_b = sess_b.elapsed_fraction(ts)
                if frac_a is not None and frac_b is not None:
                    # Overlap intensity = minimum of both session progresses (bell-shaped)
                    prog_a = max(0.0, 1.0 - abs(2.0 * frac_a - 1.0))
                    prog_b = max(0.0, 1.0 - abs(2.0 * frac_b - 1.0))
                    overlap_flags[f"session_{overlap_name}_overlap"] = min(prog_a, prog_b)
                else:
                    overlap_flags[f"session_{overlap_name}_overlap"] = 1.0
            else:
                overlap_flags[f"session_{overlap_name}_overlap"] = 0.0

        # --- Instrument sub-session (requires __instrument__ in frames) ---
        instrument = frames.get("__instrument__")
        sub_session = self._compute_sub_session(ts, instrument)

        return {
            # Legacy 12
            "session_asia": sess_asia,
            "session_london": sess_london,
            "session_ny": sess_ny,
            # Source london_ny_overlap from MARKET_OVERLAPS (spec requirement)
            "session_london_ny_overlap": overlap_flags.get("session_london_ny_overlap", 0.0),
            "session_after_hours": sess_after,
            "in_london_killzone": in_london_kz,
            "in_ny_killzone": in_ny_kz,
            "minutes_to_ny_open": mins_to_ny,
            "minutes_to_london_open": mins_to_london,
            "bars_since_session_start": bars_since,
            "is_monday": 1.0 if et.weekday() == 0 else 0.0,
            "is_friday": 1.0 if et.weekday() == 4 else 0.0,
            # Exchange flags
            **exchange_flags,
            # Break flags
            **break_flags,
            # Overlap flags — all 3; london_ny also in legacy 12 above (last write wins)
            **overlap_flags,
            # Sub-session
            **sub_session,
        }

    def _compute_sub_session(self, ts: datetime, instrument: Any) -> dict[str, float]:
        """Instrument-aware sub-session features. Defaults to 0.0 when no instrument."""
        defaults: dict[str, float] = {
            "session_elapsed_frac": 0.0,
            "is_opening_range": 0.0,
            "is_lunch_consolidation": 0.0,
            "is_power_hour": 0.0,
        }
        if instrument is None:
            return defaults

        # Continuous sessions (futures, FX, crypto) have no meaningful sub-session structure
        if instrument.session_id in CONTINUOUS_SESSIONS:
            return defaults

        session: TradingSession = instrument.trading_session
        if session is None:
            return defaults
        elapsed = session.elapsed_fraction(ts)

        if elapsed is None:
            return defaults  # all-day session

        # NOTE: 390 is NYSE session minutes (6.5h). elapsed_fraction() normalises
        # by the instrument's actual session length, so these thresholds approximate
        # "first 30 min" and "last 60 min" for NYSE sessions.
        # Gradient: linear decay from 1.0 at session start to 0.0 at threshold
        opening_threshold = 30.0 / 390.0  # ~0.077
        is_opening = max(0.0, 1.0 - elapsed / opening_threshold) if elapsed < opening_threshold else 0.0

        # Gradient: linear ramp from 0.0 at power_hour_start to 1.0 at session end
        power_start = 330.0 / 390.0  # ~0.846
        is_power = linear_ramp(elapsed, power_start, 1.0)

        if session.trading_breaks:
            # Gradient through break: use elapsed_fraction if in break
            if session.in_trading_break(ts):
                break_frac = session.elapsed_fraction(ts)
                if break_frac is not None:
                    # Bell-shaped: peak at midpoint of break period
                    is_lunch = max(0.0, 1.0 - abs(2.0 * break_frac - 1.0))
                else:
                    is_lunch = 1.0
            else:
                is_lunch = 0.0
        else:
            # Proximity to lunch peak (~0.475 session elapsed) with width 0.15
            is_lunch = threshold_decay(elapsed, 0.475, 0.15)

        return {
            "session_elapsed_frac": elapsed,
            "is_opening_range": is_opening,
            "is_lunch_consolidation": is_lunch,
            "is_power_hour": is_power,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = SessionContextPlugin()
