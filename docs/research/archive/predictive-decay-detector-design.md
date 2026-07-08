# Predictive Decay Detector — Reusable Predictive Edge Monitoring Platform

**Date:** 2026-06-27
**Status:** SUPERSEDED 2026-06-27 — consolidated into `docs/plans/archive/2026-06-27-health-guardian-design.md` (Phase 149B ICLifecycleMonitor), itself now superseded by `docs/research/intel-14-integrity-monitor.md` (ICLifecycleMonitor dissolved into an ic_engine post-run hook writing feature_registry/Concept Registry state directly). This doc's core insight (name the service after the decay problem, not the metric) survives as the reasoning behind that generalization. Kept for design rationale only; do not build from this doc.
**Type:** Service architecture concept
**Related:** `docs/research/archive/feature-vector-lifecycle.md` (IC decay logic to extract)
**Service pattern:** `docs/research/archive/data-integrity-monitor-design.md`, `docs/research/archive/system-health-monitor-design.md`

---

## What This Is

A **general-purpose predictive edge monitoring platform** that detects when any system's predictive power decays over time:

- **Feature decay** — Feature's IC erodes → exclude from ensemble
- **Ensemble IC decay** — Ensemble's IC drops → halt emission
- **Model decay** — ML model's accuracy degrades → retrain or replace
- **Strategy decay** — Strategy's Sharpe collapses → halt or reduce exposure

**First consumer:** v3.0 features (`feature_ic_scores`) + ensemble IC (`alpha_ensemble_ic`)

**Future consumers:**
- ML models in production (accuracy decay, calibration drift)
- Trading strategies (Sharpe decay, hit rate degradation)
- Any system with predictive metrics (IC, Sharpe, R², calibration)

---

## Design Principle: Decay Is Implementation-Agnostic

> "Don't name services after their metrics. Name them after the problem they solve."
>
> "IC is a metric — a measurement you use to solve the problem. The problem is: has the predictive power decayed?"
>
> "What if tomorrow you switch from IC to Sharpe? What if you use R²? The service should still work. Name it after the problem, not the metric."
> — Jim Simons (paraphrased)

**The Renaissance approach:**
1. **Problem:** Predictive decay — edge erosion over time
2. **Metric:** IC (Information Coefficient), Sharpe, R², calibration — interchangeable
3. **Service:** `PredictiveDecayDetector` — works with any predictive metric

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                  Predictive Decay Detector                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  Registration Interface (APR-backed config)                          │
│  ┌─────────────────────────────────────────────┐               │
│  │ register_predictive_system(                     │               │
│  │   name="feature_ic_scores",                  │               │
│ │   metric_type="ic",                           │               │
│ │   metric_table="feature_ic_scores",           │               │
│ │   decay_threshold=0.0,                        │               │
│ │   recovery_cooldown_days=30                    │               │ │
│ │   action="exclude_from_ensemble"             │               │ │
│ │ )                                             │               │
│  └─────────────────────────────────────────────┘               │
│                                                               │
│  Decay Detection Layer (pluggable decay triggers)                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ Metric       │  │ Threshold    │  │ Stability    │       │
│  │ Gate         │  │ Gate         │  │ Gate         │       │
│  │ (ic_sharpe)   │  │ (sharpe<0.5) │  │ (std>0.3)    │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
│           ↓                  ↓                  ↓            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ Sample Size  │  │ Reliability  │  │ Regime       │       │
│  │ Gate         │  │ Gate         │  │ Gate         │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
│                                                               │
│  Persistence Layer (single schema, all systems)                        │
│  ┌──────────────────────────────────────────────┐            │
│  │ predictive_lifecycle hypertable                │            │
│  │ • system_name (indexed)                          │            │
│  │ • metric_type (ic / sharpe / r2 / calibration)│            │
│  │ • state (candidate / active / decaying / failed)   │            │
│  │ • metric_value, threshold_value                │            │
│  │ • decay_detected_at, recovery_eligible_at        │            │
│  │ • recovery_confirmed_at                         │            │
│  └──────────────────────────────────────────────┘            │
│                                                               │
│  Action Layer (pluggable callbacks)                                       │
│  ┌──────────────────────────────────────────────┐            │
│  │ Action registry (APR-configured):                 │            │
│  │ • exclude_from_ensemble → set is_decaying=true  │            │
│  │ • halt_emission → stop output                    │            │
│ │ • reduce_exposure → multiply conviction by 0.5    │            │
│  │ • promote_to_active → set is_decaying=false      │            │
│  │ • retrain_model → enqueue training job           │            │
│  │ • alert_operator → webhook/PagerDuty             │            │
│  └──────────────────────────────────────────────┘            │
│                                                               │
│  Observability Layer (built-in)                                            │
│  ┌──────────────────────────────────────────────┐            │
│  │ • OTel Prometheus metrics (per-system)           │            │
│  │ • REST API: GET /api/predictive/:system          │            │
│  │ • Topic events: state transitions               │            │
│  └──────────────────────────────────────────────┘            │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

**Service deployment:**
- **Standalone service:** `indicant-predictive-decay-detector`
- **Port:** `:9120`
- **Check cycles:** Event-driven (on IC runs) + periodic recovery checks

---

