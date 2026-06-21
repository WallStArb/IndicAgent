"""Unit tests for trad_ORB15 I7 plugin (Opening Range Breakout — 15-min window)."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import numpy as np

from tests.unit.intelligence.helpers import make_ohlcv

_ET = ZoneInfo("America/New_York")


def _ts_utc(hour: int, minute: int, date: tuple[int, int, int] = (2026, 3, 17)) -> datetime:
    """Return a UTC datetime for the given ET time."""
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


# ─── Window gate tests ────────────────────────────────────────────────────────


def test_no_signal_outside_session_window():
    """timestamp at 12:00 ET is outside 09:30-11:30 ET window -> no_signal."""
    from src.intelligence.archive.trading_i7.orb15 import ORB15Plugin

    plugin = ORB15Plugin()
    close = np.linspace(5000.0, 5010.0, 25)
    ts = _ts_utc(12, 0)
    result = plugin.compute_full(_make_frames(close, _base_features(), ts))
    assert result.get("direction") == 0
    assert result.get("confidence") == 0.0


def test_no_signal_before_range_complete():
    """timestamp at 09:40 ET is during accumulation window (09:30-09:45) -> no_signal."""
    from src.intelligence.archive.trading_i7.orb15 import ORB15Plugin

    plugin = ORB15Plugin()
    close = np.linspace(5000.0, 5010.0, 25)
    ts = _ts_utc(9, 40)
    result = plugin.compute_full(_make_frames(close, _base_features(), ts))
    assert result.get("direction") == 0


def test_fires_on_breakout_long():
    """After range complete (09:45+ ET), close > orb_high + volume expansion -> long signal."""
    from src.intelligence.archive.trading_i7.orb15 import ORB15Plugin

    plugin = ORB15Plugin()

    # Step 1: accumulate range during 09:30-09:44 ET
    close_range = np.linspace(5000.0, 5005.0, 25)
    for minute in [30, 35, 40, 44]:
        ts = _ts_utc(9, minute)
        plugin.compute_full(_make_frames(close_range, _base_features(), ts))

    # Step 2: breakout bar at 09:46 ET — close clearly above range high (+30 pts), high volume
    ts_break = _ts_utc(9, 46)
    close_break = np.linspace(
        5000.0, 5040.0, 25
    )  # close[-1]=5040, well above orb_high (~5005+spread)
    high_vol = np.full(25, 800.0)
    high_vol[-1] = 3000.0  # large spike on last bar

    result = plugin.compute_full(
        _make_frames(close_break, _base_features(), ts_break, volume=high_vol)
    )
    assert result.get("direction") == 1
    assert result.get("signal_type") == "orb15_breakout_long"
    assert result.get("confidence", 0.0) > 0.0
    assert "entry_price" in result
    assert "stop_loss" in result
    assert "targets" in result


def test_fires_on_breakout_short():
    """After range complete, close < orb_low + volume expansion -> short signal."""
    from src.intelligence.archive.trading_i7.orb15 import ORB15Plugin

    plugin = ORB15Plugin()

    close_range = np.linspace(5000.0, 5005.0, 25)
    for minute in [30, 35, 40, 44]:
        ts = _ts_utc(9, minute)
        plugin.compute_full(_make_frames(close_range, _base_features(), ts))

    # Breakout short: close well below orb_low (range low ~5000-spread)
    ts_break = _ts_utc(9, 50)
    close_break = np.linspace(5005.0, 4960.0, 25)  # close[-1]=4960, well below range low
    high_vol = np.full(25, 800.0)
    high_vol[-1] = 3000.0

    result = plugin.compute_full(
        _make_frames(close_break, _base_features(), ts_break, volume=high_vol)
    )
    assert result.get("direction") == -1
    assert result.get("signal_type") == "orb15_breakout_short"


def test_no_signal_without_volume_expansion():
    """Close above orb_high but volume < 1.5x average -> no_signal."""
    from src.intelligence.archive.trading_i7.orb15 import ORB15Plugin

    plugin = ORB15Plugin()

    close_range = np.linspace(5000.0, 5005.0, 25)
    for minute in [30, 35, 40, 44]:
        ts = _ts_utc(9, minute)
        plugin.compute_full(_make_frames(close_range, _base_features(), ts))

    ts_break = _ts_utc(9, 50)
    close_break = np.linspace(5000.0, 5040.0, 25)  # close clearly above orb_high
    # Uniform low volume — no expansion (all bars same volume, ratio=1.0 < 1.5)
    low_vol = np.full(25, 800.0)

    result = plugin.compute_full(
        _make_frames(close_break, _base_features(), ts_break, volume=low_vol)
    )
    assert result.get("direction") == 0


def test_gap_bias_boosts_long_confidence():
    """Gap up (open > prior_session_close by > 0.1%) boosts long confidence."""
    from src.intelligence.archive.trading_i7.orb15 import ORB15Plugin

    plugin_gap = ORB15Plugin()
    plugin_flat = ORB15Plugin()

    close_range = np.linspace(5010.0, 5015.0, 25)
    for minute in [30, 35, 40, 44]:
        ts = _ts_utc(9, minute)
        plugin_gap.compute_full(_make_frames(close_range, _base_features(), ts))
        plugin_flat.compute_full(_make_frames(close_range, _base_features(), ts))

    ts_break = _ts_utc(9, 50)
    close_break = np.linspace(5010.0, 5050.0, 25)  # needs clear margin above orb_high (~5025)
    high_vol = np.full(25, 800.0)
    high_vol[-1] = 3000.0

    # With gap up (open=5010, pdc=4970 -> gap=0.8% > 0.1%) — aligns with long
    feat_gap = _base_features(prior_session_close=4970.0)
    result_gap = plugin_gap.compute_full(
        _make_frames(close_break, feat_gap, ts_break, volume=high_vol)
    )

    # Without gap (pdc=0, no gap calculation)
    feat_flat = _base_features(prior_session_close=0.0)
    result_flat = plugin_flat.compute_full(
        _make_frames(close_break, feat_flat, ts_break, volume=high_vol)
    )

    if result_gap.get("direction") == 1 and result_flat.get("direction") == 1:
        assert result_gap.get("confidence", 0.0) > result_flat.get("confidence", 0.0)
    else:
        # At least one fired — check the gap-boosted one fired
        assert result_gap.get("direction") == 1


def test_state_resets_on_new_session_date():
    """Different date causes range state to reset and re-accumulate."""
    from src.intelligence.archive.trading_i7.orb15 import ORB15Plugin

    plugin = ORB15Plugin()

    # Day 1: accumulate range
    close_range = np.linspace(5000.0, 5005.0, 25)
    for minute in [30, 35, 40, 44]:
        ts = _ts_utc(9, minute, date=(2026, 3, 17))
        plugin.compute_full(_make_frames(close_range, _base_features(), ts))

    # Day 2: new session — range should reset
    ts_day2 = _ts_utc(9, 35, date=(2026, 3, 18))
    plugin.compute_full(_make_frames(close_range, _base_features(), ts_day2))

    state = plugin._state.get(("ES", "1m"), {})
    from datetime import date

    assert state.get("session_date") == date(2026, 3, 18), "State should reflect new session date"
    # range_complete should be False after new session reset
    assert not state.get("range_complete", False)


def test_fires_only_once_per_direction():
    """After firing long, same direction does not re-fire in the same session."""
    from src.intelligence.archive.trading_i7.orb15 import ORB15Plugin

    plugin = ORB15Plugin()

    # Accumulate range
    close_range = np.linspace(5000.0, 5005.0, 25)
    for minute in [30, 35, 40, 44]:
        ts = _ts_utc(9, minute)
        plugin.compute_full(_make_frames(close_range, _base_features(), ts))

    high_vol = np.full(25, 800.0)
    high_vol[-1] = 3000.0
    close_break = np.linspace(5000.0, 5020.0, 25)

    # First breakout: should fire
    result1 = plugin.compute_full(
        _make_frames(close_break, _base_features(), _ts_utc(9, 50), volume=high_vol)
    )
    assert result1.get("direction") == 1

    # Second breakout in same direction: should NOT fire
    result2 = plugin.compute_full(
        _make_frames(close_break, _base_features(), _ts_utc(10, 0), volume=high_vol)
    )
    assert result2.get("direction") == 0


def test_min_lookback_guard():
    """Returns no_signal when df has fewer rows than min_lookback."""
    from src.intelligence.archive.trading_i7.orb15 import ORB15Plugin

    plugin = ORB15Plugin()
    close = np.array([5000.0] * 5)
    ts = _ts_utc(10, 0)
    result = plugin.compute_full(_make_frames(close, _base_features(), ts))
    assert result.get("signal_type") == "none"
    assert result.get("direction") == 0


def test_module_level_plugin_instance():
    """Module exports a plugin instance."""
    import src.intelligence.archive.trading_i7.orb15 as mod

    assert hasattr(mod, "plugin")
    from src.intelligence.archive.trading_i7.orb15 import ORB15Plugin

    assert isinstance(mod.plugin, ORB15Plugin)


def test_tf_guard_returns_no_signal_on_1h():
    """frames['timeframe']='1h' must return no_signal immediately (before any other logic)."""
    from src.intelligence.archive.trading_i7.orb15 import ORB15Plugin

    plugin = ORB15Plugin()
    close = np.linspace(5000.0, 5010.0, 25)
    ts = _ts_utc(9, 50)
    frames = _make_frames(close, _base_features(), ts)
    frames["timeframe"] = "1h"
    result = plugin.compute_full(frames)
    assert result == {"signal_type": "none", "direction": 0, "confidence": 0.0}
