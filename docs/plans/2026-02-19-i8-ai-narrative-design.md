# I8 AI Narrative Service — Design

**Version:** 1.0.0
**Date:** 2026-02-19
**Status:** Approved — proceed to implementation plan

## Problem

The I1–I7 pipeline is fully operational: signals are generated, aggregated, and persisted to `signal_ledger`. But the output is machine-readable only. There is no human-readable synthesis layer — a trader cannot look at the system and understand *what it is thinking* or *why a setup fired*.

## Goal

Build `AINarrativeService` — a standalone async service that synthesizes aggregated trading signals into concise, human-readable market narratives using a local LLM (Ollama). This creates a feedback loop: for the first time, the quality of I7 signals becomes observable and evaluable by a human.

## Architecture

### Pipeline Position

```
signals:SYMBOL:TIMEFRAME:aggregated   ← fires only when setup is selected
          ↓
  AINarrativeService (consumer group)
          ↓
  Prompt builder (pure function, unit-testable)
          ↓
  Ollama /api/chat (qwen3:8b, /no_think, 15s timeout)
          ↓
  narratives:SYMBOL:TIMEFRAME  (stream, maxlen=100)
  narrative:SYMBOL:TIMEFRAME:latest  (hash, 90s TTL)
          ↓
  (future: SSE → Dashboard narrative panel)
```

### Key Design Decisions

**Input stream:** `signals:SYMBOL:TIMEFRAME:aggregated` (not `intelligence:`)
- Already contains `supporting_factors` and `regime_context` as human-readable strings
- No need to cross-reference the intelligence stream
- Natural cost control: stream only fires when `selected_signal is not None`

**Model:** `qwen3:8b` (default) via local Ollama at `http://localhost:11434`
- Best quality from available models (5.2GB, GPU-accelerated)
- Prefix prompt with `/no_think` to suppress thinking overhead
- Configurable: fall back to `phi4-mini:3.8b` for speed if needed

**Failure mode:** Ollama unavailable or timeout → log warning, continue without publishing. No crash, no retry storm.

## Data Flow

### Input — `signals:aggregated` message fields

```
symbol, timeframe, timestamp        ← identity
direction                           ← 1=bullish, -1=bearish, 0=neutral (skip)
confidence, confluence_score        ← signal quality
setup_plugin, signal_type           ← what fired
entry_price, stop_loss, targets     ← price levels (str)
supporting_factors                  ← comma-separated list (human-readable)
regime_context                      ← e.g. "trending_up"
```

### Prompt Structure

**System:** `"You are a professional futures trading analyst. Given a market signal, write a concise 2-3 sentence trading narrative. Be specific about price levels and directional bias. No disclaimers."`

**User:**
```
/no_think

Symbol: {symbol}, Timeframe: {timeframe}
Setup: {setup_plugin} — {direction_label} (confidence {confidence:.0%})
Entry: {entry_price} | Stop: {stop_loss} | Targets: {targets}
Regime: {regime_context}
Factors: {supporting_factors}
```

### Output — `narratives:SYMBOL:TIMEFRAME` message fields

```json
{
  "symbol": "ESH6",
  "timeframe": "5m",
  "timestamp": "2026-02-19T14:05:00",
  "narrative": "ES is establishing a trend-following setup...",
  "action_bias": "bullish",
  "confidence": "0.74",
  "model": "qwen3:8b",
  "latency_ms": "1243"
}
```

Also cached to `narrative:SYMBOL:TIMEFRAME:latest` hash with 90s TTL for instant dashboard reads.

## Cost Controls

Built-in, no configuration required:
- `signals:aggregated` stream only fires on selected setups — natural throttle
- `direction == 0` → skip immediately (no Ollama call)
- 15s per-call timeout with graceful failure
- `/no_think` prefix prevents qwen3:8b from generating hidden chain-of-thought

Maximum load: 3 symbols × 2 timeframes = 6 possible calls/minute. Trivially within Ollama capacity.

## Files

| File | Action |
|------|--------|
| `services/ai_narrative_service.py` | Create — main service |
| `config/ai_narrative_service.json` | Create — symbols, timeframes, model config |
| `tests/unit/service_tests/test_ai_narrative_service.py` | Create — 5 unit tests |

## Unit Tests (5 total)

1. `test_prompt_builder_formats_bullish_signal` — validates prompt contains entry, stop, factors
2. `test_prompt_builder_formats_bearish_signal` — direction -1 → "Bearish" label
3. `test_parse_aggregated_signal_extracts_all_fields` — bytes-keyed Redis dict → typed dict
4. `test_service_skips_zero_direction` — direction=0 → no Ollama call made
5. `test_ollama_timeout_returns_none` — simulated timeout → service continues, no crash

## Out of Scope (follow-on)

- Dashboard narrative panel (SSE wiring for `narratives:` stream)
- Batch narratives (end-of-session summary)
- Multi-timeframe narrative synthesis
- OpenRouter fallback for Ollama unavailability
