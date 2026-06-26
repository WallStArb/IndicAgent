# Renaissance Drift Detection — v3.0 Design

**Date:** 2026-06-26
**Status:** PROPOSED — not planned, awaiting prioritization
**Milestone:** v3.0 Phase 149+ (Data Integrity + Observability)
**v2.x reference:** `docs/plans/archive/2026-03-11-signal-drift-detection-design.md` (shipped March 2026)

---

## Design Principle: Two Independent Detection Layers

The v2.x drift detection system was **Renaissance-grade**: automated feedback loops, no human intervention, bounded downside for false positives. That architecture is correct. What needs to change is the **data source** and **integration points** for v3.0.

**Two independent drift types, both required:**

| Drift Type | What It Detects | v2.x Implementation | v3.0 Adaptation |
|------------|----------------|-------------------|-----------------|
| **Distribution drift** | Input data distribution shifts (IBKR field changes, data corruption) | KS test on `intelligence_features` → CIS confidence penalty | KS test on `feature_vectors` → ensemble weight penalty |
| **IC decay** | Feature's predictive edge eroding over time | Not separate — conflated with CUSUM performance drift | Lifecycle states: `candidate` → `active` → `decaying` → `deprecated` |

**Why both are needed:**

- **Distribution drift** catches data corruption. If IBKR adds a new field to bars, feature formulas still compute but on corrupted data. IC decay won't catch this — the feature may still have IC on corrupted data.

- **IC decay** catches edge erosion. A feature's predictive relationship with forward returns degrades even if input distributions are stable. Distribution drift won't catch this — formulas compute correctly but the alpha is gone.

**Renaissance analysis:** "You had distribution drift detection working in v2.x and dropped it. Why? Data drift is inevitable. You need automated detection or you'll trade on corrupted data for weeks. IC decay catches edge erosion, not data corruption. Both are required layers."

---

## What Changed in v3.0 (vs v2.x)

| Component | v2.x | v3.0 | Impact on Drift Detection |
|-----------|------|------|---------------------------|
| **Feature table** | `intelligence_features` | `feature_vectors` | KS monitor reads different JSONB structure |
| **Scoring layer** | CIS (Composite Intelligence Score) | Ensemble IC weighting | No CIS layer to penalize — penalty applies to ensemble weights |
| **Performance tracking** | `setup_performance` table + perf_multiplier | `alpha_ensemble_ic` (planned Phase 142A) | CUSUM targets ensemble IC instead of per-signal pnl_r |
| **Signal emission** | I7 plugins fire → signal_events | Ensemble conviction → alpha_events | Different granularity for feedback loops |
| **Architecture** | 8-tier pipeline (I1-I7) | 3-layer (FeatureFactory → ICEngine → AlphaEngine) | Simpler DAG, clearer integration points |

**Key insight:** v3.0 removed the CIS layer that v2.x used for drift penalties. The v3.0 equivalent is **ensemble weight adjustment**. When drift is detected, the ensemble re-weights away from affected features.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        v3.0 Drift Detection                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  Layer 1: Distribution Drift (KS test)                           │
│  ┌──────────────┐    ┌──────────────┐                          │
│  │ feature_     │───→│ KS Monitor   │───→ drift_monitor table  │
│  │ vectors      │    │ (every 4h)   │     (penalty queried)    │
│  └──────────────┘    └──────────────┘                          │
│                                                               │
│  Layer 2: IC Decay (lifecycle states)                          │
│  ┌──────────────┐    ┌──────────────┐                          │
│  │ feature_ic_  │───→│ IC Engine    │───→ is_decaying flag     │
│  │ scores       │    │ (on corpus   │     ensemble exclusion    │
│  └──────────────┘    │  runs)       │                          │
│                      └──────────────┘                          │
│                                                               │
│  Ensemble Integration (both layers feed here)                  │
│  ┌─────────────────────────────────────────────┐               │
│  │ ensemble_trainer reads both signals:        │               │
│  │ • drift_monitor penalty → weight reduction  │               │
│  │ • is_decaying=true → feature excluded       │               │
│  └─────────────────────────────────────────────┘               │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

