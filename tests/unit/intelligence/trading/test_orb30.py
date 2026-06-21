"""Unit tests for trad_ORB30 I7 plugin (Opening Range Breakout — 30-min window)."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import numpy as np

from tests.unit.intelligence.helpers import make_ohlcv

_ET = ZoneInfo("America/New_York")


def _ts_utc(hour: int, minute: int, date: tuple[int, int, int] = (2026, 3, 17)) -> datetime:
    y, mo, d = date
    et_dt = datetime(y, mo, d, hour, minute, tzinfo=_ET)
    return et_dt.astimezone(UTC)


def _make_frames(close_arr, features=None, ts_utc_val=None, volume=None, symbol="ES", tf="1m"):
    df = make_ohlcv(np.array(close_arr, dtype=float), volume=volume)
    if ts_utc_val is not None:
        df["timestamp"] = [ts_utc_val] * len(df)
    return {
        "main": df,
        "i1": features,
        "i2": features,
        "i3": features,
        "i4": features,
        "i5": features,
        "smc": features,
        "i6": features or {},
        "__symbol__": symbol,
        "__timeframe__": tf,
    }


def _base_features(**kwargs):
    defaults = {
        "atr_14": 5.0,
        "hmm_regime": 0.0,
        "prior_session_close": 0.0,
        "hmm_prob_trending_up": 0.70,  # continuous regime gate (>= 0.30)
        "hmm_prob_trending_down": 0.10,
        "ctf_score": 0.40,  # I6 gate (abs >= 0.25)
    }
    defaults.update(kwargs)
    return defaults


# ─── ORB30-specific gate tests ────────────────────────────────────────────────


def test_no_signal_before_range_complete():
    """timestamp at 09:50 ET is during 09:30-10:00 accumulation window -> no_signal."""
    from src.intelligence.archive.trading_i7.orb30 import ORB30Plugin

    plugin = ORB30Plugin()
    close = np.linspace(5000.0, 5010.0, 25)
    ts = _ts_utc(9, 50)
    result = plugin.compute_full(_make_frames(close, _base_features(), ts))
    assert result.get("direction") == 0


def test_fires_on_breakout_long():
    """After range complete (10:00+ ET), close > orb_high + volume expansion -> long signal."""
    from src.intelligence.archive.trading_i7.orb30 import ORB30Plugin

    plugin = ORB30Plugin()

    # Accumulate during 09:30-09:59 ET
    close_range = np.linspace(5000.0, 5005.0, 25)
    for minute in [30, 40, 50, 59]:
        ts = _ts_utc(9, minute)
        plugin.compute_full(_make_frames(close_range, _base_features(), ts))

    # Breakout at 10:05 ET
    ts_break = _ts_utc(10, 5)
    close_break = np.linspace(5000.0, 5020.0, 25)
    high_vol = np.full(25, 800.0)
    high_vol[-1] = 3000.0

    result = plugin.compute_full(
        _make_frames(close_break, _base_features(), ts_break, volume=high_vol)
    )
    assert result.get("direction") == 1
    assert result.get("signal_type") == "orb30_breakout_long"
    assert result.get("confidence", 0.0) > 0.0
    assert "entry_price" in result
    assert "stop_loss" in result
    assert "targets" in result


def test_fires_on_breakout_short():
    """After range complete (10:00+ ET), close < orb_low + volume expansion -> short signal."""
    from src.intelligence.archive.trading_i7.orb30 import ORB30Plugin

    plugin = ORB30Plugin()

    close_range = np.linspace(5000.0, 5005.0, 25)
    for minute in [30, 40, 50, 59]:
        ts = _ts_utc(9, minute)
        plugin.compute_full(_make_frames(close_range, _base_features(), ts))

    ts_break = _ts_utc(10, 10)
    close_break = np.linspace(5005.0, 4980.0, 25)  # well below range low
    high_vol = np.full(25, 800.0)
    high_vol[-1] = 3000.0

    result = plugin.compute_full(
        _make_frames(close_break, _base_features(), ts_break, volume=high_vol)
    )
    assert result.get("direction") == -1
    assert result.get("signal_type") == "orb30_breakout_short"


def test_session_gate_blocks_after_1130():
    """timestamp at 11:35 ET is outside 09:30-11:30 window -> no_signal."""
    from src.intelligence.archive.trading_i7.orb30 import ORB30Plugin

    plugin = ORB30Plugin()
    close = np.linspace(5000.0, 5010.0, 25)
    ts = _ts_utc(11, 35)
    result = plugin.compute_full(_make_frames(close, _base_features(), ts))
    assert result.get("direction") == 0
    assert result.get("confidence") == 0.0


def test_no_signal_without_volume_expansion():
    """Close above orb_high but uniform low volume -> no_signal."""
    from src.intelligence.archive.trading_i7.orb30 import ORB30Plugin

    plugin = ORB30Plugin()

    close_range = np.linspace(5000.0, 5005.0, 25)
    for minute in [30, 40, 50, 59]:
        ts = _ts_utc(9, minute)
        plugin.compute_full(_make_frames(close_range, _base_features(), ts))

    ts_break = _ts_utc(10, 5)
    close_break = np.linspace(5000.0, 5020.0, 25)
    low_vol = np.full(25, 800.0)  # uniform low volume — no expansion

    result = plugin.compute_full(
        _make_frames(close_break, _base_features(), ts_break, volume=low_vol)
    )
    assert result.get("direction") == 0


def test_module_level_plugin_instance():
    """Module exports a plugin instance."""
    import src.intelligence.archive.trading_i7.orb30 as mod

    assert hasattr(mod, "plugin")
    from src.intelligence.archive.trading_i7.orb30 import ORB30Plugin

    assert isinstance(mod.plugin, ORB30Plugin)


def test_tf_guard_returns_no_signal_on_1h():
    """frames['timeframe']='1h' must return no_signal immediately (before any other logic)."""
    from src.intelligence.archive.trading_i7.orb30 import ORB30Plugin

    plugin = ORB30Plugin()
    close = np.linspace(5000.0, 5010.0, 25)
    ts = _ts_utc(10, 30)
    frames = _make_frames(close, _base_features(), ts)
    frames["timeframe"] = "1h"
    result = plugin.compute_full(frames)
    assert result == {"signal_type": "none", "direction": 0, "confidence": 0.0}
