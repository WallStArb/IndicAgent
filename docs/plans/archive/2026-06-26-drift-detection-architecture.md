# Drift Detection Architecture — v3.0 Integration

**Archived 2026-07-02.** Its "Part 3: CUSUM Repurposing" section (ensemble-IC change-detection,
ported from a working v2.x mechanism) was silently dropped from the 2026-06-27 consolidation
with no documented reason; restored into `docs/ideas/intel-14-integrity-monitor.md` (build with
Phase 150, alert-only, self-arming at 20 measurements/key). Kept here for the full CUSUM
algorithm detail and the v2.x-to-v3.0 adaptation reasoning not reproduced in intel-14.

**Date:** 2026-06-26
**Status:** PROPOSED — not planned, awaiting prioritization
**Milestone:** v3.0 Phases 149A-150 (Data Integrity + Observability)
**v2.x reference:** `docs/plans/archive/2026-03-11-signal-drift-detection-design.md` (shipped March 2026)
**Service design:** `docs/ideas/data-integrity-monitor-design.md` (Renaissance-grade reusable platform)

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
│  Layer 3: Ensemble IC CUSUM (performance drift)               │
│  ┌──────────────┐    ┌──────────────┐                          │
│  │ alpha_       │───→│ CUSUM        │───→ ensemble weight      │
│  │ ensemble_ic  │    │ Monitor      │     adjustment/halt       │
│  └──────────────┘    │ (after 20    │                          │
│                      │  outcomes)   │                          │
│                      └──────────────┘                          │
│                                                               │
│  Ensemble Integration (all 3 layers feed here)                  │
│  ┌─────────────────────────────────────────────┐               │
│  │ ensemble_trainer reads all signals:         │               │
│  │ • drift_monitor penalty → weight reduction  │               │
│  │ • is_decaying=true → feature excluded       │               │
│  │ • CUSUM alert → ensemble weight/halt        │               │
│  └─────────────────────────────────────────────┘               │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

**Service deployment:**
- **Standalone service:** `indicagent-drift-monitor` (reuses v2.x architecture)
- **Port:** `:9118`
- **Check cycles:** KS every 4h, IC decay on corpus runs (event-driven), CUSUM on every ensemble IC outcome

---

## Part 1: How the Two Drift Layers Interact

**Scenario 1: Distribution drift detected (KS alert)**
```
┌─────────────────────────────────────────────────────────────┐
│ KS monitor detects rsi_fast distribution shifted             │
│ → Writes drift_monitor row: alert_severity='warning'          │
│ → ensemble_trainer applies 0.80 penalty to all ES 1m feats  │
│ → Ensemble reduces weight on ES 1m features                 │
│ → System continues trading, just with lower conviction     │
└─────────────────────────────────────────────────────────────┘
```

**Scenario 2: IC decay detected (lifecycle state change)**
```
┌─────────────────────────────────────────────────────────────┐
│ IC engine detects momentum_z_mid Sharpe dropped to 0.0     │
│ → Sets is_decaying=true for momentum_z_mid                │
│ → ensemble_trainer excludes momentum_z_mid from training  │
│ → Ensemble re-weights across remaining features          │
│ → System adapts automatically, no manual intervention       │
└─────────────────────────────────────────────────────────────┘
```

**Scenario 3: Both detected (cascade)**
```
┌─────────────────────────────────────────────────────────────┐
│ KS alert active (0.60 penalty on ES 1m)                     │
│ → momentum_z_mid decays (excluded from ensemble)            │
│ → Remaining ES 1m features get 0.60 penalty applied        │
│ → Ensemble conviction drops from two independent signals │
│ → Graceful degradation, not binary on/off                  │
└─────────────────────────────────────────────────────────────┘
```

**Key principle:** The three layers are **orthogonal**. Distribution drift says "this data is suspicious." IC decay says "this feature lost its edge." CUSUM says "the ensemble itself is degrading." All three can be true simultaneously. The ensemble respects all signals.

---

## Part 2: Service Deployment — indicagent-drift-monitor (v3.0)