## Service Interface

### Registration for Features (First Consumer)

```python
# In migration or config script
await predictive_decay_service.register(
    name="feature_ic_scores",
    metric_type="ic",
    metrics_table="feature_ic_scores",
    output_table="feature_ic_scores",
    
    decay_triggers=[
        {
            "name": "walkforward_failure",
            "type": "threshold_gate",
            "description": "Walkforward test failed",
            "condition": "passes_walkforward = false",
            "severity": "critical",
            "action_on_decay": "exclude_from_ensemble",
            "action_params": {"set_is_decaying": true}
        },
        {
            "name": "ic_sharpe_threshold",
            "type": "threshold_gate",
            "description": "IC Sharpe drops below floor",
            "query": """
                SELECT ic_sharpe
                FROM feature_ic_scores
                WHERE feature_name=$1 AND symbol=$2 AND tf=$3
                  AND regime=$4 AND lookahead_bars=$5
                  AND is_pooled=false
                ORDER BY training_window_end DESC LIMIT 1
            """,
            "thresholds": {
                "decay": {"ic_sharpe": 0.0},
                "critical": {"ic_sharpe": 0.5}
            },
            "action_on_decay": "exclude_from_ensemble"
        },
        {
            "name": "reliability_loss",
            "type": "threshold_gate",
            "description": "Corpus shrank or symbol delisted",
            "condition": "reliable = false",
            "severity": "critical",
            "action_on_decay": "exclude_from_ensemble"
        }
    ],
    
    recovery_config={
        "cooldown_days": 30,  # APR: predictive.feature.recovery_cooldown_days
        "consecutive_passes_required": 2,  # APR: predictive.feature.recovery_consecutive_passes
        "min_reliable_n": 50  # Minimum samples for reliability check
    },
    
    action_on_decay="exclude_from_ensemble",
    observability={
        "prometheus_port": 9120,
        "api_route": "/api/predictive/feature_ic"
    }
)
```

---

### Registration for Ensemble IC (Second Consumer)

```python
await predictive_decay_service.register(
    name="alpha_ensemble_ic",
    metric_type="ic",
    metrics_table="alpha_ensemble_ic",
    output_table="alpha_ensemble_ic",
    
    decay_triggers=[
        {
            "name": "ensemble_ic_floor",
            "type": "threshold_gate",
            "description": "Ensemble IC drops below critical floor",
            "query": """
                SELECT ic_sharpe, walk_forward_stable, fdr_passed
                FROM alpha_ensemble_ic
                WHERE symbol=$1 AND tf=$2 AND regime=$3
                  AND lookahead=$4
                  AND scored_at > NOW() - INTERVAL '7 days'
                ORDER BY scored_at DESC LIMIT 1
            """,
            "thresholds": {
                "decay": {"ic_sharpe": 1.0},
                "critical": {"ic_sharpe": 0.3},
                "stale": {"scored_at": "7 days"}
            },
            "required_conditions": {
                "walk_forward_stable": true,
                "fdr_passed": true
            },
            "action_on_decay": "halt_emission"
        }
    ],
    
    recovery_config={
        "cooldown_days": 14,  # Ensemble recovers faster than features
        "consecutive_passes_required": 2
    },
    
    action_on_decay="halt_emission",
    observability={
        "prometheus_port": 9120,
        "api_route": "/api/predictive/ensemble_ic"
    }
)
```

---

### Future Consumers: ML Models

```python
await predictive_decay_service.register(
    name="ml_model_accuracy",
    metric_type="accuracy",
    metrics_table="model_performance",
    
    decay_triggers=[
        {
            "name": "accuracy_floor",
            "type": "threshold_gate",
            "query": "SELECT accuracy FROM model_performance WHERE model_id=$1",
            "thresholds": {
                "decay": {"accuracy": 0.70},
                "critical": {"accuracy": 0.50}
            },
            "action_on_decay": "retrain_model"
        },
        {
            "name": "calibration_drift",
            "type": "distribution_check",
            "query": "SELECT calibration_brier_score FROM model_calibration WHERE model_id=$1",
            "thresholds": {
                "decay": {"brier_score": 0.65}
            },
            "action_on_decay": "alert_operator"
        }
    ],
    
    recovery_config={
        "cooldown_days": 7,
        "consecutive_passes_required": 3
    },
    
    action_on_decay="retrain_model"
)
```

---

## Core Components

### 1. Decay Detection Algorithms (Pluggable Triggers)

**Each decay trigger is a subclass:**

