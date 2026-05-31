"""Tests for SignalContext, SignalContextCache, and Tier enum."""

import time
import unittest.mock
from datetime import datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from src.intelligence.ai.context import (
    BarContext,
    SignalContext,
    SignalContextCache,
    Tier,
)
from src.intelligence.schemas import I1Indicators, I4Context, I6Confluence


class TestTierEnum:
    """Test suite for Tier enum."""

    def test_tier_enum_values(self):
        """Verify BAR, I1-I7 all present, all str-compatible."""
        # Tier extends str, so direct comparison works
        assert Tier.BAR == "bar"
        assert Tier.I1 == "i1"
        assert Tier.I2 == "i2"
        assert Tier.I3 == "i3"
        assert Tier.I4 == "i4"
        assert Tier.I5 == "i5"
        assert Tier.I6 == "i6"
        assert Tier.I7 == "i7"

        # Verify value access
        assert Tier.BAR.value == "bar"
        assert Tier.I7.value == "i7"


class TestAIContext:
    """Test suite for SignalContext frozen model."""

    def test_ai_context_is_frozen(self):
        """Verify ConfigDict(frozen=True) prevents mutation."""
        ctx = SignalContext(
            symbol="ES",
            timeframe="5m",
            ts=datetime.now(),
        )
        with pytest.raises(Exception):
            ctx.symbol = "NQ"

    def test_ai_context_self_referential_lead(self):
        """Verify lead_context: SignalContext | None works after model_rebuild()."""
        lead = SignalContext(
            symbol="ZN",
            timeframe="5m",
            ts=datetime.now(),
        )
        ctx = SignalContext(
            symbol="ES",
            timeframe="5m",
            ts=datetime.now(),
            lead_context=lead,
        )
        assert ctx.lead_context is not None
        assert ctx.lead_context.symbol == "ZN"

    def test_tier_contexts_conditionally_populated(self):
        """Verify tier contexts can be None or populated."""
        ctx = SignalContext(
            symbol="ES",
            timeframe="5m",
            ts=datetime.now(),
            bar=BarContext(open=4500.0, high=4510.0, low=4490.0, close=4505.0),
            i1=I1Indicators(atr_14=10.0, adx_14=25.0, rsi_14=55.0),
            i4=None,
            i6=None,
            i7=None,
        )
        assert ctx.bar is not None
        assert ctx.bar.open == 4500.0
        assert ctx.i1 is not None
        assert ctx.i1.atr_14 == 10.0
        assert ctx.i4 is None