**Service deployment:**
- **Standalone service:** `indicagent-drift-monitor` (reuses v2.x architecture)
- **Port:** `:9118`
- **Check cycles:** KS every 4h, IC decay on corpus runs (event-driven)

---

## Part 1: Distribution Drift (KS Test) — Port v2.x to v3.0

### v2.x Implementation Recap

**What was monitored:** 8 continuous features from `intelligence_features` i1/i4 JSONB

| Feature | Source | Why It Matters |
|---------|--------|----------------|
| `rsi_14` | i1→'rsi_14' | Primary momentum indicator; distribution shift = regime change |
| `atr_14` | i1→'atr_14' | Volatility level; shift = risk environment changed |
| `macd_histogram_12_26_9` | i1→'macd_histogram_12_26_9' | Momentum sign/magnitude distribution |
| `adx_14` | i1→'adx_14' | Trend strength; ADX > 25 normal vs not |
| `volume_ratio` | i1→'volume_ratio' | Institutional participation |
| `stoch_k_14_3` | i1→'stoch_k_14_3' | Oscillator distribution; flat in trending markets |
| `garch_vol` | i4→'garch_vol' | Conditional volatility; drift = GARCH calibration stale |
| `bb_width` | computed: (i1→'bb_20_2_upper' - i1→'bb_20_2_lower') | Raw volatility proxy, independent of GARCH |

**Windows:** Reference (29 days, NOW−37d to NOW−8d) vs Current (7 days, NOW−7d to NOW)

**Alert criteria:** p_value < 0.05 AND ks_statistic > 0.10 AND current_n >= 50

**Severity:**
- `warning`: p < 0.05 AND ks in [0.10, 0.25)
- `critical`: p < 0.01 AND ks ≥ 0.25

**Feedback loop (v2.x):** DragonflyDB key `drift:ks:{symbol}:{tf}` → CIS confidence penalty

---

### v3.0 Adaptation: What Changes

**Data source:** `feature_vectors` instead of `intelligence_features`

**Schema difference:** v3.0 `feature_vectors` stores 54 features as top-level columns, not i1/i4 JSONB nesting

**Monitored features (expand from 8 to 54):**

The v2.x 8-feature set was I1/I4 because that's what existed. v3.0 FeatureFactory computes 54 features. The Renaissance approach: **monitor all 54**. No reason to limit monitoring when the computation cost is bounded and the value is comprehensive.

**Feature categories to monitor:**

1. **Price momentum (10 features):** rsi_* (fast/mid/slow), momentum_z_*, aroon_*
2. **Volatility (8 features):** atr_*, volatility_rank_z, bb_*, garch_vol
3. **Volume (3 features):** volume_ratio, obv_*, vwap_*
4. **Microstructure (7 features):** spread, bid_ask_ratio, order_flow*, realized_vol
5. **Regime (3 features):** hmm_regime_posteriors, vol_of_vol, regime_transition_score
6. **Trend (6 features):** adx_*, macd_*, ichimoku_*
7. **Calendar (4 features):** day_of_week_*, month_*, hour_* (intraday only)
8. **Derived (13 features):** interaction terms, cross-sectional ranks, lagged returns

**KS test applicability:**
- **Continuous features (47):** KS test directly
- **Categorical features (7):** Chi-squared test (day_of_week, month, hour, hmm_regime) — **DEFER to Phase 150**

**Starting implementation:** KS test on 47 continuous features only. Chi-squared for categorical requires separate alert thresholds and more empirical calibration. Add once continuous KS proves value.

---

### DB Query Pattern (v3.0)