**Reuse v2.x architecture, new data source:**

```python
# services/drift_monitor_service.py (v3.0 adaptation)
async def main():
    dist_monitor = DistributionDriftMonitor(db, settings)  # KS on feature_vectors
    cusum_monitor = CUSUMMonitor(db, settings)             # Ensemble IC monitoring
    # IC decay is event-driven (runs in ic_engine.py), not a separate timer

    await dist_monitor.run_forever(interval_seconds=4 * 3600)
    await cusum_monitor.run_forever(interval_seconds=1 * 3600)  # Check hourly
```

**Component changes from v2.x:**

| Component | v2.x | v3.0 |
|-----------|------|------|
| **KS data source** | `intelligence_features` (i1/i4 JSONB) | `feature_vectors` (54 top-level columns) |
| **Monitored features** | 8 continuous features | 47 continuous features (7 categorical deferred) |
| **Feedback integration** | CIS confidence penalty | Ensemble weight penalty |
| **Penalty values** | warning=0.85, critical=0.70 | warning=0.80, critical=0.60 |
| **IC decay** | Conflated with CUSUM | Separate lifecycle states |
| **CUSUM target** | Per-signal pnl_r from signal_ledger | Ensemble IC from alpha_ensemble_ic |

**What stays the same:**
- Service architecture (standalone daemon, Prometheus metrics, API endpoint)
- KS test parameters (p < 0.05, ks > 0.10, n ≥ 50)
- Alert severity thresholds (warning: ks 0.10-0.25, critical: ks ≥ 0.25)
- Direct DB queries to drift_monitor (no cache layer)
- CUSUM algorithm (same k=0.5, h=4.0, h_critical=8.0)

---

## Part 3: CUSUM Repurposing — Ensemble IC Monitoring

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

## Part 4: Observability

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
GET /api/drift
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

**Dependencies:**
- None (can run in parallel with Phase 142A ensemble IC work)

---

### Phase 149B: IC Decay Detection

**Goal:** Execute `feature-vector-lifecycle.md` spec

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
3. ✅ `ensemble_trainer` queries `drift_monitor` and applies penalty to feature weights

### Phase 149B (IC Decay)

1. ✅ IC engine sets `is_decaying=true` when feature fails walkforward
2. ✅ `ensemble_trainer` excludes `is_decaying` features from training
3. ✅ Topic event published on state transition

### Phase 150 (Ensemble IC CUSUM + Chi-Square)

1. ✅ CUSUM fires warning when ensemble IC drops >4σ from baseline
2. ✅ Chi-squared test runs on 7 categorical features
3. ✅ All three layers (KS distribution, IC decay, CUSUM ensemble) operational
4. ✅ Cascade scenario works: KS alert + IC decay → ensemble adapts correctly

---

## What Jim Simons Would Demand

> "Detection without action is surveillance. When distributions drift, the system must adapt automatically — no human intervention, no 3am panic calls."
>
> "IC decay is orthogonal to distribution drift. A feature can compute correctly on corrupted data (high KS drift) and still have IC. A feature can have stable distributions but lose its edge (IC decay). You need both layers."
>
> "False positives are acceptable. The cost of briefly under-weighting a healthy feature is bounded and recoverable. The cost of missing a genuine degradation signal is unbounded — you continue trading on decayed features at full weight. Accept the false positive risk."

---

## Parameter Summary (Starting Values — All APR-Backed, Tune Empirically)

