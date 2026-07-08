# Signal-Ranker

**Version:** 2.0
**Status:** draft
**Last Updated:** 2026-06-12

---

## 1. Purpose

Defines the design for `SignalRanker`: a single LightGBM model that replaces the entire confidence
transform chain with one end-to-end trained ranking function.

The current transform chain applies sequential learned adjustments to produce a ranking score:

```
raw_confidence
  → calibrator        (isotonic regression per plugin+tf+symbol)
  → perf_multiplier   (Sharpe rank from setup_performance)
  → adjusted_rank     (used by aggregator)
```

Each stage was trained independently on the same target variable (`pnl_r`), ignoring the others.
This is statistically equivalent to fitting correlated factors in a model you pretend are orthogonal.
The compounding error is not bounded and interactions between factors are invisible.

`SignalRanker` replaces all three with one function:

```
ranking_score = SignalRanker(raw_confidence, setup_plugin, tf, symbol,
                              hmm_state, ctf_score, exhaustion_state,
                              zone_context, bar_context, ...)
```

Everything enters simultaneously. Interactions are learned, not assumed.

**Prerequisite:** All 29 non-exempt I7 plugins must follow the 6 GOOD patterns
(`docs/signals/signals-confidence-patterns.md`) so `raw_confidence` is a clean intrinsic
score. The 8 plugins in `_I7_I6_EXEMPT` (`src/intelligence/register_plugins.py`) must complete
Phase 122 before their signals contribute meaningful training data.

---

## 2. Design Principles

### One question, one model

At signal fire time you have everything: `raw_confidence`, HMM regime probabilities, I6 CTF scores,
exhaustion state, zone context, time of day, instrument, timeframe. You want one number: the
expected ranking value for this signal given all available information.

That is one function. One training loop. The perceived need for sequential stages arises from
building toward the model incrementally — not from the correct statistical formulation.

### Extrinsic features are equal inputs, not adjustments

The intrinsic/extrinsic distinction matters at the plugin level (to keep `raw_confidence` clean).
It does not carry over to the ranking model. `hmm_prob_trending_up` and `raw_confidence` are equal
features — the model learns the weight of each from outcome data. There is no "applying extrinsic
factors" step; there is one feature matrix fed to one model.

### The target is rank, not probability

The aggregator needs to rank signals correctly within a bar — not calibrated absolute probabilities.
Train on `rank(pnl_r)` within each bar's signal set, or on `pnl_r` directly with Huber loss for
fat-tail robustness. A ranking model trained on relative outcomes is more stable than a probability
model trained on absolute thresholds.

### `raw_confidence` is immutable

`raw_confidence` is never modified after I7 fires. It is the plugin's first-class intrinsic
assessment and a direct input feature to `SignalRanker`. `ranking_score` is a separate output
column. All plugin diagnostics, shadow governance, and ablation studies use `raw_confidence`.

### Walk-forward validation is non-negotiable

Rolling 90-day train, 30-day test. A model that improves in-sample but degrades out-of-sample is
overfitting to a passed regime. Evaluate on the holdout window only.

### Shadow mode before promotion

A new `SignalRanker` version enters shadow mode: runs in parallel, logs `ranking_score` on every
signal, but the live chain runs until holdout Sharpe exceeds current chain at `p < 0.05`,
`N >= 1000` signals.

### The SignalContextEnricher multiplier approach is retired

The prior design (per-feature-bucket multipliers, `context_multipliers` table, per-bucket
promotion gates) was a structured prior about which context features matter. `SignalRanker`
replaces this with empirical discovery via SHAP values. Building the multiplier layer as a
production component is unnecessary — persist the context features, train the model directly.

---

## 3. Architecture

```
I7 plugins → raw_confidence (intrinsic, immutable)
    │
    ▼
Feature assembly
    raw_confidence, setup_plugin (categorical), tf, symbol,
    hmm_prob_trending_up, hmm_prob_trending_down, hmm_prob_ranging,
    ctf_score, ctf_structure_alignment, ctf_trend_alignment,
    exhaustion_score, exhaustion_side, exhaustion_bars,
    supply_strength, demand_strength,
    fvg_type, ob_type, choch_detected, bos_detected,
    bar_hour_et, bar_day_of_week,
    ofi_ewma_20, rel_volume, atr_pct
    (full list = capture_signal_features() output + bar metadata)
    │
    ▼
SignalRanker  (in-process, post-I7, pre-aggregator selection)
    model:   LightGBM, trained nightly on pnl_r / rank(pnl_r)
    writes:  ranking_score
    │
    ▼
Aggregator  (CISScorer + regime gate + winner selection)
    ranks on: ranking_score
    writes:   was_selected, composite_rank, cis_score
    │
    ▼
signal_ledger
    stores:  raw_confidence, ranking_score
             (all signals written — was_selected=True on winner only)

Deprecated on SignalRanker promotion:
    calibrator        src/intelligence/pipeline/calibrator.py
    perf_multiplier   src/intelligence/pipeline/ranker.py
    calibration_curves table
    setup_performance perf_multiplier column
```

`SignalRanker` is in-process inside `IntelligencePipeline` — no new service, no new Kafka topic.
It slots between the regime gate and aggregator selection in `SignalProcessor.process`.

---

## 4. Model Specification

**Algorithm:** LightGBM gradient boosted trees.

Reasons: handles feature interactions without manual specification; non-parametric (does not assume
the `raw_confidence → outcome` relationship is linear or monotone); retrains nightly on 7-8M rows
in under a minute; SHAP values provide the audit trail of which features drive each prediction;
regularizes against overfitting via depth limits and subsampling.

