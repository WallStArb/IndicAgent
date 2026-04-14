"""Tests for swarm protocol: SwarmContext, IAlphaContributor, AgentResult, AlphaMultiplier."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest


def _make_intelligence_event(symbol: str = "ESM6", tf: str = "1m", hmm_regime: int = 1):
    from src.intelligence.schemas import IntelligenceEvent
    event = MagicMock(spec=IntelligenceEvent)
    event.symbol = symbol
    event.tf = tf
    event.ts = datetime(2026, 4, 9, 14, 30, tzinfo=UTC)
    event.bar = MagicMock()
    event.bar.close = 5280.0
    event.bar.volume = 12000.0
    event.i1 = MagicMock()
    event.i1.atr_14 = 8.5
    event.i1.rsi_14 = 62.0
    event.i1.adx = 32.0
    event.i4 = MagicMock()
    event.i4.hmm_regime = hmm_regime
    event.i4.vwap = 5277.5
    event.i4.poc_price = 5275.0
    event.i4.poc_price_rolling = 5270.0
    event.i6 = MagicMock()
    event.i6.ctf_trend_alignment = 0.75
    event.i6.ctf_regime_agreement = 0.80
    event.i6.ctf_fvg_alignment = 0.60
    event.i6.ctf_ob_alignment = 0.55
    return event


def _make_ranked_signal(plugin: str = "TrendFollowing", direction: int = 1, confidence: float = 0.8):
    from src.intelligence.schemas import RankedSignal
    sig = MagicMock(spec=RankedSignal)
    sig.signal_id = str(uuid4())
    sig.plugin = plugin
    sig.direction = direction
    sig.calibrated_confidence = confidence
    sig.is_winner = True
    return sig


# ---------------------------------------------------------------------------
# SwarmContext construction
# ---------------------------------------------------------------------------

def test_context_cache_build_returns_swarm_context():
    from src.intelligence.swarm.context import SwarmContextCache
    cache = SwarmContextCache()
    event = _make_intelligence_event()
    signal = _make_ranked_signal()
    signal_id = uuid4()

    cache.update(event)
    ctx = cache.build(symbol="ESM6", tf="1m", signal=signal, signal_id=signal_id)

    assert ctx is not None
    assert ctx.symbol == "ESM6"
    assert ctx.timeframe == "1m"
    assert ctx.hmm_regime == 1
    assert ctx.atr == 8.5
    assert ctx.winner_plugin == "TrendFollowing"


def test_context_cache_returns_none_for_unknown_symbol():
    from src.intelligence.swarm.context import SwarmContextCache
    cache = SwarmContextCache()
    result = cache.build(symbol="ZZMISS", tf="1m", signal=MagicMock(), signal_id=uuid4())
    assert result is None


def test_context_is_immutable():
    from src.intelligence.swarm.context import SwarmContextCache
    cache = SwarmContextCache()
    event = _make_intelligence_event()
    cache.update(event)
    ctx = cache.build("ESM6", "1m", _make_ranked_signal(), uuid4())
    assert ctx is not None

    with pytest.raises(Exception):
        ctx.symbol = "CHANGED"


# ---------------------------------------------------------------------------
# AgentResult schema
# ---------------------------------------------------------------------------

def test_agent_result_has_path_field():
    from src.intelligence.schemas import AgentResult
    r = AgentResult(
        agent_id="test_agent",
        path="deterministic",
        multiplier=1.1,
        confidence=0.8,
    )
    assert r.path == "deterministic"
    assert r.shadow_only is True
    assert r.latency_ms == 0.0


def test_agent_result_rejects_out_of_bounds_multiplier():
    from pydantic import ValidationError

    from src.intelligence.schemas import AgentResult

    with pytest.raises(ValidationError):
        AgentResult(agent_id="x", path="deterministic", multiplier=3.0, confidence=0.5)


# ---------------------------------------------------------------------------
# AlphaMultiplier schema
# ---------------------------------------------------------------------------

def test_alpha_multiplier_has_symbol_and_timeframe():
    from src.intelligence.schemas import AgentResult, AlphaMultiplier

    contributor = AgentResult(agent_id="test", path="deterministic", multiplier=1.0, confidence=0.9)
    am = AlphaMultiplier(
        signal_id=uuid4(),
        symbol="ESM6",
        timeframe="1m",
        ts=datetime.now(UTC),
        path_a_multiplier=1.0,
        path_b_multiplier=None,
        contributors={"test": contributor},
        final_alpha_multiplier=1.0,
        production_multiplier=1.0,
        shadow_only=True,
    )
    assert am.symbol == "ESM6"
    assert am.is_production_ready is False


# ---------------------------------------------------------------------------
# FeatureVector
# ---------------------------------------------------------------------------

def test_feature_vector_is_frozen():
    from src.core.ml.features import FeatureVector
    fv = FeatureVector(
        ts="2026-04-10T14:00:00+00:00",
        symbol="ESM6",
        tf="1m",
        hmm_regime=1,
        hmm_prob=0.87,
    )
    with pytest.raises(Exception):
        fv.hmm_regime = 0  # frozen


def test_feature_vector_defaults_to_none_for_optional_fields():
    from src.core.ml.features import FeatureVector
    fv = FeatureVector(ts="2026-04-10T14:00:00+00:00", symbol="ESM6", tf="1m")
    assert fv.hmm_regime is None
    assert fv.atr is None
    assert fv.rsi is None
