# Foundational Principles of IndicAgent

**Version:** 2.9
**Status:** current
**Last Updated:** 2026-06-16
**Tags:** architecture, design-principles, plugin-system, event-driven, pipeline, extensibility

> The North Star for all development and architectural decisions. When in doubt about a design choice, check it against these principles first.

---

## 1. Plugin-Native Shell

The platform is an empty shell; intelligence is composed entirely of plugins. If logic isn't a plugin, it's not extensible. New capabilities are added by writing a single `PatternPlugin` subclass registered in `TIER_*` — without changing pipeline or stream infrastructure.
<!-- src: src/intelligence/register_plugins.py -->

## 2. Event-Driven Agents, Decoupled by Topic

No agent calls another directly. Redpanda (Kafka-compatible) is the sole, durable communication fabric. Restarting `indicagent-intelligence-pipeline` has zero operational impact on `indicagent-feature-writer` or `indicagent-signal-writer`. Each agent resumes from its committed Kafka offset — nothing is lost.
<!-- src: src/core/stream_keys.py -->

## 3. Hot Path Never Touches the Database

The real-time pipeline (I1-I7) is DB-ignorant. Persistence is strictly asynchronous — decoupled via dedicated Writers (`FeatureWriter`, `SignalWriter`, `LifecycleWriter`). A TimescaleDB outage has zero impact on intelligence computation or signal generation latency.
<!-- src: src/intelligence/intelligence_pipeline.py -->

## 4. Topological Orchestration

