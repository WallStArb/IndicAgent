# IndicAgent Layered Architecture

**Version:** 6.1.0
**Last Updated:** 2026-03-15
**Status:** I1-I8 production complete — 98 plugins + 2 aggregation components, 1754 passing tests

## Overview

IndicAgent implements a 4-layer intelligence platform that progresses from raw data collection through AI-powered narrative synthesis. All layers are production-operational as of v1.8 (2026-03-13).

The central architectural principle: **the real-time pipeline never touches the database directly.** All persistence is handled asynchronously by `feature_writer_service`, decoupling hot-path latency from cold storage.

---

## 4-Layer Architecture

### Layer 1: Data Foundation

**Purpose:** High-frequency IBKR data collection, multi-timeframe bar aggregation, stream distribution.

**Components:**
- `production/daemons/high_frequency_tws_daemon.py` — IBKR tick collection (100–500+ ticks/sec) with built-in multi-timeframe bar aggregation (1m → 5m → 15m → 1h → 4h → 1d)
- `src/core/database_manager.py` — PostgreSQL/TimescaleDB connection pooling
- Redpanda — hot-path stream distribution (Kafka-compatible; Phase 30, 2026-03-14)

**Note:** `timeframes_builder_service.py` exists but is legacy and unused. All aggregation runs inside the TWS daemon.

**Output streams:** `{env}:market:{symbol}:{tf}` (all timeframes), `{env}:ticks:{symbol}:live`

---

### Layer 2: Mathematical Intelligence (I1–I4)

**Purpose:** Incremental indicator computation and market context classification.

**Service:** `services/indicator_service.py` — reads `market:` streams, outputs `indicators:SYMBOL:TF`; metrics :9109

**I1 Raw Indicators (25 plugins):**
RSI, MA/EMA, MACompare, MACD, ATR, BollingerBands, Stochastic, CCI, WilliamsR, MFI, OBV, VWAP, Supertrend, ADX/DMI, Keltner, Donchian, ROC/PPO, Aroon, ChandelierExit, CMF, HistoricalVolatility, PSAR, StochRSI, ACOscillator, HMA

**I2 Composite / Second-Derivative Indicators (10 plugins):**
MACD Events, RSI Events, Stoch Events, ADX Events, Volume Events, MomentumAccel, DonchianPos, OBVMomentum, DerivOsc, ExhaustionScore

All plugins use `compute_next()` for incremental, stateful computation. No full-series recalculation.

**I3 Market Structure (8 plugins) and I4 Context (7 plugins)** are executed inside `market_analysis_service`:

| Tier | Plugins |
|------|---------|
| I3 | Swing, SR, TrendStructure, MarketProfile, SessionLevels, AnchoredVWAP, FibZones, SwingMomentum |
| I4 | VolRegime, TrendRegime, MomentumCtx, GARCHVol, KalmanTrend, SessionCtx, MTFVol |

---

### Layer 3: Pattern Intelligence (I5–I7)

**Purpose:** Pattern recognition, confluence analysis, setup detection, signal generation, and lifecycle tracking.

**Service:** `services/market_analysis_service.py` — executes I3 through I6; reads `indicators:` streams, outputs `intelligence:SYMBOL:TF` (typed `IntelligenceEvent` with tiered JSONB: bar/i1/i3/i4/i5/smc/i6); metrics :9114

**I5 Pattern Recognition (14 plugins):**
RSIDivergence, BollingerSqueeze, VolDivergence, Confluence, TrendConfluence, DoubleTB, HeadShoulders, TriangleWedge, Candlestick, FlagPennant, CupHandle, MeasuredMove, VolumeProfile, KeyLevelReaction

**SMC Smart Money Concepts (13 plugins):**
BOS/CHoCH, FVG, OrderBlocks, LiquiditySweeps, BOCPD, HMM, LiquidityPools, SupplyDemandZones, ICTKillzones, AMDCycle, BreakerBlocks, MitigationBlocks, PremiumDiscount

**I6 Cross-Timeframe (1 plugin):**
CrossTimeframeConfluence

**Signal generation and lifecycle:**

- `services/signal_generator_service.py` — I7: 17 setup plugins + 2 aggregation components (CISScorer, SignalAggregator) → `signals:SYMBOL:TF:aggregated` stream + `signal_ledger` table; metrics :9112. Requires ~50 live 1m bars (~50 min) warmup after restart before signals fire.
- `services/signal_lifecycle_service.py` — zone-aware lifecycle tracking: entry activation, MAE/MFE, 8-class outcome classification; metrics :9115

**8-class signal outcomes:** `never_activated`, `stopped_at_entry`, `stopped_in_trade`, `target_1`, `target_1_2`, `target_full`, `ttl_expired_ahead`, `ttl_expired_behind`

---

### Layer 4: AI Intelligence (I8)

**Purpose:** LLM-powered market narrative synthesis and model performance tracking.

**Components:**
- `services/ai_narrative_service.py` — Ollama qwen3.5:9b (per-signal analysis), phi4-mini:3.8b (group synthesis) → `narratives:SYMBOL:TF` stream; metrics :9113
- `services/llm_writer_service.py` — `llm_calls:stream` → `llm_calls` hypertable; outcome back-fill from `llm_outcomes:stream`; `llm_model_scores` refresh every 15 min; metrics :9117

