"""Unit tests for ShadowAuditorAgent gate logic.

Note: Promotion tests removed in Phase 120 (Plan 02). Promotion now lives in
shadow_validator.py. Remaining tests cover demotion-only path.
"""

from __future__ import annotations

import asyncio
import dataclasses
from unittest.mock import AsyncMock, MagicMock, patch

from services.shadow_auditor import (
    _ev_r_below_threshold,
    _should_demote,
)
from src.core.stats_utils import bootstrap_ci_lower
from src.intelligence.schemas import ShadowTransitionEvent


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
# Phase-105 regression: is_shadow filter direction in _check_demotion
# ---------------------------------------------------------------------------


def test_demotion_query_filters_is_shadow_false():
    """_check_demotion SQL must filter is_shadow = FALSE.

    Demotion counts live observations (is_shadow=FALSE). Filtering for TRUE would
    count shadow observations instead, making the EV[R] calculation wrong.

    Regression guard for Phase-105 Task 3 fix: shadow auditor filter direction.
    """
    import inspect

    import services.shadow_auditor as mod

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

    from services.shadow_auditor import _run_audit

    # Build a mock registry with one swarm_agent and one live i7_plugin
    swarm_row = {
        "component_name": "correlation_agent",
        "component_type": "swarm_agent",
        "is_shadow": False,
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
        "is_shadow": False,
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

    check_demotion_calls = []

    async def fake_check_demotion(pool, env, row):
        check_demotion_calls.append(row["component_name"])

    with patch("services.shadow_auditor._check_demotion", side_effect=fake_check_demotion):
        asyncio.run(_run_audit(pool_mock, "test"))

    # The swarm agent must NOT have triggered any demotion check
    assert (
        "correlation_agent" not in check_demotion_calls
    ), "swarm_agent rows must be skipped — _check_demotion must not be called for them"

    # The live i7_plugin must trigger _check_demotion (is_shadow=False)
    assert (
        "trad_TrendFollowing" in check_demotion_calls
    ), "live (is_shadow=False) i7_plugin must trigger _check_demotion"
