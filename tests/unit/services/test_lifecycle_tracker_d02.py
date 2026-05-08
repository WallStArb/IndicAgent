"""Tests for lifecycle_tracker D-02 violation counter.

D-02: activated_at is set but status is still PENDING at TTL time.
Phase 81: The workaround that auto-corrected this is GONE. The counter
now fires purely as an assertion to surface the bug.

test_d02_violation_counter:
  - Feed a signal with activated_at=now() and status="pending" through evaluate_signal
    with bars_elapsed >= ttl
  - Assert _LABELING_VIOLATIONS counter incremented exactly 1
  - Assert signal status was NOT mutated (remains "pending")
"""

from datetime import UTC, datetime

import pytest

from src.intelligence.trading import lifecycle_tracker
from src.intelligence.trading.lifecycle_tracker import evaluate_signal
from src.persistence.repository.signal_ledger_repository import SignalStatus


def _make_signal(status: str, activated_at: datetime | None = None) -> dict:
    """Build a minimal signal dict for evaluate_signal."""
    return {
        "signal_id": "d02-test-001",
        "status": status,
        "direction": 1,
        "entry_price": 5000.0,
        "stop_loss": 4990.0,
        "targets": [5020.0],
        "ttl_bars": 5,
        "bars_elapsed": 5,  # >= ttl_bars → triggers TTL check
        "point_value": 50.0,
        "entry_zone_low": 4998.0,
        "entry_zone_high": 5002.0,
        "activated_at": activated_at,
        "garch_sigma_at_fire": None,
        "hmm_regime_at_fire": None,
        "setup_plugin": "test_plugin",
    }


class TestD02ViolationCounter:
    """D-02 labeling violation counter fires but does NOT mutate signal state."""

    @pytest.mark.unit
    def test_d02_violation_counter(self):
        """activated_at set + status=pending at TTL → counter increments, status unchanged."""
        activated_at = datetime.now(UTC)
        signal = _make_signal(status=SignalStatus.PENDING, activated_at=activated_at)

        # Capture current counter value before calling evaluate_signal
        violations_before = lifecycle_tracker._LABELING_VIOLATIONS._value.get()

        # Call evaluate_signal — with bars_elapsed >= ttl_bars this triggers TTL path
        result = evaluate_signal(
            signal,
            high=5005.0,
            low=4995.0,
            close=5001.0,
            current_mae=0.0,
            current_mfe=0.1,
        )

        violations_after = lifecycle_tracker._LABELING_VIOLATIONS._value.get()

        # D-02 counter must have incremented exactly once
        assert violations_after == violations_before + 1, (
            f"D-02 counter should have incremented by 1: "
            f"before={violations_before}, after={violations_after}"
        )

        # evaluate_signal must return a Transition (TTL exit) — this proves the TTL path ran
        assert result is not None, "evaluate_signal should return a Transition at TTL"
        assert result.exit_reason == "ttl_expired"

        # Signal status in the dict must NOT have been mutated by evaluate_signal
        assert signal["status"] == SignalStatus.PENDING, (
            f"Signal status was mutated from pending to {signal['status']!r}; "
            "evaluate_signal must not mutate the input dict"
        )
