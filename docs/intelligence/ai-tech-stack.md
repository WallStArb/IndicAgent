# AI/ML Tech Stack — Consolidated Reference

**Purpose:** Single reference for all AI/ML technology choices. What we use, why we chose it, how it fits together.
**Last Updated:** 2026-03-24
**Status:** Living document — reflects current v2.3 ML Foundation plans

**Deep dives:**
- Tool analysis: `ml-ai-palette.md` — Detailed strengths/weaknesses for each tool
- Agent system: `ml-agent-architecture.md` — Multi-agent learning machine design
- Validation: `renaissance-alpha-pipeline.md` — Shadow-first statistical gates
- Platform stack: `tech-stack.md` — Full infrastructure decisions

---

## 1. Executive Summary

**Our AI/ML philosophy:** Renaissance-grade rigor, simplest tool that works, statistical proof over intuition.

**Core principles:**
- **Show Me the Data** — No model acts on capital until p < 0.05, ρ > 0.4
- **Shadow-First Validation** — 14-day correlation gate before production
- **Tabular > Deep Learning** — Gradient boosting wins on our data type
- **Research/Production Separation** — LLMs offline-only, deterministic code in hot path
- **Self-Hosted Everything** — No vendor lock-in, no cloud ML services

**What this gives us:**
- Validated alpha contributors (ML models, rules, heuristics) — all must earn the right
- Automated governance — CI/CD promotes/demotes based on correlation, not committees
- Explainable predictions — SHAP values per signal, full audit trail
- Fast iteration — Weekly retraining, drift detection, continuous adaptation

---

## 2. What We Use (Organized by Layer)

### 2.1 Models & Algorithms

| Tool | Purpose | Why |
|------|---------|-----|
| **LightGBM** | Production ML model | Dominates tabular benchmarks; fast; handles categoricals natively |
| **Random Forest** | Feature discovery | `feature_importances_` tells us what matters; not production |
| **scikit-learn** | Preprocessing, CV, feature selection | Already in stack for CISScorer |
| **statsmodels** | Stationarity tests, CUSUM | Ensures features aren't spurious; time-series aware |

**Key decision:** Gradient boosting (LightGBM) over deep learning (PyTorch/TF). Our data is tabular time-series features (RSI, ATR, regime), not images/text. Tree ensembles dominate tabular benchmarks.

### 2.2 Statistics & Validation

| Tool | Purpose | Why |
|------|---------|-----|
| **scipy.stats** | Pearson r, p-values | Phase 2 validator foundation; correlation gates |
| **alphalens-reloaded** | IC/ICIR analysis | Quant-standard metrics; prevents lookahead bugs |
| **evidently** | Drift detection (KS/PSI/Wasserstein) | Automated degradation triggers |
| **SHAP** | Per-signal attribution | "Why was this signal boosted?" — audit trail |

**Key decision:** IC (Information Coefficient) over accuracy/AUC. Quant standard — measures predictive power per feature. Prevents overfitting to noise.

### 2.3 Feature Engineering

| Tool | Purpose | Why |
|------|---------|-----|
| **tsfresh** | Auto feature extraction (700+ features) | "Let data speak" vs hand-engineering |
| **polars** | Batch data processing | 10-100× faster than pandas; weekly retraining |
| **NumPy** | Real-time inference | <5ms SLA for single-signal predictions |

**Key decision:** Polars for batch (feature matrix building), NumPy for real-time (per-bar inference). Don't mix them — choose one and stay there.

### 2.4 Infrastructure & Orchestration

| Tool | Purpose | Why |
|------|---------|-----|
| **MLflow** (self-hosted) | Experiment tracking, model registry | Version every model; compare 20 runs; full reproducibility |
| **optuna** | Bayesian hyperparameter optimization | Auto-tune; no manual grid search |
| **LangGraph** | Agent orchestration | Supervisor + domain agents; state machines |
| **LangFuse** (self-hosted) | Agent observability | Traces every agent step; LLM call tracking |

**Key decision:** Self-hosted over cloud SaaS. MLflow over Weights & Biases, LangFuse over LangSmith. Full data ownership, no vendor lock-in.

### 2.5 LLM Stack (Research-Only)

| Tool | Purpose | Why |
|------|---------|-----|
| **Ollama** | Local LLM inference | Offline fallback; qwen3.5:9b on iGPU |
| **OpenRouter** | Cloud LLM aggregation | 100+ models; free tier available |
| **guardrails-ai** | LLM output validation | Pydantic enforcement; prevents hallucinations |

**Key decision:** LLMs are **research-only** (Beta pipeline). No LLM calls in production hot path. They discover patterns offline → compiled to deterministic code.

---

## 3. How It Fits Together

