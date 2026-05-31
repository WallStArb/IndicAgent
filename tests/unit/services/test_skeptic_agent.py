"""Tests for SkepticAgent compute class and prompt building."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
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


# ---------------------------------------------------------------------------
# SkepticEvaluator class-attribute assertions
# ---------------------------------------------------------------------------


def test_skeptic_evaluator_agent_id_and_result_type():
    """agent_id must be 'skeptic' and result_type must be SkepticResult."""
    from src.intelligence.ai.alpha.skeptic_agent import SkepticEvaluator

    assert SkepticEvaluator.agent_id == "skeptic"
    assert SkepticEvaluator.result_type is SkepticResult
    assert SkepticEvaluator.prompt_version == ACTIVE_VERSION == "skeptic_v2"


# ---------------------------------------------------------------------------
# Transfer function test via mocked _run_typed
# ---------------------------------------------------------------------------


def _make_skeptic_evaluator():
    """Construct SkepticEvaluator bypassing __init__ (avoids LLMProviderChain dep)."""
    from src.intelligence.ai.alpha.skeptic_agent import SkepticEvaluator

    evaluator = SkepticEvaluator.__new__(SkepticEvaluator)
    evaluator.logger = MagicMock()

    # Build a tracer mock whose context manager yields a span mock with all needed attrs
    span_mock = MagicMock()
    cm_mock = MagicMock()
    cm_mock.__enter__ = MagicMock(return_value=span_mock)
    cm_mock.__exit__ = MagicMock(return_value=False)
    tracer_mock = MagicMock()
    tracer_mock.start_as_current_span = MagicMock(return_value=cm_mock)
    evaluator.tracer = tracer_mock

    evaluator._llm = MagicMock()
    evaluator._timeout_s = 120.0
    evaluator._agent_labels = {"agent_id": "skeptic", "group": "alpha"}
    evaluator.shadow_only = True
    evaluator._lineage = None  # no lineage recorder in unit tests
    return evaluator


def _make_fake_context():
    from src.intelligence.ai.context import SignalContext

    return SignalContext(symbol="ESM6", timeframe="5m", ts=datetime.now(UTC))


@pytest.mark.asyncio
async def test_compute_transfer_function_via_run_typed():
    """_compute returns correct multiplier when _run_typed returns a SkepticResult.

    multiplier = (1.0 - failure_probability) * confidence = (1.0 - 0.4) * 0.8 = 0.48
    """
    evaluator = _make_skeptic_evaluator()
    fake_context = _make_fake_context()

    fixed_result = SkepticResult(
        failure_probability=0.4,
        confidence=0.8,
        risk_factors=["x"],
        reasoning="r",
    )
    # Patch on the instance directly (method lives on BaseAIWorker parent)
    evaluator._run_typed = AsyncMock(return_value=fixed_result)

    output = await evaluator._compute(fake_context)

    assert output.output_type == "multiplier"
    assert output.payload["multiplier"] == pytest.approx((1.0 - 0.4) * 0.8)
    assert output.payload["failure_probability"] == pytest.approx(0.4)
    assert output.payload["risk_factors"] == ["x"]
    assert output.payload["confidence"] == pytest.approx(0.8)


# ---------------------------------------------------------------------------
# Neutral-on-failure regression test: pydantic ValidationError path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compute_neutral_on_validation_failure():
    """compute() returns neutral AgentOutput when _run_typed raises pydantic ValidationError.

    Proves BaseAIWorker.compute() wrapper neutralizes a validation failure,
    not only a generic Exception.
    """
    from pydantic import ValidationError

    evaluator = _make_skeptic_evaluator()
    fake_context = _make_fake_context()

    # Construct a real pydantic ValidationError by attempting to validate a bad dict.
    # pytest.raises collects the error cleanly.
    with pytest.raises(ValidationError) as exc_info:
        SkepticResult.model_validate({})
    validation_error = exc_info.value

    # Patch on the instance directly (method lives on BaseAIWorker parent)
    evaluator._run_typed = AsyncMock(side_effect=validation_error)

    # Patch the OTel metrics helpers that compute() calls to avoid real OTel setup
    with (
        patch("src.core.ai.base_agent.AI_AGENT_INVOCATIONS_TOTAL"),
        patch("src.core.ai.base_agent.AI_AGENT_DURATION_MS"),
        patch("src.core.ai.base_agent.AI_AGENT_ERRORS_TOTAL"),
    ):
        output = await evaluator.compute(fake_context)

    assert output.output_type == "neutral"
    assert output.error is not None
    assert output.error != ""
