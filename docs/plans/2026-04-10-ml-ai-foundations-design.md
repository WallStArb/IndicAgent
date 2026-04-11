# Phase 56: ML/AI Foundation Layer — Design

**Status:** Approved — Ready for implementation planning
**Date:** 2026-04-10
**Author:** Brandon + Claude Code
**Supersedes:**
- `docs/plans/2026-04-09-phase-56-swarm-foundation-design.md`
- `docs/plans/archive/2026-04-08-ai-layer-refactor-design-v3.md`

---

## Overview

Phase 56 builds the **ML/AI Foundation Layer** — the complete shared infrastructure that every downstream AI and ML component (Phase 66 swarm agents, Phase 67 LightGBM model, future synthesis agents) depends on. It is not a swarm phase. It is not a narrative phase. It is the foundation that makes all of those phases cheap to build and correct by default.

**Renaissance framing:** The feedback loop IS the edge. This phase wires the loop. Discovery starts the day Phase 56 ships — tsfresh + IC analysis runs on existing `intelligence_features` data immediately. Shadow recording starts the day swarm agents ship. Phase 67 slots into an already-running LangGraph orchestrator. No manual steps anywhere.

**Design principles:**
- Instrument everything — every LLM call, every shadow prediction, every feature IC score is recorded
- Let the system run — weekly discovery + quality checks via systemd timers, no human triggers
- Separation of concerns — LLM infra, ML core, agent base classes are independent modules
- No train/serve skew — `FeatureVector` is defined once, used identically at training and inference
- Self-hosted everything — MLflow + LangFuse on Docker, full data ownership

**What gets archived:**
- `.planning/phases/56-ai-layer-refactor-v3/` — subsumed by this design
- `.planning/phases/56-swarm-foundation/` — extended and renamed to `56-ml-ai-foundation/`
- `services/ai_narrative_service.py` → `services/_archived_ai_narrative_service.py`
- `src/intelligence/llm_providers.py` → moved to `src/core/llm/providers.py` (backward-compat stub retained one phase)

---

## Section 1: Architecture

### Directory Structure

```
src/core/llm/
  __init__.py               # exports: LLMProviderChain, CircuitBreaker, SemanticCache,
  providers.py              #          RateLimiter, TokenBudget
  circuit_breaker.py
  semantic_cache.py
  rate_limiter.py
  token_budget.py
  guardrails.py

src/core/ml/
  __init__.py               # exports: FeatureVector, FeatureExtractor, ShadowRecorder,
  features.py               #          ModelRegistry, TrainingDataQuery
  extractor.py
  shadow.py
  registry.py
  training_data.py

src/core/agents/
  ai_base.py                # AIBaseAgent (abstract, extends BaseAgent)
  alpha_contributor.py      # IAlphaContributor protocol

src/intelligence/narrative/
  __init__.py
  orchestrator.py           # NarrativeOrchestrator
  synthesizer.py
  prompts.py
  parsers.py

services/
  ai_narrative_agent.py           # AINarrativeComputeAgent (~200 lines)
  swarm_orchestrator_agent.py     # SwarmOrchestratorComputeAgent
  swarm_writer_agent.py           # SwarmWriterAgent
  ml_discovery_agent.py           # MLDiscoveryComputeAgent
  ml_data_quality_agent.py        # MLDataQualityAuditorAgent
  ml_orchestrator_agent.py        # MLOrchestratorComputeAgent (LangGraph)
```

### Wave Structure

| Wave | Plans | Parallelism | Gate |
|------|-------|-------------|------|
| 1 | 56-01 (LLM infra), 56-06 ext (DB migrations + Docker) | parallel | none |
| 2 | 56-03 ext (Protocol + FeatureVector), 56-04 ext (Metrics), 56-08 (ML core) | parallel | Wave 1 done |
| 3 | 56-02 (Narrative module), 56-05 (Narrative agent), 56-09 (Data Quality) | parallel | Wave 2 done |
| 4 | 56-07 (Swarm runtime), 56-10 (Discovery) | parallel | Wave 3 done |
| 5 | 56-11 (MLAgent Orchestrator) | sequential | Wave 4 done |

### Existing Plans Retained (from `56-swarm-foundation`)

Plans 56-01 through 56-07 are kept and some extended with new scope:

| Plan | Original scope | Extension |
|------|---------------|-----------|
| 56-01: LLM Infrastructure Move | Move `llm_providers.py` → `src/core/llm/` | + `SemanticCache`, `RateLimiter`, `TokenBudget`, LangFuse callback, guardrails-ai integration |
| 56-02: Narrative Module Extraction | Extract `src/intelligence/narrative/` | No change |
| 56-03: Swarm Protocol + Schema Fixes | `IAlphaContributor`, `SwarmContext`, `AgentResult` | + `FeatureVector` schema; `SwarmContext` references `FeatureVector` |
| 56-04: Safety + Aggregator + Metrics | `SafeSwarmWrapper`, Prometheus metrics | + ML-specific metrics (LLM latency, tokens, shadow counts, IC scores) |
| 56-05: Narrative Service Refactor | Thin `AINarrativeComputeAgent` | No change |
| 56-06: DB + Stream Keys + Migration | `alpha_multiplier_shadow`, swarm topics | + `ml_models`, `ml_discovery_runs` tables; MLflow + LangFuse Docker Compose |
| 56-07: Swarm Services | `SwarmOrchestratorComputeAgent` + `SwarmWriterAgent` | Rename class to include role suffix: `SwarmOrchestratorComputeAgent` |

### New Plans

| Plan | What it builds |
|------|---------------|
| 56-08: ML Core | `src/core/ml/` — `FeatureVector`, `FeatureExtractor`, `ShadowRecorder`, `ModelRegistry`, `TrainingDataQuery` |
| 56-09: Data Quality Agent | `MLDataQualityAuditorAgent` — automated completeness + coverage checks on `intelligence_features` |
| 56-10: Discovery Infrastructure | `MLDiscoveryComputeAgent` — tsfresh + alphalens IC analysis, weekly automated run |
| 56-11: MLAgent Orchestrator | `MLOrchestratorComputeAgent` — LangGraph skeleton, systemd timer, no manual steps |

---

## Section 2: Component Design

### Layer 1: Shared LLM Infrastructure (`src/core/llm/`)

**`LLMProviderChain`** (moved + extended from `src/intelligence/llm_providers.py`):
- Provider chain: OpenRouter (primary) → Ollama (offline fallback)
- Every `generate()` call automatically: rate-checks → semantic-cache lookup → LLM call → guardrails validate → LangFuse trace → `topic_llm_calls()` publish
- Callers see a single `async generate(prompt, system, max_tokens, timeout, call_type)` — all infrastructure is invisible

**`SemanticCache`**:
- LRU cache (configurable size: `LLM_SEMANTIC_CACHE_SIZE = 500`)
- Key: SHA-256 hash of `(system_prompt, prompt[:200], model)` — similar prompts share cache
- TTL: configurable per `call_type` via `Settings`
- Reduces OpenRouter costs on repeated/similar signal contexts

**`RateLimiter`**:
- Per-provider token bucket (RPM + TPM limits from `Settings`)
- Non-blocking: if limit hit, waits minimum backoff then retries
- Prometheus gauge: `llm_rate_limit_wait_seconds`

**`TokenBudget`**:
- Per `call_type` daily spend tracking (tokens × estimated cost)
- Configurable hard limit: exceeding budget → fallback to Ollama only
- Prometheus counter: `llm_tokens_used_total{call_type, provider}`

**`guardrails`**:
- Every LLM response validated against a Pydantic schema before returned to caller
- Schema registered per `call_type` (narrative, swarm_alpha, discovery_hypothesis)
- Validation failure → response rejected, logged to DLQ, caller receives `None`
- Prevents hallucinated multiplier values from reaching signal pipeline

**LangFuse integration**:
- Automatic trace on every `generate()` call — span includes: model, tokens, latency, prompt hash, `call_type`
- Zero per-agent wiring required — wired once in `LLMProviderChain`

---

### Layer 2: AI Base Agent Framework (`src/core/agents/`)

**`AIBaseAgent`** (abstract, extends `BaseAgent`):
- Inherits: SIGTERM drain, structured logging, Prometheus metrics server, OTel tracer
- Adds: automatic shadow recording via `ShadowRecorder` (every `IAlphaContributor` output recorded)
- Adds: per-agent `asyncio` timeout (configurable, default 30s)
- Adds: DLQ publish on unhandled exceptions
- Adds: OTel span wrapping `compute()` method
- Subclasses implement: `_compute(context: SwarmContext) -> AlphaMultiplier`

