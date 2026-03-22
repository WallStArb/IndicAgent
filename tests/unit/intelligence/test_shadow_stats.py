"""Unit tests for shadow plugin stats monitoring (SHADOW-04, Phase 47).

Tests compute_shadow_plugin_stats() and _bootstrap_ci_lower() from weight_updater.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

UTC = timezone.utc
NOW = datetime(2026, 3, 22, 12, 0, 0, tzinfo=UTC)


def _make_row(
    outcome: str,
    pnl_r: float | None = None,
    plugin: str = "trad_DualDivergence",
    days_ago: int = 1,
) -> dict:
    """Build a minimal signal_ledger-like row dict."""
    signal_computed_at = datetime(2026, 3, 22 - days_ago, 12, 0, 0, tzinfo=UTC)
    return {
        "setup_plugin": plugin,
        "outcome": outcome,
        "pnl_r": pnl_r,
        "signal_computed_at": signal_computed_at,
    }


def _make_rows(
    n_wins: int,
    n_losses: int,
    pnl_r_win: float = 1.5,
    pnl_r_loss: float = -1.0,
    days_ago: int = 1,
) -> list[dict]:
    rows = []
    for _ in range(n_wins):
        rows.append(_make_row("target_1", pnl_r_win, days_ago=days_ago))
    for _ in range(n_losses):
        rows.append(_make_row("stopped_in_trade", pnl_r_loss, days_ago=days_ago))
    return rows


# ---------------------------------------------------------------------------
# _bootstrap_ci_lower tests
# ---------------------------------------------------------------------------


def test_bootstrap_ci_lower_returns_neg_inf_when_too_few_samples():
    from src.intelligence.weight_updater import _bootstrap_ci_lower

    result = _bootstrap_ci_lower([])
    assert result == float("-inf")

    result = _bootstrap_ci_lower([1.0] * 9)
    assert result == float("-inf")


def test_bootstrap_ci_lower_returns_positive_for_positive_values():
    from src.intelligence.weight_updater import _bootstrap_ci_lower

    # 100 large positive values → CI lower should also be positive
    result = _bootstrap_ci_lower([2.0] * 100)
    assert result > 0.0


def test_bootstrap_ci_lower_returns_negative_for_all_negative():
    from src.intelligence.weight_updater import _bootstrap_ci_lower

    result = _bootstrap_ci_lower([-1.5] * 100)
    assert result < 0.0


def test_bootstrap_ci_lower_mixed_returns_finite():
    from src.intelligence.weight_updater import _bootstrap_ci_lower

    # Mixed positive/negative — result should be finite (not inf/-inf)
    values = [1.0, -1.0] * 50
    result = _bootstrap_ci_lower(values)
    assert result != float("-inf")
    assert result != float("inf")


# ---------------------------------------------------------------------------
# compute_shadow_plugin_stats — 0-row case (Test 1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shadow_stats_zero_rows_emits_zeros():
    """0 resolved shadow signals → shadow_n_resolved=0, shadow_promotion_ready=0."""
    from src.intelligence.weight_updater import compute_shadow_plugin_stats

    db_manager = MagicMock()
    db_manager.execute_query = AsyncMock(return_value=[])

    # Patch the Prometheus gauges so we can inspect .set() calls
    with patch("src.observability.metrics.SHADOW_N_RESOLVED") as mock_n, \
         patch("src.observability.metrics.SHADOW_PROMOTION_READY") as mock_promo, \
         patch("src.observability.metrics.SHADOW_WIN_RATE") as mock_wr, \
         patch("src.observability.metrics.SHADOW_EV_R") as mock_ev, \
         patch("src.observability.metrics.SHADOW_EV_CI_LOWER") as mock_ci, \
         patch("src.observability.metrics.SHADOW_DAYS_TO_GATE") as mock_days:

        # Make .labels() return self for chaining .set()
        for mock in [mock_n, mock_promo, mock_wr, mock_ev, mock_ci, mock_days]:
            mock.labels.return_value = mock

        await compute_shadow_plugin_stats(db_manager)

        mock_n.labels.assert_called()
        mock_n.set.assert_called_with(0)
        mock_promo.set.assert_called_with(0)


# ---------------------------------------------------------------------------
# compute_shadow_plugin_stats — 50 resolved rows (Test 2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shadow_stats_50_rows_below_gate():
    """50 resolved rows (30 wins, 20 losses) → n_resolved=50, promotion_ready=0 (N < 100)."""
    from src.intelligence.weight_updater import compute_shadow_plugin_stats

    rows = _make_rows(n_wins=30, n_losses=20)
    db_manager = MagicMock()
    db_manager.execute_query = AsyncMock(return_value=rows)

    n_set_calls = []
    promo_set_calls = []
    wr_set_calls = []

    with patch("src.observability.metrics.SHADOW_N_RESOLVED") as mock_n, \
         patch("src.observability.metrics.SHADOW_PROMOTION_READY") as mock_promo, \
         patch("src.observability.metrics.SHADOW_WIN_RATE") as mock_wr, \
         patch("src.observability.metrics.SHADOW_EV_R") as mock_ev, \
         patch("src.observability.metrics.SHADOW_EV_CI_LOWER") as mock_ci, \
         patch("src.observability.metrics.SHADOW_DAYS_TO_GATE") as mock_days:

        for mock in [mock_n, mock_promo, mock_wr, mock_ev, mock_ci, mock_days]:
            mock.labels.return_value = mock
        mock_n.set.side_effect = lambda v: n_set_calls.append(v)
        mock_promo.set.side_effect = lambda v: promo_set_calls.append(v)
        mock_wr.set.side_effect = lambda v: wr_set_calls.append(v)

        await compute_shadow_plugin_stats(db_manager)

    assert 50 in n_set_calls, f"Expected n_resolved=50, got {n_set_calls}"
    assert 0 in promo_set_calls, f"Expected promotion_ready=0, got {promo_set_calls}"
    # Win rate = 30/50 = 0.6
    assert any(abs(v - 0.6) < 0.01 for v in wr_set_calls), (
        f"Expected win_rate~=0.6, got {wr_set_calls}"
    )


# ---------------------------------------------------------------------------
# compute_shadow_plugin_stats — 120 rows with positive CI lower (Test 3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shadow_stats_120_rows_positive_ci_emits_promotion_ready():
    """120 resolved rows, all positive pnl_r → promotion_ready=1."""
    from src.intelligence.weight_updater import compute_shadow_plugin_stats

    # 120 wins with large positive pnl_r → CI lower will be positive
    rows = _make_rows(n_wins=120, n_losses=0, pnl_r_win=2.0)
    db_manager = MagicMock()
    db_manager.execute_query = AsyncMock(return_value=rows)

    promo_set_calls = []

    with patch("src.observability.metrics.SHADOW_N_RESOLVED") as mock_n, \
         patch("src.observability.metrics.SHADOW_PROMOTION_READY") as mock_promo, \
         patch("src.observability.metrics.SHADOW_WIN_RATE") as mock_wr, \
         patch("src.observability.metrics.SHADOW_EV_R") as mock_ev, \
         patch("src.observability.metrics.SHADOW_EV_CI_LOWER") as mock_ci, \
         patch("src.observability.metrics.SHADOW_DAYS_TO_GATE") as mock_days:

        for mock in [mock_n, mock_promo, mock_wr, mock_ev, mock_ci, mock_days]:
            mock.labels.return_value = mock
        mock_promo.set.side_effect = lambda v: promo_set_calls.append(v)

        await compute_shadow_plugin_stats(db_manager)

    assert 1 in promo_set_calls, f"Expected promotion_ready=1 for 120 wins, got {promo_set_calls}"


# ---------------------------------------------------------------------------
# compute_shadow_plugin_stats — 120 rows with negative CI lower (Test 4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shadow_stats_120_rows_negative_ci_no_promotion():
    """120 resolved rows but CI lower <= 0 → promotion_ready=0."""
    from src.intelligence.weight_updater import compute_shadow_plugin_stats

    # Equal wins/losses + small magnitudes → EV_R near 0, CI lower will be negative
    rows = _make_rows(n_wins=60, n_losses=60, pnl_r_win=0.1, pnl_r_loss=-0.1)
    db_manager = MagicMock()
    db_manager.execute_query = AsyncMock(return_value=rows)

    promo_set_calls = []

    with patch("src.observability.metrics.SHADOW_N_RESOLVED") as mock_n, \
         patch("src.observability.metrics.SHADOW_PROMOTION_READY") as mock_promo, \
         patch("src.observability.metrics.SHADOW_WIN_RATE") as mock_wr, \
         patch("src.observability.metrics.SHADOW_EV_R") as mock_ev, \
         patch("src.observability.metrics.SHADOW_EV_CI_LOWER") as mock_ci, \
         patch("src.observability.metrics.SHADOW_DAYS_TO_GATE") as mock_days:

        for mock in [mock_n, mock_promo, mock_wr, mock_ev, mock_ci, mock_days]:
            mock.labels.return_value = mock
        mock_promo.set.side_effect = lambda v: promo_set_calls.append(v)

        await compute_shadow_plugin_stats(db_manager)

    assert 0 in promo_set_calls, f"Expected promotion_ready=0 (negative CI), got {promo_set_calls}"
    assert 1 not in promo_set_calls


# ---------------------------------------------------------------------------
# days_to_gate projection (Test 7)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shadow_stats_days_to_gate_calculation():
    """days_to_gate projects correctly: 5 signals in 30 days, gate at 100, need 95 more = 570d."""
    from src.intelligence.weight_updater import compute_shadow_plugin_stats

    # 5 recent signals (all within last 30 days)
    rows = _make_rows(n_wins=3, n_losses=2, days_ago=5)
    db_manager = MagicMock()
    db_manager.execute_query = AsyncMock(return_value=rows)

    days_set_calls = []

    with patch("src.observability.metrics.SHADOW_N_RESOLVED") as mock_n, \
         patch("src.observability.metrics.SHADOW_PROMOTION_READY") as mock_promo, \
         patch("src.observability.metrics.SHADOW_WIN_RATE") as mock_wr, \
         patch("src.observability.metrics.SHADOW_EV_R") as mock_ev, \
         patch("src.observability.metrics.SHADOW_EV_CI_LOWER") as mock_ci, \
         patch("src.observability.metrics.SHADOW_DAYS_TO_GATE") as mock_days:

        for mock in [mock_n, mock_promo, mock_wr, mock_ev, mock_ci, mock_days]:
            mock.labels.return_value = mock
        mock_days.set.side_effect = lambda v: days_set_calls.append(v)

        await compute_shadow_plugin_stats(db_manager)

    # 5 signals in 30 days → fire_rate_30d=5
    # remaining = max(0, 100 - 5) = 95
    # days_to_gate = (95/5)*30 = 570
    assert days_set_calls, "SHADOW_DAYS_TO_GATE.set() must be called"
    assert any(abs(v - 570.0) < 1.0 for v in days_set_calls), (
        f"Expected days_to_gate~=570, got {days_set_calls}"
    )
