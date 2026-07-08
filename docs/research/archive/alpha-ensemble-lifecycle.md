# Alpha Ensemble Lifecycle

**Archived 2026-07-02.** Source of the cascade-scenario reasoning and the concrete
retrain-process spec that `docs/plans/archive/2026-06-27-health-guardian-design.md` dropped
without restatement; both restored into `docs/research/intel-14-integrity-monitor.md`. Kept here
for the full four-scenario cascade walkthrough and the E2A/E2B/E2C detail not reproduced there.

**Status:** Idea — not planned
**Context:** v3.0 AlphaEngine, post-Phase 142A (alpha_ensemble_ic table exists — Phase 142A
completed 2026-07-02, so this doc's stated prerequisite is now satisfied; still not planned,
just no longer blocked)
**Relates to:** `docs/research/archive/feature-vector-lifecycle.md`, `docs/plans/archive/2026-06-26-drift-detection-architecture.md`
(broken cross-reference fixed 2026-07-02 — this previously pointed at a nonexistent
`2026-06-26-renaissance-drift-detection-v3.md`)
**Completes:** The alpha-side question that drift detection leaves unanswered

---

## The Problem

`feature-vector-lifecycle.md` answers the feature question: *When does a feature stop being worth including in the ensemble?*

This doc answers the ensemble question: *When does the ensemble itself stop being worth emitting?*

The AlphaEngine is not a fire-and-forget system. It's an adaptive machine that must continuously prove it still carries edge. Three independent failure modes exist:

1. **Ensemble IC degradation** — The ensemble's IC decays even if individual features are healthy
2. **Conviction quality collapse** — Conviction scores become unreliable or unstable
3. **Systemic regime rupture** — The market enters a state the ensemble was never trained for

Renaissance principle: **"An adaptive system that cannot detect its own failure will eventually trade itself into ruin."**

---

## Core Principle: Three Independent Stop Tests

The AlphaEngine should emit alpha_events only when ALL THREE tests pass:

| Test | Question | Fail Consequence |
|------|----------|------------------|
| **E1: Ensemble IC Gate** | Does the ensemble currently predict returns? | Halt emission, retrain ensemble |
| **E2: Conviction Reliability** | Are conviction scores stable and well-calibrated? | Reduce position size, halt if critical |
| **E3: Feature Coverage** | Do we have enough active features to form a valid ensemble? | Halt emission, wait for feature recovery |

**Why three independent gates:**

A system that checks only one dimension is blind to the others. An ensemble can have:
- Healthy ensemble IC but conviction scores are erratic (E2 fails)
- Stable convictions but all features decayed (E3 fails)
- Good feature coverage but ensemble IC dropped (E1 fails)

All three must pass. Any fail halts emission until resolved.

---

## Test E1: Ensemble IC Gate

### What It Measures

**Question:** *Does the ensemble's weighted output currently predict forward returns?*

This is NOT the same as individual feature IC. A feature can have healthy IC while the ensemble's IC decays. Conversely, the ensemble can have healthy IC even if some features decay (ensemble re-weights around them).

**Measurement:** `alpha_ensemble_ic` table (Phase 142A)

```
SELECT lookahead, ic_mean, ic_sharpe, fdr_passed, walk_forward_stable
FROM alpha_ensemble_ic
WHERE symbol = $1 AND tf = $2 AND regime = $3
  AND scored_at > NOW() - INTERVAL '7 days'
ORDER BY scored_at DESC;
```

### Gate Criteria

**Emission allowed when:**
```
ic_sharpe >= alpha.ensemble.ic_sharpe_floor  (default 1.0)
AND walk_forward_stable = true
AND fdr_passed = true
AND scored_at > NOW() - INTERVAL '7 days'  (fresh measurement)
```

**What triggers the gate:**
- **IC Sharpe floor:** If ensemble IC drops below threshold, emission halts
- **Walk-forward failure:** If walk-forward stability breaks, ensemble needs retraining
- **Stale measurement:** If no IC measurement in 7 days, system is blind (halt)

### Failure Response

| Severity | Ensemble IC Sharpe | Action |
|----------|---------------------|--------|
| `critical` | < 0.5 | Halt emission immediately, force retrain |
| `warning` | 0.5 - 1.0 | Reduce conviction multiplier to 0.5, plan retrain |
| `healthy` | ≥ 1.0 | Normal emission |

### Retraining Triggers

Ensemble retraining triggered by:
1. **Scheduled:** Every 30 days (tunable via `alpha.ensemble.retrain_interval_days`)
2. **IC-driven:** Ensemble IC Sharpe drops below floor
3. **Coverage-driven:** Active feature count drops below threshold (see E3)

