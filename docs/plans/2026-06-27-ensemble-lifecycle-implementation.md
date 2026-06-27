# Ensemble Lifecycle Implementation — Three-Gate Health Check

**Date:** 2026-06-27
**Status:** PROPOSED — not planned, awaiting prioritization
**Milestone:** v3.0 Phases 151A-151C (System Health + Observability)
**Concept spec:** `docs/ideas/alpha-ensemble-lifecycle.md` (June 25, 2026)
**Service design:** `docs/ideas/system-health-monitor-design.md` (Renaissance-grade reusable platform)

---

## Design Principle

**Three independent gates. All must pass. Any fail halts emission.**

> "An adaptive system that cannot detect its own failure will eventually trade itself into ruin."
>
> "Feature health ≠ Ensemble health. Both need independent monitoring."
> — Jim Simons (paraphrased)

**Renaissance-grade requirement:** Use the decay detection service — don't build health checks into AlphaEngine directly. Register ensemble health checks via APR, zero code changes for new systems.

---

## What Changed in v3.0 (vs Concept)

| Component | Concept Doc | v3.0 Implementation | Impact |
|-----------|-------------|---------------------|--------|
| **Deployment** | Embedded in AlphaEngine | Separate `indicant-decay-monitor` service | Service reads from registry, not hardcoded |
| **Configuration** | Hardcoded thresholds | APR-backed (all parameters tunable) | Tune without migrations |
| **Schema** | Conceptual only | `system_health_monitor` hypertable | Unified schema for all systems |
| **Recovery** | Not specified | State machine: 2 consecutive clean checks | No flapping on noisy measurements |
| **Actions** | Not specified | Pluggable callbacks (halt, reduce, retrain) | Easy to extend |

---

## Architecture Overview

```
AlphaEngine Ensemble Health (3 Gates)
├─ E1: Ensemble IC Gate — Does ensemble predict returns?
├─ E2: Conviction Reliability — Are conviction scores stable/calibrated?
└─ E3: Feature Coverage — Enough active features?

Decay Detection Service
├─ Reads from system_registry (APR-backed)
├─ Runs health checks every 1-4h (configurable)
├─ Writes to system_health_monitor
├─ Executes actions (halt, reduce, retrain)
└─ Publishes to Prometheus + API + topic events

AlphaEmitter Integration
├─ Queries decay service before emission
├─ Halts if overall_status = "critical"
├─ Reduces size if overall_status = "warning"
└─ Emits with adjusted conviction
```

---

## Phase 151A: E1 Gate — Ensemble IC Gate

**Goal:** Detect when ensemble IC drops below floor → halt emission

### Health Check Configuration

**Metric:** Ensemble IC Sharpe from `alpha_ensemble_ic` table

**Query:**
```sql
SELECT ic_sharpe, walk_forward_stable, fdr_passed, scored_at
FROM alpha_ensemble_ic
WHERE symbol=$1 AND tf=$2 AND regime=$3
  AND scored_at > NOW() - INTERVAL '7 days'
ORDER BY scored_at DESC LIMIT 1
```

**Thresholds (APR-backed):**
- `critical`: ic_sharpe < 0.5 → halt emission
- `warning`: ic_sharpe < 1.0 → reduce size to 50%
- `healthy`: ic_sharpe ≥ 1.0 → normal emission

**Required conditions:**
- walk_forward_stable = true
- fdr_passed = true
- scored_at within last 7 days

**Action on fail:**
- critical: `halt_emission` (set `alpha.emitter.halted = true`)
- warning: `reduce_size` (set `alpha.emitter.size_multiplier = 0.5`)

### APR Keys

| Key | Default | Purpose |
|-----|---------|---------|
| `alpha.ensemble.ic_sharpe_floor_critical` | 0.5 | Halt emission below this IC |
| `alpha.ensemble.ic_sharpe_floor_warning` | 1.0 | Reduce size below this IC |
| `alpha.ensemble.ic_stale_days` | 7 | Max staleness before fail |
| `decay.check_interval_hours` | 1 | How often to run this check |

