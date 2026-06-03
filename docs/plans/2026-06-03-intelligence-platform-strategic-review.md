# Intelligence Platform Strategic Review

**Date:** 2026-06-03
**Status:** Active reference
**Lens:** Renaissance Technologies / Jim Simons council — mathematical rigor, data integrity, no hidden biases
**Scope:** Full architectural assessment + strategic direction for institutional intelligence platform

---

## Purpose

This document captures a full-spectrum architectural review of IndicAgent as of v2.8, conducted after sustained organic evolution across 110+ phases. The goal: verify alignment with the institutional quantitative intelligence platform target, identify structural debt blocking growth, and establish the architecture required to absorb fundamental and qualitative intelligence alongside the existing technical stack.

---

## What We Are Building

IndicAgent is not a trading bot. It is the **intelligence layer** that would feed one — a signal generation, validation, and lifecycle-tracking platform built on Renaissance principles: empirical over narrative, data integrity over model complexity, earn promotion through proof (p<0.05, n≥100).

**Near-term:** Institutional-grade quantitative signal platform for ES/NQ futures with shadow governance, ML feedback loop, and AI-assisted signal qualification.

**Target:** Multi-source intelligence platform where technical, fundamental, qualitative, and macro signals are equal-class citizens — each governed by the same shadow promotion gate, stored in the same feature hypertable, and ranked by the same unified aggregator.

The shared event bus (Redpanda) is the spine. Every signal type — however it originates — flows through the same DAG: ingest → compute → feature store → signal generation → shadow governance → outcome tracking → ML training → promotion.

---

## What Is Working

**Plugin registry and tier system** — frozen outputs, startup validation, single source of truth in `register_plugins.py`. This is the correct extensibility model. All new intelligence tiers (fundamental, qualitative) should replicate it exactly.

**Typed event bus** — `IntelligenceEvent` with Pydantic schemas. Strong contracts at deserialization boundaries. Every new tier publishes through the same bus.

**Signal lifecycle state machine** — 8-class outcome taxonomy, TTL-based expiration, zone-activation logic. Pure functions, well-tested, no side effects. The right abstraction for tracking any signal type.

**Aggregator** — CIS scoring, regime gating, co-fire detection, performance multipliers. Regime awareness is the correct primitive. The unified aggregator for multi-source signals should build on this, not replace it.

**Data model** — hypertables, JSONB tiering in `intelligence_features`, `signal_ledger` structure. Scales. Will absorb additional intelligence tiers as new JSONB columns (`f1`, `q1`, etc.) without schema disruption.

**Stream isolation** — all topic keys via `stream_keys.py`, zero hardcoded strings. DAG invariants enforced.

---

## What Is Broken (Fix Before Expanding)

These are not technical debt to schedule later. They are load-bearing system properties that do not work, meaning the platform cannot fulfill its stated purpose until they are repaired. Adding new intelligence sources on top of broken governance compounds the problem.

### Shadow Governance — Current State (Verified 2026-06-03)

Shadow governance is correctly wired for I7 plugins. Key points verified against live code:

- **`is_shadow` stamping is correct.** `executor.py` stamps `sig["is_shadow"]` on every signal dict. `signal_processor.py:418-430` builds `eligible_ranked` by explicitly filtering shadow plugins before `select_winner()`. Shadow signals reach `signal_ledger` for observation counting but never compete for winner selection.
- **Shadow metrics use correct OTel types.** All six shadow metrics (`shadow_n_resolved`, `shadow_win_rate`, etc.) are `point_gauge` using `.set()`. Numbers are correct.
- **Swarm agent graduation is a separate, intentional mechanism.** The shadow auditor skips `component_type='swarm_agent'` by design — swarm agents use Spearman-rho weight learning in `alpha_swarm._graduation_loop()` (15-min cycles), not the bootstrap CI gate used for I7 plugins. They produce confidence multipliers evaluated against realized `pnl_r`, not signal_ledger rows. Different model, different gate.

The governance loop is running. The statistical validity of the promotion gate depends on signal volume — at low-frequency signal cadences, reaching n=100 per plugin takes time. That is expected, not a bug.

### Data Integrity — Current State (Verified 2026-06-03)

Five defects from the May 2026 audit have been fixed in subsequent phases:

- **Output queue:** Main output uses `enqueue_many(timeout_sec=5.0)` — blocking with timeout. Journal is intentionally low-priority and documented as dropped on timeout (design choice, not a bug).
- **CtxWriterAgent:** All metric calls use `.add()`. The `.inc()` crash no longer present.
- **LLMWriterAgent:** Uses `BaseWriter` and `DatabaseManager` via `_setup()` correctly. No undefined `_pool`.
- **SwarmLedgerWriter:** `enable_auto_commit=False`, explicit commit after success, no-commit on transient DB failure.
- **FeatureWriterAgent:** Extends `BaseWriter` with `DatabaseManager`; no ghost-run pattern visible.

