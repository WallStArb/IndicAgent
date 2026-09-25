# Signal Pipeline DAG Refactor & Renaissance-Grade Observability

**Last Updated:** 2026-05-02

**Status:** Design Spec (Revised)
**Created:** 2026-03-19
**Author:** Claude + User
**Milestone:** v2.0 — Signal Integrity & ML Foundation

---

## Executive Summary

**Refactor the signal pipeline from a monolithic aggregator to a clean DAG of independent microservices, then add Renaissance-grade observability: performance attribution, live A/B experimentation, causal inference, data quality monitoring, and fault tolerance.**

**Problem:** The current signal pipeline violates core architectural principles:
- **Monolithic:** `signal_generator_service.py` and `aggregator.py` do everything (plugins, quality gates, TOD, calibration, aggregation, winner selection)
- **Not a DAG:** Sequential processing in one function, not composable stages
- **Poor separation of concerns:** Quality gates, TOD multipliers, and calibration all mixed together
- **No observability:** Can't see which stages add value, which suppress winners
- **No experimentation:** Can't A/B test stage configurations
- **No fault tolerance:** If one stage fails, entire pipeline fails

**Solution:**
1. **Phase 0:** Refactor into DAG microservices (clean architecture)
2. **Phase 1-5:** Add Renaissance-grade observability on clean foundation

**Renaissance principles:**
- **Instrument everything** — Every decision, transformation, and attribution tracked
- **Let the system run** — Fully automated feedback loops, no manual reviews
- **Earn the right** — Statistical proof (p < 0.05) before any change
- **Segment relentlessly** — Regime/context-specific analysis
- **Degrade gracefully** — Fault tolerance with circuit breakers
- **Data quality over model complexity** — Validation at each stage
- **Never drop data** — Full retention of all intermediate outputs

---

## Architecture: DAG Microservices

### Current (Monolithic)

```
signal_generator_service.py
  └── aggregator.aggregate()
        ├── _regime_gate_signals()
        ├── _build_all_ranked()
        │     ├── Apply Hurst×Entropy
        │     ├── Apply drift penalty
        │     ├── Apply TOD multiplier
        │     ├── Apply isotonic calibration
        │     └── Sort by adjusted_rank
        ├── _aggregate_via_cis()
        └── _aggregate_fallback()
```

**Problems:**
- One function does everything
- Hard to test independently
- Can't deploy/stage independently
- No fault isolation
- Poor observability

### Proposed (DAG Microservices)

