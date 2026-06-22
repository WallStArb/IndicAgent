# MLAgent — Renaissance-Style Learning Machine

**Version:** 1.0
**Status:** under-review
**Priority:** high
**Milestone:** v1.9+
**Last Updated:** 2026-05-02
**Tags:** ml, agents, learning-machine, shadow-governance, drift-detection, signal-scoring, renaissance

---

**See also:** `docs/ideas/ai-03-evolvable-ai-agents.md` — Long-horizon extension of this architecture: agents that evolve via Darwinian selection across prompts, weights, config, and code. The eAI doc describes the fitness function, lifecycle (birth → shadow → breeding → promotion → gene bank), and governance model.

---

## Philosophy

This isn't a model — it's a **learning machine**. Three compounding layers:

```
Layer 1: Discovery         — what does the data actually say?
Layer 2: Scoring           — real-time signal quality prediction
Layer 3: Feedback Loop     — outcomes improve the next prediction
```

Each layer is independently valuable and ships incrementally. The system never stops learning — drift detection triggers retraining, shadow mode gates promotion, every outcome makes the next prediction better.

**Renaissance principles applied:**
- Segment relentlessly — per-regime × per-setup × per-TF sub-models beat a global model
- Shadow mode before production — no model acts on signals until p < 0.05
- Drift detection is non-negotiable — KS + CUSUM, auto-retrain on drift
- IC over accuracy — information coefficient per feature vs outcomes, not just win rate
- Data quality gates model quality — fix CIS backfill and constituent_contributions first
- The feedback loop IS the edge — outcomes → retrain → better predictions → compounds
- Earn the right through proof — every model decision is statistically justified and audited

**What it replaces over time:** hand-tuned CIS weights → IC-derived weights → full ensemble. CIS doesn't die — it becomes the interpretable linear component of a two-stage filter.

**What it never does:** override risk management (AegisAgent), trade autonomously (TradeAgent). MLAgent is signal intelligence only.

---

## Multi-Agent Architecture

A **Supervisor/Orchestrator** coordinates domain-specific agents, each expert in their own toolset. The Orchestrator understands system state and routes work. Domain agents are independently testable, replaceable, and observable.

Shared cold and warm storage is acceptable for training data and artifacts, but runtime independence remains the rule. A storage outage should degrade capability, not collapse unrelated agents.

```
┌─────────────────────────────────────────────────────────────────┐
│  ML Orchestrator (LangGraph Supervisor)                         │
│  "What needs to happen next given current system state?"       │
│                                                                 │
│  Reads: drift scores, model status, discovery schedule,         │
│         data quality signals, shadow mode results               │
│  Routes to: domain agents in sequence or parallel               │
│  Decides: retrain Y/N, promote Y/N, escalate to human Y/N      │
│  Logic: deterministic rules — NOT LLM-driven                    │
└─────────────────────────────────────────────────────────────────┘
         │           │           │           │           │
         ▼           ▼           ▼           ▼           ▼
   ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────┐ ┌──────────┐
   │  Data    │ │Discovery │ │Training  │ │Monitor  │ │Narrative │
   │ Quality  │ │  Agent   │ │  Agent   │ │  Agent  │ │  Agent   │
   │          │ │ (LLM)    │ │  (det.)  │ │  (det.) │ │  (LLM)   │
   └──────────┘ └──────────┘ └──────────┘ └─────────┘ └──────────┘
```

**Key principle:** Only Discovery Agent and Narrative Agent use LLMs. Orchestrator, Training Agent, and Monitoring Agent are deterministic. Production decisions cannot be non-deterministic.

---

## Domain Agents

### Data Quality Agent
*"Is the training data trustworthy?"*

Tools:
- `check_cis_nulls()` — verify CIS fields populated in signal_ledger
- `validate_feature_coverage(symbol, tf, date_range)` — gaps in intelligence_features
- `check_forward_returns()` — signals with missing/null outcomes
- `flag_data_anomalies()` — outlier feature values, impossible values
- `compute_data_quality_score()` — aggregate score 0-1, gates Training Agent

Runs before any training. If quality score below threshold, Orchestrator halts and triggers HITL.

---

### Discovery Agent *(LLM-guided)*
*"What patterns exist in this data that we haven't found yet?"*

