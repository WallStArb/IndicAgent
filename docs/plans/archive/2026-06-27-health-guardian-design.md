# IntegrityMonitor — Unified Monitoring Platform Design

**Archived 2026-07-02.** Superseded by `docs/research/intel-14-integrity-monitor.md`, which found
this consolidation dropped real content from its own predecessors (E2B/E2C conviction
sub-tests, CUSUM, cascade reasoning) and proposed a `feature_ic_scores` schema since overruled
by the topdown review's D3. `DistributionDriftMonitor` (Monitor 1) is kept unchanged. Kept here
for the full schema DDL, APR key table, and observability spec not reproduced in intel-14.

**Date:** 2026-06-27
**Status:** PROPOSED — awaiting prioritization
**Replaces:** `docs/research/data-integrity-monitor-design.md`, `docs/research/system-health-monitor-design.md`, `docs/research/predictive-decay-detector-design.md`
**Milestone:** v3.0a-c (Phases 149A, 149B, 150, 151A-C)

---

## Problem

Three planned services (DataIntegrityMonitor, SystemHealthMonitor, PredictiveDecayDetector) solve one problem — "is this system healthy?" — with three identical service skeletons: recovery state machine, action registry, OTel metrics, periodic check loop, REST API, hypertable. They would diverge in maintenance. The original designs also have two substantive signal quality gaps: regime-blind KS windows and no shadow mode (binary `is_decaying` with cooldown clock, no evidence accumulation while benched).

---

## Solution: One Service, Three Monitor Modules

`indicagent-integrity-monitor` (port `:9118`) loads three pluggable monitor modules at startup:

```
IntegrityMonitor
├── DistributionDriftMonitor    # KS + chi-squared + signed Wasserstein on feature_vectors
├── ICLifecycleMonitor          # shadow governance for feature_ic_scores (event-driven)
└── EnsembleHealthMonitor       # 3-gate health check on alpha_ensemble_ic / alpha_events
```

One `integrity_monitor` hypertable records all check results (discriminated by `monitor_type`). One recovery state machine. One action registry. One OTel metrics block.

---

## Architecture

```
                 feature_vectors ──► DistributionDriftMonitor ──► integrity_monitor
                                           (4h timer)                    │
                                                                         │
              feature_ic_scores ──► ICLifecycleMonitor ──────────► integrity_monitor
              (corpus run event)        (event-driven)                   │
                                                                         │
      alpha_ensemble_ic + alpha_events ──► EnsembleHealthMonitor ──► integrity_monitor
                                                (1h timer)               │
                                                                         ▼
                                                               ensemble_trainer
                                                               alpha_publisher
```

**Shared infrastructure (written once):**

```python
class BaseMonitor(ABC):
    recovery_state_machine: RecoveryStateMachine  # shared
    action_registry: ActionRegistry               # shared
    metrics: OTelMetrics                          # shared labels per monitor_type

    @abstractmethod
    async def check(self, conn, params) -> MonitorResult: ...

    @abstractmethod
    def check_interval(self) -> int: ...  # seconds; 0 = event-driven
```

---

## Monitor 1: DistributionDriftMonitor

### What it detects

Input data corruption. If IBKR field changes or feature formulas compute on corrupted data, distributions shift. This is orthogonal to IC decay — a feature can have IC on corrupted data and fail KS, or have stable distributions and lose its IC edge.

### Improvements over original design

**Regime-conditioned reference windows (key improvement):**

The original 29-day reference window fires KS alerts on every regime transition — RSI and ADX distributions naturally differ between trending and ranging regimes. That is correct behavior, not corruption.

Fix: determine majority HMM regime in the current window from posteriors already in `feature_vectors`, then filter both windows to the same regime:

