# Decay Detection Service — Reusable System Health Platform

**Date:** 2026-06-27
**Status:** SUPERSEDED 2026-06-27 — consolidated into `docs/plans/archive/2026-06-27-health-guardian-design.md` (Phase 150 EnsembleHealthMonitor), itself now superseded by `docs/ideas/intel-14-integrity-monitor.md`. Kept for design rationale only; do not build from this doc.
**Type:** Service architecture concept
**Related:** `docs/ideas/archive/data-integrity-monitor-design.md` (data quality monitoring)

---

## What This Is

A **general-purpose system health monitoring platform** that can detect when any process/decays over time:

- **Performance decay** — Ensemble IC drops, model accuracy degrades, strategy Sharpe collapses
- **Stability collapse** — Conviction scores oscillate, prediction distributions drift, latency spikes
- **Coverage failure** — Not enough active features, model training data shrinks, pipeline input drops

**First consumer:** v3.0 AlphaEngine ensemble (3-gate health check)

**Future consumers:**
- ML models in production (accuracy decay, prediction drift)
- Data pipelines (latency degradation, error rate spikes)
- Trading strategies (Sharpe decay, drawdown detection)
- Any system with measurable health metrics

---

## Design Principle: Decouple Health from Data

> "Drift asks: 'Is the data trustworthy?' Decay asks: 'Is the system working?' A system can have clean data and be broken. It can have good performance and corrupted data. You need both detectors, independently."
> — Jim Simons (paraphrased)

**The Renaissance approach:**
1. **Drift Detection Service** — Monitors input data quality (KS test, chi-squared)
2. **Decay Detection Service** — Monitors system health/performance (IC gates, stability checks)
3. **Both are orthogonal** — A system passes one and fails the other → different actions
4. **Both are reusable** — Register any system via APR, zero code changes

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    Decay Detection Service                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  Registration Interface (APR-backed config)                     │
│  ┌─────────────────────────────────────────────┐               │
│  │ register_system(                             │               │
│  │   name="alpha_ensemble",                    │               │
│  │   health_checks=["ic_gate", "conviction",  │               │
│  │                  "coverage"],                │               │
│  │   metrics_table="alpha_ensemble_ic",        │               │
│  │   halt_action="stop_alpha_emitter"          │               │
│  │ )                                           │               │
│  └─────────────────────────────────────────────┘               │
│                                                               │
│  Health Check Layer (pluggable gate types)                     │
│  ┌──────────────────┐  ┌──────────────────┐                  │
│  │ Metric Threshold │  │ Stability Check   │                  │
│  │ Gate             │  │ (std, oscillation)│                  │
│  └──────────────────┘  └──────────────────┘                  │
│           ↓                     ↓                             │
│  ┌──────────────────┐  ┌──────────────────┐                  │
│  │ Distribution     │  │ Coverage Check   │                  │
│  │ Gate              │  │ (count ≥ N)      │                  │
│  └──────────────────┘  └──────────────────┘                  │
│           ↓                     ↓                             │
│  ┌──────────────────┐  ┌──────────────────┐                  │
│  │ Calibration Gate │  │ (Future)          │                  │
│  │ (win rate vs     │  │                  │                  │
│  │  prediction)     │  │                  │                  │
│  └──────────────────┘  └──────────────────┘                  │
│                                                               │
│  Persistence Layer (single schema, all systems)                │
│  ┌──────────────────────────────────────────────┐            │
│  │ system_health_monitor hypertable             │            │
│  │ • system_name (indexed)                      │            │
│  │ • health_check (ic_gate / conviction / ...)  │            │
│  │ • status (pass / warning / critical / fail)   │            │
│  │ • severity (numeric score)                    │            │
│  │ • halt_triggered (bool)                       │            │
│  │ • recovery_state machine                     │            │
│  └──────────────────────────────────────────────┘            │
│                                                               │
│  Action Layer (pluggable callbacks)                           │
│  ┌──────────────────────────────────────────────┐            │
│  │ Action registry (APR-configured):             │            │
│  │ • halt_emission → set flag, stop emitter     │            │
│  │ • reduce_size → multiply conviction by 0.5   │            │
│  │ • force_retrain → enqueue retrain job        │            │
│  │ • alert_operator → webhook/PagerDuty          │            │
│  │ • scale_workers → adjust pipeline concurrency │            │
│  └──────────────────────────────────────────────┘            │
│                                                               │
│  Observability Layer (built-in)                                │
│  ┌──────────────────────────────────────────────┐            │
│  │ • OTel Prometheus metrics (per-system)          │            │
│  │ • REST API: GET /api/health/:system           │            │
│  │ • Topic events: state transitions             │            │
│  └──────────────────────────────────────────────┘            │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Service Interface

