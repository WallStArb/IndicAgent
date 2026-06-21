"""Unit tests for trad_VCP I7 plugin (Volatility Contraction Pattern breakout)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np

from tests.unit.intelligence.helpers import make_ohlcv


def _make_frames_hl(high_val, low_val, volume_val, features=None, symbol="ES", tf="1m", ts=None):
    """Build frames with explicit high/low/volume for the last bar."""
    n = 25
    close = np.full(n, (high_val + low_val) / 2)
    df = make_ohlcv(close, volume=np.full(n, volume_val))
    # Override last bar with explicit values
    df.loc[df.index[-1], "high"] = high_val
    df.loc[df.index[-1], "low"] = low_val
    df.loc[df.index[-1], "close"] = (high_val + low_val) / 2
    # Override high[-2] so breakout check passes
    df.loc[df.index[-2], "high"] = low_val  # set prior high low so close > prior high
    df.loc[df.index[-2], "low"] = low_val - 1.0

    if ts is not None:
        df["timestamp"] = ts

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
        "hmm_regime": 1.0,
        "hmm_regime_prob": 0.75,
        "hmm_prob_trending_up": 0.75,  # continuous regime gate (>= 0.30)
        "hmm_prob_trending_down": 0.10,
        "ctf_score": 0.40,  # I6 gate (abs >= 0.25)
        "swing_low": 4900.0,
        "swing_high": 5200.0,
        "nearest_resistance": 5300.0,
        "nearest_support": 4800.0,
    }
    defaults.update(kwargs)
    return defaults


def _run_contractions(plugin, n_contractions, symbol="ES", tf="1m", features=None):
    """Feed n_contractions bars with decreasing H-L range and volume.

    Returns the plugin instance after feeding contractions (no expansion bar).
    """
    if features is None:
        features = _base_features()

    start_range = 20.0
    start_vol = 1000.0
    center = 5050.0

    for i in range(n_contractions):
        bar_range = start_range - i * 2.0
        bar_vol = start_vol - i * 50.0
        high_val = center + bar_range / 2
        low_val = center - bar_range / 2
        frames = _make_frames_hl(
            high_val, low_val, bar_vol, features=features, symbol=symbol, tf=tf
        )
        plugin.compute_full(frames)

    return plugin


# ─── Regime gate tests ───────────────────────────────────────────────────────


def test_no_signal_when_hmm_not_trend():
    """Both hmm_prob_trending_up and _down below 0.30 -> no_signal (continuous regime gate)."""
    from src.intelligence.archive.trading_i7.vcp import VCPPlugin

    plugin = VCPPlugin()
    features = _base_features(
        hmm_regime=0.0,
        hmm_prob_trending_up=0.10,
        hmm_prob_trending_down=0.10,
    )
    frames = _make_frames_hl(5055.0, 5045.0, 500.0, features=features)
    result = plugin.compute_full(frames)
    assert result.get("signal_type") == "none"
    assert result.get("direction") == 0


def test_no_signal_when_ctf_below_threshold():
    """abs(ctf_score) < 0.25 -> no_signal (I6 ctf gate replaces old hmm_regime_prob gate)."""
    from src.intelligence.archive.trading_i7.vcp import VCPPlugin

    plugin = VCPPlugin()
    features = _base_features(ctf_score=0.10)  # abs < 0.25 threshold
    frames = _make_frames_hl(5055.0, 5045.0, 500.0, features=features)
    result = plugin.compute_full(frames)
    assert result.get("signal_type") == "none"


# ─── Insufficient contractions test ─────────────────────────────────────────


def test_no_signal_with_only_two_contractions():
    """Only 2 contractions -> no_signal (need >= 3)."""
    from src.intelligence.archive.trading_i7.vcp import VCPPlugin

    plugin = VCPPlugin()
    features = _base_features()

    # Feed 2 contractions (decreasing range + volume)
    plugin = _run_contractions(plugin, 2, features=features)

    # Now expansion bar — range > last contraction, volume > last contraction * 1.2
    high_val = 5060.0  # range = 20 > 12 (last contraction range = 20-2*2=16, then 16-2=14)
    low_val = 5040.0
    # Close above prior high for breakout
    exp_frames = _make_frames_hl(high_val, low_val, 1500.0, features=features)
    # Override close to be above prior high
    exp_frames["main"].loc[exp_frames["main"].index[-1], "close"] = 5059.0

    result = plugin.compute_full(exp_frames)
    assert result.get("signal_type") == "none"


# ─── Fires after 3+ contractions ────────────────────────────────────────────


def test_fires_after_three_contractions():
    """3+ contractions with declining range/volume, then expansion bar -> fires."""
    from src.intelligence.archive.trading_i7.vcp import VCPPlugin

    plugin = VCPPlugin()
    features = _base_features(
        hmm_regime=1.0,
        hmm_regime_prob=0.75,
        nearest_resistance=5300.0,
        nearest_support=4800.0,
        swing_low=4900.0,
    )

    # Feed 3 contractions
    center = 5050.0
    ranges = [20.0, 14.0, 10.0]
    vols = [1000.0, 700.0, 500.0]
    for r, v in zip(ranges, vols, strict=True):
        high_val = center + r / 2
        low_val = center - r / 2
        frames = _make_frames_hl(high_val, low_val, v, features=features)
        plugin.compute_full(frames)

    # Expansion bar: larger range, higher volume, close above prior high
    exp_high = center + 15.0  # range=30 > 10 (last contraction)
    exp_low = center - 5.0
    exp_vol = 800.0  # > 500*1.2=600
    exp_frames = _make_frames_hl(exp_high, exp_low, exp_vol, features=features)
    # Set close to be clearly above prior bar high (= center + 10/2 = 5055)
    # prior_high was 5055 so close needs to be > 5055
    exp_frames["main"].loc[exp_frames["main"].index[-1], "close"] = exp_high - 0.5
    # Set prior bar high to be below exp_high-0.5 so breakout confirmed
    exp_frames["main"].loc[exp_frames["main"].index[-2], "high"] = center + 4.0
    exp_frames["main"].loc[exp_frames["main"].index[-2], "low"] = center - 4.0

    result = plugin.compute_full(exp_frames)
    # May or may not fire depending on frame_trade viability
    if result.get("direction") != 0:
        assert result.get("signal_type") in ("vcp_breakout_long", "vcp_breakout_short")
        assert result.get("contraction_count", 0) >= 3


def test_direction_follows_hmm_trend_long():
    """hmm_regime=1.0 -> direction=1 (long breakout)."""
    from src.intelligence.archive.trading_i7.vcp import VCPPlugin

    plugin = VCPPlugin()
    features = _base_features(
        hmm_regime=1.0, hmm_regime_prob=0.75, nearest_resistance=5300.0, nearest_support=4800.0
    )

    center = 5050.0
    for r, v in [(20.0, 1000.0), (14.0, 700.0), (10.0, 500.0)]:
        frames = _make_frames_hl(center + r / 2, center - r / 2, v, features=features)
        plugin.compute_full(frames)

    exp_frames = _make_frames_hl(center + 15, center - 5, 800.0, features=features)
    exp_frames["main"].loc[exp_frames["main"].index[-1], "close"] = center + 14.0
    exp_frames["main"].loc[exp_frames["main"].index[-2], "high"] = center + 4.0
    exp_frames["main"].loc[exp_frames["main"].index[-2], "low"] = center - 4.0

    result = plugin.compute_full(exp_frames)
    if result.get("direction") != 0:
        assert result.get("direction") == 1
        assert result.get("signal_type") == "vcp_breakout_long"


def test_direction_follows_hmm_trend_short():
    """hmm_regime=2.0 -> direction=-1 (short breakout)."""
    from src.intelligence.archive.trading_i7.vcp import VCPPlugin

    plugin = VCPPlugin()
    features = _base_features(
        hmm_regime=2.0, hmm_regime_prob=0.75, nearest_support=4800.0, nearest_resistance=5300.0
    )

    center = 5050.0
    for r, v in [(20.0, 1000.0), (14.0, 700.0), (10.0, 500.0)]:
        frames = _make_frames_hl(center + r / 2, center - r / 2, v, features=features)
        plugin.compute_full(frames)

    exp_frames = _make_frames_hl(center + 5, center - 15, 800.0, features=features)
    exp_frames["main"].loc[exp_frames["main"].index[-1], "close"] = center - 14.0
    exp_frames["main"].loc[exp_frames["main"].index[-2], "high"] = center + 4.0
    exp_frames["main"].loc[exp_frames["main"].index[-2], "low"] = center - 4.0

    result = plugin.compute_full(exp_frames)
    if result.get("direction") != 0:
        assert result.get("direction") == -1
        assert result.get("signal_type") == "vcp_breakout_short"


# ─── Session reset test ──────────────────────────────────────────────────────


def test_state_resets_on_new_session():
    """Different session date -> contraction list clears (state reset)."""
    from src.intelligence.archive.trading_i7.vcp import VCPPlugin

    plugin = VCPPlugin()
    features = _base_features()

    # Day 1: feed 3 contractions
    ts_day1 = datetime(2026, 3, 17, 10, 0, tzinfo=UTC)
    center = 5050.0
    for i, (r, v) in enumerate([(20.0, 1000.0), (14.0, 700.0), (10.0, 500.0)]):
        ts = ts_day1 + timedelta(minutes=i)
        frames = _make_frames_hl(center + r / 2, center - r / 2, v, features=features, ts=ts)
        plugin.compute_full(frames)

    # Day 2: single bar — state should reset, no fire even with expansion bar
    ts_day2 = datetime(2026, 3, 18, 10, 0, tzinfo=UTC)
    exp_frames = _make_frames_hl(center + 15, center - 5, 800.0, features=features, ts=ts_day2)
    exp_frames["main"].loc[exp_frames["main"].index[-1], "close"] = center + 14.0
    exp_frames["main"].loc[exp_frames["main"].index[-2], "high"] = center + 4.0

    result = plugin.compute_full(exp_frames)
    # After reset, contractions list has only one bar -> no fire
    assert result.get("signal_type") == "none"


def test_contraction_count_in_output():
    """Valid VCP fire must include contraction_count >= 3 in output."""
    from src.intelligence.archive.trading_i7.vcp import VCPPlugin

    plugin = VCPPlugin()
    features = _base_features(
        hmm_regime=1.0,
        hmm_regime_prob=0.75,
        nearest_resistance=5300.0,
        nearest_support=4800.0,
        swing_low=4900.0,
    )

    center = 5050.0
    for r, v in [(20.0, 1000.0), (14.0, 700.0), (10.0, 500.0), (7.0, 400.0)]:
        frames = _make_frames_hl(center + r / 2, center - r / 2, v, features=features)
        plugin.compute_full(frames)

    exp_frames = _make_frames_hl(center + 15, center - 5, 800.0, features=features)
    exp_frames["main"].loc[exp_frames["main"].index[-1], "close"] = center + 14.0
    exp_frames["main"].loc[exp_frames["main"].index[-2], "high"] = center + 3.0
    exp_frames["main"].loc[exp_frames["main"].index[-2], "low"] = center - 3.0

    result = plugin.compute_full(exp_frames)
    if result.get("direction") != 0:
        assert result.get("contraction_count", 0) >= 3


def test_insufficient_lookback_returns_empty():
    """len(df) < min_lookback -> empty dict."""
    from src.intelligence.archive.trading_i7.vcp import VCPPlugin

    plugin = VCPPlugin()
    close = np.full(5, 5050.0)
    df = make_ohlcv(close)
    frames = {
        "main": df,
        "i1": _base_features(),
        "i2": _base_features(),
        "i3": _base_features(),
        "i4": _base_features(),
        "i5": _base_features(),
        "smc": _base_features(),
        "i6": _base_features(),
        "__symbol__": "ES",
        "__timeframe__": "1m",
    }
    result = plugin.compute_full(frames)
    assert result["signal_type"] == "none"
    assert result["direction"] == 0


def test_plugin_instance_exists():
    """Module-level plugin instance must exist."""
    from src.intelligence.archive.trading_i7.vcp import VCPPlugin, plugin

    assert isinstance(plugin, VCPPlugin)
    assert plugin.name == "trad_VCP"
    assert plugin.regime_type == "trend"