```sql
-- Step 1: majority regime in current 7-day window (one query per symbol/tf)
WITH regime_labels AS (
    SELECT
        CASE
            WHEN hmm_regime_posterior_trending > hmm_regime_posterior_range
             AND hmm_regime_posterior_trending > hmm_regime_posterior_mean_revert
            THEN 'trending'
            WHEN hmm_regime_posterior_range > hmm_regime_posterior_mean_revert
            THEN 'ranging'
            ELSE 'mean_revert'
        END AS regime
    FROM feature_vectors
    WHERE symbol = $1 AND tf = $2
      AND ts >= NOW() - INTERVAL '7 days'
)
SELECT MODE() WITHIN GROUP (ORDER BY regime) AS current_regime FROM regime_labels;

-- Step 2: both windows filtered to current_regime
WHERE symbol = $1 AND tf = $2
  AND ts >= NOW() - INTERVAL '37 days'
  AND ts <  NOW() - INTERVAL '7 days'
  AND CASE
        WHEN $3 = 'trending' THEN hmm_regime_posterior_trending > hmm_regime_posterior_range
          AND hmm_regime_posterior_trending > hmm_regime_posterior_mean_revert
        WHEN $3 = 'ranging' THEN hmm_regime_posterior_range > hmm_regime_posterior_mean_revert
          AND hmm_regime_posterior_range >= hmm_regime_posterior_trending
        ELSE hmm_regime_posterior_mean_revert >= hmm_regime_posterior_trending
          AND hmm_regime_posterior_mean_revert >= hmm_regime_posterior_range
      END
```

No new joins, no new tables — regime signal is already in `feature_vectors`.

**Signed Wasserstein distance (replaces unsigned KS statistic):**

KS statistic tells you distributions differ; it doesn't tell you how. For directional features, shift direction matters: `rsi_fast` distribution shifting up during a trend strengthening is still informative. Shift toward noise/uniform is signal degradation.

`scipy.stats.wasserstein_distance` is O(n log n) like KS, and gives signed magnitude (positive = current shifted right of reference, negative = left). Initial penalty logic is symmetric — we don't yet have history to learn direction-specific penalties per feature. The signed value is recorded in `integrity_monitor.wasserstein_signed` so that after 3-6 months of data, direction-specific penalty learning is possible.

**Single query for all 54 features per window:**

KS (47 continuous) and chi-squared (7 categorical) read from the same `feature_vectors` rows. One query per (symbol, tf) per window returns all columns. Python splits them post-query. This halves DB load: 368 → 184 queries per 4h cycle.

### Alert logic

```python
# Per feature, per (symbol, tf):
ks_alert   = p_value < ks_p_threshold AND abs(wasserstein_signed) > ks_effect_threshold AND n >= ks_min_sample
chi2_alert = chi2_p < chi_sq_p_threshold AND cramers_v > chi_sq_effect_threshold AND n >= chi_sq_min_sample

# Aggregate to symbol/tf level (worst feature drives penalty)
severity = max(feature_severities)  # warning or critical
```

### Adaptive penalty (ensemble weight multiplier)

```python
# warning: penalty = max(weight_penalty_warning_min, 1.0 - abs(wasserstein_signed) * 0.3)
# critical: penalty = max(weight_penalty_critical_min, 1.0 - abs(wasserstein_signed) * 0.5)
# Scale by Wasserstein magnitude, not fixed step
```

### Recovery state machine

Shares `RecoveryStateMachine` with other monitors. Clears penalty after `recovery_clean_tests_required` (default: 2) consecutive clean checks. Piggybacked on the main 4h check cycle — no second timer.

---

## Monitor 2: ICLifecycleMonitor

### What it detects

Feature-level predictive edge erosion. A feature's IC can decay while its input distributions are stable. This monitor owns the shadow governance lifecycle.

### Shadow mode lifecycle

```
candidate ──[IC gates pass]──► active ──[IC fails]──► shadow ──[2 passing corpus runs]──► active
                                                              │                         (weight = pre_shadow_weight)
                                                              └──[shadow_max_corpus_runs failing]──► deprecated*

* deprecated requires operator insert into feature_deprecations — never automatic
```