```
┌─────────────────────────────────────────────────────────────────┐
│                    Signal Pipeline (DAG)                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────┐    ┌─────────────┐    ┌────────────────────┐    │
│  │ Plugins  │───→│ QualityGate │───→│  RegimeGate        │    │
│  │ Service  │    │  Service    │    │  Service           │    │
│  └──────────┘    └─────────────┘    └────────────────────┘    │
│                                           ↓                     │
│  ┌────────────────────────────────────────────────────────┐   │
│  │           Performance Attribution Service              │   │
│  │     (collects metrics from all stages in parallel)      │   │
│  └────────────────────────────────────────────────────────┘   │
│                                           ↓                     │
│  ┌─────────────┐    ┌─────────────┐    ┌────────────────────┐    │
│  │ TODAdjuster │───→│ Calibrator  │───→│  Ranker            │    │
│  │  Service    │    │  Service    │    │  Service           │    │
│  └─────────────┘    └─────────────┘    └────────────────────┘    │
│                                           ↓                     │
│  ┌────────────────────────────────────────────────────────┐   │
│  │           Data Quality Monitor Service                 │   │
│  │     (validates data at each stage, alerts on issues)    │   │
│  └────────────────────────────────────────────────────────┘   │
│                                           ↓                     │
│  ┌────────────────────────────────────────────────────────┐   │
│  │              WinnerSelector Service                    │   │
│  └────────────────────────────────────────────────────────┘   │
│                                           ↓                     │
│  ┌────────────────────────────────────────────────────────┐   │
│  │              SignalLedger Service (writes DB)          │   │
│  └────────────────────────────────────────────────────────┘   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Stage Definitions

Each stage is an **independent microservice**:

```python
# src/intelligence/stages/quality_gate.py
class QualityGateService:
    """
    Applies Hurst×Entropy and KS drift penalty multipliers.

    Inputs: intelligence:SYMBOL:TF
    Outputs: quality_gated:SYMBOL:TF
    Side-outputs: attribution:SYMBOL:TF (performance metrics)

    Fault tolerance: If crashes, bypass with warning and pass-through.
    """

    def __init__(self):
        self.consumer = KafkaConsumer("intelligence:SYMBOL:TF")
        self.producer = KafkaProducer("quality_gated:SYMBOL:TF")
        self.attribution_producer = KafkaProducer("attribution:SYMBOL:TF")
        self.circuit_breaker = CircuitBreaker(failure_threshold=5, timeout_sec=60)

    async def process(self, event: IntelligenceEvent) -> dict:
        """Apply quality multipliers, emit attribution."""
        try:
            signal = event.to_signal_dict()

            # Apply Hurst×Entropy
            hurst_q = signal.features.get("hurst_trend_quality", 1.0)
            entropy_q = signal.features.get("entropy_quality", 1.0)
            quality = min(hurst_q, entropy_q)
            before = signal["confidence"]
            after = round(before * quality, 4)

            # Apply drift penalty
            drift_penalty = self._get_drift_penalty(signal.symbol)
            before = after
            after = round(after * drift_penalty, 4)

            # Emit attribution
            await self.attribution_producer.send({
                "stage": "quality_gate",
                "symbol": signal.symbol,
                "timestamp": signal.timestamp,
                "value_added": round(after - signal["confidence"], 4),
                "inputs": {
                    "hurst_quality": hurst_q,
                    "entropy_quality": entropy_q,
                    "drift_penalty": drift_penalty
                }
            })

            signal["confidence"] = after
            return signal

        except Exception as e:
            logger.error(f"QualityGate failed: {e}")
            # Fault tolerance: pass through with warning
            await self.circuit_breaker.record_failure()
            signal["quality_gate_bypassed"] = True
            signal["quality_gate_error"] = str(e)
            return signal

# src/intelligence/stages/regime_gate.py
class RegimeGateService:
    """
    Suppresses signals based on HMM regime.

    Inputs: quality_gated:SYMBOL:TF
    Outputs: regime_gated:SYMBOL:TF
    Side-outputs: attribution:SYMBOL:TF
    """
    pass  # Similar structure

# src/intelligence/stages/tod_adjuster.py
class TODAdjusterService:
    """
    Applies time-of-day multipliers.

    Inputs: regime_gated:SYMBOL:TF
    Outputs: tod_adjusted:SYMBOL:TF
    Side-outputs: attribution:SYMBOL:TF
    """
    pass

# src/intelligence/stages/calibrator.py
class CalibratorService:
    """
    Applies isotonic calibration curves.

    Inputs: tod_adjusted:SYMBOL:TF
    Outputs: calibrated:SYMBOL:TF
    Side-outputs: attribution:SYMBOL:TF
    """
    pass

# src/intelligence/stages/ranker.py
class RankerService:
    """
    Sorts signals by performance-weighted priority.

    Inputs: calibrated:SYMBOL:TF
    Outputs: ranked:SYMBOL:TF
    Side-outputs: attribution:SYMBOL:TF
    """
    pass

# src/intelligence/stages/winner_selector.py
class WinnerSelectorService:
    """
    Selects winning signal using CIS or priority/majority.

    Inputs: ranked:SYMBOL:TF
    Outputs: winner:SYMBOL:TF
    Side-outputs: signal_ledger (DB write)
    """
    pass
```

### Redpanda Stream DAG

```
intelligence:SYMBOL:TF
  ↓ (Plugins Service produces)
quality_gated:SYMBOL:TF
  ↓ (QualityGate Service produces)
