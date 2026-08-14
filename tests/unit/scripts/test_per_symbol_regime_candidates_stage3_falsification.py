"""Unit tests for scripts/analysis/per_symbol_regime_candidates_stage3_falsification.py
(todos 303/304 Stage 3). Synthetic data only -- no DB, no live regime_writer/regime_
volatility dependency, verifies the pure statistical functions before this script is ever
run against real data.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.analysis.per_symbol_regime_candidates_stage3_falsification import (
    _N_TERCILES,
    _SHARPE_MIN_WINDOWS,
    _best_cell_uplift,
    _build_panel,
    _ic_sharpe,
    _joint_cell_uplifts,
    _window_ic_series,
)


class TestWindowIcSeries:
    def test_perfect_positive_correlation_gives_ic_near_one_every_window(self):
        rng = np.random.default_rng(42)
        x = rng.normal(size=2000)
        y = x + rng.normal(scale=1e-6, size=2000)  # ~identical ranks, tiny noise
        ics = _window_ic_series(x, y, window_size=500)
        assert len(ics) == 4  # 2000 / 500, non-overlapping
        assert np.all(ics > 0.99)

    def test_perfect_negative_correlation_gives_ic_near_negative_one(self):
        rng = np.random.default_rng(42)
        x = rng.normal(size=1000)
        y = -x
        ics = _window_ic_series(x, y, window_size=500)
        assert len(ics) == 2
        assert np.all(ics < -0.99)

    def test_independent_series_gives_ic_near_zero_on_average(self):
        rng = np.random.default_rng(7)
        x = rng.normal(size=20_000)
        y = rng.normal(size=20_000)
        ics = _window_ic_series(x, y, window_size=500)
        assert len(ics) == 40
        assert abs(ics.mean()) < 0.15  # near zero, not exactly (finite-sample noise)

    def test_constant_window_is_skipped_not_errored(self):
        x = np.concatenate([np.zeros(500), np.random.default_rng(1).normal(size=500)])
        y = np.random.default_rng(2).normal(size=1000)
        ics = _window_ic_series(x, y, window_size=500)
        assert len(ics) == 1  # first (constant-x) window dropped, second kept

    def test_trailing_partial_window_is_dropped_not_padded(self):
        x = np.random.default_rng(3).normal(size=1250)  # 2 full windows + 250 leftover
        y = np.random.default_rng(4).normal(size=1250)
        ics = _window_ic_series(x, y, window_size=500)
        assert len(ics) == 2


class TestIcSharpe:
    def test_none_when_fewer_than_min_windows(self):
        ics = np.array([0.1] * (_SHARPE_MIN_WINDOWS - 1))
        assert _ic_sharpe(ics) is None

    def test_none_when_degenerate_zero_variance(self):
        ics = np.array([0.2] * _SHARPE_MIN_WINDOWS)  # identical every window -> std=0
        assert _ic_sharpe(ics) is None

    def test_matches_mean_over_std_definition_exactly(self):
        rng = np.random.default_rng(5)
        ics = rng.normal(loc=0.05, scale=0.02, size=20)
        result = _ic_sharpe(ics)
        assert result == pytest.approx(ics.mean() / ics.std())


class TestJointCellUplifts:
    def test_cell_where_xbar_is_predictive_only_in_top_tercile_shows_positive_uplift(self):
        """Construct a panel where momentum_z_fast predicts return_fast strongly ONLY
        when the candidate is in its top tercile, and not at all otherwise -- the joint
        cell for (any regime, top tercile) must show a real IC Sharpe uplift over the
        regime-only baseline; the bottom/mid tercile cells must not."""
        rng = np.random.default_rng(11)
        # 18000 / 3 terciles = 6000/tercile = 12 windows of 500 -- clears _SHARPE_MIN_WINDOWS
        # (10) with margin in every tercile, not just the pooled baseline.
        n = 18_000
        candidate = rng.uniform(size=n)  # candidate rank in [0, 1]
        xbar = rng.normal(size=n)
        top_tercile_mask = candidate > (2 / 3)
        y = np.where(
            top_tercile_mask,
            xbar + rng.normal(scale=0.1, size=n),  # strong signal in top tercile
            rng.normal(size=n),  # pure noise elsewhere -- xbar irrelevant
        )
        panel = pd.DataFrame(
            {
                "cand": candidate,
                "regime_volatility": ["calm"] * n,  # single regime -- isolates the effect
                "momentum_z_fast": xbar,
                "return_fast": y,
            }
        )

        cells = _joint_cell_uplifts(panel, "cand", "momentum_z_fast", {"calm": 1})
        assert len(cells) == _N_TERCILES

        top_cell = max(cells, key=lambda c: c["tercile"])
        bottom_cell = min(cells, key=lambda c: c["tercile"])

        assert top_cell["uplift_pct"] is not None
        assert top_cell["uplift_pct"] > 0.5  # large, unmistakable uplift
        # bottom tercile: signal is pure noise there, same as baseline -- no real uplift
        assert bottom_cell["uplift_pct"] is None or bottom_cell["uplift_pct"] < 0.2

    def test_empty_panel_after_dropna_returns_empty_list(self):
        panel = pd.DataFrame(
            {
                "cand": [np.nan] * 10,
                "regime_volatility": ["calm"] * 10,
                "momentum_z_fast": [np.nan] * 10,
                "return_fast": [np.nan] * 10,
            }
        )
        assert _joint_cell_uplifts(panel, "cand", "momentum_z_fast", {}) == []


class TestBestCellUplift:
    def test_picks_max_uplift_among_n_gate_eligible_cells_only(self):
        cells = [
            {"n": 100, "uplift_pct": 0.90},  # below N-gate -- excluded despite huge uplift
            {"n": 25_000, "uplift_pct": 0.15},
            {"n": 30_000, "uplift_pct": 0.25},  # eligible and largest -- must win
        ]
        best_uplift, best_cell = _best_cell_uplift(cells)
        assert best_uplift == 0.25
        assert best_cell["n"] == 30_000

    def test_none_when_no_cell_clears_n_gate(self):
        cells = [{"n": 500, "uplift_pct": 0.99}, {"n": 100, "uplift_pct": 0.50}]
        assert _best_cell_uplift(cells) == (None, None)

    def test_none_when_cell_list_empty(self):
        assert _best_cell_uplift([]) == (None, None)


class TestBuildPanelPermutation:
    def _synthetic_symbol_data(self, seed: int) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
        rng = np.random.default_rng(seed)
        n = 500
        idx = pd.date_range("2020-01-01", periods=n, freq="D")
        close = 100 * np.exp(np.cumsum(rng.normal(scale=0.01, size=n)))
        volume = rng.uniform(1e5, 1e6, size=n)
        ohlcv = pd.DataFrame({"close": close, "volume": volume}, index=idx)
        regime_vol = pd.Series(["calm"] * n, index=idx, name="regime_volatility")
        xbar = pd.DataFrame(
            {
                "momentum_z_fast": rng.normal(size=n),
                "momentum_z_mid": rng.normal(size=n),
                "return_fast": rng.normal(size=n),
            },
            index=idx,
        )
        return ohlcv, regime_vol, xbar

    def test_unpermuted_panel_is_reproducible_across_calls(self):
        ohlcv, regime_vol, xbar = self._synthetic_symbol_data(seed=1)
        panel_a = _build_panel(
            {"SPY": ohlcv}, {"SPY": regime_vol}, {"SPY": xbar}, "hurst_rank", None
        )
        panel_b = _build_panel(
            {"SPY": ohlcv}, {"SPY": regime_vol}, {"SPY": xbar}, "hurst_rank", None
        )
        pd.testing.assert_frame_equal(panel_a, panel_b)

    def test_permuted_panel_preserves_regime_and_return_index_but_shuffles_candidate(self):
        ohlcv, regime_vol, xbar = self._synthetic_symbol_data(seed=2)
        real_panel = _build_panel(
            {"SPY": ohlcv}, {"SPY": regime_vol}, {"SPY": xbar}, "hurst_rank", None
        )
        null_panel = _build_panel(
            {"SPY": ohlcv},
            {"SPY": regime_vol},
            {"SPY": xbar},
            "hurst_rank",
            np.random.default_rng(99),
        )
        # regime_volatility and return_fast are NEVER permuted -- same values, same index.
        pd.testing.assert_series_equal(
            real_panel["regime_volatility"], null_panel["regime_volatility"]
        )
        pd.testing.assert_series_equal(real_panel["return_fast"], null_panel["return_fast"])
        # The candidate column, recomputed from permuted close/volume, must differ.
        assert not real_panel["hurst_rank"].equals(null_panel["hurst_rank"])

    def test_two_different_seeds_produce_different_permutations(self):
        ohlcv, regime_vol, xbar = self._synthetic_symbol_data(seed=3)
        panel_a = _build_panel(
            {"SPY": ohlcv},
            {"SPY": regime_vol},
            {"SPY": xbar},
            "hurst_rank",
            np.random.default_rng(1),
        )
        panel_b = _build_panel(
            {"SPY": ohlcv},
            {"SPY": regime_vol},
            {"SPY": xbar},
            "hurst_rank",
            np.random.default_rng(2),
        )
        assert not panel_a["hurst_rank"].equals(panel_b["hurst_rank"])
