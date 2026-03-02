"""smc_ICTKillzones — ICT killzone detection.

Identifies high-probability trading windows based on ICT (Inner Circle Trader)
session killzone theory. Killzones are specific UTC time windows within which
institutional order flow is most active.

Killzone windows (UTC, fixed offset — UTC-5 = ET):
  Asia:    08:00–10:00 UTC  (3am–5am ET)
  London:  07:00–10:00 UTC  (2am–5am ET)
  NY AM:   13:30–16:00 UTC  (8:30am–11am ET)
  NY PM:   18:00–20:00 UTC  (1pm–3pm ET)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ..plugins import InputSpec

def _minutes_since_midnight_utc(dt: datetime) -> int:
    return dt.hour * 60 + dt.minute


# Module-level constants — computed once, reused every bar
_KZ_MAP: dict[str, tuple[int, int]] = {
    "asia":   (8 * 60,        10 * 60),
    "london": (7 * 60,        10 * 60),
    "ny_am":  (13 * 60 + 30,  16 * 60),
    "ny_pm":  (18 * 60,       20 * 60),
}
_KZ_STARTS: tuple[int, ...] = tuple(sorted(v[0] for v in _KZ_MAP.values()))


@dataclass
class ICTKillzonesPlugin:
    """Detect which ICT killzone the current bar falls within."""

    name: str = "smc_ICTKillzones"
    outputs: frozenset[str] = frozenset({
        "in_asia_killzone",
        "in_london_killzone",
        "in_ny_am_killzone",
        "in_ny_pm_killzone",
        "killzone_name",
        "minutes_in_killzone",
        "minutes_until_next_killzone",
    })
    min_lookback: int = 1
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"smart_money", "session"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe="1m", lookback=5),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        # Extract timestamp from bar or fall back to now
        ts: datetime | None = None
        last_row = df.iloc[-1]
        if "timestamp" in df.columns:
            raw = last_row["timestamp"]
            if isinstance(raw, datetime):
                ts = raw if raw.tzinfo else raw.replace(tzinfo=UTC)
            else:
                try:
                    import pandas as pd
                    ts_pd = pd.Timestamp(raw)
                    ts = ts_pd.to_pydatetime()
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=UTC)
                    else:
                        ts = ts.astimezone(UTC)
                except Exception:
                    ts = None

        if ts is None:
            ts = datetime.now(tz=UTC)

        cur_min = _minutes_since_midnight_utc(ts)
        total_day_minutes = 24 * 60

        in_asia = 0.0
        in_london = 0.0
        in_ny_am = 0.0
        in_ny_pm = 0.0
        active_name: str | None = None
        minutes_in: float = 0.0

        kz_map = {
            "asia": (8 * 60, 10 * 60),
            "london": (7 * 60, 10 * 60),
            "ny_am": (13 * 60 + 30, 16 * 60),
            "ny_pm": (18 * 60, 20 * 60),
        }

        earliest_start: int | None = None
        for kz_name, (start, end) in kz_map.items():
            if start <= cur_min < end:
                if kz_name == "asia":
                    in_asia = 1.0
                elif kz_name == "london":
                    in_london = 1.0
                elif kz_name == "ny_am":
                    in_ny_am = 1.0
                elif kz_name == "ny_pm":
                    in_ny_pm = 1.0
                # Primary zone = earliest-starting active zone
                if earliest_start is None or start < earliest_start:
                    earliest_start = start
                    active_name = kz_name
                    minutes_in = float(cur_min - start)

        # Minutes until next killzone start
        starts = sorted(kz_map[k][0] for k in kz_map)
        minutes_until: float = float(min(
            (s - cur_min) % total_day_minutes for s in starts
        ))

        return {
            "in_asia_killzone": in_asia,
            "in_london_killzone": in_london,
            "in_ny_am_killzone": in_ny_am,
            "in_ny_pm_killzone": in_ny_pm,
            "killzone_name": active_name,
            "minutes_in_killzone": minutes_in,
            "minutes_until_next_killzone": minutes_until,
        }

plugin = ICTKillzonesPlugin()