regime_gated:SYMBOL:TF
  ↓ (RegimeGate Service produces)
tod_adjusted:SYMBOL:TF
  ↓ (TODAdjuster Service produces)
calibrated:SYMBOL:TF
  ↓ (Calibrator Service produces)
ranked:SYMBOL:TF
  ↓ (Ranker Service produces)
winner:SYMBOL:TF
  ↓ (WinnerSelector Service produces)
signal_ledger (DB write by SignalLedger Service)

Parallel streams:
attribution:SYMBOL:TF → Performance Attribution Service
data_quality:SYMBOL:TF → Data Quality Monitor Service
```

---

## Renaissance-Grade Observability

### 1. Performance Attribution (Which stage added value?)

Track **value added** by each stage:

```json
{
  "signal_id": "uuid",
  "symbol": "ES",
  "timeframe": "1m",
  "timestamp": "2026-03-19T14:43:05Z",
  "initial_confidence": 0.50,
  "baseline_win_rate": 0.38,
  "stage_attributions": [
    {
      "stage": "quality_gate",
      "before": 0.50,
      "after": 0.40,
      "value_added": -0.10,
      "reason": "Suppressed choppy market (hurst=0.15)",
      "projected_win_rate_impact": -0.04
    },
    {
      "stage": "regime_gate",
      "before": 0.40,
      "after": 0.40,
      "value_added": 0.00,
      "reason": "Regime eligible (trending)",
      "projectected_win_rate_impact": 0.00
    },
    {
      "stage": "tod_adjuster",
      "before": 0.40,
      "after": 0.50,
      "value_added": +0.10,
      "reason": "2pm ET bullish window (regime=trend,tf=1m,hour=14)",
      "projected_win_rate_impact": +0.04
    },
    {
      "stage": "calibrator",
      "before": 0.50,
      "after": 0.75,
      "value_added": +0.25,
      "reason": "trad_MeanReversion:1m calibrated upward",
      "projectected_win_rate_impact": +0.10
    }
  ],
  "final_confidence": 0.75,
  "projected_win_rate": 0.52,
  "total_value_added": +0.25,
  "attribution_summary": {
    "calibrator": +0.25,
    "tod_adjuster": +0.10,
    "quality_gate": -0.10,
    "regime_gate": +0.00
  }
}
```

**Question:** Is QualityGate SUPPRESSING winners or FILTERING losers?

**Answer:** Track counterfactual outcomes of signals suppressed by each stage.

---

### 2. Live A/B Experimentation (Continuous testing)

Multiple configurations of each stage running in parallel:

```python
# src/intelligence/experiments/ab_test_framework.py

class ABTestFramework:
    """
    Run multiple stage configurations in parallel.
    Automatically select winner after statistical significance.
    """

    def __init__(self):
        self.experiments = {}

    async def create_experiment(
        self,
        stage: str,
        config_a: dict,
        config_b: dict,
        min_sample_size: int = 1000,
        significance_level: float = 0.05
    ):
        """Create A/B test for a stage."""
        exp_id = str(uuid4())
        self.experiments[exp_id] = {
            "stage": stage,
            "config_a": config_a,
            "config_b": config_b,
            "min_sample_size": min_sample_size,
            "significance_level": significance_level,
            "status": "running",
            "created_at": datetime.now(UTC)
        }

        # Deploy both variants
        await self._deploy_variant(stage, "a", config_a)
        await self._deploy_variant(stage, "b", config_b)

        return exp_id

    async def evaluate_experiment(self, exp_id: str):
        """Check if experiment has significant result."""
        exp = self.experiments[exp_id]

        # Fetch metrics for both variants
        metrics_a = await self._get_metrics(exp["stage"], "a")
        metrics_b = await self._get_metrics(exp["stage"], "b")

        # Statistical test (t-test for proportions)
        win_rate_a = metrics_a["wins"] / metrics_a["n"]
        win_rate_b = metrics_b["wins"] / metrics_b["n"]
        p_value = self._t_test_proportions(
            metrics_a["wins"], metrics_a["n"],
            metrics_b["wins"], metrics_b["n"]
        )

        if metrics_a["n"] >= exp["min_sample_size"] and p_value < exp["significance_level"]:
            # Significant result! Pick winner
            winner = "a" if win_rate_a > win_rate_b else "b"
            await self._deploy_winner(exp["stage"], winner)
            exp["status"] = "completed"
            exp["winner"] = winner
            exp["p_value"] = p_value
            exp["lift"] = abs(win_rate_a - win_rate_b)

            return {
                "exp_id": exp_id,
                "winner": winner,
                "win_rate_a": win_rate_a,
                "win_rate_b": win_rate_b,
                "p_value": p_value,
                "lift": abs(win_rate_a - win_rate_b)
            }

        return {"exp_id": exp_id, "status": "running"}
