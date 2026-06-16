"""Tests for per-stage confidence attribution invariant.

Verifies:
- pre_quality_confidence >= pre_calibration_confidence >= calibrated_confidence
- Edge case: confidence 0.0 satisfies invariant
- LedgerEntry backward-compat shim is importable; attribution invariant is schema-independent.

Updated in Phase 130 (130-02): removed dependency on _INSERT_SQL and _to_row() which
belonged to the legacy signal_ledger schema. LedgerEntry is now a backward-compat
dataclass shim — no _to_row() method exists in the 3-table schema.
"""

from __future__ import annotations

from datetime import UTC, datetime

from src.persistence.repository.signal_events_repository import LedgerEntry

# ---------------------------------------------------------------------------
# Invariant helpers (mirror the logic from IntelligencePipeline)
# ---------------------------------------------------------------------------


def _apply_stage_reduction(
    signals: list[dict], quality_factor: float = 0.9, calibration_factor: float = 0.8
) -> list[dict]:
    """Simulate pipeline stages that reduce confidence.

    Mirrors the production pipeline:
        raw -> pre_quality (captured) -> quality_gate -> regime_gate -> tod
            -> pre_calibration (captured) -> calibration
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

    def test_ledger_entry_compat_shim_is_importable(self) -> None:
        """LedgerEntry backward-compat shim is importable and constructable.

        Phase 130: LedgerEntry no longer has _to_row() — it is a plain dataclass
        shim for callers awaiting Wave 3 rewrites. The attribution fields
        (raw_confidence, calibrated_confidence) are present as dataclass fields.
        """
        entry = LedgerEntry(
            signal_id="test-123",
            timestamp=datetime.now(UTC),
            symbol="ESM6",
            timeframe="1m",
            setup_plugin="test_plugin",
            signal_type="trend",
            direction=1,
            entry_price=5500.0,
            stop_loss=5490.0,
            targets=[5520.0],
            was_selected=True,
            raw_confidence=0.72,
            calibrated_confidence=0.65,
        )
        assert entry.raw_confidence == 0.72
        assert entry.calibrated_confidence == 0.65
        assert entry.signal_id == "test-123"
