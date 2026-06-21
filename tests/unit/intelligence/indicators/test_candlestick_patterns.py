"""
Unit tests for CandlestickPatternsPlugin — 10 new Phase 42 patterns.

Tests verify all 10 new pattern detection functions added in Phase 42.
"""

from __future__ import annotations

import pandas as pd

from src.intelligence.archive.i5_patterns.candlestick_patterns import plugin


def _make_ohlc_frame(opens, highs, lows, closes):
    """Helper to create minimal OHLCV frame."""
    df = pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [1000] * len(opens),
        }
    )
    return df


def test_harami_bull_valid():
    """Harami Bull: large bearish pp, small bullish p inside pp body.

    pp: open=100, close=94 (bearish), body=6, range=11, 6/11=54% > 50%
    p body high=94.5, low=94.2 — inside pp body [94,100]
    """
    df = _make_ohlc_frame(
        opens=[100, 95, 97],
        highs=[101, 95.5, 99],
        lows=[90, 94.2, 96],
        closes=[94, 95.3, 98.5],  # pp bearish, p bullish (95.3>95), p inside pp body
    )
    frames = {
        "main": df,
        "i1": {"atr_14": 5.0},
        "i2": {"atr_14": 5.0},
        "i3": {"atr_14": 5.0},
        "i4": {"atr_14": 5.0},
        "i5": {"atr_14": 5.0},
        "smc": {"atr_14": 5.0},
        "i6": {"atr_14": 5.0},
    }
    result = plugin.compute_full(frames)
    assert result.get("harami_bull") == 1.0


def test_harami_bull_not_fired_p_bearish():
    """Harami Bull requires p bullish."""
    df = _make_ohlc_frame(
        opens=[100, 95, 97],
        highs=[101, 95.5, 99],
        lows=[90, 94.2, 96],
        closes=[94, 94.8, 98.5],  # p bearish (94.8 < 95)
    )
    frames = {
        "main": df,
        "i1": {"atr_14": 5.0},
        "i2": {"atr_14": 5.0},
        "i3": {"atr_14": 5.0},
        "i4": {"atr_14": 5.0},
        "i5": {"atr_14": 5.0},
        "smc": {"atr_14": 5.0},
        "i6": {"atr_14": 5.0},
    }
    result = plugin.compute_full(frames)
    assert result.get("harami_bull") == 0.0


def test_harami_bear_valid():
    """Harami Bear: large bullish pp, small bearish p inside pp body.

    pp: open=100, close=108 (bullish), body=8, range=11
    p: open=105, close=104.5 (bearish), body=0.5, range=1.8, 0.5/1.8=28% < 30%
    p inside pp body [100,108]
    """
    df = _make_ohlc_frame(
        opens=[100, 105, 103],
        highs=[110, 106, 104],
        lows=[99, 104.2, 102],
        closes=[108, 104.5, 102.5],  # pp bullish, p bearish inside
    )
    frames = {
        "main": df,
        "i1": {"atr_14": 5.0},
        "i2": {"atr_14": 5.0},
        "i3": {"atr_14": 5.0},
        "i4": {"atr_14": 5.0},
        "i5": {"atr_14": 5.0},
        "smc": {"atr_14": 5.0},
        "i6": {"atr_14": 5.0},
    }
    result = plugin.compute_full(frames)
    assert result.get("harami_bear") == 1.0


def test_abandoned_baby_bull_valid():
    """Abandoned Baby Bull: large bearish pp, gap-up doji p, large bullish c.

    pp: open=100, close=94.5 (bearish), body=5.5, range=6.5, 84%>60%
    p: gap up (p_l=101.5 > pp_h=100.5), doji (body=0.08, range=1.0, ratio=8%<10%)
    c: bullish, body=3.5, range=4.5, 77%>60%
    """
    df = _make_ohlc_frame(
        opens=[100, 101.5, 102],
        highs=[100.5, 102.5, 106],
        lows=[94, 101.5, 101.5],
        closes=[94.5, 101.58, 105.5],  # pp bearish, p doji, c bullish
    )
    frames = {
        "main": df,
        "i1": {"atr_14": 5.0},
        "i2": {"atr_14": 5.0},
        "i3": {"atr_14": 5.0},
        "i4": {"atr_14": 5.0},
        "i5": {"atr_14": 5.0},
        "smc": {"atr_14": 5.0},
        "i6": {"atr_14": 5.0},
    }
    result = plugin.compute_full(frames)
    assert result.get("abandoned_baby_bull") == 1.0


