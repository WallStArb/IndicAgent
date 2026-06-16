"""Reference-validation tests for RSIPlugin against pandas-ta.

Tolerance contract:
- RSI uses Wilder's smoothing (alpha=1/N). pandas-ta RSI also uses Wilder's RMA,
  but with a different seeding (pure ewm from first diff vs our SMA-seed approach).
- The seeding difference decays exponentially. After warmup_bars=250, atol=1e-6.
- RSI must remain within [0, 100] at all times.
"""

from __future__ import annotations

import pandas as pd
import pytest

pandas_ta = pytest.importorskip("pandas_ta")

from src.intelligence.features.i1_indicators.rsi import RSIPlugin
from tests.unit.intelligence.correctness.conftest import (
    assert_close_to_reference,
    frames_from_ohlcv,
)


class TestRSIReference:
    """Validate RSIPlugin output against pandas-ta reference implementation.

    Both use Wilder's smoothing (alpha=1/14) for gain/loss averaging. They differ
    in seeding: our code seeds with SMA(first 14 gains/losses), while pandas-ta
    uses pure ewm(alpha=1/14) from the first diff. Seeding difference decays to
    atol=1e-6 after approximately 237 bars (trending fixture).
    """

    def _collect_rsi_series(self, df: pd.DataFrame) -> pd.Series:
        """Drive RSIPlugin.compute_full over the full window and return rsi_14 series."""
        plugin = RSIPlugin()
        values: dict = {}
        for i in range(1, len(df) + 1):
            window = df.iloc[:i]
            result = plugin.compute_full(frames_from_ohlcv(window))
            if "rsi_14" in result:
                values[df.index[i - 1]] = result["rsi_14"]
        return pd.Series(values, name="rsi_14")

    def test_rsi_matches_pandas_ta_on_trending(
        self, synthetic_ohlcv_trending: pd.DataFrame
    ) -> None:
        """RSI matches pandas-ta RMA-based RSI on 500-bar trending data.

        warmup_bars=250 clears the SMA-seed vs pure-ewm seeding difference.
        The 500-bar fixture leaves 250 valid comparison bars.
        """
        df = synthetic_ohlcv_trending
        ours = self._collect_rsi_series(df)

        reference = pd.Series(
            pandas_ta.rsi(df["close"], length=14, talib=False).values,
            index=df.index,
            name="rsi_ref",
        )

        assert_close_to_reference(
            ours,
            reference,
            atol=1e-6,
            directional_min=0.999,
            warmup_bars=250,
            name="rsi",
        )

    def test_rsi_matches_pandas_ta_on_ranging(self, synthetic_ohlcv_ranging: pd.DataFrame) -> None:
        """RSI matches pandas-ta RMA-based RSI on 500-bar ranging data."""
        df = synthetic_ohlcv_ranging
        ours = self._collect_rsi_series(df)

        reference = pd.Series(
            pandas_ta.rsi(df["close"], length=14, talib=False).values,
            index=df.index,
            name="rsi_ref",
        )

        assert_close_to_reference(
            ours,
            reference,
            atol=1e-6,
            directional_min=0.999,
            warmup_bars=250,
            name="rsi",
        )

    def test_rsi_output_range(self, synthetic_ohlcv_trending: pd.DataFrame) -> None:
        """RSI values must remain within [0, 100] on all valid bars."""
        df = synthetic_ohlcv_trending
        ours = self._collect_rsi_series(df)
        valid = ours.dropna()
        assert (valid >= 0 - 1e-9).all(), f"RSI below 0: min={float(valid.min()):.4f}"
        assert (valid <= 100 + 1e-9).all(), f"RSI above 100: max={float(valid.max()):.4f}"