Retraining means:
- Re-fetch latest feature_ic_scores
- Re-compute ensemble weights (IC-weighted linear combination)
- Re-test walk-forward stability
- Re-test FDR correction
- Update `alpha_ensemble_ic` with new baseline

**Emergency retrain:** If ensemble IC drops below 0.3 (severe degradation), halt emission and force retrain within 24h.

---

## Test E2: Conviction Reliability

### What It Measures

**Question:** *Are the conviction scores the AlphaEngine outputs stable and well-calibrated?*

Conviction scores are the AlphaEngine's primary output — they drive position sizing. If convictions are unstable or poorly calibrated, the system trades erratically regardless of ensemble IC.

**Measurement:** Three sub-tests

#### E2A: Conviction Stability

**Question:** *Are conviction scores stable over time, or oscillating wildly?*

```sql
-- Compute conviction std over last 100 alpha_events
SELECT STDDEV(conviction) AS conviction_std
FROM alpha_events
WHERE symbol = $1 AND tf = $2 
  AND emitted_at > NOW() - INTERVAL '7 days'
  AND conviction IS NOT NULL;
```

**Gate:** `conviction_std < alpha.ensemble.max_conviction_std` (default 0.15)

**Rationale:** A healthy ensemble produces consistent convictions. If std spikes, ensemble weights are unstable (features flipping in/out of contribution).

#### E2B: Conviction Calibration

**Question:** *Do high-conviction alpha_events actually win more often?*

```sql
-- Bucket alpha_events by conviction decile, compute win rate per bucket
SELECT 
    NTILE(10) OVER (ORDER BY conviction) AS conviction_decile,
    AVG(outcome_r > 0) AS win_rate
FROM alpha_events
WHERE symbol = $1 AND tf = $2
  AND emitted_at > NOW() - INTERVAL '30 days'
  AND outcome_r IS NOT NULL
GROUP BY conviction_decile
ORDER BY conviction_decile;
```

**Gate:** Monotonically increasing win rate across deciles

**Rationale:** If conviction is well-calibrated, high-conviction events should win more often. If not, the conviction scoring function is broken.

#### E2C: Conviction Distribution Health

**Question:** *Are convictions distributed reasonably, or collapsed into extremes?*

```sql
SELECT 
    COUNT(*) FILTER (WHERE conviction < 0.2) AS low_conviction_pct,
    COUNT(*) FILTER (WHERE conviction > 0.8) AS high_conviction_pct,
    AVG(conviction) AS mean_conviction
FROM alpha_events
WHERE symbol = $1 AND tf = $2
  AND emitted_at > NOW() - INTERVAL '7 days';
```

**Gate:** 
- `low_conviction_pct < 0.6` (not all convictions collapsed to low)
- `high_conviction_pct > 0.1` (some convictions high enough to trade)
- `mean_conviction BETWEEN 0.3 AND 0.7` (reasonable center)

**Rationale:** Healthy ensemble produces spread of convictions. All low = no confidence to trade. All high = overconfident.

### Failure Response

| Failed Test | Action |
|-------------|--------|
| E2A (stability) | Reduce position sizing by 50%, diagnose weight instability |
| E2B (calibration) | Halt emission, fix conviction scoring function |
| E2C (distribution) | Reduce position sizing, check feature coverage |

---

## Test E3: Feature Coverage

### What It Measures

**Question:** *Do we have enough active features to form a valid ensemble?*

An ensemble needs diversity. If too many features decay (feature-vector-lifecycle states), the ensemble loses robustness.

**Measurement:** Count active features per (symbol, tf, regime)

```sql
SELECT COUNT(*) FILTER (WHERE is_decaying = false) AS active_count
FROM feature_ic_scores
WHERE symbol = $1 AND tf = $2 AND regime = $3
  AND lookahead_bars = $4
  AND passes_walkforward = true
  AND reliable = true;
```

### Gate Criteria

**Emission allowed when:**
```
active_count >= alpha.ensemble.min_feature_coverage  (default 5 features)
```

**Rationale:** Fewer than 5 features = ensemble is too fragile. One feature's idiosyncratic error dominates the output.

**Per-lookahead check:** Gate applies separately per lookahead (fast, mid, slow, extended). If `fast` has 3 active features but `slow` has 8, emit slow-lookahead alpha_events only.

### Failure Response

| Severity | Active Feature Count | Action |
|----------|----------------------|--------|
| `critical` | < 3 | Halt emission, wait for feature recovery or new features |
| `warning` | 3 - 5 | Reduce position sizing by (count / min_coverage), e.g., 4/5 = 80% size |
| `healthy` | ≥ 5 | Normal emission |

