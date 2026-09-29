"""Unit tests for todo 445's 5m-over-15m incremental IC script: every pure function
on synthetic numpy arrays, no DB. See scripts/research/todo445_5m_incremental_ic.py
for the pre-stated design and decision rule these functions implement."""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest

from scripts.research import todo445_5m_incremental_ic as mod


class TestAligned5mBarTs:
    def test_returns_ts_plus_10_minutes(self):
        ts = np.array(["2024-01-02T14:30", "2024-01-02T14:45"], dtype="datetime64[m]")
        out = mod.aligned_5m_bar_ts(ts)
        expected = ts + np.timedelta64(10, "m")
        assert np.array_equal(out, expected)

    def test_never_returns_ts_itself(self):
        ts = np.array(["2024-01-02T14:30"], dtype="datetime64[m]")
        out = mod.aligned_5m_bar_ts(ts)
        assert out[0] != ts[0]


class TestFeatureColumns:
    def test_keeps_only_real_minus_excluded_classes(self):
        schema_rows = [
            ("momentum_z_5", "real"),
            ("range_to_close", "real"),
            ("hmm_vol_churn", "real"),
            ("canary_price_sanity", "real"),
            ("regime_volatility", "real"),
            ("regime", "text"),
            ("rsi_velocity_fast", "real"),
            ("momentum_rank_z", "real"),
            ("bar_ts", "timestamp with time zone"),
            ("symbol", "character varying"),
            ("feature_vector_id", "uuid"),
        ]
        out = mod.feature_columns(schema_rows)
        assert out == ["momentum_z_5", "range_to_close"]


class TestRanksByRow:
    def test_scales_to_0_1_and_preserves_nan(self):
        x = np.array([[1.0, 3.0, 2.0, np.nan], [np.nan, np.nan, 1.0, np.nan]])
        out = mod.ranks_by_row(x)
        assert out[0, 0] == pytest.approx(0.0)
        assert out[0, 2] == pytest.approx(0.5)
        assert out[0, 1] == pytest.approx(1.0)
        assert np.isnan(out[0, 3])
        # Row 1 has only 1 finite value -- no cross-section to rank.
        assert np.isnan(out[1]).all()


class TestPartialRankIcPerBar:
    def _synthetic(self, seed: int, n_bars: int = 300, m_names: int = 50):
        rng = np.random.default_rng(seed)
        x15_raw = rng.normal(size=(n_bars, m_names))
        noise = rng.normal(size=(n_bars, m_names))
        x5_raw = x15_raw + noise
        return x15_raw, x5_raw

    def test_no_incremental_signal_gives_partial_ic_near_zero(self):
        x15_raw, x5_raw = self._synthetic(seed=0)
        rng = np.random.default_rng(99)
        # y depends on x15 plus its OWN independent noise (not x5's noise, and not
        # identical to x15) -- a well-defined partial correlation once residualized,
        # not the 0/0 degeneracy of y being bit-identical to x15.
        y_raw = x15_raw + rng.normal(size=x15_raw.shape)
        x5 = mod.ranks_by_row(x5_raw)
        x15 = mod.ranks_by_row(x15_raw)
        y = mod.ranks_by_row(y_raw)
        ic = mod.partial_rank_ic_per_bar(x5, x15, y)
        assert abs(np.nanmean(ic)) < 0.02

    def test_incremental_signal_gives_clearly_positive_partial_ic(self):
        x15_raw, x5_raw = self._synthetic(seed=1)
        y_raw = x5_raw - x15_raw  # target depends only on the 5m residual
        x5 = mod.ranks_by_row(x5_raw)
        x15 = mod.ranks_by_row(x15_raw)
        y = mod.ranks_by_row(y_raw)
        ic = mod.partial_rank_ic_per_bar(x5, x15, y)
        assert np.nanmean(ic) > 0.1

    def test_bar_under_min_names_returns_nan(self):
        rng = np.random.default_rng(2)
        n_bars, m_names = 5, 10
        x15_raw = rng.normal(size=(n_bars, m_names))
        x5_raw = x15_raw + rng.normal(size=(n_bars, m_names))
        y_raw = rng.normal(size=(n_bars, m_names))
        # Bar 0 has only 3 names finite; the rest have all 10.
        x15_raw[0, 3:] = np.nan
        x5_raw[0, 3:] = np.nan
        y_raw[0, 3:] = np.nan
        x5 = mod.ranks_by_row(x5_raw)
        x15 = mod.ranks_by_row(x15_raw)
        y = mod.ranks_by_row(y_raw)
        ic = mod.partial_rank_ic_per_bar(x5, x15, y, min_names=5)
        assert np.isnan(ic[0])
        assert not np.isnan(ic[1])


class TestSessionHacT:
    def test_mean_is_the_per_session_average_ignoring_nan_bars(self):
        # 2 sessions, 3 bars each. Session 0: [1.0, NaN, 3.0] -> mean 2.0.
        # Session 1: [0.0, 0.0, 0.0] -> mean 0.0.
        bar_ics = np.array([1.0, np.nan, 3.0, 0.0, 0.0, 0.0])
        session = np.array([0, 0, 0, 1, 1, 1])
        mean, t, p, n_sessions = mod.session_hac_t(bar_ics, session, max_lag=1)
        assert n_sessions == 2
        assert mean == pytest.approx((2.0 + 0.0) / 2)

    def test_all_nan_session_is_excluded_from_n_sessions(self):
        bar_ics = np.array([np.nan, np.nan, 1.0, 1.0, 2.0, 2.0])
        session = np.array([0, 0, 1, 1, 2, 2])
        _, _, _, n_sessions = mod.session_hac_t(bar_ics, session, max_lag=1)
        assert n_sessions == 2

    def test_too_few_sessions_returns_nan(self):
        bar_ics = np.array([1.0])
        session = np.array([0])
        mean, t, p, n_sessions = mod.session_hac_t(bar_ics, session)
        assert n_sessions == 1
        assert np.isnan(mean) and np.isnan(t) and np.isnan(p)


