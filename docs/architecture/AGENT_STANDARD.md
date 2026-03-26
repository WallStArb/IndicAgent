# Architectural Standard: The Renaissance "Agent" Pattern

## 1. Core Definition: The Renaissance Agent (OODA Loop)
A Renaissance Agent is an **autonomous, event-driven compute node** within our pipeline DAG. It operates on a continuous **OODA Loop** (Observe-Decide-Act):

- **Observe:** The Agent consumes Kafka events (raw data) and internal metrics (Prometheus/OTel) to understand its operational environment.
- **Decide:** The Agent executes logic (e.g., compute, filter, or signal fire) and evaluates internal health (e.g., "is lag too high? should I apply backpressure?").
- **Act:** The Agent publishes results to a downstream topic, flushes persistence batches to a Repository, or routes errors to a Dead Letter Queue (DLQ).

## 2. Key Agentic Characteristics
- **Autonomy:** Agents bake in self-management—they monitor their own health, lag, and resource saturation.
- **Scale-in/Out Capability:** Agents are designed for horizontal scalability, decoupled via Kafka streams, allowing the infrastructure to add/remove nodes based on load.
- **Health Instrumentation:** Every Agent is self-instrumented (OpenTelemetry), providing real-time telemetry on consumer lag, processing latency, and throughput.

## 3. Scaling On-Demand (The "Lag-Based" HPA)
In the legacy system, DB bottlenecks caused hard limits. In the Agentic system, we design agents as independent Kafka consumer groups:

- **Example - Feature Tier:**
    - **IndicatorComputeAgent (CPU-Bound):** Performs heavy math. We scale horizontally to 10+ instances reading from the same topic; Kafka partitions the stream (e.g., Symbol AAPL -> Agent 1, TSLA -> Agent 2).
    - **FeatureHistorianAgent (IO-Bound):** Performs batch I/O. We scale independently based on the throughput of the database.

- **Scaling Logic:**
    - Every Agent exports a Prometheus metric: `consumer_lag_records`.
    - **K8s HPA (Horizontal Pod Autoscaler)** monitors this metric.
    - If `consumer_lag_records > 50,000`: K8s automatically spawns a new instance.
    - If `consumer_lag_records < 1,000`: K8s terminates the extra instance.
- **Independence:** Because our agents are decoupled via Kafka, scaling a `SignalLedgerWriterAgent` has zero impact on the `SignalGeneratorAgent` compute node.
- **Observability:** Prometheus + Grafana monitor the "Golden Signals" (Traffic, Latency, Errors, Saturation) for every Agent independently.

## 4. Resilience & Operational Protocols
Renaissance Agents must handle failures without human intervention and ensure no data loss during K8s lifecycle events.

### Graceful Shutdown (The "Drain" Mandate)
- **Signal Handling:** Agents MUST listen for `SIGTERM` and `SIGINT`.
- **Drain Protocol:**
    1.  Immediately stop the Kafka consumer to prevent new records from being pulled.
    2.  Complete the current batch `commit` (do not drop in-flight data).
    3.  Close the repository connection *only after* the batch is finalized.
    4.  Signal the orchestrator that the agent is "Shutdown Complete."

### Dead-Letter Queue (DLQ) Integration
- Agents MUST NOT block on unprocessable payloads (e.g., malformed JSON).
- **Protocol:**
    - Wrap persistence/compute logic in try-except.
    - On failure, route the payload to `intelligence.[domain].journal.dlq`.
    - Log an `error` event for post-mortem analysis (e.g., "Persistence failure: data unprocessable").

### Scaling & Lag Monitoring
- **Consumer Lag Instrumentation:** Every Agent MUST export `consumer_lag_records` (the difference between `latest_offset` and `current_offset`).
- **HPA Policy:**
    - If `lag > threshold`: Spawn new Agent instance.
    - If `lag < threshold`: Terminate Agent instance after drain period.
- **Independence:** Persistence Agents (Historians) and Logic Agents (Computers) MUST scale on independent metrics. Never couple them.
- **Observability:** Prometheus + Grafana monitor the "Golden Signals" (Traffic, Latency, Errors, Saturation) for every Agent independently.

## 5. Comparison: Service vs. Agent

| Feature | Legacy "Service" | Renaissance "Agent" |
| :--- | :--- | :--- |
| **State** | Monolithic (Service + DB) | Decoupled (Agent + Kafka Buffer) |
| **Scaling** | Manual/Static | Automated via Lag-based HPA |
| **Resilience** | Stop-on-Error | Dead-Letter-Queue (DLQ) + Auto-Retry |
| **Visibility** | Log files | OTel Metrics + Provenance Chain |

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

## 7. The Unified Intelligence Bus Taxonomy (v2.0)

| Tier | Topic Name | Schema (Contract) | Agent Domain |
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
2.  **Zero-Knowledge DAG:** The `SignalGeneratorAgent` (I7) doesn't need to know how `I1` works. It only needs to subscribe to `intelligence.i6.confluence` to get the pre-aggregated confluence features it requires for scoring.
3.  **Compute Efficiency:** By forcing tiers into these topics, we allow downstream agents to perform topic-based subscription filtering. If an agent only cares about `SMC` confluence, it ignores `i1` through `i5` topics entirely, saving massive CPU cycles on deserialization.

---
**Status:** Global Standard v1.0
**Last Updated:** 2026-03-25
