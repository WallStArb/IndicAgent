from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from src.intelligence.plugins import InputSpec

_SESSION_BARS = 390  # ~1 trading day on 1m
_WEEK_BARS = 1950  # ~5 trading days on 1m
_OVERNIGHT_BARS = 60  # ~1 hour on 1m
_ET_TZ = ZoneInfo("America/New_York")  # DST-aware; replaces fixed UTC-5 offset


@dataclass
class SessionLevelsPlugin:
    """Session and weekly pivot levels derived from bar-count windows."""

    name: str = "struct_SessionLevels"
    outputs: frozenset[str] = frozenset(
        {
            "prior_session_high",
            "prior_session_low",
            "prior_session_close",
            "overnight_high",
            "overnight_low",
            "overnight_range_pct",
            "opening_gap_pct",
            "weekly_pivot",
            "weekly_r1",
            "weekly_r2",
            "weekly_s1",
            "weekly_s2",
            "nearest_session_level",
            "nearest_level_dist_atr",
            "asian_session_high",
            "asian_session_low",
        }
    )
    min_lookback: int = 20
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"structure"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe="1m", lookback=520),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        features = frames.get("features") or {}
        close = float(features.get("close") or df["close"].iloc[-1])
        atr_14 = features.get("atr_14")
        n = len(df)

        # Session window: most recent ~1 trading day
        sess_n = min(_SESSION_BARS, n)
        session = df.iloc[-sess_n:]

        # Prior session: the block before current session
        prior_end = n - sess_n
        prior_n = min(_SESSION_BARS, prior_end)
        prior = df.iloc[prior_end - prior_n : prior_end] if prior_n > 0 else None

        # Overnight: last OVERNIGHT_BARS or fraction of session
        overnight_n = min(_OVERNIGHT_BARS, sess_n // 4)
        overnight = df.iloc[-overnight_n:] if overnight_n > 0 else None

        result: dict[str, Any] = {}

        if prior is not None and len(prior) > 0:
            result["prior_session_high"] = float(prior["high"].max())
            result["prior_session_low"] = float(prior["low"].min())
            result["prior_session_close"] = float(prior["close"].iloc[-1])
        else:
            result["prior_session_high"] = None
            result["prior_session_low"] = None
            result["prior_session_close"] = None

        if overnight is not None and len(overnight) > 0:
            on_high = float(overnight["high"].max())
            on_low = float(overnight["low"].min())
            on_range = on_high - on_low
            result["overnight_high"] = on_high
            result["overnight_low"] = on_low
            result["overnight_range_pct"] = on_range / on_low if on_low != 0 else 0.0
        else:
            result["overnight_high"] = None
            result["overnight_low"] = None
            result["overnight_range_pct"] = None

        psc = result["prior_session_close"]
        if psc is not None:
            today_open = float(session["open"].iloc[0])
            result["opening_gap_pct"] = (today_open - psc) / psc if psc != 0 else 0.0
        else:
            result["opening_gap_pct"] = None

        # Weekly pivot: bars from sess_n to WEEK_BARS ago (prior week proxy)
        week_end = n - sess_n
        week_start = max(0, n - _WEEK_BARS)
        week_df = df.iloc[week_start:week_end] if week_end > week_start else None

        # Fallback to prior session when weekly history unavailable
        if week_df is None or len(week_df) < 5:
            week_df = prior

        if week_df is not None and len(week_df) > 0:
            wh = float(week_df["high"].max())
            wl = float(week_df["low"].min())
            wc = float(week_df["close"].iloc[-1])
            wp = (wh + wl + wc) / 3.0
            wr = wh - wl
            result["weekly_pivot"] = wp
            result["weekly_r1"] = 2.0 * wp - wl
            result["weekly_r2"] = wp + wr
            result["weekly_s1"] = 2.0 * wp - wh
            result["weekly_s2"] = wp - wr
        else:
            result["weekly_pivot"] = None
            result["weekly_r1"] = None
            result["weekly_r2"] = None
            result["weekly_s1"] = None
            result["weekly_s2"] = None

        levels = [
            v
            for v in [
                result.get("prior_session_high"),
                result.get("prior_session_low"),
                result.get("weekly_pivot"),
                result.get("weekly_r1"),
                result.get("weekly_r2"),
                result.get("weekly_s1"),
                result.get("weekly_s2"),
            ]
            if v is not None
        ]

        if levels:
            nearest = min(levels, key=lambda x: abs(x - close))
            result["nearest_session_level"] = nearest
            result["nearest_level_dist_atr"] = (
                abs(close - nearest) / float(atr_14)
                if isinstance(atr_14, (int, float)) and atr_14 > 0
                else None
            )
        else:
            result["nearest_session_level"] = None
            result["nearest_level_dist_atr"] = None

        # Asian session H/L — vectorized: DST-aware ET, 20:00–04:00 ET wraps midnight
        if "timestamp" in df.columns and len(df) > 0:
            ts_utc = pd.to_datetime(df["timestamp"], utc=True)
            et_hours = ts_utc.dt.tz_convert(_ET_TZ).dt.hour
            asia_mask = (et_hours >= 20) | (et_hours < 4)
            asia_bars = df[asia_mask]
            if len(asia_bars) > 0:
                result["asian_session_high"] = float(asia_bars["high"].max())
                result["asian_session_low"] = float(asia_bars["low"].min())
            else:
                result["asian_session_high"] = None
                result["asian_session_low"] = None
        else:
            result["asian_session_high"] = None
            result["asian_session_low"] = None

        return result

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = SessionLevelsPlugin()