```sql
-- Single query per (symbol, tf) per window — 47 features extracted at once
SELECT
    -- Price momentum (10)
    rsi_fast, rsi_mid, rsi_slow,
    momentum_z_fast, momentum_z_mid, momentum_z_slow,
    aroon_fast, aroon_slow, aroon oscillator,
    
    -- Volatility (8)
    atr_fast, atr_mid, atr_slow,
    volatility_rank_z,
    bb_width_fast, bb_width_mid, bb_width_slow,
    garch_vol,
    
    -- Volume (3)
    volume_ratio, obv_ma, vwap_ratio,
    
    -- Microstructure (7)
    spread, bid_ask_ratio,
    order_flow_imbalance, order_flow_acceleration,
    realized_vol_5m, realized_vol_15m, realized_vol_1h,
    
    -- Regime (3)
    hmm_regime_posterior_trending, hmm_regime_posterior_range, hmm_regime_posterior_mean_revert,
    vol_of_vol, regime_transition_score,
    
    -- Trend (6)
    adx_fast, adx_mid, adx_slow,
    macd_histogram, macd_signal, ichimoku_tenkansen_senkansen_span,
    
    -- Derived (remaining continuous features)
    interaction_momentum_volatility, cross_sectional_rank_momentum,
    return_fast, return_mid, return_slow, return_extended,
    lagged_return_1, lagged_return_2, lagged_return_3
FROM feature_vectors
WHERE symbol = $1 AND tf = $2
  AND ts >= NOW() - INTERVAL '37 days'   -- reference: swap to NOW()-7d for current
  AND ts <  NOW() - INTERVAL '7 days';
```

**Query count optimization:** 23 symbols × 4 TFs × 2 windows = **184 queries per 4h cycle** (same as v2.x, despite 6× more features).

---

### Alert Criteria (v3.0)

**Per-feature alert:**

```
ALERT when: p_value < 0.05 AND ks_statistic > 0.10 AND current_n >= 50
```

**Aggregation to symbol/TF level:**

Worst-case severity across all 47 features drives the penalty for that symbol/TF pair. If 5 features are `warning` and 2 are `critical`, the aggregate state is `"critical"`.

**Rationale:** Same as v2.x — simpler than feature-level penalties, no blind spots as new features added.

---

### Feedback Loop: KS Drift → Ensemble Weight Penalty

**v2.x integration:** KS drift → CIS confidence penalty (applied in signal_generator_service, read from DragonflyDB)

**v3.0 integration:** KS drift → ensemble weight adjustment (applied in ensemble_trainer, read from TimescaleDB)

**Why the shift:** No CIS layer in v3.0. The ensemble is the scoring system. No Redis/DragonflyDB in v3.0 stack.

**Mechanism:**

```python
# KS monitor writes to drift_monitor table (TimescaleDB)
# ensemble_trainer queries drift_monitor directly

# ensemble_trainer reads penalty during weight computation
penalty = await conn.fetchval(
    """
    SELECT CASE 
        WHEN alert_severity = 'critical' THEN 0.60
        WHEN alert_severity = 'warning' THEN 0.80
        ELSE 1.0
    END AS penalty
    FROM drift_monitor
    WHERE symbol = $1 AND tf = $2 
      AND check_type = 'ks_distribution'
      AND checked_at > NOW() - INTERVAL '8 hours'
    ORDER BY checked_at DESC LIMIT 1
    """,
    symbol, tf
)

# Apply penalty to all features from this symbol/TF before ensemble weighting
adjusted_feature_ic = feature_ic * (penalty or 1.0)
```

**Why direct DB query instead of cache:**
- ensemble_trainer is batch (daily/weekly), not per-second hot path
- TimescaleDB query is fast enough for periodic reads
- Single source of truth — no state split across cache + DB
- Simpler architecture — one less dependency

**Penalty values (starting values — tune empirically):**
- `warning`: 20% reduction (penalty = 0.80) — distributions shifting, feature less trustworthy
- `critical`: 40% reduction (penalty = 0.60) — significant distribution shift, features heavily discounted

**Why harsher than v2.x:** v2.x CIS penalty was 15%/30%. v3.0 ensemble operates on fewer, more orthogonal features. A drift event affects a larger proportion of the alpha source. 20%/40% compensates for the higher impact per feature.

**Stale penalty handling:** Query filters `checked_at > NOW() - INTERVAL '8 hours'` (2× check interval). If no recent row, penalty defaults to 1.0 (no penalty). This provides automatic expiry without TTL mechanics.

---

## Part 2: IC Decay Detection — Execute feature-vector-lifecycle.md Spec

### Concept Already Spec'd

`docs/ideas/feature-vector-lifecycle.md` (Jun 25) already specifies IC decay detection. This section pulls that spec into the implementation plan.

**What it does:** Detects when a feature's IC (predictive edge) degrades over time