**Shadow state behavior:**
- Feature stays in FeatureFactory pipeline (already computed, cost is zero)
- `ic_engine` continues computing and writing IC scores — `is_shadowed = true` rows are written normally
- `ensemble_trainer` reads `is_shadowed` flag and assigns `weight = 0.0` — feature excluded from live emission
- Shadow IC scores accumulate in `feature_ic_scores`, visible in Grafana as a bench report

**Demotion triggers (active → shadow):**

Any of the following on a corpus run result:
- `passes_walkforward = false`
- `ic_sharpe < alpha.ic.shadow_decay_sharpe_threshold` (default: 0.0)
- `reliable = false` (corpus shrank, symbol delisted)

**Promotion (shadow → active):**

Two consecutive corpus runs where all gates pass:
- `passes_walkforward = true`
- `ic_sharpe >= alpha.ic.shadow_recovery_sharpe_threshold` (same as decay threshold by default)
- `reliable = true`

On promotion: `is_shadowed = false`, `shadow_entered_at = NULL`, `shadow_corpus_runs = 0`, `shadow_confirmation_count = 0`, `shadow_recovery_confirmed_at = NOW()`.

`ensemble_trainer` uses `pre_shadow_weight` as the starting weight on the first post-promotion run. This is the `ic_sharpe` value at the moment of demotion — the feature earned it, 2 confirmed corpus runs say it's back. On subsequent runs, normal IC-based weighting takes over.

**Why no cooldown period:**

The original `recovery_eligible_at` cooldown is a calendar gate — it prevents re-evaluation for 30 days regardless of IC evidence. Shadow mode removes this. The feature is continuously evaluated on every corpus run. Recovery confirmation is evidence-based (2 consecutive passing runs), not calendar-based. A feature that recovers in 10 days gets promoted in 10 days; one that never recovers gets deprecated after `shadow_max_corpus_runs` runs.

**Deprecation (shadow → deprecated):**

After `alpha.ic.shadow_max_corpus_runs` (default: 12) consecutive failing shadow corpus runs, the feature is a deprecation candidate. It is NOT automatically deprecated — an operator must insert a row into `feature_deprecations` table to confirm. This prevents automated permanent exclusion of features that might recover in an unusual regime.

### Implementation: IC engine integration

`ic_engine.py` calls `ICLifecycleMonitor.evaluate(conn, feature_name, symbol, tf, regime, lookahead_bars, current_result)` after writing each IC score row. The monitor handles all state transitions and updates.

```python
async def evaluate(self, conn, feature_name, symbol, tf, regime, lookahead_bars, result):
    prior = await self._load_prior(conn, feature_name, symbol, tf, regime, lookahead_bars)
    transition = self._compute_transition(prior, result)

    if transition == Transition.DEMOTE:
        await self._demote(conn, feature_name, symbol, tf, regime, lookahead_bars, result)
        await self._publish_event("shadow_entered", ...)

    elif transition == Transition.CONFIRM_RECOVERY:
        await self._promote(conn, feature_name, symbol, tf, regime, lookahead_bars, prior)
        await self._publish_event("shadow_exited", ...)

    elif transition == Transition.RECOVERY_ATTEMPT:
        await self._mark_recovery_attempt(conn, ...)

    elif transition == Transition.SHADOW_FAIL:
        await self._increment_shadow_runs(conn, ...)
        if prior["shadow_corpus_runs"] + 1 >= self._shadow_max_runs:
            await self._publish_event("deprecation_candidate", ...)
```

### Ensemble integration

`ensemble_trainer` (and `feature_selector`) add one filter:

```sql
AND (is_shadowed = false OR is_shadowed IS NULL)
```

This is the only change required in the ensemble. The lifecycle management is fully encapsulated in the guardian.

---

## Monitor 3: EnsembleHealthMonitor

### What it detects

Ensemble-level degradation — the ensemble can break even when individual features are healthy and input data is clean.

### Three gates (AND logic — all must pass for emission)

**E1: Ensemble IC Gate**

