# AI/ML Tech Stack — Consolidated Reference

**Purpose:** Single reference for all AI/ML technology choices. What we use, why we chose it, how it fits together.
**Last Updated:** 2026-04-21
**Status:** Living document — reflects current v2.4 state + v2.3 ML Foundation plans

**Deep dives:**
- Agent system: `../ideas/ml-agent-architecture.md` — Multi-agent learning machine design
- Validation: `../ideas/renaissance-alpha-pipeline.md` — Shadow-first statistical gates
- Platform stack: `../ideas/tech-stack.md` — Full infrastructure decisions

---

## 1. Executive Summary

**Our AI/ML philosophy:** Renaissance-grade rigor, simplest tool that works, statistical proof over intuition.

**Core principles:**
- **Show Me the Data** — No model acts on capital until p < 0.05, ρ > 0.4
- **Shadow-First Validation** — 14-day correlation gate before production
- **Tabular > Deep Learning** — Gradient boosting wins on our data type
- **Research/Production Separation** — LLMs offline-only, deterministic code in hot path
- **Self-Hosted Everything** — No vendor lock-in, no cloud ML services

---

## 2. What We Use (Organized by Layer)

### 2.1 Observability (Active — All Installed)

| Tool | Purpose | Notes |
|------|---------|-------|
| **OpenTelemetry** | Distributed tracing | `opentelemetry-api/sdk/exporter-otlp-proto-http` v1.41.0 — wired into `BaseAgent` via `src/observability/otel.py`; every agent gets a tracer; exports to OTLP endpoint (`OTEL_EXPORTER_OTLP_ENDPOINT`, default `localhost:4318`) |
| **Prometheus** | Metrics collection | `prometheus-client` v0.25.0 — per-service exporters on ports :9113–:9130; registry helper in `src/observability/metrics.py` prevents duplicate registration |
| **structlog** | Structured logging | v25.5.0 — all service logs → `logs/<service>.log` via `setup_service_logging()`; JSON-structured with `timestamp`, `service`, `symbol`, `timeframe`, `level` fields |

**OTel wiring:** `BaseAgent.__init__` calls `get_tracer(name)` and `init_tracing()` is called at `run()` time. Signal metrics agents (`signal_metrics_compute_agent`, `signal_metrics_writer_agent`) explicitly call `init_tracing()` at startup. OTel traces are no-op when no endpoint is configured — safe to deploy without a collector.

### 2.2 LLM Stack (Active — I8 Narrative + Research)

**Provider chain** (`src/core/llm/`):

| Component | Purpose | Notes |
|-----------|---------|-------|
| **OpenRouter** | Cloud LLM aggregation | Primary tier — 100+ models via single API; default model roster in `settings.openrouter_models`; env: `OPENROUTER_API_KEY`, `OPENROUTER_MODELS` |
| **Ollama** | Local LLM inference | Offline fallback — always available; default model `gemma4:e4b`; env: `OLLAMA_BASE_URL`, `OLLAMA_MODEL` |
| **LangGraph** | Agent orchestration | `langgraph>=1.0.0` (v1.1.6 installed) — Supervisor + domain agents; state machines for ML swarm (Phase 56+) |
| **LangFuse** | Agent observability | Configured in `Settings.LANGFUSE_HOST` (`localhost:3010`); NOT yet wired — no `langfuse` pip package installed. To be connected when swarm agents reach stable state. |

**Custom LLM middleware** (all in `src/core/llm/`, no pip deps):

| Component | File | Purpose |
|-----------|------|---------|
| `LLMProviderChain` | `chain.py` | High-level facade: SemanticCache → RateLimiter → TokenBudget → LLMChain → GuardrailsValidator |
| `SemanticCache` | `semantic_cache.py` | LRU + TTL cache for LLM responses; key = SHA-256(system + prompt[:200] + model); max 500 entries |
| `RateLimiter` | `rate_limiter.py` | Per-provider RPM/TPM rate limiting; configurable via `settings.LLM_RATE_LIMITS` |
| `TokenBudget` | `token_budget.py` | Daily token budget enforcement; routes to Ollama-only when cloud budget exceeded |
| `GuardrailsValidator` | `guardrails.py` | Pydantic-based schema validation of LLM responses — custom impl, NOT the `guardrails-ai` pip package |

**Key decision:** No `guardrails-ai` pip dependency — custom Pydantic validator in `src/core/llm/guardrails.py` gives the same output schema enforcement without the heavy dependency chain.

### 2.3 Models & Algorithms (Planned — ML Foundation v2.3)

These tools are **planned for Phase 64+ (ML Foundation)** — not yet installed.