def test_abandoned_baby_bear_valid():
    """Abandoned Baby Bear: large bullish pp, gap-down doji p, large bearish c.

    pp: open=100, close=105 (bullish), body=5, range=6, 83%>60%
    p: gap down (p_h=98.5 < pp_l=99.5), doji (body=0.08, range=1, 8%<10%)
    c: bearish, body=3.5, range=4.5, 77%>60%
    """
    df = _make_ohlc_frame(
        opens=[100, 98, 97],
        highs=[105.5, 98.5, 97.5],
        lows=[99.5, 97.5, 93],
        closes=[105, 98.08, 93.5],  # pp bullish, p doji, c bearish
    )
    frames = {
        "main": df,
        "i1": {"atr_14": 5.0},
        "i2": {"atr_14": 5.0},
        "i3": {"atr_14": 5.0},
        "i4": {"atr_14": 5.0},
        "i5": {"atr_14": 5.0},
        "smc": {"atr_14": 5.0},
        "i6": {"atr_14": 5.0},
    }
    result = plugin.compute_full(frames)
    assert result.get("abandoned_baby_bear") == 1.0


def test_tweezer_top_valid():
    """Tweezer Top: near-identical highs within 0.1*ATR.

    p_h=110, c_h=110.03, diff=0.03; ATR=1.0, threshold=0.1
    """
    df = _make_ohlc_frame(
        opens=[100, 105, 102],
        highs=[110, 110.03, 110],  # p and c highs within 0.03
        lows=[95, 100, 100],
        closes=[108, 103, 104],
    )
    frames = {
        "main": df,
        "i1": {"atr_14": 1.0},
        "i2": {"atr_14": 1.0},
        "i3": {"atr_14": 1.0},
        "i4": {"atr_14": 1.0},
        "i5": {"atr_14": 1.0},
        "smc": {"atr_14": 1.0},
        "i6": {"atr_14": 1.0},
    }  # 0.1*ATR = 0.1, 0.03 < 0.1
    result = plugin.compute_full(frames)
    assert result.get("tweezer_top") == 1.0


def test_tweezer_bottom_valid():
    """Tweezer Bottom: near-identical lows within 0.1*ATR.

    p_l=90, c_l=90.04, diff=0.04; ATR=1.0, threshold=0.1
    """
    df = _make_ohlc_frame(
        opens=[100, 95, 98],
        highs=[105, 100, 102],
        lows=[90, 90.04, 90],  # p and c lows within 0.04
        closes=[92, 97, 99],
    )
    frames = {
        "main": df,
        "i1": {"atr_14": 1.0},
        "i2": {"atr_14": 1.0},
        "i3": {"atr_14": 1.0},
        "i4": {"atr_14": 1.0},
        "i5": {"atr_14": 1.0},
        "smc": {"atr_14": 1.0},
        "i6": {"atr_14": 1.0},
    }
    result = plugin.compute_full(frames)
    assert result.get("tweezer_bottom") == 1.0


