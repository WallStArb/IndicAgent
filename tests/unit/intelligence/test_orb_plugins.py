"""Unit tests for ORB15 and ORB30 plugins with synthetic RTH opening range bars.

Tests verify CORRECT-RARE verdict: gate logic is structurally sound; the plugins
fire legitimately rarely (at most once per direction per RTH session).

Plugin design: compute_full() is called once per bar with the current bar as the last
row of the DataFrame. State persists in plugin._state across calls within a session.
Tests simulate this by calling compute_full() once per bar incrementally.

Phase 126: diagnose zero-signal time-specific plugins; confirm CORRECT-RARE.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from src.intelligence.archive.trading_i7.orb15 import ORB15Plugin
from src.intelligence.archive.trading_i7.orb30 import ORB30Plugin

_ET_TZ = ZoneInfo("America/New_York")
_MIN_LOOKBACK = 20  # plugin.min_lookback = 20


def _et(hour: int, minute: int = 0, date: str = "2026-06-10") -> datetime:
    """Return a UTC datetime for a given ET wall-clock time on the given date."""
    y, m, d = date.split("-")
    naive_et = datetime(int(y), int(m), int(d), hour, minute)
    return naive_et.replace(tzinfo=_ET_TZ).astimezone(UTC)


def _base_bar(ts: datetime, close: float = 5000.0, volume: float = 800.0) -> dict:
    """Return a neutral bar dict (no breakout)."""
    return {
        "timestamp": ts,
        "open": 5000.0,
        "high": 5005.0,
        "low": 4995.0,
        "close": close,
        "volume": volume,
    }


def _make_frames(history: list[dict], symbol: str = "ESM6", tf: str = "1m") -> dict:
    """Build frames dict with history as DataFrame (last row = current bar)."""
    df = pd.DataFrame(history)
    features: dict = {
        "hmm_prob_trending_up": 0.6,
        "hmm_prob_trending_down": 0.1,
        "hmm_regime": 1.0,  # trending — ORB is a trend plugin
        "atr_14": 8.0,
        "prior_session_close": 4990.0,
    }
    return {
        "main": df,
        "__symbol__": symbol,
        "__timeframe__": tf,
        "timeframe": tf,
        "i1": features,
        "i2": {},
        "i3": {},
        "i4": {},
        "i5": {},
        "smc": {},
        "i6": {"ctf_score": 0.5},
    }


def _simulate_session_to_orb15_breakout(
    plugin: ORB15Plugin,
    orb_high: float = 5010.0,
    orb_low: float = 4990.0,
    breakout_direction: int = 1,
    breakout_volume: float = 2000.0,
) -> dict:
    """Drive the plugin through a full ORB15 accumulation + breakout sequence.

    Returns the signal dict from the breakout bar (or empty if no signal).
    """
    history: list[dict] = []

    # Warmup: pad history to min_lookback with pre-session bars
    for i in range(_MIN_LOOKBACK):
        ts = _et(9, 20) - timedelta(minutes=_MIN_LOOKBACK - i)
        history.append(_base_bar(ts))

    # Range accumulation bars: 09:30-09:44 ET (15 bars)
    for i in range(15):
        ts = _et(9, 30) + timedelta(minutes=i)
        bar = {
            "timestamp": ts,
            "open": 5000.0,
            "high": orb_high,
            "low": orb_low,
            "close": (orb_high + orb_low) / 2,
            "volume": 800.0,
        }
        history.append(bar)
        plugin.compute_full(_make_frames(history))

    # Breakout bar at 09:45 ET
    if breakout_direction == 1:
        breakout_close = orb_high + 8.0  # clearly above range high
    else:
        breakout_close = orb_low - 8.0  # clearly below range low

    history.append(
        {
            "timestamp": _et(9, 45),
            "open": (orb_high + orb_low) / 2,
            "high": max((orb_high + orb_low) / 2, breakout_close),
            "low": min((orb_high + orb_low) / 2, breakout_close),
            "close": breakout_close,
            "volume": breakout_volume,
        }
    )
    return plugin.compute_full(_make_frames(history))


def _simulate_session_to_orb30_breakout(
    plugin: ORB30Plugin,
    orb_high: float = 5010.0,
    orb_low: float = 4990.0,
    breakout_direction: int = 1,
    breakout_volume: float = 2000.0,
) -> dict:
    """Drive the plugin through a full ORB30 accumulation + breakout sequence."""
    history: list[dict] = []

    # Warmup: pre-session bars
    for i in range(_MIN_LOOKBACK):
        ts = _et(9, 20) - timedelta(minutes=_MIN_LOOKBACK - i)
        history.append(_base_bar(ts))

    # Range accumulation bars: 09:30-09:59 ET (30 bars)
    for i in range(30):
        ts = _et(9, 30) + timedelta(minutes=i)
        bar = {
            "timestamp": ts,
            "open": 5000.0,
            "high": orb_high,
            "low": orb_low,
            "close": (orb_high + orb_low) / 2,
            "volume": 800.0,
        }
        history.append(bar)
        plugin.compute_full(_make_frames(history))

    # Breakout bar at 10:00 ET
    if breakout_direction == 1:
        breakout_close = orb_high + 8.0
    else:
        breakout_close = orb_low - 8.0

    history.append(
        {
            "timestamp": _et(10, 0),
            "open": (orb_high + orb_low) / 2,
            "high": max((orb_high + orb_low) / 2, breakout_close),
            "low": min((orb_high + orb_low) / 2, breakout_close),
            "close": breakout_close,
            "volume": breakout_volume,
        }
    )
    return plugin.compute_full(_make_frames(history))


class TestORB15Plugin:
    """Tests for ORB15: 09:30-09:44 ET range accumulation, 09:45-11:30 ET breakout."""

    def _fresh_plugin(self) -> ORB15Plugin:
        p = ORB15Plugin()
        p._state = {}
        return p

    def test_shadow_only_true(self):
        """ORB15 must have shadow_only=True."""
        plugin = self._fresh_plugin()
        assert plugin.shadow_only is True

    def test_no_signal_during_accumulation_window(self):
        """During 09:30-09:44 ET, plugin accumulates range and returns no_signal."""
        plugin = self._fresh_plugin()
        history: list[dict] = []
        # Pad to min_lookback
        for i in range(_MIN_LOOKBACK):
            ts = _et(9, 20) - timedelta(minutes=_MIN_LOOKBACK - i)
            history.append(_base_bar(ts))
        # Bar inside accumulation window
        history.append(
            {
                "timestamp": _et(9, 32),
                "open": 5000.0,
                "high": 5010.0,
                "low": 4990.0,
                "close": 5000.0,
                "volume": 800.0,
            }
        )
        result = plugin.compute_full(_make_frames(history))
        assert result.get("signal_type", "none") in ("none", "")

    def test_long_breakout_fires_with_volume(self):
        """ORB15 fires a long signal when close > orb_high with volume >= 1.5x avg."""
        plugin = self._fresh_plugin()
        result = _simulate_session_to_orb15_breakout(
            plugin, orb_high=5010.0, orb_low=4990.0, breakout_direction=1, breakout_volume=2000.0
        )
        assert result.get("signal_type") == "orb15_breakout_long", (
            f"Expected orb15_breakout_long, got {result.get('signal_type')!r}. "
            f"State: {plugin._state}"
        )
        assert result.get("direction") == 1

    def test_short_breakout_fires_with_volume(self):
        """ORB15 fires a short signal when close < orb_low with volume >= 1.5x avg."""
        plugin = self._fresh_plugin()
        result = _simulate_session_to_orb15_breakout(
            plugin, orb_high=5010.0, orb_low=4990.0, breakout_direction=-1, breakout_volume=2000.0
        )
        assert (
            result.get("signal_type") == "orb15_breakout_short"
        ), f"Expected orb15_breakout_short, got {result.get('signal_type')!r}"
        assert result.get("direction") == -1

    def test_fire_once_long_suppresses_duplicate(self):
        """ORB15 fires long once per session; second long breakout bar produces no signal."""
        plugin = self._fresh_plugin()
        result1 = _simulate_session_to_orb15_breakout(
            plugin, breakout_direction=1, breakout_volume=2000.0
        )
        assert result1.get("signal_type") == "orb15_breakout_long"

        # Second long breakout bar on the same session — should be suppressed
        history: list[dict] = []
        for i in range(_MIN_LOOKBACK):
            ts = _et(9, 20) - timedelta(minutes=_MIN_LOOKBACK - i)
            history.append(_base_bar(ts))
        for i in range(15):
            ts = _et(9, 30) + timedelta(minutes=i)
            history.append(
                {
                    "timestamp": ts,
                    "open": 5000.0,
                    "high": 5010.0,
                    "low": 4990.0,
                    "close": 5000.0,
                    "volume": 800.0,
                }
            )
        history.append(
            {
                "timestamp": _et(9, 45),
                "open": 5010.0,
                "high": 5020.0,
                "low": 5010.0,
                "close": 5018.0,
                "volume": 2000.0,
            }
        )
        history.append(
            {
                "timestamp": _et(9, 46),
                "open": 5020.0,
                "high": 5025.0,
                "low": 5018.0,
                "close": 5023.0,
                "volume": 2000.0,
            }
        )
        result2 = plugin.compute_full(_make_frames(history))
        assert result2.get("signal_type", "none") in (
            "none",
            "",
        ), "fire-once guard failed: second long breakout must not re-fire"

    def test_no_breakout_without_volume(self):
        """Breakout close without volume expansion does not fire."""
        plugin = self._fresh_plugin()
        history: list[dict] = []
        for i in range(_MIN_LOOKBACK):
            ts = _et(9, 20) - timedelta(minutes=_MIN_LOOKBACK - i)
            history.append(_base_bar(ts))
        for i in range(15):
            ts = _et(9, 30) + timedelta(minutes=i)
            history.append(
                {
                    "timestamp": ts,
                    "open": 5000.0,
                    "high": 5010.0,
                    "low": 4990.0,
                    "close": 5000.0,
                    "volume": 800.0,
                }
            )
            plugin.compute_full(_make_frames(history))
        # Breakout close but LOW volume (< 1.5x avg)
        history.append(
            {
                "timestamp": _et(9, 45),
                "open": 5011.0,
                "high": 5020.0,
                "low": 5010.0,
                "close": 5018.0,
                "volume": 900.0,  # 900/800 = 1.125x — below 1.5x threshold
            }
        )
        result = plugin.compute_full(_make_frames(history))
        assert result.get("signal_type", "none") in (
            "none",
            "",
        ), "ORB15 must not fire without volume expansion (< 1.5x avg)"


class TestORB30Plugin:
    """Tests for ORB30: 09:30-09:59 ET range accumulation, 10:00-11:30 ET breakout."""

    def _fresh_plugin(self) -> ORB30Plugin:
        p = ORB30Plugin()
        p._state = {}
        return p

    def test_shadow_only_true(self):
        """ORB30 must have shadow_only=True."""
        plugin = self._fresh_plugin()
        assert plugin.shadow_only is True

    def test_no_signal_during_30min_accumulation(self):
        """During 09:30-09:59 ET, plugin accumulates range and returns no_signal."""
        plugin = self._fresh_plugin()
        history: list[dict] = []
        for i in range(_MIN_LOOKBACK):
            ts = _et(9, 20) - timedelta(minutes=_MIN_LOOKBACK - i)
            history.append(_base_bar(ts))
        history.append(
            {
                "timestamp": _et(9, 45),
                "open": 5000.0,
                "high": 5010.0,
                "low": 4990.0,
                "close": 5000.0,
                "volume": 800.0,
            }
        )
        result = plugin.compute_full(_make_frames(history))
        assert result.get("signal_type", "none") in ("none", "")

    def test_long_breakout_fires_at_10am_with_volume(self):
        """ORB30 fires a long signal at/after 10:00 ET when close > orb_high + volume gate."""
        plugin = self._fresh_plugin()
        result = _simulate_session_to_orb30_breakout(
            plugin, orb_high=5010.0, orb_low=4990.0, breakout_direction=1, breakout_volume=2000.0
        )
        assert (
            result.get("signal_type") == "orb30_breakout_long"
        ), f"Expected orb30_breakout_long, got {result.get('signal_type')!r}"
        assert result.get("direction") == 1

    def test_short_breakout_fires_with_volume(self):
        """ORB30 fires a short signal when close < orb_low with volume >= 1.5x."""
        plugin = self._fresh_plugin()
        result = _simulate_session_to_orb30_breakout(
            plugin, orb_high=5010.0, orb_low=4990.0, breakout_direction=-1, breakout_volume=2000.0
        )
        assert (
            result.get("signal_type") == "orb30_breakout_short"
        ), f"Expected orb30_breakout_short, got {result.get('signal_type')!r}"

    def test_no_breakout_at_0945_still_accumulating(self):
        """At 09:45 ET, ORB30 is still in accumulation window — returns no signal
        even if close would be a breakout in ORB15."""
        plugin = self._fresh_plugin()
        history: list[dict] = []
        for i in range(_MIN_LOOKBACK):
            ts = _et(9, 20) - timedelta(minutes=_MIN_LOOKBACK - i)
            history.append(_base_bar(ts))
        # Only 15 bars of accumulation (09:30-09:44), then a 09:45 "breakout" bar
        # ORB30 is still accumulating at 09:45 (window is 09:30-09:59)
        for i in range(15):
            ts = _et(9, 30) + timedelta(minutes=i)
            history.append(
                {
                    "timestamp": ts,
                    "open": 5000.0,
                    "high": 5010.0,
                    "low": 4990.0,
                    "close": 5000.0,
                    "volume": 800.0,
                }
            )
            plugin.compute_full(_make_frames(history))
        history.append(
            {
                "timestamp": _et(9, 45),
                "open": 5011.0,
                "high": 5020.0,
                "low": 5010.0,
                "close": 5018.0,
                "volume": 2000.0,
            }
        )
        result = plugin.compute_full(_make_frames(history))
        # ORB30 is still accumulating at 09:45 — should not fire
        assert result.get("signal_type", "none") in (
            "none",
            "",
        ), "ORB30 must not fire at 09:45 ET (still in 30-min accumulation window)"
