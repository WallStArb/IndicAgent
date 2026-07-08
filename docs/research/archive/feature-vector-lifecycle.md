# Feature Vector Lifecycle

**Archived 2026-07-02.** Its cooldown-based recovery policy is superseded by
`docs/research/intel-14-integrity-monitor.md`'s evidence-based approach; its promotion/demotion gap
finding was correct, its recovery-timing answer wasn't the one that shipped. Kept here for the
original state-transition diagram and IC engine change notes not reproduced in intel-14.

**Status:** Idea — not planned
**Context:** v3.0 AlphaEngine. Applies to all features in `feature_vectors` — atomic primitives (Feature Factory) and compound primitives (Interaction Factory).
**Relates to:** `docs/research/renaissance-primitives-ohlcv.md`, `docs/research/interaction-factory.md`
**Completes:** `docs/research/archive/analog-engine-ic-factory.md` §deferred — that doc explicitly deferred the "hard IC on/off governance consumer" as out of scope for the measurement factory. This doc is that consumer.
**Eventually generalizes into:** `docs/research/concept-governance-registries.md`'s Concept Registry — `is_decaying`/`decay_detected_at`/`recovery_eligible_at` map onto `concept_eval_state.decay_ratio` + `concept_gate.decay_floor` for every domain, not just features. That system is deferred and unscheduled; this doc is the live, buildable version of the same mechanism for the one domain (`feature`) that exists today. Build this now regardless of Concept Registry's timeline — nothing here is wasted if that migration ever happens.

---

## The Gap

The IC gate (`passes_walkforward = true AND reliable = true`) handles promotion: a feature enters the ensemble when it proves statistical significance on historical corpus. That works.

What doesn't exist: demotion. `feature_ic_scores` has `is_decaying`, `decay_detected_at`, and `recovery_eligible_at` columns, but nothing sets them and nothing reads them. Once a feature enters the ensemble it stays there permanently, even if subsequent IC runs show its edge has disappeared. The system is additive-only.

The v2 signal shadow system had both sides: `shadow_auditor.py` enforced demotion when EV[R] degraded over N consecutive evaluations. v3 needs the equivalent for features.

---

## Lifecycle States

A feature has exactly one lifecycle state at any point in time.

| State | Meaning | Ensemble contribution |
|---|---|---|
| `candidate` | IC engine has never run on this feature, or last run returned `reliable = false` | None |
| `active` | Passes all IC gates (`passes_walkforward`, `reliable`, `passes_ci_gate`) | Full weight per IC Sharpe |
| `decaying` | Was active; subsequent IC run shows degraded edge | Excluded from ensemble |
| `deprecated` | Manually removed or feature definition changed | Excluded permanently |

Transitions:

```
candidate ──[IC gate pass]──► active ──[IC run: edge gone]──► decaying
                                  ▲                               │
                                  └───[cooldown elapsed + IC re-pass]──┘

active ──[manual]──► deprecated
decaying ──[manual]──► deprecated
```

No feature moves from `deprecated` back to `active`. A redefined feature is a new feature.

---

## What Drives Each Transition

### candidate → active

Current gate (already implemented):
- `passes_walkforward = true`
- `reliable = true` (n_independent ≥ `alpha.ic.min_reliable_n`, default 100)
- `passes_ci_gate = true`
- `ic_sharpe IS NOT NULL`

No change needed here. The IC engine already computes this correctly.

### active → decaying

Triggered by ic_engine on a fresh corpus run when a previously-active feature now fails:
- `passes_walkforward` flips to `false`, OR
- `ic_sharpe` drops below `alpha.ic.decay_ic_sharpe_threshold` (APR key, suggested default: 0.0), OR
- `reliable` drops to `false` (corpus shrank, symbol delisted)

On detection: set `is_decaying = true`, `decay_detected_at = now()`, compute `recovery_eligible_at = now() + alpha.ic.decay_cooldown_days`.

ic_engine must compare against the prior row for the same (feature_name, symbol, tf, regime, lookahead_bars) to detect the flip. It already writes one row per `training_window_end`; the prior-row comparison is a LAG window function or a pre-query.

### decaying → active (recovery)

Only eligible after `recovery_eligible_at` has elapsed. Then: if the next IC run produces a passing row, set `is_decaying = false` and clear the decay timestamps. The cooldown prevents thrashing — a feature that marginally passes/fails the gate doesn't oscillate in and out of the ensemble on every IC run.