```sql
SELECT ic_sharpe_hac, walk_forward_stable, fdr_passed, scored_at
FROM alpha_ensemble_ic
WHERE symbol=$1 AND tf=$2 AND regime=$3 AND lookahead=$4
  AND scored_at > NOW() - INTERVAL '7 days'
ORDER BY scored_at DESC LIMIT 1
```

- `critical`: `ic_sharpe_hac < alpha.ensemble.ic_sharpe_floor_critical` (default: 0.5) → halt emission
- `warning`: `ic_sharpe_hac < alpha.ensemble.ic_sharpe_floor_warning` (default: 1.0) → reduce conviction
- Required conditions: `walk_forward_stable = true AND fdr_passed = true`
- `stale`: no row within 7 days → critical

**E2: Conviction Stability Gate**

Regime-conditioned (improvement over original): compute stddev within majority regime of the check window, not across all regimes pooled. Trending regimes legitimately produce higher conviction variance; pooling inflates the baseline and causes false warnings.

```sql
SELECT STDDEV(conviction) AS conviction_std, COUNT(*) AS n
FROM alpha_events
WHERE symbol=$1 AND tf=$2
  AND emitted_at > NOW() - INTERVAL '7 days'
  AND conviction IS NOT NULL
  AND regime = $3  -- majority regime of check window
```

- `warning`: `conviction_std > alpha.ensemble.conviction_std_warning` (default: 0.15) AND `n >= conviction_min_samples`
- `critical`: `conviction_std > alpha.ensemble.conviction_std_critical` (default: 0.30)

**E3: Feature Coverage Gate**

```sql
SELECT COUNT(*) FILTER (WHERE is_shadowed = false OR is_shadowed IS NULL) AS active_count
FROM feature_ic_scores
WHERE symbol=$1 AND tf=$2 AND regime=$3 AND lookahead_bars=$4
  AND passes_walkforward = true AND reliable = true
```

- `critical`: `active_count < alpha.ensemble.min_feature_coverage_critical` (default: 3) → halt emission
- `warning`: `active_count < alpha.ensemble.min_feature_coverage_warning` (default: 5) → scale conviction by `active_count / warning_floor`

### Actions

- `halt_emission`: set APR key `alpha.emitter.halted = true` (checked by `alpha_publisher` before every emit)
- `reduce_conviction`: set APR key `alpha.emitter.conviction_multiplier` (multiplied in `alpha_publisher`)
- `force_retrain`: enqueue retrain job (future)

Recovery: 2 consecutive clean checks (shared `RecoveryStateMachine`) before clearing halt or restoring multiplier.

---

## Schema

### New table: `integrity_monitor` (hypertable)

```sql
CREATE TABLE IF NOT EXISTS integrity_monitor (
    id                  BIGSERIAL       PRIMARY KEY,
    monitor_type        TEXT            NOT NULL,   -- distribution_drift / ic_lifecycle / ensemble_health
    check_type          TEXT            NOT NULL,   -- ks_distribution / chi_squared / shadow_transition / ic_gate / etc.
    symbol              TEXT,
    timeframe           TEXT,
    regime              TEXT,
    lookahead           TEXT,
    feature_name        TEXT,                       -- ICLifecycleMonitor only

    checked_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- Result
    status              TEXT            NOT NULL,   -- pass / warning / critical / fail
    severity            FLOAT,                      -- 0.0 (clean) to 1.0 (max alert)
    metric_value        FLOAT,
    threshold_value     FLOAT,
    metric_name         TEXT,

    -- Distribution drift fields
    ks_statistic        FLOAT,
    ks_pvalue           FLOAT,
    wasserstein_signed  FLOAT,                      -- signed: positive=shifted right, negative=left
    chi_sq_statistic    FLOAT,
    chi_sq_pvalue       FLOAT,
    cramers_v           FLOAT,
    reference_n         INTEGER,
    current_n           INTEGER,
    reference_regime    TEXT,                       -- majority regime used for conditioning

    -- Lifecycle transition fields
    prior_state         TEXT,
    new_state           TEXT,
    trigger_reason      TEXT,

    -- Recovery state
    recovery_attempts   INTEGER         DEFAULT 0,
    recovery_cleared_at TIMESTAMPTZ,

    -- Halt state
    halt_triggered      BOOLEAN         NOT NULL DEFAULT FALSE,
    halt_reason         TEXT,
    halt_cleared_at     TIMESTAMPTZ,

    query_result        JSONB           -- full row for diagnostics
);

SELECT create_hypertable('integrity_monitor', 'checked_at',
    chunk_time_interval => INTERVAL '30 days', if_not_exists => TRUE);

CREATE INDEX ix_integrity_monitor_type   ON integrity_monitor (monitor_type, checked_at DESC);
CREATE INDEX ix_integrity_monitor_symbol ON integrity_monitor (symbol, timeframe, feature_name, checked_at DESC);
CREATE INDEX ix_integrity_monitor_halt   ON integrity_monitor (monitor_type, halt_triggered) WHERE halt_triggered = TRUE;
```