**States:**
- `candidate`: Never passed IC gates or unreliable
- `active`: Passes all gates (`passes_walkforward`, `reliable`, `passes_ci_gate`)
- `decaying`: Was active; recent IC run shows degraded edge
- `deprecated`: Manually removed or feature definition changed

**Transitions:**
```
candidate ──[IC gate pass]──► active ──[IC run: edge gone]──► decaying
                                  ▲                               │
                                  └───[cooldown elapsed + IC re-pass]──┘
```

**Trigger conditions (active → decaying):**
- `passes_walkforward` flips to `false`, OR
- `ic_sharpe` drops below `alpha.ic.decay_ic_sharpe_threshold` (default 0.0), OR
- `reliable` drops to `false` (corpus shrank, symbol delisted)

**Recovery (decaying → active):**
- Eligible after `recovery_eligible_at = decay_detected_at + alpha.ic.decay_cooldown_days`
- Default cooldown: 30 days (one IC cycle)
- If next IC run produces passing row, set `is_decaying = false` and clear timestamps

**Columns (already exist in schema):**
- `is_decaying` (boolean)
- `decay_detected_at` (timestamptz)
- `recovery_eligible_at` (timestamptz)

---

### Implementation: IC Engine Changes

**Trigger detection on each corpus run:**

```python
# In ic_engine.py, after writing new feature_ic_scores row
# Compare against prior row to detect state flip

prior = await conn.fetchrow(
    """
    SELECT passes_walkforward, is_decaying
    FROM feature_ic_scores
    WHERE feature_name=$1 AND symbol=$2 AND tf=$3 AND regime=$4
      AND lookahead_bars=$5 AND is_pooled=false
    ORDER BY training_window_end DESC LIMIT 1
    """,
    feature_name, symbol, tf, regime, lookahead_bars
)

currently_active = prior and prior["passes_walkforward"] and not prior["is_decaying"]
now_failing = not passes_walkforward  # current run result

if currently_active and now_failing:
    await conn.execute(
        """
        UPDATE feature_ic_scores
        SET is_decaying=true, decay_detected_at=$1,
            recovery_eligible_at=$1 + (alpha_ic_decay_cooldown_days * INTERVAL '1 day')
        WHERE feature_name=$2 AND symbol=$3 AND tf=$4 AND regime=$5
          AND lookahead_bars=$6 AND is_pooled=false
          AND training_window_end=$7
        """,
        now(), feature_name, symbol, tf, regime, lookahead_bars, training_window_end
    )
```

**Topic event (observability):**

```python
# Publish to topic on state transition
topic_feature_lifecycle_transition()
event = FeatureLifecycleEvent(
    feature_name=feature_name,
    symbol=symbol, tf=tf, regime=regime,
    prior_state="active",
    new_state="decaying",
    trigger_reason="ic_walkforward_failed",
    occurred_at=now()
)
```

---

### Ensemble Integration: IC Decay → Feature Exclusion

**ensemble_trainer query change:**

```sql
-- Current query ( Phase 142A )
SELECT ... FROM feature_ic_scores
WHERE is_pooled = false AND passes_walkforward = true
  AND reliable = true AND ic_sharpe IS NOT NULL

-- After IC decay implementation
SELECT ... FROM feature_ic_scores
WHERE is_pooled = false AND passes_walkforward = true
  AND reliable = true AND ic_sharpe IS NOT NULL
  AND (is_decaying = false OR is_decaying IS NULL)
  AND feature_name NOT IN (SELECT feature_name FROM feature_deprecations)
```

**Effect:** Decaying features are excluded from ensemble training. The ensemble re-weights across remaining features.

---

## Part 3: Integration Architecture — Both Layers Working Together

### How the Two Drift Layers Interact