Tools:
- `extract_features_tsfresh(symbol, tf, window)` — 700+ auto-generated time series features
- `compute_ic(feature, forward_bars)` — information coefficient via alphalens-reloaded
- `regime_conditional_ic(feature, regime)` — IC split by HMM regime 0/1/2
- `cross_asset_lag_correlation(source, target, lag_bars)` — does ES predict NQ N bars later?
- `rank_features_by_ic()` — sorted feature importance table
- `test_hypothesis(hypothesis_text)` — LLM proposes, tools validate
- `write_discovery_report(findings)` — persists to ml_discovery_runs

LLM decides which hypotheses to test next based on prior findings. Runs weekly or on-demand. Discovery findings with suspiciously high IC (> 0.3) trigger HITL review — too good is a lookahead bug signal.

---

### Training Agent *(deterministic)*
*"Build and validate the best model for this segment."*

Tools:
- `build_feature_matrix(segment, date_range)` — reads intelligence_features → polars DataFrame
- `train_lightgbm(features, labels, segment)` — fits model with optuna hyperparameter search
- `cross_validate(model, folds)` — time-series aware CV, no lookahead
- `compute_significance(model)` — win rate vs baseline, p-value
- `save_model_artifact(model, metadata)` — versioned filesystem + ml_models table
- `enter_shadow_mode(model_id)` — status="shadow", scores signals without acting
- `revert_model(model_id)` — roll back to previous production model

No LLM. Pure deterministic execution. Segments: per HMM regime × per setup type × per timeframe. Meta-model combines sub-model outputs.

---

### Monitoring Agent *(event-driven, deterministic)*
*"Is anything drifting or degrading?"*

Tools:
- `evidently_drift_check(feature_set, reference_window)` — KS/PSI/Wasserstein per feature
- `model_performance_check(model_id, window)` — win rate, avg pnl_r vs historical baseline
- `cusum_check(metric, threshold)` — detect performance degradation trend
- `shadow_mode_evaluate(model_id)` — compare shadow predictions to outcomes, p-value
- `emit_drift_event(severity, details)` — writes to stream → wakes Orchestrator
- `check_circuit_breaker()` — has model performance crossed hard floor?

Runs continuously. Primary trigger for Orchestrator to act.

---

### Narrative Agent *(LLM)*
*"Explain what changed this week in plain English."*

Tools:
- `read_discovery_report(run_id)` — latest findings from Discovery Agent
- `read_model_performance(model_id)` — current model metrics
- `read_feature_ic_scores(top_n)` — what's driving predictions
- `read_drift_events(window)` — what changed in the data
- `write_dashboard_insight(summary)` — persists human-readable card to dashboard

No decisions. Only interpretation. Feeds the Phase 3 dashboard insight panel.

---

## Orchestrator Decision Logic

```python
# Deterministic state machine — no LLM
if not data_quality_agent.check() >= QUALITY_THRESHOLD:
    hitl.alert("Data quality failure — training halted", severity="high")
    halt()

if monitoring_agent.circuit_breaker_triggered():
    training_agent.revert_model()
    hitl.alert("Circuit breaker: model reverted to previous version", severity="critical")

if monitoring_agent.drift_detected():
    if retrain_count_today < MAX_RETRAINS_PER_DAY:
        training_agent.retrain(segment=drifted_segment)
    else:
        hitl.alert("Drift detected but retrain limit reached", severity="medium")

if training_agent.shadow_model.p_value < 0.05 and shadow_model.n >= MIN_SHADOW_N:
    if shadow_model.p_value < FAST_PROMOTE_THRESHOLD:  # very high confidence
        training_agent.promote()
        narrative_agent.write_promotion_summary()
    else:  # borderline — human reviews
        hitl.request_approval("Shadow model ready for promotion", model_id=shadow_model.id)

if schedule.is_weekly_discovery():
    discovery_agent.run()
    narrative_agent.write_discovery_summary()
```

---

## Guardrails

### Hard Limits (never bypassed)
- Never promote a model with p > 0.05 — statistical significance is non-negotiable
- Never retrain more than N times per 24 hours (prevents thrashing)
- Never act on discovery IC > 0.3 without human review (likely lookahead contamination)
- Never use training data with quality score below threshold
- Circuit breaker: if production model win rate drops > 15% from baseline, auto-revert

