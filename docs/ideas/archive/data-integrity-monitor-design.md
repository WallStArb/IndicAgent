# Drift Detection Service — Reusable Platform Design

**Date:** 2026-06-26
**Status:** SUPERSEDED 2026-06-27 — consolidated into `docs/plans/archive/2026-06-27-health-guardian-design.md` (Phase 149A DistributionDriftMonitor), itself now superseded by `docs/ideas/intel-14-integrity-monitor.md`. Kept for design rationale only; do not build from this doc.
**Type:** Service architecture concept

---

## What This Is

A **general-purpose drift detection platform** that can monitor any time-series data for:
- Distribution drift (KS test on continuous features, chi-squared on categorical)
- Performance decay (IC erosion, walkforward failures)
- System degradation (CUSUM on ensemble outputs)

**First consumer:** v3.0 `feature_vectors` (47 continuous + 7 categorical features)

**Future consumers:**
- ML model predictions in production
- Data pipeline quality metrics
- Alternative data feeds (sentiment, earnings, etc.)
- Any ensemble system's member performance

---

## Design Principle: Don't Build One-Off Detection

> "You had distribution drift detection working in v2.x and dropped it. Why? Data drift is inevitable. You need automated detection or you'll trade on corrupted data for weeks."
>
> **"But don't build it for features. Build a drift detection service that features happen to use. Then use it for models, pipelines, feeds — everything."**
> — Jim Simons (paraphrased)

**The Renaissance approach:**
1. Build the **detection engine once**, with clean interfaces
2. Configure it per **data stream via APR**, not code changes
3. Make it **observable by default** (OTel metrics, API endpoint)
4. Make the **action layer pluggable** (penalties, alerts, halts)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    Drift Detection Service                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  Registration Interface (APR-backed config)                     │
│  ┌─────────────────────────────────────────────┐               │
│  │ register_stream(                             │               │
│  │   name="feature_vectors",                   │               │
│  │   table="feature_vectors",                  │               │
│  │   detection_layers=["ks", "ic_decay"],      │               │
│  │   features={continuous: [...], cat: [...]}, │               │
│  │   action="ensemble_weight_penalty"          │               │
│  │ )                                           │               │
│  └─────────────────────────────────────────────┘               │
│                                                               │
│  Detection Layer (pluggable algorithms)                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ KS Test      │  │ Chi-Squared  │  │ CUSUM        │       │
│  │ (continuous) │  │ (categorical)│  │ (ensemble)   │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
│           ↓                  ↓                  ↓              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ IC Decay     │  │ (Future)     │  │ (Future)     │       │
│  │ (lifecycle)  │  │              │  │              │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
│                                                               │
│  Persistence Layer (single schema, all streams)               │
│  ┌──────────────────────────────────────────────┐            │
│  │ drift_monitor hypertable                      │            │
│  │ • stream_name (indexed)                       │            │
│  │ • check_type (ks / chi_sq / ic_decay / cusum)│            │
│  │ • severity (warning / critical)               │            │
│  │ • recovery_checked_at (auto-recovery state)  │            │
│  └──────────────────────────────────────────────┘            │
│                                                               │
│  Action Layer (pluggable callbacks)                           │
│  ┌──────────────────────────────────────────────┐            │
│  │ Action registry (APR-configured):             │            │
│  │ • ensemble_weight_penalty → query DB         │            │
│  │ • alert_operator → webhook/PagerDuty         │            │
│  │ • halt_emission → set flag                    │            │
│  │ • custom_callback → Python function           │            │
│  └──────────────────────────────────────────────┘            │
│                                                               │
│  Observability Layer (built-in)                                │
│  ┌──────────────────────────────────────────────┐            │
│  │ • OTel Prometheus metrics (port-configured)  │            │
│  │ • REST API: GET /api/drift/:stream            │            │
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
await drift_service.register(
    name="feature_vectors",
    table="feature_vectors",
    detection_layers=["ks_distribution", "ic_decay", "cusum_ensemble"],

    continuous_features=[
        "rsi_fast", "rsi_mid", "rsi_slow",
        "momentum_z_fast", "momentum_z_mid", "momentum_z_slow",
        "aroon_fast", "aroon_slow", "aroon_oscillator",
        # ... 38 more
    ],

    categorical_features=[
        "day_of_week", "month", "hour",  # Calendar
        "hmm_regime"                       # Regime classification
    ],

    action="ensemble_weight_penalty",
    action_params={
        "warning": 0.80,   # 20% reduction
        "critical": 0.60   # 40% reduction
    },

    ks_config={
        "reference_window_days": 29,
        "current_window_days": 7,
        "p_value_threshold": 0.05,
        "effect_size_threshold": 0.10,
        "min_sample": 50,
        "check_interval_hours": 4
    },

    ic_decay_config={
        "decay_ic_sharpe_threshold": 0.0,
        "cooldown_days": 30
    },

    observability={
        "prometheus_port": 9118,
        "api_route": "/api/drift/feature_vectors"
    }
)
```

### Future Reuse: Other Data Streams

```python
# ML model drift monitoring
await drift_service.register(
    name="ml_model_predictions",
    table="model_predictions",
    detection_layers=["ks_distribution", "cusum_performance"],

    continuous_features=["prediction_confidence", "feature_drift_score"],
    categorical_features=["model_version", "deployment_region"],

    action="alert_operator",
    action_params={
        "webhook": "https://ops.internal/alert",
        "pagerduty_service": "ml-models"
    }
)