---

## Cascade Scenarios: How Feature Decay Affects Ensemble

The three layers interact. Understanding cascade is critical for correct response.

### Scenario 1: Single Feature Decay

```
Feature: momentum_z_fast decays (is_decaying=true)

Effect on ensemble:
├─ Feature excluded from ensemble training
├─ Ensemble re-weights across remaining features
├─ Ensemble IC may dip slightly (one alpha source lost)
└─ If ensemble IC stays above floor → emission continues
```

**Response:** No ensemble intervention needed. IC decay handles feature lifecycle. Ensemble adapts automatically.

---

### Scenario 2: Multi-Feature Decay (Cascade)

```
Features: 8 features decay in same regime (trending)

Effect on ensemble:
├─ 8 features excluded from training
├─ Active feature count drops from 24 → 16
├─ Ensemble re-weights on 16 features
├─ Ensemble IC Sharpe drops from 2.1 → 1.6
└─ Still above floor → emission continues
```

**Response:** Monitor but continue. 16 features still sufficient. E3 passes (16 ≥ 5). E1 passes (IC 1.6 ≥ 1.0).

---

### Scenario 3: Systemic Feature Collapse

```
Features: 20 features decay across all regimes

Effect on ensemble:
├─ 20 features excluded
├─ Active count: 24 → 4
├─ Ensemble IC drops: 2.1 → 0.4
├─ E1 FAILS (IC < 1.0)
├─ E3 FAILS (count < 5)
└─ HALT EMISSION
```

**Response:** 
1. Halt emission immediately
2. Diagnose: Why did 20 features decay simultaneously?
   - Data provider issue? (check distribution drift)
   - Regime transition? (check hmm_regime posteriors)
   - Market shock? (check volatility regime)
3. Force retrain ensemble after diagnosis
4. Do not resume until E1 and E3 pass

---

### Scenario 4: Ensemble IC Decay Without Feature Decay

```
Features: All 24 features stable (is_decaying=false)

Ensemble metrics:
├─ Individual feature ICs: all healthy
├─ Ensemble IC: drops from 2.1 → 0.7
└─ PROBLEM: Features work but ensemble doesn't

Diagnosis:
├─ Correlation structure shifted?
├─ Weighting scheme broken?
├─ Regime boundaries wrong?
└─ Ensemble retraining needed
```

**Response:**
1. E1 FAILS (ensemble IC < 1.0)
2. Halt emission
3. Force ensemble retrain (not feature retrain)
4. Investigate ensemble methodology, not feature quality

**Key insight:** Feature health ≠ Ensemble health. Both need independent monitoring.

---

## Ensemble Lifecycle States

An ensemble (per symbol, tf, regime, lookahead) has exactly one state at any time:

| State | Meaning | Emission | Active Features | Ensemble IC |
|-------|---------|----------|-----------------|--------------|
| `candidate` | Insufficient history or not yet validated | No | Any | Any |
| `active` | All three gates pass | Yes | ≥ 5 | ≥ 1.0 |
| `degraded` | One or more gates failing (but recoverable) | Reduced / halted | Varies | Varies |
| `failed` | Ensemble IC collapsed or feature count critical | No | < 3 or IC < 0.5 | < 0.5 |

### Transitions

```
candidate ──[all gates pass]──► active
active ──[any gate fails]──► degraded
degraded ──[gates recover]──► active
degraded ──[severe degradation]──► failed
failed ──[retrain succeeds]──► candidate
```

**No automatic `failed` → `active` transition.** After ensemble retrain, state goes to `candidate` first — gates must pass again before returning to `active`.

---

## Operational Governance

### Scheduled Retraining

**Default interval:** 30 days (`alpha.ensemble.retrain_interval_days`)

**What retraining does:**
1. Fetch latest `feature_ic_scores` for all (symbol, tf, regime, lookahead)
2. Filter to `is_decaying = false` features only
3. Re-compute ensemble weights via IC-weighted linear combination
4. Run walk-forward validation
5. Run FDR correction
6. Write new row to `alpha_ensemble_ic`
7. Update ensemble state if gates pass