```python
class BaseDecayTrigger(ABC):
    @abstractmethod
    async def check(self, conn, params: dict) -> DecayResult:
        """Run decay check, return severity + action."""
        pass

class ThresholdGate(BaseDecayTrigger):
    """Check if metric crosses threshold (IC Sharpe, accuracy, etc.)"""
    
    async def check(self, conn, params: dict) -> DecayResult:
        result = await conn.fetchrow(self.config["query"], *params.values())
        
        metric_value = result[self.config["metric_column"]]
        threshold = self.config["thresholds"]["decay"]
        
        if metric_value < threshold:
            severity = self._calculate_severity(metric_value, threshold)
            return DecayResult(
                state="decaying",
                severity=severity,
                metric_value=metric_value,
                threshold_value=threshold,
                trigger_reason=self.config["description"],
                action=self.config["action_on_decay"]
            )
        
        return DecayResult(state="active")

class ReliabilityGate(BaseDecayTrigger):
    """Check if reliability flag dropped (corpus shrank, delisting)"""
    
    async def check(self, conn, params: dict) -> DecayResult:
        result = await conn.fetchrow(
            "SELECT reliable, COUNT(*) AS sample_count FROM feature_ic_scores WHERE feature_name=$1",
            params["feature_name"]
        )
        
        if not result["reliable"] or result["sample_count"] < 50:
            return DecayResult(
                state="decaying",
                severity=1.0,
                trigger_reason="reliability_lost_or_insufficient_data",
                action="exclude_from_ensemble"
            )
        
        return DecayResult(state="active")

class WalkforwardGate(BaseDecayTrigger):
    """Check if walkforward test failed"""
    
    async def check(self, conn, params: dict) -> DecayResult:
        # This is checked by comparing current row to prior row
        # Handled in the IC engine integration section
        pass
```

---

### 2. Recovery State Machine

**Renaissance-grade requirement:** Systems don't auto-recover on a single fluke pass. Require confirmation.

```python
# After decay trigger fires, monitor runs recovery checks
if decay_result.state == "decaying":
    recovery_attempts += 1
    recovery_checked_at = now()
    
    # Wait for cooldown to elapse
    if now() < recovery_eligible_at:
        return  # Still in cooldown, wait
    
    # Re-test with fresh data
    new_result = await decay_trigger.check(conn, params)
    
    if new_result.state == "active":
        # Clean check
        if recovery_attempts >= 2:  # Require 2 consecutive clean checks
            recovery_required = True  # Flag for recovery action
            
            # Execute recovery action
            await execute_action("promote_to_active", system, decay_result)
    else:
        # Still failing, reset counter
        recovery_attempts = 0
```

**Recovery actions:**
- For features: set `is_decaying = false`, clear timestamps
- For ensemble: clear halt, allow emission
- For models: enable for inference

---

### 3. Persistence Schema

**Table:** `predictive_lifecycle` (hypertable, all systems)

```sql
CREATE TABLE IFICIENT EXISTS predictive_lifecycle (
    id                  BIGSERIAL       PRIMARY KEY,
    system_name         TEXT            NOT NULL,  -- feature_ic_scores, alpha_ensemble_ic, etc.
    metric_type          TEXT            NOT NULL,  -- ic, sharpe, r2, accuracy, etc.
    
    symbol              TEXT,
    timeframe           TEXT,
    regime              TEXT,
    lookahead           TEXT,
    feature_name        TEXT,              -- For feature-level tracking
    model_id            TEXT,              -- For model tracking
    
    checked_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    
    -- State
    state               TEXT            NOT NULL,  -- candidate / active / decaying / failed
    severity            FLOAT,                          -- 0-1 score of decay severity
    
    -- Metrics
    metric_value        FLOAT,                          -- ic_sharpe, accuracy, etc.
    threshold_value     FLOAT,                          -- Threshold that was evaluated
    metric_name         TEXT,                           -- ic_sharpe, accuracy, etc.
    
    -- Decay tracking
    decay_detected_at   TIMESTAMPTZ,
    decay_trigger_reason TEXT,
    
    -- Recovery state machine
    recovery_eligible_at TIMESTAMPTZ,
    recovery_checked_at  TIMESTAMPTZ,
    recovery_attempts   INTEGER DEFAULT 0,
    recovery_confirmed_at TIMESTAMPTZ,
    
    UNIQUE(system_name, metric_type, symbol, timeframe, regime, lookahead, feature_name, model_id, checked_at)
);

SELECT create_hypertable(
    'predictive_lifecycle', 'checked_at',
    chunk_time_interval => INTERVAL '30 days',
    if_not_exists => TRUE
);

CREATE INDEX ix_predictive_lifecycle_system ON predictive_lifecycle(system_name, state, checked_at DESC);
CREATE INDEX ix_predictive_lifecycle_recovery ON predictive_lifecycle(
    system_name, symbol, timeframe, regime, recovery_eligible_at
) WHERE state = 'decaying';
```

**New table:** `predictive_system_registry` (APR-backed config)

```sql
CREATE TABLE IF NOT EXISTS predictive_system_registry (
    system_name         TEXT            PRIMARY KEY,
    metric_type          TEXT            NOT NULL,  -- ic, sharpe, r2, accuracy
    metrics_table       TEXT            NOT NULL,
    output_table        TEXT,
    
    decay_triggers      JSONB           NOT NULL,  -- Array of trigger configs
    recovery_config     JSONB           NOT NULL,  -- cooldown, consecutive passes
    
    action_on_decay     TEXT,
    action_params        JSONB,
    
    observability       JSONB,
    registered_at        TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    registered_by        TEXT            NOT NULL DEFAULT 'system'
);
```

---

### 4. Action Layer (Pluggable Callbacks)

**Action registry (APR-configured):**

