# IndicAgent Layered Architecture

**Version:** 2.0
**Last Updated:** 2026-03-22
**Status:** I1-I8 production complete — 98 plugins + 2 aggregation components, 1754 passing tests

## Overview

IndicAgent implements a 4-layer intelligence platform that progresses from raw data collection through AI-powered narrative synthesis. All layers are production-operational as of v2.0 (2026-03-22).

The central architectural principle: **the real-time pipeline never touches the database directly.** All persistence is handled asynchronously by `feature_writer_service`, decoupling hot-path latency from cold storage.

---

## 4-Layer Architecture

### Layer 1: Data Foundation

**Purpose:** High-frequency IBKR data collection, multi-timeframe bar aggregation, stream distribution.

**Components:**
- `services/tws_daemon.py` — IBKR tick collection (100–500+ ticks/sec) with built-in multi-timeframe bar aggregation (1m → 5m → 15m → 1h → 4h → 1d)
- `src/core/database_manager.py` — PostgreSQL/TimescaleDB connection pooling
- Redpanda — hot-path stream distribution (Kafka-compatible)

**Output streams:** `{env}:market:{symbol}:{tf}` (all timeframes), `{env}:ticks:{symbol}:live`

---

### Layer 2: Mathematical & Market Intelligence (I1–I6)

**Purpose:** Incremental indicator computation, market context classification, and pattern recognition.

**Service:** `services/feature_pipeline_service.py` — The unified pipeline orchestrator. Reads `market:` streams, executes tiers I1 through I6 sequentially (to minimize latency), and outputs `intelligence:SYMBOL:TF` (typed `IntelligenceEvent` with tiered JSONB: bar/i1/i3/i4/i5/smc/i6).

**I1-I2 (Indicators):** 36 total plugins including RSI, MA, MACD, etc.
**I3-I6 (Market Structure, Context, Pattern Recognition, SMC):** 43 total plugins.

All plugins use `compute_next()` for incremental, stateful computation.

---

### Layer 3: Signal Intelligence (I7)

**Purpose:** Pattern confluence, setup detection, signal generation, and lifecycle tracking.

**Components:**
- `services/signal_generator_service.py` — I7: 17 setup plugins + 2 aggregation components (CISScorer, SignalAggregator) → `signals:SYMBOL:TF:aggregated` stream + `signal_ledger` table. Requires ~50 live 1m bars (~50 min) warmup after restart before signals fire.
- `services/signal_lifecycle_service.py` — zone-aware lifecycle tracking: entry activation, MAE/MFE, 8-class outcome classification.

**8-class signal outcomes:** `never_activated`, `stopped_at_entry`, `stopped_in_trade`, `target_1`, `target_1_2`, `target_full`, `ttl_expired_ahead`, `ttl_expired_behind`

---

### Layer 4: AI Intelligence (I8)

**Purpose:** LLM-powered market narrative synthesis and model performance tracking.

**Components:**
- `services/ai_narrative_service.py` — Ollama qwen3.5:9b (per-signal analysis), phi4-mini:3.8b (group synthesis) → `narratives:SYMBOL:TF` stream.
- `services/llm_writer_service.py` — `llm_calls:stream` → `llm_calls` hypertable; outcome back-fill from `llm_outcomes:stream`; `llm_model_scores` refresh every 15 min.

---

## Cross-Cutting Services

- `services/feature_pipeline_service.py` — unified I1–I6 processing.
- `services/feature_writer_service.py` — consumes `intelligence:SYMBOL:TF` streams in batch, writes to `intelligence_features` hypertable asynchronously; decouples hot path from TimescaleDB.
- `indicagent-api` — FastAPI + SSE on :8000; fans out all streams to dashboard clients.

---

## Data Flow

```
IBKR TWS
  └─ tws_daemon
       └─ {env}:market:{symbol}:{tf}  (all timeframes)
            └─ feature_pipeline_service (I1→I6)
                 └─ {env}:intelligence:{symbol}:{tf}  (IntelligenceEvent JSONB)
                      ├─ signal_generator_service (I7)
                      │    ├─ {env}:signals:{symbol}:{tf}:aggregated
                      │    └─ signal_ledger (TimescaleDB)
                      │         └─ signal_lifecycle_service
                      │              └─ {env}:llm_outcomes:stream
                      ├─ ai_narrative_service (I8)
                      │    ├─ {env}:narratives:{symbol}:{tf}
                      │    └─ {env}:llm_calls:stream
                      │         └─ llm_writer_service → llm_calls (TimescaleDB)
                      └─ feature_writer_service
                           └─ intelligence_features (TimescaleDB)
```