```

**Example experiments:**

```python
# Test QualityGate threshold
await ab_test.create_experiment(
    stage="quality_gate",
    config_a={"hurst_threshold": 0.3, "entropy_threshold": 0.5},  # Current
    config_b={"hurst_threshold": 0.2, "entropy_threshold": 0.4},  # Proposed
    min_sample_size=1000,
    significance_level=0.05
)

# Test Calibrator approach
await ab_test.create_experiment(
    stage="calibrator",
    config_a={"method": "isotonic"},  # Current
    config_b={"method": "platt"},     # Proposed
    min_sample_size=500,
    significance_level=0.05
)
```

---

### 3. Causal Inference Framework (Not just correlation)

Prove that stage changes **cause** improvements, not just correlation:

```python
# src/intelligence/experiments/causal_inference.py

class CausalInferenceEngine:
    """
    Randomized experiments to prove causality.

    Question: Did calibrating confidence CAUSE higher win rate?
    Method: Randomly assign signals to calibrated/raw branches
    Result: Calibrated wins 52% vs 48% (p < 0.01, n=1000)
    Conclusion: Calibration CAUSES +4% lift
    """

    async def run_randomized_trial(
        self,
        stage: str,
        treatment_config: dict,
        control_config: dict,
        sample_size: int = 1000
    ):
        """
        Randomly assign signals to treatment/control branches.
        Measure causal effect.
        """
        trial_id = str(uuid4())

        # Flip coin for each signal
        assigned = []
        for i in range(sample_size):
            branch = "treatment" if random.random() < 0.5 else "control"
            config = treatment_config if branch == "treatment" else control_config
            assigned.append({
                "signal_id": str(uuid4()),
                "branch": branch,
                "config": config
            })

        # Run both branches in parallel
        treatment_outcomes = await self._run_branch(assigned, "treatment")
        control_outcomes = await self._run_branch(assigned, "control")

        # Measure causal effect
        treatment_win_rate = treatment_outcomes["wins"] / treatment_outcomes["n"]
        control_win_rate = control_outcomes["wins"] / control_outcomes["n"]
        causal_effect = treatment_win_rate - control_win_rate

        # Statistical significance
        p_value = self._t_test_proportions(
            treatment_outcomes["wins"], treatment_outcomes["n"],
            control_outcomes["wins"], control_outcomes["n"]
        )

        return {
            "trial_id": trial_id,
            "stage": stage,
            "treatment_win_rate": treatment_win_rate,
            "control_win_rate": control_win_rate,
            "causal_effect": causal_effect,
            "p_value": p_value,
            "conclusion": "CAUSAL" if p_value < 0.05 else "NO_EVIDENCE"
        }
```

---

### 4. Data Quality Monitoring (At each stage)

Validate data integrity at every stage:

```python
# src/intelligence/monitoring/data_quality_monitor.py