def test_belt_hold_bull_valid():
    """Belt Hold Bull: long white candle, upper wick < 10% of range.

    c: open=104, high=109.5, low=104, close=109
    body=5, range=5.5, upper_wick=0.5, lower_wick=0
    body/range=91%>70%, upper_wick/range=9%<10%
    """
    df = _make_ohlc_frame(
        opens=[100, 102, 104],
        highs=[105, 104.5, 109.5],
        lows=[95, 100, 104],
        closes=[104, 103, 109],  # c bullish, body 91% of range, upper wick 9%
    )
    frames = {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
    result = plugin.compute_full(frames)
    assert result.get("belt_hold_bull") == 1.0


def test_belt_hold_bear_valid():
    """Belt Hold Bear: long black candle, lower wick < 10% of range.

    c: open=96, high=96, low=90, close=90.5
    body=5.5, range=6, lower_wick=0.5, upper_wick=0
    body/range=92%>70%, lower_wick/range=8%<10%
    """
    df = _make_ohlc_frame(
        opens=[100, 98, 96],
        highs=[105, 99, 96],
        lows=[95, 95.5, 90],
        closes=[96, 97, 90.5],  # c bearish, body 92% of range, lower wick 8%
    )
    frames = {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
    result = plugin.compute_full(frames)
    assert result.get("belt_hold_bear") == 1.0


def test_kicker_bull_valid():
    """Kicker Bull: pp bearish, c opens above pp_h, c bullish with small upper wick.

    pp: open=100, close=94 (bearish), pp_h=105
    c: open=106 > pp_h=105 (gap), close=111 (bullish)
    body=5, range=6, upper_wick=0.5, 0.5/6=8%<15%
    """
    df = _make_ohlc_frame(
        opens=[100, 94, 106],  # pp bearish; c opens at 106 > pp_h=105
        highs=[105, 98, 111.5],
        lows=[95, 92, 105.5],
        closes=[94, 95, 111],  # c: body=5, range=6, upper_wick=0.5
    )
    frames = {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
    result = plugin.compute_full(frames)
    assert result.get("kicker_bull") == 1.0


def test_kicker_bear_valid():
    """Kicker Bear: pp bullish, c opens below pp_l, c bearish with small lower wick.

    pp: open=100, close=106 (bullish), pp_l=95
    c: open=93 < pp_l=95 (gap down), close=88 (bearish)
    body=5, range=7, lower_wick=1, 1/7=14%<15%
    """
    df = _make_ohlc_frame(
        opens=[100, 106, 93],  # pp bullish; c opens at 93 < pp_l=95
        highs=[108, 108, 94],
        lows=[95, 100, 87],
        closes=[106, 105, 88],  # c: body=5, range=7, lower_wick=1
    )
    frames = {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
    result = plugin.compute_full(frames)
    assert result.get("kicker_bear") == 1.0


def test_all_patterns_zero_with_insufficient_bars():
    """All patterns return 0.0 with fewer than 3 bars."""
    df = _make_ohlc_frame([100], [105], [95], [104])
    frames = {
        "main": df,
        "i1": {"atr_14": 5.0},
        "i2": {"atr_14": 5.0},
        "i3": {"atr_14": 5.0},
        "i4": {"atr_14": 5.0},
        "i5": {"atr_14": 5.0},
        "smc": {"atr_14": 5.0},
        "i6": {"atr_14": 5.0},
    }
    result = plugin.compute_full(frames)
    new_patterns = [
        "harami_bull",
        "harami_bear",
        "abandoned_baby_bull",
        "abandoned_baby_bear",
        "tweezer_top",
        "tweezer_bottom",
        "belt_hold_bull",
        "belt_hold_bear",
        "kicker_bull",
        "kicker_bear",
    ]
    for pattern in new_patterns:
        assert result.get(pattern, 0.0) == 0.0


def test_outputs_frozenset_contains_all_new_fields():
    """Plugin outputs frozenset must include all 10 new pattern field names."""
    new_fields = {
        "harami_bull",
        "harami_bear",
        "abandoned_baby_bull",
        "abandoned_baby_bear",
        "tweezer_top",
        "tweezer_bottom",
        "belt_hold_bull",
        "belt_hold_bear",
        "kicker_bull",
        "kicker_bear",
    }
    missing = new_fields - plugin.outputs
    assert not missing, f"Missing from outputs frozenset: {missing}"