class TestAIContextCache:
    """Test suite for SignalContextCache."""

    def test_context_cache_update_and_build(self):
        """Verify update with mock event, build returns SignalContext."""
        cache = SignalContextCache()

        # Create mock event using SimpleNamespace with typed tier models
        event = SimpleNamespace(
            symbol="ES",
            tf="5m",
            ts=datetime.now(),
            bar=SimpleNamespace(open=4500.0, high=4510.0, low=4490.0, close=4505.0, volume=1000),
            i1=I1Indicators(atr_14=10.0, adx_14=25.0, rsi_14=55.0),
            i2=None,
            i3=None,
            i4=I4Context(trend_regime=0.8, vol_regime=0.5, poc_price=4501.0),
            i5=None,
            i6=I6Confluence(ctf_score=0.7, ctf_trend_alignment=0.5, ctf_regime_agreement=0.8),
            smc=None,
            i7=None,
        )

        # Update cache
        cache.update(event)

        # Build context
        ctx = cache.build(
            symbol="ES",
            tf="5m",
            tiers_needed=frozenset({Tier.BAR, Tier.I1, Tier.I4, Tier.I6}),
        )
        assert ctx is not None
        assert ctx.symbol == "ES"
        assert ctx.timeframe == "5m"
        assert ctx.bar is not None
        assert ctx.bar.close == 4505.0
        assert ctx.i1 is not None
        assert ctx.i1.atr_14 == 10.0
        assert ctx.i4 is not None

    def test_context_cache_ttl_expiry(self):
        """Verify cached entry expires after _TTL_SECONDS."""
        cache = SignalContextCache()

        event = SimpleNamespace(
            symbol="ES",
            tf="5m",
            ts=datetime.now(),
            bar=SimpleNamespace(close=4500.0),
            i1=I1Indicators(atr_14=10.0),
            i2=None,
            i3=None,
            i4=None,
            i5=None,
            i6=None,
            smc=None,
        )

        cache.update(event)

        # Build immediately — should succeed
        ctx = cache.build(
            symbol="ES",
            tf="5m",
            tiers_needed=frozenset({Tier.I1}),
        )
        assert ctx is not None

        # Patch _ttl_for_tf to return 0 so the entry expires immediately
        import src.intelligence.ai.context as ctx_module

        with unittest.mock.patch.object(ctx_module, "_ttl_for_tf", return_value=0):
            time.sleep(0.1)  # Small delay to ensure monotonic time advances
            ctx_expired = cache.build(
                symbol="ES",
                tf="5m",
                tiers_needed=frozenset({Tier.I1}),
            )
            assert ctx_expired is None  # Should be None after expiry

    def test_context_cache_get_lead(self):
        """Verify get_lead() returns lead context for valid lead_map entry (D-10 fix)."""
        cache = SignalContextCache()

        # Add lead symbol (ZN) to cache
        lead_event = SimpleNamespace(
            symbol="ZN",
            tf="5m",
            ts=datetime.now(),
            bar=SimpleNamespace(close=120.0),
            i1=I1Indicators(atr_14=2.0),
            i2=None,
            i3=None,
            i4=I4Context(trend_regime=0.5, vol_regime=0.5, poc_price=120.3),
            i5=None,
            i6=I6Confluence(ctf_score=0.5, ctf_trend_alignment=0.4, ctf_regime_agreement=0.6),
            smc=None,
            i7=None,
        )
        cache.update(lead_event)

        # Call get_lead for ES (which maps to ZN)
        lead_ctx = cache.get_lead(
            symbol="ES",
            tf="5m",
            lead_map={"ES": "ZN"},
        )
        assert lead_ctx is not None
        assert lead_ctx.symbol == "ZN"

        # Test with no lead map entry
        no_lead_ctx = cache.get_lead(
            symbol="NQ",
            tf="5m",
            lead_map={},
        )
        assert no_lead_ctx is None

    def test_context_cache_seed_from_db_row(self):
        """Verify seed_from_db_row works with asyncpg dict rows."""
        cache = SignalContextCache()

        row = {
            "symbol": "ES",
            "tf": "5m",
            "ts": datetime.now(),
            "bar": {"close": 4500.0, "volume": 1000},
            "technical_indicators": {"atr_14": 10.0, "adx_14": 25.0},
            "regime_features": {"trend_regime": 0.8},
            "cross_timeframe_context": {"ctf_score": 0.7},
        }

        cache.seed_from_db_row(row)

        # Build from seeded cache
        ctx = cache.build(
            symbol="ES",
            tf="5m",
            tiers_needed=frozenset({Tier.BAR, Tier.I1}),
        )
        assert ctx is not None
        assert ctx.symbol == "ES"
        assert ctx.bar is not None
        assert ctx.bar.close == 4500.0
        assert ctx.i1 is not None
        assert ctx.i1.atr_14 == 10.0

    def test_context_cache_build_with_signal(self):
        """Verify build populates i7 context when signal provided."""
        cache = SignalContextCache()

        event = SimpleNamespace(
            symbol="ES",
            tf="5m",
            ts=datetime.now(),
            bar=SimpleNamespace(close=4500.0),
            i1=None,
            i2=None,
            i3=None,
            i4=None,
            i5=None,
            i6=None,
            smc=None,
            i7=None,
        )
        cache.update(event)

        # Create mock signal
        signal = SimpleNamespace(
            signal_id=UUID("00000000-0000-0000-0000-000000000001"),
            plugin="TrendFollowing",
            direction=1,
            confidence=0.8,
            calibrated_confidence=0.75,
        )

        ctx = cache.build(
            symbol="ES",
            tf="5m",
            tiers_needed=frozenset({Tier.I7}),
            signal=signal,
            signal_id=signal.signal_id,
        )
        assert ctx is not None
        assert ctx.i7 is not None
        assert ctx.i7.winner_plugin == "TrendFollowing"
        assert ctx.i7.winner_direction == 1
        assert ctx.i7.winner_confidence == 0.75