These were real issues when documented (2026-05-23) and have since been repaired.

### Observability Gap (Medium)

OTel span coverage exists on the critical path (`pipeline.process_bar_inner` wraps the full I1-I7 bar compute; `writer.flush` is spanned in feature_writer, llm_writer, context_writer; AI agents span `_compute()` and `_llm_generate()`). What is missing is **intra-tier granularity**: within the outer pipeline span you cannot distinguish how long I2 took vs I3 vs I5. A slow plugin is diagnosable via per-plugin histograms but not via traces. Per-plugin child spans inside `PluginExecutor` would close this gap.

### Pipeline Scope Is Intentionally Bar-Bounded

`intelligence_pipeline.py` is large by design — it is shared in-process compute for I1-I7 bar-based OHLCV processing. Keeping tiers in-process eliminates Kafka serialization hops between stages and is the correct latency decision for sub-second bar cadence. This pipeline is **not** the integration point for future intelligence tiers.

F-tier (fundamental: earnings, economic releases) and Q-tier (qualitative: news, sentiment) operate on completely different cadences — quarterly, monthly, or event-driven irregular. They do not belong in a 500ms-timeout bar pipeline and would have different failure profiles, state models, and latency budgets. Each gets its own independently-runnable event-driven pipeline. The integration point is the **feature store** (via the `ctx` as-of join at bar-write time) and the **unified aggregator** — not the compute layer.

---

## Strategic Architecture: Path to Multi-Source Intelligence

### Current Reality

IndicAgent is a sophisticated technical analysis engine. The AI layer (narrative swarm, alpha swarm) produces outputs that are not first-class signal citizens — they do not go through shadow governance, do not have feature vectors in `intelligence_features`, and do not have outcome tracking. The validation loop only covers I7 technical setups.

### Target Architecture

```
Data Sources
  Market microstructure (IBKR)               ← live
  Macro / cross-asset (equity indices, VIX)  ← live, partially
  Fundamental (earnings, economic releases)  ← not built
  Qualitative (news, sentiment, filings)     ← not built

Intelligence Tiers
  I1–I6: Indicators, patterns, structure, confluence  ← live (139 plugins)
  F1–F4: Fundamental context (event-driven, as-of join) ← not built
  Q1–Q2: Qualitative context (NLP, sentiment)         ← not built

Signal Generation
  I7: Technical setups (37 plugins + 2 aggregators)   ← live
  F7: Fundamental setups                              ← not built
  Q7: Qualitative setups                              ← not built
  Unified aggregator: ranks across all signal types   ← partially built (I7 only)

Validation (same gate for ALL signal types)
  Shadow governance: n≥100, bootstrap_ci_lower(pnl_r) > 0
  Outcome tracking: 8-class taxonomy, TTL lifecycle
  ML training: cross-source feature matrix
```

The key architectural insight: **the plugin registry, shadow governance, and signal lifecycle are the right abstractions — they need to be universal, not technical-only.** When fundamental signals are added, they should be plugins in an F-tier with the same registration pattern, `is_shadow` stamp, and outcome tracking as any I7 plugin. The governance mechanism is already designed for this; it just has to work first.

### Three Architectural Decisions

**1. I8 is not LLM narrative — it is the Qualitative Signal Tier**

The current I8 designation points to Ollama-powered narrative generation. That is a display layer, not a signal source. A proper Q-tier ingest: news/filings/sentiment via Kafka topics → extractive/abstractive analysis → `q1`–`q7` feature vectors stored in `intelligence_features` as a new JSONB column → Q7 signal plugins through shadow governance like any I7 setup. Narrative generation remains useful but belongs downstream of signal generation, not in the same tier slot.

**2. Fundamental data requires event-driven injection, not bar-driven processing**

Fundamentals (earnings, NFP, FOMC, economic surprises) are irregular events, not bar-cadence data. The pipeline cannot block on them. The correct pattern: a `ctx_events` / `ctx_snapshots` table keyed by `(symbol, event_timestamp)`, joined to bar rows at write time using an as-of pattern (latest qualitative snapshot effective at bar close). The feature writer resolves the correct snapshot during persistence. This keeps the hot-path bar processing DB-ignorant and the qualitative layer independently runnable.

Integration rule: if the qualitative layer is offline, quant ingestion and compute continue. Consumers degrade by missing context, not by blocking upstream agents. Do not mutate a bar row after write when qualitative context arrives — that creates hidden race conditions.

**3. The unified aggregator ranks across signal types, not tiers**

The current aggregator only sees I7 signals. An institutional platform ranks across all source types — a strong fundamental signal with weak technical backing should score differently than cross-source alignment. The aggregator should weight by: regime coherence, source independence (technical + fundamental = higher conviction than two technical setups), historical edge per source type, and CIS. This is the highest-value architectural addition after governance is fixed.

### Intelligence Fabric Design

The unified intelligence layer is a set of **domain-owned streams plus optional read models** — not a central controller.

