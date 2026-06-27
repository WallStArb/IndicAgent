# Feature Distribution Drift Detection — KS Test on 54 Features

**Date:** 2026-06-26
**Status:** PROPOSED — not planned, awaiting prioritization
**Milestone:** v3.0 Phase 149A (Data Integrity)
**v2.x reference:** `docs/plans/archive/2026-03-11-signal-drift-detection-design.md` (shipped March 2026)
**Service design:** `docs/ideas/data-integrity-monitor-design.md` (Renaissance-grade reusable platform)

---

## Design Principle

Distribution drift catches **data corruption**. If IBKR adds a new field to bars, feature formulas still compute but on corrupted data. IC decay won't catch this — the feature may still have IC on corrupted data.

**Renaissance analysis:** "You had distribution drift detection working in v2.x and dropped it. Why? Data drift is inevitable. You need automated detection or you'll trade on corrupted data for weeks. IC decay catches edge erosion, not data corruption. Both are required layers."

**Renaissance-grade requirement:** Monitor all 54 features from day one. No partial coverage. 13% blind is unacceptable when the computation cost is bounded.

---

## What Changed in v3.0 (vs v2.x)

| Component | v2.x | v3.0 | Impact on Drift Detection |
|-----------|------|------|---------------------------|
| **Feature table** | `intelligence_features` | `feature_vectors` | KS monitor reads different JSONB structure |
| **Scoring layer** | CIS (Composite Intelligence Score) | Ensemble IC weighting | No CIS layer to penalize — penalty applies to ensemble weights |

**Key insight:** v3.0 removed the CIS layer that v2.x used for drift penalties. The v3.0 equivalent is **ensemble weight adjustment**. When drift is detected, the ensemble re-weights away from affected features.

---

## v2.x Implementation Recap

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

## v3.0 Adaptation: What Changes

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
- **Categorical features (7):** Chi-squared test (day_of_week, month, hour, hmm_regime) — **Phase 149A, complete coverage**

**Renaissance-grade requirement:** All 54 features monitored from day one. Chi-squared uses same alert framework as KS test — p-value < 0.05, effect size threshold via Cramér's V. No partial coverage, no deferred work.

---

## DB Query Pattern (v3.0)

```sql
-- Single query per (symbol, tf) per window — 47 features extracted at once
SELECT
    -- Price momentum (10)
    rsi_fast, rsi_mid, rsi_slow,
    momentum_z_fast, momentum_z_mid, momentum_z_slow,
    aroon_fast, aroon_slow, aroon_oscillator,

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

**Query count optimization:** 23 symbols × 4 TFs × 2 windows = **184 queries per 4h cycle** (same as v2.x, despite 6.75× more features).

**Chi-squared query pattern (categorical features):**

```sql
-- Single query per (symbol, tf) per window — 7 categorical features
SELECT
    day_of_week, month, hour,  -- Calendar
    hmm_regime_posterior_trending, hmm_regime_posterior_range, hmm_regime_posterior_mean_revert
FROM feature_vectors
WHERE symbol = $1 AND tf = $2
  AND ts >= NOW() - INTERVAL '37 days'   -- reference: swap to NOW()-7d for current
  AND ts <  NOW() - INTERVAL '7 days';

-- Chi-squared test on each categorical column
for feature in ["day_of_week", "month", "hour", "hmm_regime"]:
    reference_dist = reference[feature].value_counts(normalize=True)
    current_dist = current[feature].value_counts(normalize=True)
    chi2_stat, chi2_p, dof, expected = scipy.stats.chi2_contingency(
        pd.concat([reference_dist, current_dist], axis=1)
    )
    cramér_v = np.sqrt(chi2_stat / (len(data) * (min(reference_dist.shape) - 1)))

    ALERT when: chi2_p < 0.05 AND cramér_v > 0.10 AND current_n >= 50