### 3.1 Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    MLAgent Orchestrator                      │
│            (LangGraph Supervisor — Deterministic)              │
│  Reads: drift scores, model status, discovery schedule       │
│  Routes to: domain agents in sequence or parallel            │
└──────────────────┬──────────────────┬──────────────────────┘
                   │                  │
        ┌──────────┴───┐     ┌───────┴────────┐
        │  Data Quality │     │   Discovery    │
        │    Agent      │     │   Agent (LLM)  │
        └───────────────┘     └────────────────┘
                   │                  │
        ┌──────────┴───────────────┴────────┐
        │        Training Agent         │
        │   (Deterministic — LightGBM)    │
        └──────────┬──────────────────────┘
                   │
        ┌──────────┴──────────────┐
        │    Monitoring Agent     │
        │  (Drift — evidently)     │
        └─────────────────────────┘
```

**Agent responsibilities:**
- **Data Quality Agent** — Validates training data (no CIS nulls, no gaps)
- **Discovery Agent (LLM)** — Finds patterns via tsfresh/alphalens
- **Training Agent** — Builds LightGBM models per regime × setup × TF
- **Monitoring Agent** — Drift detection → auto-retrain
- **Narrative Agent (LLM)** — Explains what changed in plain English

### 3.2 Data Flow

```
TimescaleDB (intelligence_features)
    ↓
Polars (feature matrix builder)
    ↓
LightGBM (train model)
    ↓
MLflow (log run, register model)
    ↓
Shadow Mode (write predictions to shadow_ml_predictions)
    ↓
14-Day Correlation Gate (scipy.stats.pearsonr)
    ↓
Production (if ρ > 0.4, p < 0.05, N ≥ 100)
    ↓
NumPy (real-time inference <5ms)
    ↓