```python
class ExcludeFromEnsemble(BaseActionCallback):
    """Set is_decaying=true for features"""
    
    async def execute(self, system: str, decay_result: DecayResult) -> ActionOutcome:
        if system == "feature_ic_scores":
            await conn.execute(
                """
                UPDATE feature_ic_scores
                SET is_decaying=true, decay_detected_at=$1,
                    recovery_eligible_at=$1 + (predictive_feature_recovery_cooldown_days * INTERVAL '1 day')
                WHERE feature_name=$2 AND symbol=$3 AND tf=$4 AND regime=$5
                  AND lookahead_bars=$6
                """,
                now(), decay_result.feature_name, decay_result.symbol,
                decay_result.tf, decay_result.regime, decay_result.lookahead
            )
            return ActionOutcome(excluded=True, reason=decay_result.trigger_reason)

class HaltEmission(BaseActionCallback):
    """Stop alpha event emission"""
    
    async def execute(self, system: str, decay_result: DecayResult) -> ActionOutcome:
        if system == "alpha_ensemble_ic":
            await config_service.set(
                f"alpha.emitter.halted",
                value=True,
                reason=f"ensemble_ic_decay: {decay_result.trigger_reason}",
                metadata={
                    "symbol": decay_result.symbol,
                    "tf": decay_result.tf,
                    "regime": decay_result.regime,
                    "severity": decay_result.severity
                }
            )
            return ActionOutcome(halted=True)

class ReduceExposure(BaseActionCallback):
    """Reduce position sizing by multiplier"""
    
    async def execute(self, system: str, decay_result: DecayResult) -> ActionOutcome:
        multiplier = decay_result.action_params.get("multiplier", 0.5)
        
        await config_service.set(
            f"alpha.emitter.exposure_multiplier",
            value=multiplier,
            reason=f"predictive_decay: reducing exposure to {multiplier*100}%"
        )
        return ActionOutcome(exposure_reduced=True, multiplier=multiplier)

class RetrainModel(BaseActionCallback):
    """Enqueue model retrain job"""
    
    async def execute(self, system: str, decay_result: DecayResult) -> ActionOutcome:
        await job_queue.enqueue(
            job_type="model_retrain",
            priority="urgent",
            params={"model_id": decay_result.model_id},
            reason=decay_result.trigger_reason
        )
        return ActionOutcome(retrain_queued=True)
```

---

### 5. Observability Layer (Built-In)

**Prometheus metrics (per-system):**

```
predictive_lifecycle_state{system_name, metric_type, state}  # 0=candidate, 1=active, 2=decaying, 3=failed
predictive_lifecycle_severity{system_name, metric_type}  # Numeric score 0-1
predictive_decay_detected_total{system_name, trigger_reason}  # Cumulative decays
predictive_recovery_confirmed_total{system_name}  # Cumulative recoveries
predictive_system_registry_size  # How many systems registered
```

**API endpoint (per-system):**

```
GET /api/predictive/:system_name
```

**Response (example for feature_ic_scores):**

```json
{
  "system_name": "feature_ic_scores",
  "metric_type": "ic",
  "registered_at": "2026-06-27T10:00:00Z",
  "overall_status": "healthy",
  "decay_alerts": [
    {
      "feature_name": "momentum_z_mid",
      "symbol": "ES",
      "tf": "1m",
      "regime": "trending",
      "lookahead_bars": 5,
      "state": "decaying",
      "severity": 0.8,
      "metric_value": 0.3,
      "threshold_value": 0.5,
      "trigger_reason": "ic_sharpe_below_threshold",
      "decay_detected_at": "2026-06-27T12:00:00Z",
      "recovery_eligible_at": "2026-06-27T12:00:00Z + 30 days",
      "recovery_attempts": 0,
      "action": "exclude_from_ensemble"
    }
  ],
  "recovery_alerts": [
    {
      "feature_name": "rsi_fast",
      "symbol": "ES",
      "tf": "1m",
      "regime": "trending",
      "lookahead_bars": 5,
      "state": "active",
      "recovery_confirmed_at": "2026-06-27T14:00:00Z",
      "decay_detected_at": "2026-06-20T10:00:00Z"
    }
  ]
}
```

**Topic events (state transitions):**

```python
# Published on any state transition
topic_predictive_lifecycle_transition()
event = PredictiveLifecycleEvent(
    system_name="feature_ic_scores",
    metric_type="ic",
    feature_name="momentum_z_mid",
    symbol="ES", tf="1m", regime="trending",
    lookahead_bars=5,
    prior_state="active",
    new_state="decaying",
    trigger_reason="ic_sharpe_below_threshold",
    metric_value=0.3,
    threshold_value=0.5,
    transitioned_at=now()
)
```

---

## Renaissance-Grade Requirements

**What makes this platform truly reusable:**

1. ✅ **Implementation-agnostic** — Works with IC, Sharpe, R², calibration, any predictive metric
2. ✅ **All parameters APR-backed** — No hardcoded thresholds, cooldowns, or sample sizes
3. ✅ **Pluggable decay triggers** — Easy to add new trigger types (distribution check, regime-specific, etc.)
4. ✅ **Pluggable actions** — Not just exclude/halt — retrain, reduce exposure, alert operators, custom callbacks
5. ✅ **Per-system isolation** — Each system has independent config, metrics, recovery settings
6. ✅ **Recovery state machine** — Not just expiry, but confirmed recovery (2 consecutive clean checks)
7. ✅ **Zero code changes for new systems** — Registration via APR migration
8. ✅ **Orthogonal to other services** — Complements DataIntegrityMonitor and SystemHealthMonitor