**Global model with `setup_plugin` as categorical feature.** One model across all 29 setups.
Shares information across plugins (critical for low-frequency setups like `trad_MeanReversion`
with <100 signals) and learns plugin-specific behavior when data supports it. Per-plugin models
are a fallback only if global model interaction terms dominate.

**Training cadence:** Nightly by `ml-training` batch job on a rolling 90-day window. New model
written to `model_artifacts` with `is_shadow=True`. Promoted when holdout Sharpe beats current
model `p < 0.05`, `N >= 1000`.

**Feature importance:** SHAP values computed at training time, written to `model_feature_importance`
table. This is the empirical answer to which context features improve predictions — replaces all
prior intuition about which extrinsic factors to "apply."

---

## 5. Data Contracts

### `signal_ledger` additions (migration required)

`context_features jsonb` — full `capture_signal_features()` output persisted at signal fire time.
This is the training dataset. Without it, the model cannot be trained. Currently written to the
signal's `_shadow` dict only (`src/intelligence/trading/confidence_utils.py`); must be promoted
to a persisted column.

`ranking_score float8` — `SignalRanker` output, populated at pipeline time. Null until live.
Existing `calibrated_confidence` kept until deprecation is complete.

### `model_artifacts` table (new)

| Column | Type | Description |
|---|---|---|
| `model_id` | `uuid` | Primary key |
| `model_type` | `text` | `signal_ranker_v1` |
| `trained_at` | `timestamptz` | Nightly batch timestamp |
| `feature_list` | `text[]` | Ordered feature names |
| `artifact_path` | `text` | Serialized LightGBM model path |
| `holdout_sharpe` | `float8` | Out-of-sample Sharpe on 30-day holdout |
| `holdout_n` | `int4` | Signal count in holdout |
| `is_shadow` | `bool` | True until promoted |
| `is_active` | `bool` | True for live model |

### `model_feature_importance` table (new)

| Column | Type | Description |
|---|---|---|
| `model_id` | `uuid` | FK → `model_artifacts` |
| `feature_name` | `text` | Feature key |
| `shap_mean_abs` | `float8` | Mean absolute SHAP across holdout signals |
| `rank` | `int4` | Importance rank (1 = highest) |

---

## 6. Build Scope

**Phase 122 (prerequisite):** Strip 8 `_I7_I6_EXEMPT` plugins — clean `raw_confidence` for all
I7 plugins.

**Phase 123 — Feature Persistence:**
1. Migration: add `context_features jsonb` to `signal_ledger`.
2. Promote `capture_signal_features()` output from `_shadow` dict to persisted `context_features`
   column in `signal_processor.py`.
3. Add `context_features` to `_INSERT_SYNC_TEMPLATE` in `historical_backfill.py`.
4. Backfill: replay signals with context features populated (use `--use-precomputed-features`).

**Phase 124 — SignalRanker:**
5. Migration: create `model_artifacts` and `model_feature_importance` tables.
6. Implement `SignalRanker` in `src/intelligence/pipeline/signal_ranker.py`.
7. Wire into `SignalProcessor.process` between regime gate and aggregator.
8. Add `ranking_score` to `signal_ledger` insert template.
9. Add nightly `SignalRanker` training + SHAP pass to `ml-training` batch job.
10. Shadow governance: promote on holdout Sharpe `p < 0.05`, `N >= 1000`.

**Phase 125 — Deprecate chain:**

Code deleted:
11. Delete `src/intelligence/pipeline/calibrator.py`.
12. Delete `src/intelligence/pipeline/ranker.py`.
13. Delete `src/intelligence/pipeline/tod_adjuster.py` (already removed from pipeline in prior refactor; file still exists).
14. Remove `apply_calibration` call + import from `signal_processor.py`.
15. Remove `rank_signals` call + import from `signal_processor.py`; replace with `SignalRanker.score()`.
16. Remove `CacheSnapshot.calibration_curves` and `CacheSnapshot.perf_weights` fields.

`CacheManager` cleanup:
17. Remove `_load_calibration_curves()` and `_load_perf_weights()` methods.
18. Remove `calibration_curves` and `perf_weights` properties.
19. Remove `seed_calibration_curves()` and `seed_perf_weights()` seed methods.
20. Remove those refresh loops from `start_refresh_loops()`.

`IntelligencePipeline` cleanup:
21. Remove `calibration_curves` and `perf_weights` from checkpoint assembly in `get_checkpoint_extra()`.

`historical_backfill.py`:
22. Replace `calibrated_confidence` with `ranking_score` in `_INSERT_SYNC_TEMPLATE`.

DB migrations:
23. Drop `calibration_curves` table.
24. Drop `tod_multipliers` table (already empty).
25. Drop `calibrated_confidence` column from `signal_ledger` once `ranking_score` is fully backfilled.

Tests:
26. Remove `calibration_curves={}` and `perf_weights={}` from all `CacheSnapshot` constructors.
27. Remove all `mock.patch("...apply_calibration")` and `mock.patch("...rank_signals")` patches.
28. Remove calibration curve load/seed tests from `test_cache_manager.py`.

---

## 7. See Also

- `docs/signals/signals-confidence-patterns.md` — 6 GOOD patterns; `raw_confidence` must be clean before training
- `src/intelligence/trading/confidence_utils.py` — `capture_signal_features()`; context feature source
- `src/intelligence/pipeline/signal_processor.py` — pipeline orchestration; `SignalRanker` slots post-regime-gate
- `src/intelligence/pipeline/calibrator.py` — deprecated on `SignalRanker` promotion
- `src/intelligence/pipeline/ranker.py` — `perf_multiplier` deprecated on promotion
- `src/intelligence/register_plugins.py` — `_I7_I6_EXEMPT` (8 plugins); Phase 122 prerequisite
- `signal_ledger_full` view (migration 095) — training dataset source