```
Scenario 1: Distribution drift detected (KS alert)
┌─────────────────────────────────────────────────────────────┐
│ KS monitor detects rsi_fast distribution shifted             │
│ → Writes drift_monitor row: alert_severity='warning'          │
│ → ensemble_trainer applies 0.80 penalty to all ES 1m feats  │
│ → Ensemble reduces weight on ES 1m features                 │
│ → System continues trading, just with lower conviction     │
└─────────────────────────────────────────────────────────────┘

Scenario 2: IC decay detected (lifecycle state change)
┌─────────────────────────────────────────────────────────────┐
│ IC engine detects momentum_z_mid Sharpe dropped to 0.0     │
│ → Sets is_decaying=true for momentum_z_mid                │
│ → ensemble_trainer excludes momentum_z_mid from training  │
│ → Ensemble re-weights across remaining features          │
│ → System adapts automatically, no manual intervention       │
└─────────────────────────────────────────────────────────────┘

Scenario 3: Both detected (cascade)
┌─────────────────────────────────────────────────────────────┐
│ KS alert active (0.60 penalty on ES 1m)                     │
│ → momentum_z_mid decays (excluded from ensemble)            │
│ → Remaining ES 1m features get 0.60 penalty applied        │
│ → Ensemble conviction drops from two independent signals │
│ → Graceful degradation, not binary on/off                  │
└─────────────────────────────────────────────────────────────┘
```

**Key principle:** The two layers are **orthogonal**. Distribution drift says "this data is suspicious." IC decay says "this feature lost its edge." Both can be true simultaneously. The ensemble respects both signals.

---

### Service Deployment: indicagent-drift-monitor (v3.0)

**Reuse v2.x architecture, new data source:**

```python
# services/drift_monitor_service.py (v3.0 adaptation)
async def main():
    dist_monitor = DistributionDriftMonitor(db, settings)  # KS on feature_vectors
    # IC decay is event-driven (runs in ic_engine.py), not a separate timer
    await dist_monitor.run_forever(interval_seconds=4 * 3600)
```

**Component changes from v2.x:**

| Component | v2.x | v3.0 |
|-----------|------|------|
| **KS data source** | `intelligence_features` (i1/i4 JSONB) | `feature_vectors` (54 top-level columns) |
| **Monitored features** | 8 continuous features | 47 continuous features (7 categorical deferred) |
| **Feedback integration** | CIS confidence penalty | Ensemble weight penalty |
| **Penalty values** | warning=0.85, critical=0.70 | warning=0.80, critical=0.60 |
| **IC decay** | Conflated with CUSUM | Separate lifecycle states |

**What stays the same:**
- Service architecture (standalone daemon, Prometheus metrics, API endpoint)
- KS test parameters (p < 0.05, ks > 0.10, n ≥ 50)
- Alert severity thresholds (warning: ks 0.10-0.25, critical: ks ≥ 0.25)
- Direct DB queries to drift_monitor (no cache layer)
- CUSUM monitoring (repurposed for ensemble IC instead of per-signal pnl_r) — **see below**

---

## Part 4: CUSUM Repurposing — Ensemble IC Monitoring

### v2.x CUSUM (Performance Drift) → v3.0 Adaptation

**v2.x CUSUM monitored:** per-signal pnl_r from `signal_ledger`

**v3.0 CUSUM monitors:** ensemble IC from `alpha_ensemble_ic` (planned Phase 142A)

**Rationale:** v3.0 no longer has per-signal pnl_r tracking at emission time. The ensemble is the emission layer. CUSUM should monitor whether the **ensemble's IC** is degrading.

**Implementation (after Phase 142A ships):**

```python
# CUSUMMonitor reads alpha_ensemble_ic instead of signal_ledger
SELECT ic_mean, ic_sharpe, fdr_passed, walk_forward_stable
FROM alpha_ensemble_ic
WHERE symbol = $1 AND tf = $2 AND regime = $3
  AND lookahead = $4
ORDER BY scored_at ASC;

# Baseline: first 20 IC measurements per (symbol, tf, regime, lookahead)
μ₀ = mean(ic_mean[0:20])
σ₀ = std(ic_mean[0:20])  # clamped to minimum 0.5

# CUSUM on ic_mean (same algorithm as v2.x)
x_n = (ic_mean[n] - μ₀) / σ₀
S+_n = max(0, S+_{n-1} + (x_n - k))    # detects improvement
S-_n = max(0, S-_{n-1} + (-x_n - k))   # detects degradation

# Alert when S- > h (4.0σ)
```

**Feedback loop:** CUSUM ensemble IC drift → reduce overall ensemble weight (or halt emission if critical)

**Implementation timing:** Phase 150 — requires `alpha_ensemble_ic` table from Phase 142A

---

## DB Schema