```

**Total queries per 4h cycle:** 23 symbols × 4 TFs × 2 windows × 2 test types (KS + chi-squared) = **368 queries**

---

## Alert Criteria (v3.0)

**Per-feature alert:**

```
ALERT when: p_value < 0.05 AND ks_statistic > 0.10 AND current_n >= 50
```

**Aggregation to symbol/TF level:**

Worst-case severity across all 47 features drives the penalty for that symbol/TF pair. If 5 features are `warning` and 2 are `critical`, the aggregate state is `"critical"`.

**Rationale:** Same as v2.x — simpler than feature-level penalties, no blind spots as new features added.

---

## Feedback Loop: KS Drift → Ensemble Weight Penalty

**v2.x integration:** KS drift → CIS confidence penalty (applied in signal_generator_service, read from DragonflyDB)

**v3.0 integration:** KS drift → ensemble weight adjustment (applied in ensemble_trainer, read from TimescaleDB)

**Why the shift:** No CIS layer in v3.0. The ensemble is the scoring system. No Redis/DragonflyDB in v3.0 stack.

**Mechanism (with adaptive penalties):**

```python
# KS monitor writes to drift_monitor table (TimescaleDB)
# ensemble_trainer queries drift_monitor directly

# ensemble_trainer reads penalty during weight computation
penalty = await conn.fetchval(
    """
    SELECT CASE
        WHEN alert_severity = 'critical' THEN
            CASE
                WHEN $3 = true THEN
                    GREATEST(0.40, 1.0 - (ks_statistic * 0.5))  -- Adaptive: scale by effect size
                ELSE
                    0.60  -- Fixed base penalty
            END
        WHEN alert_severity = 'warning' THEN
            CASE
                WHEN $3 = true THEN
                    GREATEST(0.70, 1.0 - (ks_statistic * 0.3))   -- Adaptive: scale by effect size
                ELSE
                    0.80  -- Fixed base penalty
            END
        ELSE 1.0
    END AS penalty
    FROM drift_monitor
    WHERE symbol = $1 AND tf = $2
      AND check_type IN ('ks_distribution', 'chi_squared')
      AND checked_at > NOW() - INTERVAL '8 hours'
      AND (penalty_cleared_at IS NULL OR penalty_cleared_at > checked_at)
    ORDER BY checked_at DESC LIMIT 1
    """,
    symbol, tf, adaptive_enabled
)

# Apply penalty to all features from this symbol/TF before ensemble weighting
adjusted_feature_ic = feature_ic * (penalty or 1.0)
```

**Adaptive penalty formula (Renaissance-grade):**

Scale penalty by effect size (ks_statistic or cramér_v):
- `warning`: `penalty = max(0.70, 1.0 - ks_statistic * 0.3)`
  - ks=0.10 → penalty=0.97 (3% reduction)
  - ks=0.18 → penalty=0.85 (15% reduction)
  - ks=0.25 → penalty=0.80 (20% reduction, base)
- `critical`: `penalty = max(0.40, 1.0 - ks_statistic * 0.5)`
  - ks=0.25 → penalty=0.88 (12% reduction)
  - ks=0.40 → penalty=0.80 (20% reduction)
  - ks=0.60 → penalty=0.70 (30% reduction)

**Why adaptive:** Fixed 20%/40% penalties treat ks=0.10 (minor drift) the same as ks=0.60 (severe drift). Adaptive scaling matches penalty to severity.

**Recovery state machine (Renaissance-grade):**

```python
# After KS alert fires, monitor runs recovery checks every 4h
if alert_triggered and not recovery_required:
    recovery_attempts += 1
    recovery_checked_at = now()

    # Re-test with fresh data
    new_ks_stat, new_ks_p = run_ks_test(reference, current)

    if new_ks_p >= 0.05 or new_ks_stat < 0.10:
        # Clean test
        if recovery_attempts >= 2:  # Require 2 consecutive clean tests
            recovery_required = true  # Flag for penalty clear
            penalty_cleared_at = now()
    else:
        # Still drifting, reset counter
        recovery_attempts = 0
