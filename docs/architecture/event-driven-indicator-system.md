# Plugin-Native Intelligence Processing Architecture

**Version:** 2.0
**Last Updated:** 2026-03-22
**Status:** I1-I8 pipeline complete — 98 plugins + 2 aggregation components

## Executive Summary

IndicAgent's plugin-native intelligence processing system transforms live market data into sophisticated intelligence through event-driven, stream-based processing. The system implements a complete I1-I8 intelligence framework using plugin-based DAG execution, real-time Redpanda stream processing, and a typed intelligence bus.

**Core Capability:** Real-time intelligence generation across 98 plugins spanning 8 tiers — from mathematical indicators through smart money concepts, confluence scoring, trading setups, and LLM-powered market narratives.

---

## **Plugin-Native Intelligence Architecture**

### **Event-Driven Intelligence Processing**

The pipeline is fully service-native: each tier runs in a dedicated systemd service consuming upstream Redpanda topics and publishing to downstream topics. Orchestration is handled by the stream topology.

#### **Core Intelligence Files**
- `src/intelligence/register_plugins.py` — `TIER_I1`…`TIER_I7` lists, single source of truth for plugin registration
- `src/intelligence/schemas.py` — `IntelligenceEvent` Pydantic model
- `src/intelligence/plugins.py` — `IndicatorPlugin` and `PatternPlugin` protocols
- `src/intelligence/dag.py` — DAG execution engine

#### **Service Orchestration**
- `services/feature_compute_agent.py` — Unified I1+I2+I3+I4+I5+SMC+I6 pipeline
- `services/signal_generator_service.py` — I7 setup detection + aggregation
- `services/signal_tracker_agent.py` — signal zone tracking, MAE/MFE, 8-class outcome
- `services/ai_narrative_service.py` — I8 LLM narrative generation
- `services/feature_writer_service.py` — Redpanda → TimescaleDB batch writer
- `services/llm_writer_service.py` — LLM call audit + outcome back-fill + score cache
- `src/api/main.py` — FastAPI + SSE on :8000
- `services/data_provider_agent.py` — IBKR tick + bar collection with built-in multi-TF aggregation

---

## **Real-Time Intelligence Pipeline**

```
IBKR TWS → feature_compute_agent (I1→I6) →
  signal_generator_service (I7) → signal_ledger + intelligence_features →
  feature_writer_service → TimescaleDB → SSE → Dashboard

signal_tracker_agent reads market:{symbol}:TF independently
ai_narrative_service reads signals:{symbol}:{tf}:aggregated
llm_writer_service reads llm_calls:stream
```

### **Processing Stages**

1. **Market Data** — `data_provider_agent.py` collects IBKR ticks + bars, publishes to `market:{symbol}:{tf}`
2. **I1-I6 Features** — `feature_compute_agent` reads market bars, runs tiers I1 through I6 sequentially, publishes typed `IntelligenceEvent` to `intelligence:{symbol}:{tf}`
3. **I7 Setups** — `signal_generator_service` reads intelligence stream, runs 17 setup plugins + CISScorer, writes to `signals:{symbol}:{tf}:aggregated` and `signal_ledger`
4. **I8 Narrative** — `ai_narrative_service` reads aggregated signals, calls Ollama LLM, publishes to `narratives:{symbol}:{tf}`
5. **Persistence** — `feature_writer_service` batch-writes `intelligence:{symbol}:{tf}` events to `intelligence_features` hypertable
6. **LLM Audit** — `llm_writer_service` persists every LLM call to `llm_calls` hypertable and back-fills outcomes

---

## **I1-I8 Intelligence Tiers**

### **I1-I6 — Mathematical, Market Structure & Pattern Intelligence**

Unified in `feature_compute_agent`. 98 plugins total.

**I1-I6 Content:** Technical indicators (RSI, MA, etc.), market structure (Swing, SR), regime context (VolRegime, GARCHVol), and Smart Money Concepts (BOS/CHoCH, FVG).

**Output stream:** `intelligence:{symbol}:{tf}` (typed `IntelligenceEvent`)

### **I7 — Trading Setups + Aggregation (17 setup plugins + 2 aggregation components)**

Setup plugins: TrendFollowing, MeanReversion, LiquiditySweepReclaim, MTFAlignment, SqueezeExpansion, VWAPDeviation, MomentumBreakout, LiquidityHunt, SupplyDemandSetup, CHoCHReversal, FVGFill, PatternCompletion, DivergenceStack, RegimeTransition, GapAnalysis, CandlestickPatternSetup, SessionExtremes

Aggregation components:
- **CISScorer** — Confluence Intelligence Score
- **SignalAggregator** — selects the highest-ranked eligible signal

**Output stream:** `signals:{symbol}:{tf}:aggregated`

---

## **Services Reference**

| Service | Unit | Source | Metrics |
|---------|------|--------|---------|
| Data Provider | `indicagent-data-provider` | `services/data_provider_agent.py` | — |
| Feature Compute | `indicagent-feature-compute` | `services/feature_compute_agent.py` | :9125 |
| Signal Generator | `indicagent-signal-generator` | `services/signal_generator_service.py` | :9112 |
| Signal Tracker | `indicagent-signal-tracker` | `services/signal_tracker_agent.py` | :9115 |
| AI Narrative | `indicagent-ai-narrative` | `services/ai_narrative_service.py` | :9113 |
| Feature Writer | `indicagent-feature-writer` | `services/feature_writer_service.py` | :9116 |
| LLM Writer | `indicagent-llm-writer` | `services/llm_writer_service.py` | :9117 |
| API | `indicagent-api` | `src/api/main:app` | :8000 |

All services are systemd-managed. Logs: `journalctl -u indicagent-<name> -f`.