### Registration (APR-Backed Configuration)

```python
# In migration or config script
await decay_service.register(
    name="alpha_ensemble",
    metrics_table="alpha_ensemble_ic",
    output_table="alpha_events",
    
    health_checks=[
        {
            "name": "ic_gate",
            "type": "metric_threshold",
            "description": "Ensemble IC predicts returns",
            "query": """
                SELECT ic_sharpe, walk_forward_stable, fdr_passed
                FROM alpha_ensemble_ic
                WHERE symbol=$1 AND tf=$2 AND regime=$3
                  AND scored_at > NOW() - INTERVAL '7 days'
                ORDER BY scored_at DESC LIMIT 1
            """,
            "query_params": ["symbol", "tf", "regime"],
            "thresholds": {
                "critical": {"ic_sharpe": 0.5, "action": "halt_emission"},
                "warning": {"ic_sharpe": 1.0, "action": "reduce_size"},
                "healthy": {"ic_sharpe": 1.0}
            },
            "required_conditions": {
                "walk_forward_stable": true,
                "fdr_passed": true
            },
            "check_interval_hours": 1
        },
        {
            "name": "conviction_stability",
            "type": "stability_check",
            "description": "Conviction scores are stable (not oscillating)",
            "query": """
                SELECT STDDEV(conviction) AS conviction_std,
                       COUNT(*) AS sample_count
                FROM alpha_events
                WHERE symbol=$1 AND tf=$2 
                  AND emitted_at > NOW() - INTERVAL '7 days'
                  AND conviction IS NOT NULL
            """,
            "query_params": ["symbol", "tf"],
            "thresholds": {
                "warning": {"conviction_std": 0.15, "action": "reduce_size"},
                "critical": {"conviction_std": 0.30, "action": "halt_emission"}
            },
            "min_sample_count": 50,
            "check_interval_hours": 4
        },
        {
            "name": "feature_coverage",
            "type": "coverage_check",
            "description": "Enough active features to form valid ensemble",
            "query": """
                SELECT COUNT(*) FILTER (WHERE is_decaying = false) AS active_count
                FROM feature_ic_scores
                WHERE symbol=$1 AND tf=$2 AND regime=$3
                  AND lookahead_bars=$4
                  AND passes_walkforward = true 
                  AND reliable = true
            """,
            "query_params": ["symbol", "tf", "regime", "lookahead_bars"],
            "thresholds": {
                "critical": {"active_count": 3, "action": "halt_emission"},
                "warning": {"active_count": 5, "action": "reduce_size"},
                "healthy": {"active_count": 5}
            },
            "check_interval_hours": 1
        }
    ],
    
    halt_action="stop_alpha_emitter",
    halt_action_params={"flag": "alpha.emitter.halted", "reason": "ensemble_health_failed"},
    
    observability={
        "prometheus_port": 9119,
        "api_route": "/api/health/alpha_ensemble"
    }
)
```

---

## Core Components

### 1. Health Check Algorithms (Pluggable Gate Types)

**Each gate type is a subclass:**

