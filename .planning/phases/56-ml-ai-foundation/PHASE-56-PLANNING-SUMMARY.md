# Phase 56: ML/AI Foundation Layer — Planning Summary

**Status:** Ready to execute
**Design doc:** `docs/plans/2026-04-10-ml-ai-foundations-design.md`
**Supersedes:** `.planning/phases/56-swarm-foundation/` (extended + renamed)

---

## Wave Structure

| Wave | Plans | Parallelism | Dependencies |
|------|-------|-------------|--------------|
| 1 | 56-01 (LLM infra), 56-06 (DB + Docker) | parallel | none |
| 2 | 56-03 (Protocol + FeatureVector), 56-04 (Metrics), 56-08 (ML core) | parallel | Wave 1 done |
| 3 | 56-02 (Narrative module), 56-05 (Narrative agent), 56-09 (Data Quality) | parallel | Wave 2 done |
| 4 | 56-07 (Swarm services), 56-10 (Discovery) | parallel | Wave 3 done |
| 5 | 56-11 (ML Orchestrator) | sequential | Wave 4 done |

Total: **11 plans**, 5 waves.

---

## Plan Index

| Plan | What it builds | Wave | Key deliverable |
|------|---------------|------|----------------|
| 56-01 | LLM Infrastructure | 1 | `src/core/llm/` package: `LLMProviderChain`, `SemanticCache`, `RateLimiter`, `TokenBudget`, `GuardrailsValidator` |
| 56-02 | Narrative Module | 3 | `src/intelligence/narrative/`: `prompts.py`, `parsers.py`, `NarrativeOrchestrator` |
| 56-03 | Protocol + FeatureVector | 2 | `SwarmContext`, `IAlphaContributor` fix, `FeatureVector`, 4 agents archived |
| 56-04 | Safety + Aggregator + Metrics | 2 | `SafeSwarmWrapper`, `SwarmAggregator`, `SwarmBaseAgent`, ML Prometheus metrics |
| 56-05 | Narrative Service Refactor | 3 | `ai_narrative_agent.py` (~200 lines) replaces 1,327-line monolith |
| 56-06 | DB + Stream Keys + Docker | 1 | 9 stream key functions, 3 DB migrations, MLflow + LangFuse Docker Compose |
| 56-07 | Swarm Services | 4 | `SwarmOrchestratorComputeAgent` + `SwarmWriterAgent` + systemd units |
| 56-08 | ML Core | 2 | `src/core/ml/`: `FeatureExtractor`, `ShadowRecorder`, `ModelRegistry`, `TrainingDataQuery` |
| 56-09 | Data Quality Agent | 3 | `MLDataQualityAuditorAgent` + Monday 05:00 systemd timer |
| 56-10 | Discovery Infrastructure | 4 | `MLDiscoveryComputeAgent` + tsfresh + IC analysis + Monday 06:00 timer |
| 56-11 | ML Orchestrator | 5 | `MLOrchestratorComputeAgent` LangGraph pipeline + Monday 04:00 timer |

---

## New Infrastructure (DB Tables)

| Table | Created by | Purpose |
|-------|-----------|---------|
| `alpha_multiplier_shadow` | 56-06 migration 058 | Shadow multiplier predictions for Pearson validation |
| `ml_models` | 56-06 migration 059 | Model registry — routes inference to MLflow artifacts |
| `ml_discovery_runs` | 56-06 migration 060 | Weekly tsfresh + IC analysis results |

---

## New Docker Services

| Service | Port | Purpose |
|---------|------|---------|
| MLflow | :5000 | ML experiment tracking + artifact store |
| LangFuse | :3000 | LLM observability — traces, latency, token spend |

---

## New systemd Units

| Unit | Trigger | Purpose |
|------|---------|---------|
| `indicagent-ml-orchestrator.timer` | Monday 04:00 UTC | LangGraph pipeline kick-off |
| `indicagent-ml-data-quality.timer` | Monday 05:00 UTC | Training data quality gate |
| `indicagent-ml-discovery.timer` | Monday 06:00 UTC | tsfresh + IC feature discovery |
| `indicagent-swarm-orchestrator.service` | always-on | Swarm signal processing |
| `indicagent-swarm-writer.service` | always-on | Shadow prediction persistence |

---

## Prometheus Metrics Added

| Metric | Added in |
|--------|---------|
| `llm_call_duration_seconds` | 56-01 |
| `llm_tokens_used_total` | 56-01 |
| `llm_cache_hit_total` | 56-01 |
| `llm_guardrails_rejections_total` | 56-01 |
| `llm_rate_limit_wait_seconds` | 56-01 |
| `swarm_signals_processed_total` | 56-04 |
| `swarm_agent_latency_seconds` | 56-04 |
| `swarm_agent_errors_total` | 56-04 |
| `shadow_predictions_total` | 56-04 |
| `agent_inference_latency_seconds` | 56-04 |
| `feature_ic_score` | 56-04 |
| `data_quality_score` | 56-04 |
| `ml_discovery_features_extracted` | 56-04 |

---

## Execution Order

```bash
# Wave 1 (parallel)
/gsd-execute-phase 56 --plans 56-01,56-06

# Wave 2 (parallel, after wave 1)
/gsd-execute-phase 56 --plans 56-03,56-04,56-08

# Wave 3 (parallel, after wave 2)
/gsd-execute-phase 56 --plans 56-02,56-05,56-09

# Wave 4 (parallel, after wave 3)
/gsd-execute-phase 56 --plans 56-07,56-10

# Wave 5 (sequential, after wave 4)
/gsd-execute-phase 56 --plans 56-11
```

Or simply: `/gsd-execute-phase 56` (executor reads wave dependencies from plan frontmatter).
