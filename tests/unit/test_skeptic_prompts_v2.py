"""Tests for skeptic_v2 prompt — typed AIContext rendering.

Plan 078-05, Task 2:
- render_full_context iterates model_fields (open-ended, D-16)
- skeptic_v2 registered as ACTIVE_VERSION (D-17)
- v1 preserved for rollback
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from pydantic import BaseModel

from src.core.ai.context import AIContext, I7Context, render_full_context
from src.intelligence.ai.alpha.skeptic_prompts import (
    ACTIVE_VERSION,
    PROMPT_REGISTRY,
    build_skeptic_prompt,
)
from src.intelligence.schemas import I1Indicators, I4Context, I6Confluence


def _make_ctx(
    *,
    symbol: str = "ESM6",
    timeframe: str = "5m",
    i1: I1Indicators | None = None,
    i4: I4Context | None = None,
    i6: I6Confluence | None = None,
    i7: I7Context | None = None,
) -> AIContext:
    return AIContext(
        symbol=symbol,
        timeframe=timeframe,
        ts=datetime.now(tz=UTC),
        i1=i1,
        i4=i4,
        i6=i6,
        i7=i7,
    )


class TestRenderFullContext:
    """Tests for render_full_context helper (D-16 open-ended iteration)."""

    def test_renders_i1_section_when_present(self) -> None:
        ctx = _make_ctx(i1=I1Indicators(rsi_14=55.0))
        result = render_full_context(ctx)
        assert "## i1" in result

    def test_renders_rsi_14_field_correctly(self) -> None:
        ctx = _make_ctx(i1=I1Indicators(rsi_14=55.0))
        result = render_full_context(ctx)
        assert "- rsi_14: 55.0000" in result

    def test_renders_none_fields_as_null(self) -> None:
        ctx = _make_ctx(i1=I1Indicators(rsi_14=55.0, atr_14=None))
        result = render_full_context(ctx)
        assert "- atr_14: null" in result

    def test_skips_i5_section_when_none(self) -> None:
        """When i5 is None, no ## i5 section appears."""
        ctx = _make_ctx(i1=I1Indicators(rsi_14=55.0))
        result = render_full_context(ctx)
        assert "## i5" not in result

    def test_open_ended_new_tier_automatically_appears(self) -> None:
        """A new BaseModel tier added to AIContext auto-appears with no code change.

        We test this by creating a patched AIContext subclass with an extra tier.
        """

        class SyntheticTierModel(BaseModel):
            fancy_signal: float | None = 99.0

        # Build an actual AIContext and then simulate an extra tier by patching
        # model_fields at class level to include a synthetic entry.
        ctx = _make_ctx(i1=I1Indicators(rsi_14=55.0))

        # Patch model_fields to include a synthetic tier
        original_fields = AIContext.model_fields.copy()
        import pydantic.fields

        fake_field = pydantic.fields.FieldInfo(annotation=SyntheticTierModel | None, default=None)
        patched_fields = dict(original_fields, synthetic_tier=fake_field)

        with patch.object(AIContext, "model_fields", patched_fields):
            # Add the attribute to the frozen model via object.__setattr__
            object.__setattr__(ctx, "synthetic_tier", SyntheticTierModel(fancy_signal=99.0))
            result = render_full_context(ctx)

        assert "## synthetic_tier" in result
        assert "- fancy_signal: 99.0000" in result

    def test_iteration_uses_model_fields_not_hardcoded_list(self) -> None:
        """The implementation must reference model_fields, not a hardcoded tier list."""
        import pathlib

        content = pathlib.Path("src/core/ai/context.py").read_text()
        assert (
            "model_fields" in content
        ), "render_full_context must iterate ctx.__class__.model_fields"
        # Should NOT have hardcoded 'i1', 'i2' tier list inside the function
        # (checking for a list literal that enumerates all six tiers)
        assert '"i1", "i2"' not in content

    def test_empty_context_returns_no_features_message(self) -> None:
        ctx = _make_ctx()  # all tiers None
        result = render_full_context(ctx)
        assert result == "(no features available)"


class TestBuildSkepticPromptV2:
    """Tests for build_skeptic_prompt with ACTIVE_VERSION == 'skeptic_v2'."""

    def test_v2_prompt_contains_symbol(self) -> None:
        ctx = _make_ctx(
            symbol="NQM6",
            i4=I4Context(vol_regime=1.2, trend_regime=0.9),
        )
        with patch("src.intelligence.ai.alpha.skeptic_prompts.ACTIVE_VERSION", "skeptic_v2"):
            prompt = build_skeptic_prompt(ctx)

        assert "NQM6" in prompt

    def test_v2_prompt_contains_i4_section(self) -> None:
        ctx = _make_ctx(
            symbol="ESM6",
            i4=I4Context(vol_regime=1.2, trend_regime=0.9),
        )
        with patch("src.intelligence.ai.alpha.skeptic_prompts.ACTIVE_VERSION", "skeptic_v2"):
            prompt = build_skeptic_prompt(ctx)

        assert "## i4" in prompt

    def test_v2_raises_type_error_on_dict_input(self) -> None:
        """skeptic_v2 must reject dict input (was v1 contract)."""
        ctx_dict = {"symbol": "ESM6", "timeframe": "5m"}
        with patch("src.intelligence.ai.alpha.skeptic_prompts.ACTIVE_VERSION", "skeptic_v2"):
            with pytest.raises(TypeError, match="skeptic_v2 requires AIContext"):
                build_skeptic_prompt(ctx_dict)  # type: ignore[arg-type]


class TestSkepticV1BackCompat:
    """v1 must remain working for rollback."""

    def test_v1_still_in_registry(self) -> None:
        assert "skeptic_v1" in PROMPT_REGISTRY

    def test_v1_works_with_dict_input(self) -> None:
        ctx_dict = {
            "symbol": "ESM6",
            "timeframe": "5m",
            "winner_plugin": "TrendFollowing",
            "winner_direction": 1,
            "winner_confidence": 0.75,
            "price": 4500.0,
            "volume": 1000.0,
            "atr": 12.5,
            "rsi": 55.0,
            "adx": 25.0,
            "hmm_regime": 1,
            "trend_regime": 0.9,
            "vol_regime": 1.2,
            "garch_vol_ratio": 1.1,
            "ctf_trend_alignment": 0.8,
            "ctf_regime_agreement": 0.7,
            "ctf_fvg_alignment": 0.6,
            "ctf_ob_alignment": 0.5,
            "vwap": 4490.0,
            "poc_price": 4485.0,
            "poc_price_rolling": 4480.0,
        }
        with patch("src.intelligence.ai.alpha.skeptic_prompts.ACTIVE_VERSION", "skeptic_v1"):
            result = build_skeptic_prompt(ctx_dict)

        assert "ESM6" in result
        assert "TrendFollowing" in result


class TestActiveVersion:
    """ACTIVE_VERSION must be skeptic_v2 after this plan."""

    def test_active_version_is_skeptic_v2(self) -> None:
        assert ACTIVE_VERSION == "skeptic_v2"

    def test_v2_in_registry(self) -> None:
        assert "skeptic_v2" in PROMPT_REGISTRY