```python
class BaseHealthCheck(ABC):
    @abstractmethod
    async def check(self, conn, params: dict) -> HealthCheckResult:
        """Run health check, return status + severity."""
        pass

class MetricThresholdGate(BaseHealthCheck):
    """Check if metric crosses threshold (IC Sharpe, accuracy, latency)"""
    
    async def check(self, conn, params: dict) -> HealthCheckResult:
        result = await conn.fetchrow(self.config["query"], *params.values())
        
        ic_sharpe = result["ic_sharpe"]
        if ic_sharpe < self.config["thresholds"]["critical"]["ic_sharpe"]:
            return HealthCheckResult(
                status="critical",
                severity=1.0 - (ic_sharpe / 0.5),  # Scale 0-1
                metric_value=ic_sharpe,
                threshold_value=0.5,
                action="halt_emission"
            )
        elif ic_sharpe < self.config["thresholds"]["warning"]["ic_sharpe"]:
            return HealthCheckResult(
                status="warning",
                severity=1.0 - (ic_sharpe / 1.0),
                metric_value=ic_sharpe,
                threshold_value=1.0,
                action="reduce_size"
            )
        else:
            return HealthCheckResult(status="pass", severity=0.0)

class StabilityCheckGate(BaseHealthCheck):
    """Check stability via std/oscillation (conviction stability, prediction drift)"""
    
    async def check(self, conn, params: dict) -> HealthCheckResult:
        result = await conn.fetchrow(self.config["query"], *params.values())
        
        std = result["conviction_std"]
        sample_count = result["sample_count"]
        
        if sample_count < self.config.get("min_sample_count", 50):
            return HealthCheckResult(
                status="fail",
                severity=1.0,
                metric_value=std,
                reason="insufficient_sample_count"
            )
        
        if std > self.config["thresholds"]["critical"]["conviction_std"]:
            return HealthCheckResult(
                status="critical",
                severity=std / 0.30,
                metric_value=std,
                threshold_value=0.30,
                action="halt_emission"
            )
        elif std > self.config["thresholds"]["warning"]["conviction_std"]:
            return HealthCheckResult(
                status="warning",
                severity=std / 0.15,
                metric_value=std,
                threshold_value=0.15,
                action="reduce_size"
            )
        else:
            return HealthCheckResult(status="pass", severity=0.0)

class CoverageCheckGate(BaseHealthCheck):
    """Check minimum count (feature coverage, model training size, pipeline input)"""
    
    async def check(self, conn, params: dict) -> HealthCheckResult:
        result = await conn.fetchrow(self.config["query"], *params.values())
        
        count = result["active_count"]
        
        if count < self.config["thresholds"]["critical"]["active_count"]:
            return HealthCheckResult(
                status="critical",
                severity=1.0 - (count / 3),
                metric_value=count,
                threshold_value=3,
                action="halt_emission"
            )
        elif count < self.config["thresholds"]["warning"]["active_count"]:
            # Scale action by severity: 4/5 = 80% size, 3/5 = 60% size
            size_multiplier = count / self.config["thresholds"]["warning"]["active_count"]
            return HealthCheckResult(
                status="warning",
                severity=1.0 - size_multiplier,
                metric_value=count,
                threshold_value=5,
                action="reduce_size",
                action_params={"multiplier": size_multiplier}
            )
        else:
            return HealthCheckResult(status="pass", severity=0.0)

class DistributionCheckGate(BaseHealthCheck):
    """Check calibration (win rate vs prediction, distribution drift)"""
    
    async def check(self, conn, params: dict) -> HealthCheckResult:
        # Implementation for calibration checks
        # E.g., high-conviction events should win more often
        pass
```

---

### 2. Persistence Layer (Unified Schema)

**Table:** `system_health_monitor` (hypertable, same schema for all systems)

```sql
CREATE TABLE IF NOT EXISTS system_health_monitor (
    id                  BIGSERIAL       PRIMARY KEY,
    system_name         TEXT            NOT NULL,           -- alpha_ensemble, ml_model, etc.
    health_check        TEXT            NOT NULL,           -- ic_gate, conviction_stability, etc.
    symbol              TEXT,
    timeframe           TEXT,
    regime              TEXT,
    lookahead           TEXT,                               -- For ensemble lookahead-specific checks
    
    checked_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    
    -- Health check results
    status              TEXT            NOT NULL,           -- pass / warning / critical / fail
    severity            FLOAT,                          -- Numeric score (0-1), for sorting/prioritization
    metric_value        FLOAT,                          -- Raw metric (ic_sharpe, conviction_std, etc.)
    threshold_value     FLOAT,                          -- Threshold that was evaluated against
    metric_name         TEXT,                           -- Name of metric (ic_sharpe, conviction_std, etc.)
    
    -- Query results (for debugging)
    query_result        JSONB,                          -- Full query result for diagnostics
    
    -- Halt state
    halt_triggered      BOOLEAN         NOT NULL DEFAULT FALSE,
    halt_reason         TEXT,
    halt_action         TEXT,                           -- halt_emission, reduce_size, force_retrain, etc.
    halt_cleared_at     TIMESTAMPTZ,
    
    -- Recovery state machine
    recovery_checked_at TIMESTAMPTZ,
    recovery_attempts   INTEGER DEFAULT 0,
    recovery_required   BOOLEAN DEFAULT FALSE,
    
    UNIQUE(system_name, health_check, symbol, timeframe, regime, lookahead, checked_at)
);

SELECT create_hypertable(
    'system_health_monitor', 'checked_at',
    chunk_time_interval => INTERVAL '30 days',
    if_not_exists => TRUE
);

CREATE INDEX ix_system_health_monitor_system ON system_health_monitor(system_name, checked_at DESC);
CREATE INDEX ix_system_health_monitor_halt ON system_health_monitor(system_name, halt_triggered) 
    WHERE halt_triggered = TRUE;
CREATE INDEX ix_system_health_monitor_recovery ON system_health_monitor(
    system_name, symbol, timeframe, regime, recovery_checked_at DESC
) WHERE recovery_required = TRUE;
```

