"""Tests for src/intelligence/narrative/prompts.py.

All functions are pure — no I/O, no LLM calls. Tests verify prompt content
and structure using BarIntelligenceRecord instances.
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock


def _make_record(
    symbol: str = "ESM6",
    tf: str = "1m",
    winner_plugin: str = "TrendFollowing",
    direction: int = 1,
    confidence: float = 0.80,
    hmm_regime: int = 1,
):
    from src.intelligence.schemas import BarIntelligenceRecord, IntelligenceEvent, RankedSignal

    event = MagicMock(spec=IntelligenceEvent)
    event.symbol = symbol
    event.tf = tf
    event.ts = datetime(2026, 4, 9, 14, 30, tzinfo=UTC)
    event.bar = MagicMock()
    event.bar.c = 5280.25
    event.bar.h = 5285.0
    event.bar.l = 5275.0
    event.i1 = MagicMock()
    event.i1.atr_14 = 8.5
    event.i1.rsi_14 = 62.0
    event.i4 = MagicMock()
    event.i4.hmm_regime = hmm_regime
    event.i4.hmm_regime_prob = 0.87
    event.i4.vwap = 5277.50
    event.i6 = MagicMock()
    event.i6.ctf_trend_alignment = 0.75
    event.i6.ctf_regime_agreement = 0.80

    winner = MagicMock(spec=RankedSignal)
    winner.plugin = winner_plugin
    winner.direction = direction
    winner.calibrated_confidence = confidence
    winner.is_winner = True

    record = MagicMock(spec=BarIntelligenceRecord)
    record.intelligence = event
    record.winner_plugin = winner_plugin
    record.winner_confidence = confidence
    record.winner_direction = direction
    record.ranked_signals = [winner]
    return record


def test_build_short_prompt_contains_symbol():
    from src.intelligence.narrative.prompts import build_short_prompt
    prompt = build_short_prompt(_make_record())
    assert "ESM6" in prompt


def test_build_short_prompt_contains_direction_label():
    from src.intelligence.narrative.prompts import build_short_prompt
    long_prompt = build_short_prompt(_make_record(direction=1))
    short_prompt = build_short_prompt(_make_record(direction=-1))
    assert "bullish" in long_prompt.lower() or "Bullish" in long_prompt
    assert "bearish" in short_prompt.lower() or "Bearish" in short_prompt


def test_build_deep_prompt_contains_confluence():
    from src.intelligence.narrative.prompts import build_deep_prompt
    prompt = build_deep_prompt(_make_record())
    assert any(word in prompt.lower() for word in ["confluence", "ctf", "alignment"])


def test_prompts_include_no_think_prefix():
    """Qwen3/Ollama models require /no_think prefix to avoid thinking token budget issues."""
    from src.intelligence.narrative.prompts import build_deep_prompt, build_short_prompt
    record = _make_record()
    assert build_short_prompt(record).startswith("/no_think")
    assert build_deep_prompt(record).startswith("/no_think")