**`IAlphaContributor`** (Protocol):
```python
class IAlphaContributor(Protocol):
    agent_id: str                          # unique, stable identifier
    path: Literal["path_a", "path_b"]     # deterministic vs LLM

    async def compute(self, ctx: SwarmContext) -> AlphaMultiplier: ...
```
- Multiplier range: `[0.0, 2.0]` — enforced by `SafeSwarmWrapper`
- `1.0` = neutral (no adjustment)
- Every contributor records to `alpha_multiplier_shadow` automatically via `AIBaseAgent`

---

### Layer 3: ML Core (`src/core/ml/`)

**`FeatureVector`** (Pydantic, `model_config = ConfigDict(frozen=True)`):
- ~85 fields drawn from `intelligence_features` JSONB tiers (i1–i7)
- Identical schema used at training time (polars → `FeatureVector`) and inference time (`IntelligenceEvent` → `FeatureVector`)
- Eliminates train/serve skew: one schema, one source of truth
- Regime fields: `hmm_regime`, `hmm_prob`, `hurst_exponent` — always present for segmentation

**`FeatureExtractor`**:
- `from_event(event: IntelligenceEvent) -> FeatureVector` — real-time path
- `from_row(row: polars.Series) -> FeatureVector` — training/batch path
- Both paths use identical field extraction logic — same function, different input adapter

**`ShadowRecorder`**:
- `async record(signal_id, agent_id, multiplier, confidence, symbol, tf, regime, path)` → `alpha_multiplier_shadow`
- Called automatically by `AIBaseAgent` — zero per-agent boilerplate
- Batched writes (configurable batch size + flush interval) via asyncpg

**`ModelRegistry`** (thin MLflow wrapper):
- `register(run_id, segment, artifact_path) -> model_id`
- `load_latest(segment) -> model_artifact`
- `promote(model_id)` / `revert(model_id)`
- Hides MLflow API from all callers

**`TrainingDataQuery`**:
- `async query(symbol, tf, regime, date_range) -> polars.DataFrame`
- JOIN: `intelligence_features` + `signal_ledger` on `(symbol, feature_ts, feature_tf)`
- Output columns: all `FeatureVector` fields + `outcome`, `pnl_r`, `mae`, `mfe`
- No lookahead: `WHERE feature_ts < outcome_ts` enforced in SQL

---

### Layer 4: Data Quality Agent

**`MLDataQualityAuditorAgent`** (`services/ml_data_quality_agent.py`):
- Runs via systemd timer: `indicagent-ml-data-quality.timer` (Monday 05:00)
- Checks:
  - CIS null rate in `intelligence_features` (target: < 1%)
  - Outcome label coverage in `signal_ledger` (target: > 95% resolved)
  - Feature coverage gaps per (symbol, tf, date_range) — missing bars
  - Outlier feature values (> 6σ from rolling mean)
- Emits: `data_quality_score` Prometheus gauge (0.0–1.0)
- Publishes alert to `topic_ml_data_quality_alerts()` if score < `DATA_QUALITY_MIN_SCORE` (default: 0.85)
- `MLOrchestratorComputeAgent` reads score before dispatching `MLDiscoveryComputeAgent`

---

### Layer 5: Discovery Infrastructure

**`MLDiscoveryComputeAgent`** (`services/ml_discovery_agent.py`):
- Runs via systemd timer: `indicagent-ml-discovery.timer` (Monday 06:00, after data quality)
- Step 1 — Feature extraction: `tsfresh.extract_features()` on rolling `intelligence_features` window (configurable lookback, default 90 days)
- Step 2 — IC analysis: `alphalens-reloaded` IC/ICIR per feature vs `signal_ledger.pnl_r`, segmented by `hmm_regime`
- Step 3 — LLM hypothesis (optional, `call_type="discovery_hypothesis"`): `LLMProviderChain` generates interpretations for top-IC features
- Step 4 — Persistence: writes to `ml_discovery_runs`; updates `feature_ic_score` Prometheus gauge per feature
- Can run on existing data immediately — no trained model required
- Regime segmentation: IC computed per `hmm_regime ∈ {0, 1, 2}` — global IC alone does not qualify

