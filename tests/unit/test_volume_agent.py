"""Tests for VolumeAgent compute class and prompt building."""
import json
from uuid import uuid4

from src.intelligence.swarm.agents.volume_agent import (
    _parse_volume_response,
    _validate_volume_fields,
)
from src.intelligence.swarm.agents.volume_prompts import (
    ACTIVE_VERSION,
    PROMPT_REGISTRY,
    build_volume_prompt,
)
from src.intelligence.swarm.context import SwarmContext


def _make_ctx(**overrides) -> SwarmContext:
    """Build a minimal SwarmContext for testing."""
    defaults = dict(
        signal_id=uuid4(), symbol="ESM6", timeframe="5m", ts=None,
        atr=12.5, adx=25.3, rsi=55.0,
        hmm_regime=1, trend_regime=0.7, vol_regime=0.3,
        vol_percentile=None, garch_vol_ratio=None, garch_vol_regime=None,
        kalman_trend=None, kalman_slope=None,
        vwap=4500.0, poc_price=4498.0, poc_price_rolling=4495.0,
        ctf_score=None, ctf_trend_alignment=0.8, ctf_structure_alignment=None,
        ctf_regime_agreement=0.6, ctf_timeframes_aligned=None,
        ctf_fvg_alignment=0.4, ctf_ob_alignment=0.3,
        winner_plugin="TrendFollowing", winner_direction=1,
        winner_confidence=0.75, price=4502.0, volume=1500,
    )
    defaults.update(overrides)
    return SwarmContext(**defaults)


def test_active_version_in_registry():
    assert ACTIVE_VERSION in PROMPT_REGISTRY


def test_build_prompt_without_volume_profile():
    """Prompt builds fine when volume_profile is None."""
    ctx = _make_ctx(volume_profile=None)
    prompt = build_volume_prompt(ctx)
    assert "ESM6" in prompt
    assert "5m" in prompt
    assert "TrendFollowing" in prompt


def test_build_prompt_with_volume_profile():
    """Prompt fills VP fields when volume_profile dict is set."""
    vp = {
        "vah": 4510.0,
        "val": 4490.0,
        "vah_rolling": 4512.0,
        "val_rolling": 4488.0,
        "price_in_value_area": 1.0,
        "distance_to_vah_atr": 0.65,
        "distance_to_val_atr": -0.35,
    }
    ctx = _make_ctx(volume_profile=vp)
    prompt = build_volume_prompt(ctx)
    assert "4510.00" in prompt  # VAH
    assert "4490.00" in prompt  # VAL
    assert "0.650" in prompt  # distance_to_vah_atr


def test_build_prompt_uses_volume_profile_not_private():
    """Per D-16: reads context.volume_profile (not _volume_data)."""
    ctx = _make_ctx(volume_profile={"vah": 4510.0})
    prompt = build_volume_prompt(ctx)
    assert "4510.00" in prompt


def test_parse_valid_json():
    raw = json.dumps({
        "failure_probability": 0.6,
        "confidence": 0.85,
        "risk_factors": ["low volume"],
        "reasoning": "test",
    })
    result = _parse_volume_response(raw)
    assert result is not None
    assert result["failure_probability"] == 0.6


def test_parse_json_with_preamble():
    raw = 'Analysis:\n' + json.dumps({
        "failure_probability": 0.2,
        "confidence": 0.9,
        "risk_factors": [],
        "reasoning": "strong volume",
    })
    result = _parse_volume_response(raw)
    assert result is not None
    assert result["failure_probability"] == 0.2


def test_parse_invalid_returns_none():
    assert _parse_volume_response("not json") is None
    assert _parse_volume_response("") is None


def test_validate_clamps_values():
    result = _validate_volume_fields({
        "failure_probability": 1.5,
        "confidence": -0.5,
        "risk_factors": "not a list",
        "reasoning": 123,
    })
    assert result is not None
    assert result["failure_probability"] == 1.0  # clamped
    assert result["confidence"] == 0.0  # clamped
    assert isinstance(result["risk_factors"], list)
    assert isinstance(result["reasoning"], str)


def test_validate_rejects_missing_fields():
    assert _validate_volume_fields({"failure_probability": 0.5}) is None
    assert _validate_volume_fields({"confidence": 0.5}) is None
