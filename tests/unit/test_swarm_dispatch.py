"""Tests for AlphaSwarmComputeAgent: enrichment, TF filter, agent registry, cache seeding."""
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.intelligence.swarm.context import SwarmContext


def _make_service():
    """Create AlphaSwarmComputeAgent using __new__ pattern (bypass __init__)."""
    from services.alpha_swarm_agent import AlphaSwarmComputeAgent

    svc = AlphaSwarmComputeAgent.__new__(AlphaSwarmComputeAgent)
    svc.settings = MagicMock(env_name="test")
    svc._context_cache = MagicMock()
    svc._recorder = MagicMock()
    svc._recorder.record = AsyncMock()
    svc._producer = MagicMock()
    svc._producer.publish = AsyncMock()
    svc._agents = []  # populated per test
    svc.logger = MagicMock()
    return svc


def _make_context(**overrides):
    """Create a minimal SwarmContext for testing."""
    defaults = dict(
        signal_id=uuid4(), symbol="ESM6", timeframe="5m", ts=None,
        atr=None, adx=None, rsi=None,
        hmm_regime=None, trend_regime=None, vol_regime=None,
        vol_percentile=None, garch_vol_ratio=None, garch_vol_regime=None,
        kalman_trend=None, kalman_slope=None,
        vwap=None, poc_price=None, poc_price_rolling=None,
        ctf_score=None, ctf_trend_alignment=None, ctf_structure_alignment=None,
        ctf_regime_agreement=None, ctf_timeframes_aligned=None,
        ctf_fvg_alignment=None, ctf_ob_alignment=None,
        winner_plugin=None, winner_direction=None, winner_confidence=None,
        price=None, volume=None,
    )
    defaults.update(overrides)
    return SwarmContext(**defaults)


def test_tf_filter_allows_5m_and_above():
    from services.alpha_swarm_agent import _ELIGIBLE_TFS
    assert "5m" in _ELIGIBLE_TFS
    assert "15m" in _ELIGIBLE_TFS
    assert "1h" in _ELIGIBLE_TFS
    assert "4h" in _ELIGIBLE_TFS
    assert "1d" in _ELIGIBLE_TFS
    assert "1m" not in _ELIGIBLE_TFS


def test_enrich_context_adds_fields():
    svc = _make_service()
    svc._context_cache._cache = {}
    ctx = _make_context(symbol="ESM6", timeframe="5m")

    enriched = svc._enrich_context(ctx)
    # lead_context should be None (no cache data)
    assert enriched.lead_context is None
    # volume_profile should be None (no cache data)
    assert enriched.volume_profile is None
    # Original fields preserved
    assert enriched.symbol == "ESM6"
    assert enriched.timeframe == "5m"


def test_enrich_context_preserves_original():
    svc = _make_service()
    svc._context_cache._cache = {}
    ctx = _make_context(symbol="ESM6", price=4500.0)

    enriched = svc._enrich_context(ctx)
    assert enriched.price == 4500.0
    assert enriched.symbol == "ESM6"
    # Original ctx unchanged (frozen model)
    assert ctx.lead_context is None
    assert ctx.volume_profile is None


def test_lead_index_mapping():
    from services.alpha_swarm_agent import _LEAD_INDEX_MAP
    assert _LEAD_INDEX_MAP["NQ"] == "ES"
    assert _LEAD_INDEX_MAP["ES"] == "ES"
    assert _LEAD_INDEX_MAP["HO"] == "CL"
    assert _LEAD_INDEX_MAP["SI"] == "GC"


def test_find_lead_context_returns_cache_result():
    """_find_lead_context delegates to _context_cache.get_lead() for non-self-lead symbols."""
    svc = _make_service()
    mock_lead = MagicMock()
    mock_lead.symbol = "ESM6"
    svc._context_cache.get_lead.return_value = mock_lead

    ctx = _make_context(symbol="NQM6", timeframe="5m")
    lead = svc._find_lead_context("NQM6", "5m", ctx)

    assert lead is mock_lead
    assert lead.symbol == "ESM6"


def test_find_lead_context_returns_none_for_self_lead():
    """ES maps to ES (self-lead) -- should return None."""
    svc = _make_service()
    svc._context_cache._cache = {}
    ctx = _make_context(symbol="ESM6", timeframe="5m")
    lead = svc._find_lead_context("ESM6", "5m", ctx)
    assert lead is None


def test_find_lead_context_returns_none_for_unknown():
    """Symbol with no lead mapping returns None."""
    svc = _make_service()
    svc._context_cache._cache = {}
    ctx = _make_context(symbol="XYZ", timeframe="5m")
    lead = svc._find_lead_context("XYZ", "5m", ctx)
    assert lead is None


@pytest.mark.skip(reason="Tests SwarmContextCache implementation which is replaced by AIContextCache")
def test_seed_context_cache():
    """Per D-08: _seed_context_cache calls seed_from_db_row for each row."""
    pass