**New table:** `system_registry` (APR-backed configuration)

```sql
CREATE TABLE IF NOT EXISTS system_registry (
    system_name         TEXT            PRIMARY KEY,
    metrics_table       TEXT            NOT NULL,
    output_table        TEXT,
    health_checks       JSONB           NOT NULL,  -- Array of check configs
    halt_action         TEXT,
    halt_action_params  JSONB,
    observability       JSONB,
    registered_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    registered_by       TEXT            NOT NULL DEFAULT 'system'
);
```

---

### 3. Action Layer (Pluggable Callbacks)

**Action registry (APR-configured):**

```python
class BaseActionCallback(ABC):
    @abstractmethod
    async def execute(self, system: str, alert: HealthCheckResult) -> ActionOutcome:
        pass

class HaltEmission(BaseActionCallback):
    """Stop alpha event emission"""
    
    async def execute(self, system: str, alert: HealthCheckResult) -> ActionOutcome:
        # Set halt flag in config_state
        await self.config_service.set(
            f"alpha.emitter.halted",
            value=True,
            reason=f"{alert.health_check}: {alert.halt_reason}",
            metadata={
                "system": system,
                "symbol": alert.symbol,
                "tf": alert.timeframe,
                "severity": alert.severity,
                "checked_at": alert.checked_at.isoformat()
            }
        )
        return ActionOutcome(halted=True, reason=alert.halt_reason)

class ReduceSize(BaseActionCallback):
    """Reduce position sizing by multiplier"""
    
    async def execute(self, system: str, alert: HealthCheckResult) -> ActionOutcome:
        multiplier = alert.action_params.get("multiplier", 0.5)
        
        # Set size reduction in config_state
        await self.config_service.set(
            f"alpha.emitter.size_multiplier",
            value=multiplier,
            reason=f"{alert.health_check}: reducing to {multiplier*100}%"
        )
        return ActionOutcome(size_reduced=True, multiplier=multiplier)

class ForceRetrain(BaseActionCallback):
    """Enqueue system retrain job"""
    
    async def execute(self, system: str, alert: HealthCheckResult) -> ActionOutcome:
        # Add retrain job to queue
        await self.job_queue.enqueue(
            job_type="ensemble_retrain",
            priority="urgent",
            params={"symbol": alert.symbol, "tf": alert.timeframe},
            reason=alert.halt_reason
        )
        return ActionOutcome(retrain_queued=True)

class AlertOperator(BaseActionCallback):
    """Send alert to operations team"""
    
    async def execute(self, system: str, alert: HealthCheckResult) -> ActionOutcome:
        # Send webhook / PagerDuty alert
        await self.webhook.send({
            "system": system,
            "health_check": alert.health_check,
            "severity": alert.status,
            "symbol": alert.symbol,
            "tf": alert.timeframe,
            "reason": alert.halt_reason,
            "metric_value": alert.metric_value,
            "threshold": alert.threshold_value
        })
        return ActionOutcome(notified=True)
```

---

### 4. Recovery State Machine

**Renaissance-grade requirement:** Systems don't auto-recover on a single fluke pass. Require confirmation.

```python
# After health check fails, monitor runs recovery checks
if alert.status in ["warning", "critical"]:
    recovery_attempts += 1
    recovery_checked_at = now()
    
    # Re-test with fresh data
    new_alert = await health_check.check(conn, params)
    
    if new_alert.status == "pass":
        # Clean check
        if recovery_attempts >= 2:  # Require 2 consecutive clean checks
            recovery_required = True  # Flag for recovery action
            
            # Clear halt if triggered
            if halt_triggered:
                halt_cleared_at = now()
                await execute_action("clear_halt", system, alert)
    else:
        # Still failing, reset counter
        recovery_attempts = 0
```