**What retraining does NOT do:**
- Change feature definitions (FeatureFactory's job)
- Modify feature lifecycle (feature-vector-lifecycle's job)
- Halt emission (unless gates fail)

### Emergency Retraining

**Triggers:**
- Ensemble IC drops below 0.3 (severe degradation)
- All three gates fail simultaneously
- Manual operator trigger

**Timeline:** Within 24h of trigger

**Process:** Same as scheduled retrain, plus diagnostic logging: why did ensemble degrade?

### Manual Intervention

**Operator can:**
- Force halt emission (set ensemble state = `failed`)
- Force retrain (set retrain_requested flag)
- Adjust ensemble parameters via APR

**Operator cannot:**
- Manually set ensemble state to `active` (must earn it through gates)
- Override gate criteria (hard safety checks)

---

## Relationship to Drift Detection Layers

The three drift detection layers feed into the three ensemble gates:

```
Layer 1: Distribution Drift (KS test)
├─ Monitors: feature input data quality
├─ Writes: drift_monitor table (KS alerts)
├─ Feeds into: ensemble weight penalty (NOT a gate)
└─ Impact: Reduced conviction, but emission continues if gates pass

Layer 2: IC Decay (feature lifecycle)
├─ Monitors: feature predictive edge
├─ Writes: feature_ic_scores.is_decaying flag
├─ Feeds into: E3 (Feature Coverage gate)
└─ Impact: If too many features decay → halt emission

Layer 3: Ensemble IC CUSUM
├─ Monitors: ensemble IC degradation over time
├─ Writes: drift_monitor table (CUSUM alerts)
├─ Feeds into: E1 (Ensemble IC gate)
└─ Impact: If ensemble IC collapses → halt emission
```

**Key insight:** Distribution drift (Layer 1) is the only layer that does NOT directly trigger a gate. It applies a penalty but doesn't halt. This design is intentional:

- Distribution drift = "data is suspicious, don't trust it fully" → Reduce weight
- IC decay = "feature stopped working" → Exclude from ensemble
- Ensemble IC CUSUM = "ensemble itself is broken" → Halt emission

---

## What This Does NOT Do

**No per-alpha-event lifecycle states.**

Alpha_events do NOT have `candidate` → `active` → `decaying` states. Only the ensemble has states. Alpha_events are outputs, not monitored entities.

**Rationale:** Alpha_events are ephemeral. They fire, they resolve, they're done. The ensemble persists. Monitoring applies to the ensemble, not individual events.

**No conviction histogram gates.**

We don't require convictions to follow a specific distribution shape. We only require:
- They're stable (E2A)
- They're calibrated (E2B)
- They're not collapsed (E2C)

**No per-lookahead minimum feature coverage.**

E3 checks total active features per (symbol, tf, regime). It does NOT require each lookahead (fast, mid, slow, extended) to have minimum coverage. If `fast` has 3 active features and `slow` has 8, emit slow-lookahead events only.

---

## Success Criteria

A complete ensemble lifecycle system should:

1. ✅ Halt emission when ensemble IC drops below 1.0
2. ✅ Halt emission when active feature count drops below 5
3. ✅ Halt emission when convictions are unstable (std > 0.15)
4. ✅ Reduce position sizing when convictions poorly calibrated
5. ✅ Force retrain within 24h when ensemble IC drops below 0.3
6. ✅ Survive feature decay without intervention (cascade scenarios)
7. ✅ Detect ensemble IC decay even when individual features are healthy
8. ✅ Publish ensemble state to Prometheus for observability
9. ✅ Log all state transitions with diagnostic context
10. ✅ Allow manual operator intervention via APR keys

---

## What Jim Simons Would Demand

> "You built an adaptive machine. Now give it the ability to detect when it stops working. An ensemble that cannot recognize its own failure will eventually trade itself into ruin."
>
> "Three independent gates. If any fails, stop. Don't argue about which is more important. If ensemble IC collapses, it doesn't matter that convictions are stable. If features vanish, it doesn't matter that IC is healthy. All three must pass."
>
> "Feature decay is inevitable. The ensemble must adapt around it automatically. If you need manual intervention every time a feature dies, you don't have an adaptive system — you have a fragile one."
>
> "Retraining is not failure. It's maintenance. A system that never needs retraining is a system that isn't learning. Schedule it, automate it, and move on."

---

## Open Questions

1. **Conviction scoring function:** How do we actually compute conviction from ensemble weights? (This is an AlphaEngine implementation question, not a governance question)

2. **Position sizing formula:** How does conviction translate to actual trade size? (Implementation question)

3. **Regime-specific ensembles:** Should we maintain separate ensembles per HMM regime, or one ensemble with regime-conditioned weights? (Architecture question — affects gate granularity)

4. **Ensemble diagnostics:** When ensemble IC degrades without feature decay, what diagnostic queries should run? (Tooling question)

5. **Retraining costs:** How long does ensemble retraining take, and can we afford 24h emergency retrain timelines? (Operational question)

---

**This doc establishes the governance philosophy for when AlphaEngine should emit. Implementation details (conviction formulas, weight computation, position sizing) belong in the AlphaEngine architecture and IC spec docs.**
