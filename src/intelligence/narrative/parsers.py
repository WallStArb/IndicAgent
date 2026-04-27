"""Pure parsing functions for BarIntelligenceRecord → typed dict.

No I/O — extracts fields needed by NarrativeOrchestrator from the record.
Returns None when direction=0 (no actionable signal to narrate).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.intelligence.schemas import BarIntelligenceRecord


def parse_bar_intelligence_record(record: BarIntelligenceRecord) -> dict[str, Any] | None:
    """Extract narrative-relevant fields from a BarIntelligenceRecord.

    Returns None if direction is 0 (no actionable signal).
    """
    direction = record.winner_direction or 0
    if direction == 0:
        return None

    intel = record.intelligence

    return {
        "symbol": intel.symbol,
        "timeframe": intel.tf,
        "ts": intel.ts if isinstance(intel.ts, str) else intel.ts.isoformat(),
        "direction": direction,
        "confidence": record.winner_confidence or 0.0,
        "plugin": record.winner_plugin or "unknown",
        "close": intel.bar.c,
        "regime": getattr(intel.i4, "hmm_regime", None),
        "regime_prob": getattr(intel.i4, "hmm_regime_prob", None),
        "ctf_trend_alignment": getattr(intel.i6, "ctf_trend_alignment", None),
        "ctf_regime_agreement": getattr(intel.i6, "ctf_regime_agreement", None),
    }
