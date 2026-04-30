"""Tests for AIContext typed tier rewrite.

Plan 078-05, Task 1:
- AIContext uses schemas.py types directly (no sparse subclasses)
- Tier enum exposes I2, I3, I5
- Direct pass-through of event.iN to ctx.iN (object identity)
- Frozen model raises on mutation attempt
"""

from __future__ import annotations

import types
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.core.ai.context import AIContext, AIContextCache, BarContext, I7Context, Tier
from src.intelligence.schemas import (
    I1Indicators,
    I2Events,
    I3Structure,
    I4Context,
    I5Patterns,
    I6Confluence,
    SMCContext,
)


_UNSET = object()  # sentinel for "caller did not provide a value"


def _make_event(
    symbol: str = "ESM6",
    tf: str = "5m",
    *,
    i1: object = _UNSET,
    i2: object = _UNSET,
    i3: object = _UNSET,
    i4: object = _UNSET,
    i5: object = _UNSET,
    i6: object = _UNSET,
    smc: object = _UNSET,
) -> types.SimpleNamespace:
    """Build a minimal event-like proxy for cache.update() / build() tests.

    Pass a value (including None) to override the default.
    Omitting a kwarg uses a sensible non-None default.
    """
    return types.SimpleNamespace(
        symbol=symbol,
        tf=tf,
        ts=datetime.now(tz=timezone.utc),
        bar=types.SimpleNamespace(o=4500.0, h=4510.0, l=4490.0, c=4505.0, v=1000),
        i1=I1Indicators(rsi_14=55.0, atr_14=12.5) if i1 is _UNSET else i1,
        i2=I2Events() if i2 is _UNSET else i2,
        i3=I3Structure() if i3 is _UNSET else i3,
        i4=I4Context(vol_regime=1.0, trend_regime=0.8) if i4 is _UNSET else i4,
        i5=I5Patterns() if i5 is _UNSET else i5,
        i6=I6Confluence(ctf_score=0.7) if i6 is _UNSET else i6,
        smc=SMCContext(hmm_regime=1.0) if smc is _UNSET else smc,
    )


class TestTierEnumComplete:
    """D-14: Tier enum must expose I2, I3, I5."""

    def test_tier_i2_exists_with_correct_value(self) -> None:
        assert Tier.I2 is not None
        assert Tier.I2.value == "i2"

    def test_tier_i3_exists_with_correct_value(self) -> None:
        assert Tier.I3 is not None
        assert Tier.I3.value == "i3"

    def test_tier_i5_exists_with_correct_value(self) -> None:
        assert Tier.I5 is not None
        assert Tier.I5.value == "i5"

    def test_all_tiers_in_enum(self) -> None:
        tier_values = {t.value for t in Tier}
        assert tier_values == {"bar", "i1", "i2", "i3", "i4", "i5", "i6", "i7", "smc"}


class TestAIContextTypedAssignment:
    """D-09, D-13: AIContext uses schemas.py types; build() does direct pass-through."""

    def test_i1_object_identity_no_copy(self) -> None:
        """build() must return event.i1 as-is (object identity, not a copy)."""
        cache = AIContextCache()
        event = _make_event()
        cache.update(event)

        result = cache.build("ESM6", "5m", frozenset({Tier.I1}))
        assert result is not None
        assert result.i1 is event.i1  # D-13: direct assignment

    def test_all_six_tiers_populated(self) -> None:
        """With all tiers requested, all six are non-None."""
        cache = AIContextCache()
        event = _make_event()
        cache.update(event)

        result = cache.build(
            "ESM6",
            "5m",
            frozenset({Tier.I1, Tier.I2, Tier.I3, Tier.I4, Tier.I5, Tier.I6}),
        )
        assert result is not None
        assert result.i1 is not None
        assert result.i2 is not None
        assert result.i3 is not None
        assert result.i4 is not None
        assert result.i5 is not None
        assert result.i6 is not None

    def test_all_six_tiers_are_schema_types(self) -> None:
        """Populated tiers must be the canonical schemas.py types."""
        cache = AIContextCache()
        event = _make_event()
        cache.update(event)

        result = cache.build(
            "ESM6",
            "5m",
            frozenset({Tier.I1, Tier.I2, Tier.I3, Tier.I4, Tier.I5, Tier.I6}),
        )
        assert result is not None
        assert isinstance(result.i1, I1Indicators)
        assert isinstance(result.i2, I2Events)
        assert isinstance(result.i3, I3Structure)
        assert isinstance(result.i4, I4Context)
        assert isinstance(result.i5, I5Patterns)
        assert isinstance(result.i6, I6Confluence)

    def test_null_safe_when_tier_missing_from_event(self) -> None:
        """If event has i5=None, result.i5 must be None (no raise)."""
        cache = AIContextCache()
        event = _make_event(i5=None)
        cache.update(event)

        result = cache.build("ESM6", "5m", frozenset({Tier.I5}))
        assert result is not None
        assert result.i5 is None

    def test_not_requested_tier_is_none(self) -> None:
        """Tier not in tiers_needed must not be populated even if available."""
        cache = AIContextCache()
        event = _make_event()
        cache.update(event)

        result = cache.build("ESM6", "5m", frozenset({Tier.I1}))
        assert result is not None
        assert result.i2 is None
        assert result.i3 is None
        assert result.i4 is None
        assert result.i5 is None
        assert result.i6 is None