### Recovery State Machine

**Recovery triggers:** 2 consecutive clean checks (ic_sharpe ≥ 1.0)

**Recovery process:**
1. First clean check: Set `recovery_attempted_at`, wait for next run
2. Second clean check: Clear `is_decaying`, clear halt if triggered
3. Failed check: Reset `recovery_attempted_at`, start over

**APR key:**
- `alpha.ensemble.recovery_consecutive_passes = 2` (configurable)

### Success Criteria

1. ✅ Decay service runs E1 gate check every 1h
2. ✅ `system_health_monitor` populated with E1 results
3. ✅ Halt triggered when ic_sharpe < 0.5
4. ✅ Size reduction when ic_sharpe < 1.0
5. ✅ Recovery clears halt after 2 consecutive clean checks
6. ✅ Prometheus metric: `decay_health_check_status{health_check="ic_gate"}`

---

## Phase 151B: E2+E3 Gates — Conviction + Coverage

**Goal:** Detect conviction instability and feature coverage failure

### E2A: Conviction Stability Gate

**Metric:** Conviction std over last 100 alpha_events

**Query:**
```sql
SELECT STDDEV(conviction) AS conviction_std,
       COUNT(*) AS sample_count
FROM alpha_events
WHERE symbol=$1 AND tf=$2 
  AND emitted_at > NOW() - INTERVAL '7 days'
  AND conviction IS NOT NULL
```

**Thresholds (APR-backed):**
- `critical`: conviction_std > 0.30 → halt emission
- `warning`: conviction_std > 0.15 → reduce size
- `healthy`: conviction_std ≤ 0.15

**Required conditions:**
- sample_count ≥ 50

**Action on fail:**
- critical: `halt_emission`
- warning: `reduce_size`

**APR Keys:**
- `alpha.ensemble.conviction_std_critical = 0.30`
- `alpha.ensemble.conviction_std_warning = 0.15`
- `alpha.ensemble.conviction_min_samples = 50`

---

### E2B: Conviction Calibration Gate

**Metric:** Win rate vs conviction (monotonicity check)

**Query:**
```sql
SELECT 
    NTILE(10) OVER (ORDER BY conviction) AS conviction_decile,
    AVG(outcome_r > 0) AS win_rate
FROM alpha_events
WHERE symbol=$1 AND tf=$2
  AND emitted_at > NOW() - INTERVAL '30 days'
  AND outcome_r IS NOT NULL
GROUP BY conviction_decile
ORDER BY conviction_decile;
```

**Threshold:**
- `fail`: Win rate not monotonically increasing across deciles

**Action on fail:** `halt_emission`, investigate conviction scoring

---

### E2C: Conviction Distribution Health Gate

**Metric:** Conviction distribution (not collapsed to extremes)

**Query:**
```sql
SELECT 
    COUNT(*) FILTER (WHERE conviction < 0.2) AS low_conviction_pct,
    COUNT(*) FILTER (WHERE conviction > 0.8) AS high_conviction_pct,
    AVG(conviction) AS mean_conviction
FROM alpha_events
WHERE symbol=$1 AND tf=$2
  AND emitted_at > NOW() - INTERVAL '7 days';
```

**Thresholds (APR-backed):**
- `warning`: low_conviction_pct > 0.6 OR high_conviction_pct < 0.1 OR mean_conviction NOT BETWEEN 0.3 AND 0.7

**Action on fail:** `reduce_size`, check feature coverage

**APR Keys:**
- `alpha.ensemble.conviction_low_max_pct = 0.60`
- `alpha.ensemble.conviction_high_min_pct = 0.10`
- `alpha.ensemble.conviction_mean_min = 0.30`
- `alpha.ensemble.conviction_mean_max = 0.70`

---

### E3: Feature Coverage Gate

**Metric:** Active feature count (not decaying)

