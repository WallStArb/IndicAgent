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

# --- Legacy ET session windows (local wall-clock, preserved for backward compat) ---

_ET_TZ = ZoneInfo("America/New_York")  # replaces hardcoded _ET_OFFSET = timedelta(hours=-5)

_SESSIONS = {
    "asia":    ((20, 0), (4, 0)),   # wraps midnight in ET
    "london":  ((3, 0),  (12, 0)),
    "ny":      ((9, 30), (16, 0)),
    "overlap": ((8, 0),  (12, 0)),  # London/NY overlap (legacy range, preserved)
}

_KILLZONES = {
    "london_kz": ((2, 0), (5, 0)),
    "ny_kz":     ((7, 0), (10, 0)),
}


def _et_from_utc(ts: datetime) -> datetime:
    return ts.astimezone(_ET_TZ)


def _in_window(et_dt: datetime, start: tuple[int, int], end: tuple[int, int]) -> bool:
    t = (et_dt.hour, et_dt.minute)
    if start <= end:
        return start <= t < end
    return t >= start or t < end


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

        # --- Legacy outputs (backward compat) ---
        sess_asia    = 1.0 if _in_window(et, *_SESSIONS["asia"])    else 0.0
        sess_london  = 1.0 if _in_window(et, *_SESSIONS["london"])  else 0.0
        sess_ny      = 1.0 if _in_window(et, *_SESSIONS["ny"])      else 0.0
        sess_after   = 0.0 if (sess_asia or sess_london or sess_ny)  else 1.0

        in_london_kz = 1.0 if _in_window(et, *_KILLZONES["london_kz"]) else 0.0
        in_ny_kz     = 1.0 if _in_window(et, *_KILLZONES["ny_kz"])     else 0.0

        mins_to_ny     = _minutes_until(et, 9, 30)
        mins_to_london = _minutes_until(et, 3, 0)
        bars_since     = float(len(df))

        # --- Exchange active flags (data-driven from EXCHANGE_SESSIONS) ---
        exchange_flags: dict[str, float] = {}
        break_flags: dict[str, float] = {}
        for ex_id, session in EXCHANGE_SESSIONS.items():
            exchange_flags[f"session_{ex_id}_active"] = 1.0 if session.is_open(ts) else 0.0
            if session.trading_breaks:
                break_flags[f"session_{ex_id}_in_break"] = (
                    1.0 if session.in_trading_break(ts) else 0.0
                )

        # --- Market overlap flags (data-driven from MARKET_OVERLAPS) ---
        overlap_flags: dict[str, float] = {}
        for overlap_name, (ex_a, ex_b) in MARKET_OVERLAPS.items():
            sess_a = SESSION_REGISTRY.get(ex_a)
            sess_b = SESSION_REGISTRY.get(ex_b)
            both_open = bool(sess_a and sess_b and sess_a.is_open(ts) and sess_b.is_open(ts))
            overlap_flags[f"session_{overlap_name}_overlap"] = 1.0 if both_open else 0.0

        # --- Instrument sub-session (requires __instrument__ in frames) ---
        instrument = frames.get("__instrument__")
        sub_session = self._compute_sub_session(ts, instrument)

        return {
            # Legacy 12
            "session_asia":             sess_asia,
            "session_london":           sess_london,
            "session_ny":               sess_ny,
            # Source london_ny_overlap from MARKET_OVERLAPS (spec requirement)
            "session_london_ny_overlap": overlap_flags.get("session_london_ny_overlap", 0.0),
            "session_after_hours":      sess_after,
            "in_london_killzone":       in_london_kz,
            "in_ny_killzone":           in_ny_kz,
            "minutes_to_ny_open":       mins_to_ny,
            "minutes_to_london_open":   mins_to_london,
            "bars_since_session_start": bars_since,
            "is_monday":                1.0 if et.weekday() == 0 else 0.0,
            "is_friday":                1.0 if et.weekday() == 4 else 0.0,
            # Exchange flags
            **exchange_flags,
            # Break flags
            **break_flags,
            # Overlap flags — all 3; london_ny also in legacy 12 above (last write wins)
            **overlap_flags,
            # Sub-session
            **sub_session,
        }

    def _compute_sub_session(
        self, ts: datetime, instrument: Any
    ) -> dict[str, float]:
        """Instrument-aware sub-session features. Defaults to 0.0 when no instrument."""
        defaults: dict[str, float] = {
            "session_elapsed_frac": 0.0,
            "is_opening_range":     0.0,
            "is_lunch_consolidation": 0.0,
            "is_power_hour":        0.0,
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
        is_opening  = 1.0 if elapsed < (30.0 / 390.0) else 0.0
        is_power    = 1.0 if elapsed > (330.0 / 390.0) else 0.0

        if session.trading_breaks:
            is_lunch = 1.0 if session.in_trading_break(ts) else 0.0
        else:
            is_lunch = 1.0 if 0.30 <= elapsed <= 0.65 else 0.0

        return {
            "session_elapsed_frac":   elapsed,
            "is_opening_range":       is_opening,
            "is_lunch_consolidation": is_lunch,
            "is_power_hour":          is_power,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = SessionContextPlugin()
