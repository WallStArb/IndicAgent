"""Tests for SkepticAgent compute class and prompt building."""

from uuid import uuid4

import pytest

from src.intelligence.ai.alpha.skeptic_prompts import (
    ACTIVE_VERSION,
    PROMPT_REGISTRY,
    SkepticResult,
    build_skeptic_prompt,
)


def test_active_version_in_registry():
    assert ACTIVE_VERSION in PROMPT_REGISTRY


def test_build_prompt_fills_fields(monkeypatch):
    """Verify v1 prompt template has all expected placeholders filled (dict path)."""
    import src.intelligence.ai.alpha.skeptic_prompts as _sp

    monkeypatch.setattr(_sp, "ACTIVE_VERSION", "skeptic_v1")
    ctx = {
        "signal_id": uuid4(),
        "symbol": "ESM6",
        "timeframe": "5m",
        "ts": None,
        "atr": 12.5,
        "adx": 25.3,
        "rsi": 55.0,
        "hmm_regime": 1,
        "trend_regime": 0.7,
        "vol_regime": 0.3,
        "vol_percentile": None,
        "garch_vol_ratio": 1.2,
        "garch_vol_regime": None,
        "kalman_trend": None,
        "kalman_slope": None,
        "vwap": 4500.0,
        "poc_price": 4498.0,
        "poc_price_rolling": 4495.0,
        "ctf_score": None,
        "ctf_trend_alignment": 0.8,
        "ctf_structure_alignment": None,
        "ctf_regime_agreement": 0.6,
        "ctf_timeframes_aligned": None,
        "ctf_fvg_alignment": 0.4,
        "ctf_ob_alignment": 0.3,
        "winner_plugin": "TrendFollowing",
        "winner_direction": 1,
        "winner_confidence": 0.75,
        "price": 4502.0,
        "volume": 1500,
    }
    prompt = build_skeptic_prompt(ctx)
    assert "ESM6" in prompt
    assert "5m" in prompt
    assert "TrendFollowing" in prompt
    assert "LONG" in prompt
    assert "N/A" not in prompt  # all fields set


def test_skeptic_result_valid():
    """SkepticResult parses valid LLM output dict."""
    result = SkepticResult(
        failure_probability=0.7,
        confidence=0.8,
        risk_factors=["weak trend"],
        reasoning="test",
    )
    assert result.failure_probability == 0.7
    assert result.confidence == 0.8


def test_skeptic_result_clamps_floats():
    """SkepticResult clamps failure_probability and confidence to [0, 1]."""
    result = SkepticResult(
        failure_probability=1.5,
        confidence=-0.5,
        risk_factors=[],
        reasoning="test",
    )
    assert result.failure_probability == 1.0
    assert result.confidence == 0.0


def test_skeptic_result_coerces_risk_factors_to_list():
    """SkepticResult coerces non-list risk_factors to list[str]."""
    result = SkepticResult(
        failure_probability=0.5,
        confidence=0.5,
        risk_factors="not a list",
        reasoning="test",
    )
    assert isinstance(result.risk_factors, list)
    assert result.risk_factors == ["not a list"]


def test_skeptic_result_coerces_reasoning_to_str():
    """SkepticResult coerces non-str reasoning to str."""
    result = SkepticResult(
        failure_probability=0.5,
        confidence=0.5,
        risk_factors=[],
        reasoning=123,
    )
    assert isinstance(result.reasoning, str)
    assert result.reasoning == "123"


def test_skeptic_result_rejects_missing_fields():
    """SkepticResult raises ValidationError when required fields are missing."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SkepticResult(failure_probability=0.5)

    with pytest.raises(ValidationError):
        SkepticResult(confidence=0.5)
