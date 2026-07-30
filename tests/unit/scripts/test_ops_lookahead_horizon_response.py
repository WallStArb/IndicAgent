"""Unit tests for ops_lookahead_horizon_response.py's stride correction (todo 146).

The diagnostic's original Fisher-z CI was computed on raw overlapping-window observations
(consecutive forward returns at horizon h overlap by h-1 bars and are serially dependent),
understating its own half-width -- flagged by Fable 5's review of the todo-146 full-corpus
run. Fix mirrors ic_engine.py's production `scale_stride = max(subsample_min_stride,
lookahead_bars)` discipline. No DB, no asyncio -- pure function + CLI parsing tests only.
"""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import patch

import numpy as np
import pytest

from scripts.ops.alpha.ops_lookahead_horizon_response import (
    _feature_significance,
    _fetch_all_symbols_horizon_rows,
    _parse_args,
    _stride_for_horizon,
)


class TestStrideForHorizon:
    def test_short_horizon_floored_at_min_stride(self):
        assert _stride_for_horizon(min_stride=5, horizon_bars=1) == 5

    def test_horizon_at_min_stride_boundary(self):
        assert _stride_for_horizon(min_stride=5, horizon_bars=5) == 5

    def test_long_horizon_exceeds_min_stride(self):
        assert _stride_for_horizon(min_stride=5, horizon_bars=60) == 60

    def test_custom_min_stride(self):
        assert _stride_for_horizon(min_stride=10, horizon_bars=6) == 10


class TestMinStrideCliFlag:
    def test_defaults_to_none(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["prog"])
        args = _parse_args()
        assert args.min_stride is None

    def test_accepts_value(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["prog", "--min-stride", "10"])
        args = _parse_args()
        assert args.min_stride == 10


class TestFeatureSignificance:
    """Per-feature CI-exclude-zero / BH-FDR breakdown (2026-07-29): the diagnostic's
    median_abs_ic can sit inside its own CI while individual features don't -- these
    guard the mask/NaN/FDR-family plumbing that surfaces that, independent of any DB."""

    def test_raw_sig_flags_ci_excluding_zero(self):
        ic_vec = np.array([0.20, 0.01, -0.15])
        ci_lower = np.array([0.10, -0.05, -0.25])
        ci_upper = np.array([0.30, 0.07, -0.05])
        p_vec = np.array([0.001, 0.9, 0.01])
        mask = np.array([True, True, True])

        idxs, raw_sig, _fdr_sig = _feature_significance(
            ic_vec, ci_lower, ci_upper, p_vec, mask, fdr_alpha=0.05
        )

        assert list(idxs) == [0, 1, 2]
        assert list(raw_sig) == [True, False, True]

    def test_mask_excludes_features_outside_it(self):
        """A candidate/canary feature must never contribute to the active family's
        significance count, and vice versa -- the whole point of separating them."""
        ic_vec = np.array([0.20, 0.20])
        ci_lower = np.array([0.10, 0.10])
        ci_upper = np.array([0.30, 0.30])
        p_vec = np.array([0.001, 0.001])
        active_only_mask = np.array([True, False])

        idxs, raw_sig, fdr_sig = _feature_significance(
            ic_vec, ci_lower, ci_upper, p_vec, active_only_mask, fdr_alpha=0.05
        )

        assert list(idxs) == [0]
        assert list(raw_sig) == [True]
        assert list(fdr_sig) == [True]

    def test_nan_ic_or_p_excluded_from_family(self):
        """A degenerate feature (NaN IC/p, e.g. zero-variance this horizon) must not
        be silently coerced into the FDR family -- it's unmeasurable, not a null."""
        ic_vec = np.array([0.20, np.nan, 0.15])
        ci_lower = np.array([0.10, np.nan, 0.05])
        ci_upper = np.array([0.30, np.nan, 0.25])
        p_vec = np.array([0.001, np.nan, 0.02])
        mask = np.array([True, True, True])

        idxs, raw_sig, fdr_sig = _feature_significance(
            ic_vec, ci_lower, ci_upper, p_vec, mask, fdr_alpha=0.05
        )

        assert list(idxs) == [0, 2]
        assert len(raw_sig) == 2
        assert len(fdr_sig) == 2

    def test_empty_mask_returns_empty_arrays(self):
        ic_vec = np.array([0.20, 0.15])
        ci_lower = np.array([0.10, 0.05])
        ci_upper = np.array([0.30, 0.25])
        p_vec = np.array([0.001, 0.02])
        mask = np.array([False, False])

        idxs, raw_sig, fdr_sig = _feature_significance(
            ic_vec, ci_lower, ci_upper, p_vec, mask, fdr_alpha=0.05
        )

        assert len(idxs) == 0
        assert len(raw_sig) == 0
        assert len(fdr_sig) == 0

    def test_fdr_correction_can_reject_a_raw_significant_feature(self):
        """FDR must be strictly more conservative than the raw per-feature CI test --
        a family with 3 clearly real p-values and 47 clearly-not-significant ones
        (all with ci_lower > 0, so every one is "raw significant") should see BH-FDR
        reject the 47, not pass all 50 through, exercising the actual correction path
        rather than a pass-through of raw_sig."""
        rng = np.random.default_rng(42)
        n_features = 50
        p_vec = np.concatenate(
            [[0.0001, 0.0005, 0.001], rng.uniform(0.2, 0.9, size=n_features - 3)]
        )
        ic_vec = np.full(n_features, 0.10)
        ci_lower = np.full(n_features, 0.01)  # raw CI excludes zero for every feature
        ci_upper = np.full(n_features, 0.50)
        mask = np.ones(n_features, dtype=bool)

        idxs, raw_sig, fdr_sig = _feature_significance(
            ic_vec, ci_lower, ci_upper, p_vec, mask, fdr_alpha=0.05
        )

        assert len(idxs) == n_features
        assert raw_sig.sum() == n_features  # every ci_lower > 0 by construction
        assert fdr_sig[0] and fdr_sig[1] and fdr_sig[2]  # the 3 real ones survive
        assert fdr_sig.sum() < raw_sig.sum()  # the 47 large-p features do not


class TestFetchAllSymbolsHorizonRowsConcurrency:
    @pytest.mark.asyncio
    async def test_fetches_all_symbols_concurrently(self):
        """Per-symbol fetches must overlap in time (asyncio.gather), not run one
        after another -- and pairing (symbol, rows) must survive gather's ordering
        guarantee (results ordered by input, not completion order)."""
        concurrent = 0
        max_concurrent = 0

        async def fake_fetch(
            pool, tf, symbol, vintage, horizons, max_bars_per_symbol, *, allow_overnight=False
        ):
            nonlocal concurrent, max_concurrent
            concurrent += 1
            max_concurrent = max(max_concurrent, concurrent)
            await asyncio.sleep(0.01)
            concurrent -= 1
            return [{"symbol": symbol}]

        with patch(
            "scripts.ops.alpha.ops_lookahead_horizon_response._fetch_horizon_response_rows",
            new=fake_fetch,
        ):
            result = await _fetch_all_symbols_horizon_rows(
                pool=None,
                tf="1h",
                symbols=["A", "B", "C"],
                vintage=None,
                horizons=(1, 2),
                max_bars_per_symbol=100,
            )

        assert max_concurrent > 1, "fetches ran sequentially, not concurrently"
        assert [symbol for symbol, _ in result] == ["A", "B", "C"]
        assert result[1][1] == [{"symbol": "B"}]
