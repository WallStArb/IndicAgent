"""Reference-validation tests for ADXPlugin against pandas-ta.

Tolerance contract:
- ADX uses double Wilder's smoothing (DM and TR each get RMA, then ADX is RMA of DX).
- Both our code and pandas-ta use the same Wilder convention (alpha=1/N), but seeding
  differs (our SMA seed vs pandas-ta's initialization). Seeding difference decays to
  atol=1e-4 after approximately 224 bars; warmup_bars=250 provides safe clearance.
- Directional agreement >= 99.9%.
"""

from __future__ import annotations

import pandas as pd
import pytest

pandas_ta = pytest.importorskip("pandas_ta")

from src.intelligence.features.i1_indicators.adx import ADXPlugin
from tests.unit.intelligence.correctness.conftest import (
    assert_close_to_reference,
    frames_from_ohlcv,
)


class TestADXReference:
    """Validate ADXPlugin output against pandas-ta reference implementation.

    Both implementations use Wilder's smoothing (alpha=1/14) for DM, TR, and DX.
    Double-Wilder seeding differences require warmup_bars=250 for atol=1e-4 convergence.
    """

    def _collect_adx_series(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
        """Drive ADXPlugin.compute_full and return (adx, plus_di, minus_di) series."""
        plugin = ADXPlugin()
        adx_vals: dict = {}
        pdi_vals: dict = {}
        mdi_vals: dict = {}
        for i in range(1, len(df) + 1):
            window = df.iloc[:i]
            result = plugin.compute_full(frames_from_ohlcv(window))
            if "adx_14" in result:
                adx_vals[df.index[i - 1]] = result["adx_14"]
                pdi_vals[df.index[i - 1]] = result["plus_di_14"]
                mdi_vals[df.index[i - 1]] = result["minus_di_14"]
        return (
            pd.Series(adx_vals, name="adx"),
            pd.Series(pdi_vals, name="plus_di"),
            pd.Series(mdi_vals, name="minus_di"),
        )

    def test_adx_matches_pandas_ta_on_trending(
        self, synthetic_ohlcv_trending: pd.DataFrame
    ) -> None:
        """ADX/+DI/-DI match pandas-ta on 500-bar trending data.

        warmup_bars=250 allows double-Wilder seeding differences to decay to atol=1e-4.
        The 500-bar fixture leaves 250 valid comparison bars.
        """
        df = synthetic_ohlcv_trending
        ours_adx, ours_pdi, ours_mdi = self._collect_adx_series(df)

        ref = pandas_ta.adx(df["high"], df["low"], df["close"], length=14, talib=False)
        ref_adx = pd.Series(ref["ADX_14"].values, index=df.index)
        ref_pdi = pd.Series(ref["DMP_14"].values, index=df.index)
        ref_mdi = pd.Series(ref["DMN_14"].values, index=df.index)

        assert_close_to_reference(
            ours_adx,
            ref_adx,
            atol=1e-4,
            directional_min=0.999,
            warmup_bars=250,
            name="adx",
        )
        assert_close_to_reference(
            ours_pdi,
            ref_pdi,
            atol=1e-4,
            directional_min=0.999,
            warmup_bars=250,
            name="plus_di",
        )
        assert_close_to_reference(
            ours_mdi,
            ref_mdi,
            atol=1e-4,
            directional_min=0.999,
            warmup_bars=250,
            name="minus_di",
        )

    def test_adx_matches_pandas_ta_on_ranging(self, synthetic_ohlcv_ranging: pd.DataFrame) -> None:
        """ADX/+DI/-DI match pandas-ta on 500-bar ranging data."""
        df = synthetic_ohlcv_ranging
        ours_adx, ours_pdi, ours_mdi = self._collect_adx_series(df)

        ref = pandas_ta.adx(df["high"], df["low"], df["close"], length=14, talib=False)
        ref_adx = pd.Series(ref["ADX_14"].values, index=df.index)
        ref_pdi = pd.Series(ref["DMP_14"].values, index=df.index)
        ref_mdi = pd.Series(ref["DMN_14"].values, index=df.index)

        assert_close_to_reference(
            ours_adx,
            ref_adx,
            atol=1e-4,
            directional_min=0.999,
            warmup_bars=250,
            name="adx",
        )
        assert_close_to_reference(
            ours_pdi,
            ref_pdi,
            atol=1e-4,
            directional_min=0.999,
            warmup_bars=250,
            name="plus_di",
        )
        assert_close_to_reference(
            ours_mdi,
            ref_mdi,
            atol=1e-4,
            directional_min=0.999,
            warmup_bars=250,
            name="minus_di",
        )
