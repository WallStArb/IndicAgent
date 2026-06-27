# Feature IC Decay Detection — Lifecycle States

**Date:** 2026-06-26
**Status:** PROPOSED — not planned, awaiting prioritization
**Milestone:** v3.0 Phase 149B (Data Integrity)
**Concept spec:** `docs/ideas/feature-vector-lifecycle.md` (June 25, 2026)
**Service design:** `docs/ideas/data-integrity-monitor-design.md` (Renaissance-grade reusable platform)

---

## Design Principle

IC decay catches **edge erosion**. A feature's predictive relationship with forward returns degrades even if input distributions are stable. Distribution drift won't catch this — formulas compute correctly but the alpha is gone.

**Renaissance analysis:** "IC decay is orthogonal to distribution drift. A feature can compute correctly on corrupted data (high KS drift) and still have IC. A feature can have stable distributions but lose its edge (IC decay). You need both layers."

**Renaissance-grade requirement:** Recovery requires confirmation. Don't restore a feature on a single fluke IC run — require 2 consecutive passing IC runs to avoid flapping.

---

## What Changed in v3.0 (vs v2.x)

| Component | v2.x | v3.0 | Impact on IC Decay |
|-----------|------|------|-------------------|
| **Feature table** | `intelligence_features` | `feature_vectors` | IC engine reads different JSONB structure |
| **Signal emission** | I7 plugins fire → signal_events | Ensemble conviction → alpha_events | Different granularity for feedback loops |

**Key insight:** v2.x conflated IC decay with CUSUM performance drift. v3.0 separates them: IC decay is feature lifecycle, CUSUM is ensemble monitoring.

---

## Concept Already Spec'd

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
- **Recovery confirmation:** Require 2 consecutive passing IC runs to clear `is_decaying`
- If IC run 1 passes: set `recovery_attempted_at`, wait for next run
- If IC run 2 also passes: set `is_decaying = false`, clear timestamps
- If IC run 2 fails: reset `recovery_attempted_at`, start cooldown over

**Why confirmation:** Prevent flapping on noisy IC measurements. A single passing run could be statistical noise. Two consecutive runs confirm genuine recovery.

**Columns (already exist in schema, add recovery_attempted_at):**
- `is_decaying` (boolean)
- `decay_detected_at` (timestamptz)
- `recovery_eligible_at` (timestamptz)
- `recovery_attempted_at` (timestamptz, nullable) — NEW: Track first recovery attempt

---

## Implementation: IC Engine Changes

**Trigger detection on each corpus run:**

```python
# In ic_engine.py, after writing new feature_ic_scores row
# Compare against prior row to detect state flip

prior = await conn.fetchrow(
    """
    SELECT passes_walkforward, is_decaying, recovery_attempted_at
    FROM feature_ic_scores
    WHERE feature_name=$1 AND symbol=$2 AND tf=$3 AND regime=$4
      AND lookahead_bars=$5 AND is_pooled=false
    ORDER BY training_window_end DESC LIMIT 1
    """,
    feature_name, symbol, tf, regime, lookahead_bars
)

# Detection: active → decaying
currently_active = prior and prior["passes_walkforward"] and not prior["is_decaying"]
now_failing = not passes_walkforward  # current run result

if currently_active and now_failing:
    await conn.execute(
        """
        UPDATE feature_ic_scores
        SET is_decaying=true, decay_detected_at=$1,
            recovery_eligible_at=$1 + (alpha_ic_decay_cooldown_days * INTERVAL '1 day'),
            recovery_attempted_at=NULL
        WHERE feature_name=$2 AND symbol=$3 AND tf=$4 AND regime=$5
          AND lookahead_bars=$6 AND is_pooled=false
          AND training_window_end=$7
        """,
        now(), feature_name, symbol, tf, regime, lookahead_bars, training_window_end
    )

# Recovery: decaying → active (requires 2 consecutive passing runs)
currently_decaying = prior and prior["is_decaying"]
now_passing = passes_walkforward and reliable and ic_sharpe >= decay_threshold

if currently_decaying and now_passing:
    if prior["recovery_attempted_at"] is None:
        # First passing run — mark attempt, wait for confirmation
        await conn.execute(
            """
            UPDATE feature_ic_scores
            SET recovery_attempted_at=$1
            WHERE feature_name=$2 AND symbol=$3 AND tf=$4 AND regime=$5
              AND lookahead_bars=$6 AND is_pooled=false
              AND training_window_end=$7
            """,
            now(), feature_name, symbol, tf, regime, lookahead_bars, training_window_end
        )
    else:
        # Second consecutive passing run — confirm recovery
        await conn.execute(
            """
            UPDATE feature_ic_scores
            SET is_decaying=false, decay_detected_at=NULL,
                recovery_eligible_at=NULL, recovery_attempted_at=NULL
            WHERE feature_name=$2 AND symbol=$3 AND tf=$4 AND regime=$5
              AND lookahead_bars=$6 AND is_pooled=false
              AND training_window_end=$7
            """,
            feature_name, symbol, tf, regime, lookahead_bars, training_window_end
        )

# Recovery failed (second run didn't pass) — reset attempt, start cooldown over
elif currently_decaying and not now_passing and prior["recovery_attempted_at"] is not None:
    await conn.execute(
        """
        UPDATE feature_ic_scores
        SET recovery_attempted_at=NULL,
            recovery_eligible_at=NOW() + (alpha_ic_decay_cooldown_days * INTERVAL '1 day')
        WHERE feature_name=$1 AND symbol=$2 AND tf=$3 AND regime=$4
          AND lookahead_bars=$5 AND is_pooled=false
          AND training_window_end=$6
        """,
        feature_name, symbol, tf, regime, lookahead_bars, training_window_end
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

## Ensemble Integration: IC Decay → Feature Exclusion

**ensemble_trainer query change:**

```sql
-- Current query (Phase 142A)
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

