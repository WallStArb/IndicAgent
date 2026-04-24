"""Tests for SkepticAgent compute class and prompt building."""
import json
from uuid import uuid4

from src.intelligence.swarm.agents.skeptic_agent import (
    _parse_skeptic_response,
    _validate_skeptic_fields,
)
from src.intelligence.swarm.agents.skeptic_prompts import (
    ACTIVE_VERSION,
    PROMPT_REGISTRY,
    build_skeptic_prompt,
)
from src.intelligence.swarm.context import SwarmContext


def test_active_version_in_registry():
    assert ACTIVE_VERSION in PROMPT_REGISTRY


def test_build_prompt_fills_fields():
    """Verify prompt template has all expected placeholders filled."""
    ctx = SwarmContext(
        signal_id=uuid4(), symbol="ESM6", timeframe="5m", ts=None,
        atr=12.5, adx=25.3, rsi=55.0,
        hmm_regime=1, trend_regime=0.7, vol_regime=0.3,
        vol_percentile=None, garch_vol_ratio=1.2, garch_vol_regime=None,
        kalman_trend=None, kalman_slope=None,
        vwap=4500.0, poc_price=4498.0, poc_price_rolling=4495.0,
        ctf_score=None, ctf_trend_alignment=0.8, ctf_structure_alignment=None,
        ctf_regime_agreement=0.6, ctf_timeframes_aligned=None,
        ctf_fvg_alignment=0.4, ctf_ob_alignment=0.3,
        winner_plugin="TrendFollowing", winner_direction=1,
        winner_confidence=0.75, price=4502.0, volume=1500,
    )
    prompt = build_skeptic_prompt(ctx)
    assert "ESM6" in prompt
    assert "5m" in prompt
    assert "TrendFollowing" in prompt
    assert "LONG" in prompt
    assert "N/A" not in prompt  # all fields set


def test_parse_valid_json():
    raw = json.dumps({
        "failure_probability": 0.7,
        "confidence": 0.8,
        "risk_factors": ["weak trend"],
        "reasoning": "test",
    })
    result = _parse_skeptic_response(raw)
    assert result is not None
    assert result["failure_probability"] == 0.7


def test_parse_json_with_preamble():
    raw = 'Here is my analysis:\n' + json.dumps({
        "failure_probability": 0.3,
        "confidence": 0.9,
        "risk_factors": [],
        "reasoning": "looks good",
    })
    result = _parse_skeptic_response(raw)
    assert result is not None
    assert result["failure_probability"] == 0.3


def test_parse_invalid_returns_none():
    assert _parse_skeptic_response("not json") is None
    assert _parse_skeptic_response("") is None


def test_validate_clamps_values():
    result = _validate_skeptic_fields({
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
    assert _validate_skeptic_fields({"failure_probability": 0.5}) is None
    assert _validate_skeptic_fields({"confidence": 0.5}) is None