---

### 5. Observability Layer (Built-In)

**Prometheus metrics (per-system):**

```
decay_health_check_status{system_name, health_check, status}  # 0=fail, 1=warning, 2=critical, 3=pass
decay_health_check_severity{system_name, health_check}  # Numeric score 0-1
decay_halt_triggered_total{system_name, health_check, reason}  # Cumulative halts
decay_recovery_attempt_total{system_name, health_check}  # Cumulative recovery attempts
decay_system_registry_size  # How many systems registered
```

**Grafana alert rules:**
- `decay_health_check_status{system_name="alpha_ensemble", health_check="ic_gate"} < 3`
- `decay_halt_triggered_total{system_name="alpha_ensemble"} > 0`

**API endpoint (per-system):**

```
GET /api/health/:system_name
```

**Response (example for alpha_ensemble):**

```json
{
  "system_name": "alpha_ensemble",
  "registered_at": "2026-06-27T10:00:00Z",
  "health_checks": ["ic_gate", "conviction_stability", "feature_coverage"],
  "overall_status": "critical",
  "halts_active": [
    {
      "health_check": "ic_gate",
      "severity": "critical",
      "symbol": "ES",
      "tf": "1m",
      "regime": "trending",
      "metric_value": 0.42,
      "threshold_value": 0.5,
      "status": "critical",
      "halt_reason": "ic_sharpe below critical floor",
      "halt_triggered_at": "2026-06-27T14:30:00Z",
      "recovery_attempts": 0,
      "recovery_checked_at": null
    }
  ],
  "warnings": [
    {
      "health_check": "feature_coverage",
      "severity": "warning",
      "symbol": "ES",
      "tf": "1m",
      "regime": "trending",
      "metric_value": 4,
      "threshold_value": 5,
      "status": "warning",
      "action": "reduce_size",
      "action_params": {"multiplier": 0.8},
      "checked_at": "2026-06-27T14:00:00Z"
    }
  ]
}
```

**Topic events (state transitions):**

```python
# Published on any state change
topic_system_health_transition()
event = SystemHealthTransitionEvent(
    system_name="alpha_ensemble",
    health_check="ic_gate",
    prior_status="pass",
    new_status="critical",
    symbol="ES", tf="1m", regime="trending",
    metric_value=0.42,
    threshold_value=0.5,
    halt_triggered=True,
    transitioned_at=now()
)
```

---

## Renaissance-Grade Requirements

**What makes this platform truly reusable:**

1. ✅ **All parameters APR-backed** — No hardcoded thresholds, windows, or intervals
2. ✅ **Pluggable gate types** — Easy to add new check types (distribution, calibration, custom)
3. ✅ **Pluggable actions** — Not just halt/reduce — alerts, scaling, retraining, custom callbacks
4. ✅ **Per-system isolation** — Each system has independent config, metrics, API routes
5. ✅ **Recovery state machine** — Not just halt expiry, but confirmed recovery (2 consecutive clean checks)
6. ✅ **Zero code changes for new systems** — Registration via APR migration
7. ✅ **Orthogonal to drift detection** — Separate services, independent concerns
8. ✅ **Unified schema** — Single `system_health_monitor` table for all systems

---

## Migration Strategy (v3.0)

### Phase 1: Service Foundation (One-Time Setup)

**Create the service infrastructure:**
1. `system_health_monitor` hypertable (with recovery columns)
2. `system_registry` table (APR-backed config)
3. Base classes: `BaseHealthCheck`, `BaseActionCallback`
4. Implement gate types: `MetricThreshold`, `StabilityCheck`, `CoverageCheck`, `DistributionCheck`
5. Implement actions: `HaltEmission`, `ReduceSize`, `ForceRetrain`, `AlertOperator`
6. `indicant-decay-monitor` service (generic, reads from registry)
7. OTel metrics + API endpoint (per-system routing)
8. Recovery state machine logic

**No AlphaEngine-specific code in this phase.** Just the platform.

---

### Phase 2: Register AlphaEngine Ensemble System