**Exception note:** `MLDiscoveryComputeAgent` writes directly to `ml_discovery_runs` (batch job, timer-triggered). Acceptable deviation from ComputeAgent = DB-ignorant rule. Precedent: `indicagent-data-quality` timer service.

---

### Layer 6: Narrative Refactor

**`AINarrativeComputeAgent`** (`services/ai_narrative_agent.py`, ~200 lines):
- Replaces `ai_narrative_service.py` (1,327 lines archived)
- Subscribes to `topic_intelligence_i7_signals()`
- Delegates all narrative logic to `src/intelligence/narrative/NarrativeOrchestrator`
- Uses `LLMProviderChain` from `src/core/llm/` — no direct provider instantiation

**`src/intelligence/narrative/`** (extracted):
- `NarrativeOrchestrator` — coordinates prompt building + LLM call + parsing
- `NarrativeSynthesizer` — group synthesis logic
- `prompts.py` — prompt templates (constants)
- `parsers.py` — response parsing (pure functions)

---

### Layer 7: Swarm Runtime

**`SwarmOrchestratorComputeAgent`** (`services/swarm_orchestrator_agent.py`):
- Subscribes to: `topic_intelligence_i7_signals()` + `topic_intelligence_journal()`
- Bar loop: populates `SwarmContextCache` (symbol+tf keyed, TTL 5min, `BoundedLRUSet` dedup)
- Signal loop:
  1. Build `SwarmContext` from cache (O(1), no DB)
  2. Run Path A contributors (deterministic, `asyncio.gather`, <5ms each) → `topic_swarm_alpha_path_a()`
  3. Dispatch Path B contributors (LLM swarm, per-agent timeout) → `topic_swarm_alpha_path_b()`
  4. Publish world state delta → `topic_swarm_world_state()` (compacted)
- DLQ: `topic_swarm_orchestrator_dlq()` for unresolvable contexts
- SIGTERM: drain in-flight contributors, flush context cache

**`SwarmWriterAgent`** (`services/swarm_writer_agent.py`):
- Subscribes to: `topic_swarm_alpha_path_a()` + `topic_swarm_alpha_path_b()`
- Writes to: `alpha_multiplier_shadow` (batched asyncpg)
- DLQ: `topic_swarm_writer_dlq()` for malformed payloads or DB failures

---

### Layer 8: MLAgent Orchestrator

**`MLOrchestratorComputeAgent`** (`services/ml_orchestrator_agent.py`):
- LangGraph `StateGraph` with 4 nodes (2 active, 2 stubs):

```
DataQualityNode → DiscoveryNode → [TrainingNode: stub] → [MonitorNode: stub]
```

- `MLOrchestrationState`: `data_quality_score`, `last_discovery_run_id`, `model_status`, `last_error`
- Routing: if `data_quality_score < DATA_QUALITY_MIN_SCORE` → skip `DiscoveryNode`, emit alert, exit
- `TrainingNode` and `MonitorNode`: no-ops that log `"awaiting Phase 67"` and pass state through
- Runs via systemd timer: `indicagent-ml-orchestrator.timer` (Monday 04:00 — before data quality + discovery)
- Deterministic routing only — no LLM in the orchestrator. Discovery and Narrative nodes use LLMs.
- Phase 67 adds `TrainingNode` and `MonitorNode` implementations — no architecture changes

---

### Layer 9: Self-Hosted Infrastructure

**Docker Compose additions:**
```yaml
mlflow:
  image: ghcr.io/mlflow/mlflow:latest
  ports: ["5000:5000"]
  volumes: ["mlflow_data:/mlflow"]
  restart: unless-stopped

langfuse:
  image: langfuse/langfuse:latest
  ports: ["3000:3000"]
  environment:
    DATABASE_URL: postgresql://...
  restart: unless-stopped
```

**DB Migrations:**