# Alternative data feed quality
await drift_service.register(
    name="alternative_data_sentiment",
    table="external_sentiment",
    detection_layers=["ks_distribution"],

    continuous_features=["sentiment_score", "source_count", "volume"],
    categorical_features=["source_category", "language"],

    action="halt_ingestion",
    action_params={"reason": "Data quality degradation detected"}
)
```

---

## Core Components

### 1. Detection Engine (Pluggable Algorithms)

**Each detection algorithm is a subclass:**

```python
class BaseDetectionAlgorithm(ABC):
    @abstractmethod
    async def check(self, data: pd.DataFrame) -> DetectionResult:
        """Run detection, return severity + metadata."""
        pass

class KSDistributionCheck(BaseDetectionAlgorithm):
    async def check(self, data: pd.DataFrame) -> DetectionResult:
        # KS test on continuous columns
        reference = data[data["ts"] >= NOW() - timedelta(days=29)]
        current = data[data["ts"] >= NOW() - timedelta(days=7)]

        for feature in self.features:
            ks_stat, ks_p = scipy.stats.ks_2samp(
                reference[feature], current[feature]
            )

            if ks_p < 0.05 and ks_stat > 0.10 and len(current) >= 50:
                severity = "critical" if ks_stat >= 0.25 else "warning"
                return DetectionResult(
                    check_type="ks_distribution",
                    severity=severity,
                    feature_name=feature,
                    ks_statistic=ks_stat,
                    ks_pvalue=ks_p
                )

class ChiSquaredCategoricalCheck(BaseDetectionAlgorithm):
    async def check(self, data: pd.DataFrame) -> DetectionResult:
        # Chi-squared test on categorical columns
        # Similar structure to KS test

class ICLifecycleCheck(BaseDetectionAlgorithm):
    async def check(self, data: pd.DataFrame) -> DetectionResult:
        # Compare current IC run vs prior row
        # Detect active → decaying transition

class CUSUMEnsembleCheck(BaseDetectionAlgorithm):
    async def check(self, data: pd.DataFrame) -> DetectionResult:
        # CUSUM on ensemble IC (or any performance metric)
```

**Registration maps algorithm to stream:**

```python
# Internally stored in drift_stream_registry table
stream_config = await conn.fetchrow("SELECT * FROM drift_stream_registry WHERE name=$1", name)

# Instantiate configured algorithms
detectors = []
if "ks_distribution" in stream_config["detection_layers"]:
    detectors.append(KSDistributionCheck(
        features=stream_config["continuous_features"],
        config=stream_config["ks_config"]
    ))
if "ic_decay" in stream_config["detection_layers"]:
    detectors.append(ICLifecycleCheck(config=stream_config["ic_decay_config"]))
