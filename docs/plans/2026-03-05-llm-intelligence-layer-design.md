# LLM Intelligence Layer — Design

**Date:** 2026-03-05
**Status:** Approved
**Framing:** What would Jim Simons and Renaissance Capital demand?

---

## Problem

Every LLM call in the AI narrative pipeline is invisible after 90 seconds. We know what model was used and whether the trade won, but we never capture it together. We cannot answer:

- Which model produces better narratives for winning trades?
- Does GLM-5 outperform qwen3.5:9b in trending regimes?
- What prompt context correlates with accurate narrative reasoning?
- What labeled data do we have for fine-tuning local models?

Renaissance principle: *you can always discard data you didn't need. You can never recover data you didn't capture.*

---

## Decision: Option C — Full LLM Intelligence Layer, Event-Driven

Every LLM call (per-signal, group synthesis, counterfactual) flows through the existing hot/warm/cold tiered architecture. No special paths. Model scores computed continuously, cached in Redis for live routing, persisted cold in TimescaleDB.

---

## Architecture

```
ai_narrative_service
  ├── per-signal call  ──→ xadd "llm_calls:stream"
  ├── group synthesis  ──→ xadd "llm_calls:stream"
  └── counterfactuals  ──→ xadd "llm_calls:stream"

signal_lifecycle_service
  └── on signal close  ──→ xadd "llm_outcomes:stream"

llm_writer_service  (new — mirrors feature_writer_service)
  ├── reads "llm_calls:stream"   → INSERT llm_calls (TimescaleDB)
  ├── reads "llm_outcomes:stream" → UPDATE llm_calls SET outcome fields WHERE signal_id
  └── recomputes llm_model_scores → UPDATE Redis "llm_scores:MODEL:REGIME"

ai_narrative_service (routing)
  └── reads Redis "llm_scores:MODEL:REGIME" at startup + every 5 min
      → re-orders provider chain if significant winner exists (p < 0.05, n >= 30)
```

---

## Data Schema

### `llm_calls` — TimescaleDB hypertable, partitioned by `called_at`

```sql
call_id          UUID PRIMARY KEY DEFAULT gen_random_uuid()
called_at        TIMESTAMPTZ NOT NULL          -- partition key
call_type        TEXT NOT NULL                 -- 'per_signal' | 'group_synthesis' | 'counterfactual'
signal_id        UUID REFERENCES signal_ledger(signal_id) -- nullable for group/counterfactual
group_name       TEXT                          -- for group synthesis
symbol           TEXT NOT NULL
timeframe        TEXT NOT NULL

-- LLM call details
model            TEXT NOT NULL                 -- 'zai:glm-5', 'ollama:qwen3.5:9b', etc.
provider         TEXT NOT NULL                 -- 'zai' | 'openrouter' | 'ollama'
prompt           TEXT NOT NULL                 -- full prompt sent
response         TEXT                          -- full response (NULL if call failed)
latency_ms       INTEGER
tokens_est       INTEGER                       -- estimated from response length
succeeded        BOOLEAN NOT NULL DEFAULT TRUE

-- Market context at time of call (captured, never changes)
regime           TEXT
session          TEXT
entry_price      DOUBLE PRECISION
stop_loss        DOUBLE PRECISION
target_price     DOUBLE PRECISION
confidence       DOUBLE PRECISION
cis_score        DOUBLE PRECISION
entry_zone_low   DOUBLE PRECISION
entry_zone_high  DOUBLE PRECISION
setup_type       TEXT                          -- setup_plugin name

-- Outcome (back-filled when signal closes)
outcome          TEXT                          -- 8-class outcome from signal_ledger
pnl_r            DOUBLE PRECISION
mae              DOUBLE PRECISION
mfe              DOUBLE PRECISION
bars_in_trade    INTEGER
win              BOOLEAN                       -- pnl_r > 0
outcome_at       TIMESTAMPTZ
```

### `llm_model_scores` — aggregate performance table

