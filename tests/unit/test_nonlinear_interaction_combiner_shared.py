"""Unit tests for scripts/analysis/_nonlinear_interaction_combiner_shared.py (todo 239, todo 240).

DB-free -- exercises the pure helper functions only, never fetch_training_matrix or
run_nonlinear_interaction_combiner_check (both require a live corpus).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from scripts.analysis._nonlinear_interaction_combiner_shared import (
    EXCLUDE_COLS,
    _pooled_panel_folds,
    _select_feature_columns,
    bootstrap_ic_stats,
    fit_linear_ensemble_weights,
    paired_bootstrap_ic_difference,
    score_linear_ensemble,
    train_and_predict_oos,
)


def _make_bar_ts(bars_and_symbol_counts: list[int]) -> np.ndarray:
    """Build a pooled-panel bar_ts array: bar i repeated bars_and_symbol_counts[i] times,
    matching the real fetch's ORDER BY bar_ts ASC, symbol ASC (each bar's rows contiguous)."""
    parts = [np.full(count, i, dtype=np.int64) for i, count in enumerate(bars_and_symbol_counts)]
    return np.concatenate(parts)


class TestPooledPanelFolds:
    def test_uneven_symbols_per_bar_maps_embargo_in_bar_units_not_rows(self) -> None:
        """todo 239's actual bug: 10 bars x 80 symbols/bar = 800 rows. An embargo of 2
        BARS must skip 2 bars' worth of rows at the boundary (160 rows), not 2 rows."""
        bar_ts = _make_bar_ts([80] * 10)
        folds = _pooled_panel_folds(bar_ts, n_folds=1, embargo_bars=2, min_reliable_n=1)
        assert len(folds) == 1
        train_end, test_start, test_end = folds[0]
        # n_valid=10 bars, n_folds=1: train_end_bar = int(10*1/2) = 5, test_start_bar = 5+2=7,
        # test_end_bar = int(10*2/2) = 10.
        assert train_end == 5 * 80
        assert test_start == 7 * 80
        assert test_end == 10 * 80

    def test_uneven_symbols_per_bar_boundary_never_splits_a_bar(self) -> None:
        """A fold boundary must land on a bar edge -- never inside a bar's block of rows,
        even when bars have different symbol counts (missing data for some symbols)."""
        counts = [80, 79, 80, 81, 80, 79, 80, 80, 80, 79]
        bar_ts = _make_bar_ts(counts)
        first_row_of_bar = np.concatenate(([0], np.cumsum(counts)[:-1]))
        row_boundaries = set(first_row_of_bar.tolist()) | {int(np.sum(counts))}

        folds = _pooled_panel_folds(bar_ts, n_folds=3, embargo_bars=1, min_reliable_n=1)
        assert len(folds) > 0
        for train_end, test_start, test_end in folds:
            assert train_end in row_boundaries
            assert test_start in row_boundaries
            assert test_end in row_boundaries

    def test_single_symbol_per_bar_matches_build_walk_forward_folds_directly(self) -> None:
        """Degenerate case (1 row per bar_ts, i.e. a single-symbol panel): row folds must
        be identical to calling build_walk_forward_folds directly on n_valid=n_bars."""
        from src.intelligence.statistics.ic_math import build_walk_forward_folds

        bar_ts = _make_bar_ts([1] * 500)
        expected = build_walk_forward_folds(
            n_valid=500, n_folds=5, embargo_bars=20, min_reliable_n=50
        )
        folds = _pooled_panel_folds(bar_ts, n_folds=5, embargo_bars=20, min_reliable_n=50)
        actual_test_slices = [(test_start, test_end) for _, test_start, test_end in folds]
        assert actual_test_slices == expected

    def test_empty_when_all_folds_too_small(self) -> None:
        bar_ts = _make_bar_ts([80] * 5)
        folds = _pooled_panel_folds(bar_ts, n_folds=3, embargo_bars=1, min_reliable_n=100)
        assert folds == []


