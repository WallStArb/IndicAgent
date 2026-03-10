"""Failing tests (RED phase) for compute_setup_performance — FEED-01 + FEED-02.

These tests define the behavioral contract for the setup_performance_updater module
that will be created in Plan 02. All tests fail with ImportError in RED phase because
the target module does not exist yet.

FEED-01: compute_setup_performance returns win_rate, avg_pnl_r, sample_size, sharpe_ratio
         per setup_plugin, computed over resolved signals in a rolling 30-day window.
FEED-02: Promotion gate — setup_plugin with sample_size < 30 is excluded from result.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

# RED phase: this import will raise ImportError — module does not exist yet.
from src.intelligence.setup_performance_updater import compute_setup_performance

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_resolved_signal(
    setup_plugin: str,
    pnl_r: float | None,
    resolved_at: datetime | None = None,
    outcome: str = "target_1",
) -> dict:
    """Build a minimal resolved signal dict matching signal_ledger columns."""
    if resolved_at is None:
        resolved_at = datetime.now(UTC)
    return {
        "setup_plugin": setup_plugin,
        "pnl_r": pnl_r,
        "resolved_at": resolved_at,
        "outcome": outcome,
    }


def _recent_signals(plugin: str, pnl_r_values: list[float | None]) -> list[dict]:
    """Build a list of recently-resolved signals for a plugin."""
    return [_make_resolved_signal(plugin, v) for v in pnl_r_values]


# ---------------------------------------------------------------------------
# Module import test (fails RED with ImportError)
# ---------------------------------------------------------------------------

class TestModuleImport:
    @pytest.mark.unit
    def test_setup_performance_updater_module_importable(self):
        """compute_setup_performance is importable from setup_performance_updater.

        RED: fails with ImportError because the module does not exist yet.
        """
        # Import is at module level — reaching this line means import succeeded.
        assert callable(compute_setup_performance)


# ---------------------------------------------------------------------------
# FEED-01: compute_setup_performance output shape and correctness
# ---------------------------------------------------------------------------

class TestComputeSetupPerformanceBasicBehavior:
    @pytest.mark.unit
    def test_compute_setup_performance_empty_input(self):
        """Empty signal list returns empty dict."""
        result = compute_setup_performance([])
        assert result == {}

    @pytest.mark.unit
    def test_compute_setup_performance_at_threshold_included(self):
        """Exactly n=30 resolved signals returns a row with required keys."""
        signals = _recent_signals("trad_TrendFollowing", [0.5] * 30)
        result = compute_setup_performance(signals)
        assert "trad_TrendFollowing" in result
        row = result["trad_TrendFollowing"]
        assert "win_rate" in row
        assert "avg_pnl_r" in row
        assert "sample_size" in row
        assert "sharpe_ratio" in row

    @pytest.mark.unit
    def test_compute_setup_performance_above_threshold(self):
        """n=50 resolved signals returns a populated entry."""
        signals = _recent_signals("trad_MeanReversion", [1.0] * 30 + [-0.5] * 20)
        result = compute_setup_performance(signals)
        assert "trad_MeanReversion" in result
        row = result["trad_MeanReversion"]
        assert row["sample_size"] == 50

    @pytest.mark.unit
    def test_compute_setup_performance_win_rate_calculation(self):
        """20 wins (pnl_r > 0) out of 30 → win_rate == 20/30."""
        signals = _recent_signals(
            "trad_TrendFollowing",
            [1.0] * 20 + [-0.5] * 10,
        )
        result = compute_setup_performance(signals)
        assert "trad_TrendFollowing" in result
        assert result["trad_TrendFollowing"]["win_rate"] == pytest.approx(20 / 30)

    @pytest.mark.unit
    def test_compute_setup_performance_sharpe_ratio_nonzero(self):
        """30 signals with varying pnl_r → sharpe_ratio is a float (mean/std)."""
        import random
        random.seed(42)
        pnl_rs = [round(random.gauss(0.3, 1.0), 4) for _ in range(30)]
        signals = _recent_signals("trad_TrendFollowing", pnl_rs)
        result = compute_setup_performance(signals)
        assert "trad_TrendFollowing" in result
        sharpe = result["trad_TrendFollowing"]["sharpe_ratio"]
        assert isinstance(sharpe, float)

    @pytest.mark.unit
    def test_compute_setup_performance_multiple_setups(self):
        """Two setup_plugins each with n>=30 → both appear in result dict."""
        signals_a = _recent_signals("trad_TrendFollowing", [0.5] * 30)
        signals_b = _recent_signals("trad_MeanReversion", [0.3] * 35)
        result = compute_setup_performance(signals_a + signals_b)
        assert "trad_TrendFollowing" in result
        assert "trad_MeanReversion" in result


# ---------------------------------------------------------------------------
# FEED-02: Promotion gate — n < 30 is excluded
# ---------------------------------------------------------------------------

class TestPromotionGate:
    @pytest.mark.unit
    def test_compute_setup_performance_below_threshold_returns_empty(self):
        """n=25 resolved signals for a setup → returns empty dict (FEED-02 gate)."""
        signals = _recent_signals("trad_TrendFollowing", [1.0] * 25)
        result = compute_setup_performance(signals)
        assert result == {}

    @pytest.mark.unit
    def test_compute_setup_performance_mixed_threshold(self):
        """One setup n=30, another n=25 → only the n=30 setup appears in result."""
        signals_pass = _recent_signals("trad_TrendFollowing", [0.5] * 30)
        signals_fail = _recent_signals("trad_MeanReversion", [0.5] * 25)
        result = compute_setup_performance(signals_pass + signals_fail)
        assert "trad_TrendFollowing" in result
        assert "trad_MeanReversion" not in result


# ---------------------------------------------------------------------------
# Rolling 30-day window and null handling
# ---------------------------------------------------------------------------

class TestWindowAndNullHandling:
    @pytest.mark.unit
    def test_compute_setup_performance_30day_window(self):
        """Signals with resolved_at older than 30 days are excluded from sample_size."""
        old_resolved_at = datetime.now(UTC) - timedelta(days=31)
        # 25 old signals (excluded) + 30 recent signals = 30 eligible
        old_signals = [
            _make_resolved_signal("trad_TrendFollowing", 1.0, resolved_at=old_resolved_at)
            for _ in range(25)
        ]
        recent_signals = _recent_signals("trad_TrendFollowing", [0.5] * 30)
        result = compute_setup_performance(old_signals + recent_signals)
        # Should be included (30 recent meet threshold)
        assert "trad_TrendFollowing" in result
        # Old signals are excluded so sample_size == 30, not 55
        assert result["trad_TrendFollowing"]["sample_size"] == 30

    @pytest.mark.unit
    def test_compute_setup_performance_null_pnl_r_excluded(self):
        """Rows with pnl_r=None are not counted toward sample_size."""
        # 10 None + 30 valid = 30 eligible (None rows excluded)
        signals = _recent_signals(
            "trad_TrendFollowing",
            [None] * 10 + [1.0] * 30,
        )
        result = compute_setup_performance(signals)
        assert "trad_TrendFollowing" in result
        assert result["trad_TrendFollowing"]["sample_size"] == 30