```

**Why recovery state machine:** Fixed 8h expiry is amnesia, not recovery. System should know when distributions normalize and clear penalty early. Require 2 consecutive clean tests to avoid flapping.

**Why direct DB query instead of cache:**
- ensemble_trainer is batch (daily/weekly), not per-second hot path
- TimescaleDB query is fast enough for periodic reads
- Single source of truth — no state split across cache + DB
- Simpler architecture — one less dependency

---

## DB Schema

### Migration 026 (Renaissance-Grade: Complete Coverage + Recovery State)

**Table:** `drift_monitor` (hypertable, enhanced schema)

```sql
CREATE TABLE IF NOT EXISTS drift_monitor (
    id                  BIGSERIAL       PRIMARY KEY,
    check_type          TEXT            NOT NULL,  -- ks_distribution / chi_squared
    symbol              TEXT            NOT NULL,
    timeframe           TEXT,
    feature_name        TEXT,
    checked_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- KS fields (distribution drift)
    ks_statistic        FLOAT,
    ks_pvalue           FLOAT,
    reference_n         INTEGER,
    current_n           INTEGER,

    -- Chi-squared fields (categorical drift)
    chi_sq_statistic    FLOAT,
    chi_sq_pvalue       FLOAT,
    cramers_v           FLOAT,              -- Effect size for chi-squared
    reference_dist      JSONB,              -- Reference distribution (for debugging)
    current_dist        JSONB,              -- Current distribution (for debugging)

    -- CUSUM fields (ensemble IC drift) — unused in Phase 149A
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
    recovery_required   BOOLEAN DEFAULT FALSE, -- Set to true after 2 consecutive clean tests

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

CREATE INDEX ix_drift_monitor_recovery ON drift_monitor(symbol, timeframe, feature_name, recovery_checked_at DESC);
```

**APR keys (Renaissance-grade: All parameters tunable):**

| Key | Default | Purpose |
|-----|---------|---------|
| `alpha.drift.ks_check_interval_hours` | 4 | KS monitor check frequency |
| `alpha.drift.ks_reference_window_days` | 29 | KS reference window (NOW−37d to NOW−8d) |
| `alpha.drift.ks_current_window_days` | 7 | KS current window (NOW−7d to NOW) |
| `alpha.drift.ks_p_value_threshold` | 0.05 | KS significance threshold |
| `alpha.drift.ks_effect_size_threshold` | 0.10 | Minimum ks_statistic for alert |
| `alpha.drift.ks_min_sample` | 50 | Minimum current_n for alert |
| `alpha.drift.chi_sq_p_value_threshold` | 0.05 | Chi-squared significance threshold |
| `alpha.drift.chi_sq_effect_size_threshold` | 0.10 | Minimum cramér_v for alert |
| `alpha.drift.chi_sq_min_sample` | 50 | Minimum current_n for chi-squared alert |
| `alpha.drift.recovery_check_interval_hours` | 4 | Recovery re-test frequency |
| `alpha.drift.recovery_clean_tests_required` | 2 | Consecutive clean tests before clearing penalty |
| `alpha.drift.weight_penalty_warning_min` | 0.80 | Base penalty for warning |
| `alpha.drift.weight_penalty_critical_min` | 0.60 | Base penalty for critical |
| `alpha.drift.weight_penalty_adaptive` | true | Scale penalty by effect size |

**Why KS windows in APR:** Hardcoded windows in SQL queries require migrations to tune. APR allows operator to adjust windows without code changes.

---

## Migration Strategy

### Phase 149A: Distribution Drift (KS + Chi-Squared, Renaissance-Grade)

**Goal:** Port v2.x KS monitor to `feature_vectors` with complete coverage (all 54 features)

**Migration order:**
1. Apply migration 026 with enhanced schema (recovery columns + chi-squared fields)
2. Add all APR keys (KS windows, chi-squared thresholds, recovery params)
3. Deploy `indicagent-drift-monitor` service with KS + chi-squared monitors
4. Implement adaptive penalty formula (scale by effect size)
5. Implement recovery state machine (2 consecutive clean tests)
6. Update `ensemble_trainer` to query drift_monitor with adaptive penalties
7. Confirm Prometheus metrics visible at `:9118`
8. Verify `GET /api/drift` returns distribution alerts for both KS and chi-squared

**Renaissance-grade requirements:**
- ✅ All 54 features monitored (47 KS + 7 chi-squared)
- ✅ All parameters APR-backed (KS windows, thresholds, penalties)
- ✅ Recovery state machine (not just penalty expiry)
- ✅ Adaptive penalties (scale by effect size)

**Dependencies:**
- None (can run in parallel with Phase 142A ensemble IC work)

---

## Success Criteria

### Phase 149A (Distribution Drift — Renaissance-Grade)

1. ✅ KS check runs every 4h on all 47 continuous features per symbol/TF
2. ✅ Chi-squared check runs every 4h on all 7 categorical features per symbol/TF
3. ✅ `drift_monitor` table populated with KS + chi-squared results every 4h
4. ✅ `ensemble_trainer` queries `drift_monitor` and applies adaptive penalty to feature weights
5. ✅ Unit test: KS warning fires when `reference = Normal(0,1)` and `current = Normal(1.5,1)` with N=200
6. ✅ Unit test: Chi-squared warning fires when day_of_week distribution shifts (uniform → weekday-heavy)
7. ✅ Unit test: Adaptive penalty scales correctly (ks=0.10 → 0.97, ks=0.60 → 0.70)
8. ✅ Unit test: Recovery clears penalty after 2 consecutive clean tests
9. ✅ Prometheus metrics visible at `:9118`
10. ✅ `GET /api/drift` returns distribution alerts for both KS and chi-squared
11. ✅ All KS windows, thresholds, and penalties are APR-backed (tunable without migrations)

---

## Parameter Summary (Starting Values — All APR-Backed, Tune Empirically)

| Parameter | Value | Notes |
|-----------|-------|-------|
| **KS Distribution Drift** | | |
| KS reference window | 29 days (NOW−37d to NOW−8d) | `alpha.drift.ks_reference_window_days` — Sliding; self-correcting |
| KS current window | 7 days (NOW−7d to NOW) | `alpha.drift.ks_current_window_days` |
| KS p-value threshold | 0.05 | `alpha.drift.ks_p_value_threshold` — Standard significance |
| KS effect size threshold | 0.10 | `alpha.drift.ks_effect_size_threshold` — Minimum ks_statistic |
| KS min sample | 50 bars | `alpha.drift.ks_min_sample` — Guard for short-history TFs |
| **Chi-Squared Categorical Drift** | | |
| Chi-squared p-value threshold | 0.05 | `alpha.drift.chi_sq_p_value_threshold` |
| Chi-squared effect size threshold | 0.10 | `alpha.drift.chi_sq_effect_size_threshold` — Minimum cramér_v |
| Chi-squared min sample | 50 bars | `alpha.drift.chi_sq_min_sample` |
| **Recovery State Machine** | | |
| Recovery check interval | 4 hours | `alpha.drift.recovery_check_interval_hours` |
| Recovery clean tests required | 2 | `alpha.drift.recovery_clean_tests_required` |
| **Adaptive Penalties** | | |
| Warning base penalty | 0.80 | `alpha.drift.weight_penalty_warning_min` — 20% reduction at ks=0.25 |
| Critical base penalty | 0.60 | `alpha.drift.weight_penalty_critical_min` — 40% reduction at ks=0.25 |
| Adaptive scaling enabled | true | `alpha.drift.weight_penalty_adaptive` — Scale by effect size |
| **Common** | | |
| Check interval | 4 hours | `alpha.drift.ks_check_interval_hours` |

---

## Execution Order

**Phase 149A (Distribution Drift — Renaissance-Grade):**
1. Apply migration 026 with enhanced schema (recovery + chi-squared columns)
2. Add all APR keys (KS windows, chi-squared thresholds, recovery params, adaptive penalties)
3. Deploy drift_monitor_service with KS + chi-squared monitors
4. Implement adaptive penalty formula (scale by effect size)
5. Implement recovery state machine (2 consecutive clean tests)
6. Wire ensemble_trainer to query drift_monitor with adaptive penalties

All phases are independent of core v3.0 AlphaEngine work (Phases 137-144). Can run in parallel once Phase 142A (ensemble IC measurement) ships.

---

**Renaissance-grade foundation:** All parameters APR-backed, complete feature coverage (54/54), recovery state machine, adaptive penalties. No technical debt.