class TestFitLinearEnsembleWeights:
    def test_returns_finite_weights_matching_feature_count(self) -> None:
        rng = np.random.default_rng(0)
        n_rows, n_features = 2000, 12
        X = rng.normal(size=(n_rows, n_features)).astype(np.float32)
        true_weight = np.zeros(n_features)
        true_weight[0] = 1.0
        y = X @ true_weight + rng.normal(scale=0.1, size=n_rows)

        fit = fit_linear_ensemble_weights(X, y)

        assert fit.weights.shape == (n_features,)
        assert fit.impute_median.shape == (n_features,)
        assert fit.feature_mean.shape == (n_features,)
        assert fit.feature_std.shape == (n_features,)
        assert np.all(np.isfinite(fit.weights))
        assert np.all(np.isfinite(fit.impute_median))
        assert np.all(fit.feature_std > 0)

    def test_signal_feature_gets_more_weight_than_pure_noise_feature(self) -> None:
        """The one feature actually driving y should end up with materially higher
        |weight| than a feature that is pure noise -- sanity that the IC-shrinkage +
        mean-variance combination is doing something directionally sane, not a
        placeholder that returns e.g. uniform or all-zero weights."""
        rng = np.random.default_rng(1)
        n_rows, n_features = 5000, 8
        X = rng.normal(size=(n_rows, n_features)).astype(np.float32)
        y = 2.0 * X[:, 0] + rng.normal(scale=0.5, size=n_rows)

        fit = fit_linear_ensemble_weights(X, y)

        assert abs(fit.weights[0]) > abs(fit.weights[1])
        assert abs(fit.weights[0]) > abs(fit.weights[2])

    def test_high_variance_noise_feature_does_not_dominate_scale_matched_signal(self) -> None:
        """Regression guard: before standardization, a high-raw-variance noise column could
        dominate a low-raw-variance signal column's contribution to the score even though the
        signal column has far higher |IC| -- confirmed on the real corpus (a ~4x-weaker-IC,
        high-variance column contributed ~114x more to score variance than the strongest
        feature). Reproduce the same shape here with a realistic feature count (20 -- enough
        that derive_weights' 0.20 per-feature cap isn't pathologically binding on every feature
        at once, which a too-small feature count would trigger): col 0 drives y with unit scale,
        col 1 is pure noise at 100x the raw scale, the rest are unit-scale pure noise."""
        rng = np.random.default_rng(9)
        n_rows, n_features = 20_000, 20
        X = rng.normal(size=(n_rows, n_features)).astype(np.float32)
        X[:, 1] *= 100.0
        y = X[:, 0] + rng.normal(scale=0.3, size=n_rows)

        fit = fit_linear_ensemble_weights(X, y)
        score = score_linear_ensemble(fit, X)
        X_std = (X - fit.feature_mean) / fit.feature_std
        contribution_0 = abs(fit.weights[0]) * np.std(X_std[:, 0])
        contribution_1 = abs(fit.weights[1]) * np.std(X_std[:, 1])

        assert abs(fit.weights[0]) > abs(fit.weights[1])
        assert contribution_0 > contribution_1
        assert np.all(np.isfinite(score))

    def test_handles_nan_features_via_median_imputation(self) -> None:
        rng = np.random.default_rng(2)
        n_rows, n_features = 3000, 6
        X = rng.normal(size=(n_rows, n_features)).astype(np.float32)
        y = X[:, 0] + rng.normal(scale=0.2, size=n_rows)
        X[:100, 3] = np.nan

        fit = fit_linear_ensemble_weights(X, y)

        assert np.all(np.isfinite(fit.weights))
        assert np.isfinite(fit.impute_median[3])

    def test_subsamples_when_train_exceeds_max_fit_rows(self) -> None:
        """Large expanding-window folds (millions of rows) must not force LedoitWolf /
        rankdata over the full training slice -- max_fit_rows bounds the fit cost/memory
        regardless of how large X_train has grown."""
        rng = np.random.default_rng(3)
        n_rows, n_features = 10_000, 5
        X = rng.normal(size=(n_rows, n_features)).astype(np.float32)
        y = X[:, 0] + rng.normal(scale=0.1, size=n_rows)

        fit = fit_linear_ensemble_weights(X, y, max_fit_rows=500)

        assert fit.weights.shape == (n_features,)
        assert np.all(np.isfinite(fit.weights))

    def test_deterministic_given_same_seed(self) -> None:
        rng = np.random.default_rng(4)
        n_rows, n_features = 4000, 6
        X = rng.normal(size=(n_rows, n_features)).astype(np.float32)
        y = X[:, 0] + rng.normal(scale=0.3, size=n_rows)

        fit1 = fit_linear_ensemble_weights(X, y, max_fit_rows=1000, rng_seed=7)
        fit2 = fit_linear_ensemble_weights(X, y, max_fit_rows=1000, rng_seed=7)
        np.testing.assert_array_equal(fit1.weights, fit2.weights)