### Additions to `feature_ic_scores`

Rename `is_decaying → is_shadowed` (column is on schema, not yet wired to ensemble — safe to rename now). Add shadow tracking columns:

```sql
-- Rename existing column
ALTER TABLE feature_ic_scores RENAME COLUMN is_decaying TO is_shadowed;
ALTER TABLE feature_ic_scores RENAME COLUMN decay_detected_at TO shadow_entered_at;
-- Drop recovery_eligible_at: replaced by evidence-based recovery (no cooldown clock)
ALTER TABLE feature_ic_scores DROP COLUMN IF EXISTS recovery_eligible_at;

-- Add shadow tracking
ALTER TABLE feature_ic_scores
    ADD COLUMN IF NOT EXISTS pre_shadow_weight       DOUBLE PRECISION,   -- ic_sharpe at demotion
    ADD COLUMN IF NOT EXISTS shadow_corpus_runs      INTEGER DEFAULT 0,  -- consecutive failing shadow runs
    ADD COLUMN IF NOT EXISTS shadow_confirmation_count INTEGER DEFAULT 0, -- consecutive passing runs (recovery)
    ADD COLUMN IF NOT EXISTS shadow_recovery_confirmed_at TIMESTAMPTZ;   -- when promotion was confirmed

-- Index for ensemble_trainer filter
CREATE INDEX IF NOT EXISTS feature_ic_scores_shadow_idx
    ON feature_ic_scores (is_shadowed, symbol, tf, regime)
    WHERE is_shadowed = true;
```

### Existing table: `feature_deprecations`

Already in schema design (Phase 149B). Operator-confirmed only:

```sql
CREATE TABLE IF NOT EXISTS feature_deprecations (
    feature_name   TEXT        PRIMARY KEY,
    reason         TEXT        NOT NULL,
    deprecated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deprecated_by  TEXT        NOT NULL DEFAULT 'operator'
);
```

---

## APR Keys

