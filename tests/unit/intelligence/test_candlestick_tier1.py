"""
Tests for CandlestickPatternsPlugin — Tier 1 three-bar patterns.

TDD RED phase: these tests assert that 10 new output fields exist and fire
correctly. They will FAIL until Task 2 extends the plugin.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.intelligence.archive.i5_patterns.candlestick_patterns import CandlestickPatternsPlugin

# ---------------------------------------------------------------------------
# DataFrame helpers — build synthetic 3-bar sequences
# ---------------------------------------------------------------------------


def _frames(bars: list[dict]) -> dict:
    """Wrap list-of-bar-dicts into the frames dict expected by compute_full."""
    return {
        "main": pd.DataFrame(bars),
        "i1": {},
        "i2": {},
        "i3": {},
        "i4": {},
        "i5": {},
        "smc": {},
        "i6": {},
    }


def _three_white_soldiers(base: float = 100.0) -> dict:
    """Canonical Three White Soldiers: 3 consecutive bullish bars opening inside prior body."""
    return _frames(
        [
            # pp: strong bullish, upper wick < 0.25 * body
            {
                "open": base,
                "high": base + 2.0,
                "low": base - 0.2,
                "close": base + 1.8,
                "volume": 1000,
            },
            # p: opens within pp body, closes near high
            {
                "open": base + 1.5,
                "high": base + 3.8,
                "low": base + 1.3,
                "close": base + 3.5,
                "volume": 1200,
            },
            # c: opens within p body, closes near high
            {
                "open": base + 3.2,
                "high": base + 5.8,
                "low": base + 3.0,
                "close": base + 5.5,
                "volume": 1100,
            },
        ]
    )


def _three_black_crows(base: float = 110.0) -> dict:
    """Canonical Three Black Crows: mirror of Three White Soldiers."""
    return _frames(
        [
            # pp: strong bearish, lower wick < 0.25 * body
            {
                "open": base,
                "high": base + 0.2,
                "low": base - 2.0,
                "close": base - 1.8,
                "volume": 1000,
            },
            # p: opens within pp body (between pp_c and pp_o), closes near low
            {
                "open": base - 1.5,
                "high": base - 1.3,
                "low": base - 3.8,
                "close": base - 3.5,
                "volume": 1200,
            },
            # c: opens within p body, closes near low
            {
                "open": base - 3.2,
                "high": base - 3.0,
                "low": base - 5.8,
                "close": base - 5.5,
                "volume": 1100,
            },
        ]
    )


def _morning_star(base: float = 100.0) -> dict:
    """Morning Star: large bearish + doji/indecision star + large bullish above pp midpoint."""
    return _frames(
        [
            # pp: large bearish bar, body > 0.6 * range
            {
                "open": base + 5.0,
                "high": base + 5.2,
                "low": base + 0.1,
                "close": base + 0.5,
                "volume": 1000,
            },
            # p: small body (star), body < 0.3 * range
            {
                "open": base + 0.4,
                "high": base + 1.0,
                "low": base - 0.5,
                "close": base + 0.5,
                "volume": 800,
            },
            # c: large bullish, c_c > (pp_o + pp_c) / 2 = (base+5 + base+0.5)/2 = base+2.75
            {
                "open": base + 0.6,
                "high": base + 4.0,
                "low": base + 0.3,
                "close": base + 3.5,
                "volume": 1200,
            },
        ]
    )


def _evening_star(base: float = 100.0) -> dict:
    """Evening Star: large bullish + doji/indecision star + large bearish below pp midpoint."""
    return _frames(
        [
            # pp: large bullish bar, body > 0.6 * range
            {
                "open": base,
                "high": base + 5.1,
                "low": base - 0.1,
                "close": base + 4.8,
                "volume": 1000,
            },
            # p: small body (star), body < 0.3 * range
            {
                "open": base + 4.9,
                "high": base + 5.5,
                "low": base + 4.1,
                "close": base + 5.0,
                "volume": 800,
            },
            # c: large bearish, c_c < (pp_o + pp_c) / 2 = (base + base+4.8)/2 = base+2.4
            {
                "open": base + 4.7,
                "high": base + 4.8,
                "low": base + 0.3,
                "close": base + 1.5,
                "volume": 1200,
            },
        ]
    )


def _three_inside_up(base: float = 100.0) -> dict:
    """Three Inside Up: large bearish → harami (bullish inside) → close above pp_open."""
    return _frames(
        [
            # pp: large bearish, body > 0.5 * range
            {
                "open": base + 4.0,
                "high": base + 4.2,
                "low": base - 0.2,
                "close": base + 0.2,
                "volume": 1000,
            },
            # p: bullish, body inside pp body (p_o > pp_c, p_c < pp_o, p_c > p_o)
            # pp_c = base+0.2, pp_o = base+4.0
            # p_o > pp_c => p_o > base+0.2  ✓  (base+0.8)
            # p_c < pp_o => p_c < base+4.0  ✓  (base+2.5)
            # p_c > p_o  ✓  (base+2.5 > base+0.8)
            {
                "open": base + 0.8,
                "high": base + 2.8,
                "low": base + 0.5,
                "close": base + 2.5,
                "volume": 900,
            },
            # c: bullish, c_c > pp_o (base+4.0)
            {
                "open": base + 2.6,
                "high": base + 4.8,
                "low": base + 2.4,
                "close": base + 4.5,
                "volume": 1100,
            },
        ]
    )


def _three_inside_down(base: float = 100.0) -> dict:
    """Three Inside Down: large bullish → bearish harami inside → close below pp_open."""
    return _frames(
        [
            # pp: large bullish, body > 0.5 * range
            {
                "open": base,
                "high": base + 4.2,
                "low": base - 0.2,
                "close": base + 4.0,
                "volume": 1000,
            },
            # p: bearish, body inside pp body (p_o < pp_c, p_c > pp_o, p_c < p_o)
            # pp_c = base+4.0, pp_o = base
            # p_o < pp_c => p_o < base+4.0  ✓  (base+3.0)
            # p_c > pp_o => p_c > base  ✓    (base+1.5)
            # p_c < p_o  ✓  (base+1.5 < base+3.0)
            {
                "open": base + 3.0,
                "high": base + 3.3,
                "low": base + 1.2,
                "close": base + 1.5,
                "volume": 900,
            },
            # c: bearish, c_c < pp_o (base)
            {
                "open": base + 1.4,
                "high": base + 1.6,
                "low": base - 0.8,
                "close": base - 0.5,
                "volume": 1100,
            },
        ]
    )


def _harami_cross(base: float = 100.0) -> dict:
    """Harami Cross: large body bar followed by doji entirely inside the prior body."""
    return _frames(
        [
            # pp: large bullish, body > 0.6 * range (body=4, range=4.4 → 4/4.4 ≈ 0.91 > 0.6)
            {
                "open": base,
                "high": base + 4.2,
                "low": base - 0.2,
                "close": base + 4.0,
                "volume": 1000,
            },
            # p: doji inside pp body: body/range < 0.10; p_h < pp_c (base+4.0), p_l > pp_o (base)
            # p_open ≈ p_close (doji); body=0.1, range=1.0 → ratio=0.1 (at threshold, use 0.09)
            # Use: open=base+2.0, close=base+2.09, high=base+2.5, low=base+1.5
            # body=0.09, range=1.0 → ratio=0.09 < 0.10  ✓
            # p_h = base+2.5 < base+4.0 ✓; p_l = base+1.5 > base ✓
            {
                "open": base + 2.0,
                "high": base + 2.5,
                "low": base + 1.5,
                "close": base + 2.09,
                "volume": 800,
            },
            # c: not used for harami_cross detection (only pp and p matter)
            {
                "open": base + 2.1,
                "high": base + 2.8,
                "low": base + 1.8,
                "close": base + 2.5,
                "volume": 900,
            },
        ]
    )


def _dark_cloud_cover(base: float = 100.0) -> dict:
    """Dark Cloud Cover: bullish pp, then c opens above pp_high and closes below pp midpoint."""
    pp_o, pp_c = base, base + 4.0
    pp_h = base + 4.2
    # midpoint = (pp_o + pp_c) / 2 = base + 2.0 — used as reference in comments below
    return _frames(
        [
            # pp: bullish bar
            {"open": pp_o, "high": pp_h, "low": base - 0.1, "close": pp_c, "volume": 1000},
            # p (current bar "p" in the 3-bar window — but for dark cloud we only use pp and c)
            # We need a filler bar; dark_cloud_cover uses only pp and current (c).
            # Make p a neutral bar between pp and c.
            {
                "open": base + 4.0,
                "high": base + 4.3,
                "low": base + 3.8,
                "close": base + 4.1,
                "volume": 900,
            },
            # c: gaps above pp_h, closes below midpoint but above pp_o
            # c_o > pp_h (base+4.2) → use base+4.5
            # c_c < midpoint (base+2.0) → use base+1.8
            # c_c > pp_o (base) → base+1.8 > base ✓
            {
                "open": base + 4.5,
                "high": base + 4.6,
                "low": base + 1.6,
                "close": base + 1.8,
                "volume": 1200,
            },
        ]
    )


def _piercing_line(base: float = 100.0) -> dict:
    """Piercing Line: bearish pp, then c opens below pp_low and closes above pp midpoint."""
    pp_o, pp_c = base + 4.0, base
    pp_l = base - 0.2
    # midpoint = (pp_o + pp_c) / 2 = base + 2.0 — used as reference in comments below
    return _frames(
        [
            # pp: bearish bar
            {"open": pp_o, "high": base + 4.2, "low": pp_l, "close": pp_c, "volume": 1000},
            # filler p bar
            {
                "open": base,
                "high": base + 0.3,
                "low": base - 0.4,
                "close": base - 0.1,
                "volume": 900,
            },
            # c: gaps below pp_l, closes above midpoint but below pp_o
            # c_o < pp_l (base-0.2) → use base-0.5
            # c_c > midpoint (base+2.0) → use base+2.2
            # c_c < pp_o (base+4.0) → base+2.2 < base+4.0 ✓
            {
                "open": base - 0.5,
                "high": base + 2.4,
                "low": base - 0.7,
                "close": base + 2.2,
                "volume": 1200,
            },
        ]
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def plugin() -> CandlestickPatternsPlugin:
    return CandlestickPatternsPlugin()


class TestThreeBarTier1Patterns:

    def test_three_white_soldiers(self, plugin: CandlestickPatternsPlugin) -> None:
        result = plugin.compute_full(_three_white_soldiers())
        assert (
            result.get("three_white_soldiers") == 1.0
        ), f"Expected three_white_soldiers=1.0, got {result.get('three_white_soldiers')}"

    def test_three_black_crows(self, plugin: CandlestickPatternsPlugin) -> None:
        result = plugin.compute_full(_three_black_crows())
        assert (
            result.get("three_black_crows") == 1.0
        ), f"Expected three_black_crows=1.0, got {result.get('three_black_crows')}"

    def test_morning_star(self, plugin: CandlestickPatternsPlugin) -> None:
        result = plugin.compute_full(_morning_star())
        assert (
            result.get("morning_star") == 1.0
        ), f"Expected morning_star=1.0, got {result.get('morning_star')}"

    def test_evening_star(self, plugin: CandlestickPatternsPlugin) -> None:
        result = plugin.compute_full(_evening_star())
        assert (
            result.get("evening_star") == 1.0
        ), f"Expected evening_star=1.0, got {result.get('evening_star')}"

    def test_three_inside_up(self, plugin: CandlestickPatternsPlugin) -> None:
        result = plugin.compute_full(_three_inside_up())
        assert (
            result.get("three_inside_up") == 1.0
        ), f"Expected three_inside_up=1.0, got {result.get('three_inside_up')}"

    def test_three_inside_down(self, plugin: CandlestickPatternsPlugin) -> None:
        result = plugin.compute_full(_three_inside_down())
        assert (
            result.get("three_inside_down") == 1.0
        ), f"Expected three_inside_down=1.0, got {result.get('three_inside_down')}"

    def test_harami_cross(self, plugin: CandlestickPatternsPlugin) -> None:
        result = plugin.compute_full(_harami_cross())
        assert (
            result.get("harami_cross") == 1.0
        ), f"Expected harami_cross=1.0, got {result.get('harami_cross')}"

    def test_dark_cloud_cover(self, plugin: CandlestickPatternsPlugin) -> None:
        result = plugin.compute_full(_dark_cloud_cover())
        assert (
            result.get("dark_cloud_cover") == 1.0
        ), f"Expected dark_cloud_cover=1.0, got {result.get('dark_cloud_cover')}"

    def test_piercing_line(self, plugin: CandlestickPatternsPlugin) -> None:
        result = plugin.compute_full(_piercing_line())
        assert (
            result.get("piercing_line") == 1.0
        ), f"Expected piercing_line=1.0, got {result.get('piercing_line')}"


class TestMinLookbackGuard:

    def test_min_lookback_guard(self, plugin: CandlestickPatternsPlugin) -> None:
        """2-bar DataFrame must return {} (not raise IndexError)."""
        two_bar = pd.DataFrame(
            [
                {"open": 100.0, "high": 101.0, "low": 99.5, "close": 100.8, "volume": 1000},
                {"open": 100.9, "high": 102.0, "low": 100.5, "close": 101.5, "volume": 1100},
            ]
        )
        result = plugin.compute_full(
            {"main": two_bar, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        # With min_lookback=3, a 2-bar DF must return empty dict — no IndexError
        assert result == {}, f"Expected empty dict for 2-bar df, got {result}"

    def test_zero_bar_returns_empty(self, plugin: CandlestickPatternsPlugin) -> None:
        """0-bar DataFrame must return {}."""
        empty = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        result = plugin.compute_full(
            {"main": empty, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        assert result == {}

    def test_one_bar_returns_empty(self, plugin: CandlestickPatternsPlugin) -> None:
        """1-bar DataFrame must return {}."""
        one_bar = pd.DataFrame(
            [
                {"open": 100.0, "high": 101.0, "low": 99.5, "close": 100.8, "volume": 1000},
            ]
        )
        result = plugin.compute_full(
            {"main": one_bar, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        assert result == {}


class TestExistingPatternsUnchanged:

    def test_existing_outputs_present_on_3bar_df(self, plugin: CandlestickPatternsPlugin) -> None:
        """All 9 existing outputs are still present in compute_full result on a 3-bar DataFrame."""
        existing_keys = {
            "engulfing_bull",
            "engulfing_bear",
            "pin_bar_bull",
            "pin_bar_bear",
            "hammer_detected",
            "shooting_star_detected",
            "inside_bar",
            "outside_bar",
            "doji_detected",
        }
        # Use three_white_soldiers as a valid 3-bar DataFrame
        result = plugin.compute_full(_three_white_soldiers())
        for key in existing_keys:
            assert key in result, f"Missing existing output key: {key}"

    def test_engulfing_bull_still_fires(self, plugin: CandlestickPatternsPlugin) -> None:
        """Bullish engulfing pattern still detected correctly on 3-bar df."""
        # c (last bar) must be bullish and engulf prior bar; pp is arbitrary
        frames = _frames(
            [
                {
                    "open": 102.0,
                    "high": 102.5,
                    "low": 101.0,
                    "close": 101.5,
                    "volume": 1000,
                },  # pp (filler)
                {
                    "open": 101.0,
                    "high": 101.5,
                    "low": 99.0,
                    "close": 99.5,
                    "volume": 1000,
                },  # p: bearish
                {
                    "open": 98.5,
                    "high": 102.5,
                    "low": 98.0,
                    "close": 102.0,
                    "volume": 2000,
                },  # c: bullish engulf
            ]
        )
        result = plugin.compute_full(frames)
        assert result.get("engulfing_bull") == 1.0

    def test_doji_still_fires(self, plugin: CandlestickPatternsPlugin) -> None:
        """Doji detection unchanged on 3-bar df."""
        frames = _frames(
            [
                {
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.5,
                    "volume": 1000,
                },  # pp filler
                {
                    "open": 100.5,
                    "high": 101.0,
                    "low": 99.5,
                    "close": 100.2,
                    "volume": 1000,
                },  # p filler
                # c: body = 0.05, range = 2.0 → ratio = 0.025 < 0.10 → doji
                {"open": 100.05, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000},
            ]
        )
        result = plugin.compute_full(frames)
        assert result.get("doji_detected") == 1.0


class TestNoPatternOnRandom:

    def test_flat_bars_no_three_bar_pattern(self, plugin: CandlestickPatternsPlugin) -> None:
        """Random flat bars should not trigger any 3-bar pattern."""
        # Three identical bars — no engulfing, no three soldiers/crows, no stars
        frames = _frames(
            [
                {"open": 100.0, "high": 100.5, "low": 99.5, "close": 100.1, "volume": 1000},
                {"open": 100.0, "high": 100.5, "low": 99.5, "close": 100.1, "volume": 1000},
                {"open": 100.0, "high": 100.5, "low": 99.5, "close": 100.1, "volume": 1000},
            ]
        )
        result = plugin.compute_full(frames)
        new_pattern_keys = [
            "three_white_soldiers",
            "three_black_crows",
            "morning_star",
            "evening_star",
            "three_inside_up",
            "three_inside_down",
            "harami_cross",
            "dark_cloud_cover",
            "piercing_line",
        ]
        for key in new_pattern_keys:
            assert (
                result.get(key, 0.0) == 0.0
            ), f"Expected {key}=0.0 for flat bars, got {result.get(key)}"

    def test_outputs_frozenset_contains_all_new_fields(
        self, plugin: CandlestickPatternsPlugin
    ) -> None:
        """Plugin outputs frozenset must include all 10 new field names."""
        new_fields = {
            "three_white_soldiers",
            "three_black_crows",
            "morning_star",
            "evening_star",
            "three_inside_up",
            "three_inside_down",
            "harami_cross",
            "dark_cloud_cover",
            "piercing_line",
        }
        missing = new_fields - plugin.outputs
        assert not missing, f"Missing from outputs frozenset: {missing}"

    def test_min_lookback_is_3(self, plugin: CandlestickPatternsPlugin) -> None:
        """Plugin min_lookback must be 3 after extension."""
        assert plugin.min_lookback == 3, f"Expected min_lookback=3, got {plugin.min_lookback}"
