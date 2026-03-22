# Service Separation of Duties

**Last Updated:** 2026-03-22
**Status:** Production — I1-I8 complete

---

## Principle

Each service has **one reason to change**. Services communicate exclusively via Redpanda topics — no direct HTTP calls between services in the pipeline. A service can be restarted, redeployed, or scaled independently without affecting others.

---

## Services and Responsibilities

### `tws_daemon.py`

**Responsibility:** Connect to IBKR TWS, ingest live ticks, form 1-minute OHLCV bars, and build higher timeframe bars internally.

This service owns the IBKR connection. Restarting it disconnects from the broker.

**Publishes:** `market:SYMBOL:TF`, `ticks:SYMBOL:live`, `price:SYMBOL:latest`

---

### `feature_pipeline_service`

**Responsibility:** Unified I1–I6 analysis. Executes the mathematical and market intelligence pipeline (technical indicators, market structure, regime context, pattern recognition, SMC).

Publishes a fully enriched bar message: OHLCV + all I1–I6 fields.

Does **NOT** write to the database — intelligence features are persisted by `feature_writer_service`.

**Publishes:** `intelligence:SYMBOL:TF`
**Consumes:** `market:SYMBOL:TF`

---

### `feature_writer_service`

**Responsibility:** Async decoupled persistence of intelligence features from hot path to cold storage.

Consumes `intelligence:SYMBOL:TF` stream, batches writes to `intelligence_features` hypertable.

**Writes:** `intelligence_features` hypertable

---

### `signal_generator_service`

**Responsibility:** Detect trading setups and produce actionable signals (I7).

On each enriched bar: runs all 17 I7 setup plugins + 2 aggregation components (CISScorer, SignalAggregator).

**Publishes:** `signals:SYMBOL:TF:aggregated`
**Consumes:** `intelligence:SYMBOL:TF`
**Writes:** `signal_ledger` (new signal rows)

---

### `signal_lifecycle_service`

**Responsibility:** Zone-aware lifecycle tracking for all pending and active signals.

Evaluates all pending/active signals per bar with zone-aware activation logic and MAE/MFE tracking.

**Publishes:** `llm_outcomes:stream` (signal exits with outcome/pnl_r/mae/mfe)
**Consumes:** `market:SYMBOL:TF`
**Writes:** `signal_ledger` (lifecycle updates)

---

### `ai_narrative_service`

**Responsibility:** Synthesise AI narratives from aggregated signals using a local LLM.

Consumes `signals:SYMBOL:TF:aggregated`. Calls Ollama to generate market narratives.

**Publishes:** `narratives:SYMBOL:TF`, `llm_calls:stream`
**Consumes:** `signals:SYMBOL:TF:aggregated`

---

### `llm_writer_service`

**Responsibility:** Persist LLM call audit records and update model performance scores.

Consumes `llm_calls:stream` and `llm_outcomes:stream`. Writes to `llm_calls` hypertable and maintains `llm_model_scores`.

**Writes:** `llm_calls` hypertable, `llm_model_scores` table

---

## Stream Flow

```
IBKR TWS ──► tws_daemon ──► market:SYMBOL:TF ──► feature_pipeline_service
                                                      │
             ┌────────────────────────────────────────┘
             ▼
    intelligence:SYMBOL:TF
    (fully enriched bar)
             │
             ├───────────────────────┐
             ▼                       ▼
    signal_generator_service    feature_writer_service
             │                       │
             ▼                       ▼
    signals:SYMBOL:TF:aggregated  TimescaleDB (intelligence_features)
             │
             ├────────────┐
             ▼            ▼
    signal_lifecycle    ai_narrative
    (updates          (generates
     signal_ledger)    narratives)
```

---

## Stream Key Reference

| Stream | Producer | Consumer(s) |
|--------|----------|-----------|
| `market:SYMBOL:TF` | `tws_daemon` | `feature_pipeline_service`, `signal_lifecycle_service` |
| `intelligence:SYMBOL:TF` | `feature_pipeline_service` | `signal_generator_service`, `feature_writer_service` |
| `signals:SYMBOL:TF:aggregated` | `signal_generator_service` | `ai_narrative_service` |
| `narratives:SYMBOL:TF` | `ai_narrative_service` | `api_service` |
| `llm_calls:stream` | `ai_narrative_service` | `llm_writer_service` |
| `llm_outcomes:stream` | `signal_lifecycle_service` | `llm_writer_service` |
