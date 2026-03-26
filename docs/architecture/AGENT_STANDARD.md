# Architectural Standard: The Renaissance "Agent" Pattern

## 1. Core Definition: The Renaissance Agent (OODA Loop)
A Renaissance Agent is an **autonomous, event-driven compute node** within our pipeline DAG. It operates on a continuous **OODA Loop** (Observe-Decide-Act):

- **Observe:** The Agent consumes Kafka events (raw data) and internal metrics (Prometheus) to understand its operational environment.
- **Decide:** The Agent executes logic (e.g., compute, filter, or signal fire) and evaluates internal health (e.g., "is lag too high? should I apply backpressure?").
- **Act:** The Agent publishes results to a downstream topic, flushes persistence batches to a Repository, or routes errors to a Dead Letter Queue (DLQ).

## 2. Key Agentic Characteristics
- **Autonomy:** Agents bake in self-management—they monitor their own health, lag, and resource saturation.
- **Scale-in/Out Capability:** **[CURRENT STANDARD]** Agents run as systemd services on a single server; scaling is achieved by adjusting systemd instance counts manually based on Prometheus lag alerts. **[TARGET ARCHITECTURE]** Horizontal scaling via Kafka consumer group partitioning (multiple instances).
- **Health Instrumentation:** **[CURRENT STANDARD]** Every Agent is instrumented with Prometheus metrics via `src/observability/metrics.py` — consumer lag, processing latency, throughput. **[TARGET ARCHITECTURE]** OpenTelemetry (OTel) is not in the current stack and must not be added until `opentelemetry-sdk` is in `requirements.txt`.

## 3. Scaling On-Demand (Lag-Based) **[CURRENT STANDARD]**

Production runs on a **single server with systemd** — no Kubernetes. Scaling is managed manually via Prometheus lag alerting:

- **Current Scaling Logic:**
    - Persistence Agents MUST export `persistence_batch_latency` and `persistence_consumer_lag` via `src/observability/metrics.py`.
    - Compute Agents MUST export `plugin_execution_seconds` (histogram by `plugin_name`) and `events_consumed_total`.
    - **Grafana alerting** monitors `persistence_consumer_lag`. If lag exceeds threshold, the on-call engineer restarts or adds instances manually via systemd.

- **Example - Feature Tier (Current):**
    - **IndicatorComputeAgent (CPU-Bound):** Single systemd instance. If overwhelmed, increase batch size or reduce polling interval.
    - **FeatureWriterAgent (IO-Bound):** Single systemd instance. Scale by tuning batch size and flush interval before adding instances.

- **Independence:** Because agents are decoupled via Kafka, tuning a `FeatureWriterAgent` has zero impact on `IndicatorComputeAgent` compute.
- **Observability:** Prometheus + Grafana monitor the "Golden Signals" (Traffic, Latency, Errors, Saturation) for every Agent independently.

> **[TARGET ARCHITECTURE]** Future: Kafka consumer group partitioning (multiple instances per agent type, each assigned a partition subset). No K8s HPA — production is a single server. K8s references in any implementation plan are invalid.

## 4. Resilience & Operational Protocols
Renaissance Agents must handle failures without human intervention and ensure no data loss during systemd lifecycle events (start/stop/restart).

### Graceful Shutdown (The "Drain" Mandate)
- **Signal Handling:** Agents MUST listen for `SIGTERM` and `SIGINT`.
- **Drain Protocol:**
    1.  Immediately stop the Kafka consumer to prevent new records from being pulled.
    2.  Complete the current batch `commit` (do not drop in-flight data).
    3.  Close the repository connection *only after* the batch is finalized.
    4.  Signal the orchestrator that the agent is "Shutdown Complete."

### Dead-Letter Queue (DLQ) Integration **[TARGET ARCHITECTURE — not yet implemented]**
> **Current Standard:** DLQ topic infrastructure does not exist. Agents MUST catch unprocessable payloads, log a structured error via `structlog`, and discard. Do NOT attempt to publish to a DLQ topic that doesn't exist.
>
> **Target:** Once DLQ topics are provisioned:
- Agents MUST NOT block on unprocessable payloads (e.g., malformed JSON).
- **Protocol:**
    - Wrap persistence/compute logic in try-except.
    - On failure, route the payload to `{env}.intelligence.[domain].journal.dlq`.
    - Log an `error` event for post-mortem analysis (e.g., "Persistence failure: data unprocessable").

### Scaling & Lag Monitoring **[CURRENT STANDARD]**
- **Consumer Lag Instrumentation:** Persistence Agents MUST export `persistence_consumer_lag` and `persistence_batch_latency` via `src/observability/metrics.py`. Compute Agents MUST export `plugin_execution_seconds` and `events_consumed_total`. Use the canonical metric names — do not invent new names.
- **Grafana Alerting Policy:**
    - If `persistence_consumer_lag > threshold`: Page on-call engineer to investigate and manually restart or tune agent.
    - If lag clears: Resolve alert.
