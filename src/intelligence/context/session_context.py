from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from ..plugins import InputSpec

# Eastern Time offset (UTC-5; no auto-DST adjustment for simplicity)
_ET_OFFSET = timedelta(hours=-5)

# Session windows in ET (hour, minute) inclusive ranges
_SESSIONS = {
    "asia":     ((20, 0), (4, 0)),   # wraps midnight
    "london":   ((3, 0),  (12, 0)),
    "ny":       ((9, 30), (16, 0)),
    "overlap":  ((8, 0),  (12, 0)),  # London/NY overlap
}
# Killzone windows in ET
_KILLZONES = {
    "london_kz": ((2, 0), (5, 0)),
    "ny_kz":     ((7, 0), (10, 0)),
}


def _et_from_utc(ts: datetime) -> datetime:
    return ts.astimezone(timezone(offset=_ET_OFFSET))


def _in_window(et_dt: datetime, start: tuple[int, int], end: tuple[int, int]) -> bool:
    """Return True if et_dt is in [start, end) window, handling midnight wrap."""
    t = (et_dt.hour, et_dt.minute)
    if start <= end:
        return start <= t < end
    # Wraps midnight: Asia 20:00–04:00 means t >= 20:00 OR t < 04:00
    return t >= start or t < end


def _minutes_until(et_dt: datetime, target_hour: int, target_min: int) -> float:
    target = et_dt.replace(hour=target_hour, minute=target_min, second=0, microsecond=0)
    if target <= et_dt:
        target = target + timedelta(days=1)
    return (target - et_dt).total_seconds() / 60.0


def _extract_ts(df: Any) -> datetime | None:
    """Pull last-row timestamp from a DataFrame if available."""
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
    """Time-of-day session context — Asia / London / NY / killzones."""

    name: str = "ctx_SessionContext"
    outputs: frozenset[str] = frozenset(
        {
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
            # No timestamp available — return neutral flags
            return {k: 0.0 for k in self.outputs}

        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)

        et = _et_from_utc(ts)

        sess_asia = 1.0 if _in_window(et, *_SESSIONS["asia"]) else 0.0
        sess_london = 1.0 if _in_window(et, *_SESSIONS["london"]) else 0.0
        sess_ny = 1.0 if _in_window(et, *_SESSIONS["ny"]) else 0.0
        sess_overlap = 1.0 if _in_window(et, *_SESSIONS["overlap"]) else 0.0
        sess_after = 0.0 if (sess_asia or sess_london or sess_ny) else 1.0

        in_london_kz = 1.0 if _in_window(et, *_KILLZONES["london_kz"]) else 0.0
        in_ny_kz = 1.0 if _in_window(et, *_KILLZONES["ny_kz"]) else 0.0

        mins_to_ny = _minutes_until(et, 9, 30)
        mins_to_london = _minutes_until(et, 3, 0)

        # Bars in lookback window (rough proxy for session length)
        bars_since = float(len(df))

        return {
            "session_asia": sess_asia,
            "session_london": sess_london,
            "session_ny": sess_ny,
            "session_london_ny_overlap": sess_overlap,
            "session_after_hours": sess_after,
            "in_london_killzone": in_london_kz,
            "in_ny_killzone": in_ny_kz,
            "minutes_to_ny_open": mins_to_ny,
            "minutes_to_london_open": mins_to_london,
            "bars_since_session_start": bars_since,
            "is_monday": 1.0 if et.weekday() == 0 else 0.0,
            "is_friday": 1.0 if et.weekday() == 4 else 0.0,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = SessionContextPlugin()
