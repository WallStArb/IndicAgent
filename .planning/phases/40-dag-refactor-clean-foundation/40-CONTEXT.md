# Phase 40: Signal Pipeline DAG Refactor - Context

**Gathered:** 2026-03-19
**Status:** Ready for planning
**Source:** Design spec `docs/plans/2026-03-19-signal-pipeline-dag-refactor-and-renaissance-observability.md`

---

## Phase Boundary

Refactor the signal pipeline from a monolithic aggregator to a clean DAG of independent microservices — 6 stages (QualityGate → RegimeGate → TODAdjuster → Calibrator → Ranker → WinnerSelector) communicate via Redpanda streams, each with circuit breakers and basic attribution tracking.

**Scope (Phase 0 from design spec):** DAG refactor only — clean architecture foundation with basic instrumentation.

**Out of scope (deferred to Phase 47):**
- Performance Attribution Service (aggregates attribution into DB for analysis)
- Counterfactual Analysis (track suppressed signals and missed opportunities)
- A/B Test Framework (continuous experimentation with statistical validation)
- Causal Inference Engine (prove improvements are causal, not correlational)
- LLM Gate Optimizer (automated configuration tuning based on attribution)
- Dashboard DAG Visualization (real-time observability of stage health)
- Modifying plugin logic (plugins layer stays the same)
- Changing signal lifecycle tracking (Phase 39)
- ML model training infrastructure (Phase 46)

---

## Implementation Decisions

### Renaissance Principles (NON-NEGOTIABLE)

### What Would Jim Simons Demand?

These principles override all other considerations:

#### 1. Instrument Everything (Basic Attribution)
**Decision:** Every stage emits basic attribution tracking (foundation for future Phase 47 observability).
- No "black box" stages
- Every confidence adjustment logged with before/after values
- Every suppression reason recorded
- Every stage emits attribution to `attribution:SYMBOL:TF` (basic format: {before, after, value_added, reason})
- Full retention of all intermediate outputs (7-day topic retention)
- Note: Full aggregation into `performance_attribution` table deferred to Phase 47

#### 2. Let the System Run (Automation Foundation)
**Decision:** Automated circuit breakers and bypass — no manual intervention for fault tolerance.
- Circuit breakers auto-open/close based on failure thresholds
- Stages auto-bypass on failure with warning logging
- Note: A/B testing, statistical gates, and LLM analysis deferred to Phase 47

#### 3. Earn the Right Through Proof (Foundation)
**Decision:** Clean architecture enables future statistical validation — attribution data collected for Phase 47.
- Basic attribution tracking enables future A/B testing and causal inference
- Note: Statistical validation (A/B tests, causal inference) deferred to Phase 47

#### 4. Segment Relentlessly (Foundation)
**Decision:** Segmentation infrastructure preserved — attribution data includes context for future analysis.
- TOD multipliers grouped by (regime_type, tf, hour_et) — 120 cells (existing)
- Attribution includes symbol, timeframe, regime context (enables Phase 47 segmentation)
- Note: Segmented analysis and counterfactuals deferred to Phase 47

#### 5. Degrade Gracefully
**Decision:** Fault tolerance with circuit breakers and bypass modes.
- Each stage has CircuitBreaker(failure_threshold=5, timeout_sec=60)
- On N failures: open circuit, bypass stage, log warning
- Auto-close after timeout
- Pipeline continues even if stages fail
- Data quality monitor drops invalid signals with alerts

#### 6. Data Quality Over Model Complexity
**Decision:** Validate data at each stage; drop invalid signals with alerts.
- Stage output schemas defined in `DataQualityMonitor.STAGE_SCHEMAS`
- Type checks, range checks, enum validation
- Critical alerts on violations
- Never propagate bad data downstream

#### 7. Never Drop Data (Stream Retention)
**Decision:** Full retention of all intermediate outputs in streams (DB aggregation deferred to Phase 47).
- All stage outputs persisted to Redpanda with 7-day retention (attribution stream)
- Ground truth: `market_data_ohlcv` kept forever
- Note: Aggregation into `performance_attribution` and `signal_counterfactuals` tables deferred to Phase 47

---

### Architecture: DAG Microservices (LOCKED)

