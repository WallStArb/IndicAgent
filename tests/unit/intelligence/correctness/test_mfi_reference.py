"""Reference-validation tests for MFIPlugin against pandas-ta.

Tolerance contract:
- MFI is a pure rolling calculation (positive/negative money flow sums).
- Agreement is machine-epsilon after warmup_bars=14.
- MFI must remain within [0, 100].
"""

from __future__ import annotations

import pandas as pd
import pytest

pandas_ta = pytest.importorskip("pandas_ta")

from src.intelligence.features.i1_indicators.mfi import MFIPlugin
from tests.unit.intelligence.correctness.conftest import (
    assert_close_to_reference,
    frames_from_ohlcv,
)


class TestMFIReference:
    """Validate MFIPlugin output against pandas-ta reference implementation.

    MFI is a bounded oscillator [0, 100] based on typical-price money flow ratio.
    Both implementations use the same rolling-sum approach, yielding machine-epsilon
    agreement after warmup_bars=14.
    """

    def _collect_mfi_series(self, df: pd.DataFrame) -> pd.Series:
        """Drive MFIPlugin.compute_full over the full window and return mfi_14 series."""
        plugin = MFIPlugin()
        values: dict = {}
        for i in range(1, len(df) + 1):
            window = df.iloc[:i]
            result = plugin.compute_full(frames_from_ohlcv(window))
            if "mfi_14" in result:
                values[df.index[i - 1]] = result["mfi_14"]
        return pd.Series(values, name="mfi_14")

    def test_mfi_matches_pandas_ta_on_trending(
        self, synthetic_ohlcv_trending: pd.DataFrame
    ) -> None:
        """MFI matches pandas-ta on 500-bar trending data at machine-epsilon precision."""
        df = synthetic_ohlcv_trending
        ours = self._collect_mfi_series(df)

        reference = pd.Series(
            pandas_ta.mfi(df["high"], df["low"], df["close"], df["volume"], length=14).values,
            index=df.index,
            name="mfi_ref",
        )

        assert_close_to_reference(
            ours,
            reference,
            atol=1e-6,
            directional_min=0.999,
            warmup_bars=14,
            name="mfi",
        )

    def test_mfi_matches_pandas_ta_on_ranging(self, synthetic_ohlcv_ranging: pd.DataFrame) -> None:
        """MFI matches pandas-ta on 500-bar ranging data."""
        df = synthetic_ohlcv_ranging
        ours = self._collect_mfi_series(df)

        reference = pd.Series(
            pandas_ta.mfi(df["high"], df["low"], df["close"], df["volume"], length=14).values,
            index=df.index,
            name="mfi_ref",
        )

        assert_close_to_reference(
            ours,
            reference,
            atol=1e-6,
            directional_min=0.999,
            warmup_bars=14,
            name="mfi",
        )

    def test_mfi_output_range(self, synthetic_ohlcv_trending: pd.DataFrame) -> None:
        """MFI values must remain within [0, 100] on all valid bars."""
        df = synthetic_ohlcv_trending
        ours = self._collect_mfi_series(df)
        valid = ours.dropna()
        assert (valid >= 0 - 1e-9).all(), f"MFI below 0: min={float(valid.min()):.4f}"
        assert (valid <= 100 + 1e-9).all(), f"MFI above 100: max={float(valid.max()):.4f}"
