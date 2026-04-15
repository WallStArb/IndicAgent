"""Unit tests for shadow plugin stats monitoring (SHADOW-04, Phase 47).

Tests compute_shadow_plugin_stats() and _bootstrap_ci_lower() from weight_updater.
"""
from __future__ import annotations

from datetime import UTC, datetime

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

UTC = UTC
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