**Consuming the service:**
1. Insert `system_registry` row for "alpha_ensemble"
2. Configure 3 health checks: ic_gate, conviction_stability, feature_coverage
3. Configure thresholds and actions for each gate
4. Configure observability: port 9119, route `/api/health/alpha_ensemble`

**Service starts monitoring ensemble health automatically.** No code deployment needed.

---

### Phase 3: AlphaEmitter Integration

**Wire alpha_emitter to check service:**
```python
# Before emitting any alpha_event
health_status = await decay_service.get_health("alpha_ensemble", symbol, tf, regime)

if health_status["overall_status"] == "critical":
    # Skip emission, system halted
    return

if health_status["overall_status"] == "warning":
    # Apply size reduction
    size_multiplier = health_status.get("size_multiplier", 0.5)
    conviction *= size_multiplier

# Emit with adjusted conviction
```

That's it. Service handles health checks, actions, recovery. AlphaEmitter just queries and obeys.

---

### Future Systems: Zero Deployment

**Add ML model monitoring:**
1. Insert `system_registry` row for "ml_model_predictions"
2. Configure health checks: accuracy_gate, prediction_drift
3. Service auto-discovers on next check cycle
4. No deployment, no downtime

**Add data pipeline monitoring:**
1. Insert `system_registry` row for "data_pipeline_jobs"
2. Configure health checks: latency_gate, error_rate_gate
3. Zero code changes

**That's the Renaissance approach.**

---

## Relationship to Drift Detection Service

**Two independent, orthogonal platforms:**

```
┌─────────────────────────────────────────────────────────────┐
│                   Data Quality Layer                       │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ Drift Detection Service (KS, Chi-Squared)            │  │
│  │ • Monitors: Input data distributions                 │  │
│  │ • Question: "Is the data trustworthy?"             │  │
│  │ • Action: Reduce weight, don't trust                │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                   System Health Layer                      │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ Decay Detection Service (IC, Stability, Coverage)     │  │
│  │ • Monitors: System performance, output quality       │  │
│  │ • Question: "Is the system working?"                 │  │
│  │ • Action: Halt emission, retrain, reduce size        │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

**Cascade scenarios:**

| Drift Status | Decay Status | System Action |
|-------------|-------------|----------------|
| ✅ Clean | ✅ Healthy | Normal operation |
| ❌ Drifted | ✅ Healthy | Reduce weight (drift penalty) |
| ✅ Clean | ❌ Decayed | Halt emission (decay halt) |
| ❌ Drifted | ❌ Decayed | Halt + reduce weight (cascade) |

**Both services required.** A system needs:
1. Trustworthy input data (drift detection)
2. Healthy performance (decay detection)

Missing either → unacceptable risk.

---

## What Jim Simons Would Demand

> "You built drift detection as a service. Good. Now build decay detection as a service. They're orthogonal problems."
>
> "One platform. Many systems. Renaissance-grade infrastructure."
>
> "Don't build ensemble health checks into AlphaEngine. Build a decay detection service that AlphaEngine happens to use. Then use it for models, pipelines, strategies — everything."
>
> "All parameters APR-backed. Recovery state machine. Zero code changes for new systems. That's how you build infrastructure."

---

## APR Keys (All Parameters Tunable)

### AlphaEngine Ensemble Decay
```python
# E1: Ensemble IC Gate
alpha.ensemble.ic_sharpe_floor_critical = 0.5    # Critical floor
alpha.ensemble.ic_sharpe_floor_warning = 1.0     # Warning floor
alpha.ensemble.ic_stale_days = 7                 # Max staleness before fail

# E2: Conviction Reliability
alpha.ensemble.conviction_std_warning = 0.15      # Stability warning threshold
alpha.ensemble.conviction_std_critical = 0.30     # Stability critical threshold
alpha.ensemble.conviction_min_samples = 50        # Min samples for stability check

# E3: Feature Coverage
alpha.ensemble.min_feature_coverage_critical = 3   # Critical floor
alpha.ensemble.min_feature_coverage_warning = 5    # Warning floor

# Retraining
alpha.ensemble.retrain_interval_days = 30         # Scheduled retrain
alpha.ensemble.emergency_retrain_ic = 0.3          # Emergency retrain trigger