class DataQualityMonitor:
    """
    Monitor data quality at each stage.
    Alert on anomalies.
    """

    STAGE_SCHEMAS = {
        "quality_gate": {
            "confidence": {"type": "float", "min": 0.0, "max": 1.0},
            "hurst_quality": {"type": "float", "min": 0.0, "max": 1.0},
            "entropy_quality": {"type": "float", "min": 0.0, "max": 1.0},
            "drift_severity": {"type": "str", "enum": ["none", "warning", "critical"]}
        },
        "regime_gate": {
            "regime_eligible": {"type": "bool"},
            "suppression_reason": {"type": "str", "nullable": True}
        },
        # ... etc for each stage
    }

    async def validate_stage_output(self, stage: str, data: dict):
        """Validate data against schema."""
        schema = self.STAGE_SCHEMAS.get(stage, {})

        violations = []
        for field, rules in schema.items():
            value = data.get(field)

            # Type check
            if rules["type"] == "float":
                if not isinstance(value, (int, float)):
                    violations.append(f"{field}: wrong type {type(value)}")
                elif value < rules["min"] or value > rules["max"]:
                    violations.append(f"{field}: out of range [{rules['min']}, {rules['max']}]")

            elif rules["type"] == "str":
                if "enum" in rules and value not in rules["enum"]:
                    violations.append(f"{field}: invalid value '{value}', expected {rules['enum']}")

        if violations:
            # Drop signal, alert, log
            await self.alert_channel.send({
                "stage": stage,
                "signal_id": data.get("signal_id"),
                "violations": violations,
                "severity": "critical"
            })
            return False

        return True
```

---

### 5. Fault Tolerance (Degrade gracefully)

Circuit breakers and bypass modes:

```python
# src/intelligence/fault_tolerance/circuit_breaker.py

class CircuitBreaker:
    """
    Circuit breaker pattern for fault tolerance.

    If stage fails N times, open circuit and bypass.
    Auto-close after timeout.
    """

    def __init__(self, failure_threshold: int = 5, timeout_sec: int = 60):
        self.failure_threshold = failure_threshold
        self.timeout_sec = timeout_sec
        self.failures = 0
        self.last_failure_time = None
        self.state = "closed"  # closed, open, half-open

    async def call(self, func, *args, **kwargs):
        """Execute function with circuit breaker protection."""
        if self.state == "open":
            if datetime.now(UTC) - self.last_failure_time > timedelta(seconds=self.timeout_sec):
                self.state = "half-open"
            else:
                raise CircuitBreakerOpenError(f"Circuit breaker open, failing fast")

        try:
            result = await func(*args, **kwargs)
            if self.state == "half-open":
                self.state = "closed"
                self.failures = 0
            return result
        except Exception as e:
            self.failures += 1
            self.last_failure_time = datetime.now(UTC)

            if self.failures >= self.failure_threshold:
                self.state = "open"
                logger.error(f"Circuit breaker opened after {self.failures} failures")

            raise e


# Usage in each stage
class QualityGateService:
    def __init__(self):
        self.circuit_breaker = CircuitBreaker(failure_threshold=5, timeout_sec=60)

    async def process(self, event: IntelligenceEvent):
        try:
            return await self.circuit_breaker.call(self._apply_quality_gate, event)
        except CircuitBreakerOpenError:
            # Bypass stage with warning
            logger.warning("QualityGate bypassed: circuit breaker open")
            return event.to_signal_dict_with_warning("quality_gate_bypassed")
