"""Tests for SwarmDispatchService: enrichment, TF filter, agent registry, cache seeding."""
import types
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from src.intelligence.swarm.context import SwarmContext, SwarmContextCache


def _make_service():
    """Create SwarmDispatchService using __new__ pattern (bypass __init__)."""
    from services.swarm_dispatch_service import SwarmDispatchService

    svc = SwarmDispatchService.__new__(SwarmDispatchService)
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
    from services.swarm_dispatch_service import _ELIGIBLE_TFS
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
    from services.swarm_dispatch_service import _LEAD_INDEX_MAP
    assert _LEAD_INDEX_MAP["NQ"] == "ES"
    assert _LEAD_INDEX_MAP["ES"] == "ES"
    assert _LEAD_INDEX_MAP["HO"] == "CL"
    assert _LEAD_INDEX_MAP["SI"] == "GC"


def test_find_lead_context_builds_from_cache():
    """Per D-15 + D-16: _find_lead_context builds real SwarmContext from cache."""
    import time

    svc = _make_service()

    # Simulate cache entry for ESM6 (lead index) at 5m
    i1 = types.SimpleNamespace(atr_14=12.5, adx=25.0, rsi_14=55.0)
    i4 = types.SimpleNamespace(
        hmm_regime=1, trend_regime=0.8, vol_regime=0.3,
        vol_percentile=0.6, garch_vol_ratio=1.1, garch_vol_regime=1,
        kalman_trend=0.01, kalman_slope=0.002,
        vwap=4500.0, poc_price=4498.0, poc_price_rolling=4495.0,
    )
    i6 = types.SimpleNamespace(
        ctf_score=0.7, ctf_trend_alignment=0.8,
        ctf_structure_alignment=0.6, ctf_regime_agreement=0.7,
        ctf_timeframes_aligned=3, ctf_fvg_alignment=0.4,
        ctf_ob_alignment=0.3,
    )
    bar = types.SimpleNamespace(close=4502.0, volume=1500)
    event_proxy = types.SimpleNamespace(
        symbol="ESM6", tf="5m", ts=None,
        bar=bar, i1=i1, i4=i4, i6=i6,
    )
    svc._context_cache._cache = {
        ("ESM6", "5m"): (event_proxy, time.monotonic()),
    }

    # NQM6 should find ESM6 as its lead index
    ctx = _make_context(symbol="NQM6", timeframe="5m")
    lead = svc._find_lead_context("NQM6", "5m", ctx)

    assert lead is not None
    assert lead.symbol == "ESM6"
    assert lead.atr == 12.5
    assert lead.adx == 25.0
    assert lead.rsi == 55.0
    assert lead.hmm_regime == 1
    assert lead.trend_regime == 0.8
    assert lead.ctf_trend_alignment == 0.8
    assert lead.price == 4502.0
    assert lead.volume == 1500
    # No winner signal for lead context
    assert lead.winner_plugin is None
    # Reuses signal's ID
    assert lead.signal_id == ctx.signal_id


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


def test_seed_context_cache():
    """Per D-08: _seed_context_cache calls seed_from_db_row for each row."""
    import asyncio

    svc = _make_service()
    # Use a real SwarmContextCache (not MagicMock) so seed_from_db_row works
    svc._context_cache = SwarmContextCache()

    # Create a mock pool that returns a fake row
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[
        {
            "symbol": "ESM6", "tf": "5m", "ts": None,
            "bar": {"close": 4500.0, "volume": 1000},
            "i1": {"atr_14": 12.0},
            "i4": {"hmm_regime": 1},
            "i6": {},
        },
    ])
    mock_pool = AsyncMock()
    mock_pool.acquire = MagicMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(
        return_value=mock_conn,
    )
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    # Verify seed_from_db_row is called -- check cache was populated
    asyncio.run(svc._seed_context_cache(mock_pool))

    # Cache should have the ESM6 entry
    assert ("ESM6", "5m") in svc._context_cache._cache
