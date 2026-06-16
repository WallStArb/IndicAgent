"""Reference-validation tests for StochasticPlugin against pandas-ta.

Tolerance contract:
- Stochastic is a pure rolling calculation (no EWM seeding). Agreement is machine-
  epsilon after warmup_bars=14.
- Our plugin computes raw %K and %D = SMA(raw %K, 3). This matches pandas-ta when
  called with smooth_k=1 (no %K smoothing step before %D).
- Stochastic values must remain within [0, 100].
"""

from __future__ import annotations

import pandas as pd
import pytest

pandas_ta = pytest.importorskip("pandas_ta")

from src.intelligence.features.i1_indicators.stochastic import StochasticPlugin
from tests.unit.intelligence.correctness.conftest import (
    assert_close_to_reference,
    frames_from_ohlcv,
)


class TestStochasticReference:
    """Validate StochasticPlugin output against pandas-ta reference implementation.

    Convention note: our plugin computes fast %K and %D = SMA3(fast %K).
    pandas-ta with smooth_k=1 does the same (no %K smoothing before %D).
    """

    def _collect_stoch_series(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        """Drive StochasticPlugin.compute_full and return (%K, %D) series."""
        plugin = StochasticPlugin()
        k_vals: dict = {}
        d_vals: dict = {}
        for i in range(1, len(df) + 1):
            window = df.iloc[:i]
            result = plugin.compute_full(frames_from_ohlcv(window))
            if "stoch_k_14_3" in result:
                k_vals[df.index[i - 1]] = result["stoch_k_14_3"]
                d_vals[df.index[i - 1]] = result["stoch_d_14_3"]
        return (
            pd.Series(k_vals, name="stoch_k"),
            pd.Series(d_vals, name="stoch_d"),
        )

    def test_stochastic_matches_pandas_ta_on_trending(
        self, synthetic_ohlcv_trending: pd.DataFrame
    ) -> None:
        """Stochastic %K and %D match pandas-ta on 500-bar trending data.

        Uses smooth_k=1 to match our plugin's fast-stochastic computation
        (no intermediate %K smoothing before computing %D).
        """
        df = synthetic_ohlcv_trending
        ours_k, ours_d = self._collect_stoch_series(df)

        # smooth_k=1 means no %K smoothing — matches our raw-K then SMA3 approach
        ref = pandas_ta.stoch(df["high"], df["low"], df["close"], k=14, d=3, smooth_k=1)
        ref_k = pd.Series(ref["STOCHk_14_3_1"].values, index=df.index)
        ref_d = pd.Series(ref["STOCHd_14_3_1"].values, index=df.index)

        assert_close_to_reference(
            ours_k,
            ref_k,
            atol=1e-6,
            directional_min=0.999,
            warmup_bars=14,
            name="stoch_k",
        )
        assert_close_to_reference(
            ours_d,
            ref_d,
            atol=1e-6,
            directional_min=0.999,
            warmup_bars=14,
            name="stoch_d",
        )

    def test_stochastic_matches_pandas_ta_on_ranging(
        self, synthetic_ohlcv_ranging: pd.DataFrame
    ) -> None:
        """Stochastic %K and %D match pandas-ta on 500-bar ranging data."""
        df = synthetic_ohlcv_ranging
        ours_k, ours_d = self._collect_stoch_series(df)

        ref = pandas_ta.stoch(df["high"], df["low"], df["close"], k=14, d=3, smooth_k=1)
        ref_k = pd.Series(ref["STOCHk_14_3_1"].values, index=df.index)
        ref_d = pd.Series(ref["STOCHd_14_3_1"].values, index=df.index)

        assert_close_to_reference(
            ours_k,
            ref_k,
            atol=1e-6,
            directional_min=0.999,
            warmup_bars=14,
            name="stoch_k",
        )
        assert_close_to_reference(
            ours_d,
            ref_d,
            atol=1e-6,
            directional_min=0.999,
            warmup_bars=14,
            name="stoch_d",
        )

    def test_stochastic_output_range(self, synthetic_ohlcv_trending: pd.DataFrame) -> None:
        """Stochastic %K and %D must remain within [0, 100] on all valid bars."""
        df = synthetic_ohlcv_trending
        ours_k, ours_d = self._collect_stoch_series(df)

        k_valid = ours_k.dropna()
        d_valid = ours_d.dropna()

        assert (k_valid >= 0 - 1e-9).all(), f"Stoch %K below 0: min={float(k_valid.min()):.4f}"
        assert (k_valid <= 100 + 1e-9).all(), f"Stoch %K above 100: max={float(k_valid.max()):.4f}"
        assert (d_valid >= 0 - 1e-9).all(), f"Stoch %D below 0: min={float(d_valid.min()):.4f}"
        assert (d_valid <= 100 + 1e-9).all(), f"Stoch %D above 100: max={float(d_valid.max()):.4f}"