| Tool | Purpose | Why | Status |
|------|---------|-----|--------|
| **LightGBM** `>=4.6.0` | Production ML model | Dominates tabular benchmarks; DART mode for correlated features; fast on 50k-200k rows | Planned Phase 64+ |
| **XGBoost** `>=3.2.0` | Shadow challenger | Level-wise growth more stable for small per-regime N; run as A/B baseline | Planned Phase 64+ |
| **scikit-learn** `>=1.5.0` | Preprocessing, CV | Already installed — isotonic regression, logistic regression in use for calibration | ✅ Installed |
| **optuna** `>=4.3.0` | Bayesian hyperparameter search | TPE sampler + LightGBMTuner integration; run at model init, not every retrain | Planned Phase 64+ |

**Key decision:** LightGBM over PyTorch/TF. Our data is tabular time-series features — tree ensembles dominate tabular benchmarks. PyTorch only if we add unstructured data (news text, options surface).

### 2.4 Statistics & Validation

| Tool | Purpose | Status |
|------|---------|--------|
| **scipy.stats** | Pearson r, p-values, ADF | ✅ Installed (v1.17.1) — promotion gate foundation |
| **statsmodels** `>=0.14.4` | Stationarity tests, CUSUM, OLS | ✅ Installed — ADF stationarity + promotion gate p-values |
| **SHAP** `>=0.51.0` | Per-signal feature attribution | Planned Phase 64+ — TreeExplainer for GBDT; top-5 SHAP features per signal to `signal_ledger` |
| **alphalens-reloaded** | IC/ICIR analysis | Planned — quant-standard metrics; prevents lookahead bugs |
| **evidently** | Drift detection (KS/PSI) | Planned — automated model degradation triggers |

**Key decision:** IC (Information Coefficient) over accuracy/AUC. Quant standard — measures predictive power per feature.

### 2.5 Feature Engineering

| Tool | Purpose | Status |
|------|---------|--------|
| **NumPy** `>=2.4.0` | Real-time inference arrays | ✅ Installed — <5ms SLA for per-signal predictions |
| **pandas** `>=3.0.0` | Batch data manipulation | ✅ Installed |
| **tsfresh** `==0.21.1` | Auto feature extraction (700+ features) | ✅ Installed — ML discovery phase |
| **polars** | Batch data processing | Planned — 10-100× faster than pandas for feature matrix building at scale |

**Key decision:** NumPy for real-time inference (already in hot path), polars for batch training (weekly retraining at scale). NumPy arrays ARE tensors — no PyTorch overhead needed.

### 2.6 Signal Analysis Libraries (Installed — Available for Use)

These are installed in the venv but not yet wired into production code. Available for plugin development and research:

| Tool | Version | Purpose | When to Use |
|------|---------|---------|-------------|
| **stumpy** | 1.14.1 | Matrix Profile — time-series motif discovery | Pattern matching in I5; anomaly detection; find recurring microstructure patterns |
| **numba** | 0.65.0 | JIT compilation for NumPy-heavy loops | Hot-path plugins where vectorization isn't enough; compile inner loops that process all symbols |
| **PyWavelets (pywt)** | 1.9.0 | Wavelet transforms for signal decomposition | Multi-resolution analysis; denoising price series; regime transition detection |
| **empyrical-reloaded** | 0.5.12 | Performance metrics (Sharpe, Sortino, Calmar, max drawdown) | Signal performance reporting; setup_performance table stats; ML training evaluation |

**stumpy** is particularly relevant for I5/I7 pattern plugins — matrix profiles find shape-based matches across historical bars without manual rule authoring.

**empyrical-reloaded** is the natural fit for `setup_performance` stats and the ML scoring evaluation pipeline.

### 2.7 Infrastructure & Orchestration

| Tool | Purpose | Status |
|------|---------|--------|
| **MLflow** | Experiment tracking, model registry | Wired in `src/core/ml/registry.py` (lazy import); self-hosted at `localhost:5000`; configured via `MLFLOW_TRACKING_URI` — add `mlflow` to requirements.txt before Phase 64 |
| **LangGraph** | ML swarm orchestration | ✅ Installed v1.1.6 — Supervisor + domain agents; Phase 56 Swarm Foundation |

---

## 3. How It Fits Together

### 3.1 Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    ML Swarm (Phase 56+)                      │
│         LangGraph Supervisor → DataQuality → Discovery       │
│              → Training (LightGBM) → Monitoring             │
│         LangFuse observability (planned)                     │
└──────────────────┬──────────────────┬──────────────────────┘
                   │                  │
        ┌──────────┴───┐     ┌───────┴────────┐
        │   MLflow      │     │   evidently    │
        │  (registry)   │     │  (drift, plan) │
        └──────────────┘     └────────────────┘

