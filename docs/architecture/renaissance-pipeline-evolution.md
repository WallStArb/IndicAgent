# Renaissance Pipeline Evolution Strategy

## Context
This document tracks the evolution of the `indicagent` data layer from a monolithic service architecture toward the current agentic DAG. It captures both what shipped and where the design is headed next.

---

## Baseline (v2.0, shipped 2026-03-22): Data Layer Foundation

Phases 39–47 established the foundation:

- **Clock-Driven Data Flow:** Guaranteed 1-minute bar emission via internal heartbeat, ensuring temporal alignment for stateful models.
- **Multi-Stream Reconciliation:** Dual-stream comparison (5s real-time vs 1m audited) provides drift detection.
- **Zero-Loss Guarantee:** Kafka consumers migrated to `auto_offset_reset="earliest"` with explicit `commit()` operations, ensuring mathematical continuity after service crashes.
- **I1-I6 Unified Pipeline:** `feature_compute_agent` runs the full indicator-through-confluence stack in a single service, subscribing to both `market.bars` (1m) and `market.bars.htf` (aggregated timeframes).

---

## v2.1 Shipped: Agentic DAG Refactor (Phases 52–54)

### Phase 52-53: BaseAgent Unification

All pipeline services now extend `BaseAgent` (`src/core/agent/base.py`), providing a unified lifecycle: graceful SIGTERM drain, Golden Signals instrumentation (Traffic, Latency, Errors, Saturation via Prometheus), and a consistent startup/shutdown contract.

New dedicated agents were introduced with clear role separation:

| Agent | Role | DB Access |
|-------|------|-----------|
| `BarAggregatorComputeAgent` | 1m → HTF bar aggregation via `BarAccumulator` | None (compute only) |
| `BarWriterAgent` | Persists `market.bars` + `market.bars.htf` → `market_data_ohlcv` | Write |
| `BarAuditorAgent` | Gap detection, emits `market.events.gap_requests` | None (compute only) |
| `RollComputeAgent` | Futures roll premium computation | None (compute only) |
| `SignalTrackerAgent` | Zone-aware signal lifecycle: activation, MAE/MFE, 8-class outcome | Write |

The principle is explicit: **DB-ignorant compute agents** publish to Kafka topics; **DB-aware writer agents** consume from those topics and own all persistence. No compute agent touches the database.

### Phase 54: Provider Abstraction Layer

The previous `TwsDaemon` / `tws_daemon` was replaced by a proper provider abstraction:

- **`BaseProviderAgent`** — abstract base defining the instrument qualification protocol and gap-fill loop. Provider-agnostic by design.
- **`IBKRAdapter`** — thin adapter pattern wrapping `IBKRProvider`, translating IBKR-specific events to the canonical bar schema.
- **`IBKRProviderAgent`** — extends `BaseProviderAgent`, wires `IBKRAdapter` into the agent lifecycle.
- **`ProviderMergerAgent`** — canonical bar authority. Consumes from provider-specific raw topics (`market.bars.raw.<provider>`), performs multi-provider auto-failover on primary silence, and publishes to the single canonical `market.bars` topic. Emits `ProviderQualityEvent` on the quality side-channel.

The raw/canonical topic split (`market.bars.raw.ibkr` → `ProviderMergerAgent` → `market.bars`) means downstream consumers are fully provider-agnostic. Switching or adding a data source only requires a new `BaseProviderAgent` subclass — nothing downstream changes.

---

## Next: Intelligence Pipeline Unification (Phase 57, Planned)

The current pipeline still uses Kafka for inter-service communication between `feature_compute_agent` (I1-I6) and `signal_generator_agent` (I7). The Phase 57 design (`IntelligencePipelineComputeAgent`) will merge these into a single agent with an internal `asyncio.Queue` as the I6→I7 bus — eliminating one Kafka hop and simplifying state management.

Key elements of the Phase 57 design:
- Single `services/intelligence_pipeline_agent.py`, unit `indicagent-intelligence-pipeline`, port `:9125`
- Async Kafka output via `asyncio.Queue(maxsize=500)` — compute hot path zero I/O blocking
- State checkpointing to a compacted Kafka topic (`development.intelligence.pipeline.state`) — eliminates warmup on restart
- `BarHistorySeeder` retained as cold-start fallback only (checkpoint miss or agent version bump)
- Shadow rollout via `intelligence.shadow` topic before cutover

**This has not shipped yet.** Kafka is still the inter-service bus for I1-I7. Any reference to an "in-process intelligence engine" or "eliminating Kafka" describes this future work, not current reality.

### Further Future Direction: Renaissance Validation Framework

Once the intelligence pipeline is unified, the next evolution is the **Renaissance Alpha Pipeline** — a validation framework ensuring all alpha contributors earn the right through statistical proof:

- Shadow-first validation (14-day correlation gate)
- Automated promotion/demotion based on Pearson r
- `IAlphaContributor` interface for all signal sources
- LLMs in research-only, offline mode (no real-time calls in hot path)

This transforms the system from "feature factory" to "validated alpha engine." Design in `docs/ideas/renaissance-alpha-pipeline.md`.

---

*Analysis Date: 2026-03-22*
*Updated: 2026-03-29 — reflect v2.1 shipped state (phases 52–54); mark Phase 57 intelligence unification as planned, not shipped*
