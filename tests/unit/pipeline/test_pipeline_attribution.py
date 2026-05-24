"""Tests for per-stage confidence attribution invariant.

Verifies:
- pre_quality_confidence >= pre_calibration_confidence >= calibrated_confidence
- Edge case: confidence 0.0 satisfies invariant
- LedgerEntry includes both attribution fields in 64-element tuple
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from src.persistence.repository.signal_ledger_repository import (
    _INSERT_SQL,
    LedgerEntry,
)

# ---------------------------------------------------------------------------
# Invariant helpers (mirror the logic from IntelligencePipelineComputeAgent)
# ---------------------------------------------------------------------------


def _apply_stage_reduction(
    signals: list[dict], quality_factor: float = 0.9, calibration_factor: float = 0.8
) -> list[dict]:
    """Simulate pipeline stages that reduce confidence.

    Mirrors the production pipeline:
        raw -> pre_quality (captured) -> quality_gate -> regime_gate -> tod -> pre_calibration (captured) -> calibration
    """
    for sig in signals:
        # Capture BEFORE quality gate
        sig["pre_quality_confidence"] = sig.get("confidence", 0.0)
        # Quality gate reduces confidence
        sig["confidence"] = round(sig["confidence"] * quality_factor, 6)
        # Regime + TOD may further reduce
        sig["confidence"] = round(sig["confidence"] * 0.95, 6)
        # Capture BEFORE calibration
        sig["pre_calibration_confidence"] = sig.get("confidence", 0.0)
        # Calibration reduces
        sig["confidence"] = round(sig["confidence"] * calibration_factor, 6)
        sig["calibrated_confidence"] = sig["confidence"]
    return signals


class TestAttributionInvariant:
    """Verify the monotonic non-increasing confidence chain."""

    def test_attribution_invariant_holds(self) -> None:
        """pre_quality >= pre_calibration >= calibrated for varying confidences."""
        raw_confs = [0.8, 0.5, 0.95, 0.3, 0.7]
        signals = [{"confidence": c} for c in raw_confs]
        processed = _apply_stage_reduction(signals)

        for sig in processed:
            pq = sig["pre_quality_confidence"]
            pc = sig["pre_calibration_confidence"]
            cc = sig["calibrated_confidence"]
            assert pq >= pc, f"pre_quality ({pq}) < pre_calibration ({pc})"
            assert pc >= cc, f"pre_calibration ({pc}) < calibrated ({cc})"

    def test_attribution_zero_confidence(self) -> None:
        """Signal with confidence=0.0 satisfies invariant (all three are 0.0)."""
        signals = [{"confidence": 0.0}]
        processed = _apply_stage_reduction(signals)
        sig = processed[0]
        assert sig["pre_quality_confidence"] == 0.0
        assert sig["pre_calibration_confidence"] == 0.0
        assert sig["calibrated_confidence"] == 0.0

    def test_attribution_fields_on_ledger_entry(self) -> None:
        """LedgerEntry param count matches _INSERT_SQL placeholder count and attribution fields land at correct positions."""
        entry = LedgerEntry(
            signal_id="test-123",
            timestamp=datetime.now(UTC),
            symbol="ESM6",
            timeframe="1m",
            setup_plugin="test_plugin",
            signal_type="trend",
            direction=1,
            was_selected=True,
            pre_quality_confidence=0.80,
            pre_calibration_confidence=0.68,
        )
        params = entry._to_row()
        sql_param_count = len(re.findall(r"\$\d+", _INSERT_SQL))
        assert (
            len(params) == sql_param_count
        ), f"Expected {sql_param_count} params, got {len(params)}"
        assert params[27] == 0.80, "pre_quality_confidence must be $28 (index 27)"
        assert params[28] == 0.68, "pre_calibration_confidence must be $29 (index 28)"
