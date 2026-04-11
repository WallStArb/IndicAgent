"""Tests for src/intelligence/narrative/parsers.py."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock


def _make_record(direction: int = 1, confidence: float = 0.75):
    from src.intelligence.schemas import BarIntelligenceRecord, IntelligenceEvent, RankedSignal
    intel = MagicMock(spec=IntelligenceEvent)
    intel.symbol = "NQM6"
    intel.tf = "5m"
    intel.ts = datetime(2026, 4, 9, 15, 0, tzinfo=UTC)
    intel.bar = MagicMock()
    intel.bar.close = 18500.0
    intel.bar.open = 18490.0
    intel.i4 = MagicMock()
    intel.i4.hmm_regime = 1
    intel.i4.hmm_regime_prob = 0.9
    intel.i6 = MagicMock()
    intel.i6.ctf_trend_alignment = 0.8

    record = MagicMock(spec=BarIntelligenceRecord)
    record.intelligence = intel
    record.winner_plugin = "MomentumBreakout"
    record.winner_direction = direction
    record.winner_confidence = confidence
    return record


def test_parse_returns_dict_with_required_keys():
    from src.intelligence.narrative.parsers import parse_bar_intelligence_record
    result = parse_bar_intelligence_record(_make_record())
    required = {"symbol", "timeframe", "direction", "confidence", "plugin", "regime"}
    assert required.issubset(result.keys())


def test_parse_direction_zero_returns_none():
    """direction=0 means no actionable signal — parser returns None."""
    from src.intelligence.narrative.parsers import parse_bar_intelligence_record
    assert parse_bar_intelligence_record(_make_record(direction=0)) is None


def test_parse_extracts_symbol_and_tf():
    from src.intelligence.narrative.parsers import parse_bar_intelligence_record
    result = parse_bar_intelligence_record(_make_record())
    assert result["symbol"] == "NQM6"
    assert result["timeframe"] == "5m"


def test_parse_includes_hmm_regime():
    from src.intelligence.narrative.parsers import parse_bar_intelligence_record
    result = parse_bar_intelligence_record(_make_record())
    assert result["regime"] == 1
