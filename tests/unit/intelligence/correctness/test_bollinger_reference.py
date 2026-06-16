"""Reference-validation tests for BollingerPlugin against pandas-ta.

Tolerance contract:
- Bollinger uses rolling mean/std with ddof=0. pandas-ta defaults to ddof=1 but
  accepts ddof=0 when called with ddof=0 and talib=False.
- After warmup_bars=20, agreement is at machine-epsilon: atol=1e-6.
"""

from __future__ import annotations

import pandas as pd
import pytest

pandas_ta = pytest.importorskip("pandas_ta")

from src.intelligence.features.i1_indicators.bollinger import BollingerPlugin
from tests.unit.intelligence.correctness.conftest import (
    assert_close_to_reference,
    frames_from_ohlcv,
)


class TestBollingerReference:
    """Validate BollingerPlugin output against pandas-ta reference implementation.

    Key: call pandas-ta bbands with ddof=0 and talib=False to match our population
    standard deviation (not sample std with Bessel's correction).
    """

    def _collect_bollinger_series(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
        """Drive BollingerPlugin.compute_full and return (upper, mid, lower) series."""
        plugin = BollingerPlugin()
        upper_vals: dict = {}
        mid_vals: dict = {}
        lower_vals: dict = {}
        for i in range(1, len(df) + 1):
            window = df.iloc[:i]
            result = plugin.compute_full(frames_from_ohlcv(window))
            if "bb_20_2_upper" in result:
                upper_vals[df.index[i - 1]] = result["bb_20_2_upper"]
                mid_vals[df.index[i - 1]] = result["bb_20_2_mid"]
                lower_vals[df.index[i - 1]] = result["bb_20_2_lower"]
        return (
            pd.Series(upper_vals, name="bb_upper"),
            pd.Series(mid_vals, name="bb_mid"),
            pd.Series(lower_vals, name="bb_lower"),
        )

    def test_bollinger_matches_pandas_ta_on_trending(
        self, synthetic_ohlcv_trending: pd.DataFrame
    ) -> None:
        """Bollinger upper/mid/lower match pandas-ta on 500-bar trending data.

        Calls pandas-ta with ddof=0 and talib=False to match our population
        standard deviation convention. Agreement is machine-epsilon after 20 bars.
        """
        df = synthetic_ohlcv_trending
        ours_upper, ours_mid, ours_lower = self._collect_bollinger_series(df)

        ref = pandas_ta.bbands(df["close"], length=20, std=2.0, ddof=0, talib=False)
        ref_upper = pd.Series(ref["BBU_20_2.0_2.0"].values, index=df.index)
        ref_mid = pd.Series(ref["BBM_20_2.0_2.0"].values, index=df.index)
        ref_lower = pd.Series(ref["BBL_20_2.0_2.0"].values, index=df.index)

        assert_close_to_reference(
            ours_upper,
            ref_upper,
            atol=1e-6,
            directional_min=0.999,
            warmup_bars=20,
            name="bb_upper",
        )
        assert_close_to_reference(
            ours_mid,
            ref_mid,
            atol=1e-6,
            directional_min=0.999,
            warmup_bars=20,
            name="bb_mid",
        )
        assert_close_to_reference(
            ours_lower,
            ref_lower,
            atol=1e-6,
            directional_min=0.999,
            warmup_bars=20,
            name="bb_lower",
        )

    def test_bollinger_matches_pandas_ta_on_ranging(
        self, synthetic_ohlcv_ranging: pd.DataFrame
    ) -> None:
        """Bollinger upper/mid/lower match pandas-ta on 500-bar ranging data."""
        df = synthetic_ohlcv_ranging
        ours_upper, ours_mid, ours_lower = self._collect_bollinger_series(df)

        ref = pandas_ta.bbands(df["close"], length=20, std=2.0, ddof=0, talib=False)
        ref_upper = pd.Series(ref["BBU_20_2.0_2.0"].values, index=df.index)
        ref_mid = pd.Series(ref["BBM_20_2.0_2.0"].values, index=df.index)
        ref_lower = pd.Series(ref["BBL_20_2.0_2.0"].values, index=df.index)

        assert_close_to_reference(
            ours_upper,
            ref_upper,
            atol=1e-6,
            directional_min=0.999,
            warmup_bars=20,
            name="bb_upper",
        )
        assert_close_to_reference(
            ours_mid,
            ref_mid,
            atol=1e-6,
            directional_min=0.999,
            warmup_bars=20,
            name="bb_mid",
        )
        assert_close_to_reference(
            ours_lower,
            ref_lower,
            atol=1e-6,
            directional_min=0.999,
            warmup_bars=20,
            name="bb_lower",
        )

    def test_bollinger_bands_contain_price(self, synthetic_ohlcv_trending: pd.DataFrame) -> None:
        """Upper band >= mid >= lower for all valid bars (band ordering invariant)."""
        df = synthetic_ohlcv_trending
        ours_upper, ours_mid, ours_lower = self._collect_bollinger_series(df)

        valid = ours_upper.notna() & ours_mid.notna() & ours_lower.notna()
        assert (
            ours_upper[valid] >= ours_mid[valid]
        ).all(), "Upper band must be >= mid band on all valid bars"
        assert (
            ours_mid[valid] >= ours_lower[valid]
        ).all(), "Mid band must be >= lower band on all valid bars"

        # Upper/lower are symmetric around mid (both 2.0 std_dev)
        half_width_upper = (ours_upper[valid] - ours_mid[valid]).abs()
        half_width_lower = (ours_mid[valid] - ours_lower[valid]).abs()
        max_asymmetry = float((half_width_upper - half_width_lower).abs().max())
        assert (
            max_asymmetry <= 1e-10
        ), f"Upper/lower bands should be symmetric; max asymmetry={max_asymmetry:.2e}"
