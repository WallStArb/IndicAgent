# High-Level Architecture Concepts

**Status:** current
**Last Updated:** 2026-04-22

> Conceptual overview of the *mechanisms* behind the IndicAgent architecture. **North Star rules** are in `principles.md`. **Layer-by-layer service map** is in `layered-architecture.md`. This doc explains the *how* — the design patterns and their consequences.

---

## Plugin DAG (Topological Execution)

The intelligence pipeline runs 128 plugins across I1–I7 tiers. Execution order is not hardcoded — each plugin declares `inputs` and `outputs`, and Kahn's topological sort derives the order at startup. Circular dependencies cause a hard crash before any bar is processed.

**What this enables:**
- Adding a plugin that depends on an existing output requires only declaring the dependency — no pipeline changes.
- Plugins with no shared dependencies run concurrently. I1 and I7 tiers are currently parallelized via `asyncio.gather` + `ThreadPoolExecutor`.
- I2–I6 remain sequential (GIL prevents true CPU parallelism for Python). See `pipeline-optimization.md`.

---

## Service-Level Agent DAG

The plugin DAG operates within a single service. The system as a whole is also a DAG — a directed graph of services connected exclusively via Kafka topics:

```
Provider Layer  →  Bar Processing Tier  →  Intelligence Compute  →  Persistence Tier
                         ↓                                               ↑
                   Audit / Side-Channel Layer  ─────────────────────────┘
```

No service skips a tier or calls a sibling service directly. Each tier produces to Kafka topics consumed exclusively by the next tier. Full topology with Mermaid diagram: `dag-topology.md`.

**Topology invariants:**
- `ProviderMergerAgent` is the sole writer to `market.bars` — all downstream services are isolated from provider topology changes
- `IntelligencePipelineComputeAgent` consumes from both `market.bars` (1m) and `market.bars.htf` — the same compute pipeline handles all timeframes
- Persistence tier services consume from intelligence topics only — they never touch upstream bar topics

---

## Incremental-First Computation

Every plugin implements `compute_next()` for O(1) updates per bar. Processing 128 plugins per bar means updating only what changed since the previous bar — not recomputing from scratch on a rolling window.

This is the throughput model: cost scales with the number of active instruments and timeframes, not with indicator window sizes (e.g., a 200-period EMA and a 14-period EMA cost the same per bar).

**Warmup exception:** GARCH, Kalman, and HMM-based plugins require ~50 bars to converge. During warmup, bars are processed but output is suppressed (`warming_up=True`). Once warm, the state is stable and O(1) updates resume.

---

## Hot/Warm/Cold Persistence Tiers

Persistence is handled asynchronously — entirely outside the hot path:

| Tier | Mechanism | Latency |
|------|-----------|---------|
| Hot | In-process I1–I7 compute | <10ms/bar |
| Warm | Redpanda streams (Kafka-compatible) | sub-millisecond |
| Cold | Async batch WriterAgents → TimescaleDB | seconds |

The real-time pipeline is DB-ignorant. A TimescaleDB outage has zero impact on signal generation latency.

---

## WriterAgent Pattern (Convergence Gate)

All persistence is delegated to dedicated WriterAgents — the only DB-aware components in the system. The pattern:

```
ComputeAgent → Kafka topic → WriterAgent → TimescaleDB
```

WriterAgents use a **Convergence Gate** (`StreamMerger`) to merge events from multiple upstream sources before writing. This guarantees atomic batch INSERTs: all fields from all contributing compute agents land in the same DB row in a single commit. A Kafka offset commit only advances after the DB write succeeds, so a crash mid-write replays from the last committed offset rather than silently dropping data.

**Active WriterAgents:** `FeatureWriterAgent`, `SignalWriterAgent`, `LifecycleWriterAgent`, `BarWriterAgent`, `SwarmWriterAgent`

---

## Dead Letter Queue (DLQ)

Every WriterAgent and AuditorAgent maintains a DLQ topic (`<domain>.dlq`). Messages that fail schema validation, have null CIS, or cannot be deserialized are routed there rather than crashing the consumer. The consumer logs the rejection and continues; the live data stream is unaffected.

**Operational rule:** A non-empty DLQ is a bug to investigate, not a normal operating state. The `ParityAuditorAgent` counts DLQ entries as part of pipeline health scoring. Null-CIS signals caught at the DLQ are the most common category — they indicate a plugin produced an incomplete `IntelligenceEvent`.

---

## Agent Role Taxonomy — SoC by Convention

Each agent has exactly one role, encoded in its class name suffix. The suffix determines DB access rights — enforced by convention, not a runtime permission system.

