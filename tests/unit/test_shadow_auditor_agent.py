"""Unit tests for ShadowAuditorAgent gate logic."""

from __future__ import annotations

import asyncio
import dataclasses
from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg

from services.shadow_auditor_agent import (
    TAIL_GATE_MIN_RECOVERY,
    TAIL_GATE_MIN_SKEWNESS,
    _check_promotion,
    _ev_r_below_threshold,
    _should_demote,
    _should_promote,
    _tail_risk_blocks_promotion,
)
from src.core.stats_utils import bootstrap_ci_lower
from src.intelligence.schemas import ShadowTransitionEvent


def test_promotion_gate_passes_when_n_and_ci_met():
    assert _should_promote(n=150, ci_lower=0.02, min_n=100, min_ev_r=0.0) is True


def test_promotion_gate_fails_when_n_insufficient():
    assert _should_promote(n=50, ci_lower=0.05, min_n=100, min_ev_r=0.0) is False


def test_promotion_gate_fails_when_ci_lower_insufficient():
    assert _should_promote(n=150, ci_lower=-0.01, min_n=100, min_ev_r=0.0) is False


def test_demotion_increments_consecutive_count():
    # count was 1, now becomes 2; min_evaluations=3 — not yet demoted
    assert _should_demote(new_count=2, min_evaluations=3) is False


def test_demotion_triggers_at_min_evaluations():
    assert _should_demote(new_count=3, min_evaluations=3) is True


def test_demotion_resets_count_on_recovery():
    # ev_r=0.05 is above threshold -0.05 — not below — count resets
    assert _ev_r_below_threshold(ev_r=0.05, threshold=-0.05) is False


def test_ev_r_below_threshold_returns_true_when_degraded():
    assert _ev_r_below_threshold(ev_r=-0.10, threshold=-0.05) is True


def test_bootstrap_ci_lower_returns_neg_inf_on_empty():
    assert bootstrap_ci_lower([]) == float("-inf")


def test_shadow_transition_event_serializable():
    event = ShadowTransitionEvent(
        component_name="test_plugin",
        component_type="i7_plugin",
        from_state="shadow",
        to_state="live",
        trigger_reason="promotion_gate_cleared",
        n=150,
        ev_r=0.12,
        ci_lower=0.02,
        win_rate=0.58,
        triggered_at="2026-04-29T12:00:00.000Z",
    )
    d = dataclasses.asdict(event)
    assert d["component_name"] == "test_plugin"
    assert d["from_state"] == "shadow"
    assert d["to_state"] == "live"
    assert d["n"] == 150


# ---------------------------------------------------------------------------
# _tail_risk_blocks_promotion — pure function tests
# ---------------------------------------------------------------------------


def test_tail_risk_blocks_when_skewness_too_negative():
    assert _tail_risk_blocks_promotion(-2.5, 0.8, -2.0, 0.5) is True


def test_tail_risk_blocks_when_recovery_too_low():
    assert _tail_risk_blocks_promotion(-1.0, 0.3, -2.0, 0.5) is True


def test_tail_risk_blocks_when_both_below():
    assert _tail_risk_blocks_promotion(-3.0, 0.1, -2.0, 0.5) is True


def test_tail_risk_passes_when_both_acceptable():
    assert _tail_risk_blocks_promotion(-1.5, 0.7, -2.0, 0.5) is False


def test_tail_risk_passes_when_skewness_none_recovery_ok():
    assert _tail_risk_blocks_promotion(None, 0.7, -2.0, 0.5) is False


def test_tail_risk_passes_when_recovery_none_skewness_ok():
    assert _tail_risk_blocks_promotion(-1.5, None, -2.0, 0.5) is False


def test_tail_risk_passes_when_both_none():
    assert _tail_risk_blocks_promotion(None, None, -2.0, 0.5) is False


def test_tail_risk_blocks_when_skewness_below_with_recovery_none():
    assert _tail_risk_blocks_promotion(-2.5, None, -2.0, 0.5) is True