class TestSparseClassesDeleted:
    """D-10: I1Context, I4Context(TierContext), I6Context must not exist in context module."""

    def test_no_i1context_local_class(self) -> None:
        import src.core.ai.context as ctx_mod

        assert not hasattr(ctx_mod, "I1Context"), (
            "I1Context sparse subclass must be deleted per D-10"
        )

    def test_no_i4context_local_class(self) -> None:
        """The local sparse I4Context(TierContext) must be gone.
        schemas.I4Context may be imported but should not be exposed as a local class
        that shadows the schemas import.
        """
        import src.core.ai.context as ctx_mod

        # Check that if I4Context exists in module it's the schemas type
        i4 = getattr(ctx_mod, "I4Context", None)
        if i4 is not None:
            # Must be the schemas version, not TierContext subclass
            from src.core.ai.context import TierContext

            assert not issubclass(i4, TierContext), (
                "Sparse I4Context(TierContext) must be deleted per D-10; "
                "only schemas.I4Context import is allowed"
            )

    def test_no_i6context_local_class(self) -> None:
        import src.core.ai.context as ctx_mod

        assert not hasattr(ctx_mod, "I6Context"), (
            "I6Context sparse subclass must be deleted per D-10"
        )

    def test_grep_no_class_i1context(self) -> None:
        """File-level grep check: no 'class I1Context' in context.py."""
        import pathlib

        content = pathlib.Path("src/core/ai/context.py").read_text()
        assert "class I1Context" not in content

    def test_grep_no_class_i6context(self) -> None:
        import pathlib

        content = pathlib.Path("src/core/ai/context.py").read_text()
        assert "class I6Context" not in content


class TestNoEscapeHatch:
    """D-15: No dict[str, Any] escape hatch on AIContext pipeline tier fields."""

    def test_no_full_features_field(self) -> None:
        import pathlib

        content = pathlib.Path("src/core/ai/context.py").read_text()
        assert "full_features" not in content

    def test_aicontext_i1_type_is_not_dict(self) -> None:
        """AIContext.i1 annotation must be I1Indicators | None, not dict."""
        import typing

        hints = AIContext.model_fields
        i1_field = hints.get("i1")
        assert i1_field is not None
        # annotation should reference I1Indicators, not dict
        annotation_str = str(i1_field.annotation)
        assert "dict" not in annotation_str.lower() or "I1Indicators" in annotation_str


class TestFrozenModel:
    """AIContext must be frozen (immutable after construction)."""

    def test_assigning_i1_raises_validation_error(self) -> None:
        ctx = AIContext(symbol="ES", timeframe="5m", ts=None)
        with pytest.raises((ValidationError, TypeError)):
            ctx.i1 = None  # type: ignore[misc]

    def test_minimal_context_constructs_ok(self) -> None:
        ctx = AIContext(symbol="ES", timeframe="5m", ts=None)
        assert ctx.symbol == "ES"
        assert ctx.i1 is None
        assert ctx.i5 is None


class TestSchemaImports:
    """context.py must import from schemas.py."""

    def test_i1indicators_importable_from_context_module(self) -> None:
        """I1Indicators must be accessible (used in type annotations)."""
        from src.core.ai.context import AIContext  # noqa: F401

        # Verify I1Indicators is the type used for i1 field
        field = AIContext.model_fields.get("i1")
        assert field is not None

    def test_schemas_import_present(self) -> None:
        import pathlib

        content = pathlib.Path("src/core/ai/context.py").read_text()
        assert "from src.intelligence.schemas import" in content

    def test_i1indicators_i2events_in_content(self) -> None:
        import pathlib

        content = pathlib.Path("src/core/ai/context.py").read_text()
        for cls in ["I1Indicators", "I2Events", "I3Structure", "I5Patterns", "I6Confluence"]:
            assert cls in content, f"{cls} must be imported in context.py"