---

## Cross-Cutting Services

- `services/feature_writer_service.py` — consumes `intelligence:SYMBOL:TF` streams in batch, writes to `intelligence_features` hypertable asynchronously; decouples hot path from TimescaleDB; metrics :9116
- `indicagent-api` — FastAPI + SSE on :8000; fans out all streams to dashboard clients

---

## Data Flow

```
IBKR TWS
  └─ high_frequency_tws_daemon
       └─ {env}:market:{symbol}:{tf}  (all timeframes)
            └─ indicator_service (I1+I2)
                 └─ {env}:indicators:{symbol}:{tf}
                      └─ market_analysis_service (I3→I6)
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

---

## Stream Keys

All stream keys are env-prefixed (e.g., `development:` in dev) and constructed via `src/core/stream_keys.py`.

| Stream | Producer | Purpose |
|--------|----------|---------|
| `{env}:market:{symbol}:{tf}` | TWS daemon | OHLCV bars |
| `{env}:ticks:{symbol}:live` | TWS daemon | Raw ticks |
| `{env}:indicators:{symbol}:{tf}` | indicator_service | I1+I2 outputs |
| `{env}:intelligence:{symbol}:{tf}` | market_analysis_service | Typed IntelligenceEvent (I3–I6 tiered JSONB) |
| `{env}:signals:{symbol}:{tf}:aggregated` | signal_generator_service | I7 winner signal |
| `{env}:narratives:{symbol}:{tf}` | ai_narrative_service | I8 LLM narrative |
| `{env}:llm_calls:stream` | ai_narrative_service | Full LLM audit (maxlen=500) |
| `{env}:llm_outcomes:stream` | signal_lifecycle_service | Lifecycle exits with outcome/pnl_r/MAE/MFE (maxlen=200) |

---

## TimescaleDB Tables

| Table | Description | Retention |
|-------|-------------|-----------|
| `market_data_ohlcv` | Raw OHLCV; backfill only; ground truth | Forever |
| `intelligence_features` | Full feature vectors per bar incl. I7/I8 JSONB; compressed after 7d | Forever |
| `signal_ledger` | I7 signals + 14 lifecycle columns (MAE, MFE, outcome, bars_in_trade, etc.) | Forever |
| `llm_calls` | Full LLM audit log per call; outcome back-filled by llm_writer_service | Forever |
| `llm_model_scores` | Per-model win rate / avg pnl_r / p-value; refreshed every 15 min | Rolling |
| `setup_performance` | Per-setup rolling 30d stats (win_rate, avg_pnl_r, sharpe); FEED-02 gate: only rows with sample_size >= 30 written | Rolling |

`signal_ledger` joins to `intelligence_features` on `(symbol, feature_ts, feature_tf)` for full bar OHLCV.

---

## Hot / Warm / Cold Tiers

| Tier | Path | Latency |
|------|------|---------|
| Hot | Redpanda Streams | sub-ms |
| Warm | Service pipeline (indicator → analysis → signal) | <10ms |
| Cold | feature_writer_service → TimescaleDB (batch, async) | seconds |

The real-time pipeline never touches the database directly.

---

## Plugin Registry

All tier membership is declared in `src/intelligence/register_plugins.py` (`TIER_I1` … `TIER_I7`). `registry.validate_tier()` hard-crashes at startup on any missing plugin name — this is intentional to prevent silent misconfiguration.

**Plugin counts:** 25 I1 + 11 I2 + 8 I3 + 9 I4 + 14 I5 + 13 SMC + 1 I6 + 17 I7 = 98 plugins + 2 aggregation components (CISScorer, SignalAggregator)

---

## Service Summary

| Service | Unit | Metrics | Purpose |
|---------|------|---------|---------|
| TWS Daemon | `indicagent-tws` | — | IBKR tick collection + bar aggregation |
| Indicator Service | `indicagent-indicator` | :9109 | I1+I2 (35 plugins) → `indicators:` |
| Market Analysis | `indicagent-market-analysis` | :9114 | I3→I6 (43 plugins) → `intelligence:` |
| Signal Generator | `indicagent-signal-generator` | :9112 | I7 (17 setup plugins + 2 agg) → `signals:` + `signal_ledger` |
| Signal Lifecycle | `indicagent-signal-lifecycle` | :9115 | Zone-aware lifecycle, MAE/MFE, 8-class outcome |
| AI Narrative | `indicagent-ai-narrative` | :9113 | I8 LLM → `narratives:` |
| Feature Writer | `indicagent-feature-writer` | :9116 | `intelligence:` → `intelligence_features` (batch) |
| LLM Writer | `indicagent-llm-writer` | :9117 | `llm_calls:stream` → `llm_calls` + outcome back-fill |
| API | `indicagent-api` | — | FastAPI + SSE :8000 |

---

**Related Documentation:**
- [Intelligence Tiers (I1-I8)](../concepts/intelligence-tiers.md)
- [Stream Schemas](../reference/schemas/stream-schemas.md)
- [DB Maintenance Runbook](../reference/db-maintenance.md)