---

## Migration Strategy (v3.0)

### Phase 1: Service Foundation (One-Time Setup)

**Create the service infrastructure:**
1. `predictive_lifecycle` hypertable (with recovery columns)
2. `predictive_system_registry` table (APR-backed config)
3. Base classes: `BaseDecayTrigger`, `BaseActionCallback`
4. Implement trigger types: `ThresholdGate`, `ReliabilityGate`, `WalkforwardGate`
5. Implement actions: `ExcludeFromEnsemble`, `HaltEmission`, `ReduceExposure`, `RetrainModel`
6. `indicant-predictive-decay-detector` service (generic, reads from registry)
7. OTel metrics + API endpoint (per-system routing)
8. Recovery state machine logic

**No feature-specific or ensemble-specific code in this phase.** Just the platform.

---

### Phase 2: Register Features as First Consumer

**Consuming the service:**
1. Insert `predictive_system_registry` row for "feature_ic_scores"
2. Configure 3 decay triggers (walkforward, ic_sharpe, reliability)
3. Configure recovery config (30d cooldown, 2 consecutive passes)
4. Update `ic_engine.py` to call service instead of direct logic
5. Update `ensemble_trainer` to query `is_decaying` flag

**Service detects decay automatically.** IC engine just runs IC checks, service handles lifecycle.

---

### Phase 3: Register Ensemble IC as Second Consumer

**Adding ensemble monitoring:**
1. Insert `predictive_system_registry` row for "alpha_ensemble_ic"
2. Configure decay trigger (ensemble IC floor)
3. Configure recovery config (14d cooldown, faster than features)
4. Wire to SystemHealthMonitor (halt emission on ensemble IC decay)

**Ensemble IC decay now monitored alongside feature decay.**

---

### Future Systems: Zero Deployment

**Add ML model monitoring:**
1. Insert `predictive_system_registry` row for "ml_model_accuracy"
2. Configure triggers (accuracy floor, calibration drift)
3. Service auto-discovers on next evaluation cycle
4. No deployment, no downtime

**That's the Renaissance approach.**

---

## Relationship to Other Services

**Three orthogonal services, three questions:**