class TestScoreLinearEnsemble:
    def test_scores_a_different_slice_using_fit_sample_transform(self) -> None:
        rng = np.random.default_rng(6)
        n_rows, n_features = 3000, 5
        X_train = rng.normal(size=(n_rows, n_features)).astype(np.float32)
        y_train = X_train[:, 0] + rng.normal(scale=0.2, size=n_rows)
        X_test = rng.normal(size=(200, n_features)).astype(np.float32)

        fit = fit_linear_ensemble_weights(X_train, y_train)
        score = score_linear_ensemble(fit, X_test)

        assert score.shape == (200,)
        assert np.all(np.isfinite(score))

    def test_test_slice_nans_filled_from_fit_medians_not_its_own(self) -> None:
        rng = np.random.default_rng(8)
        n_rows, n_features = 3000, 4
        X_train = rng.normal(size=(n_rows, n_features)).astype(np.float32)
        y_train = X_train[:, 0] + rng.normal(scale=0.2, size=n_rows)
        fit = fit_linear_ensemble_weights(X_train, y_train)

        X_test = rng.normal(size=(50, n_features)).astype(np.float32)
        X_test[:, 2] = np.nan  # entirely NaN column in the TEST slice only

        score = score_linear_ensemble(fit, X_test)
        assert np.all(np.isfinite(score))


class TestSelectFeatureColumns:
    """Todo 245: the CTF-leak diagnostic needs to exclude ctf_momentum/ctf_vwap_align/
    ctf_regime_align WITHOUT mutating the shared EXCLUDE_COLS module constant (which every
    other caller, including the eventual 'real' re-run, also reads) -- a hand-edit-then-revert
    on shared state is exactly the kind of manual, forgettable step that silently corrupts a
    later run in a repo other sessions are concurrently committing to."""

    def _attrs(self, names_and_types: list[tuple[str, str]]):
        return names_and_types

    def test_selects_float_columns_not_in_exclude_cols(self) -> None:
        attrs = [("momentum_z_fast", "float4"), ("symbol", "text"), ("bar_ts", "timestamptz")]
        result = _select_feature_columns(attrs)
        assert result == ["momentum_z_fast"]

    def test_excludes_return_fast_even_though_its_a_float_column(self) -> None:
        attrs = [("momentum_z_fast", "float4"), ("return_fast", "float4")]
        result = _select_feature_columns(attrs)
        assert result == ["momentum_z_fast"]

    def test_excludes_module_level_exclude_cols_by_default(self) -> None:
        excluded_name = next(iter(EXCLUDE_COLS))
        attrs = [("momentum_z_fast", "float4"), (excluded_name, "float4")]
        result = _select_feature_columns(attrs)
        assert result == ["momentum_z_fast"]

    def test_extra_exclude_cols_removes_additional_columns_without_touching_module_constant(
        self,
    ) -> None:
        before = frozenset(EXCLUDE_COLS)
        attrs = [
            ("momentum_z_fast", "float4"),
            ("ctf_momentum", "float4"),
            ("ctf_vwap_align", "float4"),
            ("ctf_regime_align", "float4"),
        ]
        result = _select_feature_columns(
            attrs,
            extra_exclude_cols=frozenset({"ctf_momentum", "ctf_vwap_align", "ctf_regime_align"}),
        )
        assert result == ["momentum_z_fast"]
        assert EXCLUDE_COLS == before  # module constant untouched -- the whole point

    def test_extra_exclude_cols_defaults_to_empty_no_behavior_change(self) -> None:
        attrs = [("momentum_z_fast", "float4"), ("ctf_momentum", "float4")]
        result = _select_feature_columns(attrs)
        assert result == ["momentum_z_fast", "ctf_momentum"]

    def test_preserves_schema_order(self) -> None:
        attrs = [("z_col", "float4"), ("a_col", "float4"), ("m_col", "float4")]
        result = _select_feature_columns(attrs)
        assert result == ["z_col", "a_col", "m_col"]