| Role Suffix | Responsibility | DB Access |
|-------------|---------------|-----------|
| `ProviderAgent` | External source → Kafka raw topic. No compute. | None |
| `MergerAgent` | Multi-source routing + auto-failover. DB-ignorant. | None |
| `ComputeAgent` | Math/stats transform. DB-ignorant. | None |
| `WriterAgent` | DB persistence only. Reads Kafka, writes DB. | Write |
| `TrackerAgent` | Business object lifecycle. Reads and writes signal state. | Read/Write |
| `AuditorAgent` | Data integrity validation + self-healing. | Read |

**Why naming encodes SoC:** Anyone reading `IntelligencePipelineComputeAgent` immediately knows it has no DB access. Anyone reading `FeatureWriterAgent` knows it does. No documentation lookup needed. When someone tries to add a DB query to a `ComputeAgent`, the name itself signals the violation.

**The SoC consequence that matters:** `IntelligencePipelineComputeAgent` processes 128 plugins per bar without any coupling to TimescaleDB availability. A database failure, migration, or backpressure has zero effect on the hot path.

---

## BaseAgent — Observability as Infrastructure

Every agent inherits a standard lifecycle contract from `BaseAgent` (`src/core/agent/base.py`). Observability is not configured per-service — it's baked into the base class and active from day one.

**What every agent gets automatically:**
- **Structured logging** — `structlog.BoundLogger` bound with `agent=name`; standard event types (`agent.starting`, `agent.stopped`, `agent.run_failed`) emitted at lifecycle boundaries
- **OTel tracing** — `self.tracer = get_tracer(name)` available immediately; behaves as a no-op when tracing is not initialized, so it's safe to use before setup completes
- **Prometheus metrics** — metrics server starts on the agent's declared port at `start()`; inherited counters for crash, setup success/failure, setup latency, and last-message timestamp (stall detection)
- **Graceful shutdown** — SIGTERM/SIGINT both set a shared `_stop_event`; `_run()` loops check `self.running`; `_teardown()` drains queues and closes connections before exit
- **DLQ routing** — `_send_to_dlq()` is called on unprocessable payloads; the default logs and discards, concrete agents override to produce to a named DLQ topic

**Design philosophy:** observability that requires per-service configuration gets skipped under deadline pressure. By building it into `BaseAgent`, every new service is traceable, metricked, and gracefully-shutdownable with zero additional code. Full reference: `base-agent-patterns.md`.

---

## Plugin Extension Model

The platform is an empty shell; intelligence is composed entirely of plugins.

- **Single extension point:** Write a `PatternPlugin` subclass, register it in `TIER_I*` in `src/intelligence/register_plugins.py`. Nothing else changes — the DAG rebuilds, the topic schema absorbs the new output fields.
- **Data contract:** `IntelligenceEvent` (tiered JSONB: i1, i2, i3, i4, i5, smc, i6) is the sole contract between compute and consumers. Plugins expose outputs via named fields in their tier's JSONB — consumers are decoupled from plugin internals.
- **Shadow gate:** New I7 plugins deploy with `IS_SHADOW=True`. They compute and write to `signal_ledger` but are excluded from position sizing until regime-conditional win rate reaches statistical significance (p < 0.05, sufficient N).

---

## Provider-Neutral Architecture

The platform abstracts data sources through the `BaseProviderAgent` contract. Any market data source can be wired in by subclassing `BaseProviderAgent` and implementing the provider-specific connection and bar emission logic — nothing downstream changes.

**Current implementation:**
- `IBKRProviderAgent` — connects to IBKR TWS, collects 5s real-time bars, publishes to `market.bars.raw.ibkr`
- `ProviderMergerAgent` — consumes `market.bars.raw.*` from all active providers, applies auto-failover on primary silence (configurable silence threshold), publishes canonical `market.bars`; emits a quality side-channel `ProviderQualityEvent` to `market.data.quality`

**Properties:**
- **Auto-failover** — `ProviderMergerAgent` detects primary silence and promotes a secondary without operator intervention.
- **Quality side-channel** — downstream agents can react to data quality signals without coupling to provider logic.
- **Zero downstream coupling** — consumers subscribe to `market.bars` (canonical), never to provider-specific topics.

---

## Microservices — Decoupled by Topic

No agent calls another directly. Redpanda is the sole durable communication fabric.

- Restarting `indicagent-intelligence-pipeline` has zero operational impact on `indicagent-feature-writer`.
- Each agent resumes from its committed Kafka offset — no in-flight data is lost.
- Services can be deployed, restarted, or scaled independently.

**Scaling:** Production runs on a single server with systemd. Horizontal scaling is achieved by adding systemd instances within a Kafka consumer group — multiple instances consume from the same topic and partition-balance automatically. Prometheus consumer lag alerts trigger manual scale decisions. No Kubernetes.