```
┌─────────────────────────────────────────────────────────────┐
│              Three Validation Questions                      │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  Question 1: "Is the DATA trustworthy?"                          │
│  ┌──────────────────────────────────────────────┐            │
│  │ DataIntegrityMonitor                             │            │
│  │ • Monitors: Input data distributions         │            │
│  │ • Detects: KS test, chi-squared             │            │
│  │ • Question: "Is the data corrupted?"      │            │
│  │ • Action: Reduce weight if suspicious       │            │
│  └──────────────────────────────────────────────┘            │
│                                                               │
│  Question 2: "Has the PREDICTIVE POWER decayed?"                  │
│  ┌──────────────────────────────────────────────┐            │
│  │ PredictiveDecayDetector                       │            │
│  │ • Monitors: IC, Sharpe, R², accuracy      │            │
│  │ • Detects: Metric below threshold         │            │
│ │  │  │  │  │  │  │
│  │  │  │  │  │  │  │  │││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││ ││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││ │││││ |│││││ |│
│││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││→ |│││││| |││→ |│→
│  │  │  │  │  │  │  │  │  │  │  │  │  │ │  │  │  │  │  │  │
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │ │  │  │  │  │  │  │  │  │  │  │  │ │  │ │  │  │  │  │ │  │  │  │  │  │ │  │  │ │  │  │  │  │  │ │  │ │  │  │  │  │ │  │  │  │  │  │  │ │  │  │  │ │  │  │  │  │ │  │  │ │  │  │  │  │  │  │  │  │ │   │  │ │  │  │  │ │  │  │  │  │  │  │ │  │  │  │  │  │ │ │  │ │ │  │  │  │  │  │ │  │ │  │  │  │ │ │ │  │  │  │  │  │ │  │  │ │ │ │  │  │  │  │  │  │  │  │  │  │ │ │ │  │ │  │  │  │ │  │  | | | |
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  |  | | |
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  | | | |
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  |  | | |
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  | | | |
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  | | | |
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  | | | | |
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  | | | | |
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  |  | | |
│  │  │  │  │  │  │  │  │  │  │  │  │  | | | | | |
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  |  | | | | |
│  │  │  │  │  │  │  │  │  │  │  │  │  │  |  | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | |  |  |  | | | | | | | | | | | |  |  |  | | | | | | | | | | | | | | | |  | | | | | | | | | | | |  | | | | | | | | | |  |  | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | |  | | | | | | | | | | |  |  | | | | | | | | | | | | | | | |  | | | | | | | | | | | | | |  | | | | | | | | | | | | | | | | | | |  │  |  |  | |  |  |  | |  |  |  |  | |  |  |  | | | |  |  |  |  |  | |  |  |  |  |  |  | |  | | |  | |  |  |  |  | | | |  |  |  | | |  |  | | |  | |  |  |  |  | |  |  |  |  |  |  |  |  |  |  |  | |  |  | | |  |  | |  | | |  |  | | | |  |  |  |  | |  |  |  |  |  |  | | |  | | |  |  |  |  | |  |  |  |  |  |  │  |  | |  |  | |  | |  |  |  | |  │  |  |  |  |  |  | |  |  |  |  |  | |  |  |  |  |  |  |  |  |  |  │  |  |  |  |  |  |  │  |  |  |  |  |  │  |  |  |  │  |  |  |  │  |  |  |  │  |  |  |  |  |  |  │  │  |  |  |  |  │  |  |  |  |  |  |  |  |  |  |  |  │  |  |  |  |  |  |  |  │  |  |  |  |  |  |  |  │  │  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | |  |  |  |  |  |  | |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |   |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | |  |  |  |  |  |  |  |  |  |  |  |  | |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |   |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |   |  | |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | |  |  |  |  |  |  |  |  |  |  |  |  |  |   |  |  |  |  |  |  |  | |  |  |  |  |  |  |  |  |  |  |  |  |  | |  | |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | |  |  |  |  | |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | |  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  +  | | | | | |
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  | | | | |
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  | | | | |
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  | | | | |
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  | | | | |
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  | | | | |
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  | | | | |
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  | | | | |
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  | | | | |
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  | | | | |
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  | | | | |
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  | | | | |
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  | | | | |
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  | | | | |
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  | | | | |
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  | | | | |
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  | | | | |
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  | | | | |
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  | | | | |
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  | | | | |
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  | | | | |
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  |  | | | |
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  | | | | |
│  │  │  │  │  │  │  │  │  | │  │  │  │  │  │  │  | | | | |
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  |  | | | |
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  | | | | |
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  | | | | |
│  │  │  │  │  │  │  │  │  │  │  │  │  │  |  │  │  | | | | |
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  | | | | |
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  |  | | | |
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  |  | | | | |
│  │  │  │  │ │  ││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││││ ic_lifecycle_state || │ │ │ │ │ │ │ │ │ │ │ │ │ │ │ │ │ │ │ │ | | | | | | | | | | | | | | | | | | | | | | |  | | | | | | | |  |  |  | | | |  |  |  |  |  | |  |  |  |  |  |  | |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |   |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |   |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | AGE - Stage 2                        │
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |   |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |   |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |   |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  |  │  │  │  │  │  │  │  │  │  │  │  │  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |   |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |   |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |   |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |   |  |  |  |  |  |  |  |  IC.lifecycleMonitor: Track state (candidate/active/decaying)
│  ┌──────────────┐    ┌──────────────┐                          │
│  │ feature_     │───→│ Decay        │───→ ic_lifecycle_state │ │
│  │ ic_scores    │    │ (on corpus   │     (candidate/active/decaying) │
│  └──────────────┘    └──────────────┘                          │
│  ┌──────────────┐    ┌──────────────┐                          │
│  │ alpha_       │───→│ Decay        │───→ ic_lifecycle_state │ │
│  │ ensemble_ic │    │ (on corpus   │     (candidate/active/decaying) │ │
│  └──────────────┘    └──────────────┘                          │
│                                                               │
│  Action Layer (pluggable callbacks)                               │
│  ┌──────────────────────────────────────────────┐            │
│  │ Action registry (APR-configured):             │            │
│  │ • exclude_from_ensemble → set is_decaying=true   │            │
│  │ • halt_emission → set flag, stop emitter    │            │
│  │ • promote_to_active → set is_decaying=false   │            │
│  │ • demote_to_shadow → revert from production   │            │
│  └──────────────────────────────────────────────┘            │
│                                                               │
│  Observability Layer (built-in)                                │
│  ┌──────────────────────────────────────────────┐            │
│  │ • OTel Prometheus metrics (per-system)          │            │
│  │ • REST API: GET /api/predictive/:system   │            │
│  │ • Topic events: state transitions           │            │
│  └──────────────────────────────────────────────┘            │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```
**Service deployment:**
- **Standalone service:** `indicant-predictive-decay-detector`
- **Port:** `:9120`
- **Check cycles:** Event-driven (on IC runs) + periodic recovery checks

---

## What Jim Simons Would Demand

> "You have three generic patterns here. All three should be services."
>
> "Don't embed IC lifecycle logic in ic_engine.py. Extract it into a service. Then use it for ensemble IC, model IC, strategy IC — anything with IC metrics."
>
> **"One service per problem. Many consumers. Renaissance-grade infrastructure."**

---

## APR Keys (All Parameters Tunable)

### Feature IC Decay (extracted from feature-vector-lifecycle.md)

```python
# Decay triggers
predictive.feature.walkforward_failure_enabled = true        # Enable walkforward failure trigger
predictive.feature.ic_sharpe_threshold = 0.0           # IC Sharpe decay floor
predictive.feature.min_relible_n = 100             # Minimum samples for reliability check

# Recovery config
predictive.feature.cooldown_days = 30                   # Recovery cooldown (one IC cycle)
predictive.feature.recovery_consecutive_passes = 2          # Recovery confirmation (2 clean checks)
```

### Ensemble IC Decay (new, not previously defined)