```

---

## Implementation Phases

### Phase 0: DAG Refactor (4-5 days)

**Goal:** Refactor monolithic pipeline into clean DAG microservices.

**Tasks:**

1. **Create stage base class**
   ```python
   # src/intelligence/stages/base.py
   class Stage(ABC):
       """Base class for all pipeline stages."""

       def __init__(self, stage_name: str):
           self.stage_name = stage_name
           self.consumer = KafkaConsumer(f"{stage_name}_input:SYMBOL:TF")
           self.producer = KafkaProducer(f"{stage_name}_output:SYMBOL:TF")
           self.attribution_producer = KafkaProducer("attribution:SYMBOL:TF")
           self.circuit_breaker = CircuitBreaker()
           self.data_quality_monitor = DataQualityMonitor()

       @abstractmethod
       async def process(self, event: IntelligenceEvent) -> dict:
           """Process event through this stage."""
           pass

       async def run(self):
           """Main loop: consume, process, produce."""
           async for event in self.consumer:
               try:
                   # Data quality check
                   if not await self.data_quality_monitor.validate_input(event):
                       continue

                   # Process with circuit breaker
                   result = await self.circuit_breaker.call(self.process, event)

                   # Emit attribution
                   await self.emit_attribution(event, result)

                   # Publish to next stage
                   await self.producer.send(result)

               except Exception as e:
                   logger.error(f"{self.stage_name} failed: {e}")
   ```

2. **Implement each stage**
   - `QualityGateService` (extends `Stage`)
   - `RegimeGateService` (extends `Stage`)
   - `TODAdjusterService` (extends `Stage`)
   - `CalibratorService` (extends `Stage`)
   - `RankerService` (extends `Stage`)
   - `WinnerSelectorService` (extends `Stage`)

3. **Create Redpanda topics**
   ```bash
   # Create topics for each stage
   rpk topic create quality_gated -c retention.ms=604800000
   rpk topic create regime_gated -c retention.ms=604800000
   rpk topic create tod_adjusted -c retention.ms=604800000
   rpk topic create calibrated -c retention.ms=604800000
   rpk topic create ranked -c retention.ms=604800000
   rpk topic create winner -c retention.ms=604800000
   rpk topic create attribution -c retention.ms=604800000
   rpk topic create data_quality -c retention.ms=604800000
   ```

4. **Update `signal_generator_service.py`**
   - Remove monolithic `aggregator.aggregate()`
   - Publish to `intelligence:SYMBOL:TF` (plugins only)
   - Subscribe to `winner:SYMBOL:TF` (final winner)
   - Write to `signal_ledger`

5. **Create systemd services**
   ```bash
   # indicagnet-quality-gate.service
   # indicagnet-regime-gate.service
   # indicagnet-tod-adjuster.service
   # indicagnet-calibrator.service
   # indicagnet-ranker.service
   # indicagnet-winner-selector.service
   # indicagnet-performance-attribution.service
   # indicagnet-data-quality.service
   ```

6. **Integration tests**
   - End-to-end: plugin → quality → regime → TOD → calibrate → rank → winner
   - Fault tolerance: kill QualityGate, verify bypass
   - Data quality: send bad data, verify alert

**Success criteria:**
- All stages running as independent services
- End-to-end signal flow working
- Fault tolerance: bypass on stage failure
- Data quality: alerts on invalid data
- Performance: < 10ms latency per stage

---

### Phase 1: Performance Attribution (2-3 days)

**Goal:** Track value added by each stage.

**Tasks:**

1. **Create `performance_attribution_service.py`**
   - Subscribe to `attribution:SYMBOL:TF`
   - Aggregate by stage, symbol, timeframe
   - Write to `performance_attribution` table

2. **Create `performance_attribution` table**
   ```sql
   CREATE TABLE performance_attribution (
       id SERIAL PRIMARY KEY,
       signal_id UUID,
       stage TEXT NOT NULL,
       symbol TEXT NOT NULL,
       timeframe TEXT NOT NULL,
       timestamp TIMESTAMPTZ NOT NULL,
       before_confidence FLOAT NOT NULL,
       after_confidence FLOAT NOT NULL,
       value_added FLOAT NOT NULL,
       inputs JSONB,
       reason TEXT,
       projected_win_rate_impact FLOAT
   );
   ```

3. **Add attribution aggregation queries**
   ```sql
   -- Which stages add most value?
   SELECT stage, AVG(value_added) as avg_value, COUNT(*) as n
   FROM performance_attribution
   WHERE timestamp > NOW() - INTERVAL '7 days'
   GROUP BY stage
   ORDER BY avg_value DESC;

   -- Which stages are suppressing winners?
   SELECT
       stage,
       COUNT(*) as n_suppressed,
       AVG(counterfactual_outcome_r) as avg_missed_r
   FROM performance_attribution pa
   JOIN signal_counterfactuals sc ON pa.signal_id = sc.signal_id
   WHERE pa.value_added < -0.1
   GROUP BY stage;
   ```

4. **UX: Show attribution on signal card hover**
   - "QualityGate: -10% (choppy)"
   - "Calibrator: +25% (well-calibrated)"

**Success criteria:**
- Every signal has full attribution chain
- Can query: "Which stages add most value?"
- Can query: "Which stages suppress winners?"

---

### Phase 2: Counterfactual Analysis (2-3 days)

**Goal:** Track what would have happened if stages were bypassed.

**Tasks:**

1. **Create `signal_counterfactuals` table**
   ```sql
   CREATE TABLE signal_counterfactuals (
       signal_id UUID PRIMARY KEY REFERENCES signal_ledger(signal_id),
       counterfactual_confidence FLOAT NOT NULL,
       stages_skipped TEXT[] NOT NULL,
       would_have_activated BOOLEAN,
       projected_mfe FLOAT,
       projected_mae FLOAT,
       actual_outcome TEXT,
       counterfactual_outcome TEXT,
       opportunity_cost_r FLOAT,
       gate_chain_json JSONB,
       created_at TIMESTAMPTZ DEFAULT NOW()
   );
   ```

2. **Create `scripts/analyze_counterfactuals.py`**
   - Nightly batch: replay suppressed signals
   - Simulate outcomes
   - Calculate opportunity cost

3. **UX: Show counterfactual outcomes**
   - "Would have hit T1 (+1.2R)"

**Success criteria:**
- All suppressed signals tracked
- Opportunity cost quantified per stage

---

### Phase 3: AI Gate Optimization (2-3 days)

**Goal:** LLM analyzes attribution + counterfactuals, recommends changes.

**Tasks:**

1. **Create `scripts/auto_gate_optimizer.py`**
   - Load attribution + counterfactual reports
   - Call LLM for analysis
   - Create A/B experiments

2. **Create A/B test framework**
   - `ab_test_framework.py`
   - Deploy multiple variants
   - Statistical winner selection

**Success criteria:**
- LLM generates nightly recommendations
- A/B tests run automatically
- Significant findings deployed

---

### Phase 4: Causal Inference (1-2 days)

**Goal:** Prove changes CAUSE improvements, not just correlation.

**Tasks:**

1. **Create `causal_inference.py`**
   - Randomized trials
   - Causal effect estimation
   - Statistical validation

2. **Integrate with A/B framework**
   - A/B tests now measure CAUSAL effects

**Success criteria:**
- Every stage change proven causal
- No "correlation != causation" mistakes

---

### Phase 5: Dashboard & Monitoring (2 days)

**Goal:** Full visibility into DAG performance.

**Tasks:**

1. **Add DAG visualization** to dashboard
   - Show each stage
   - Real-time latency
   - Error rates
   - Attribution metrics

2. **Add stage health metrics**
   - Circuit breaker status
   - Data quality alerts
   - A/B test status

3. **Add attribution reports**
   - Stage value added
   - Counterfactual opportunity cost
   - Causal effects

**Success criteria:**
- Full DAG observability
- Real-time health monitoring
- Attribution reports

---

## Success Criteria

### Architectural (DAG + Microservices)

- [ ] Pipeline is clean DAG of independent stages
- [ ] Each stage is separate microservice
- [ ] Stages communicate via Redpanda streams
- [ ] Each stage has single responsibility
- [ ] Fault tolerance: bypass on stage failure
- [ ] Data quality: validation at each stage
- [ ] < 10ms latency per stage

### Renaissance-Grade Observability

- [ ] **Performance attribution:** Track value added by each stage
- [ ] **A/B experimentation:** Continuous testing of stage configs
- [ ] **Causal inference:** Prove changes cause improvements
- [ ] **Data quality monitoring:** Validate at each stage
- [ ] **Fault tolerance:** Circuit breakers + bypass modes

### Business

- [ ] Can answer: "Which stages add most value?"
- [ ] Can answer: "Which stages suppress winners?"
- [ ] Can answer: "What is the opportunity cost of stage X?"
- [ ] Can answer: "Does stage X CAUSE improvements?"
- [ ] Fully automated: no manual reviews

---

## Open Questions

1. **Stage granularity** — Are these 6 stages right, or should we split further?
   - Option A: Keep as-is (6 stages)
   - Option B: Split QualityGate into HurstGate + EntropyGate + DriftGate
   - **Recommendation:** Start with 6 stages, split if attribution shows they're doing too much

2. **Circuit breaker thresholds** — What's the right failure threshold and timeout?
   - **Recommendation:** Start with (5 failures, 60s timeout), tune based on production

3. **A/B test duration** — How long to run experiments?
   - **Recommendation:** Min 1000 samples OR 14 days, whichever is longer

4. **Counterfactual simulation** — Full trade simulation or MFE/MAE only?
   - **Recommendation:** Start with MFE/MAE, upgrade to full simulation if needed

---

## Dependencies

**Blocking:**
- None

**Requires coordination:**
- Database migrations (new tables)
- Redpanda topic creation
- Systemd service creation
- Port allocation for metrics servers

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| DAG latency too high | Slow signals | < 10ms per stage, monitor end-to-end |
| Stage isolation fails | Coupling returns | Strict stream communication, no shared state |
| A/B tests deploy bad configs | System degrades | Statistical validation + auto-rollback |
| Circuit breakers too sensitive | Bypass everything | Tune thresholds in production |
| Too many stages to manage | Complexity | Start with 6, split only if needed |

---

## Timeline

**Total: 15-20 days**

| Phase | Duration | Dependencies |
|-------|----------|--------------|
| 0: DAG Refactor | 4-5 days | None |
| 1: Performance Attribution | 2-3 days | 0 |
| 2: Counterfactual Analysis | 2-3 days | 1 |
| 3: AI Gate Optimization | 2-3 days | 2 |
| 4: Causal Inference | 1-2 days | 3 |
| 5: Dashboard & Monitoring | 2 days | 0,1,2,3,4 |

**Sequencing:** 0 → 1 → 2 → 3 → 4 (|| 5) (Phase 5 can run in parallel)

---

## Next Steps

1. **Review this revised spec** — Confirm DAG architecture + Renaissance features
2. **Invoke writing-plans skill** — Create detailed TDD implementation plan for Phase 0 (DAG refactor)
3. **Execute Phase 0** — Build clean DAG foundation
4. **Evaluate after Phase 0** — Confirm DAG works before adding observability

---

## Appendix: Sample Attribution Output

```json
{
  "signal_id": "abc-123",
  "timestamp": "2026-03-19T14:43:05Z",
  "initial_confidence": 0.50,
  "final_confidence": 0.75,
  "stage_chain": [
    {"stage": "quality_gate", "value_added": -0.10, "reason": "hurst=0.15"},
    {"stage": "regime_gate", "value_added": +0.00, "reason": "eligible"},
    {"stage": "tod_adjuster", "value_added": +0.10, "reason": "2pm ET bull"},
    {"stage": "calibrator", "value_added": +0.25, "reason": "well-calibrated"}
  ],
  "attribution_summary": {
    "quality_gate": -0.10,
    "regime_gate": +0.00,
    "tod_adjuster": +0.10,
    "calibrator": +0.25
  },
  "counterfactual": {
    "if_quality_gate_skipped": "Would have won +0.8R",
    "if_calibrator_skipped": "Would have won +0.3R",
    "opportunity_cost": "-0.5R (quality_gate too aggressive)"
  }
}
```

This tells you EXACTLY what's happening:
- QualityGate crushed confidence (-0.10) and suppressed a winner (+0.8R missed)
- Calibrator added massive value (+0.25) and boosted win rate
- TOD boost was modest (+0.10) but correct

**Renaissance would say:** "QualityGate is suppressing winners. Loosen the threshold. Calibrator is adding value. Keep it."