```sql
model            TEXT NOT NULL
regime           TEXT NOT NULL                 -- 'trending' | 'ranging' | 'volatile' | '__all__'
setup_type       TEXT NOT NULL                 -- setup_plugin name or '__all__'
call_type        TEXT NOT NULL
n_calls          INTEGER NOT NULL DEFAULT 0
n_outcomes       INTEGER NOT NULL DEFAULT 0    -- calls with known outcome
win_rate         DOUBLE PRECISION
avg_pnl_r        DOUBLE PRECISION
avg_latency_ms   INTEGER
p_value          DOUBLE PRECISION              -- vs baseline win rate
is_significant   BOOLEAN DEFAULT FALSE         -- p < 0.05 AND n_outcomes >= 30
score_updated_at TIMESTAMPTZ
PRIMARY KEY (model, regime, setup_type, call_type)
```

---

## Stream Keys

```
{env}:llm_calls:stream          -- all LLM calls, emitted by ai_narrative_service
{env}:llm_outcomes:stream       -- signal close events, emitted by signal_lifecycle_service
```

Redis score cache:
```
{env}:llm_scores:{call_type}:{regime}   -- HSET: {model} → JSON score blob
```

---

## Component Changes

### `ai_narrative_service`
- After every LLM call (success or failure): `xadd llm_calls:stream` with full payload
- Emit counterfactuals: signals below confidence threshold still generate a call log entry with `call_type='counterfactual'`, prompt built but not sent to LLM
- At startup + every 5 min: read `llm_scores` from Redis, re-sort provider chain if a significant winner exists

### `signal_lifecycle_service`
- On signal exit: `xadd llm_outcomes:stream` with `signal_id`, `outcome`, `pnl_r`, `mae`, `mfe`, `bars_in_trade`

### `llm_writer_service` (new)
- Consumes `llm_calls:stream` → batch INSERT to `llm_calls`
- Consumes `llm_outcomes:stream` → UPDATE `llm_calls SET outcome fields WHERE signal_id = $1`
- Every 15 min: recompute `llm_model_scores` from `llm_calls WHERE outcome IS NOT NULL`
- Update Redis score cache after recompute

---

## Adaptive Routing Logic

```python
# On score refresh — re-order provider chain for call_type X regime
scores = get_scores_from_redis(call_type, current_regime)
significant = [s for s in scores if s.is_significant]
if significant:
    best = max(significant, key=lambda s: s.avg_pnl_r)
    move best.model to position 0 in provider chain
```

Promotion requires: `p < 0.05` AND `n_outcomes >= 30`. Shadow mode is implicit — every model in the chain gets called as fallback, accumulating outcome data before it can be promoted.

---

## Fine-Tuning Export

```sql
-- Winning per-signal examples for supervised fine-tuning
SELECT prompt, response, outcome, pnl_r, regime, setup_type
FROM llm_calls
WHERE call_type = 'per_signal'
  AND win = TRUE
  AND pnl_r >= 1.5
  AND response IS NOT NULL
ORDER BY pnl_r DESC;

-- RLHF pairs: same signal, different models, different outcomes
SELECT a.prompt, a.response as chosen, b.response as rejected
FROM llm_calls a
JOIN llm_calls b ON a.signal_id = b.signal_id AND a.model != b.model
WHERE a.win = TRUE AND b.win = FALSE;
```

---

## Migration

`production/migrations/016_llm_intelligence_layer.sql`
- Create `llm_calls` hypertable
- Create `llm_model_scores` table
- Create indexes: `(signal_id)`, `(model, regime)`, `(called_at DESC)`

---

## What Renaissance Would Validate

Before promoting any model to position 1:
- Minimum 30 outcomes with known result
- p < 0.05 vs baseline win rate (binomial test)
- Performance must hold across at least 2 different regimes (not a regime artifact)
- Latency within acceptable range (no point promoting a model that times out 20% of calls)

---

## Out of Scope (this phase)

- Dashboard panels for model comparison (separate phase)
- Automated fine-tuning pipeline (separate phase — needs training infrastructure)
- Cross-model ensemble voting (backlog)
