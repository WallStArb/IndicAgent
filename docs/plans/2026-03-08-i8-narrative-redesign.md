# I8 Narrative Redesign — Two-Tier LLM Synthesis

**Date:** 2026-03-08
**Status:** Approved
**Author:** Design session

---

## Problem

The current narrative is a thin wrapper around signal metadata. It outputs 2-3 sentences that read like a template fill-in — direction, setup name, confidence percentage. It throws away 95% of the intelligence the pipeline computed: SMC zones, HMM regime state, FVG bounds, cross-TF confluence alignment, group context. A PM reading it learns nothing they couldn't read off the raw card fields.

**Goal:** A non-quant PM reads the narrative and knows exactly what the market is doing, why this setup matters, where to act (or wait), and what would prove the thesis wrong.

---

## Design

### Two-Tier Architecture

| Tier | Model | Latency | Role |
|------|-------|---------|------|
| Short | GLM-4.7 | ~1-2s | One punch-line sentence. Card always shows this immediately. |
| Deep | GLM-5 | ~5-8s | Full trading desk brief. Revealed on expand. |

Both calls fire as soon as the signal arrives. Short appears first; deep appears when ready.
Both stored in `llm_calls` with `call_type = "narrative_short"` / `call_type = "narrative_deep"`.
Both scored by `llm_writer_service` for the learning loop.

---

### Signal Card Anatomy

**Always visible:**
```
BTCUSD  15m  ▲ Bullish
Bar: 16:40:00 · Signal: 16:42:07 · Synth: 2.1s pipeline lag
Entry 67,200 | Stop 66,380 | T1 67,850

"BTC reclaiming structure at a 3-TF confluent order block —
ideal to wait for a pull-back to 66,800–67,100 rather than
chase the breakout here."

▼ Full analysis
```

**Expanded (GLM-5 deep brief):**
```
[3-4 sentences — see Deep Narrative format below]

T2: 68,400  T3: 69,200  R:R 2.8

[Invalidation / group confirmation]
```

**Metadata fields (structured data, not LLM-generated):**
- `bar_time` — the bar close timestamp that triggered the signal
- `signal_generated_at` — when I7 computed the signal
- Synthesis latency — `narrative_generated_at − bar_close_time` (full pipeline lag, a demo metric)
- T1/T2/T3 — already published as `profit_target`, `profit_target_2`, `profit_target_3` in stream

---

### Prompt Design Principles

**Core rule:** Every factor mentioned must be followed by *why it matters*. Never list data — only explain significance.

> Bad: "HMM regime is trending, RSI divergence detected, FVG at 66,800"
> Good: "The 1h trend regime confirms this isn't noise — price is in a clean impulse, and the FVG at 66,800 is where institutions left unfilled orders, making it the highest-probability entry rather than chasing the current price"

**System prompt (both tiers):**
```
You are a professional trading analyst briefing a portfolio manager who is not a quant.
For every factor you mention, explain why it matters to this trade.
Never list raw data or indicator values — only explain significance and actionability.
Be specific about price levels. No disclaimers. No filler.
```

---

### Short Narrative Prompt (GLM-4.7)

**Format:** One sentence. Setup thesis + key zone/action + why now.

**Prompt template:**
```
/no_think

{SYMBOL} {TF} — {DIRECTION} signal ({SETUP_TYPE})
Regime: {HMM_STATE} | Vol: {GARCH_STATE}
Key zone: {ZONE_TYPE} at {ZONE_LOW}–{ZONE_HIGH}
Cross-TF: {N} timeframes aligned ({TF_LIST})
Confidence: {CONFIDENCE_PCT}

Write ONE sentence: what the market is doing and what the trader should watch for or do.
Lead with the asset and direction. Include the key zone if it adds actionability.
```

**Fields selected (distilled, not dumped):**
- `hmm_regime` translated: 0=ranging, 1=trending-up, 2=trending-down
- `garch_vol_state`: expanding / contracting / elevated
- Nearest zone (FVG or OB): low/high bounds
- `confluence_score` → number of aligned TFs
- `setup_plugin` translated to plain English (e.g. "FVGFill" → "unfilled institutional gap")

---

### Deep Narrative Prompt (GLM-5)

**Format:** 3-4 sentences. Each answers a specific PM question.