class TestPairedBootstrapIcDifference:
    def test_deterministic_given_same_seed(self) -> None:
        rng = np.random.default_rng(20)
        n = 5000
        actual = rng.normal(size=n)
        score_a = actual + rng.normal(scale=0.5, size=n)
        score_b = rng.normal(size=n)

        r1 = paired_bootstrap_ic_difference(score_a, score_b, actual, 10, 200, seed=1)
        r2 = paired_bootstrap_ic_difference(score_a, score_b, actual, 10, 200, seed=1)
        assert r1 == r2

    def test_identical_scores_never_show_significant_difference(self) -> None:
        rng = np.random.default_rng(21)
        n = 5000
        actual = rng.normal(size=n)
        score = actual + rng.normal(scale=0.3, size=n)

        result = paired_bootstrap_ic_difference(score, score.copy(), actual, 10, 300, seed=2)

        assert result["point_diff"] == pytest.approx(0.0, abs=1e-9)
        assert result["ci_lower"] <= 0.0 <= result["ci_upper"]
        assert not result["a_significantly_better"]
        assert not result["b_significantly_better"]

    def test_clearly_better_score_shows_significant_positive_difference(self) -> None:
        rng = np.random.default_rng(22)
        n = 5000
        actual = rng.normal(size=n)
        score_a = actual + rng.normal(scale=0.05, size=n)  # near-perfect
        score_b = rng.normal(size=n)  # pure noise

        result = paired_bootstrap_ic_difference(score_a, score_b, actual, 10, 300, seed=3)

        assert result["point_diff"] > 0
        assert result["ci_lower"] > 0
        assert result["a_significantly_better"]

    def test_paired_ci_narrower_than_independent_marginal_cis_for_correlated_scores(self) -> None:
        """The whole point of pairing: two scores measured on the SAME rows have strongly
        correlated bootstrap ICs, so the paired difference's CI should be much narrower than
        the gap you'd need to bridge by comparing two independent marginal CIs -- proving the
        pairing captures the shared variance rather than double-counting it."""
        rng = np.random.default_rng(23)
        n = 8000
        actual = rng.normal(size=n)
        score_a = actual + rng.normal(scale=0.4, size=n)
        score_b = score_a + rng.normal(scale=0.05, size=n)  # highly correlated with score_a

        paired = paired_bootstrap_ic_difference(score_a, score_b, actual, 10, 500, seed=4)
        stats_a = bootstrap_ic_stats(score_a, actual, 10, 500, seed=4)
        stats_b = bootstrap_ic_stats(score_b, actual, 10, 500, seed=4)

        paired_width = paired["ci_upper"] - paired["ci_lower"]
        marginal_a_width = stats_a["ci_upper"] - stats_a["ci_lower"]
        marginal_b_width = stats_b["ci_upper"] - stats_b["ci_lower"]

        assert paired_width < marginal_a_width
        assert paired_width < marginal_b_width


