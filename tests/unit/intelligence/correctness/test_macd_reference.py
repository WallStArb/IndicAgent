"""Reference-validation tests for MACDPlugin against pandas-ta.

Tolerance contract:
- MACD uses standard EMA with span convention (alpha=2/(N+1)).
- Both use adjust=False. pandas-ta MACD EMA seeding differs from our EMA seeding
  (pandas ewm first-value init vs pandas-ta's), so warmup_bars=200 is required
  before agreement reaches atol=1e-4.
- Directional agreement >= 99.9%.
"""

from __future__ import annotations

import pandas as pd
import pytest

pandas_ta = pytest.importorskip("pandas_ta")

from src.intelligence.features.i1_indicators.macd import MACDPlugin
from tests.unit.intelligence.correctness.conftest import (
    assert_close_to_reference,
    frames_from_ohlcv,
)


class TestMACDReference:
    """Validate MACDPlugin output against pandas-ta reference implementation.

    Both implementations use EMA with span=N (alpha=2/(N+1)) for fast/slow and
    span=9 for signal. Seeding differences require warmup_bars=200 for atol=1e-4.
    """

    def _collect_macd_series(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
        """Drive MACDPlugin.compute_full and return (macd, signal, histogram) series."""
        plugin = MACDPlugin()
        macd_vals: dict = {}
        sig_vals: dict = {}
        hist_vals: dict = {}
        for i in range(1, len(df) + 1):
            window = df.iloc[:i]
            result = plugin.compute_full(frames_from_ohlcv(window))
            if "macd_12_26_9" in result:
                macd_vals[df.index[i - 1]] = result["macd_12_26_9"]
                sig_vals[df.index[i - 1]] = result["macd_signal_12_26_9"]
                hist_vals[df.index[i - 1]] = result["macd_histogram_12_26_9"]
        return (
            pd.Series(macd_vals, name="macd"),
            pd.Series(sig_vals, name="macd_signal"),
            pd.Series(hist_vals, name="macd_histogram"),
        )

    def test_macd_matches_pandas_ta_on_trending(
        self, synthetic_ohlcv_trending: pd.DataFrame
    ) -> None:
        """MACD line/signal/histogram match pandas-ta on 500-bar trending data.

        warmup_bars=200 allows EMA seeding differences to decay to atol=1e-4.
        """
        df = synthetic_ohlcv_trending
        ours_macd, ours_sig, ours_hist = self._collect_macd_series(df)

        ref = pandas_ta.macd(df["close"], fast=12, slow=26, signal=9, talib=False)
        ref_macd = pd.Series(ref["MACD_12_26_9"].values, index=df.index)
        ref_sig = pd.Series(ref["MACDs_12_26_9"].values, index=df.index)
        ref_hist = pd.Series(ref["MACDh_12_26_9"].values, index=df.index)

        assert_close_to_reference(
            ours_macd,
            ref_macd,
            atol=1e-4,
            directional_min=0.999,
            warmup_bars=200,
            name="macd_line",
        )
        assert_close_to_reference(
            ours_sig,
            ref_sig,
            atol=1e-4,
            directional_min=0.999,
            warmup_bars=200,
            name="macd_signal",
        )
        assert_close_to_reference(
            ours_hist,
            ref_hist,
            atol=1e-4,
            directional_min=0.999,
            warmup_bars=200,
            name="macd_histogram",
        )

    def test_macd_matches_pandas_ta_on_ranging(self, synthetic_ohlcv_ranging: pd.DataFrame) -> None:
        """MACD line/signal/histogram match pandas-ta on 500-bar ranging data."""
        df = synthetic_ohlcv_ranging
        ours_macd, ours_sig, ours_hist = self._collect_macd_series(df)

        ref = pandas_ta.macd(df["close"], fast=12, slow=26, signal=9, talib=False)
        ref_macd = pd.Series(ref["MACD_12_26_9"].values, index=df.index)
        ref_sig = pd.Series(ref["MACDs_12_26_9"].values, index=df.index)
        ref_hist = pd.Series(ref["MACDh_12_26_9"].values, index=df.index)

        assert_close_to_reference(
            ours_macd,
            ref_macd,
            atol=1e-4,
            directional_min=0.999,
            warmup_bars=200,
            name="macd_line",
        )
        assert_close_to_reference(
            ours_sig,
            ref_sig,
            atol=1e-4,
            directional_min=0.999,
            warmup_bars=200,
            name="macd_signal",
        )
        assert_close_to_reference(
            ours_hist,
            ref_hist,
            atol=1e-4,
            directional_min=0.999,
            warmup_bars=200,
            name="macd_histogram",
        )
