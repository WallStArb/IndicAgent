"""Tests for src/core/ai/prompt_utils — parse_llm_json, clamp."""


def test_parse_llm_json_clean_json():
    """Direct JSON parse returns dict when validator accepts."""
    from src.core.ai.prompt_utils import parse_llm_json

    result = parse_llm_json('{"a": 1}', lambda d: d)
    assert result == {"a": 1}


def test_parse_llm_json_regex_fallback():
    """Garbage prefix with embedded JSON returns dict via brace-counting fallback."""
    from src.core.ai.prompt_utils import parse_llm_json

    result = parse_llm_json('garbage {"a": 2} trailing', lambda d: d)
    assert result == {"a": 2}


def test_parse_llm_json_nested_braces():
    """Brace-counting fallback handles nested objects that the old flat regex could not."""
    from src.core.ai.prompt_utils import parse_llm_json

    raw = 'Here is the result: {"score": 0.8, "conditions": [{"type": "bullish"}]}'
    result = parse_llm_json(raw, lambda d: d)
    assert result == {"score": 0.8, "conditions": [{"type": "bullish"}]}


def test_parse_llm_json_not_json_returns_none():
    """Completely non-JSON string returns None."""
    from src.core.ai.prompt_utils import parse_llm_json

    result = parse_llm_json("not json at all", lambda d: d)
    assert result is None


def test_parse_llm_json_validator_rejects_returns_none():
    """Returns None when validator function rejects the parsed dict."""
    from src.core.ai.prompt_utils import parse_llm_json

    result = parse_llm_json('{"a": 1}', lambda d: None)
    assert result is None


def test_clamp_above_max():
    """Values above max are clamped to max."""
    from src.core.ai.prompt_utils import clamp

    assert clamp(5, 0, 1) == 1.0


def test_clamp_below_min():
    """Values below min are clamped to min."""
    from src.core.ai.prompt_utils import clamp

    assert clamp(-1, 0, 1) == 0.0


def test_clamp_in_range():
    """Values within [lo, hi] are returned unchanged."""
    from src.core.ai.prompt_utils import clamp

    assert clamp(0.5, 0, 1) == 0.5
