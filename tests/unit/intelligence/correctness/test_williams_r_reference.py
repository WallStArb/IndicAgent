"""Reference-validation tests for WilliamsRPlugin against pandas-ta.

Tolerance contract:
- Williams %R is a pure rolling calculation (rolling high/low window).
  Agreement is machine-epsilon after warmup_bars=14.

Sign convention:
- pandas-ta willr() returns values in [-100, 0] (negative: overbought at 0,
  oversold at -100). Our WilliamsRPlugin also uses this convention: -100*(HH-C)/(HH-LL).
- No sign inversion is needed between our plugin and pandas-ta.
"""

from __future__ import annotations

import pandas as pd
import pytest

pandas_ta = pytest.importorskip("pandas_ta")

from src.intelligence.features.i1_indicators.williams_r import WilliamsRPlugin
from tests.unit.intelligence.correctness.conftest import (
    assert_close_to_reference,
    frames_from_ohlcv,
)


class TestWilliamsRReference:
    """Validate WilliamsRPlugin output against pandas-ta willr() reference.

    Sign convention: both our plugin and pandas-ta return values in [-100, 0].
    Our implementation: willr = -100 * (HH - close) / (HH - LL)
    pandas-ta: same formula, same sign convention.
    No adjustment needed between the two.
    """

    def _collect_wr_series(self, df: pd.DataFrame) -> pd.Series:
        """Drive WilliamsRPlugin.compute_full and return williams_r_14 series."""
        plugin = WilliamsRPlugin()
        values: dict = {}
        for i in range(1, len(df) + 1):
            window = df.iloc[:i]
            result = plugin.compute_full(frames_from_ohlcv(window))
            if "williams_r_14" in result:
                values[df.index[i - 1]] = result["williams_r_14"]
        return pd.Series(values, name="williams_r_14")

    def test_williams_r_matches_pandas_ta_on_trending(
        self, synthetic_ohlcv_trending: pd.DataFrame
    ) -> None:
        """Williams %R matches pandas-ta willr on 500-bar trending data.

        Both use the convention [-100, 0]: -100*(HH-close)/(HH-LL).
        Agreement is machine-epsilon after warmup_bars=14 (pure rolling).
        """
        df = synthetic_ohlcv_trending
        ours = self._collect_wr_series(df)

        reference = pd.Series(
            pandas_ta.willr(df["high"], df["low"], df["close"], length=14).values,
            index=df.index,
            name="wr_ref",
        )

        assert_close_to_reference(
            ours,
            reference,
            atol=1e-6,
            directional_min=0.999,
            warmup_bars=14,
            name="williams_r",
        )

    def test_williams_r_matches_pandas_ta_on_ranging(
        self, synthetic_ohlcv_ranging: pd.DataFrame
    ) -> None:
        """Williams %R matches pandas-ta willr on 500-bar ranging data."""
        df = synthetic_ohlcv_ranging
        ours = self._collect_wr_series(df)

        reference = pd.Series(
            pandas_ta.willr(df["high"], df["low"], df["close"], length=14).values,
            index=df.index,
            name="wr_ref",
        )

        assert_close_to_reference(
            ours,
            reference,
            atol=1e-6,
            directional_min=0.999,
            warmup_bars=14,
            name="williams_r",
        )

    def test_williams_r_output_range_negative(self, synthetic_ohlcv_trending: pd.DataFrame) -> None:
        """Williams %R must remain within [-100, 0] on all valid bars.

        Convention: [-100, 0] where 0 = close at highest high (overbought),
        -100 = close at lowest low (oversold). Values outside this range
        indicate a calculation error.
        """
        df = synthetic_ohlcv_trending
        ours = self._collect_wr_series(df)
        valid = ours.dropna()
        assert (valid >= -100 - 1e-9).all(), f"WilliamsR below -100: min={float(valid.min()):.4f}"
        assert (valid <= 0 + 1e-9).all(), f"WilliamsR above 0: max={float(valid.max()):.4f}"
