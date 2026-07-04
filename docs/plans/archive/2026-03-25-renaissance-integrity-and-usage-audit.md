# Renaissance Intelligence Audit & Integrity Design

**Last Updated:** 2026-05-02

## Vision
To build an intelligence platform that operates with the mathematical rigor of a systematic hedge fund, treating every computation as an experimental data point. We focus on three pillars: **Mathematical Integrity**, **Predictive Attribution**, and **Compute Efficiency**.

## Pillar 1: Mathematical Integrity (The "Shadow Audit")
We treat our core pipeline (Tiers 1-3) as a mission-critical math library.
- **Shadow Validation:** Critical signal plugins (e.g., SMA-20, VWAP) will run a `ShadowAuditor` sidecar. This service performs identical calculations in a high-precision, zero-dependency environment.
- **Integrity Breach Monitoring:** If a live plugin's output deviates from the shadow output by > `1e-9`, the service emits an `INTEGRITY_BREACH` event to Kafka.
- **Recursive Provenance:** Events carry a `provenance_chain` (list of `plugin_id:version_id`). If any upstream node is breached, all downstream consumers automatically cascade to a "Degraded" state.

## Pillar 2: Predictive Attribution (Alpha-as-a-Science)
Every plugin must justify its existence via its **Information Coefficient (IC)**.
- **Dynamic Attribution:** The `SignalLifecycleService` maps every `SignalID` to its realized `PnL` and the context state at the time of signal generation.
- **Alpha Registry:** We maintain a real-time registry of plugin performance:
    - Realized Alpha = `SignalDirection` * `PriceMove` - `ExecutionCost`
    - Automated "Alpha Garbage Collection": Plugins consistently underperforming a baseline (e.g., simple Z-score < -1.0) are flagged in daily reports.
- **Scientific Pruning:** Plugins that are "predictive deadweight" (low feature importance via SHAP values) are surfaced for automatic removal.

## Pillar 3: Compute Efficiency (The "Efficient Frontier")
We optimize the graph for minimal compute cost per unit of alpha.
- **Compute Contract:** Every plugin registration requires a defined `Compute Budget` (Latency, Memory, Input-Signal count).
- **Liveness Tracker:** We map the consumption of every pipeline node.
    - If a plugin's output has 0 downstream consumers in the DAG for >24 hours, it triggers a `REDUNDANT_COMPUTATION_WARNING`.
- **Visualization:** Grafana dashboard plotting the "Alpha/Latency Frontier":
    - X-Axis: `Compute Cost (ns)`
    - Y-Axis: `Information Coefficient (Predictivity)`
    - *Goal:* Identify and prune nodes that are high-cost/low-alpha.

## Implementation Roadmap
1.  **Phase 1 (Integrity):** Standardize `src/validation/` to house reference implementations for all Tier 1-3 signals.
2.  **Phase 2 (Instrumentation):** Instrument the DAG with `ProvenanceChain` and `ExecutionTime` headers in Kafka.
3.  **Phase 3 (Reporting):** Build the automated `AuditService` that produces the "Alpha/Latency Frontier" report and flags redundant logic.

## Principles for Tooling
- **Deterministic First:** No non-deterministic frameworks (LLM-based logic) in the hot signal path.
- **Transparency:** Every node’s decision trace must be visible (no black-box chaining).
- **Automation:** No manual auditing; all audit results must be actionable (flags, auto-removal PRs, or automated circuit-breaker events).
