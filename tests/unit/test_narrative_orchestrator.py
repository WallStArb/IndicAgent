"""Tests for NarrativeOrchestrator."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_record(direction: int = 1, confidence: float = 0.75, symbol: str = "ESM6"):
    from src.intelligence.schemas import BarIntelligenceRecord, IntelligenceEvent
    intel = MagicMock(spec=IntelligenceEvent)
    intel.symbol = symbol
    intel.tf = "1m"
    intel.ts = datetime(2026, 4, 9, 14, 30, tzinfo=UTC)
    intel.bar = MagicMock()
    intel.bar.close = 5280.0
    intel.i1 = MagicMock()
    intel.i1.atr_14 = 8.5
    intel.i4 = MagicMock()
    intel.i4.hmm_regime = 1
    intel.i4.hmm_regime_prob = 0.87
    intel.i6 = MagicMock()
    intel.i6.ctf_trend_alignment = 0.75
    intel.i6.ctf_regime_agreement = 0.80
    record = MagicMock(spec=BarIntelligenceRecord)
    record.intelligence = intel
    record.winner_plugin = "TrendFollowing"
    record.winner_direction = direction
    record.winner_confidence = confidence
    record.ranked_signals = []
    return record


@pytest.mark.asyncio
async def test_orchestrator_returns_narrative_string():
    """NarrativeOrchestrator.generate() returns a non-empty string."""
    from src.intelligence.narrative.orchestrator import NarrativeOrchestrator

    mock_chain = MagicMock()
    mock_chain.generate = AsyncMock(return_value="The market is showing bullish momentum.")

    orchestrator = NarrativeOrchestrator(chain=mock_chain)
    result = await orchestrator.generate(_make_record())

    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_orchestrator_returns_none_for_zero_direction():
    """NarrativeOrchestrator returns None when record has no winner (direction=0)."""
    from src.intelligence.narrative.orchestrator import NarrativeOrchestrator

    mock_chain = MagicMock()
    mock_chain.generate = AsyncMock(return_value="should not be called")

    orchestrator = NarrativeOrchestrator(chain=mock_chain)
    result = await orchestrator.generate(_make_record(direction=0))

    assert result is None
    mock_chain.generate.assert_not_called()
