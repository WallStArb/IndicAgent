"""Tests for CorrelationAgent compute class and prompt building."""
import json
from uuid import uuid4

from src.intelligence.ai.alpha.correlation_agent import (
    _parse_correlation_response,
    _validate_correlation_fields,
)
from src.intelligence.ai.alpha.correlation_prompts import (
    ACTIVE_VERSION,
    PROMPT_REGISTRY,
    build_correlation_prompt,
    get_lead_index,
)


def _make_ctx(**overrides) -> dict:
    """Build a minimal context dict for testing."""
    defaults = dict(
        signal_id=uuid4(), symbol="NQM6", timeframe="5m", ts=None,
        atr=12.5, adx=25.3, rsi=55.0,
        hmm_regime=1, trend_regime=0.7, vol_regime=0.3,
        vol_percentile=None, garch_vol_ratio=None, garch_vol_regime=None,
        kalman_trend=None, kalman_slope=None,
        vwap=None, poc_price=None, poc_price_rolling=None,
        ctf_score=None, ctf_trend_alignment=0.8, ctf_structure_alignment=None,
        ctf_regime_agreement=0.6, ctf_timeframes_aligned=None,
        ctf_fvg_alignment=0.4, ctf_ob_alignment=0.3,
        winner_plugin="TrendFollowing", winner_direction=1,
        winner_confidence=0.75, price=18050.0, volume=1500,
    )
    defaults.update(overrides)
    return defaults


def test_active_version_in_registry():
    assert ACTIVE_VERSION in PROMPT_REGISTRY


def test_build_prompt_without_lead_context():
    """Prompt builds fine when lead_context is None."""
    ctx = _make_ctx()
    prompt = build_correlation_prompt(ctx)
    assert "NQM6" in prompt
    assert "5m" in prompt
    assert "TrendFollowing" in prompt
    assert "LONG" in prompt
    assert "N/A" in prompt  # lead fields should be N/A


def test_build_prompt_with_lead_context():
    """Prompt fills lead index fields when lead fields are set."""
    ctx = _make_ctx(
        lead_symbol="ESM6",
        lead_trend_regime=0.5,
        trend_regime=0.7,
    )
    prompt = build_correlation_prompt(ctx)
    assert "ESM6" in prompt
    # The prompt should show both trend regimes
    assert "0.70" in prompt  # asset trend regime
    assert "0.50" in prompt  # lead trend regime


def test_build_prompt_uses_lead_context_not_private():
    """Per D-16: reads context.lead_symbol (not _lead_ctx)."""
    ctx = _make_ctx(lead_symbol="ESM6")
    prompt = build_correlation_prompt(ctx)
    assert "ESM6" in prompt


def test_get_lead_index():
    """Lead index mapping works for known symbols."""
    assert get_lead_index("NQM6") == "ES"
    assert get_lead_index("ESM6") == "ES"  # self-lead
    assert get_lead_index("CLK6") == "CL"
    assert get_lead_index("GCM6") == "GC"
    assert get_lead_index("UNKNOWN") is None


def test_parse_valid_json():
    raw = json.dumps({
        "failure_probability": 0.7,
        "confidence": 0.8,
        "risk_factors": ["decorrelation"],
        "reasoning": "test",
    })
    result = _parse_correlation_response(raw)
    assert result is not None
    assert result["failure_probability"] == 0.7


def test_parse_json_with_preamble():
    raw = 'Here is my analysis:\n' + json.dumps({
        "failure_probability": 0.3,
        "confidence": 0.9,
        "risk_factors": [],
        "reasoning": "correlated",
    })
    result = _parse_correlation_response(raw)
    assert result is not None
    assert result["failure_probability"] == 0.3


def test_parse_invalid_returns_none():
    assert _parse_correlation_response("not json") is None
    assert _parse_correlation_response("") is None


def test_validate_clamps_values():
    result = _validate_correlation_fields({
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
    assert _validate_correlation_fields({"failure_probability": 0.5}) is None
    assert _validate_correlation_fields({"confidence": 0.5}) is None
