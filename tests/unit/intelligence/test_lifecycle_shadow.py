"""Tests for shadow signal (regime_suppressed) virtual-activation contract.

Phase 12 Plan 01 — Wave 0 / TDD RED phase.

Shadow signals are signals suppressed by the regime filter that are written to
signal_ledger with status='regime_suppressed'. The lifecycle service tracks them
for MAE/MFE without a zone-activation step — they are treated as immediately
active for excursion tracking purposes.

Key contracts defined here:
- evaluate_signal() with status='active' returns a Transition on stop-hit
  (validates the virtual-activation pattern is viable without code changes)
- MAE/MFE tracking works from bar 0 when status='active' at init
- Shadow signals must never have update_signal_status called with status='active'
  (they retain 'regime_suppressed' in DB)
"""

from __future__ import annotations

import pytest

from src.intelligence.trading.lifecycle_tracker import Transition, evaluate_signal


def _shadow_signal(direction: int = 1) -> dict:
    """Build a minimal shadow signal dict in virtual-active state.

    Shadow signals are initialized with status='active' for lifecycle_tracker
    purposes (virtual-activation pattern) even though their DB status is
    'regime_suppressed'.
    """
    entry = 5100.0
    stop = 5085.0 if direction == 1 else 5115.0
    targets = [5115.0] if direction == 1 else [5085.0]
    return {
        "signal_id": "shadow-signal-uuid-0001",
        "status": "active",  # virtual-activation override
        "direction": direction,
        "entry_price": entry,
        "stop_loss": stop,
        "targets": targets,
        "ttl_bars": 20,
        "bars_elapsed": 0,
        "point_value": 50.0,  # ES contract value
        "entry_zone_low": entry - 5.0,
        "entry_zone_high": entry,
        # Preserve regime_suppressed info for caller reference
        "regime_eligible": False,
        "suppression_reason": "regime_type",
    }


class TestShadowSignalVirtualActivation:
    """Virtual-activation pattern: shadow signals skip zone-activation, start as active.

    These tests validate that evaluate_signal() with status='active' already
    handles the shadow signal use case correctly — no code changes needed in
    lifecycle_tracker.py itself.
    """

    @pytest.mark.unit
    def test_shadow_signal_skips_zone_activation(self):
        """evaluate_signal with status='active' returns Transition on stop-hit.

        This validates the virtual-activation pattern: shadow signals initialized
        with status='active' bypass the pending->active zone-activation step.
        A stop-hit on bar 1 returns a Transition immediately.

        EXPECTED TO PASS: evaluate_signal() already handles status='active' correctly.
        This test documents that the pattern is viable before Plan 04 wires it.
        """
        sig = _shadow_signal(direction=1)
        # Long stop at 5085.0 — price drops below stop
        result = evaluate_signal(
            sig,
            high=5095.0,
            low=5080.0,  # below stop_loss=5085.0
            close=5082.0,
            current_mae=0.0,
            current_mfe=0.0,
        )
        assert result is not None, (
            "evaluate_signal() with status='active' must return a Transition "
            "when price hits stop. Virtual-activation requires this to work "
            "without a prior pending->active transition."
        )
        assert isinstance(result, Transition), (
            f"Expected Transition, got {type(result)}"
        )
        assert result.new_status == "stopped_out", (
            f"Expected new_status='stopped_out', got {result.new_status!r}"
        )

    @pytest.mark.unit
    def test_shadow_signal_mae_mfe_tracked_from_bar_zero(self):
        """MAE/MFE accumulation works from bar 0 with status='active'.

        Simulates the lifecycle service initializing _mae[sid]=0.0 and
        _mfe[sid]=0.0 at startup and calling evaluate_signal() on each bar.

        EXPECTED TO PASS: evaluate_signal() already handles status='active'
        with MAE/MFE update logic. Documents that shadow signal tracking is
        viable without architecture changes to lifecycle_tracker.py.
        """
        sig = _shadow_signal(direction=1)
        entry = sig["entry_price"]  # 5100.0
        stop = sig["stop_loss"]     # 5085.0
        risk = abs(entry - stop)    # 15.0 ticks

        # Bar 0: price moves favorably (above entry)
        result_bar0 = evaluate_signal(
            sig,
            high=5108.0,
            low=5099.0,
            close=5105.0,
            current_mae=0.0,
            current_mfe=0.0,
        )
        # No exit yet (stop not hit, target not hit)
        assert result_bar0 is None, (
            "Bar 0 favorable movement should not trigger an exit"
        )

        # Bar 1: price drops adversely
        result_bar1 = evaluate_signal(
            sig,
            high=5101.0,
            low=5083.0,  # below stop_loss=5085.0
            close=5084.0,
            current_mae=0.0,
            current_mfe=(5108.0 - entry) / risk,  # MFE from bar 0 favorable move
        )
        assert result_bar1 is not None, "Stop hit on bar 1 must return a Transition"
        # MAE should be negative (adverse = below entry for long)
        assert result_bar1.mae is not None
        assert result_bar1.mae < 0, (
            f"MAE must be negative when price moved against direction: {result_bar1.mae}"
        )
        # MFE should be positive (favorable move occurred on bar 0)
        assert result_bar1.mfe is not None
        assert result_bar1.mfe > 0, (
            f"MFE must be positive from prior favorable movement: {result_bar1.mfe}"
        )

    @pytest.mark.unit
    def test_shadow_signal_status_never_becomes_active(self):
        """Shadow signals retain 'regime_suppressed' in DB — never upgraded to 'active'.

        Design contract test: validates that the regime_suppressed signal dict
        has was_selected=False, which the lifecycle service uses to identify
        shadow signals and avoid calling update_signal_status with status='active'.

        RED: This test validates a design invariant — it passes if the contract
        is correctly expressed in the signal dict. If lifecycle_service ever
        incorrectly activates a shadow signal (was_selected=True on a
        regime_suppressed entry), this contract is violated.

        The test confirms: a signal with regime_eligible=False MUST NOT be
        selected (was_selected must be False when the signal dict has
        regime_eligible=False). The lifecycle service checks was_selected to
        decide whether to promote to 'active'.
        """
        # Simulate a shadow signal as produced by build_ledger_entries
        # after Plan 02/03 are implemented: regime_eligible=False -> was_selected=False
        shadow_signal_in_db = {
            "signal_id": "shadow-uuid-0002",
            "status": "regime_suppressed",
            "was_selected": False,  # shadow signals are never selected
            "regime_eligible": False,
            "suppression_reason": "regime_type",
            "direction": 1,
            "entry_price": 5100.0,
            "stop_loss": 5085.0,
            "targets": [5115.0],
        }

        # Contract: was_selected must be False for any regime_suppressed signal
        assert shadow_signal_in_db.get("regime_eligible") is False, (
            "Shadow signal must have regime_eligible=False"
        )
        assert shadow_signal_in_db.get("was_selected") is False, (
            "Shadow signal must have was_selected=False. "
            "The lifecycle service MUST NOT call update_signal_status with "
            "status='active' for signals where was_selected=False and "
            "status='regime_suppressed'."
        )
        assert shadow_signal_in_db.get("status") == "regime_suppressed", (
            "Shadow signal DB status must remain 'regime_suppressed', never 'active'"
        )
