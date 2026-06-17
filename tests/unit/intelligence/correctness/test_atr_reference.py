"""Reference-validation tests for ATRPlugin against pandas-ta.

Tolerance contract (from 093-ATR-WILDER-INVESTIGATION.md):
- Both our code and pandas-ta use alpha=1/N (Wilder's definition), adjust=False.
- However, seeding differs: pandas-ta uses presma=True (SMA seed at bar N-1);
  our code uses pandas ewm's internal min_periods=N initialization.
- The seeding difference decays exponentially. After warmup_bars=150, error < 1e-6.
  (warmup_bars=28 only achieves atol=1e-3 — insufficient for the 1e-6 target.)
- Directional agreement >= 99.9% on non-flat data.

See: .planning/phases/093-mathematical-correctness-audit/093-ATR-WILDER-INVESTIGATION.md
"""

from __future__ import annotations

import pandas as pd
import pytest

pandas_ta = pytest.importorskip("pandas_ta", reason="pandas-ta not installed (test-only oracle)")

from src.intelligence.features.i1_indicators.atr import ATRPlugin
from tests.unit.intelligence.correctness.conftest import (
    assert_close_to_reference,
    frames_from_ohlcv,
)


class TestATRReference:
    """Validate ATRPlugin output against pandas-ta reference implementation.

    Both implementations use Wilder's RMA convention (alpha=1/N, adjust=False).
    They differ only in the seeding of the first N bars (pandas-ta uses presma=True
    SMA seed; our code uses pandas ewm's min_periods=N default). After 150 bars of
    warmup the seeding difference decays below 1e-6 on all tested data shapes.
    """

    def _collect_atr_series(self, df: pd.DataFrame) -> pd.Series:
        """Drive ATRPlugin.compute_full over the full window and return atr_14 series."""
        plugin = ATRPlugin()
        values = {}
        for i in range(1, len(df) + 1):
            window = df.iloc[:i]
            result = plugin.compute_full(frames_from_ohlcv(window))
            if "atr_14" in result:
                values[df.index[i - 1]] = result["atr_14"]
        return pd.Series(values, name="atr_14")

    def test_atr_matches_pandas_ta_on_trending(
        self, synthetic_ohlcv_trending: pd.DataFrame
    ) -> None:
        """ATR matches pandas-ta RMA-based ATR on 500-bar upward-trending data.

        warmup_bars=150 clears the presma-vs-ewm seeding difference (see investigation
        doc). After 150 bars, agreement is at floating-point precision: atol=1e-6.
        The 500-bar fixture leaves 350 valid comparison bars.
        """
        df = synthetic_ohlcv_trending

        ours = self._collect_atr_series(df)

        reference = pd.Series(
            pandas_ta.atr(df["high"], df["low"], df["close"], length=14).values,
            index=df.index,
            name="atr_ref",
        )

        assert_close_to_reference(
            ours,
            reference,
            atol=1e-6,
            directional_min=0.999,
            warmup_bars=150,
            name="atr",
        )

    def test_atr_matches_pandas_ta_on_ranging(self, synthetic_ohlcv_ranging: pd.DataFrame) -> None:
        """ATR matches pandas-ta RMA-based ATR on 500-bar mean-reverting (ranging) data.

        warmup_bars=150 clears the presma-vs-ewm seeding difference (see investigation
        doc). Ranging data converges slightly later than trending (bar ~128 vs ~101).
        """
        df = synthetic_ohlcv_ranging

        ours = self._collect_atr_series(df)

        reference = pd.Series(
            pandas_ta.atr(df["high"], df["low"], df["close"], length=14).values,
            index=df.index,
            name="atr_ref",
        )

        assert_close_to_reference(
            ours,
            reference,
            atol=1e-6,
            directional_min=0.999,
            warmup_bars=150,
            name="atr",
        )

    def test_atr_incremental_matches_full(self, synthetic_ohlcv_trending: pd.DataFrame) -> None:
        """Incremental compute_next is numerically equivalent to compute_full at atol=1e-9.

        This is a self-consistency test (same code, two paths), so the tighter 1e-9
        tolerance is appropriate — floating-point arithmetic should be identical.

        Protocol:
        1. compute_full on bars [0:100] to get initial state.
        2. compute_next bar-by-bar for bars [100:200] threading state through.
        3. compute_full on bars [0:200] for ground truth.
        4. Compare final atr_14 values at bars 100-199.
        """
        df = synthetic_ohlcv_trending
        plugin = ATRPlugin()

        # Step 1: seed state from first 100 bars
        seed_result = plugin.compute_full(frames_from_ohlcv(df.iloc[:100]))
        state = seed_result.get("_state", {})
        assert state, "compute_full must return _state after 100 bars"

        # Step 2: incremental path for bars 100..199
        incremental_values = {}
        for i in range(100, 200):
            window = df.iloc[: i + 1]
            result = plugin.compute_next(frames_from_ohlcv(window), state=state)
            state = result.get("_state", state)
            if "atr_14" in result:
                incremental_values[df.index[i]] = result["atr_14"]

        # Step 3: full recompute on bars [0:200]
        full_values = {}
        for i in range(100, 200):
            window = df.iloc[: i + 1]
            result = plugin.compute_full(frames_from_ohlcv(window))
            if "atr_14" in result:
                full_values[df.index[i]] = result["atr_14"]

        assert len(incremental_values) > 0, "incremental path produced no values"
        assert len(full_values) > 0, "full recompute produced no values"

        incremental_series = pd.Series(incremental_values, name="incremental")
        full_series = pd.Series(full_values, name="full")

        assert_close_to_reference(
            incremental_series,
            full_series,
            atol=1e-9,
            directional_min=0.999,
            warmup_bars=0,
            name="atr_incremental_vs_full",
        )
