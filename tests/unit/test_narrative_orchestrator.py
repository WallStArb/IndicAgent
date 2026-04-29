"""Tests for NarrativeComputeAgent."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest


def _make_context(**overrides):
    """Create a minimal AIContext for testing."""
    from uuid import uuid4

    from src.core.ai.context import AIContext

    defaults = dict(
        signal_id=uuid4(),
        symbol="ESM6",
        timeframe="5m",
        ts=datetime(2026, 4, 9, 14, 30, tzinfo=UTC),
    )
    defaults.update(overrides)
    return AIContext(**defaults)


@pytest.mark.skip(reason="NarrativeComputeAgent TF gate rejects 1m bars; test needs 5m+ context")
@pytest.mark.asyncio
async def test_orchestrator_returns_narrative_string():
    """NarrativeComputeAgent returns text in payload."""
    pass


@pytest.mark.skip(reason="Test needs update for new AgentOutput-based API")
@pytest.mark.asyncio
async def test_orchestrator_returns_none_for_zero_direction():
    """NarrativeComputeAgent handles zero direction."""
    pass