```sql
-- alpha_multiplier_shadow (TimescaleDB hypertable)
CREATE TABLE alpha_multiplier_shadow (
    ts              TIMESTAMPTZ NOT NULL,
    signal_id       UUID NOT NULL,
    agent_id        TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    tf              TEXT NOT NULL,
    hmm_regime      INT,
    path            TEXT NOT NULL,          -- 'path_a' | 'path_b'
    predicted_multiplier FLOAT NOT NULL,
    confidence      FLOAT NOT NULL,
    features        JSONB,                  -- snapshot of FeatureVector for training
    PRIMARY KEY (signal_id, agent_id)
);
SELECT create_hypertable('alpha_multiplier_shadow', 'ts');

-- ml_models
CREATE TABLE ml_models (
    model_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_type      TEXT NOT NULL,          -- 'lightgbm', 'random_forest'
    segment         JSONB NOT NULL,         -- {regime, setup_type, tf}
    mlflow_run_id   TEXT,
    status          TEXT NOT NULL DEFAULT 'shadow',  -- 'shadow' | 'production' | 'retired'
    shadow_correlation FLOAT,
    promoted_at     TIMESTAMPTZ,
    artifact_path   TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ml_discovery_runs
CREATE TABLE ml_discovery_runs (
    run_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ts              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    symbol          TEXT,
    tf              TEXT,
    regime          INT,
    top_features    JSONB NOT NULL,         -- [{name, ic, icir, p_value}]
    ic_scores       JSONB NOT NULL,         -- full feature → IC map
    feature_count   INT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'complete'  -- 'complete' | 'partial'
);
```

---

### Layer 10: ML Observability

New Prometheus metrics (via `src/observability/metrics.py`):

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `llm_call_duration_seconds` | Histogram | `provider`, `call_type`, `status` | LLM latency per provider |
| `llm_tokens_used_total` | Counter | `provider`, `call_type` | Token spend tracking |
| `llm_cache_hit_total` | Counter | `call_type` | SemanticCache hit rate |
| `llm_guardrails_rejections_total` | Counter | `call_type` | Schema validation failures |
| `shadow_predictions_total` | Counter | `agent_id`, `path` | Shadow recording volume |
| `agent_inference_latency_seconds` | Histogram | `agent_id` | Per-agent compute time |
| `feature_ic_score` | Gauge | `feature_name`, `regime` | IC per feature per regime (updated weekly) |
| `data_quality_score` | Gauge | — | Current training data quality (0–1) |

OTel: all `LLMProviderChain.generate()` calls emit spans → LangFuse (automatic via callback). `AIBaseAgent.compute()` wraps in a child span.

---

## Section 3: Data Flow

```
# Hot path (unchanged — swarm never blocks it)
IntelligencePipelineComputeAgent
  └→ intelligence.i7.signals
  └→ intelligence_features / signal_ledger (via existing writers)

# Swarm path (async, out-of-band, shadow only)
intelligence.i7.signals
  └→ SwarmOrchestratorComputeAgent
        ├→ Path A: deterministic contributors (sync, <5ms)
        │     └→ topic_swarm_alpha_path_a()
        └→ Path B: LLM contributors (asyncio.gather, per-agent timeout)
              └→ topic_swarm_alpha_path_b()
  └→ SwarmWriterAgent
        └→ alpha_multiplier_shadow

# Narrative path (refactored internals, same topology)
intelligence.i7.signals
  └→ AINarrativeComputeAgent
        └→ NarrativeOrchestrator (src/intelligence/narrative/)
        └→ LLMProviderChain (src/core/llm/)
        └→ topic_narratives()

# ML batch path (weekly, fully automated)
indicagent-ml-orchestrator.timer (Monday 04:00)
  └→ MLOrchestratorComputeAgent (LangGraph)
        ├→ DataQualityNode: MLDataQualityAuditorAgent
        │     checks intelligence_features + signal_ledger
        │     └→ data_quality_score gauge
        │     └→ topic_ml_data_quality_alerts() if score < threshold
        └→ DiscoveryNode: MLDiscoveryComputeAgent (gated on quality)
              tsfresh → 700+ features
              alphalens IC vs pnl_r, segmented by regime
              └→ ml_discovery_runs
              └→ feature_ic_score gauges (per feature, per regime)
              [TrainingNode: stub → Phase 67]
              [MonitorNode:  stub → Phase 67]

# LLM observability (automatic)
LLMProviderChain.generate()
  └→ LangFuse span (tokens, latency, model, call_type)
  └→ topic_llm_calls() (existing)
  └→ Prometheus: llm_call_duration_seconds, llm_tokens_used_total
```

---

## Section 4: Error Handling