**Sentence structure:**
1. **Why this setup matters** — what confluence of structure, regime, and pattern created this
2. **Where to act and why that zone** — the specific level, what makes it significant (OB, FVG, S/D, key structure)
3. **What invalidates the thesis** — the specific price level or condition that proves this wrong
4. **Broader context** — does the asset group confirm, diverge, or add conviction?

**Prompt template:**
```
/no_think

{SYMBOL} {TF} — {DIRECTION} ({SETUP_TYPE}, confidence {CONFIDENCE_PCT})
Entry: {ENTRY} | Stop: {STOP} | T1: {T1} T2: {T2} T3: {T3}

Market structure:
- Regime: {HMM_STATE_PLAIN} with {GARCH_STATE_PLAIN} volatility
- BOS/CHoCH: {BOS_DIRECTION} confirmed at {BOS_LEVEL}
- Nearest zone: {ZONE_TYPE} {ZONE_LOW}–{ZONE_HIGH} ({ZONE_SIGNIFICANCE})
- FVG: {FVG_PRESENT} at {FVG_BOTTOM}–{FVG_TOP}
- Killzone: {KILLZONE_ACTIVE}
- Active divergences: {DIVERGENCE_SUMMARY}
- Squeeze: {SQUEEZE_STATE}

Cross-timeframe:
- {N} of {TOTAL} TFs aligned {DIRECTION}: {ALIGNED_TF_LIST}
- Highest TF confirming: {HTF_CONFIRMATION}

{GROUP_CONTEXT_IF_AVAILABLE}

Write 3-4 sentences for a portfolio manager:
1. Why this setup is significant right now (not just what happened)
2. Where to act and exactly why that level — is it wait-for-zone or act-now?
3. What specific price action would invalidate this thesis
4. Whether the broader {GROUP_NAME} picture confirms or adds caution
Do not use indicator jargon. Explain significance, not mechanics.
```

**Fields selected:**
- I4: `hmm_regime` (plain English), `garch_vol_regime`
- I6 SMC: `bos_direction`, `bos_level`, nearest FVG bounds, nearest OB bounds, `killzone_active`
- I5: active divergences (RSI/vol), squeeze state
- I6 Confluence: aligned TF count + list, highest confirming TF
- Group synthesis: if available within 2s window, append; otherwise omit gracefully

**Fields explicitly excluded** (raw indicator values that don't add meaning):
- SMA/EMA values, RSI value, MACD value, raw Stochastic
- Exact volume numbers
- Individual plugin scores

---

### Data Enrichment

The narrative service currently only reads from `signals:SYMBOL:TF:aggregated`. To build the richer prompt it also needs the latest `intelligence:SYMBOL:TF` event from Redis (published by `market_analysis_service`).

Approach: at call time, do a single `XREVRANGE intelligence:SYMBOL:TF + - COUNT 1` to get the most recent intelligence event. Latency: ~1ms. The intelligence event carries the full tiered JSONB (i1/i3/i4/i5/smc/i6) needed for the deep prompt.

Parse only the fields listed above — no full JSONB dump into the prompt.

---

### Stream Changes

`narratives:SYMBOL:TF` stream gains two new fields:
- `narrative_type`: `"short"` | `"deep"`
- `synthesis_latency_ms`: `narrative_generated_at − bar_close_time` in ms

Both narratives published as separate stream entries. Dashboard subscribes and applies each as it arrives.

---

### Dashboard Changes

Signal card:
- Always shows short narrative immediately when signal fires
- `▼ Full analysis` toggle — smooth fade-in when GLM-5 response arrives
- T2/T3 shown in expanded section (already in stream, just not rendered)
- Synthesis latency shown as a subtle metadata field ("Synth: 2.1s")

No new panels required. Works within existing card component.

---

## What This Demonstrates

For the demo audience:
- **Speed**: card lights up in ~2s with an intelligent, human-readable thesis
- **Depth**: one click reveals institutional-quality analysis that a quant spent an hour writing, generated automatically
- **Pipeline**: the synthesis latency metric shows the full I1→I8 loop in real time
- **Intelligence**: the narrative proves the system understands market structure, not just pattern-matched data

---

## Files to Modify

- `services/ai_narrative_service.py` — dual call chain, enriched prompt builders, stream fields
- `src/intelligence/llm_providers.py` — GLM-4.7 model config (ZAIProvider already works)
- `src/config/settings.py` — `zai_model_short`, `zai_model_deep` settings
- `dashboard/src/` — signal card expand/collapse + T2/T3 display + synthesis latency