```

---

### 2. Persistence Layer (Unified Schema)

**Table:** `drift_monitor` (hypertable, same schema for all streams)

```sql
CREATE TABLE IF NOT EXISTS drift_monitor (
    id                  BIGSERIAL       PRIMARY KEY,
    stream_name         TEXT            NOT NULL,           -- NEW: Which stream
    check_type          TEXT            NOT NULL,           -- ks / chi_sq / ic_decay / cusum
    symbol              TEXT,
    timeframe           TEXT,
    feature_name        TEXT,

    checked_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- KS / Chi-Squared fields (distribution drift)
    ks_statistic        FLOAT,
    ks_pvalue           FLOAT,
    chi_sq_statistic    FLOAT,              -- NEW
    chi_sq_pvalue       FLOAT,              -- NEW
    reference_n         INTEGER,
    current_n           INTEGER,

    -- IC decay fields (lifecycle state)
    prior_state         TEXT,               -- NEW: "active", "decaying"
    new_state           TEXT,               -- NEW
    trigger_reason      TEXT,               -- NEW

    -- CUSUM fields (performance drift)
    cusum_pos           FLOAT,
    cusum_neg           FLOAT,
    cusum_threshold    FLOAT,
    baseline_mean       FLOAT,
    baseline_std        FLOAT,
    total_outcomes      INTEGER,

    -- Recovery state machine (NEW)
    recovery_checked_at TIMESTAMPTZ,        -- Last re-test for recovery
    penalty_cleared_at  TIMESTAMPTZ,        -- When penalty was cleared
    recovery_attempts   INTEGER DEFAULT 0,  -- How many recovery checks run

    -- Shared
    alert_triggered     BOOLEAN         NOT NULL DEFAULT FALSE,
    alert_severity      TEXT,               -- warning / critical
    alert_message       TEXT
);

SELECT create_hypertable(
    'drift_monitor', 'checked_at',
    chunk_time_interval => INTERVAL '30 days',
    if_not_exists => TRUE
);

CREATE INDEX ix_drift_monitor_stream_checked ON drift_monitor(stream_name, checked_at DESC);
```

**New table:** `drift_stream_registry` (APR-backed configuration)

```sql
CREATE TABLE IF NOT EXISTS drift_stream_registry (
    stream_name         TEXT            PRIMARY KEY,
    table_name          TEXT            NOT NULL,
    detection_layers     TEXT[]          NOT NULL,  -- ["ks", "ic_decay", "cusum"]
    continuous_features TEXT[]          NOT NULL,
    categorical_features TEXT[]         NOT NULL,
    action              TEXT            NOT NULL,
    action_params       JSONB,
    ks_config           JSONB,
    chi_sq_config       JSONB,
    ic_decay_config     JSONB,
    cusum_config        JSONB,
    observability       JSONB,
    registered_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);
```

---

### 3. Action Layer (Pluggable Callbacks)

**Action registry (APR-configured):**

```python
class BaseActionCallback(ABC):
    @abstractmethod
    async def execute(self, alert: DetectionResult) -> ActionOutcome:
        pass

class EnsembleWeightPenalty(BaseActionCallback):
    async def execute(self, alert: DetectionResult) -> ActionOutcome:
        # Query drift_monitor for active penalties
        penalty = await self.get_current_penalty(alert.stream_name, alert.symbol, alert.tf)

        # Return penalty value (consumer applies it)
        return ActionOutcome(penalty_multiplier=penalty)

class AlertOperator(BaseActionCallback):
    async def execute(self, alert: DetectionResult) -> ActionOutcome:
        # Send webhook / PagerDuty alert
        await self.webhook.send({
            "stream": alert.stream_name,
            "severity": alert.severity,
            "feature": alert.feature_name,
            "message": alert.message
        })
        return ActionOutcome(notified=True)

class HaltIngestion(BaseActionCallback):
    async def execute(self, alert: DetectionResult) -> ActionOutcome:
        # Set flag in config_state to stop ingestion
        await self.config_service.set(
            f"ingestion.{alert.stream_name}.halted",
            value=True,
            reason=alert.message
        )
        return ActionOutcome(halted=True)
```

**Consumer (ensemble_trainer) queries action outcome:**

```python
# Get current penalties from drift detection service
penalties = await drift_service.get_penalties("feature_vectors", symbol="ES", tf="1m")

# Apply to features before ensemble weighting
for feature in features:
    feature.adjusted_ic = feature.ic * penalties.get("distribution", 1.0)
