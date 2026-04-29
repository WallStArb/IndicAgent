"""Unit tests for ShadowAuditorAgent gate logic."""

from __future__ import annotations

import dataclasses

from services.shadow_auditor_agent import (
    _ev_r_below_threshold,
    _should_demote,
    _should_promote,
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
    # count was 1, now becomes 2; min_evaluations=3 → not yet demoted
    assert _should_demote(new_count=2, min_evaluations=3) is False


def test_demotion_triggers_at_min_evaluations():
    assert _should_demote(new_count=3, min_evaluations=3) is True


def test_demotion_resets_count_on_recovery():
    # ev_r=0.05 is above threshold -0.05 → not below → count resets
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