#### Current State (Monolithic - MUST BE REPLACED)

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
- One function does everything (violates single responsibility)
- Hard to test independently
- Can't deploy/stage independently
- No fault isolation
- Poor observability (can't see which stage adds value)

#### Target State (DAG Microservices - LOCKED)

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

**Stage Definitions (LOCKED):**

1. **QualityGateService** — Apply Hurst×Entropy and KS drift penalty multipliers
2. **RegimeGateService** — Suppress signals based on HMM regime
3. **TODAdjusterService** — Apply time-of-day multipliers
4. **CalibratorService** — Apply isotonic calibration curves
5. **RankerService** — Sort signals by performance-weighted priority
6. **WinnerSelectorService** — Select winning signal using CIS or priority/majority

**Each stage MUST:**
- Extend `Stage` base class
- Be independent microservice (separate systemd service)
- Communicate via Redpanda streams only
- Emit attribution to `attribution:SYMBOL:TF`
- Have CircuitBreaker(failure_threshold=5, timeout_sec=60)
- Validate output with DataQualityMonitor
- Bypass on failure with warning

**Stage Base Class Pattern (LOCKED):**

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

---

### Redpanda Topics (LOCKED)

**Stage pipeline topics (7-day retention):**
- `quality_gated:SYMBOL:TF`
- `regime_gated:SYMBOL:TF`
- `tod_adjusted:SYMBOL:TF`
- `calibrated:SYMBOL:TF`
- `ranked:SYMBOL:TF`
- `winner:SYMBOL:TF`

**Side-output topics (7-day retention):**
- `attribution:SYMBOL:TF` — Performance attribution from all stages
- `data_quality:SYMBOL:TF` — Data quality violations

**Creation command template:**
```bash
docker exec redpanda rpk topic create <topic> --set retention.ms=604800000
```

---

### Systemd Services (LOCKED)

Create one systemd service per stage:

```bash
indicagnet-quality-gate.service
indicagnet-regime-gate.service
indicagnet-tod-adjuster.service
indicagnet-calibrator.service
indicagnet-ranker.service
indicagnet-winner-selector.service
indicagnet-performance-attribution.service
indicagnet-data-quality.service
```

**Service template:**
- `Restart=always`
- `User=bg`
- `WorkingDirectory=/home/bg/dev/indicagent`
- `ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/<stage>_service.py`
- `PYTHONUNBUFFERED=1` (critical for journald)
- Metrics port: increment from :9118 (e.g., :9119, :9120, ...)

---

### Database Schema (DEFERRED to Phase 47)

Note: Database tables for attribution aggregation and counterfactual analysis are **out of scope** for this phase. This phase (Phase 40) only creates the DAG infrastructure and basic attribution tracking to Redpanda streams. Database aggregation and analysis will be implemented in Phase 47 (Renaissance Observability).

**Deferred tables:**
- `performance_attribution` — Aggregates attribution from stream into queriable table
- `signal_counterfactuals` — Tracks suppressed signals and opportunity costs

**Current phase (40) uses:**
- Redpanda streams only — `attribution:SYMBOL:TF` with 7-day retention
- No DB writes for attribution (deferred to Phase 47)

---

### Implementation Phases (LOCKED)

#### Phase 0: DAG Refactor (4-5 days) — CURRENT PHASE
**Goal:** Refactor monolithic pipeline into clean DAG microservices with basic attribution tracking.

**Tasks:**
1. Create `src/intelligence/stages/base.py` — Stage base class
2. Implement 6 stage services (QualityGate, RegimeGate, TODAdjuster, Calibrator, Ranker, WinnerSelector)
3. Create Redpanda topics for stage pipeline (8 topics with 7-day retention)
4. Update `signal_generator_service.py` — remove monolithic aggregator, publish to first stage, subscribe to winner
5. Create 6 systemd services (one per stage)
6. Integration tests (end-to-end, fault tolerance, data quality)

**Success criteria:**
- All stages running as independent services
- End-to-end signal flow working
- Fault tolerance: bypass on stage failure
- Data quality: alerts on invalid data
- Performance: < 10ms latency per stage
- Basic attribution emitted to `attribution:SYMBOL:TF` stream

**Deferred to Phase 47 (Renaissance Observability):**
- Phase 1: Performance Attribution Service (aggregates attribution into `performance_attribution` table)
- Phase 2: Counterfactual Analysis (tracks suppressed signals and missed opportunities)
- Phase 3: AI Gate Optimization + A/B Test Framework (automated experimentation)
- Phase 4: Causal Inference Engine (proves causality vs correlation)
- Phase 5: Dashboard & Monitoring (DAG visualization, health metrics, attribution reports)

---

### Success Criteria (LOCKED)

#### Architectural (DAG + Microservices)
- [ ] Pipeline is clean DAG of independent stages
- [ ] Each stage is separate microservice
- [ ] Stages communicate via Redpanda streams only
- [ ] Each stage has single responsibility
- [ ] Fault tolerance: bypass on stage failure
- [ ] Data quality: validation at each stage
- [ ] < 10ms latency per stage

#### Renaissance-Grade Observability (Basic Foundation)
- [ ] **Basic attribution tracking:** Each stage emits {before, after, value_added, reason} to attribution stream
- [ ] **Data quality monitoring:** Validate at each stage
- [ ] **Fault tolerance:** Circuit breakers + bypass modes
- [ ] Note: Full aggregation, A/B testing, and causal inference deferred to Phase 47

#### Business (Current Phase)
- [ ] DAG pipeline is observable (attribution stream enables future analysis)
- [ ] Fault tolerance automated (circuit breakers)
- [ ] Data quality validated at each stage
- [ ] Note: Business questions ("Which stages add most value?", "Does X cause Y?") deferred to Phase 47 when attribution is aggregated into DB

---

## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Architecture & Design
- `docs/plans/2026-03-19-signal-pipeline-dag-refactor-and-renaissance-observability.md` — Full design spec with detailed architecture
- `CLAUDE.md` — Project instructions, plugin vs service boundary, refactoring philosophy

### Intelligence Layer
- `src/intelligence/CLAUDE.md` — Tier definitions, plugin protocol
- `src/intelligence/schemas.py` — Typed bus schemas (IntelligenceEvent)
- `src/intelligence/register_plugins.py` — Tier lists (TIER_I1...TIER_I7)

### Current Pipeline (TO BE REFACTORED)
- `services/signal_generator_service.py` — Current monolithic implementation
- `src/intelligence/aggregator.py` — Current aggregator logic (study before replacing)

### Streaming & Topics
- `src/core/stream_keys.py` — Stream/topic key construction (MUST use for all topics)
- `CLAUDE.md` — Redpanda retention requirements (7 days for dev.* topics)

### Services & Patterns
- `src/core/service_utils.py` — setup_service_logging(), PLUGIN_METRICS_SAMPLE_RATE
- `src/core/database_manager.py` — PostgreSQL/TimescaleDB with connection pooling
- `src/observability/metrics.py` — Metrics creation (prevents duplicate registration)

### Database
- `CLAUDE.md` — TimescaleDB gotchas (VACUUM, autovacuum on hypertables, migrations via docker cp)

---

## Specific Ideas

### Attribution Data Model

Each stage MUST emit attribution in this format:

```json
{
  "signal_id": "uuid",
  "symbol": "ES",
  "timeframe": "1m",
  "timestamp": "2026-03-19T14:43:05Z",
  "stage": "quality_gate",
  "before": 0.50,
  "after": 0.40,
  "value_added": -0.10,
  "reason": "Suppressed choppy market (hurst=0.15)",
  "projected_win_rate_impact": -0.04,
  "inputs": {
    "hurst_quality": 0.15,
    "entropy_quality": 0.30,
    "drift_penalty": 1.0
  }
}
```

### Circuit Breaker Thresholds (CURRENT PHASE)

**Starting point (tune in production):**
- `failure_threshold=5` — Open circuit after 5 failures
- `timeout_sec=60` — Auto-close after 60 seconds

### TOD Grouping

**120 cells:** (regime_type, tf, hour_et)
- 3 regime types × 4 timeframes × 10 hours = 120
- NOT per-plugin (plugins don't have TOD, stages do)

---

## Deferred Ideas

### Future Enhancements (OUT OF SCOPE for this phase)

- **Stage splitting:** If attribution shows stages do too much, split QualityGate into HurstGate + EntropyGate + DriftGate
- **Full trade simulation:** Counterfactuals start with MFE/MAE, upgrade to full simulation if needed
- **ML-based stage optimization:** Use ML to predict optimal stage configs (later phase)
- **Cross-asset DAG:** Extend DAG to cross-asset signals (Phase 43)
- **Real-time counterfactuals:** Currently nightly batch; upgrade to streaming if needed

---

## Open Questions

### Stage Granularity
**Question:** Are these 6 stages right, or should we split further?

**Answer (LOCKED):** Start with 6 stages, split if attribution shows they're doing too much. Don't pre-optimize.

### Circuit Breaker Thresholds
**Question:** What's the right failure threshold and timeout?

**Answer (LOCKED):** Start with (5 failures, 60s timeout), tune based on production metrics.

### A/B Test Duration
**Question:** How long to run experiments?

**Answer (LOCKED):** Min 1000 samples OR 14 days, whichever is longer.

### Counterfactual Simulation
**Question:** Full trade simulation or MFE/MAE only?

**Answer (LOCKED):** Start with MFE/MAE, upgrade to full simulation if needed.

---

*Phase: 40-signal-pipeline-dag-refactor*
*Context gathered: 2026-03-19 from design spec*