| Failure | Handler |
|---------|---------|
| LLM all providers fail | CircuitBreaker opens; `SemanticCache` returns stale if available; DLQ otherwise |
| guardrails validation fails | Response rejected; logged to `topic_llm_calls()` with `status=rejected`; caller receives `None` |
| SwarmOrchestratorComputeAgent: no cache entry | `topic_swarm_orchestrator_dlq()` — never blocks hot path |
| SwarmWriterAgent: DB insert fails | `topic_swarm_writer_dlq()` — 3× retry, then dead-letter |
| MLDataQualityAuditorAgent: score < threshold | Alert to `topic_ml_data_quality_alerts()`; orchestrator skips DiscoveryNode |
| MLDiscoveryComputeAgent: tsfresh timeout | Partial results written (`status=partial`); next weekly run starts fresh |
| LangGraph node failure | State serialised + logged; systemd restarts on next timer tick |

All agents inherit SIGTERM drain from `BaseAgent` via `AIBaseAgent`.

---

## Section 5: Testing

Convention: `tests/unit/test_<module>.py`, functions `test_<what>_<condition>`.

| Plan | Key unit tests |
|------|---------------|
| 56-01 | `test_semantic_cache_returns_cached_on_hit`, `test_rate_limiter_blocks_at_rpm_limit`, `test_circuit_breaker_opens_after_5_failures`, `test_guardrails_rejects_wrong_schema`, `test_token_budget_falls_back_to_ollama_on_exceeded` |
| 56-03 | `test_feature_vector_is_frozen`, `test_swarm_context_builds_from_event`, `test_alpha_contributor_clamps_multiplier_to_range` |
| 56-08 | `test_feature_extractor_same_result_from_event_and_row`, `test_shadow_recorder_writes_correct_columns`, `test_training_data_query_enforces_no_lookahead` |
| 56-09 | `test_quality_score_fails_on_high_cis_null_rate`, `test_quality_gate_blocks_discovery_node` |
| 56-10 | `test_ic_analysis_segmented_by_regime`, `test_discovery_writes_ml_discovery_runs`, `test_partial_result_on_timeout` |
| 56-11 | `test_orchestrator_skips_discovery_on_low_quality_score`, `test_training_node_is_noop`, `test_monitor_node_is_noop` |

All unit tests mock Kafka + DB via class-level `AsyncMock` (per CLAUDE.md async mock gotcha). Integration tests in `tests/integration/` require live TimescaleDB + Redpanda.

---

## Section 6: Constants & Config

All configurable via `src/config/settings.py`:

| Constant | Default | Purpose |
|----------|---------|---------|
| `LLM_SEMANTIC_CACHE_SIZE` | `500` | SemanticCache LRU max entries |
| `LLM_RATE_LIMIT_RPM` | per-provider dict | Requests-per-minute per provider |
| `LLM_RATE_LIMIT_TPM` | per-provider dict | Tokens-per-minute per provider |
| `SHADOW_CORRELATION_THRESHOLD` | `0.4` | ρ required for promotion |
| `SHADOW_MIN_SAMPLES` | `100` | N required for promotion |
| `DATA_QUALITY_MIN_SCORE` | `0.85` | Gate for discovery + training |
| `ML_DISCOVERY_LOOKBACK_DAYS` | `90` | tsfresh rolling window |
| `ML_DISCOVERY_IC_THRESHOLD` | `0.05` | Min IC to include in report |
| `ML_ORCHESTRATOR_SCHEDULE` | `"0 4 * * 1"` | Weekly Monday 04:00 |
| `ML_DATA_QUALITY_SCHEDULE` | `"0 5 * * 1"` | Weekly Monday 05:00 |
| `ML_DISCOVERY_SCHEDULE` | `"0 6 * * 1"` | Weekly Monday 06:00 |

---

## Related Documentation

- `docs/intelligence/ai-tech-stack.md` — ML/AI technology choices (LightGBM, LangFuse, MLflow, evidently)
- `docs/ideas/ml-agent-architecture.md` — Multi-agent learning machine design
- `docs/ideas/renaissance-alpha-pipeline.md` — Shadow-first validation framework
- `docs/ideas/intelligence-swarm-manifest.md` — Swarm agent registry + IAlphaContributor principles
- `docs/intelligence/ai-intelligence-architecture.md` — Current I1-I8 pipeline state
- `.planning/ROADMAP.md` — v2.3 milestone: Phase 56 (this) → Phase 66 (SkepticAgent) → Phase 67 (LightGBM)

---

*Focus: what to build and why. Implementation plans in `.planning/phases/56-ml-ai-foundation/`.*