APR key: `alpha.ic.decay_cooldown_days` — initial estimate 30 days (one IC cycle).

### anything → deprecated

Manual operator action only. An INSERT to a `feature_deprecations` log table (feature_name, reason, deprecated_at, deprecated_by). The ensemble_trainer cross-checks this table and excludes any feature with a deprecation row regardless of IC state.

Triggers: feature definition changed (column renamed or formula modified), data quality issue discovered, feature found to be a linear combination of another (collinear redundancy audit).

---

## Ensemble Trainer Changes

`ensemble_trainer.py` currently queries:

```sql
SELECT ... FROM feature_ic_scores
WHERE is_pooled = false AND passes_walkforward = true
  AND reliable = true AND ic_sharpe IS NOT NULL
```

After this is implemented, the query adds:

```sql
  AND (is_decaying = false OR is_decaying IS NULL)
  AND feature_name NOT IN (SELECT feature_name FROM feature_deprecations)
```

The `IS NULL` guard handles rows written before this system was introduced — the schema default for `is_decaying` is `false`, so legacy rows are unaffected.

---

## IC Engine Changes

The ic_engine must detect decay on each run. The minimal addition:

```python
# After writing the new feature_ic_scores row, check if this feature was active
# and now fails the gate — if so, set is_decaying = true.
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
        WHERE feature_name=$2 AND symbol=$3 ...
        """,
        now(), feature_name, symbol, ...
    )
    # publish topic event (see Observability below)
```

The exact implementation needs to handle the `is_pooled=false` row that was just written. Likely cleaner as a post-write UPDATE pass rather than inline.

---

## Observability

### Metrics

Two new point gauges on `src/observability/metrics.py`:

- `feature_active_count` — labeled `(tf, regime)` — how many features currently contributing to ensemble
- `feature_decaying_count` — labeled `(tf, regime)` — how many currently excluded due to decay

These let the Grafana board show whether the ensemble is contracting (features decaying faster than new features qualify).

### Topic Event

On any state transition (active→decaying, decaying→active), the IC engine publishes to a topic:

```python
topic_feature_lifecycle_transition()  # new key in stream_keys.py
```

Payload mirrors the v2 `ShadowTransitionEvent` schema:
```python
@dataclass
class FeatureLifecycleEvent:
    feature_name: str
    symbol: str
    tf: str
    regime: str
    prior_state: str      # 'active', 'candidate'
    new_state: str        # 'active', 'decaying', 'deprecated'
    trigger_reason: str   # 'ic_walkforward_failed', 'ic_sharpe_below_threshold', 'manual_deprecation'
    ic_sharpe: float | None
    occurred_at: datetime
```

No subscriber is required at implementation time — the topic exists for future diagnostics and audit trail.

---

## What This Does NOT Do

**No live shadow period for new features.** v2 shadow mode ran plugins on live signals before promotion. v3 has no equivalent — the IC gate is retrospective. A new feature added to the Feature Factory goes through backfill → IC run → gate check. If it passes, it enters the ensemble. There is no "run in shadow for 30 days on live alpha" step because all validation is batch-historical.

This is not a gap — it reflects the architectural difference between v2 (plugins fire on live signals) and v3 (ensemble trained on corpus, scores applied to new bars). The IC walkforward test approximates what a live shadow period would observe. If that approximation is insufficient, the remedy is longer walkforward windows and more folds, not a live shadow period.

**No feature-level weight dampening during decay detection window.** A simpler approach (reduce weight gradually rather than binary exclude) was considered. Rejected: the IC gate is already a statistical threshold. A feature either has demonstrated edge or it hasn't. Gradual weight reduction implies we're partially trusting edge we can no longer prove exists. The ensemble weight already scales by IC Sharpe magnitude — a weak-but-passing feature gets low weight automatically.

---

## Migration

`is_decaying`, `decay_detected_at`, `recovery_eligible_at` columns already exist in `feature_ic_scores`. No schema migration needed for the core columns.

New additions required:
1. `feature_deprecations` table (feature_name, reason, deprecated_at, deprecated_by)
2. `topic_feature_lifecycle_transition` key in `stream_keys.py`
3. `feature_active_count` and `feature_decaying_count` metrics in `metrics.py`
4. APR key: `alpha.ic.decay_ic_sharpe_threshold` and `alpha.ic.decay_cooldown_days`

All are additive changes. The system runs correctly without them — they only add the demotion enforcement and observability that are currently missing.