| Key | Default | Notes |
|-----|---------|-------|
| **Distribution drift** | | |
| `alpha.drift.ks_check_interval_hours` | 4 | Check cadence |
| `alpha.drift.ks_reference_window_days` | 29 | Reference window size (NOW-37d to NOW-8d) |
| `alpha.drift.ks_current_window_days` | 7 | Current window size |
| `alpha.drift.ks_p_value_threshold` | 0.05 | KS significance |
| `alpha.drift.ks_effect_size_threshold` | 0.10 | Min Wasserstein magnitude for alert |
| `alpha.drift.ks_min_sample` | 50 | Min bars required |
| `alpha.drift.chi_sq_p_value_threshold` | 0.05 | Chi-squared significance |
| `alpha.drift.chi_sq_effect_size_threshold` | 0.10 | Min Cramér's V |
| `alpha.drift.chi_sq_min_sample` | 50 | Min bars required |
| `alpha.drift.recovery_clean_tests_required` | 2 | Consecutive clean tests to clear penalty |
| `alpha.drift.weight_penalty_warning_min` | 0.80 | Floor for warning penalty |
| `alpha.drift.weight_penalty_critical_min` | 0.60 | Floor for critical penalty |
| `alpha.drift.weight_penalty_adaptive` | true | Scale penalty by Wasserstein magnitude |
| `alpha.drift.weight_penalty_warning_scale` | 0.3 | Wasserstein multiplier for warning: `1.0 - magnitude * scale` |
| `alpha.drift.weight_penalty_critical_scale` | 0.5 | Wasserstein multiplier for critical: `1.0 - magnitude * scale` |
| **IC lifecycle (shadow)** | | |
| `alpha.ic.shadow_decay_sharpe_threshold` | 0.0 | IC Sharpe floor for demotion |
| `alpha.ic.shadow_consecutive_passes` | 2 | Consecutive passing corpus runs for promotion |
| `alpha.ic.shadow_max_corpus_runs` | 12 | Consecutive failing shadow runs before deprecation candidate |
| `alpha.ic.shadow_recovery_sharpe_threshold` | 0.0 | IC Sharpe floor for promotion (same as decay by default) |
| **Ensemble health** | | |
| `alpha.ensemble.ic_sharpe_floor_critical` | 0.5 | E1 critical halt threshold |
| `alpha.ensemble.ic_sharpe_floor_warning` | 1.0 | E1 warning threshold |
| `alpha.ensemble.ic_stale_days` | 7 | E1 staleness threshold |
| `alpha.ensemble.conviction_std_warning` | 0.15 | E2 stability warning |
| `alpha.ensemble.conviction_std_critical` | 0.30 | E2 stability critical |
| `alpha.ensemble.conviction_min_samples` | 50 | E2 minimum sample |
| `alpha.ensemble.min_feature_coverage_critical` | 3 | E3 critical floor |
| `alpha.ensemble.min_feature_coverage_warning` | 5 | E3 warning floor |
| `alpha.ensemble.recovery_consecutive_passes` | 2 | Recovery confirmation for ensemble gates |

---

## Observability

**Prometheus metrics (port `:9118`):**

```
integrity_distribution_drift_pvalue{symbol, timeframe, feature, test_type}
integrity_distribution_drift_wasserstein{symbol, timeframe, feature}   -- signed
integrity_distribution_penalty{symbol, timeframe}                       -- active weight multiplier
integrity_ic_shadow_count{tf, regime}                                   -- features currently shadowed
integrity_ic_active_count{tf, regime}                                   -- features currently active
integrity_ic_deprecation_candidate_count                                -- awaiting operator action
integrity_ensemble_gate_status{symbol, tf, regime, gate}                -- 0=fail, 1=warn, 2=pass
integrity_ensemble_halt_active{symbol, tf, regime}                      -- 1 if halted
integrity_check_duration_seconds{monitor_type}                          -- histogram
```

**REST API:**

```
GET /api/integrity/drift          # distribution drift alerts + active penalties
GET /api/integrity/shadow         # features in shadow + promotion candidates
GET /api/integrity/ensemble       # ensemble gate status + halt state
GET /api/integrity               # combined summary
```

**Topic events on state transitions:**
- `topic_integrity_distribution_alert()` — KS or chi-squared fires
- `topic_health_shadow_entered()` — feature demoted to shadow
- `topic_health_shadow_exited()` — feature promoted back to active
- `topic_health_deprecation_candidate()` — feature hit shadow_max_corpus_runs
- `topic_integrity_ensemble_gate_changed()` — any E1/E2/E3 status change

---

## Service Deployment

**Unit:** `indicagent-integrity-monitor.service`
**Port:** `:9118`
**Binary:** `services/integrity_monitor_service.py`