### Migration 026 (Reuse v2.x, Adapt for v3.0)

**Table:** `drift_monitor` (hypertable, same structure as v2.x)

```sql
CREATE TABLE IF NOT EXISTS drift_monitor (
    id              BIGSERIAL       PRIMARY KEY,
    check_type      TEXT            NOT NULL,
    symbol          TEXT            NOT NULL,
    timeframe       TEXT,
    feature_name    TEXT,
    checked_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- KS fields (distribution drift)
    ks_statistic    FLOAT,
    ks_pvalue       FLOAT,
    reference_n     INTEGER,
    current_n       INTEGER,

    -- CUSUM fields (ensemble IC drift)
    cusum_pos       FLOAT,
    cusum_neg       FLOAT,
    cusum_threshold FLOAT,
    baseline_mean   FLOAT,
    baseline_std    FLOAT,
    total_outcomes  INTEGER,

    -- Shared
    alert_triggered BOOLEAN         NOT NULL DEFAULT FALSE,
    alert_severity  TEXT,
    alert_message   TEXT
);

SELECT create_hypertable(
    'drift_monitor', 'checked_at',
    chunk_time_interval => INTERVAL '30 days',
    if_not_exists => TRUE
);
```

**New table:** `feature_deprecations` (manual deprecation log)

```sql
CREATE TABLE IF NOT EXISTS feature_deprecations (
    feature_name   TEXT            PRIMARY KEY,
    reason         TEXT            NOT NULL,
    deprecated_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    deprecated_by  TEXT            NOT NULL DEFAULT 'system'
);
```

**APR keys:**

| Key | Default | Purpose |
|-----|---------|---------|
| `alpha.drift.ks_check_interval_hours` | 4 | KS monitor check frequency |
| `alpha.drift.ks_p_value_threshold` | 0.05 | KS significance threshold |
| `alpha.drift.ks_effect_size_threshold` | 0.10 | Minimum ks_statistic for alert |
| `alpha.drift.ks_min_sample` | 50 | Minimum current_n for alert |
| `alpha.drift.weight_penalty_warning` | 0.80 | Ensemble weight multiplier for KS warning |
| `alpha.drift.weight_penalty_critical` | 0.60 | Ensemble weight multiplier for KS critical |
| `alpha.ic.decay_ic_sharpe_threshold` | 0.0 | IC Sharpe floor for decay detection |
| `alpha.ic.decay_cooldown_days` | 30 | Recovery cooldown after decay |
| `alpha.drift.cusum_k` | 0.5 | CUSUM allowance (σ units) |
| `alpha.drift.cusum_h` | 4.0 | CUSUM decision threshold (σ units) |
| `alpha.drift.cusum_h_critical` | 8.0 | CUSUM critical threshold (σ units) |
| `alpha.drift.cusum_min_outcomes` | 20 | Minimum IC measurements before CUSUM |

---

## Observability

### Prometheus Metrics

**Port:** `:9118` (same as v2.x)

**Metrics (adapted for v3.0):**

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `drift_ks_pvalue` | Gauge | `symbol, timeframe, feature` | Most recent KS p-value |
| `drift_ks_statistic` | Gauge | `symbol, timeframe, feature` | Most recent KS statistic (0–1) |
| `drift_ks_alert_total` | Counter | `symbol, timeframe, feature, severity` | Cumulative KS alerts |
| `drift_distribution_penalty` | Gauge | `symbol, timeframe` | Active ensemble weight penalty (1.0 / 0.80 / 0.60) |
| `drift_feature_ic_decaying_count` | Gauge | `tf, regime` | How many features currently decaying |
| `drift_feature_active_count` | Gauge | `tf, regime` | How many features currently active |
| `drift_cusum_ensemble_neg` | Gauge | `symbol, tf, regime, lookahead` | Current S- for ensemble IC |
| `drift_cusum_ensemble_pos` | Gauge | `symbol, tf, regime, lookahead` | Current S+ for ensemble IC |
| `drift_cusum_ensemble_alert_total` | Counter | `symbol, tf, regime, lookahead, severity` | Cumulative ensemble IC CUSUM alerts |
| `drift_monitor_check_duration_seconds` | Histogram | `check_type` | Time to complete one check cycle |

