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
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"structure"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=520),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
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

        # Asian session H/L — vectorized: DST-aware ET, 20:00-04:00 ET wraps midnight
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

        # Seed incremental state from full computation
        if state is not None:
            state["bar_count"] = n
            state["sess_n"] = sess_n
            # Session tracking: track bar index of session start
            state["session_start_idx"] = n - sess_n
            # Store prior session levels (finalized; won't change until next boundary)
            state["prior_session_high"] = result.get("prior_session_high")
            state["prior_session_low"] = result.get("prior_session_low")
            state["prior_session_close"] = result.get("prior_session_close")
            # Current session running high/low (from session slice)
            state["session_high"] = float(session["high"].max()) if len(session) > 0 else None
            state["session_low"] = float(session["low"].min()) if len(session) > 0 else None
            state["session_open"] = float(session["open"].iloc[0]) if len(session) > 0 else None
            # Weekly pivot levels (updated only when weekly data changes significantly)
            state["weekly_pivot"] = result.get("weekly_pivot")
            state["weekly_r1"] = result.get("weekly_r1")
            state["weekly_r2"] = result.get("weekly_r2")
            state["weekly_s1"] = result.get("weekly_s1")
            state["weekly_s2"] = result.get("weekly_s2")
            state["weekly_high"] = (
                float(week_df["high"].max()) if week_df is not None and len(week_df) > 0 else None
            )
            state["weekly_low"] = (
                float(week_df["low"].min()) if week_df is not None and len(week_df) > 0 else None
            )
            state["weekly_close"] = (
                float(week_df["close"].iloc[-1])
                if week_df is not None and len(week_df) > 0
                else None
            )
            # Overnight state: track the last OVERNIGHT_BARS segment
            state["overnight_n"] = overnight_n
            state["overnight_high"] = result.get("overnight_high")
            state["overnight_low"] = result.get("overnight_low")
            # Asian session state
            state["asian_session_high"] = result.get("asian_session_high")
            state["asian_session_low"] = result.get("asian_session_low")

        return result

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        """Incremental session level update.

        Session boundary detection: the "session" is the last _SESSION_BARS bars.
        When bar_count mod _SESSION_BARS crosses a boundary (new session), we:
        1. Roll current session -> prior session (high/low/close finalized).
        2. Reset current session state from the new bar.
        3. Recompute weekly pivots from the now-prior-session data.

        All other fields (overnight, asian session) are approximated from
        running state maintained per-bar.

        Falls back to compute_full when state is None or empty.

        State keys:
            bar_count (int): total bars processed; tracks session boundary.
            session_start_idx (int): df index where current session began.
            session_high (float | None): current session running high.
            session_low (float | None): current session running low.
            session_open (float | None): first bar open of current session.
            prior_session_high (float | None): previous session high.
            prior_session_low (float | None): previous session low.
            prior_session_close (float | None): last bar close of previous session.
            overnight_high (float | None): high over last overnight_n bars.
            overnight_low (float | None): low over last overnight_n bars.
            overnight_n (int): number of overnight bars (derived once, then cached).
            asian_session_high (float | None): high over Asian-hour bars.
            asian_session_low (float | None): low over Asian-hour bars.
            weekly_pivot / weekly_r1 / weekly_r2 / weekly_s1 / weekly_s2 (float | None).
            weekly_high / weekly_low / weekly_close (float | None).
        """
        if state is None or not state:
            return self.compute_full(windows, state=state)

        df = windows.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        features = windows.get("features") or {}
        close = float(features.get("close") or df["close"].iloc[-1])
        atr_14 = features.get("atr_14")
        n = len(df)

        bar = df.iloc[-1]
        bar_high = float(bar["high"])
        bar_low = float(bar["low"])
        bar_close = float(bar["close"])
        bar_open = float(bar["open"])

        prev_bar_count = state.get("bar_count", n - 1)
        prev_session_start = state.get("session_start_idx", max(0, n - _SESSION_BARS))

        # Detect session boundary: a new session starts when we've accumulated
        # _SESSION_BARS bars since the last session start
        current_session_length = n - prev_session_start
        new_session = current_session_length > _SESSION_BARS

        if new_session:
            # Roll: current session becomes prior session
            state["prior_session_high"] = state.get("session_high")
            state["prior_session_low"] = state.get("session_low")
            state["prior_session_close"] = bar_close  # last bar of old session
            # Reset current session
            state["session_start_idx"] = n - 1
            state["session_high"] = bar_high
            state["session_low"] = bar_low
            state["session_open"] = bar_open
            # Update weekly data from the now-prior session
            psh = state.get("prior_session_high")
            psl = state.get("prior_session_low")
            psc_val = state.get("prior_session_close")
            if psh is not None and psl is not None and psc_val is not None:
                wh = max(psh, state.get("weekly_high") or psh)
                wl = min(psl, state.get("weekly_low") or psl)
                wc = psc_val
                wp = (wh + wl + wc) / 3.0
                wr = wh - wl
                state["weekly_pivot"] = wp
                state["weekly_r1"] = 2.0 * wp - wl
                state["weekly_r2"] = wp + wr
                state["weekly_s1"] = 2.0 * wp - wh
                state["weekly_s2"] = wp - wr
                state["weekly_high"] = wh
                state["weekly_low"] = wl
                state["weekly_close"] = wc
        else:
            # Update running session high/low
            prev_sh = state.get("session_high")
            prev_sl = state.get("session_low")
            state["session_high"] = max(prev_sh, bar_high) if prev_sh is not None else bar_high
            state["session_low"] = min(prev_sl, bar_low) if prev_sl is not None else bar_low

        state["bar_count"] = n

        # Overnight: approximate as last overnight_n bars
        overnight_n = state.get("overnight_n", min(_OVERNIGHT_BARS, _SESSION_BARS // 4))
        if n >= overnight_n:
            on_slice = df.iloc[-overnight_n:]
            on_high = float(on_slice["high"].max())
            on_low = float(on_slice["low"].min())
            state["overnight_high"] = on_high
            state["overnight_low"] = on_low

        # Asian session: recompute from df if timestamp column available
        # (fast path: only update if timestamp present, else keep last state value)
        if "timestamp" in df.columns and len(df) > 0:
            ts_utc = pd.to_datetime(df["timestamp"], utc=True)
            et_hours = ts_utc.dt.tz_convert(_ET_TZ).dt.hour
            asia_mask = (et_hours >= 20) | (et_hours < 4)
            asia_bars = df[asia_mask]
            if len(asia_bars) > 0:
                state["asian_session_high"] = float(asia_bars["high"].max())
                state["asian_session_low"] = float(asia_bars["low"].min())
            else:
                state["asian_session_high"] = None
                state["asian_session_low"] = None

        # Build result from state
        result: dict[str, Any] = {
            "prior_session_high": state.get("prior_session_high"),
            "prior_session_low": state.get("prior_session_low"),
            "prior_session_close": state.get("prior_session_close"),
        }

        on_high = state.get("overnight_high")
        on_low = state.get("overnight_low")
        result["overnight_high"] = on_high
        result["overnight_low"] = on_low
        if on_high is not None and on_low is not None and on_low != 0:
            result["overnight_range_pct"] = (on_high - on_low) / on_low
        else:
            result["overnight_range_pct"] = None

        psc = result["prior_session_close"]
        session_open = state.get("session_open")
        if psc is not None and session_open is not None:
            result["opening_gap_pct"] = (session_open - psc) / psc if psc != 0 else 0.0
        else:
            result["opening_gap_pct"] = None

        result["weekly_pivot"] = state.get("weekly_pivot")
        result["weekly_r1"] = state.get("weekly_r1")
        result["weekly_r2"] = state.get("weekly_r2")
        result["weekly_s1"] = state.get("weekly_s1")
        result["weekly_s2"] = state.get("weekly_s2")
        result["asian_session_high"] = state.get("asian_session_high")
        result["asian_session_low"] = state.get("asian_session_low")

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

        return result


plugin = SessionLevelsPlugin()