```python
async def main():
    drift_monitor = DistributionDriftMonitor(db, config)
    lifecycle_monitor = ICLifecycleMonitor(db, config)
    ensemble_monitor = EnsembleHealthMonitor(db, config)

    # drift and ensemble run on timers; lifecycle is event-driven
    async with asyncio.TaskGroup() as tg:
        tg.create_task(drift_monitor.run_forever())    # 4h interval
        tg.create_task(ensemble_monitor.run_forever()) # 1h interval
        tg.create_task(lifecycle_monitor.listen())     # subscribes to corpus-complete topic
```

`ICLifecycleMonitor.listen()` subscribes to a Kafka topic that `ic_engine.py` publishes to on completion. No polling required.

---

## Migration Plan

**Phase 149A — IntegrityMonitor foundation + distribution drift:**
1. Migration: `integrity_monitor` hypertable + all distribution drift APR keys
2. `DistributionDriftMonitor`: regime-conditioned KS + chi-squared + signed Wasserstein, merged queries
3. `indicagent-integrity-monitor` service skeleton with `DistributionDriftMonitor` loaded
4. Wire `ensemble_trainer` to read `integrity_monitor` for drift penalty

**Phase 149B — IC shadow lifecycle:**
1. Migration: rename `is_decaying → is_shadowed`, add shadow tracking columns, `feature_deprecations` table, shadow APR keys
2. `ICLifecycleMonitor`: demotion/promotion/deprecation-candidate logic
3. IC engine publishes corpus-complete topic event
4. `ensemble_trainer` adds `AND (is_shadowed = false OR is_shadowed IS NULL)` filter

**Phase 150 — Ensemble health monitor:**
1. Migration: ensemble health APR keys (requires `alpha_ensemble_ic` from Phase 142A)
2. `EnsembleHealthMonitor`: E1/E2/E3 gates, regime-conditioned conviction check
3. `alpha_publisher` reads `alpha.emitter.halted` + `alpha.emitter.conviction_multiplier` before emit

All three phases are independent of core AlphaEngine work (Phases 137-144) and can run in parallel with Phase 142A once ensemble IC measurement is available.

---

## What Jim Simons Would Demand

> "One service. Three monitors. One table. You built this right the first time."

> "Your reference window was blind to regime. You were comparing apple season to orange season and calling it drift. Condition on regime or your drift detector is noise."

> "A benched feature with a cooldown clock is a benched feature guessing. A benched feature in shadow mode is a benched feature proving. The difference is the evidence trail."

> "Wasserstein tells you where the distribution moved. KS only tells you that it moved. Direction is signal."

---

## Success Criteria

**Phase 149A:**
1. KS + chi-squared run every 4h on all 54 features, regime-conditioned
2. Signed Wasserstein recorded for all continuous features
3. Adaptive penalty scaled by Wasserstein magnitude, applied by ensemble_trainer
4. Recovery clears after 2 consecutive clean checks (piggybacked on main cycle)
5. Unit test: no KS alert when trending→ranging regime shift with clean data
6. Unit test: KS alert fires on genuine distribution corruption with N=200
7. Unit test: signed Wasserstein positive for right-shift, negative for left-shift

**Phase 149B:**
1. Feature demoted to shadow when walkforward fails or ic_sharpe < threshold
2. Shadow features: IC continues computing, ensemble weight = 0.0
3. Promotion after 2 consecutive passing corpus runs, `pre_shadow_weight` restored
4. Failed recovery attempt resets `shadow_confirmation_count = 0`
5. `shadow_corpus_runs` increments on each failing shadow run
6. Deprecation candidate event fires at `shadow_max_corpus_runs`
7. `feature_deprecations` insert required for permanent exclusion

**Phase 150:**
1. E1 gate halts emission when `ic_sharpe_hac < 0.5` or IC stale > 7d
2. E2 gate is regime-conditioned — no false warnings during trending periods
3. E3 gate counts only non-shadowed active features
4. All three gates must pass for emission (AND logic)
5. Recovery confirmed after 2 consecutive clean checks
6. `alpha.emitter.halted` APR key checked by `alpha_publisher` before every emit