| Parameter | Value | Notes |
|-----------|-------|-------|
| **KS Distribution Drift** | | |
| KS reference window | 29 days (NOW−37d to NOW−8d) | `alpha.drift.ks_reference_window_days` — Sliding; self-correcting |
| KS current window | 7 days (NOW−7d to NOW) | `alpha.drift.ks_current_window_days` |
| KS p-value threshold | 0.05 | `alpha.drift.ks_p_value_threshold` |
| KS effect size threshold | 0.10 | `alpha.drift.ks_effect_size_threshold` |
| KS min sample | 50 bars | `alpha.drift.ks_min_sample` |
| KS check interval | 4 hours | `alpha.drift.ks_check_interval_hours` |
| **Chi-Squared Categorical Drift** | | |
| Chi-squared p-value threshold | 0.05 | `alpha.drift.chi_sq_p_value_threshold` |
| Chi-squared effect size threshold | 0.10 | `alpha.drift.chi_sq_effect_size_threshold` (cramér_v) |
| Chi-squared min sample | 50 bars | `alpha.drift.chi_sq_min_sample` |
| **Recovery State Machine (KS + Chi-Squared)** | | |
| Recovery check interval | 4 hours | `alpha.drift.recovery_check_interval_hours` |
| Recovery clean tests required | 2 | `alpha.drift.recovery_clean_tests_required` |
| **Adaptive Penalties** | | |
| Warning base penalty | 0.80 | `alpha.drift.weight_penalty_warning_min` |
| Critical base penalty | 0.60 | `alpha.drift.weight_penalty_critical_min` |
| Adaptive scaling enabled | true | `alpha.drift.weight_penalty_adaptive` |
| **IC Decay** | | |
| IC Sharpe decay floor | 0.0 | `alpha.ic.decay_ic_sharpe_threshold` |
| Decay cooldown | 30 days | `alpha.ic.decay_cooldown_days` |
| Recovery confirmation runs | 2 | `alpha.ic.recovery_confirmation_runs` |
| **Ensemble IC CUSUM** | | |
| CUSUM k (allowance) | 0.5 σ | `alpha.drift.cusum_k` — Min detectable shift |
| CUSUM h (threshold) | 4.0 σ | `alpha.drift.cusum_h` — Warning trigger |
| CUSUM h_critical | 8.0 σ | `alpha.drift.cusum_h_critical` |
| CUSUM min IC measurements | 20 | `alpha.drift.cusum_min_outcomes` |

---

## What's Deferred

| Item | Why Deferred |
|------|--------------|
| Feature-level granularity for KS penalties | Coarser symbol/TF-level penalty is simpler, safer, easier to maintain |
| Per-TF CUSUM | Most setups lack 20 outcomes per TF yet; add after 3+ months of ensemble IC history |
| Automatic CUSUM reset | Requires human investigation before re-baselining; auto-reset masks recurring degradation |

**Note:** Chi-squared tests for categorical features are **NOT deferred** — shipped in Phase 149A with KS test. All 54 features monitored from day one (Renaissance-grade).

---

## Execution Order

**Phase 149A (Distribution Drift — Renaissance-Grade):**
1. Apply migration 026 with enhanced schema (recovery + chi-squared columns)
2. Add all APR keys (KS windows, chi-squared thresholds, recovery params, adaptive penalties)
3. Deploy drift_monitor_service with KS + chi-squared monitors
4. Implement adaptive penalty formula (scale by effect size)
5. Implement recovery state machine (2 consecutive clean tests)
6. Wire ensemble_trainer to query drift_monitor with adaptive penalties

**Phase 149B (IC Decay — Renaissance-Grade):**
1. Add `recovery_attempted_at` column to `feature_ic_scores`
2. Add APR key for recovery confirmation runs
3. Implement feature-vector-lifecycle.md spec with recovery confirmation logic
4. Add Prometheus metrics + topic events

**Phase 150 (Ensemble IC CUSUM):**
5. Repurpose CUSUM for ensemble IC (requires alpha_ensemble_ic table from Phase 142A)

All phases are independent of core v3.0 AlphaEngine work (Phases 137-144). Can run in parallel once Phase 142A (ensemble IC measurement) ships.

---

**This architecture restores v2.x drift detection capabilities to v3.0, adapts them to the feature_vectors architecture, and adds IC decay detection as a second orthogonal layer. Renaissance-grade: All 54 features monitored, all parameters APR-backed, recovery state machines for both KS and IC decay, adaptive penalties. The system trades on degraded features automatically — with bounded downside for false positives and unbounded protection against genuine degradation.**