```

---

### 4. Observability Layer (Built-In)

**Prometheus metrics (per-stream):**

```
drift_detection_check_duration_seconds{stream_name, check_type}
drift_alert_total{stream_name, severity, feature}
drift_penalty_active{stream_name, symbol, timeframe}
drift_recovery_attempt_total{stream_name, feature}
drift_stream_registry_size  # How many streams registered
```

**API endpoint (per-stream):**

```
GET /api/drift/:stream_name
```

**Response (example for feature_vectors):**

```json
{
  "stream_name": "feature_vectors",
  "registered_at": "2026-06-26T10:00:00Z",
  "detection_layers": ["ks_distribution", "ic_decay"],
  "active_alerts": [
    {
      "check_type": "ks_distribution",
      "severity": "warning",
      "symbol": "ES",
      "timeframe": "1m",
      "feature": "rsi_fast",
      "ks_statistic": 0.18,
      "ks_pvalue": 0.003,
      "penalty_active": 0.80,
      "checked_at": "2026-06-26T14:00:00Z",
      "recovery_checked_at": null,
      "recovery_attempts": 0
    }
  ],
  "ic_decay_alerts": [
    {
      "feature_name": "momentum_z_mid",
      "symbol": "ES",
      "tf": "1m",
      "regime": "trending",
      "ic_sharpe": 0.0,
      "state_transition": "active → decaying",
      "trigger_reason": "ic_walkforward_failed",
      "decayed_at": "2026-06-26T12:00:00Z",
      "recovery_eligible_at": "2026-07-26T12:00:00Z"
    }
  ]
}
```

**Topic events (state transitions):**

```python
# Published on any state change
topic_drift_state_transition()
event = DriftStateTransitionEvent(
    stream_name="feature_vectors",
    check_type="ks_distribution",
    prior_state="normal",
    new_state="warning",
    feature="rsi_fast",
    symbol="ES", tf="1m",
    transitioned_at=now()
)
```

---

## Renaissance-Grade Requirements

**What makes this platform truly reusable:**

1. ✅ **All parameters APR-backed** — No hardcoded windows, thresholds, or penalties
2. ✅ **Complete feature coverage** — KS test on 54 features (47 continuous + 7 categorical) from day one
3. ✅ **Recovery state machine** — Not just penalty expiry, but confirmed recovery
4. ✅ **Adaptive penalties** — Scale by effect size (ks_statistic 0.10→0.80, 0.25→0.60, 0.50→0.40)
5. ✅ **Pluggable algorithms** — Easy to add new detection types (e.g., Isolation Forest for outliers)
6. ✅ **Pluggable actions** — Not just ensemble penalties — alerts, halts, custom callbacks
7. ✅ **Stream isolation** — Each data stream has independent config, metrics, API routes
8. ✅ **Zero code changes for new streams** — Registration via APR migration

---

## Migration Strategy (v3.0)

### Phase 1: Service Foundation (One-Time Setup)

**Create the service infrastructure:**
1. `drift_monitor` hypertable (with new recovery columns)
2. `drift_stream_registry` table (APR-backed config)
3. Base classes: `BaseDetectionAlgorithm`, `BaseActionCallback`
4. Implement core algorithms: KS, Chi-Squared, IC Decay, CUSUM
5. Implement core actions: EnsembleWeightPenalty, AlertOperator, HaltIngestion
6. `indicant-drift-monitor` service (generic, reads from registry)
7. OTel metrics + API endpoint (per-stream routing)

**No feature_vectors-specific code in this phase.** Just the platform.

---

### Phase 2: Register feature_vectors Stream

**Consuming the service:**
1. Insert `drift_stream_registry` row for "feature_vectors"
2. Configure detection layers: KS, IC Decay, CUSUM
3. Configure all 54 features (47 continuous + 7 categorical)
4. Configure action: ensemble_weight_penalty
5. Configure observability: port 9118, route `/api/drift/feature_vectors`

**Service starts monitoring automatically.** No code deployment needed.

---

### Phase 3: Ensemble Integration

**Wire ensemble_trainer to query service:**
```python
penalties = await drift_service.get_penalties("feature_vectors", symbol, tf)
```

That's it. Service handles the rest.

---

### Future Streams: Zero Deployment

**Add ML model monitoring:**
1. Insert `drift_stream_registry` row for "ml_model_predictions"
2. Service auto-discovers on next check cycle
3. No deployment, no downtime

**That's the Renaissance approach.**

---

## What Jim Simons Would Say

> "This is how you build infrastructure. Once. Reuse it everywhere. Don't write drift detection five times — write it once, configure it five times."
>
> "All parameters APR-backed? Good. Complete coverage from day one? Good. Recovery state machine? Good."
>
> "Now ship it. Then use it for everything."

---

## Renaissance Validation Requirements

**What Renaissance would demand before deployment:**

> "Good architecture is not enough. Engineering requires proof. Show me the backtest where drift detection prevented losses. Show me the false positive rate. Show me the latency benchmark. Without validation, this is theory, not production engineering."
> — Jim Simons (paraphrased)

---

### Phase 0: Proof (Must Have Before Deployment)

**Historical Validation:**
1. ✅ **Backtest on 3 known data corruption events**
   - Event 1: IBKR field change (e.g., new `adjusted_close` column added)
   - Event 2: Instrument roll without notice (symbol delisted)
   - Event 3: Data pipeline bug (null values in price column)
   - Required: "KS test fired within 4h, penalty prevented X bad trades"
   - Deliverable: `tests/integration/test_drift_detection_historical_events.py`

2. ✅ **False positive analysis (expected value calculation)**
   - p<0.05 means 5% false positives by definition
   - Calculate: `false_positive_rate × penalty_cost = economic_drag`
   - Calculate: `true_positive_rate × loss_prevented = economic_benefit`
   - Required: `net_benefit > 0` with 95% CI
   - Deliverable: `analysis/drift_detection_economic_impact.ipynb`

3. ✅ **Latency benchmark (prove it's fast enough)**
   - Benchmark: KS test on 54 features × 58 symbols × 4 timeframes
   - SLO: `check completes in <50ms p95` (4h interval allows this budget)
   - If SLO violated → batch to nightly, not every 4h
   - Deliverable: `tests/benchmarks/test_ks_latency.py`

**Stress Testing:**
4. ✅ **Validate on 3 historical crises**
   - Crisis 1: 2020-03 COVID crash (volatility spike, regime shift)
   - Crisis 2: 2022-10 vol spike (inflation surprise)
   - Crisis 3: 2023-03 banking crisis (correlation breakdown)
   - Required: "KS test fired on regime change, no false alarms during stable period"
   - Deliverable: `tests/integration/test_drift_stress_scenarios.py`

---

### Phase 1: Calibration (High Value)

**Parameter Calibration (Replace Magic Numbers):**
5. ✅ **KS thresholds calibrated from historical data**
   - Current: `p_value_threshold=0.05, effect_size_threshold=0.10` (arbitrary)
   - Required: "Analyze last 12 months of feature_vectors, find KS statistic values at known corruption events"
   - Example: "KS > 0.15 caught 90% of corruption events with 10% FP rate"
   - Deliverable: `analysis/ks_threshold_calibration.ipynb`

6. ✅ **Chi-squared sample size calculation**
   - Current: `min_sample=50` (naive)
   - Required: `n ≥ 5 × degrees_of_freedom` for chi-squared validity
   - For 5-level categorical: `min_sample=25` per cell
   - Deliverable: Update APR key with calculated minimum

7. ✅ **Recovery state machine simulation**
   - Simulate 1000 recovery cycles (synthetic decay + recovery events)
   - Measure: false recovery rate (system says recovered but hasn't)
   - Current: "2 consecutive clean checks" — measure if this is optimal
   - Alternative: "2 consecutive OR 3 out of 5" (more adaptive)
   - Deliverable: `analysis/recovery_state_machine_simulation.ipynb`

8. ✅ **Cascade failure analysis**
   - Scenario: DataIntegrityMonitor (penalty 0.60) + PredictiveDecayDetector (is_decaying=true) fire simultaneously
   - Current behavior: Feature weight → 0, feature excluded
   - Question: "Is this correct? Or should penalties be independent?"
   - Required: Cascade failure matrix + decision logic spec
   - Deliverable: `docs/analysis/cascade_failure_modes.md`

---

### Phase 2: Observability (Required)

**Critical Missing Metrics:**
9. ✅ **False recovery tracking**
   - Metric: `drift_recovery_false_positive_total{stream_name}`
   - Definition: Recovery triggered but KS statistic still > threshold on next check
   - Alert if: `false_positive_rate > 0.20` (20% of recoveries are fake)

10. ✅ **Economic impact tracking**
    - Metric: `drift_penalty_economic_impact_usd{stream_name}`
    - Calculation: `sum(penalty_amount × feature_weight × pnl_r)`
    - Distinguish: `true_positive_prevented_loss` vs `false_positive_cost`

11. ✅ **Cascade shutdown tracking**
    - Metric: `drift_cascade_shutdown_total{triggering_services}`
    - Definition: All three monitoring services fired within 1h window
    - Alert if: `rate > 0.01 per day` (system too sensitive)

12. ✅ **Backtesting methodology validation**
    - Proof: Walkforward validation has no lookahead bias
    - Test: Temporal holdout (train on t-30 to t-7, validate on t-6 to t)
    - Audit: Scan code for `data leakage` (future info in training)
    - Deliverable: `tests/validation/test_walkforward_no_lookahead.py`

---

## Next Steps

1. **Formalize this concept** → Add to ROADMAP.md as v3.0 Phase 149A-150
2. **Update the 3 planning docs** with Renaissance-grade requirements
3. **Use `/gsd-plan-phase`** when ready to schedule implementation

**This is a reusable platform. Build it right, use it everywhere.**