# Recovery
alpha.ensemble.recovery_consecutive_passes = 2    # Recovery confirmation
```

### ML Model Decay
```python
ml.model.accuracy_floor_critical = 0.70
ml.model.accuracy_floor_warning = 0.85
ml.model.drift_threshold = 0.10                    # KL divergence for prediction drift
ml.model.retrain_interval_days = 7
```

### Data Pipeline Decay
```python
pipeline.latency_warning_ms = 5000
pipeline.latency_critical_ms = 10000
pipeline.error_rate_critical = 0.05
pipeline.throughput_warning_mb = 10                # Below 10 MB/min = warning
```

### Service Configuration
```python
decay.check_interval_hours = 1                      # Default health check frequency
decay.recovery_check_interval_hours = 4             # Recovery re-test frequency
decay.recovery_consecutive_passes = 2               # Recovery confirmation for all systems
```

---

## Next Steps

1. **Formalize this concept** → Add to ROADMAP.md as v3.0 Phase 151A-151C
2. **Create implementation plan** → `docs/plans/2026-06-27-ensemble-lifecycle-implementation.md`
3. **Use `/gsd-plan-phase`** when ready to schedule implementation

**This is a reusable platform. Build it right, use it everywhere.**

---

## Success Criteria

A complete decay detection service should:

1. ✅ Halt emission when ensemble IC drops below floor (E1 gate)
2. ✅ Halt emission when conviction scores oscillate (E2A gate)
3. ✅ Reduce size when convictions poorly calibrated (E2B gate)
4. ✅ Halt emission when feature coverage drops below floor (E3 gate)
5. ✅ All three gates must pass for emission (AND logic, not OR)
6. ✅ Recovery requires 2 consecutive clean checks
7. ✅ Prometheus metrics visible per-system
8. ✅ `/api/health/:system` returns system status
9. ✅ Topic events published on state transitions
10. ✅ All thresholds APR-backed (tunable without migrations)
11. ✅ Zero code changes to register new systems
12. ✅ Survive feature decay without intervention (cascade scenarios)
13. ✅ Detect ensemble IC decay even when individual features are healthy
14. ✅ Pluggable gate types (easy to add new check algorithms)
15. ✅ Pluggable actions (easy to add new responses)

---

## Renaissance Validation Requirements

**What Renaissance would demand before deployment:**

> "You designed three health gates. Great. Now show me they work. Backtest on historical periods where ensemble IC degraded. Show me false positive rate. Show me latency benchmarks. Engineering requires proof, not intuition."
> — Jim Simons (paraphrased)

---

### Phase 0: Proof (Must Have Before Deployment)

**Historical Validation:**
1. ✅ **Backtest on 3 ensemble IC degradation events**
   - Event 1: Feature decay cascade (5+ features decayed simultaneously)
   - Event 2: Regime shift with low IC (trending → ranging transition)
   - Event 3: Volatility spike with high conviction variance
   - Required: "E1 gate fired within 1h, halt emission prevented bad trades"
   - Deliverable: `tests/integration/test_ensemble_health_historical_events.py`

2. ✅ **False positive analysis (expected value calculation)**
   - E1: `ic_sharpe<0.5` threshold — what's FP rate?
   - E2A: `conviction_std>0.30` — how often during stable periods?
   - E3: `active_count<3` — any false alarms during normal operation?
   - Required: Each gate's `false_positive_rate × action_cost < true_positive_rate × loss_prevented`
   - Deliverable: `analysis/ensemble_health_economic_impact.ipynb`

3. ✅ **Latency benchmark (prove it's fast enough)**
   - Benchmark: 3 gates × 58 symbols × 4 timeframes × 3 regimes
   - SLO: `all gates complete in <100ms p95` (must not block emission)
   - If SLO violated → gate checks run in background, emission uses cached result
   - Deliverable: `tests/benchmarks/test_health_gate_latency.py`

**Stress Testing:**
4. ✅ **Validate on 3 historical crises**
   - Crisis 1: 2020-03 COVID crash (ensemble IC collapsed?)
   - Crisis 2: 2022-10 vol spike (conviction scores unstable?)
   - Crisis 3: Correlation breakdown (individual features OK, ensemble failed?)
   - Required: "Gates fired correctly, no false alarms during stable periods"
   - Deliverable: `tests/integration/test_ensemble_health_stress_scenarios.py`

---

### Phase 1: Calibration (High Value)

**Parameter Calibration (Replace Magic Numbers):**
5. ✅ **E1 thresholds calibrated from historical ensemble IC**
   - Current: `ic_sharpe<0.5` (critical), `<1.0` (warning) — arbitrary
   - Required: "Analyze last 12 months of alpha_ensemble_ic, find IC values at known degradation events"
   - Example: "ic_sharpe<0.3 caught 85% of decay events with 5% FP rate"
   - Deliverable: `analysis/ensemble_ic_threshold_calibration.ipynb`

6. ✅ **E2A conviction std threshold from data**
   - Current: `conviction_std>0.30` — based on what distribution?
   - Required: "Plot conviction_std over last 6 months, find 95th percentile during stable periods"
   - If `std` is lognormally distributed, use log-scale thresholds
   - Deliverable: `analysis/conviction_stability_distribution.ipynb`

7. ✅ **Recovery state machine simulation**
   - Simulate 1000 ensemble recovery cycles (synthetic IC degradation + recovery)
   - Measure: False recovery rate (gate clears but IC still bad)
   - Test: "2 consecutive clean checks" vs "3 out of 5 checks" vs "timeout 7d"
   - Deliverable: `analysis/ensemble_recovery_simulation.ipynb`

8. ✅ **Gate independence analysis**
   - Question: "Should gates be independent (OR logic) or coupled (AND logic)?"
   - Scenario: E1 passes (IC good) but E3 fails (coverage low) → halt emission?
   - Current: "All gates must pass (AND)" — measure if this is optimal
   - Alternative: Weighted voting (E1=50%, E2=30%, E3=20%)
   - Deliverable: `analysis/gate_decision_logic_evaluation.ipynb`

---

### Phase 2: Observability (Required)

**Critical Missing Metrics:**
9. ✅ **False recovery tracking**
    - Metric: `health_recovery_false_positive_total{gate_name}`
    - Definition: Recovery cleared but next check shows degradation again
    - Alert if: `false_positive_rate > 0.15` (15% of recoveries are fake)

10. ✅ **Emission impact tracking**
    - Metric: `health_halted_emissions_total{gate_name, reason}`
    - Metric: `health_reduced_size_total{gate_name, reduction_multiplier}`
    - Distinguish: `halt_prevented_loss` vs `halt_missed_opportunity`

11. ✅ **Gate correlation tracking**
    - Metric: `health_gate_correlation{gate_a, gate_b}`
    - Question: "Do E2 and E3 always fire together? If yes, they're not orthogonal"
    - Alert if: `correlation > 0.7` (gates redundant, consider combining)

12. ✅ **AlphaEmitter integration testing**
    - Test: `AlphaEmitter` queries health service before emission
    - Verify: Halt actually stops emission (not cached)
    - Verify: Size reduction actually multiplies conviction
    - Deliverable: `tests/integration/test_alphaemitter_health_integration.py`

---

### Phase 1 Extensions: Conviction Calibration

13. ✅ **E2B calibration monotonicity test**
    - Current: "Win rate not monotonically increasing across conviction deciles"
    - Test: Generate synthetic data where high conviction ≠ high win rate
    - Verify: Gate fires correctly (halts emission)
    - Deliverable: `tests/integration/test_conviction_calibration_gate.py`

14. ✅ **E2C distribution health from empirical data**
    - Current thresholds: `low<0.60, high<0.10, mean∈[0.3,0.7]` — arbitrary
    - Required: "Analyze actual conviction distribution from alpha_events, set thresholds at 5th/95th percentiles"
    - Deliverable: `analysis/conviction_distribution_empirical.ipynb`

---

### Decision Framework: Gate Independence vs Coupling

**Renaissance analysis question:**
> "Is the current AND logic correct? If IC is good but coverage is low, should we halt? Or reduce size? Or continue with warning?"

**Required analysis:**
1. Historical periods where:
   - E1 failed, E2 passed, E3 passed (ensemble IC bad, conviction stable, coverage OK)
   - E1 passed, E2 failed, E3 passed (ensemble IC OK, conviction unstable, coverage OK)
   - E1 passed, E2 passed, E3 failed (ensemble IC OK, conviction stable, coverage low)

2. For each scenario, answer:
   - What did OOS performance look like?
   - Did halting prevent losses or miss opportunities?
   - What decision logic would have been optimal?

**Deliverable:** `docs/analysis/gate_independence_decision_matrix.md` with recommendation on AND vs OR vs weighted voting logic.