## DB Schema

**New table:** `feature_deprecations` (manual deprecation log)

```sql
CREATE TABLE IF NOT EXISTS feature_deprecations (
    feature_name   TEXT            PRIMARY KEY,
    reason         TEXT            NOT NULL,
    deprecated_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    deprecated_by  TEXT            NOT NULL DEFAULT 'system'
);
```

**Schema addition to feature_ic_scores (Renaissance-grade recovery confirmation):**

```sql
-- Add column for recovery attempt tracking
ALTER TABLE feature_ic_scores
ADD COLUMN recovery_attempted_at TIMESTAMPTZ;
```

**APR keys (all parameters tunable):**

| Key | Default | Purpose |
|-----|---------|---------|
| `alpha.ic.decay_ic_sharpe_threshold` | 0.0 | IC Sharpe floor for decay detection |
| `alpha.ic.decay_cooldown_days` | 30 | Recovery cooldown after decay |
| `alpha.ic.recovery_confirmation_runs` | 2 | Consecutive passing IC runs required for recovery |

**Why confirmation in APR:** Default is 2, but operator can adjust to 1 (aggressive) or 3 (conservative) based on observed IC stability.

---

## Migration Strategy

### Phase 149B: IC Decay Detection (Renaissance-Grade)

**Goal:** Execute `feature-vector-lifecycle.md` spec with recovery confirmation

**Implementation order:**
1. `feature_deprecations` table (add to migration 026 or separate migration)
2. Add `recovery_attempted_at` column to `feature_ic_scores`
3. Add APR key: `alpha.ic.recovery_confirmation_runs = 2`
4. Update `ic_engine.py` to detect decay and set `is_decaying` flag with recovery confirmation logic
5. Update `ensemble_trainer` query to exclude `is_decaying` features
6. Add Prometheus metrics: `drift_feature_ic_decaying_count`, `drift_feature_active_count`, `drift_recovery_attempt_total`
7. Add topic event: `topic_feature_lifecycle_transition()`

**Renaissance-grade requirements:**
- ✅ All decay parameters APR-backed (Sharpe threshold, cooldown, confirmation runs)
- ✅ Recovery confirmation (2 consecutive passing IC runs)
- ✅ Recovery attempt tracking (recovery_attempted_at column)

**Dependencies:**
- Phase 139 (alpha_events table exists)
- Phase 140-141 (IC engine running, corpus backfilled)
- Phase 142A (ensemble_trainer exists, even if preliminary)

---

## Success Criteria

### Phase 149B (IC Decay — Renaissance-Grade)

1. ✅ IC engine sets `is_decaying=true` when feature fails walkforward
2. ✅ `recovery_eligible_at = decay_detected_at + 30 days`
3. ✅ `ensemble_trainer` excludes `is_decaying` features from training
4. ✅ Decayed feature requires 2 consecutive passing IC runs to recover
5. ✅ First passing run sets `recovery_attempted_at`
6. ✅ Second passing run clears `is_decaying` and all timestamps
7. ✅ Failed recovery resets `recovery_attempted_at` and restarts cooldown
8. ✅ Prometheus metrics: `drift_feature_ic_decaying_count` reflects active decays
9. ✅ Prometheus metrics: `drift_recovery_attempt_total` tracks recovery attempts
10. ✅ Topic event published on each state transition
11. ✅ All decay parameters are APR-backed (tunable without migrations)

---

## Parameter Summary (Starting Values — All APR-Backed, Tune Empirically)

| Parameter | Value | Notes |
|-----------|-------|-------|
| **IC Decay** | | |
| IC Sharpe decay floor | 0.0 | `alpha.ic.decay_ic_sharpe_threshold` |
| Decay cooldown | 30 days | `alpha.ic.decay_cooldown_days` |
| Recovery confirmation runs | 2 | `alpha.ic.recovery_confirmation_runs` — Consecutive passing IC runs required |

---

## Execution Order

**Phase 149B (IC Decay — Renaissance-Grade):**
1. Add `recovery_attempted_at` column to `feature_ic_scores`
2. Add APR key for recovery confirmation runs
3. Implement feature-vector-lifecycle.md spec with recovery confirmation logic
4. Add Prometheus metrics + topic events

All phases are independent of core v3.0 AlphaEngine work (Phases 137-144). Can run in parallel once Phase 142A (ensemble IC measurement) ships.

---

**Renaissance-grade foundation:** All parameters APR-backed, recovery confirmation prevents flapping, complete observability. No technical debt.