### Structural Guardrails (`guardrails-ai` + Pydantic)
- All LLM agent outputs validated against Pydantic schemas before persistence
- Discovery Agent: `hypothesis_text` must reference real feature names (validated against `feature_ic_scores`)
- Narrative Agent: output must be < 500 tokens, must cite specific metrics
- Tool inputs validated before execution — no agent can call a tool with invalid parameters

### Output Validation Pattern
```python
from guardrails import Guard
from pydantic import BaseModel

class DiscoveryFinding(BaseModel):
    feature_name: str       # must exist in feature_ic_scores
    ic_value: float         # must be -1 to 1
    regime: Optional[int]   # must be 0, 1, 2, or None
    hypothesis: str         # max 200 chars

guard = Guard.from_pydantic(DiscoveryFinding)
validated = guard.parse(llm_output)  # raises if invalid
```

---

## Human in the Loop (HITL)

### When the Orchestrator Pauses for Human Review

| Trigger | Severity | Default if No Response |
|---------|----------|----------------------|
| Data quality failure | High | Halt training |
| IC > 0.3 (possible lookahead) | High | Block discovery report |
| Borderline p-value (0.03-0.05) | Medium | Reject promotion |
| Circuit breaker triggered | Critical | Auto-revert, alert |
| First promotion of new segment | Medium | Block until approved |
| Retrain limit reached with drift | Medium | Log and wait |

### HITL Implementation
- **LangGraph `interrupt()`** — pauses the graph at decision point, serialises state
- **Notification** — writes to `ml_agent_hitl_queue` table → API endpoint → dashboard alert card
- **Dashboard approval UI** — human sees pending decision with full context (metrics, reason, model comparison)
- **Timeout policy** — if no response in 4 hours: default-safe action (reject promotion, maintain status quo)
- **Audit trail** — every HITL decision logged with approver, timestamp, reasoning

```python
# LangGraph HITL pattern
def check_promotion(state: MLState) -> Command:
    if state.shadow_model.p_value < FAST_PROMOTE_THRESHOLD:
        return Command(goto="promote")  # auto-promote high confidence
    else:
        # pause graph, wait for human
        human_decision = interrupt({
            "action": "approve_promotion",
            "model_id": state.shadow_model.id,
            "metrics": state.shadow_model.metrics,
            "reason": "Borderline p-value requires human review"
        })
        return Command(goto="promote" if human_decision["approved"] else "reject")
```

---

## Observability Stack

### LangFuse (Self-Hosted)
Agent-level observability. Every agent step, tool call, LLM invocation traced.
- Runs as Docker container alongside existing stack
- Native LangChain/LangGraph `CallbackHandler` integration
- Token costs, latency, success/failure per agent run
- Evaluation scoring — did the discovery agent find actionable insights?
- Zero code change: `graph.invoke(state, config={"callbacks": [langfuse_handler]})`

### OpenTelemetry Bridge
Already in stack. LangFuse → OTEL → Prometheus → Grafana pipeline:
- Agent trace spans flow into existing Grafana dashboards
- Unified view: service metrics + agent behavior in one place

### Prometheus Metrics (new counters)
```
ml_agent_runs_total{agent, status}
ml_model_promotions_total{segment}
ml_drift_events_total{severity}
ml_hitl_pending_count
ml_shadow_win_prob_vs_outcome  # calibration
ml_discovery_ic_top_feature    # highest IC found this week
```

### MLflow (Model Registry)
- Self-hosted, Docker
- Experiment tracking: compare 20 training runs, see which hyperparameters mattered
- Model registry: versioning, staging → production lifecycle
- Artifact storage: LightGBM models, feature importance, SHAP values
- Replaces hand-rolled `ml_models` filesystem approach with proper tooling

### Grafana Dashboards (Phase 3)
- Agent run history and success rates
- Feature IC rankings (updated weekly)
- Model calibration: predicted win_prob vs actual outcomes
- Drift event timeline
- HITL queue and decision history
- Shadow model performance vs production

---

## Agent Memory

Three tiers:

| Tier | Storage | What |
|------|---------|------|
| Short-term | LangGraph StateGraph | Current run state, agent handoffs |
| Long-term structured | TimescaleDB | ml_discovery_runs, feature_ic_scores, ml_models, decisions |
| Long-term semantic | pgvector (already planned) | Embedding past discovery findings — "have we tested this hypothesis before?" |

pgvector enables the Discovery Agent to recall: "we tested RSI acceleration vs regime 0 outcomes 3 months ago and got IC=0.12" — avoids rediscovering the same things.

---

## Inter-Agent Communication

**Within a run:** LangGraph shared `StateGraph` — typed state passed between nodes.

**Cross-service / async:** Redpanda event streams (migration complete as of 2026-03-14):

```
ml.discovery.completed      → Orchestrator wakes, routes to Training Agent
ml.drift.detected           → Orchestrator wakes, evaluates retrain
ml.model.shadow_ready       → Orchestrator begins shadow evaluation
ml.model.promoted           → signal_generator reloads CIS weights
ml.hitl.response            → Orchestrator resumes paused graph
```

---

## Technology Stack

### Core Agent Infrastructure
| Package | Purpose | When |
|---------|---------|------|
| `langgraph` | Agent orchestration, state machines | Already in stack |
| `langchain` | Tool definitions, LLM wrappers | Already in stack |
| `langfuse` | Self-hosted agent observability | Phase 1 |
| `guardrails-ai` | LLM output validation, schema enforcement | Phase 1 |
| `mlflow` | Model registry, experiment tracking | Phase 2 |

### ML / Statistics
| Package | Purpose | When |
|---------|---------|------|
| `scipy` | IC analysis, KS test, significance | Phase 1 |
| `alphalens-reloaded` | Quant-standard IC/factor analysis | Phase 1 |
| `evidently` | Drift detection, ML monitoring reports | Phase 1 |
| `tsfresh` | Auto time series feature extraction (700+ features) | Phase 1 |
| `lightgbm` | The model — tabular data champion | Phase 2 |
| `shap` | TreeSHAP explainability — why did the model score this signal? | Phase 2 |
| `optuna` | Hyperparameter optimisation | Phase 2 |
| `statsmodels` | CUSUM, time series stats | Phase 2 |
| `river` | Online/incremental learning — continuous adaptation | Phase 3 |

### Performance
| Package | Purpose | When |
|---------|---------|------|
| `polars` | Rust-based dataframes, 10-100× faster than pandas for batch | Phase 1 |

### Already in Stack (no additions needed)
`scikit-learn`, `pandas`, `numpy`, `pyarrow`, `pydantic`, `opentelemetry-*`, `prometheus-client`, `pgvector` (planned)

---

## requirements.txt Additions

**Phase 1:**
```
# Agent infrastructure
langfuse>=2.0.0
guardrails-ai>=0.5.0

# Discovery + observability
scipy>=1.14.0
alphalens-reloaded>=0.4.0
evidently>=0.4.0
tsfresh>=0.21.0
polars>=1.0.0
mlflow>=2.15.0
```

**Phase 2:**
```
lightgbm>=4.5.0
shap>=0.46.0
optuna>=4.0.0
statsmodels>=0.14.0
```

**Phase 3:**
```
river>=0.21.0
```

---

## Phasing

### Phase 1 — Discovery Engine + Adaptive CIS *(buildable now)*
- Data Quality Agent + Discovery Agent + Narrative Agent
- IC analysis, tsfresh feature extraction, alphalens factor evaluation
- Adaptive CIS: weights updated from IC scores weekly (no more hand-tuning)
- LangFuse + guardrails wired from day one
- HITL alerts via dashboard for anomalous findings

### Phase 2 — Segmented Ensemble + Scoring Service *(60-90 days outcome volume)*
- Training Agent + Monitoring Agent fully operational
- LightGBM ensemble: per-regime × per-setup × per-TF
- Shadow mode gate with p < 0.05 promotion
- Evidently drift detection → auto-retrain loop
- MLflow model registry
- ml_scoring_service: reads signals:* stream, writes win_prob to signal_ledger
- Rerunability: `backfill_ml_scores(model_version, date_range)`