```python
# Decay triggers
predictive.ensemble.ic_sharpe_floor_eligible = 1.0    # Warning floor
predictive.ensemble.ic_sharpe_floor_critical = 0.5   # Critical floor
predictive.ensemble.ic_stale_days_threshold = 7         # Max staleness
predictive.ensemble.walkforward_stable_required = true
predictive.ensemble.fdr_passed_required = true

# Recovery config (faster than features)
predictive.ensemble.cooldown_days = 14                   # 14-day cooldown
predictive.ensemble.recovery_consecutive_passes = 2
```

### ML Model Decay (future)

```python
predictive.model.accuracy_floor_eligible = 0.70
predictive.model.accuracy_floor_critical = 0.50
predictive.model.calibration_brier_score = 0.65
predictive.model.cooldown_days = 7
predictive.model.recovery_consecutive_passes = 3
```

### Service Configuration

```python
# Check intervals
predictive.feature.check_interval_hours = 1              # When to run decay checks
predictive.feature.recovery_check_interval_hours = 4         # When to run recovery checks
predictive.ensemble.check_interval_hours = 1           # Ensemble checks every hour
```

---

## Success Criteria

A complete predictive decay detection service should:

1. ✅ Features marked `is_decaying=true` when walkforward fails
2. ✅ Features marked `is_decaying=true` when IC Sharpe drops below threshold
3. ✅ Features marked `is_decaying=true` when reliability drops
4. ✅ Decay detection for features works automatically (no manual intervention)
5. ✅ Recovery clears `is_decaying` flag after 2 consecutive clean IC runs
6. ✅ Prometheus metrics: `predictive_decay_state{system_name="feature_ic_scores"}` reflects decay counts
7. ✅ Prometheus metrics: `predictive_recovery_confirmed_total{system_name}` tracks recoveries
8. ✅ `/api/predictive/feature_ic` returns decay status for all features
9. ✅ `/api/predictive/ensemble_ic` returns decay status for ensemble
10. ✅ All parameters APR-backed (tunable without migrations)
11. ✅ Service handles both features and ensemble IC (multiple systems)
12. ✅ Zero code changes to add ensemble IC monitoring (just registration)
13. ✅ Zero code changes to add ML model monitoring (just registration)
14. ✅ Recovery state machine prevents flapping (2 consecutive clean checks required)
15. ✅ Pluggable decay triggers (easy to add new triggers)
16. ✅ Pluggable actions (exclude, halt, promote, demote, reduce, retrain)

---

## What Jim Simons Would Say

> "Three services. Three orthogonal problems. Renaissance-grade infrastructure."
>
> "Data integrity (DataIntegrityMonitor). Predictive decay (PredictiveDecayDetector). System health (SystemHealthMonitor). These are the three validation questions every Renaissance system needs."
>
> "Don't embed the IC lifecycle logic in ic_engine.py. Extract it into PredictiveDecayDetector service. Then use it for features, ensemble IC, models, strategies — anything with predictive metrics."
>
> **"One service per problem. Many consumers. Renaissance-grade infrastructure."**

---

**This is a reusable platform. Build it right, use it everywhere.**

---

## Renaissance Validation Requirements

**What Renaissance would demand before deployment:**

> "You designed a service to detect IC decay. Great. Now show me it works. Backtest on historical features that decayed. Show me the recovery false positive rate. Show me latency benchmarks. Engineering requires proof, not good intentions."
> — Jim Simons (paraphrased)

---

### Phase 0: Proof (Must Have Before Deployment)

**Historical Validation:**
1. ✅ **Backtest on 3 feature decay events from historical data**
   - Event 1: Momentum feature decayed after regime shift (trending → ranging)
   - Event 2: Volatility feature lost edge after volatility spike
   - Event 3: Mean reversion feature decayed after correlation breakdown
   - Required: "Service set `is_decaying=true` within 1 check cycle, excluded from ensemble"
   - Deliverable: `tests/integration/test_feature_decay_historical_events.py`

2. ✅ **False positive analysis (expected value calculation)**
   - Decay trigger: `ic_sharpe<0.0` (floor threshold)
   - Calculate: `false_positive_rate × exclusion_cost = opportunity_cost`
   - Calculate: `true_positive_rate × decay_prevented_loss = benefit`
   - Required: `net_benefit > 0` with 95% CI
   - Deliverable: `analysis/predictive_decay_economic_impact.ipynb`