┌─────────────────────────────────────────────────────────────┐
│             I8 LLM Layer (Active)                            │
│  LLMProviderChain: SemanticCache → RateLimiter →            │
│    TokenBudget → LLMChain (OpenRouter → Ollama) →           │
│    GuardrailsValidator                                      │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│           Observability Layer (Active)                       │
│  OTel traces (BaseAgent) + Prometheus metrics per service    │
│  + structlog JSON logs → logs/<service>.log                 │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Data Flow (ML Path)

```
TimescaleDB (intelligence_features + signal_ledger)
    ↓ JOIN on (symbol, feature_ts, feature_tf)
polars (feature matrix — planned)
    ↓
LightGBM (train per regime × setup × TF — planned)
    ↓
MLflow (log run, register model)
    ↓
Shadow Mode (shadow_ml_predictions table)
    ↓
14-Day Correlation Gate (scipy.stats.pearsonr + statsmodels ADF)
    ↓
Production (if ρ > 0.4, p < 0.05, N ≥ 100)
    ↓
NumPy (real-time inference <5ms)
    ↓
Signal Scoring (ml_win_prob → signal_ledger)
```

### 3.3 Shadow-First Lifecycle

Every alpha source (ML model, rule-based heuristic, LLM-derived pattern) follows:

1. **Shadow Mode** — Write predictions to shadow table, no production impact
2. **Correlation Analysis** — Daily job: `Pearson(predictions, realized_pnl_r)`
3. **Promotion** — Auto-promote if ρ > 0.4, N ≥ 100, p < 0.05
4. **Production** — Multipliers feed into signal scoring
5. **Continuous Monitoring** — Daily correlation checks continue
6. **Degradation** — Auto-disable if ρ < 0.2 for 7 consecutive days

**This applies to everything:** I1-I7 plugins, ML models, LLM-derived heuristics. No exceptions.

---

## 4. Why These Choices

### 4.1 OpenTelemetry Over Custom Tracing

OTel is the CNCF standard for distributed tracing. It gives us:
- Vendor-neutral traces exportable to Jaeger, Tempo, or any OTLP collector
- No-op behavior when no endpoint is configured — zero overhead in development
- Standard span/trace context propagation across async boundaries

### 4.2 Custom LLM Middleware Over guardrails-ai

`guardrails-ai` is a heavy dependency with its own validator ecosystem. Our needs are simpler: validate that LLM JSON output matches a Pydantic schema. The custom `GuardrailsValidator` in `src/core/llm/guardrails.py` does this with zero external dependencies.

### 4.3 LightGBM Over PyTorch/TF (Planned)

| Aspect | LightGBM | PyTorch/TF |
|--------|----------|------------|
| Tabular benchmarks | Wins 95% of time | Loses |
| Training time | Minutes | Hours-days |
| Explainability | SHAP (exact) | Black box |
| Categorical support | Native | Requires encoding |
| Overfitting risk | Lower | Higher (noisy data) |
| Compute | CPU sufficient | GPU required |

**When we'd add PyTorch:** Unstructured data (news sentiment, options chain surface).

### 4.4 Self-Hosted Over Cloud

| Tool | Self-Hosted | Cloud Alternative |
|------|-------------|-------------------|
| MLflow | MLflow (Docker) | Weights & Biases ($$) |
| LangFuse | LangFuse (Docker, planned) | LangSmith ($$$) |
| Ollama | Local LLM | OpenAI API ($$) |

---

## 5. What We Don't Use (And Why)

| Technology | Why Not | When We'd Reconsider |
|------------|---------|---------------------|
| **PyTorch/TensorFlow** | Overkill for tabular; gradient boosting wins | Unstructured data added (news, options) |
| **Ray/Dask** | Overkill for current scale (<1M rows) | Data volume >10M rows or training >4h |
| **Feast** | TimescaleDB IS our feature store | Multi-service feature sharing (swarm agents) |
| **Temporal** | LangGraph sufficient | Multi-day workflows requiring restart persistence |
| **Weights & Biases** | Cloud, paid; MLflow is open-source | Never — self-hosted principle |
| **guardrails-ai** | Custom Pydantic validator suffices | If we need Rail specs or complex multi-step validation |
| **river** | Online learning overkill | N > 500k rows with strong non-stationarity |

---

## 6. Quick Reference (Tool List)

**Active — Observability:**
- OpenTelemetry (traces), Prometheus (metrics), structlog (logs)

**Active — LLM Stack:**
- OpenRouter (cloud), Ollama (local), LangGraph (orchestration)
- Custom: LLMProviderChain, SemanticCache, RateLimiter, TokenBudget, GuardrailsValidator

**Active — Statistics/ML Utilities:**
- scipy.stats, statsmodels, scikit-learn, tsfresh, NumPy, pandas

**Installed — Available but not yet wired:**
- stumpy (matrix profiles), numba (JIT), PyWavelets (wavelet transforms), empyrical-reloaded (performance metrics)