class TestRankTurnover:
    def test_mean_absolute_change_ignoring_nan(self):
        # 7 rows clears the n > horizon_bars + 5 guard. Full flip every row: every
        # abs diff at horizon 1 is exactly 1.0.
        ranks = np.array([[0.0, 1.0], [1.0, 0.0]] * 3 + [[0.0, 1.0]])
        out = mod.rank_turnover(ranks, horizon_bars=1)
        assert out == pytest.approx(1.0)

    def test_too_few_bars_returns_none(self):
        ranks = np.zeros((3, 2))
        assert mod.rank_turnover(ranks, horizon_bars=10) is None


class TestIcMin:
    def test_reproduces_0b_formula_on_a_hand_computed_case(self):
        turnover, horizon_bars, bars_per_year, lib_rank, breadth = 0.4, 10, 6552.0, 3.0, 4.5
        # Independently recomputed from the 0b formula components, not via mod.ic_min.
        one_way = 0.00014 / 2 + 0.0035 / 50.0
        rebal_per_year = bars_per_year / horizon_bars
        drag = rebal_per_year * 2 * turnover * one_way
        expected = drag / (0.16 * np.sqrt(lib_rank * breadth))
        out = mod.ic_min(turnover, horizon_bars, bars_per_year, lib_rank, breadth)
        assert out == pytest.approx(expected, rel=1e-9)


class TestBhFdrExcludingNan:
    def test_nan_entries_excluded_from_family_never_reject_never_corrupt_others(self):
        # Mixing NaN into statsmodels' multipletests directly corrupts every
        # p_corrected to NaN (confirmed live on the 186-07 run, 14/480 NaN
        # cells). This must exclude the NaN entries from the family entirely.
        p_values = [0.001, 0.5, float("nan"), 0.02, 0.8, float("nan"), 0.006]
        reject, p_corr = mod.bh_fdr_excluding_nan(p_values, alpha=0.05)
        assert reject[2] is False and reject[5] is False
        assert np.isnan(p_corr[2]) and np.isnan(p_corr[5])
        # The finite entries must have real, non-NaN corrected p-values.
        finite_positions = [0, 1, 3, 4, 6]
        for i in finite_positions:
            assert not np.isnan(p_corr[i]), f"index {i} corrupted by the NaN entries"
        # The three smallest real p-values (0.001, 0.02, 0.006) should reject.
        assert reject[0] is True and reject[3] is True and reject[6] is True
        assert reject[1] is False and reject[4] is False

    def test_all_nan_returns_all_false_no_crash(self):
        reject, p_corr = mod.bh_fdr_excluding_nan([float("nan"), float("nan")], alpha=0.05)
        assert reject == [False, False]
        assert all(np.isnan(p) for p in p_corr)

    def test_empty_returns_empty(self):
        reject, p_corr = mod.bh_fdr_excluding_nan([], alpha=0.05)
        assert reject == []
        assert p_corr == []


class TestDecide:
    def test_empty_cells_is_drop_5m(self):
        decision, names = mod.decide([])
        assert decision == "drop_5m"
        assert names == []

    def test_no_passing_cell_is_drop_5m(self):
        cells = [
            {"feature": "a", "bh_reject": True, "cost_clears": False},
            {"feature": "b", "bh_reject": False, "cost_clears": True},
        ]
        decision, names = mod.decide(cells)
        assert decision == "drop_5m"
        assert names == []

    def test_one_passing_cell_is_keep_5m_with_that_feature(self):
        cells = [
            {"feature": "a", "bh_reject": True, "cost_clears": False},
            {"feature": "b", "bh_reject": True, "cost_clears": True},
            {"feature": "b", "bh_reject": False, "cost_clears": False},
        ]
        decision, names = mod.decide(cells)
        assert decision == "keep_5m"
        assert names == ["b"]


class TestAssertWithinOosStart:
    def test_passes_when_end_exclusive_before_oos_start(self):
        mod.assert_within_oos_start(
            {"end_exclusive": "2020-01-01T00:00:00", "oos_start": "2025-12-24T05:15:00+00:00"}
        )

    def test_raises_when_end_exclusive_past_oos_start(self):
        with pytest.raises(ValueError):
            mod.assert_within_oos_start(
                {
                    "end_exclusive": "2026-01-01T00:00:00+00:00",
                    "oos_start": "2025-12-24T05:15:00+00:00",
                }
            )


class TestBuildTargets:
    def test_calls_forward_returns_with_session_and_never_closes(self):
        opens = np.ones((10, 3))
        session = np.repeat(np.arange(5), 2)
        with patch.object(
            mod.panel_mod, "forward_returns", wraps=mod.panel_mod.forward_returns
        ) as spy:
            mod.build_targets(opens, session, horizons=(1, 2))
        assert spy.call_count == 2
        for call in spy.call_args_list:
            assert "closes" not in call.kwargs
            assert call.kwargs.get("session") is session