3. ✅ **Latency benchmark (prove it's fast enough)**
   - Benchmark: Check 58 features × 4 timeframes × 3 regimes = 696 feature rows
   - SLO: `check completes in <200ms p95` (event-driven, allows more budget than timer-based)
   - Deliverable: `tests/benchmarks/test_decay_detection_latency.py`

**Stress Testing:**
4. ✅ **Validate on 3 historical crises**
   - Crisis 1: 2020-03 COVID crash (many features decayed simultaneously)
   - Crisis 2: 2022-10 vol spike (volatility features impacted)
   - Crisis 3: 2023 rate hike cycle (mean reversion features decayed)
   - Required: "Decay detection fired correctly, recovery worked after regime restabilized"
   - Deliverable: `tests/integration/test_predictive_decay_stress_scenarios.py`

---

### Phase 1: Calibration (High Value)

**Parameter Calibration (Replace Magic Numbers):**
5. ✅ **IC Sharpe threshold calibrated from historical feature performance**
   - Current: `ic_sharpe<0.0` (decay floor) — arbitrary
   - Required: "Analyze last 12 months of feature_ic_scores, find IC values at known decay events"
   - Example: "ic_sharpe<0.3 caught 80% of decay events with 10% FP rate"
   - Deliverable: `analysis/ic_sharpe_threshold_calibration.ipynb`

6. ✅ **Recovery cooldown calculation**
   - Current: `cooldown_days=30` — arbitrary
   - Required: "Analyze historical decay-recovery cycles, measure time from decay_trigger to IC recovery"
   - Question: "How long does it take for a decayed feature to recover?"
   - Deliverable: `analysis/recovery_cooldown_empirical.ipynb`

7. ✅ **Recovery confirmation requirement validation**
   - Current: `recovery_consecutive_passes=2` — why 2?
   - Simulate 1000 recovery cycles with different requirements (1, 2, 3, "3 out of 5")
   - Measure: False recovery rate vs time-to-recover
   - Trade-off: Stricter requirement (3) → lower false recovery but slower recovery
   - Deliverable: `analysis/recovery_confirmation_simulation.ipynb`

8. ✅ **Bootstrap CI gate analysis**
   - Current: `bootstrap_ci_lower > 0` requirement for feature promotion
   - Test: "Does this gate actually predict future OOS performance?"
   - Analysis: "Features passing bootstrap CI gate have X% higher OOS IC"
   - Deliverable: `analysis/bootstrap_ci_predictive_power.ipynb`

---

### Phase 2: Observability (Required)

**Critical Missing Metrics:**
9. ✅ **False recovery tracking**
    - Metric: `predictive_decay_recovery_false_positive_total{system_name}`
    - Definition: Recovery confirmed but next IC run shows `is_decaying=true` again
    - Alert if: `false_positive_rate > 0.20` (20% of recoveries are fake)

10. ✅ **Decay economic impact tracking**
    - Metric: `predictive_decay_excluded_features_total{system_name}`
    - Metric: `predictive_decay_prevented_loss_usd{system_name}`
    - Calculation: Estimate loss avoided by excluding decayed features (compare to if they stayed in ensemble)

11. ✅ **Recovery rate tracking**
    - Metric: `predictive_decay_recovery_rate{system_name}`
    - Definition: `features_recovered / features_decayed` over last 30/60/90 days
    - Alert if: `recovery_rate < 0.10` (less than 10% of decayed features ever recover)

12. ✅ **Cross-system decay correlation**
    - Metric: `predictive_decay_correlation{system_a, system_b}`
    - Question: "When feature_ic_scores decay, does alpha_ensemble_ic also decay?"
    - Alert if: `correlation > 0.8` (ensemble decay tracks feature decay, consider combining systems)

---

### Phase 1 Extensions: Ensemble IC Decay

13. ✅ **Ensemble IC threshold calibration**
    - Current: `ic_sharpe<0.5` (critical), `<1.0` (warning) — arbitrary
    - Required: "Analyze historical alpha_ensemble_ic, find IC values at known ensemble degradation events"
    - Test: "If ensemble IC dropped to 0.3, did OOS performance actually degrade?"
    - Deliverable: `analysis/ensemble_ic_threshold_calibration.ipynb`

14. ✅ **Ensemble recovery simulation**
    - Simulate 100 ensemble IC decay + recovery cycles
    - Test: Halt emission vs reduce size vs continue with warning
    - Measure: "Which action minimized drawdown during decay?"
    - Deliverable: `analysis/ensemble_recovery_action_simulation.ipynb`

---

### Decision Framework: Feature vs Ensemble IC Decay

**Renaissance analysis question:**
> "When feature IC decays, should we exclude the feature OR halt ensemble emission? Current design: both actions independently. Is this correct?"

**Required analysis:**
1. Historical periods where:
   - Feature IC decayed (many features set `is_decaying=true`)
   - Ensemble IC also decayed (ensemble `ic_sharpe` dropped)
   - OOS performance during both scenarios

2. For each scenario, answer:
   - Did excluding decayed features improve ensemble IC?
   - Did halting emission prevent losses or miss opportunities?
   - What decision logic would have been optimal?

**Deliverable:** `docs/analysis/feature_vs_ensemble_decay_decision_matrix.md` with recommendation on independent vs coupled decay handling.

---

### Decision Framework: Recovery Confirmation

**Renaissance analysis question:**
> "Recovery requires 2 consecutive clean IC runs. During fast regime changes (crash → volatility → trend), a feature might recover and decay again within days. Is 2 consecutive checks optimal or too rigid?"

**Required analysis:**
1. Simulate regime switching scenarios:
   - Scenario: Regime A (decayed) → Regime B (recovered) → Regime A (decayed again)
   - Measure: "How long does feature stay in wrong state with 2-consecutive rule?"
   - Compare: "1 check" (faster but more flapping) vs "2 checks" (slower but more stable) vs "3 out of 5" (adaptive)

**Deliverable:** `docs/analysis/recovery_confirmation_logic_evaluation.md` with recommendation on optimal recovery confirmation strategy.