**Grafana alert rules:**
- `drift_ks_pvalue < 0.05` (filtered by `drift_ks_statistic > 0.10`)
- `drift_distribution_penalty < 1.0`
- `drift_feature_ic_decaying_count > 0`
- `drift_cusum_ensemble_neg > drift_cusum_ensemble_threshold`

---

### API Endpoint

**File:** `src/api/routes/drift.py`

**Route:**

```
GET /api/dift
```

**Response:**

```json
{
  "distribution_alerts": [
    {
      "symbol": "ES",
      "timeframe": "1m",
      "feature": "rsi_fast",
      "ks_statistic": 0.18,
      "ks_pvalue": 0.003,
      "severity": "warning",
      "penalty_active": 0.80,
      "checked_at": "2026-06-26T14:00:00Z"
    }
  ],
  "ic_decay_alerts": [
    {
      "feature_name": "momentum_z_mid",
      "symbol": "ES",
      "tf": "1m",
      "regime": "trending",
      "ic_sharpe": 0.0,
      "decayed_at": "2026-06-26T12:00:00Z",
      "recovery_eligible_at": "2026-07-26T12:00:00Z"
    }
  ],
  "ensemble_cusum_alerts": [
    {
      "symbol": "ES",
      "tf": "1m",
      "regime": "trending",
      "lookahead": "fast",
      "cusum_neg": 5.2,
      "threshold": 4.0,
      "total_ic_measurements": 87,
      "severity": "warning",
      "checked_at": "2026-06-26T13:00:00Z"
    }
  ]
}
```

---

## Migration Strategy

### Phase 149A: Distribution Drift (KS Test)

**Goal:** Port v2.x KS monitor to `feature_vectors`

**Migration order:**
1. Apply migration 026 (reuses v2.x schema, no changes needed)
2. Deploy `indicagent-drift-monitor` service with KS monitor only
3. Update `ensemble_trainer` to query drift_monitor for penalties (if Phase 142A complete)
4. Confirm Prometheus metrics visible at `:9118`
5. Verify `GET /api/drift` returns distribution alerts

**Dependencies:**
- None (can run in parallel with Phase 142A ensemble IC work)

---

### Phase 149B: IC Decay Detection

**Goal:** Execute `feature-vector-lifecycle.md` spec

**Implementation order:**
1. `feature_deprecations` table (add to migration 026 or separate migration)
2. Update `ic_engine.py` to detect decay and set `is_decaying` flag
3. Add APR keys for decay thresholds
4. Update `ensemble_trainer` query to exclude `is_decaying` features
5. Add Prometheus metrics: `drift_feature_ic_decaying_count`, `drift_feature_active_count`
6. Add topic event: `topic_feature_lifecycle_transition()`

**Dependencies:**
- Phase 139 (alpha_events table exists)
- Phase 140-141 (IC engine running, corpus backfilled)
- Phase 142A (ensemble_trainer exists, even if preliminary)

---

### Phase 150: Ensemble IC CUSUM + Chi-Square

**Goal:** Repurpose CUSUM for ensemble IC, add chi-squared for categorical features

**Implementation order:**
1. Extend `drift_monitor_service.py` with CUSUMMonitor for `alpha_ensemble_ic`
2. Add chi-squared test for categorical features (day_of_week, month, hour, hmm_regime)
3. Update alert thresholds and penalty calculations
4. Extend observability (metrics, API endpoint)

**Dependencies:**
- Phase 142A (`alpha_ensemble_ic` table exists)
- Phase 149A-149B (distribution drift + IC decay operational)

---

## Success Criteria

### Phase 149A (Distribution Drift)

1. ✅ KS check runs every 4h on all 47 continuous features per symbol/TF
2. ✅ `drift_monitor` table populated with KS results every 4h
3. ✅ `drift_monitor` table populated with KS results every 4h
4. ✅ `ensemble_trainer` queries `drift_monitor` and applies penalty to feature weights
5. ✅ Unit test: KS warning fires when `reference = Normal(0,1)` and `current = Normal(1.5,1)` with N=200
6. ✅ Prometheus metrics visible at `:9118`
7. ✅ `GET /api/drift` returns distribution alerts

### Phase 149B (IC Decay)