**Query:**
```sql
SELECT COUNT(*) FILTER (WHERE is_decaying = false) AS active_count
FROM feature_ic_scores
WHERE symbol=$1 AND tf=$2 AND regime=$3
  AND lookahead_bars=$4
  AND passes_walkforward = true
  AND reliable = true;
```

**Thresholds (APR-backed):**
- `critical`: active_count < 3 → halt emission
- `warning`: active_count < 5 → reduce size (proportional: count/5)
- `healthy`: active_count ≥ 5

**Action on fail:**
- critical: `halt_emission`
- warning: `reduce_size` with multiplier = count/5

**APR Keys:**
- `alpha.ensemble.min_feature_coverage_critical = 3`
- `alpha.ensemble.min_feature_coverage_warning = 5`

**Per-lookahead check:** Run E3 separately per lookahead (fast, mid, slow, extended)

---

### Recovery State Machine (E2+E3)

**Same as E1:** 2 consecutive clean checks required

**APR key:**
- `decay.recovery_consecutive_passes = 2` (shared across all gates)

### Success Criteria

1. ✅ Decay service runs E2A check every 4h
2. ✅ Decay service runs E3 check every 1h
3. ✅ E2B (calibration) runs every 24h (expensive)
4. ✅ E2C (distribution) runs every 4h
5. ✅ `system_health_monitor` populated with all E2+E3 results
6. ✅ Halt triggered when conviction_std > 0.30
7. ✅ Halt triggered when active_count < 3
8. ✅ Size reduction proportional to coverage deficit (4/5 = 80%)
9. ✅ Recovery clears all E2+E3 failures after 2 consecutive clean checks
10. ✅ Prometheus metrics for all E2+E3 gates

---

## Phase 151C: Retraining Automation + AlphaEmitter Integration

**Goal:** Automated ensemble retraining + AlphaEmitter obeys decay service

### Scheduled Retraining

**Trigger:** Every 30 days (APR-backed)

**Process:**
1. Fetch latest `feature_ic_scores` for all (symbol, tf, regime, lookahead)
2. Filter to `is_decaying = false` features only
3. Re-compute ensemble weights via IC-weighted linear combination
4. Run walk-forward validation
5. Run FDR correction
6. Write new row to `alpha_ensemble_ic`
7. Decay service auto-discovers new IC scores on next check cycle

**APR Keys:**
- `alpha.ensemble.retrain_interval_days = 30`

---

### Emergency Retraining

**Triggers:**
- Ensemble IC drops below 0.3 (severe degradation)
- All three gates fail simultaneously
- Manual operator trigger (APR flag)

**Timeline:** Within 24h of trigger

**APR Keys:**
- `alpha.ensemble.emergency_retrain_ic = 0.3`
- `alpha.ensemble.emergency_retrain_hours = 24`

**Process:** Same as scheduled retrain, plus diagnostic logging

---

### AlphaEmitter Integration

**Before emission:**
```python
# In alpha_emitter.py, before emitting any alpha_event
health_status = await decay_service.get_health(
    system="alpha_ensemble",
    symbol=symbol,
    tf=tf,
    regime=regime
)

# Check overall status
if health_status["overall_status"] == "critical":
    logger.warning(f"Halting emission: ensemble health critical - {health_status['halts_active']}")
    return  # Skip emission

if health_status["overall_status"] == "warning":
    # Apply size reduction
    size_multiplier = health_status.get("size_multiplier", 0.5)
    conviction *= size_multiplier
    logger.info(f"Reducing size to {size_multiplier*100}% due to warning: {health_status['warnings']}")

# Emit with adjusted conviction
await emit_alpha_event(conviction=conviction, ...)
```

**That's the entire integration.** Three lines of code. Service handles everything else.

### Success Criteria

1. ✅ Scheduled retrain runs every 30 days automatically
2. ✅ Emergency retrain triggers within 24h when IC < 0.3
3. ✅ AlphaEmitter queries decay service before each emission
4. ✅ AlphaEmitter halts when overall_status = "critical"
5. ✅ AlphaEmitter reduces size when overall_status = "warning"
6. ✅ Prometheus metric: `decay_system_registry_size` = 1 (alpha_ensemble registered)
7. ✅ `/api/health/alpha_ensemble` returns complete health status
8. ✅ Topic events published on all state transitions
9. ✅ All gates pass → emission proceeds normally
10. ✅ Any gate fails → appropriate action executed

