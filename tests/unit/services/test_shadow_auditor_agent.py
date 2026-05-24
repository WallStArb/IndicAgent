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
    assert _tail_risk_blocks_promotion(-2.5, 0.8, -2.0, 0.5) == "skewness"


def test_tail_risk_blocks_when_recovery_too_low():
    assert _tail_risk_blocks_promotion(-1.0, 0.3, -2.0, 0.5) == "recovery_factor"


def test_tail_risk_blocks_when_both_below():
    # skewness is checked first; that reason is returned
    assert _tail_risk_blocks_promotion(-3.0, 0.1, -2.0, 0.5) == "skewness"


def test_tail_risk_passes_when_both_acceptable():
    assert _tail_risk_blocks_promotion(-1.5, 0.7, -2.0, 0.5) is None


def test_tail_risk_passes_when_skewness_none_recovery_ok():
    assert _tail_risk_blocks_promotion(None, 0.7, -2.0, 0.5) is None


def test_tail_risk_passes_when_recovery_none_skewness_ok():
    assert _tail_risk_blocks_promotion(-1.5, None, -2.0, 0.5) is None


def test_tail_risk_passes_when_both_none():
    assert _tail_risk_blocks_promotion(None, None, -2.0, 0.5) is None


def test_tail_risk_blocks_when_skewness_below_with_recovery_none():
    assert _tail_risk_blocks_promotion(-2.5, None, -2.0, 0.5) == "skewness"


def test_tail_risk_blocks_when_recovery_below_with_skewness_none():
    assert _tail_risk_blocks_promotion(None, 0.3, -2.0, 0.5) == "recovery_factor"


def test_tail_risk_passes_at_exact_skewness_threshold():
    # strict < semantics: equal to threshold does not block
    assert _tail_risk_blocks_promotion(-2.0, 0.7, -2.0, 0.5) is None


def test_tail_risk_passes_at_exact_recovery_threshold():
    # strict < semantics: equal to threshold does not block
    assert _tail_risk_blocks_promotion(-1.5, 0.5, -2.0, 0.5) is None


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


# ---------------------------------------------------------------------------
# Phase-105 regression: is_shadow filter direction in _check_promotion / _check_demotion
# ---------------------------------------------------------------------------


def test_promotion_query_filters_is_shadow_true():
    """_check_promotion SQL must filter is_shadow = TRUE.

    Promotion counts shadow observations (is_shadow=TRUE). Filtering for FALSE would
    count live observations instead, making the gate meaningless.

    Regression guard for Phase-105 Task 3 fix: shadow auditor filter direction.
    """
    import inspect

    import services.shadow_auditor_agent as mod

    source = inspect.getsource(mod._check_promotion)
    # Must contain is_shadow = TRUE (the shadow row filter for shadow signal observations)
    assert (
        "is_shadow = TRUE" in source
    ), "_check_promotion must filter 'is_shadow = TRUE' to count shadow observations"
    # Must NOT filter is_shadow = FALSE in the main promotion query
    assert (
        "is_shadow = FALSE" not in source
    ), "_check_promotion must NOT filter 'is_shadow = FALSE' (that is for demotion)"


def test_demotion_query_filters_is_shadow_false():
    """_check_demotion SQL must filter is_shadow = FALSE.

    Demotion counts live observations (is_shadow=FALSE). Filtering for TRUE would
    count shadow observations instead, making the EV[R] calculation wrong.

    Regression guard for Phase-105 Task 3 fix: shadow auditor filter direction.
    """
    import inspect

    import services.shadow_auditor_agent as mod

    source = inspect.getsource(mod._check_demotion)
    # Must contain is_shadow = FALSE (live-only observations for demotion gate)
    assert (
        "is_shadow = FALSE" in source
    ), "_check_demotion must filter 'is_shadow = FALSE' to count live observations"
    # Must NOT filter is_shadow = TRUE in the demotion query
    assert (
        "is_shadow = TRUE" not in source
    ), "_check_demotion must NOT filter 'is_shadow = TRUE' (that is for promotion)"


def test_run_audit_skips_swarm_agent_rows():
    """_run_audit() must skip registry rows with component_type == 'swarm_agent'.

    Swarm agents have no signal_ledger rows; evaluating them yields n=0 and would
    reset demotion_consecutive_count to 0 every cycle, neutralizing demotion.

    Regression guard for Phase-105: swarm agents are correctly skipped.
    """
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from services.shadow_auditor_agent import _run_audit

    # Build a mock registry with one swarm_agent and one i7_plugin
    swarm_row = {
        "component_name": "correlation_agent",
        "component_type": "swarm_agent",
        "is_shadow": True,
        "min_n": 100,
        "min_ev_r": 0.0,
        "ci_alpha": 0.05,
        "demotion_lookback_days": 30,
        "demotion_threshold_ev_r": -0.05,
        "demotion_min_evaluations": 3,
        "demotion_consecutive_count": 0,
    }
    plugin_row = {
        "component_name": "trad_TrendFollowing",
        "component_type": "i7_plugin",
        "is_shadow": True,
        "min_n": 100,
        "min_ev_r": 0.0,
        "ci_alpha": 0.05,
        "demotion_lookback_days": 30,
        "demotion_threshold_ev_r": -0.05,
        "demotion_min_evaluations": 3,
        "demotion_consecutive_count": 0,
    }

    # Make the rows support dict-style access (asyncpg Record API)
    def _make_mock_row(data: dict):
        row = MagicMock()
        row.__getitem__ = lambda self, k: data[k]
        row.get = lambda k, default=None: data.get(k, default)
        # Support iteration for dict(row) — asyncpg Records are iterable over (key, val) pairs
        row.items = MagicMock(return_value=data.items())
        row.keys = MagicMock(return_value=data.keys())
        row.values = MagicMock(return_value=data.values())
        # dict(row) works via mapping protocol — mock the __iter__ for key access
        row.__iter__ = lambda self: iter(data.keys())
        return row

    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(
        return_value=[_make_mock_row(swarm_row), _make_mock_row(plugin_row)]
    )

    acquire_cm = AsyncMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=mock_conn)
    acquire_cm.__aexit__ = AsyncMock(return_value=False)
    pool_mock = MagicMock()
    pool_mock.acquire = MagicMock(return_value=acquire_cm)

    check_promotion_calls = []
    check_demotion_calls = []

    async def fake_check_promotion(pool, env, row):
        check_promotion_calls.append(row["component_name"])

    async def fake_check_demotion(pool, env, row):
        check_demotion_calls.append(row["component_name"])

    with (
        patch("services.shadow_auditor_agent._check_promotion", side_effect=fake_check_promotion),
        patch("services.shadow_auditor_agent._check_demotion", side_effect=fake_check_demotion),
    ):
        asyncio.run(_run_audit(pool_mock, "test"))

    # The swarm agent must NOT have triggered any promotion/demotion check
    assert (
        "correlation_agent" not in check_promotion_calls
    ), "swarm_agent rows must be skipped — _check_promotion must not be called for them"
    assert (
        "correlation_agent" not in check_demotion_calls
    ), "swarm_agent rows must be skipped — _check_demotion must not be called for them"

    # The i7_plugin IS shadow (is_shadow=True) → _check_promotion should be called
    assert (
        "trad_TrendFollowing" in check_promotion_calls
    ), "is_shadow=True i7_plugin must trigger _check_promotion"


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
