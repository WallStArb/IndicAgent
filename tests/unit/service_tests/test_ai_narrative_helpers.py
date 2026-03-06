"""Tests for pure helper functions in ai_narrative_service."""

from services.ai_narrative_service import (
    _build_llm_call_payload,
    build_narrative_prompt,
    parse_aggregated_signal,
)


def _make_fields(direction: int = 1, **overrides) -> dict[bytes, bytes]:
    """Build a bytes-keyed field dict like xreadgroup returns."""
    base: dict[bytes, bytes] = {
        b"symbol": b"ESH6",
        b"timeframe": b"5m",
        b"timestamp": b"2026-02-19T14:05:00",
        b"direction": str(direction).encode(),
        b"confidence": b"0.74",
        b"confluence_score": b"0.81",
        b"setup_plugin": b"trad_TrendFollowing",
        b"signal_type": b"trend_following",
        b"entry_price": b"5102.50",
        b"stop_loss": b"5094.00",
        b"targets": b"5112.00,5118.50",
        b"regime_context": b"trending_up",
        b"supporting_factors": b"BOS confirmed, RSI bullish",
    }
    for k, v in overrides.items():
        key = k.encode() if isinstance(k, str) else k
        val = v.encode() if isinstance(v, str) else v
        base[key] = val
    return base


def test_parse_aggregated_signal_bullish():
    """Bullish signal (direction=1) is parsed to typed dict with correct fields."""
    result = parse_aggregated_signal(_make_fields(direction=1))
    assert result is not None
    assert result["direction"] == 1
    assert result["direction_label"] == "Bullish"
    assert result["symbol"] == "ESH6"
    assert result["confidence"] == 0.74
    assert result["entry_price"] == "5102.50"


def test_parse_aggregated_signal_bearish():
    """Bearish signal (direction=-1) has direction_label='Bearish'."""
    result = parse_aggregated_signal(_make_fields(direction=-1))
    assert result is not None
    assert result["direction"] == -1
    assert result["direction_label"] == "Bearish"


def test_parse_aggregated_signal_skips_zero_direction():
    """direction=0 returns None — no narrative needed for neutral bars."""
    result = parse_aggregated_signal(_make_fields(direction=0))
    assert result is None


def test_build_narrative_prompt_contains_key_fields():
    """Prompt contains entry price, stop, symbol, supporting factors, and /no_think prefix."""
    signal = parse_aggregated_signal(_make_fields(direction=1))
    prompt = build_narrative_prompt(signal)
    assert "ESH6" in prompt
    assert "5102.50" in prompt        # entry_price
    assert "5094.00" in prompt        # stop_loss
    assert "BOS confirmed" in prompt  # supporting_factors
    assert "/no_think" in prompt      # suppress qwen3 thinking overhead
    assert "Bullish" in prompt


# ── signal_id threading tests ────────────────────────────────────────────────

def test_parse_aggregated_signal_includes_signal_id():
    """signal_id present in stream fields is included in parse result."""
    result = parse_aggregated_signal(_make_fields(signal_id="abc-123"))
    assert result is not None
    assert result["signal_id"] == "abc-123"


def test_parse_aggregated_signal_signal_id_empty_when_missing():
    """signal_id absent from stream fields returns empty string in parse result."""
    result = parse_aggregated_signal(_make_fields())
    assert result is not None
    assert result["signal_id"] == ""


def test_build_llm_call_payload_uses_signal_id_from_signal_data():
    """_build_llm_call_payload passes signal_data['signal_id'] through to payload."""
    signal_data = {
        "signal_id": "test-uuid-456",
        "symbol": "ESH6",
        "timeframe": "5m",
        "regime_context": "trending",
        "confidence": 0.74,
        "entry_price": "5100",
        "stop_loss": "5090",
        "profit_target": "5120",
        "setup_plugin": "trad_TrendFollowing",
    }
    payload = _build_llm_call_payload(
        call_type="per_signal",
        signal_data=signal_data,
        group_name="",
        prompt="test prompt",
        response="test response",
        latency_ms=100.0,
        succeeded=True,
        model_id="qwen3.5:9b",
    )
    assert payload["signal_id"] == "test-uuid-456"


def test_build_llm_call_payload_empty_string_when_no_signal_id():
    """_build_llm_call_payload returns empty string for signal_id when not in signal_data."""
    payload = _build_llm_call_payload(
        call_type="per_signal",
        signal_data={},
        group_name="",
        prompt="test prompt",
        response=None,
        latency_ms=50.0,
        succeeded=False,
        model_id="ollama",
    )
    assert payload["signal_id"] == ""