---

## DB Schema

### Migration 027: Decay Detection Service Schema

**Table 1:** `system_health_monitor` (hypertable)

```sql
CREATE TABLE IF NOT EXISTS system_health_monitor (
    id                  BIGSERIAL       PRIMARY KEY,
    system_name         TEXT            NOT NULL,
    health_check        TEXT            NOT NULL,
    symbol              TEXT,
    timeframe           TEXT,
    regime              TEXT,
    lookahead           TEXT,
    
    checked_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    
    status              TEXT            NOT NULL,
    severity            FLOAT,
    metric_value        FLOAT,
    threshold_value     FLOAT,
    metric_name         TEXT,
    
    query_result        JSONB,
    
    halt_triggered      BOOLEAN         NOT NULL DEFAULT FALSE,
    halt_reason         TEXT,
    halt_action         TEXT,
    halt_cleared_at     TIMESTAMPTZ,
    
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
```

**Table 2:** `system_registry` (APR-backed config)

```sql
CREATE TABLE IF NOT EXISTS system_registry (
    system_name         TEXT            PRIMARY KEY,
    metrics_table       TEXT            NOT NULL,
    output_table        TEXT,
    health_checks       JSONB           NOT NULL,
    halt_action         TEXT,
    halt_action_params  JSONB,
    observability       JSONB,
    registered_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    registered_by       TEXT            NOT NULL DEFAULT 'system'
);
```

---

## Migration Strategy

### Phase 151A (E1 Gate)

1. Apply migration 027 (create `system_health_monitor`, `system_registry`)
2. Deploy `indicant-decay-monitor` service
3. Insert `system_registry` row for "alpha_ensemble" with E1 gate config
4. Add APR keys for E1 thresholds
5. Verify E1 check runs every 1h
6. Verify Prometheus metrics visible at `:9119`
7. Verify `/api/health/alpha_ensemble` returns E1 status

**Dependencies:**
- Phase 142A complete (`alpha_ensemble_ic` table exists)

---

### Phase 151B (E2+E3 Gates)

1. Update `system_registry` row to add E2A, E2B, E2C, E3 gates
2. Add APR keys for E2+E3 thresholds
3. Verify all gates run on configured intervals
4. Verify all gates write to `system_health_monitor`
5. Verify cascade scenarios (multiple gates failing)

**Dependencies:**
- Phase 151A complete (decay service deployed)
- Phase 149B complete (`feature_ic_scores.is_decaying` exists)

---

### Phase 151C (Retraining + Integration)

1. Implement scheduled retrain job (every 30 days)
2. Implement emergency retrain trigger (IC < 0.3)
3. Update `alpha_emitter.py` to query decay service before emission
4. Test halt logic (set IC < 0.5, verify emission stops)
5. Test size reduction logic (set IC < 1.0, verify conviction × 0.5)
6. Verify all three gates must pass (AND logic)

**Dependencies:**
- Phase 151B complete (all gates registered)
- Phase 142A complete (`alpha_events` table exists)

---

## Success Criteria (All Phases)

### Phase 151A (E1 Gate)

1. ✅ E1 check runs every 1h per (symbol, tf, regime)
2. ✅ Halt triggered when ic_sharpe < 0.5
3. ✅ Size reduction when ic_sharpe < 1.0
4. ✅ Recovery clears halt after 2 consecutive clean checks
5. ✅ Prometheus metrics visible at `:9119`
6. ✅ All E1 parameters APR-backed

---

### Phase 151B (E2+E3 Gates)

