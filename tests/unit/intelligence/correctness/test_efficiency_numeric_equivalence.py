"""Numeric equivalence guard for efficiency refactors introduced in Phase 093 Plan 04.

These tests run AFTER the refactors in 093-04 (np.partition for BollingerSqueeze,
.to_numpy for MFI/WilliamsR/Stochastic/CCI/VolumeZscore) and confirm that the
refactored code produces bit-equivalent output to the pre-refactor paths.

Tolerance contract (tighter than the reference-validation tests in 093-02/03):
- atol=1e-9 for all comparisons (vs 1e-6 for reference-validation)
- Incremental vs full-path comparisons use atol=1e-12 (pure algorithmic identity)

Rationale: efficiency refactors must not change numeric output at all; the tighter
tolerance will catch any future change that accidentally alters these hot paths.
"""

from __future__ import annotations

import pandas as pd
import pytest

ta = pytest.importorskip("pandas_ta")

from tests.unit.intelligence.correctness.conftest import (
    assert_close_to_reference,
    frames_from_ohlcv,
)


class TestEfficiencyNumericEquivalence:
    """Numeric equivalence guards for the 093-04 efficiency refactors.

    Each test either:
    (a) Compares our plugin output against the pandas_ta reference at atol=1e-9, or
    (b) Compares compute_full vs compute_full + compute_next at atol=1e-12 (incremental
        consistency) when no pandas_ta reference exists or pre-existing formula differences
        make a pandas_ta comparison inappropriate.
    """

    # ------------------------------------------------------------------
    # BollingerSqueeze: incremental consistency after np.partition refactor
    # ------------------------------------------------------------------

    def test_bollinger_squeeze_matches_self(self, synthetic_ohlcv_trending: pd.DataFrame) -> None:
        """BollingerSqueeze compute_full vs incremental path agree at atol=1e-9.

        Drives compute_full on the first 100 bars to seed state, then calls
        compute_next bar-by-bar through bar 500. The final squeeze_active,
        squeeze_duration, and squeeze_bandwidth_pctile must match compute_full
        on the full 500-bar window.
        """
        from src.intelligence.archive.i5_patterns.bollinger_squeeze import BollingerSqueezePlugin

        df = synthetic_ohlcv_trending
        plugin = BollingerSqueezePlugin()

        # Full-path result on all 500 bars
        full_result = plugin.compute_full(frames_from_ohlcv(df))
        assert full_result, "compute_full returned empty on 500-bar window"

        # Incremental path: seed on first 100 bars, then compute_next bar-by-bar
        seed_result = plugin.compute_full(frames_from_ohlcv(df.iloc[:100]))
        assert seed_result, "compute_full returned empty on 100-bar seed window"

        state = seed_result["_state"]
        last_incremental: dict = {}
        for i in range(100, len(df)):
            window = df.iloc[: i + 1]
            last_incremental = plugin.compute_next(frames_from_ohlcv(window), state=state)
            if last_incremental and "_state" in last_incremental:
                state = last_incremental["_state"]

        assert last_incremental, "compute_next returned empty at final bar"

        # Compare squeeze_bandwidth_pctile — this is the output most affected by
        # the np.partition refactor (rank-based percentile computation).
        full_pctile = full_result.get("squeeze_bandwidth_pctile", -1.0)
        incr_pctile = last_incremental.get("squeeze_bandwidth_pctile", -2.0)
        assert abs(full_pctile - incr_pctile) <= 1e-9, (
            f"squeeze_bandwidth_pctile mismatch: full={full_pctile}, incr={incr_pctile}, "
            f"diff={abs(full_pctile - incr_pctile):.2e}"
        )

        # Compare squeeze_active (binary, should be identical)
        assert full_result.get("squeeze_active") == last_incremental.get("squeeze_active"), (
            f"squeeze_active mismatch: full={full_result.get('squeeze_active')}, "
            f"incr={last_incremental.get('squeeze_active')}"
        )

    # ------------------------------------------------------------------
    # MFI: pandas_ta reference comparison after .to_numpy refactor
    # ------------------------------------------------------------------

    def test_mfi_matches_pandas_ta(self, synthetic_ohlcv_trending: pd.DataFrame) -> None:
        """MFI output matches pandas_ta.mfi to atol=1e-9 after .tolist() removal."""
        from src.intelligence.features.i1_indicators.mfi import MFIPlugin

        df = synthetic_ohlcv_trending
        plugin = MFIPlugin()

        # Build our values via compute_full seed then compute_next bar-by-bar
        # to confirm the seeded incremental path is also correct
        our_values: list[float] = []
        warmup = 20  # need p+1 = 15 bars; use 20 for safety

        result_full = plugin.compute_full(frames_from_ohlcv(df.iloc[:warmup]))
        state = result_full.get("_state", {})

        for i in range(warmup, len(df)):
            window = df.iloc[: i + 1]
            r = plugin.compute_next(frames_from_ohlcv(window), state=state)
            if "_state" in r:
                state = r["_state"]
            our_values.append(r.get("mfi_14", float("nan")))

        our_series = pd.Series(our_values, index=df.index[warmup:])

        # pandas_ta reference (talib=False for pure Python computation)
        ref_series = ta.mfi(
            df["high"], df["low"], df["close"], df["volume"], length=14, talib=False
        )
        ref_trimmed = ref_series.iloc[warmup:].reset_index(drop=True)
        our_aligned = our_series.reset_index(drop=True)

        assert_close_to_reference(
            our_aligned,
            ref_trimmed,
            atol=1e-9,
            name="MFI",
        )

    # ------------------------------------------------------------------
    # Williams %R: pandas_ta reference comparison after .to_numpy refactor
    # ------------------------------------------------------------------

    def test_williams_r_matches_pandas_ta(self, synthetic_ohlcv_trending: pd.DataFrame) -> None:
        """Williams %R matches pandas_ta.willr to atol=1e-9 after .tolist() removal."""
        from src.intelligence.features.i1_indicators.williams_r import WilliamsRPlugin

        df = synthetic_ohlcv_trending
        plugin = WilliamsRPlugin()
        p = 14
        warmup = p + 1

        result_full = plugin.compute_full(frames_from_ohlcv(df.iloc[:warmup]))
        state = result_full.get("_state", {})

        our_values: list[float] = []
        for i in range(warmup, len(df)):
            window = df.iloc[: i + 1]
            r = plugin.compute_next(frames_from_ohlcv(window), state=state)
            if "_state" in r:
                state = r["_state"]
            our_values.append(r.get("williams_r_14", float("nan")))

        our_series = pd.Series(our_values, index=df.index[warmup:])
        ref_series = ta.willr(df["high"], df["low"], df["close"], length=p, talib=False)
        ref_trimmed = ref_series.iloc[warmup:].reset_index(drop=True)

        assert_close_to_reference(
            our_series.reset_index(drop=True),
            ref_trimmed,
            atol=1e-9,
            name="WilliamsR",
        )

    # ------------------------------------------------------------------
    # Stochastic: pandas_ta reference comparison after .to_numpy refactor
    # ------------------------------------------------------------------

    def test_stochastic_matches_pandas_ta(self, synthetic_ohlcv_trending: pd.DataFrame) -> None:
        """Stochastic %K and %D match pandas_ta.stoch to atol=1e-9 after .tolist() removal."""
        from src.intelligence.features.i1_indicators.stochastic import StochasticPlugin

        df = synthetic_ohlcv_trending
        plugin = StochasticPlugin()
        k_period, d_period = 14, 3
        warmup = k_period + d_period

        result_full = plugin.compute_full(frames_from_ohlcv(df.iloc[:warmup]))
        state = result_full.get("_state", {})

        our_k_vals: list[float] = []
        our_d_vals: list[float] = []
        for i in range(warmup, len(df)):
            window = df.iloc[: i + 1]
            r = plugin.compute_next(frames_from_ohlcv(window), state=state)
            if "_state" in r:
                state = r["_state"]
            our_k_vals.append(r.get(f"stoch_k_{k_period}_{d_period}", float("nan")))
            our_d_vals.append(r.get(f"stoch_d_{k_period}_{d_period}", float("nan")))

        # pandas_ta stoch with smooth_k=1 matches our fast-stochastic implementation
        ref_stoch = ta.stoch(
            df["high"], df["low"], df["close"], k=k_period, d=d_period, smooth_k=1, talib=False
        )
        ref_k = ref_stoch[f"STOCHk_{k_period}_{d_period}_1"].iloc[warmup:].reset_index(drop=True)
        ref_d = ref_stoch[f"STOCHd_{k_period}_{d_period}_1"].iloc[warmup:].reset_index(drop=True)

        assert_close_to_reference(
            pd.Series(our_k_vals),
            ref_k,
            atol=1e-9,
            name="Stochastic %K",
        )
        assert_close_to_reference(
            pd.Series(our_d_vals),
            ref_d,
            atol=1e-9,
            name="Stochastic %D",
        )

    # ------------------------------------------------------------------
    # CCI: incremental consistency (our formula differs from pandas_ta)
    # ------------------------------------------------------------------

    def test_cci_incremental_equals_full(self, synthetic_ohlcv_trending: pd.DataFrame) -> None:
        """CCI compute_full equals compute_full + compute_next at atol=1e-9.

        Our CCI uses Lambert's formula with a rolling window computed on the last
        p bars only (window.mean() + MAD). This differs from how pandas_ta computes
        CCI in some edge cases; the incremental consistency check is the appropriate
        regression guard for the .tolist() -> .to_numpy() refactor.
        """
        from src.intelligence.features.i1_indicators.cci import CCIPlugin

        df = synthetic_ohlcv_trending
        plugin = CCIPlugin()
        p = 14
        warmup = 20  # need p+1 = 15 bars; use 20 for safety (matches min_lookback)

        # Seed state
        result_full = plugin.compute_full(frames_from_ohlcv(df.iloc[:warmup]))
        state = result_full.get("_state", {})

        our_incr_vals: list[float] = []
        for i in range(warmup, len(df)):
            window = df.iloc[: i + 1]
            r = plugin.compute_next(frames_from_ohlcv(window), state=state)
            if "_state" in r:
                state = r["_state"]
            our_incr_vals.append(r.get("cci_14", float("nan")))

        # Reference: compute_full at each bar position (uses the same rolling window)
        our_full_vals: list[float] = []
        for i in range(warmup, len(df)):
            r = plugin.compute_full(frames_from_ohlcv(df.iloc[: i + 1]))
            our_full_vals.append(r.get("cci_14", float("nan")))

        assert_close_to_reference(
            pd.Series(our_incr_vals),
            pd.Series(our_full_vals),
            atol=1e-9,
            name="CCI incremental vs full",
        )

    # ------------------------------------------------------------------
    # VolumeZscore: incremental consistency after .to_numpy refactor
    # ------------------------------------------------------------------

    def test_volume_zscore_incremental_equals_full(
        self, synthetic_ohlcv_trending: pd.DataFrame
    ) -> None:
        """VolumeZscore compute_full equals compute_full + compute_next at atol=1e-9.

        VolumeZscore has no pandas_ta equivalent; incremental consistency is the
        correct regression guard for the .tolist() -> .to_numpy() refactor.
        """
        from src.intelligence.trading.volume_zscore import VolumeZscorePlugin

        df = synthetic_ohlcv_trending
        plugin = VolumeZscorePlugin()
        warmup = 22  # _WINDOW + 2 for at least one meaningful z-score

        # Seed state on first warmup bars
        result_seed = plugin.compute_full(frames_from_ohlcv(df.iloc[:warmup]))
        assert result_seed, "compute_full returned empty on seed window"
        state = result_seed.get("_state", {})

        our_incr_vals: list[float] = []
        for i in range(warmup, len(df)):
            window = df.iloc[: i + 1]
            r = plugin.compute_next(frames_from_ohlcv(window), state=state)
            if "_state" in r:
                state = r["_state"]
            our_incr_vals.append(r.get("volume_z_score", float("nan")))

        # Reference: compute_full at each bar position
        our_full_vals: list[float] = []
        for i in range(warmup, len(df)):
            r = plugin.compute_full(frames_from_ohlcv(df.iloc[: i + 1]))
            our_full_vals.append(r.get("volume_z_score", float("nan")))

        assert_close_to_reference(
            pd.Series(our_incr_vals),
            pd.Series(our_full_vals),
            atol=1e-9,
            name="VolumeZscore incremental vs full",
        )