Signal Scoring (ml_win_prob → signal_ledger)
```

### 3.3 Shadow-First Lifecycle

**Every alpha source** (ML model, rule-based heuristic, LLM-derived pattern) follows:

1. **Shadow Mode** — Write predictions to shadow table, no production impact
2. **Correlation Analysis** — Daily job: `Pearson(predictions, realized_pnl_r)`
3. **Promotion** — Auto-promote if ρ > 0.4, N ≥ 100, p < 0.05
4. **Production** — Multipliers feed into SignalLifecycleService
5. **Continuous Monitoring** — Daily correlation checks continue
6. **Degradation** — Auto-disable if ρ < 0.2 for 7 consecutive days

**This applies to everything:** I1-I7 plugins, ML models, LLM-derived heuristics. No exceptions.

---

## 4. Why These Choices

### 4.1 LightGBM Over PyTorch/TF

**Our data:** Tabular time-series features (RSI, ATR, regime) — structured rows/columns
**Their data:** Images, text, audio — unstructured, hierarchical

| Aspect | LightGBM | PyTorch/TF |
|--------|----------|------------|
| Tabular benchmarks | Wins 95% of time | Loses |
| Training time | Minutes | Hours-days |
| Explainability | SHAP (exact) | Black box |
| Categorical support | Native | Requires encoding |
| Overfitting risk | Lower | Higher (noisy data) |
| Compute | CPU sufficient | GPU required |

**When we'd add PyTorch:** Unstructured data (news sentiment → NLP, options chain surface → CNN)

### 4.2 Polars Over Pandas

| Operation | Polars | Pandas |
|------------|--------|--------|
| Join 100K rows | 2 sec | 30 sec |
| Groupby aggregation | 1 sec | 15 sec |
| Memory | Lower | Higher |
| Ecosystem | Smaller | Larger |

**Use case:** Feature matrix building for weekly retraining (must complete in <30 min)

### 4.3 Self-Hosted Over Cloud

| Tool | Self-Hosted | Cloud Alternative |
|------|-------------|-------------------|
| MLflow | MLflow (Docker) | Weights & Biases ($$) |
| LangFuse | LangFuse (Docker) | LangSmith ($$$) |
| Ollama | Local LLM | OpenAI API ($$) |

**Renaissance principle:** No vendor lock-in on intelligence data. Full ownership.

---

## 5. What We Don't Use (And Why)

| Technology | Why Not | Renaissance Principle |
|------------|---------|----------------------|
| **PyTorch/TensorFlow** | Overkill for tabular; gradient boosting wins | Simplest tool that works |
| **Ray/Dask** | Overkill for current scale (<1M rows) | Add when triggered |
| **Feast** | TimescaleDB IS our feature store | Consolidate before expanding |
| **Temporal** | LangGraph sufficient; institutional-scale only | Add when trigger is real |
| **Weights & Biases** | Cloud, paid; MLflow is open-source | No vendor lock-in |

**When we'd reconsider:**
- **PyTorch/TF** — Unstructured data added (news text, options images)
- **Ray/Dask** — Data volume exceeds 10M rows or training time >4 hours
- **Feast** — Multi-service sharing features (QualAgent + DerivAgent + TradeAgent)
- **Temporal** — Multi-day workflows requiring state persistence across restarts

---

## 6. Quick Reference (Tool List)

**Models:**
- LightGBM (production), Random Forest (discovery), scikit-learn (utilities)

**Statistics:**
- scipy.stats (correlation), statsmodels (stationarity/CUSUM), alphalens-reloaded (IC/ICIR)

**Features:**
- tsfresh (auto-extraction), SHAP (attribution), polars (batch), NumPy (real-time)

**Infrastructure:**
- MLflow (experiments), optuna (tuning), LangGraph (orchestration), LangFuse (observability)

**LLMs (research-only):**
- Ollama (local), OpenRouter (cloud), guardrails-ai (validation)

**Full analysis:** See `ml-ai-palette.md` for strengths/weaknesses, why chosen, when to reconsider.

---

## 7. Integration Points

### 7.1 Phase 2 (The Validator)
- `scipy.stats.pearsonr` — Correlation coefficient, p-value
- `asyncpg` — Query shadow table, compute stats in SQL where possible
- Daily cron job — Automated correlation checks

### 7.2 Phase 54 (ML Scoring Model)
- `polars.DataFrame` — Build feature matrix from `intelligence_features`
- `lightgbm.train()` — Fit per-regime × per-setup × per-TF models
- `shap.TreeExplainer` — Compute feature attributions
- MLflow model registry — Version and track all trained models

### 7.3 Beta Pipeline (Discovery)
- `tsfresh.extract_features()` — Auto-generate candidate features
- `alphalens-reloaded` — Compute IC/ICIR per feature
- `evidently.DriftDetector` — Catch distribution shifts before corruption

---

## 8. Performance Boundaries

**What scales where:**

| Scale | Tool | Performance |
|-------|------|-------------|
| Single signal (<5ms) | NumPy + LightGBM | Real-time inference |
| 100K rows (<5 min) | Polars + LightGBM | Weekly retraining |
| 1M rows (<30 min) | Polars + LightGBM | Full historical backfill |
| 10M rows | Consider Ray/Dask | Future multi-product scale |

**When to optimize:**
- Weekly retrain >30 min → Optimize feature extraction
- Inference >5ms → Switch to C++/Rust (Rust modules)
- Drift detection slow → Sample features, don't check all 85

---

## 9. Decision Log

| Date | Tool | Decision | Rationale |
|------|------|----------|-----------|
| 2026-03-24 | LightGBM | Chosen | Dominates tabular benchmarks |
| 2026-03-24 | PyTorch/TF | Rejected | Overkill for our data type |
| 2026-03-24 | polars | Chosen | 10-100× faster than pandas |
| 2026-03-24 | MLflow | Chosen | Self-hosted; experiment tracking |
| 2026-03-15 | optuna | Chosen | Bayesian optimization |
| 2026-03-15 | alphalens-reloaded | Chosen | Quant-standard IC/ICIR |
| 2026-03-15 | tsfresh | Chosen | Auto feature extraction |

---

## 10. Related Documentation

**Core architecture:**
- `../architecture/principles.md` — Foundational principles (plugin-native, event-driven, hot path isolation)
- `../architecture/plugin-native-architecture-explained.md` — How the plugin system works
- `ai-intelligence-resources.md` — I8 LLM layer details

**Deep dives:**
- `../ideas/ml-ai-palette.md` — Tool analysis (strengths/weaknesses, why chosen)
- `../ideas/ml-agent-architecture.md` — Multi-agent learning machine design
- `../ideas/renaissance-alpha-pipeline.md` — Validation framework (shadow-first gates)
- `../ideas/tech-stack.md` — Full platform stack (Redpanda, TimescaleDB, etc.)

**Research:**
- `../ideas/ml-classification-pattern-recognition.md` — Random Forest/KNN/SVM exploration
- `../ideas/intelligence-stack-latency-reduction.md` — Performance optimization

---

## 11. How to Update This Document

When adding/removing tools:

1. Update section 2 (What We Use) with new tool
2. Add decision to section 9 (Decision Log)
3. Cross-reference detailed docs if exists
4. Commit with message: `docs: add/remove/update [tool] in AI tech stack`

**Before adding:**
- Check `ml-ai-palette.md` — if analysis exists, reference it
- Verify Renaissance alignment — simplest tool, proven, minimal
- Document "Why not [existing tool]?"

---

**Version:** 1.0.0
**Last Updated:** 2026-03-24
**Milestone:** v2.3 ML Foundation