- **Independence:** Persistence Agents (WriterAgents) and Logic Agents (ComputeAgents) MUST be instrumented on independent metrics. Never couple them.
- **Observability:** Prometheus + Grafana monitor the "Golden Signals" (Traffic, Latency, Errors, Saturation) for every Agent independently.

## 5. Comparison: Service vs. Agent

| Feature | Legacy "Service" | Renaissance "Agent" |
| :--- | :--- | :--- |
| **State** | Monolithic (Service + DB) | Decoupled (Agent + Kafka Buffer) |
| **Scaling** | Manual/Static | Automated via Lag-based HPA |
| **Resilience** | Stop-on-Error | Structured error logging + DLQ (target) |
| **Visibility** | Log files | Prometheus metrics + structlog (current); ProvenanceChain (target, not yet implemented) |

## 6. Taxonomy & Domain Mapping

| Domain | Role | Agent Suffix | Example |
| :--- | :--- | :--- | :--- |
| **Compute** | Feature Transformation | `ComputeAgent` | `IndicatorComputeAgent` |
| **Decision** | Signal/Trade Fire | `GeneratorAgent` | `SignalGeneratorAgent` |
| **Persistence** | Data I/O/Batching | `WriterAgent` | `SignalLedgerWriterAgent` |
| **Lifecycle** | State Tracking (PnL/MAE) | `TrackerAgent` | `SignalTrackerAgent` |
| **Inference** | AI/ML Decision Engine | `PredictiveAlphaAgent` | `AlphaInferenceAgent` |
| **Training** | Model Learning | `TrainingAgent` | `FeatureTrainingAgent` |
| **Swarm** | Multi-Agent Reasoning | `SwarmAgent` | `SwarmIntelligenceAgent` |

> **Taxonomy Note:** `FeatureHistorianAgent` previously appeared in plans but uses the wrong suffix — persistence agents use `WriterAgent` suffix (e.g., `FeatureWriterAgent`). The `HistorianAgent` suffix is not in the taxonomy and must not be used. Similarly, `SwarmSMCContributor` violates the `SwarmAgent` suffix rule — correct name would be `SwarmSMCAgent`.

## 7. The Unified Intelligence Bus Taxonomy **[TARGET ARCHITECTURE — topics not yet in stream_keys.py]**

> **Important:** None of these tiered topics currently exist in `src/core/stream_keys.py`. The current pipeline publishes `IntelligenceEvent` to `intelligence:{SYMBOL}:{TF}` (a single unified topic per symbol/tf). The per-tier topic split below is the target architecture. Do not reference these topic names in implementation plans until they are added to `stream_keys.py`.
>
> **Topic naming rule (CLAUDE.md):** All topics must be prefixed with `{env}.` via `stream_keys.py`. The topic names below show the suffix only — actual topics are `{env}.intelligence.i1.indicators` etc.

| Tier | Topic Suffix | Schema (Contract) | Agent Domain |
| :--- | :--- | :--- | :--- |
| **I1** | `intelligence.i1.indicators` | `I1Indicators` | `IndicatorComputeAgent` |
| **I2** | `intelligence.i2.events` | `I2Events` | `EventComputeAgent` |
| **I3** | `intelligence.i3.structure` | `I3Structure` | `StructureComputeAgent` |
| **I4** | `intelligence.i4.context` | `I4Context` | `ContextComputeAgent` |
| **I5** | `intelligence.i5.patterns` | `I5Patterns` | `PatternComputeAgent` |
| **I6** | `intelligence.i6.confluence` | `I6Confluence` | `ConfluenceComputeAgent` |
| **I7** | `intelligence.i7.signals` | `RankedSignal` | `SignalGeneratorAgent` |
| **I8** | `intelligence.i8.alpha` | `AlphaMultiplier` | `PredictiveAlphaAgent` |

### Why this is the "Renaissance" Way:

1.  **Strict Modularity:** If a plugin in I3 produces an output that doesn't fit `I3Structure`, the schema validation fails at the producer node. It never pollutes the downstream pipeline.
2.  **Zero-Knowledge DAG:** The `SignalGeneratorAgent` (I7) doesn't need to know how `I1` works. It only needs to subscribe to `{env}.intelligence.i6.confluence` to get the pre-aggregated confluence features it requires for scoring.
3.  **Compute Efficiency:** By forcing tiers into these topics, we allow downstream agents to perform topic-based subscription filtering. If an agent only cares about `SMC` confluence, it ignores `i1` through `i5` topics entirely, saving massive CPU cycles on deserialization.

---
**Status:** Global Standard v1.1 — Current vs Target architecture labelled
**Last Updated:** 2026-03-26

> **Reading this document:** Sections labelled **[CURRENT STANDARD]** describe what agents must do today. Sections labelled **[TARGET ARCHITECTURE]** describe where we are heading — do not implement until the prerequisite infrastructure exists.