| Domain | Canonical truth | Optional projection |
|---|---|---|
| Quant features | `intelligence.journal`, `intelligence_features` | `AIContext`, dashboard, ML exports |
| Signals | `signal_ledger` | scoring feature matrices |
| Qualitative context | `ctx_events`, `ctx_snapshots` | `intelligence_features.ctx`, prompt context |
| LLM/AI calls | `llm.calls`, `llm_calls` | model score summaries |
| ML decisions | model registry + shadow evaluation | promoted model score stream |

**Decoupling rule:** if a projection/read model is down, source-domain ingestion and compute continue. Each intelligence domain must be independently runnable. No cross-domain hard dependencies at runtime.

**Stream contract:** do not add tier-specific Kafka topics until a concrete consumer or scaling bottleneck justifies the additional stream surface. Until then, AI/ML/context consumers use `intelligence.journal`, `intelligence_features`, or explicitly versioned derived topics.

**Qualitative output must not affect I7 confidence, signal selection, or position sizing until it passes shadow-mode statistical validation** — the same bar any technical plugin must clear.

---

## Priority Action List

### Foundation (verified 2026-06-03 — all clear)

Issues flagged in the May 2026 audit have been fixed in subsequent phases. Shadow governance, data integrity, OTel coverage, and swarm agent graduation are all correctly wired. No P0/P1 remediation needed.

### Expand

| Priority | Action |
|---|---|
| P3 | `ctx_events` / `ctx_snapshots` tables + `CtxWriterAgent` — the qualitative substrate |
| P3 | First deterministic context lane: macro economic calendar or earnings surprise |
| P3 | `intelligence_features.ctx` JSONB column + as-of join at feature write time |
| P4 | Q-tier plugin framework: same registration pattern as I-tier, same shadow governance |
| P4 | F-tier plugin framework: fundamental signals with event-driven injection |
| P5 | Unified cross-source aggregator: ranks I7 + F7 + Q7 by cross-source conviction |

---

## Verified Open Findings (from platform-08-architectural-weaknesses.md)

Full detail and fix guidance in `docs/ideas/platform-08-architectural-weaknesses.md`.

### Fixed (2026-06-03)

| # | Finding | Fix |
|---|---|---|
| #25 | `TransformRecorder` live on archived hot path — 4-5 DB writes/signal/bar | `recorder=None` passed to SignalProcessor; teardown block removed. Commit 3dada29f. |
| #14 | Per-tier latency (I2-I6) completely absent | Per-tier timing added in `executor.py run_tiers()` via `_timed_tier` wrapper. All 6 tiers now emit `intelligence_pipeline_tier_latency_ms{tier=X}`. |
| #34 | `otel.py` silently suppresses all OTel init errors | Both except blocks now emit `_log.warning()` with endpoint and error. |
| HF-10 (partial) | `llm.outcomes` topic had no publisher — LLM outcome back-fill permanently broken | `signal_tracker._publish_transition()` now publishes to `topic_llm_outcomes` on every EXIT transition. `intelligence.i8` subscriber remains — deferred pending qualitative tier. |
| #32 (partial) | Raw `.isoformat()` on Kafka message paths | Fixed in `lifecycle_transitions.py` `to_dict()`/`_json_safe()`, `bar_replay_provider._publish_bar()`, `signal_replay_auditor` transition payloads. Non-Kafka paths (logs, checkpoints) left as-is. |

### Confirmed Still Open

| # | Finding | Severity |
|---|---|---|
| #33 | Dual graduation mechanisms — `graduation_analyzer` still reads `signal_transform_log` which TransformRecorder no longer writes. Needs migration to `signal_lineage` before graduation_compute starves. | MEDIUM |
| HF-10 (i8) | `intelligence.i8` subscriber in `llm_writer` has no publisher — deferred until qualitative tier is built | LOW (deferred by design) |

### Not Verified (needs a focused session)

HF-6 (LLMWriter stall watchdog permanently disabled), HF-7 (BarWriter stall detection blind), HF-11 (CtxWriter skips `super()._teardown()`), #17 (systemd After= wrong unit), #19 (feature_writer agent ID mismatch), #20 (cyclic L5 restart order), #24 (agent vs agent_id label split), #30 (bar_replay no Conflicts= guard), #36 (checkpoint write synchronous).

---

## Related Documents

- `docs/ideas/ai-10-qualitative-intelligence-layer.md` — detailed qualitative tier design (schema, ingestion lanes, as-of join, NLP quality constraints)
- `docs/ideas/platform-01-architecture.md` — product family vision (shared bus, QualAgent, TradeAgent, DerivAgent)
- `docs/ideas/platform-08-architectural-weaknesses.md` — full bug inventory with root causes and file references
- `docs/plans/2026-06-02-intelligence-pipeline-signal-integrity.md` — P0 signal integrity fix plan (22 findings, contamination timeline)
- `docs/foundation/principles.md` — north star principles
