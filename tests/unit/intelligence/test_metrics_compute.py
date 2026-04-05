"""Tests for compute_signal_metrics and compute_ic_metrics."""
from datetime import UTC, datetime, timedelta

import pytest

from src.intelligence.metrics.compute import (
    HMM_TO_REGIME,
    MIN_SAMPLE_SIZE,
    compute_signal_metrics,
    compute_ic_metrics,
)


def _make_row(
    setup_plugin="trad_TrendFollowing",
    tf="5m",
    hmm_regime=1,
    direction=1,
    entry_price=5000.0,
    stop_loss=4999.0,
    pnl_r=1.0,
    mae=-0.3,
    mfe=1.5,
    outcome="target_1",
    confidence=0.75,
    signal_id="00000000-0000-0000-0000-000000000001",
    exit_at=None,
    market_entry_pnl_r=0.8,
    market_entry_mae=-0.2,
    market_entry_mfe=1.2,
    market_entry_outcome="target_1",
    days_ago=5,
):
    if exit_at is None:
        exit_at = datetime.now(UTC) - timedelta(days=days_ago)
    return {
        "signal_id": signal_id,
        "setup_plugin": setup_plugin,
        "tf": tf,
        "hmm_regime_at_fire": hmm_regime,
        "direction": direction,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "pnl_r": pnl_r,
        "mae": mae,
        "mfe": mfe,
        "outcome": outcome,
        "confidence": confidence,
        "exit_at": exit_at,
        "market_entry_pnl_r": market_entry_pnl_r,
        "market_entry_mae": market_entry_mae,
        "market_entry_mfe": market_entry_mfe,
        "market_entry_outcome": market_entry_outcome,
    }


class TestHmmToRegimeMapping:
    def test_regime_0_is_mean_reversion(self):
        assert HMM_TO_REGIME[0] == "mean_reversion"

    def test_regime_1_is_trend(self):
        assert HMM_TO_REGIME[1] == "trend"

    def test_regime_2_is_trend(self):
        assert HMM_TO_REGIME[2] == "trend"


class TestComputeSignalMetrics:
    def _make_n_rows(self, n, pnl_r=1.0, outcome="target_1", hmm_regime=1):
        return [_make_row(pnl_r=pnl_r, outcome=outcome, hmm_regime=hmm_regime)
                for _ in range(n)]

    def test_returns_empty_when_insufficient_n(self):
        rows = self._make_n_rows(MIN_SAMPLE_SIZE - 1)
        result = compute_signal_metrics(rows, track="zone", window_days=30)
        assert result == []

    def test_returns_row_when_n_meets_minimum(self):
        rows = self._make_n_rows(MIN_SAMPLE_SIZE)
        result = compute_signal_metrics(rows, track="zone", window_days=30)
        # Expect per-regime row + 'all' rollup
        assert len(result) == 2

    def test_all_rollup_row_present(self):
        rows = self._make_n_rows(MIN_SAMPLE_SIZE)
        result = compute_signal_metrics(rows, track="zone", window_days=30)
        regime_types = {r.regime_type for r in result}
        assert "all" in regime_types

    def test_win_rate_all_wins(self):
        rows = self._make_n_rows(MIN_SAMPLE_SIZE, pnl_r=1.0, outcome="target_1")
        result = compute_signal_metrics(rows, track="zone", window_days=30)
        all_row = next(r for r in result if r.regime_type == "all")
        assert all_row.win_rate == pytest.approx(1.0, abs=0.001)

    def test_win_rate_all_losses(self):
        rows = self._make_n_rows(MIN_SAMPLE_SIZE, pnl_r=-1.0, outcome="stopped_in_trade")
        result = compute_signal_metrics(rows, track="zone", window_days=30)
        all_row = next(r for r in result if r.regime_type == "all")
        assert all_row.win_rate == pytest.approx(0.0, abs=0.001)

    def test_never_activated_pct_counted(self):
        # 30 valid rows + 10 never-activated (pnl_r=None, outcome=never_activated)
        valid = self._make_n_rows(MIN_SAMPLE_SIZE, pnl_r=1.0, outcome="target_1")
        never_act = [_make_row(pnl_r=None, outcome="never_activated")
                     for _ in range(10)]
        result = compute_signal_metrics(valid + never_act, track="zone", window_days=30)
        all_row = next(r for r in result if r.regime_type == "all")
        assert all_row.never_activated_pct == pytest.approx(10 / 40, abs=0.01)

    def test_dq_invalid_rows_excluded_and_counted(self):
        # 30 valid + 5 with bad risk (should be caught by validator -> n_outliers)
        valid = self._make_n_rows(MIN_SAMPLE_SIZE)
        bad = [_make_row(entry_price=5000.0, stop_loss=5000.01, pnl_r=-193.0)
               for _ in range(5)]
        result = compute_signal_metrics(valid + bad, track="zone", window_days=30)
        all_row = next(r for r in result if r.regime_type == "all")
        assert all_row.n == MIN_SAMPLE_SIZE
        assert all_row.n_outliers == 5

    def test_market_track_uses_market_entry_fields(self):
        rows = self._make_n_rows(MIN_SAMPLE_SIZE, pnl_r=-2.0)
        # market_entry_pnl_r defaults to 0.8 in _make_row
        result = compute_signal_metrics(rows, track="market", window_days=30)
        all_row = next(r for r in result if r.regime_type == "all")
        assert all_row.avg_r == pytest.approx(0.8, abs=0.01)

    def test_track_field_set_correctly(self):
        rows = self._make_n_rows(MIN_SAMPLE_SIZE)
        zone = compute_signal_metrics(rows, track="zone", window_days=30)
        market = compute_signal_metrics(rows, track="market", window_days=30)
        assert all(r.track == "zone" for r in zone)
        assert all(r.track == "market" for r in market)

    def test_multiple_regimes_produce_separate_rows(self):
        trend_rows = self._make_n_rows(MIN_SAMPLE_SIZE, hmm_regime=1)
        mr_rows = self._make_n_rows(MIN_SAMPLE_SIZE, hmm_regime=0)
        result = compute_signal_metrics(trend_rows + mr_rows, track="zone", window_days=30)
        regime_types = {r.regime_type for r in result}
        assert "trend" in regime_types
        assert "mean_reversion" in regime_types
        assert "all" in regime_types


class TestComputeIcMetrics:
    def _make_ic_rows(self, n, confidence=0.7, outcome="target_1"):
        return [_make_row(confidence=confidence, outcome=outcome) for _ in range(n)]

    def test_returns_empty_when_insufficient_n(self):
        rows = self._make_ic_rows(MIN_SAMPLE_SIZE - 1)
        result = compute_ic_metrics(rows, window_days=30)
        assert result == []

    def test_returns_row_when_n_meets_minimum(self):
        # Mix wins and losses with varying confidence to get non-trivial IC
        wins = [_make_row(confidence=0.8, outcome="target_1") for _ in range(20)]
        losses = [_make_row(confidence=0.4, outcome="stopped_in_trade") for _ in range(20)]
        result = compute_ic_metrics(wins + losses, window_days=30)
        assert len(result) >= 1

    def test_ic_row_has_required_fields(self):
        wins = [_make_row(confidence=0.8, outcome="target_1") for _ in range(20)]
        losses = [_make_row(confidence=0.4, outcome="stopped_in_trade") for _ in range(20)]
        result = compute_ic_metrics(wins + losses, window_days=30)
        row = result[0]
        assert row.setup_plugin == "trad_TrendFollowing"
        assert row.tf == "5m"
        assert row.window_days == 30
        assert row.n >= MIN_SAMPLE_SIZE