**Planned — ML Foundation (Phase 64+):**
- LightGBM, XGBoost, SHAP, optuna, polars, alphalens-reloaded, evidently

**Planned — Observability Wiring:**
- LangFuse (self-hosted, configured but not yet imported)
- MLflow (lazy import exists in registry.py — add to requirements.txt before Phase 64)

---

## 7. Integration Points

### 7.1 Promotion Gate (Active)
- `scipy.stats.pearsonr` — Correlation coefficient + p-value
- `statsmodels.tsa.stattools.adfuller` — Stationarity check before training
- `asyncpg` — Query shadow table, compute stats in SQL where possible
- Daily cron job — Automated correlation checks

### 7.2 ML Scoring Model (Phase 64+)
- `polars.DataFrame` — Build feature matrix from `intelligence_features`
- `lightgbm.train()` — Fit per-regime × per-setup × per-TF models
- `shap.TreeExplainer` — Compute feature attributions; top-5 to `signal_ledger.ml_top_features`
- `optuna` — Hyperparameter search at model init + major regime shifts
- MLflow model registry — Version and track all trained models

### 7.3 Discovery Pipeline (Phase 64+)
- `tsfresh.extract_features()` — Auto-generate candidate features
- `alphalens-reloaded` — Compute IC/ICIR per feature candidate
- `evidently.DriftDetector` — Catch distribution shifts before model corruption

### 7.4 Plugin Research (Available Now)
- `stumpy.stump()` — Matrix profile for bar pattern matching
- `numba.njit` — JIT-compile NumPy inner loops in CPU-bound plugins
- `pywt.wavedec()` — Wavelet decomposition for regime transition signals
- `empyrical.sharpe_ratio()` / `empyrical.max_drawdown()` — Signal performance stats

---

## 8. Performance Boundaries

| Scale | Tool | Performance |
|-------|------|-------------|
| Single signal (<5ms) | NumPy + LightGBM (planned) | Real-time inference |
| 100K rows (<5 min) | polars + LightGBM (planned) | Weekly retraining |
| 1M rows (<30 min) | polars + LightGBM (planned) | Full historical backfill |
| 10M rows | Consider Ray/Dask | Future multi-product scale |

---

## 9. Decision Log

| Date | Tool | Decision | Rationale |
|------|------|----------|-----------|
| 2026-04-21 | stumpy/numba/PyWavelets/empyrical | Installed, not yet wired | Available for plugin dev and research; no wiring risk |
| 2026-04-21 | guardrails-ai | Replaced by custom impl | No pip dep needed; Pydantic validator suffices |
| 2026-04-21 | LangFuse | Configured, not yet wired | Self-hosted plan stands; connect when swarm stable |
| 2026-04-21 | OTel | Added to docs | Already active in BaseAgent + signal metrics agents |
| 2026-03-24 | LightGBM | Chosen (planned) | Dominates tabular benchmarks |
| 2026-03-24 | PyTorch/TF | Rejected | Overkill for our data type |
| 2026-03-24 | MLflow | Chosen | Self-hosted experiment tracking |
| 2026-03-15 | optuna | Chosen (planned) | Bayesian optimization |
| 2026-03-15 | alphalens-reloaded | Chosen (planned) | Quant-standard IC/ICIR |
| 2026-03-15 | tsfresh | Chosen | Auto feature extraction |

---

## 10. Related Documentation

**Core architecture:**
- `ai-intelligence-architecture.md` — Full I1-I8 pipeline architecture
- `ai-intelligence-resources.md` — LLM provider chain usage patterns
- `../architecture/current-state.md` — Active services, data flow, performance

**Deep dives:**
- `../ideas/ml-agent-architecture.md` — Multi-agent learning machine design
- `../ideas/renaissance-alpha-pipeline.md` — Validation framework (shadow-first gates)
- `../ideas/tech-stack.md` — Full platform stack (Redpanda, TimescaleDB, etc.)
- `.planning/research/ML-SCORING.md` — LightGBM/XGBoost decision + training architecture

---

## 11. How to Update This Document

When adding/removing tools:

1. Update section 2 with new tool + status (Active / Installed / Planned)
2. Add decision to section 9 (Decision Log) with date and rationale
3. Cross-reference `.planning/research/` if an analysis doc exists
4. Commit with: `docs: add/remove/update [tool] in AI tech stack`

**Before adding:**
- Verify it's not already covered by an installed library
- Check Renaissance alignment — simplest tool, proven, minimal
- Document "Why not [existing tool]?"
- Mark status clearly: Active (wired), Installed (available), or Planned (not yet installed)

---

**Version:** 2.0.0
**Last Updated:** 2026-04-21
**Milestone:** v2.4 Observability Hardening / v2.3 ML Foundation (planned)