1. ✅ E2A (conviction stability) check runs every 4h
2. ✅ E2B (calibration) check runs every 24h
3. ✅ E2C (distribution) check runs every 4h
4. ✅ E3 (coverage) check runs every 1h per lookahead
5. ✅ Halt triggered when conviction_std > 0.30
6. ✅ Halt triggered when active_count < 3
7. ✅ Size reduction proportional to coverage deficit
8. ✅ Recovery clears all E2+E3 failures after 2 clean checks
9. ✅ All E2+E3 parameters APR-backed

---

### Phase 151C (Retraining + Integration)

1. ✅ Scheduled retrain runs every 30 days
2. ✅ Emergency retrain triggers within 24h when IC < 0.3
3. ✅ AlphaEmitter queries decay service before emission
4. ✅ AlphaEmitter halts when overall_status = "critical"
5. ✅ AlphaEmitter reduces size when overall_status = "warning"
6. ✅ All three gates must pass for emission (AND logic)
7. ✅ `/api/health/alpha_ensemble` returns complete health
8. ✅ Topic events published on state transitions

---

## Parameter Summary (All APR-Backed)

| Parameter | Value | Notes |
|-----------|-------|-------|
| **E1: Ensemble IC Gate** | | |
| IC Sharpe floor (critical) | 0.5 | `alpha.ensemble.ic_sharpe_floor_critical` |
| IC Sharpe floor (warning) | 1.0 | `alpha.ensemble.ic_sharpe_floor_warning` |
| IC staleness threshold | 7 days | `alpha.ensemble.ic_stale_days` |
| **E2A: Conviction Stability** | | |
| Conviction std (critical) | 0.30 | `alpha.ensemble.conviction_std_critical` |
| Conviction std (warning) | 0.15 | `alpha.ensemble.conviction_std_warning` |
| Conviction min samples | 50 | `alpha.ensemble.conviction_min_samples` |
| **E2C: Conviction Distribution** | | |
| Low conviction max pct | 0.60 | `alpha.ensemble.conviction_low_max_pct` |
| High conviction min pct | 0.10 | `alpha.ensemble.conviction_high_min_pct` |
| Mean conviction min | 0.30 | `alpha.ensemble.conviction_mean_min` |
| Mean conviction max | 0.70 | `alpha.ensemble.conviction_mean_max` |
| **E3: Feature Coverage** | | |
| Min coverage (critical) | 3 | `alpha.ensemble.min_feature_coverage_critical` |
| Min coverage (warning) | 5 | `alpha.ensemble.min_feature_coverage_warning` |
| **Retraining** | | |
| Scheduled retrain interval | 30 days | `alpha.ensemble.retrain_interval_days` |
| Emergency retrain IC trigger | 0.3 | `alpha.ensemble.emergency_retrain_ic` |
| Emergency retrain timeline | 24 hours | `alpha.ensemble.emergency_retrain_hours` |
| **Recovery** | | |
| Consecutive passes required | 2 | `alpha.ensemble.recovery_consecutive_passes` |
| **Service Configuration** | | |
| Default check interval | 1 hour | `decay.check_interval_hours` |
| Recovery check interval | 4 hours | `decay.recovery_check_interval_hours` |

---

## Execution Order

**Phase 151A (E1 Gate):**
1. Apply migration 027 (create tables)
2. Deploy decay-monitor service
3. Register alpha_ensemble with E1 gate
4. Verify E1 check runs and halts work

**Phase 151B (E2+E3 Gates):**
1. Register E2A, E2B, E2C, E3 gates
2. Add APR keys for all thresholds
3. Verify all gates run and cascade works

**Phase 151C (Retraining + Integration):**
1. Implement scheduled retrain job
2. Implement emergency retrain trigger
3. Update alpha_emitter to query decay service
4. Test halt/size reduction logic

All phases are independent of core v3.0 AlphaEngine work (Phases 137-144). Can run in parallel once Phase 142A (alpha_ensemble_ic) and Phase 149B (feature_ic_scores.is_decaying) ship.

---

**Renaissance-grade foundation:** All parameters APR-backed, three independent gates, recovery state machine, automated retraining, zero code changes for new systems. No technical debt.**
