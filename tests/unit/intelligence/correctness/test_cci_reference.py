"""Reference-validation tests for CCIPlugin against a direct reference implementation.

Tolerance contract:
- CCI is a pure rolling calculation (typical price, SMA, MAD with constant 0.015).
  Agreement is machine-epsilon after warmup_bars=20.

Note on pandas-ta CCI: pandas-ta 0.3.14b+ has a formula bug where `cci` computes
`tp - mean_tp / (c * mad)` instead of `(tp - mean_tp) / (c * mad)`. The operator
precedence is wrong — it should be `(tp - mean_tp) / (c * mad)`. Because of this
bug, pandas-ta CCI cannot be used as a reference. Instead, this test uses a direct
Python implementation of the Lambert CCI formula as the reference.

Reference: Lambert (1980) CCI formula is:
    TP = (High + Low + Close) / 3
    Mean_TP = SMA(TP, period)
    MAD = mean(|TP_i - Mean_TP| for i in window)
    CCI = (TP - Mean_TP) / (0.015 * MAD)

CCI is unbounded and should be zero when price is at the rolling mean.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.intelligence.features.i1_indicators.cci import CCIPlugin
from tests.unit.intelligence.correctness.conftest import (
    assert_close_to_reference,
    frames_from_ohlcv,
)


def _reference_cci(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Direct Lambert CCI implementation as reference.

    This is the ground-truth formula: (TP - SMA(TP,N)) / (0.015 * MAD(TP,N))
    where MAD is the mean absolute deviation of TP within the rolling window.
    """
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    mean_tp = tp.rolling(window=period, min_periods=period).mean()
    mad = tp.rolling(window=period, min_periods=period).apply(
        lambda x: float(np.abs(x - x.mean()).mean()), raw=True
    )
    # Avoid division by zero at constant price (MAD=0 -> CCI=0)
    denom = 0.015 * mad
    cci = (tp - mean_tp) / denom
    cci = cci.where(denom != 0, 0.0)
    return cci


class TestCCIReference:
    """Validate CCIPlugin output against direct Lambert CCI reference implementation.

    Uses period=20 to produce cci_20 output (matches plan requirement).
    Agreement is machine-epsilon after warmup_bars=20 (pure rolling, no EWM).

    Note: pandas-ta cci() has a formula bug (wrong operator precedence) and cannot
    be used as the reference. The direct Python implementation below is the ground truth.
    """

    def _collect_cci_series(self, df: pd.DataFrame) -> pd.Series:
        """Drive CCIPlugin(periods=[20]).compute_full and return cci_20 series."""
        plugin = CCIPlugin(periods=[20])
        values: dict = {}
        for i in range(1, len(df) + 1):
            window = df.iloc[:i]
            result = plugin.compute_full(frames_from_ohlcv(window))
            if "cci_20" in result:
                values[df.index[i - 1]] = result["cci_20"]
        return pd.Series(values, name="cci_20")

    def test_cci_matches_reference_on_trending(
        self, synthetic_ohlcv_trending: pd.DataFrame
    ) -> None:
        """CCI(20) matches direct Lambert formula on 500-bar trending data.

        warmup_bars=20 is the rolling period. Agreement is machine-epsilon
        (both use identical pure-Python rolling computation).
        """
        df = synthetic_ohlcv_trending
        ours = self._collect_cci_series(df)
        reference = _reference_cci(df, period=20)

        assert_close_to_reference(
            ours,
            reference,
            atol=1e-6,
            directional_min=0.999,
            warmup_bars=20,
            name="cci",
        )

    def test_cci_matches_reference_on_ranging(self, synthetic_ohlcv_ranging: pd.DataFrame) -> None:
        """CCI(20) matches direct Lambert formula on 500-bar ranging data."""
        df = synthetic_ohlcv_ranging
        ours = self._collect_cci_series(df)
        reference = _reference_cci(df, period=20)

        assert_close_to_reference(
            ours,
            reference,
            atol=1e-6,
            directional_min=0.999,
            warmup_bars=20,
            name="cci",
        )

    def test_cci_zero_at_mean(self, synthetic_ohlcv_flat: pd.DataFrame) -> None:
        """CCI is zero on flat-price data (price equals rolling mean at all times)."""
        df = synthetic_ohlcv_flat
        plugin = CCIPlugin(periods=[20])
        values: dict = {}
        for i in range(1, len(df) + 1):
            window = df.iloc[:i]
            result = plugin.compute_full(frames_from_ohlcv(window))
            if "cci_20" in result:
                values[df.index[i - 1]] = result["cci_20"]
        ours = pd.Series(values, name="cci_20")
        valid = ours.dropna()
        assert (
            valid.abs() < 1e-9
        ).all(), f"CCI should be zero on flat data; max={float(valid.abs().max()):.2e}"
