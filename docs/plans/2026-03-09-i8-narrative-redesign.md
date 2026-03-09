# I8 Narrative Redesign — Three-Tier Intelligence Briefing

**Date:** 2026-03-09
**Status:** Approved
**Supersedes:** `2026-03-08-i8-narrative-redesign.md`, `2026-03-08-i8-narrative-implementation.md`

---

## Problem

The current narrative is data-starved and voice-blind. `build_narrative_prompt` receives only stripped-down signal metadata (setup name, direction, entry/stop/target, a string regime label, internal factor codes). None of the rich intelligence the pipeline computed — FVG bounds, OB levels, HMM state probabilities, cross-TF confluence breakdown, killzone context — reaches the LLM. The result is template-filling prose that sounds robotic and tells a PM nothing they couldn't read off the raw card fields.

**Examples of bad output:**
- *"Gold futures are capitalizing on a bullish 5-minute pattern completion to initiate a long position at 5108.7..."*
- *"Execute long orders on ESH6 at 6653.0 to capture the bullish pattern completion within the strong regime..."*

Both are wordy, passive, and content-free.

---

## Core Principle

> A PM's brain is wired for **Context + Execution**.

The split is clean:
- **Signal bar** — deterministic, instant, assembled from pipeline output. Zero LLM.
- **Short narrative** — LLM interprets: *why this structure matters right now*, *what to do given confidence level*
- **Deep narrative** — LLM explains: *the full confluence story, key levels, confidence-weighted guidance*

Renaissance principle applied: the signal bar states facts the system already computed with precision. Letting an LLM restate those facts introduces hallucination risk at the highest-visibility layer. The LLM earns its place at the layers where structured data can't do the job.

---

## Architecture

### Three-Tier Output

| Tier | Source | Latency | Always visible |
|------|--------|---------|----------------|
| Signal bar | Deterministic from signal stream | Instant | Yes |
| Short narrative | `narrative_short` LLM call | ~500ms | Yes |
| Deep narrative | `narrative_deep` LLM call | ~5-8s | On expand |

### Data Enrichment

At signal time, narrative service does one `XREVRANGE` lookup on `intelligence:SYMBOL:TF` to get the latest typed bus payload. Extracts two context packages:

**Short context (pre-digested):**
- HMM regime label + state probability
- Dominant structural event (BOS, reclaim, FVG fill, liquidity sweep)
- Cross-TF confluence count
- Entry, stop, T1
- Confidence level
- Active killzone (if any)

**Deep context (full):**
- Everything in short context plus:
- Full FVG bounds, OB levels, supply/demand zone levels
- All targets T1/T2/T3 with R:R
- Full confluence breakdown per timeframe
- HMM state probabilities across states
- Supporting factors list

### Call Layer

Two async calls fire concurrently from the same pre-fetched context:

```python
short_task = asyncio.create_task(chain_short.generate(short_prompt, system_prompt))
deep_task  = asyncio.create_task(chain_deep.generate(deep_prompt, system_prompt))
```

Both use `LLMChain` with standard OpenRouter provider order. No model hardcoding. `_apply_score_routing()` optimizes each call type independently based on `llm_model_scores` outcome data — `narrative_short` learns which fast models hit sub-500ms with quality, `narrative_deep` learns which models produce better confluence stories.

Both stored in `llm_calls` with `call_type = "narrative_short"` / `"narrative_deep"`. Both scored by `llm_writer_service` for the learning loop.

---

## Prompt Engineering

### System Prompt (both tiers)

> You are a senior trading desk analyst briefing a portfolio manager. Write with precision and economy. Never use passive voice. Never hedge with "suggests" or "indicates" — the system computed these signals with statistical confidence, state them directly. Never restate the setup name or direction label — the PM already sees those. Your job is to explain WHY this structure matters right now and WHAT to do about it.

**Banned phrases:** "capitalizing on", "execute long orders", "protect the position", "price momentum suggests", "within the established regime", "deliver a risk-to-reward."

### Short Prompt — Pre-digested inputs

```
Regime: trending (HMM state 2, prob 0.87)
Structure: liquidity sweep reclaim at 3-TF confluent order block
Confluence: 3 timeframes aligned bullish
Entry: 67200 | Stop: 66380 | T1: 68400
Confidence: 78%
Killzone: London open active
```

**Instruction:** Write exactly 2 sentences.

- **Sentence 1 (Context):** The structural state of play — what the market is doing and why this level matters. Use high-signal terminology (confluence, liquidity sweep, order block, BOS). Explain this is structural, not random.
- **Sentence 2 (Execution):** The immediate trade step — confidence-gated:

| Confidence | Instruction |
|-----------|-------------|
| >75% | Direct entry with specific price. Act now. |
| 50–75% | Conditional — name the exact condition to wait for |
| <50% | Monitor — name what would confirm before acting |

### Deep Prompt — Full context inputs

Same as short context plus all bounds, levels, targets, probabilities, and supporting factors.

**Instruction:** Write exactly 3 sentences.

1. **Confluence story:** What's aligning and from how many sources — name the TFs, the structure type, the SMC confirmation.
2. **Key levels:** Entry rationale and stop placement logic (not just the numbers — why those levels). T1/T2/T3 with sizing implication.
3. **Confidence-weighted guidance:** What to do and what would invalidate the thesis. Always include the invalidation condition.

---

## Signal Bar

Deterministic. Assembled from signal data. Renders immediately.

**Format:**
```
[ACTION TAG]  SYMBOL · TF
Entry X  |  Stop Y  |  T1 Z  R:R N.N
```

**Action tags** (from direction + confidence):
- `[BULLISH RECLAIM]` / `[BEARISH BREAKDOWN]` — confidence >75%, actionable now
- `[WAIT — BULLISH]` / `[WAIT — BEARISH]` — confidence 50–75%, conditional
- `[MONITOR]` — confidence <50%, observational

Structural label (RECLAIM, FVG FILL, BOS, SWEEP, REVERSAL, PATTERN) derived from `setup_plugin`.

---

## Dashboard — Signal Card Layout

```
┌─────────────────────────────────────────────────────┐
│ [BULLISH RECLAIM]  GC · 5m                          │
│ Entry 5108.7  |  Stop 5100.47  |  T1 5143.84  4.27× │  ← instant
├─────────────────────────────────────────────────────┤
│ Gold testing a 3-TF confluent order block after a   │  ← short, ~500ms
│ liquidity sweep cleared stops below 5095. Enter at  │
│ 5108–5112 on any 1m reclaim — stop invalidates      │
│ below 5100.                                         │
├─────────────────────────────────────────────────────┤
│ ▼ Full analysis                                     │  ← collapsed by default
│ [deep narrative loads concurrently, ready on expand]│
└─────────────────────────────────────────────────────┘
```

**Render sequence:**
1. Signal bar — instant, from stream data
2. Short narrative — fade-in when ready (~500ms); signal bar alone is sufficient until then
3. Full analysis — collapsed by default; deep call fires concurrently so it's ready when PM expands; if still in-flight, show minimal skeleton

---

## What Does Not Change

- `llm_writer_service` — no changes; scores both call types normally
- `_apply_score_routing()` — no changes; gains two new call types to optimize
- `LLMChain` provider order — no changes; OpenRouter primary, no model hardcoding
- `llm_calls` hypertable — no schema changes; `call_type` column distinguishes tiers

---

## Out of Scope

- Model selection — handled by routing system, not this design
- Group synthesis — unchanged
- Counterfactual calls — unchanged
- Provider chain configuration — unchanged