### Phase 3 — Dashboard + Autonomous Loop *(after Phase 2 proven)*
- Full Grafana ML dashboard panels
- Drift → retrain → shadow → promote with no human required (except circuit breaker)
- River online learning: model adapts continuously between retrains
- pgvector memory: Discovery Agent recalls past hypotheses
- Discovery insight cards on main dashboard

---

## New Database Tables

```sql
-- Versioned model artifacts
ml_models (
  model_id        UUID PRIMARY KEY,
  version         TEXT,
  segment         TEXT,          -- "regime_0:GapAnalysis:5m" or "global"
  status          TEXT,          -- "shadow" | "production" | "retired"
  trained_at      TIMESTAMPTZ,
  training_n      INT,
  p_value         FLOAT,
  win_rate        FLOAT,
  avg_pnl_r       FLOAT,
  artifact_path   TEXT,
  mlflow_run_id   TEXT
)

-- Per-signal ML scores
ml_signal_scores (
  signal_id       UUID REFERENCES signal_ledger(signal_id),
  model_id        UUID REFERENCES ml_models(model_id),
  win_prob        FLOAT,
  expected_pnl_r  FLOAT,
  confidence_band FLOAT,
  shap_values     JSONB,         -- top feature contributions
  scored_at       TIMESTAMPTZ,
  PRIMARY KEY (signal_id, model_id)
)

-- IC per feature — drives adaptive CIS weights
feature_ic_scores (
  feature_name    TEXT,
  regime          INT,           -- NULL=global, 0/1/2=regime-specific
  ic              FLOAT,
  icir            FLOAT,         -- IC information ratio
  n               INT,
  updated_at      TIMESTAMPTZ,
  PRIMARY KEY (feature_name, COALESCE(regime, -1))
)

-- Weekly discovery run metadata
ml_discovery_runs (
  run_id          UUID PRIMARY KEY,
  ran_at          TIMESTAMPTZ,
  top_features    JSONB,
  cross_asset     JSONB,
  regime_findings JSONB,
  tsfresh_new     JSONB,         -- new features found by tsfresh with IC > threshold
  summary_text    TEXT
)

-- HITL queue
ml_agent_hitl_queue (
  id              UUID PRIMARY KEY,
  created_at      TIMESTAMPTZ,
  trigger         TEXT,
  severity        TEXT,
  context         JSONB,
  status          TEXT,          -- "pending" | "approved" | "rejected" | "timed_out"
  decided_at      TIMESTAMPTZ,
  decided_by      TEXT
)
```

### signal_ledger additions
```sql
ml_win_prob         FLOAT,    -- NULL until Phase 2 live
ml_expected_pnl_r   FLOAT,
ml_model_version    TEXT,
ml_shap_top_features JSONB    -- top 5 SHAP contributors for this signal
```

---

## Prerequisites

All three prerequisites are met as of v1.8 (2026-03-13):

1. **CIS backfill fix** ✅ — `aggregate()` now receives `features=` kwarg; fixed in Phase 25 + historical_backfill.py
2. **constituent_contributions** ✅ — Phase 29-01: per-setup score contributions now populated in CISResult; written to signal_ledger JSONB
3. **Signal replay verification** ✅ — lifecycle_replay.py inverted-condition bug fixed (2026-03-14); dual-track market entry outcomes backfilled for all historical signals

---

## Open Questions

- Model artifact storage: filesystem + path in ml_models (simple) vs MLflow artifact store (queryable) — MLflow recommended
- CIS weight update cadence: weekly with discovery run, or continuous via river online learning from Phase 1?
- Cross-asset correlation: symmetric (ES↔NQ) or directional with lag (ES at t-N → NQ at t)?
- tsfresh compute cost: full 700+ features or curated subset per TF? Profile first.
- HITL notification channel: dashboard-only or also email/Slack?

---

## Related

- `docs/ideas/renaissance-gap-analysis.md` — T1 signal quality items are feature engineering for Phase 1
- `docs/ideas/renaissance-i7-i8-refinement.md` — 105 ideas, many feed as features into the ensemble
- `docs/ideas/i6-confluence-expansion.md` — cross-asset features feed directly into IC analysis
- `docs/ideas/renaissance-framing.md` — philosophical framing
- `docs/ideas/tech-stack.md` — infrastructure decisions (Redpanda, pgvector, LangFuse)