---

## API-First

The full intelligence stack is accessible via standard HTTP without any SDK dependency.

- **REST** — instrument metadata, signal history, model performance
- **SSE** — live intelligence streams pushed to any HTTP client (dashboard, trading bots, notebooks)
- **Multi-consumer** — any number of SSE subscribers can connect without affecting pipeline latency (fan-out at the API layer, not in the pipeline)
- **Schema-first** — `IntelligenceEvent` and `BarIntelligenceRecord` define the contract; the API exposes them verbatim

---

## Dual-Path Intelligence Architecture

The system separates two fundamentally different types of intelligence:

```
Path A (deterministic):  I1 → I2 → I3 → I4 → I5/SMC → I6 → I7
                         128 plugins, O(1) per bar, topological DAG
                         Fires signals in real-time (<10ms/bar)

Path B (probabilistic):  SwarmOrchestratorAgent → specialist agents
                         AlphaMultiplier vectors, asynchronous, shadow-validated
                         Overlays on Path A signals after statistical validation
```

Path A produces signals immediately and unconditionally. Path B runs out-of-band and never blocks signal execution. Path B multipliers adjust position sizing only after clearing the shadow gate (ρ > 0.4 correlation to realized PnL, p < 0.05, 14-day minimum).

### Intelligence Swarm (Path B)

Nine specialist agents quantify distinct dimensions of market friction:

| Group | Agents |
|-------|--------|
| Regime & Entropy | Regime Sentinel (latent manifold RTP), Volatility Arbiter |
| SMC & Structural Liquidity | Liquidity Decay Arbiter, SMC Validator, Liquidity Sweep Hunter |
| Cross-Asset & Macro | Correlation Contagion Agent, Macro Event Observer |
| Model & System Integrity | Execution Quality Observer, SkepticAgent (counterfactual) |

Each agent outputs an `AlphaMultiplier` vector. The `SafeSwarmWrapper` range-clamps the final composite multiplier to `[0.0, 2.0]` and defaults to `1.0` on any schema violation. Full design: `docs/ideas/intelligence-swarm-manifest.md`.

**Mixture of Agents (MoA) composition:** Each specialist agent operates on an independent information dimension — regime entropy, LOB friction, cross-asset correlation, counterfactual failure probability, etc. Independence is a design requirement: agents that share inputs would produce correlated outputs and false confidence in the composite. The `SwarmOrchestratorAgent` combines their outputs weighted by each agent's shadow-validated ρ score. A schema violation or timeout from any individual agent defaults that agent's contribution to `1.0` (neutral) — a malfunctioning agent degrades gracefully rather than corrupting the composite or blocking execution.

**Current state (v2.3):** `SwarmOrchestratorAgent` + `SwarmWriterAgent` plumbing is live. Specialist agents (SkepticAgent first) are planned for Phase 66+.

### ML Pipeline (Path A quality layer)

Three timer-based agents manage the ML training loop independently of the real-time path:

- `MLDataQualityAgent` — audits `intelligence_features` for training data quality before any model trains
- `MLDiscoveryAgent` — discovers signal patterns via LLM-assisted IC analysis (weekly cadence)
- `MLOrchestratorAgent` — orchestrates training decisions (retrain Y/N, promote Y/N) via deterministic rules, not LLM

**Key constraint:** Only `MLDiscoveryAgent` and `AINarrativeAgent` use LLMs. Orchestration, training, and monitoring are deterministic — production decisions cannot be non-deterministic.

Full design (LangGraph supervisor, 5 domain agents, HITL pattern): `docs/ideas/ml-agent-architecture.md`.

---

## Statistical Gate (Shadow-First)

Every alpha source — plugin, swarm agent, or ML model — follows the same promotion lifecycle before affecting position sizing:

1. **Shadow mode** — outputs are computed and persisted but do not affect signal execution
2. **Correlation analysis** — automated jobs compute ρ(prediction, realized_PnL_R) over a minimum window
3. **Statistical gate** — promotion requires p < 0.05 and sufficient N (14+ days for swarm, regime-conditional N for I7 plugins)
4. **Decay monitoring** — promoted sources are continuously monitored; correlation drop below threshold triggers automatic reversion to shadow

This applies uniformly: new I7 plugins (`IS_SHADOW=True`), swarm agents (`alpha_multiplier_shadow` table), and ML models (shadow scoring in `ml_signal_scores`).

**CIS ensemble gate:** Within Path A, the Confluence Intelligence Score requires agreement from at least 3 of 6 independent evidence buckets before an I7 signal fires. A single dominant indicator cannot override the ensemble. Every fired signal is a labeled training sample — kept forever in `signal_ledger` for regime-conditional win rate analysis.