1. ✅ IC engine sets `is_decaying=true` when feature fails walkforward
2. ✅ `recovery_eligible_at = decay_detected_at + 30 days`
3. ✅ `ensemble_trainer` excludes `is_decaying` features from training
4. ✅ Decayed feature recovers after cooldown if IC gate re-passes
5. ✅ Prometheus metrics: `drift_feature_ic_decaying_count` reflects active decays
6. ✅ Topic event published on state transition

### Phase 150 (Ensemble IC CUSUM + Chi-Square)

1. ✅ CUSUM fires warning when ensemble IC drops >4σ from baseline
2. ✅ Chi-squared test runs on 7 categorical features
3. ✅ All three layers (KS distribution, IC decay, CUSUM ensemble) operational
4. ✅ Cascade scenario works: KS alert + IC decay → ensemble adapts correctly

---

## What Jim Simons Would Demand

> "You had this working in v2.x and you dropped it. Why? Data drift is inevitable. You need automated detection or you'll trade on corrupted data for weeks."
>
> "Detection without action is surveillance. When distributions drift, the system must adapt automatically — no human intervention, no 3am panic calls."
>
> "IC decay is orthogonal to distribution drift. A feature can compute correctly on corrupted data (high KS drift) and still have IC. A feature can have stable distributions but lose its edge (IC decay). You need both layers."
>
> "False positives are acceptable. The cost of briefly under-weighting a healthy feature is bounded and recoverable. The cost of missing a genuine degradation signal is unbounded — you continue trading on decayed features at full weight. Accept the false positive risk."

---

## Parameter Summary (All Starting Values — Tune Empirically)

| Parameter | Value | Notes |
|-----------|-------|-------|
| **KS Distribution Drift** | | |
| KS reference window | 29 days (NOW−37d to NOW−8d) | Sliding; self-correcting |
| KS current window | 7 days (NOW−7d to NOW) | |
| KS p-value threshold | 0.05 | Standard significance |
| KS effect size threshold | 0.10 | Minimum ks_statistic for alert |
| KS min sample | 50 bars | Guard for short-history TFs |
| KS warning penalty | 0.80 | 20% ensemble weight reduction |
| KS critical penalty | 0.60 | 40% ensemble weight reduction |
| KS check interval | 4 hours | |
| **IC Decay** | | |
| IC Sharpe decay floor | 0.0 | `alpha.ic.decay_ic_sharpe_threshold` |
| Decay cooldown | 30 days | `alpha.ic.decay_cooldown_days` |
| **Ensemble IC CUSUM** | | |
| CUSUM k (allowance) | 0.5 σ | Min detectable shift |
| CUSUM h (threshold) | 4.0 σ | Warning trigger |
| CUSUM h_critical | 8.0 σ | Critical trigger |
| CUSUM min IC measurements | 20 | Before monitoring begins |

---

## What's Deferred

| Item | Why Deferred |
|------|--------------|
| Chi-squared tests for categorical features | Continuous KS captures most structural shifts; add once continuous KS proves value |
| Feature-level granularity for KS penalties | Coarser symbol/TF-level penalty is simpler, safer, easier to maintain |
| Per-TF CUSUM | Most setups lack 20 outcomes per TF yet; add after 3+ months of ensemble IC history |
| Automatic CUSUM reset | Requires human investigation before re-baselining; auto-reset masks recurring degradation |

---

## Execution Order

**Phase 149A (Distribution Drift):**
1. Deploy drift_monitor_service with KS monitor
2. Wire ensemble_trainer to query drift_monitor for penalties

**Phase 149B (IC Decay):**
3. Implement feature-vector-lifecycle.md spec
4. Add Prometheus metrics + topic events

**Phase 150 (Ensemble IC + Chi-Square):**
5. Repurpose CUSUM for ensemble IC
6. Add chi-squared for categorical features

All phases are independent of core v3.0 AlphaEngine work (Phases 137-144). Can run in parallel once Phase 142A (ensemble IC measurement) ships.

---

**This plan restores v2.x drift detection capabilities to v3.0, adapts them to the feature_vectors architecture, and adds IC decay detection as a second orthogonal layer. The system trades on degraded features automatically — with bounded downside for false positives and unbounded protection against genuine degradation.**
