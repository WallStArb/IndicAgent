"""Tests for pure helper functions in ai_narrative_service."""

from services.ai_narrative_service import (
    _build_llm_call_payload,
    build_action_tag,
    build_deep_prompt,
    build_narrative_prompt,
    build_short_prompt,
    extract_deep_context,
    extract_short_context,
    get_structural_label,
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
    """Bearish signal (direction=-1) has direction_label=\'Bearish\'."""
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
    assert "5102.50" in prompt
    assert "5094.00" in prompt
    assert "BOS confirmed" in prompt
    assert "/no_think" in prompt
    assert "Bullish" in prompt


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
    """_build_llm_call_payload passes signal_data[\'signal_id\'] through to payload."""
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


# ── Three-tier helper tests ───────────────────────────────────────────────────

_SIGNAL = {
    "symbol": "GCJ6",
    "timeframe": "5m",
    "direction": 1,
    "direction_label": "Bullish",
    "confidence": 0.78,
    "setup_plugin": "LiquiditySweepReclaim",
    "signal_type": "sweep_long",
    "entry_price": "5108.7",
    "stop_loss": "5100.47",
    "profit_target": "5143.84",
    "risk_reward_ratio": "4.27",
    "regime_context": "bullish",
    "supporting_factors": "ma_alignment_bullish,fvg_fill",
    "signal_id": "sig-abc123",
    "timestamp": "2026-03-09T14:20:00Z",
}

_INTEL = {
    "hmm_regime": "2",
    "hmm_regime_prob": "0.87",
    "fvg_bottom": "5095.0",
    "fvg_top": "5108.0",
    "ob_bottom": "5099.0",
    "ob_top": "5110.0",
    "confluence_score": "0.82",
    "trend_confluence_score": "0.75",
    "killzone_name": "london",
    "in_london_killzone": "1",
    "nearest_demand_low": "5090.0",
    "nearest_demand_high": "5098.0",
}


def test_extract_short_context_includes_regime():
    ctx = extract_short_context(_SIGNAL, _INTEL)
    assert ctx["hmm_regime"] == "2"
    assert ctx["hmm_regime_prob"] == "0.87"
    assert ctx["killzone"] == "London"


def test_extract_short_context_includes_signal_fields():
    ctx = extract_short_context(_SIGNAL, _INTEL)
    assert ctx["confidence"] == 0.78
    assert ctx["entry"] == "5108.7"
    assert ctx["stop"] == "5100.47"
    assert ctx["target_1"] == "5143.84"


def test_extract_short_context_empty_intel():
    ctx = extract_short_context(_SIGNAL, {})
    assert ctx["entry"] == "5108.7"
    assert ctx["hmm_regime"] is None


def test_extract_deep_context_includes_fvg_bounds():
    ctx = extract_deep_context(_SIGNAL, _INTEL)
    assert ctx["fvg_bottom"] == "5095.0"
    assert ctx["fvg_top"] == "5108.0"
    assert ctx["ob_bottom"] == "5099.0"


def test_extract_deep_context_is_superset_of_short():
    short = extract_short_context(_SIGNAL, _INTEL)
    deep = extract_deep_context(_SIGNAL, _INTEL)
    for key in short:
        assert key in deep


def test_build_short_prompt_contains_key_fields():
    ctx = extract_short_context(_SIGNAL, _INTEL)
    prompt = build_short_prompt(_SIGNAL, ctx)
    assert "5108.7" in prompt
    assert "5100.47" in prompt
    assert "78%" in prompt or "0.78" in prompt
    assert "london" in prompt.lower() or "killzone" in prompt.lower()


def test_build_short_prompt_includes_confidence_instruction():
    ctx = extract_short_context(_SIGNAL, _INTEL)
    prompt = build_short_prompt(_SIGNAL, ctx)
    assert "direct" in prompt.lower() or "entry" in prompt.lower() or "act now" in prompt.lower()


def test_build_short_prompt_low_confidence_instructs_wait():
    low_signal = {**_SIGNAL, "confidence": 0.52}
    ctx = extract_short_context(low_signal, _INTEL)
    prompt = build_short_prompt(low_signal, ctx)
    assert "wait" in prompt.lower() or "conditional" in prompt.lower()


def test_build_deep_prompt_contains_fvg_bounds():
    ctx = extract_deep_context(_SIGNAL, _INTEL)
    prompt = build_deep_prompt(_SIGNAL, ctx)
    assert "5095" in prompt or "fvg" in prompt.lower()


def test_build_action_tag_high_confidence_bullish():
    tag = build_action_tag(_SIGNAL)
    assert "BULLISH" in tag
    assert "WAIT" not in tag


def test_build_action_tag_mid_confidence_shows_wait():
    sig = {**_SIGNAL, "confidence": 0.60}
    tag = build_action_tag(sig)
    assert "WAIT" in tag
    assert "BULLISH" in tag


def test_build_action_tag_low_confidence_shows_monitor():
    sig = {**_SIGNAL, "confidence": 0.40}
    tag = build_action_tag(sig)
    assert "MONITOR" in tag


def test_build_action_tag_bearish():
    sig = {**_SIGNAL, "direction": -1, "direction_label": "Bearish"}
    tag = build_action_tag(sig)
    assert "BEARISH" in tag


def test_get_structural_label_sweep():
    assert get_structural_label("LiquiditySweepReclaim") == "SWEEP RECLAIM"


def test_get_structural_label_fvg():
    assert get_structural_label("FVGFill") == "FVG FILL"


def test_get_structural_label_choch():
    assert get_structural_label("CHoCHReversal") == "REVERSAL"


def test_get_structural_label_unknown():
    label = get_structural_label("UnknownPlugin")
    assert isinstance(label, str)
    assert len(label) > 0