Dependency-aware DAG execution replaces hardcoded sequencing. Plugin dependencies are declared via `inputs`/`outputs`, allowing the system to derive execution order automatically (Kahn's algorithm) and detect circular dependencies at startup. Parallel execution emerges from the dependency graph — no manual config.
<!-- src: src/intelligence/dag_executor.py -->

## 5. Incremental-First

Every plugin implements `compute_next()` for O(1) updates per bar. This is the foundation of throughput: 132 plugins process a new bar by updating only what changed since the last bar, not recomputing from scratch. Warmup is the only exception (~50 bars for GARCH/Kalman/HMM to converge).
<!-- src: src/intelligence/base_plugin.py -->

## 6. Data Contracts Over APIs

The schema is the API. `IntelligenceEvent` (tiered JSONB: i1, i2, i3, i4, i5, smc, i6) is the sole contract between compute and consumers. `BarIntelligenceRecord` wraps it with ranked signals into an atomic per-bar record on `intelligence.journal` — single topic, single atomic INSERT, no partial writes.
<!-- src: src/intelligence/schemas.py -->

## 7. Institutional Rigor — Evidence-Graded Intelligence

Every output is evidence-graded. Every feature score, ensemble weight, and alpha emission is traceable to a measured IC against realized forward returns. Bootstrap confidence intervals, p < 0.05 promotion gates, and rolling walk-forward IC are the standard — not static thresholds or hand-tuned weights. Every bar processed adds to the labeled training corpus. Every labeled sample is kept forever.

**The north star:** The researcher produces features across orthogonal domains. The IC engine measures which features predict returns. The ensemble discovers what combinations matter. No human defines what confluence looks like — the data shows it. Any design that requires a researcher to encode which feature combinations constitute edge is a bias embedded in architecture, not rigor. The CIS score (researcher-defined confluence buckets) is a v2.x construct; v3.0 replaces it with IC-weighted ensemble combination where confluence emerges from co-occurring high-IC scores, discovered empirically.

Every alpha emission is a labeled training sample — kept forever in the three-table architecture: `alpha_events` (detection) / `trade_frames` (hypothesis) / `trade_executions` (execution).

**See also:** `docs/ideas/signal-08-intelligence-refactor.md` — full conceptual design of the v3.0 intelligence refactor and the north star principle.
<!-- src: signal_events table, trade_frames table, trade_executions table -->

## 8. Self-Correcting Pipeline

Drift detection (KS/CUSUM), performance monitoring, and model-weight backfilling are baked into the live loop. `ServiceAuditor` monitors pipeline health and triggers restarts on threshold breach. `ParityAuditor` certifies feature writes after 60 clean parity cycles. The system validates its own integrity and self-adjusts without human intervention.
<!-- src: services/service_auditor.py, services/parity_auditor.py -->

## 9. Never Drop Data That Could Contain Signal

Storage is the cheapest thing we own. Every signal outcome, feature vector, and LLM call is a labeled training sample. Once gone, it cannot be recovered. `intelligence_features`, SLA tables (`signal_events`, `trade_frames`, `trade_executions`), and `llm_calls` have no retention policies — they grow forever (TimescaleDB compression handles the cost). The ECL boundary invariant is a direct consequence of this principle: any extrinsic emission gate removes training data permanently.
<!-- src: docs/foundation/glossary.md — ECL boundary invariant -->

## 10. Shadow Before Production

No model, strategy, or feature goes to production without statistically significant evidence (p < 0.05, sufficient N). `FeatureSnapshotWriter` dual-writes to a shadow table; `ParityAuditor` compares for 60 clean cycles before certifying. New I7 plugins run with `IS_SHADOW=True` until their regime-conditional win rate is proven.
<!-- src: src/intelligence/register_plugins.py — IS_SHADOW flag -->

## 11. DAG Invariants — Non-Negotiable

The agentic DAG has seven structural invariants. These are not guidelines — violating any one of them breaks the guarantees that make the rest of the system work. Every new service and every code review must verify these hold.

1. **`ProviderMerger` is the sole writer to `market.bars`.** All downstream agents are isolated from provider topology. Adding a new data source means adding a Provider — zero downstream changes.
2. **I1–I7 runs entirely in-process.** `IntelligencePipeline` computes all 132 plugins in-memory before publishing. Kafka is a sink, not an inter-stage pipe. No I6→I7 Kafka hop.
3. **No hot-path compute touches the database.** Only Writer, Tracker, and Auditor services perform DB operations. A hot-path daemon that queries the DB is a DAG violation.
4. **All topic keys via `stream_keys.py`.** No hardcoded topic strings anywhere in the codebase.
5. **No agent calls another agent directly.** Topics are the only coupling. Point-to-point calls make topology invisible, create restart dependencies, and break the restart-from-offset guarantee.
6. **All timestamps UTC.** Every bar, event, and DB write uses timezone-aware UTC datetimes. `datetime.now(UTC)` only — never `datetime.now()` or `datetime.utcnow()`.
7. **Scaling via systemd + Prometheus lag.** No Kubernetes HPA. Consumer lag monitored via `persistence_consumer_lag` metric.

**Canonical reference:** `docs/architecture/architecture-dag-topology.md` — full system map with Mermaid diagram, agent taxonomy, and topic registry.
<!-- src: services/service_auditor.py — _DAG_ORDER -->

## 12. Signal Generation Invariant

**Pattern:** I7 plugins emit fully-framed signals only.

Every signal MUST include: stops, targets, zones, invalidation. Trade framing (`frame_trade()`) is called by the plugin during signal detection, not by a separate service. There is no "raw signal" intermediate state — this would be invalid per Renaissance data quality principles.

**Why:** A signal without stops/targets/zones cannot be evaluated by lifecycle services, executed, or persisted. Forcing a separation creates artificial intermediate state that violates the "every signal has a non-zero trading window" invariant.

**Enforcement:** `signal_schema.py` validation gate rejects incomplete signals. All 37 I7 plugins use `frame_trade()` (directly or via `detect_spike_signal()`).

**See also:** `docs/plans/2026-06-07-trade-framing-architecture-analysis.md` — Renaissance council analysis affirming embedded framing as correct architecture.
<!-- src: src/intelligence/trading/signal_schema.py -->
