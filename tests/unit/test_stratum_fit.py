"""Unit tests for src/intelligence/ensemble/stratum_fit.py.

The stratum fit is the compute half of EnsembleTrainer._process_stratum, extracted so
the trainer and the Phase 179 walk-forward harness run the same code. It is a pure
function of the stratum's IC rows and its training-window feature matrix: no clock,
no DB (todo 408).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from src.intelligence.ensemble.covariance import compute_shrinkage_covariance
from src.intelligence.ensemble.stratum_fit import (
    fit_stratum_weights,
    select_stratum,
)

_WINDOW_END = datetime(2025, 12, 24, 5, 15, tzinfo=UTC)
_FIT_PARAMS = {
    "weight_method": "ic_proportional",
    "max_feature_weight": 0.90,
    "max_cluster_corr": 0.80,
    "max_cluster_weight": 0.90,
    "mv_condition_max": 1000.0,
}


def _ic_row(name: str, ic: float, lo: float, hi: float, window_end: datetime = _WINDOW_END):
    return {
        "feature_name": name,
        "ic_sharpe_hac": ic,
        "ic_shrunk": ic,
        "shrinkage_weight": 1.0,
        "ic_ci_lower": lo,
        "ic_ci_upper": hi,
        "ic_sign": 1,
        "lookahead_bars": 5,
        "training_window_end": window_end,
    }


def _rows(window_end: datetime = _WINDOW_END) -> list[dict]:
    return [
        _ic_row("feat_a", 0.50, 0.10, 0.90, window_end),
        _ic_row("feat_b", 0.30, 0.05, 0.60, window_end),
        _ic_row("feat_c", 0.20, 0.02, 0.40, window_end),
    ]


def _select(rows: list[dict], feature_cols: list[str] | None = None, min_passing: int = 2):
    return select_stratum(
        rows,
        ic_input_column="ic_sharpe_hac",
        sharpe_floor=0.025,
        feature_cols=feature_cols or ["feat_a", "feat_b", "feat_c"],
        min_passing_features=min_passing,
    )


def _bar_ts(n_rows: int = 400) -> list[datetime]:
    """n_rows daily timestamps, all on or before _WINDOW_END."""
    return [_WINDOW_END - timedelta(days=n_rows - 1 - i) for i in range(n_rows)]


def _matrix(n_rows: int = 400, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    base = rng.standard_normal((n_rows, 3))
    base[:, 1] += 0.6 * base[:, 0]
    return base.astype(np.float32)


class TestSelectStratum:
    def test_selection_follows_ic_order_restricted_to_existing_columns(self) -> None:
        selection, reason, _ = _select(_rows(), feature_cols=["feat_c", "feat_a", "feat_b"])
        assert reason is None
        assert selection.feature_names == ["feat_a", "feat_b", "feat_c"]

    def test_features_without_a_column_are_dropped(self) -> None:
        selection, reason, _ = _select(_rows(), feature_cols=["feat_a", "feat_b"])
        assert reason is None
        assert selection.feature_names == ["feat_a", "feat_b"]
        assert len(selection.quality_weights) == 2

    def test_too_few_selected_features_is_a_named_skip(self) -> None:
        selection, reason, _ = _select(_rows()[:1])
        assert selection is None
        assert reason == "min_features"

    def test_too_few_columns_is_a_named_skip(self) -> None:
        selection, reason, _ = _select(_rows(), feature_cols=["feat_a"])
        assert selection is None
        assert reason == "missing_cols"

    def test_too_few_selected_features_reports_the_count(self) -> None:
        _, reason, n = _select(_rows()[:1])
        assert (reason, n) == ("min_features", 1)

    def test_selected_rows_from_different_ic_windows_fail_loudly(self) -> None:
        """Mixing IC windows is todo 405's unpinned read; the fit has no single causal
        bound then, so it must refuse rather than pick one."""
        rows = _rows()
        rows[1]["training_window_end"] = datetime(2025, 6, 30, tzinfo=UTC)
        with pytest.raises(ValueError, match="training_window_end"):
            _select(rows)

    def test_training_window_end_is_carried_on_the_selection(self) -> None:
        selection, _, _ = _select(_rows())
        assert selection.training_window_end == _WINDOW_END


class TestFitStratumWeights:
    def test_matches_resolve_stratum_weights_on_quality_weights(self) -> None:
        from src.intelligence.ensemble.stratum_fit import resolve_stratum_weights

        selection, _, _ = _select(_rows())
        X = _matrix()
        fit = fit_stratum_weights(selection, X, _bar_ts(), **_FIT_PARAMS)

        cov, shrinkage = compute_shrinkage_covariance(X)
        std = np.sqrt(np.outer(np.diag(cov), np.diag(cov)))
        corr = np.where(std > 1e-10, cov / std, 0.0)
        np.fill_diagonal(corr, 1.0)
        expected = resolve_stratum_weights(
            "ic_proportional",
            selection.quality_weights,
            cov,
            corr,
            selection.ic_sharpes,
            selection.ic_signs,
            0.90,
            0.80,
            0.90,
            1000.0,
        )
        np.testing.assert_array_equal(fit.result.weights, expected.weights)
        np.testing.assert_array_equal(fit.result.raw_weights, expected.raw_weights)
        assert fit.result.method_used == "ic_proportional"
        assert fit.shrinkage == pytest.approx(shrinkage)

    def test_weights_do_not_depend_on_how_old_the_ic_window_is(self) -> None:
        """Todo 408: the trainer used to flatten weights to 1/n once the IC window
        was more than weight_stale_max_days behind the wall clock. The fit has no
        clock, so an IC window from years ago gives the same weights as a fresh one."""
        X = _matrix()
        fresh, _, _ = _select(_rows(_WINDOW_END))
        old, _, _ = _select(_rows(datetime(2019, 1, 2, tzinfo=UTC)))
        np.testing.assert_array_equal(
            fit_stratum_weights(fresh, X, _bar_ts(), **_FIT_PARAMS).result.weights,
            fit_stratum_weights(
                old,
                X,
                [t - (_WINDOW_END - datetime(2019, 1, 2, tzinfo=UTC)) for t in _bar_ts()],
                **_FIT_PARAMS,
            ).result.weights,
        )

    def test_unequal_quality_gives_unequal_weights(self) -> None:
        selection, _, _ = _select(_rows())
        weights = fit_stratum_weights(selection, _matrix(), _bar_ts(), **_FIT_PARAMS).result.weights
        assert not np.allclose(weights, 1.0 / len(weights))

    def test_effective_n_is_reported(self) -> None:
        from src.intelligence.ensemble.weights import effective_n

        selection, _, _ = _select(_rows())
        fit = fit_stratum_weights(selection, _matrix(), _bar_ts(), **_FIT_PARAMS)
        assert fit.effective_n == pytest.approx(effective_n(fit.result.weights))

    def test_fit_uses_bars_up_to_and_including_the_window_end_only(self) -> None:
        """Todo 409: the covariance must not see bars after the IC window. ic_engine
        measures IC with ts <= training_window_end, so the bar at the window end is in."""
        selection, _, _ = _select(_rows())
        X = _matrix(420)
        ts = _bar_ts(400) + [_WINDOW_END + timedelta(days=d) for d in range(1, 21)]
        X_later = X.copy()
        X_later[400:] = 1000.0 * np.arange(20)[:, None]  # wild post-window rows
        on_window = fit_stratum_weights(selection, X[:400], ts[:400], **_FIT_PARAMS)
        with_later = fit_stratum_weights(selection, X_later, ts, **_FIT_PARAMS)
        np.testing.assert_array_equal(with_later.result.weights, on_window.result.weights)
        assert with_later.n_fit_rows == 400