def test_tail_risk_blocks_when_recovery_below_with_skewness_none():
    assert _tail_risk_blocks_promotion(None, 0.3, -2.0, 0.5) is True


def test_tail_risk_passes_at_exact_skewness_threshold():
    # strict < semantics: equal to threshold does not block
    assert _tail_risk_blocks_promotion(-2.0, 0.7, -2.0, 0.5) is False


def test_tail_risk_passes_at_exact_recovery_threshold():
    # strict < semantics: equal to threshold does not block
    assert _tail_risk_blocks_promotion(-1.5, 0.5, -2.0, 0.5) is False


def test_module_constants_match_locked_thresholds():
    assert TAIL_GATE_MIN_SKEWNESS == -2.0
    assert TAIL_GATE_MIN_RECOVERY == 0.5


# ---------------------------------------------------------------------------
# _check_promotion fail-open: DB error on tail gate fetchrow does not propagate
# ---------------------------------------------------------------------------


def _make_signal_row(outcome: str = "target_1", pnl_r: float = 0.5):
    """Return a dict-like object simulating an asyncpg Record row."""
    row = MagicMock()
    row.__getitem__ = lambda self, key: {
        "outcome": outcome,
        "pnl_r": pnl_r,
        "signal_computed_at": None,
    }[key]
    row.get = lambda key, default=None: {
        "outcome": outcome,
        "pnl_r": pnl_r,
        "signal_computed_at": None,
    }.get(key, default)
    return row


def test_check_promotion_fails_open_when_tail_gate_db_query_raises():
    """DB error inside tail gate fetchrow must not propagate; gate is skipped (fail-open)."""

    # Build a minimal shadow_registry row dict
    registry_row = {
        "component_name": "test_plugin",
        "component_type": "i7_plugin",
        "min_n": 10,
        "min_ev_r": 0.0,
        "ci_alpha": 0.05,
    }

    # conn.fetch (signal_ledger query) returns one winning row
    signal_row = _make_signal_row(outcome="target_1", pnl_r=0.05)
    conn_mock = AsyncMock()
    conn_mock.fetch = AsyncMock(return_value=[signal_row])
    # fetchrow raises to simulate DB error on tail-gate query
    conn_mock.fetchrow = AsyncMock(side_effect=asyncpg.PostgresError("simulated DB down"))
    conn_mock.execute = AsyncMock(return_value=None)

    # pool.acquire() is an async context manager returning conn_mock
    acquire_cm = AsyncMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=conn_mock)
    acquire_cm.__aexit__ = AsyncMock(return_value=False)
    pool_mock = MagicMock()
    pool_mock.acquire = MagicMock(return_value=acquire_cm)

    with (
        patch("services.shadow_auditor_agent.SHADOW_TAIL_GATE_DB_ERROR") as mock_db_err_counter,
        patch("services.shadow_auditor_agent.SHADOW_TAIL_RISK_BLOCKED") as mock_blocked_counter,
        patch("services.shadow_auditor_agent.SHADOW_N_RESOLVED"),
        patch("services.shadow_auditor_agent.SHADOW_WIN_RATE"),
        patch("services.shadow_auditor_agent.SHADOW_EV_R"),
        patch("services.shadow_auditor_agent.SHADOW_EV_CI_LOWER"),
        patch("services.shadow_auditor_agent.SHADOW_DAYS_TO_GATE"),
        patch("services.shadow_auditor_agent.SHADOW_PROMOTION_READY"),
    ):
        # Must not raise
        asyncio.run(_check_promotion(pool_mock, "test", registry_row))

        # DB error counter must have been incremented
        mock_db_err_counter.add.assert_called_once()
        call_args = mock_db_err_counter.add.call_args
        assert call_args[0][0] == 1
        assert call_args[0][1].get("plugin") == "test_plugin"

        # Tail-risk-blocked counter must NOT have been incremented (gate was skipped)
        mock_blocked_counter.add.assert_not_called()