class TestTrainAndPredictOosIntegration:
    """Synthetic end-to-end proof that the todo 239 fold-mapping fix and the todo 240 linear
    arm are correctly wired into train_and_predict_oos together -- an uneven symbols-per-bar
    panel (some symbols missing on some bars, the real corpus's actual shape), never a live DB."""

    def _synthetic_panel(self, rng: np.random.Generator, n_bars: int, n_features: int):
        symbols = [f"SYM{i}" for i in range(10)]
        rows_symbol, rows_bar_ts, rows_X, rows_y = [], [], [], []
        for bar in range(n_bars):
            # Drop one symbol every 7th bar -- uneven symbols-per-bar, matching the real
            # corpus's occasional missing-data shape that motivated todo 239's boundary test.
            present = symbols if bar % 7 != 0 else symbols[:-1]
            for sym in present:
                x = rng.normal(size=n_features)
                rows_X.append(x)
                rows_y.append(x[0] + rng.normal(scale=0.1))
                rows_symbol.append(sym)
                rows_bar_ts.append(bar)
        X = np.array(rows_X, dtype=np.float32)
        y = np.array(rows_y, dtype=np.float64)
        meta = pd.DataFrame(
            {
                "symbol": rows_symbol,
                "bar_ts": pd.to_datetime(rows_bar_ts, unit="D", utc=True),
            }
        )
        return X, y, meta

    def test_runs_end_to_end_and_produces_both_arms(self) -> None:
        rng = np.random.default_rng(42)
        X, y, meta = self._synthetic_panel(rng, n_bars=200, n_features=6)

        oos = train_and_predict_oos(
            X,
            y,
            meta,
            target_col="return_fast_demeaned",
            n_folds=3,
            embargo_bars=5,
            min_reliable_n=10,
            bootstrap_seed=42,
        )

        assert "tree_score" in oos.columns
        assert "linear_score" in oos.columns
        assert len(oos) > 0
        assert np.all(np.isfinite(oos["tree_score"]))
        assert np.all(np.isfinite(oos["linear_score"]))
        # Every OOS row's bar must strictly postdate its fold's train_end -- proof the
        # bar-to-row mapping didn't leak train rows into test (todo 239's actual concern).
        assert oos["fold"].nunique() <= 3

    def test_embargo_in_bars_actually_separates_train_and_test_by_full_bars(self) -> None:
        """Regression guard for the exact todo 239 bug: with embargo_bars=3 on a panel with
        multiple symbols/bar, no test row's bar_ts may be within 3 BARS of the boundary --
        under the old row-unit bug this gap would have been a fraction of one bar."""
        rng = np.random.default_rng(1)
        X, y, meta = self._synthetic_panel(rng, n_bars=100, n_features=4)
        bar_ts_int = pd.DatetimeIndex(meta["bar_ts"]).asi8
        unique_bar_ts = np.unique(bar_ts_int)

        oos = train_and_predict_oos(
            X,
            y,
            meta,
            target_col="return_fast_demeaned",
            n_folds=2,
            embargo_bars=3,
            min_reliable_n=10,
            bootstrap_seed=42,
        )

        for fold_id, fold_df in oos.groupby("fold"):
            test_bars = pd.DatetimeIndex(fold_df["bar_ts"]).asi8
            first_test_bar_idx = int(np.searchsorted(unique_bar_ts, test_bars.min()))
            # At least 3 distinct bars must exist strictly before this fold's first test bar
            # that are NOT part of test (i.e. the embargo gap is bar-sized, not row-sized).
            assert first_test_bar_idx >= 3
