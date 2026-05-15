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
from unittest.mock import MagicMock, patch

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
    """D-02 labeling violation counter fires in the TTL block, which is only
    reached for ACTIVE signals after the TTL reorder. PENDING signals short-circuit
    to zone activation check and never reach the TTL block.

    For PENDING signals with zone overlap, evaluate_signal returns an activation
    Transition. The D-02 counter is NOT incremented for these cases — the violation
    is only detected when an ACTIVE signal reaches the TTL check.
    """

    @pytest.mark.unit
    def test_d02_pending_with_zone_overlap_activates_instead_of_ttl(self):
        """PENDING + activated_at at TTL with zone overlap → activation, no violation counter."""
        activated_at = datetime.now(UTC)
        signal = _make_signal(status=SignalStatus.PENDING, activated_at=activated_at)

        mock_violations = MagicMock()
        with patch.object(lifecycle_tracker, "_LABELING_VIOLATIONS", mock_violations):
            # Zone overlap: high=5005 >= zone_low=4998 AND low=4995 <= zone_high=5002
            result = evaluate_signal(
                signal,
                high=5005.0,
                low=4995.0,
                close=5001.0,
                current_mae=0.0,
                current_mfe=0.1,
            )

        # PENDING with zone overlap activates — D-02 counter NOT incremented
        mock_violations.add.assert_not_called()

        # Returns an activation Transition, not TTL expired
        assert result is not None, "evaluate_signal should return activation Transition"
        assert result.new_status == SignalStatus.ACTIVE

        # Signal status must NOT have been mutated by evaluate_signal
        assert signal["status"] == SignalStatus.PENDING, (
            f"Signal status was mutated from pending to {signal['status']!r}; "
            "evaluate_signal must not mutate the input dict"
        )
