# Interaction Factory

**Status:** Idea - not planned
**Depends on:** Primitives expansion (renaissance-primitives-ohlcv.md), IC engine stable (Phase 138+)
**Governance:** `docs/ideas/feature-vector-lifecycle.md` — lifecycle states and demotion apply to promoted compound primitives
**Trigger:** IC engine producing stable results on current 54 features, primitives expansion landed (~100+ tier-0 atomics), corpus complete.

---

## What This Is

The Interaction Factory is a combinatorial expansion layer that generates all N*(N-1)/2 pairwise combinations of atomic primitives — products, ratios, and rolling correlations — and screens them through the IC engine. Survivors become promoted columns in `feature_vectors` alongside the atomic primitives that produced them.

This is distinct from the hand-picked "Interaction Primitives" in `renaissance-primitives-ohlcv.md`. Those are curated based on domain intuition (vol_body_product, price_vol_corr). The Interaction Factory generates everything and lets IC decide what survives. No intuition in, no bias introduced.

With ~100 atomic primitives (current 54 + primitives expansion):
- Pairs: 100 * 99 / 2 = 4,950
- Operations: 3 types (product, ratio, correlation)
- Windows: 2-3 per rolling correlation
- **Total candidates: ~20,000-30,000**

IC engine screens all of them. Survivors are promoted as compound primitives.

---

## Primitive Taxonomy

Interactions are **compound primitives** — they are still tier-0 in the feature vector lifecycle. The distinction between atomic and compound is purely about how they are computed, not where they live or how IC treats them. Both kinds land in `feature_vectors` after promotion.

| Kind | Examples | Who computes | Lifecycle |
|---|---|---|---|
| Atomic primitive | `body_ratio`, `atr_z`, `volume_z`, `momentum_z_fast` | Feature Factory | Directly computed from OHLCV |
| Compound primitive | `xf_prod__body_ratio__volume_z`, `xf_corr__ret_lag_fast__atr_z__fast` | Interaction Factory | Deterministic combination of two atomics |
| Theory-embedded | `poc_dist_atr`, `ctf_*`, `hmm_state` | I5/I7 (archived) | Encodes structural judgment; separate IC track |

The compound/atomic distinction matters for IC clustering analysis: a compound primitive that has IC after controlling for its parent atomics carries genuine incremental information. One that doesn't is collinear with its parents and gets dropped. This is an analysis-time concept, not a schema boundary.

---

## Three Interaction Operations

### 1. Product: f_i × f_j

Captures joint behavior. Most meaningful when both features carry sign — a large positive product means both features agree directionally.

**Valid when:** both features are reasonably bounded or have been z-scored. Unbounded × unbounded produces a heavy-tailed distribution that inflates IC variance. Pre-normalize unbounded inputs before computing products.

**Example:** `body_ratio * volume_z` — directional conviction × volume confirmation. Strong bar with high volume. Neither alone is sufficient.

### 2. Ratio: f_i / f_j

Relative magnitude. Encodes "feature i relative to feature j."

**Valid when:** denominator is always positive and bounded away from zero. Ratios with a denominator that can be near-zero produce extreme values that blow up IC estimates.

**Valid denominators:** `atr_z + offset`, `volume_z + offset`, any [0, ∞) feature with a floor.
**Invalid denominators:** `body_ratio` (crosses zero), `ret_lag_fast` (crosses zero), anything centered at 0.

Enforcing this requires feature metadata. The factory must know each feature's sign and range type.

### 3. Rolling Correlation: corr(f_i, f_j, N)

Time-varying joint behavior over a window N. Captures whether two features agree or disagree in a rolling period. When correlation goes from +1 to -1, a regime has shifted even if neither feature alone has changed.

**Valid when:** both features have meaningful variance in the window. Constant features produce undefined correlations.

**Window choices:** fast (APR-backed) and slow (APR-backed) — same gradient naming convention as other features.

**Compute cost:** O(N) per bar per pair. With 4,950 pairs and N=20, this is expensive. Profile before running at full corpus scale.

---

## Feature Metadata Requirements

The factory cannot run without knowing each tier-0 feature's properties:

| Property | Values | Used for |
|---|---|---|
| `sign_type` | `signed`, `positive`, `bounded_01`, `binary` | Ratio validity, product normalization |
| `scale` | `z_scored`, `natural_bounded`, `raw_ratio`, `raw_unbounded` | Whether to pre-normalize before product |
| `has_window` | bool | Whether feature has a time-window parameter |

This is exactly what `docs/ideas/feature-registry.md` (todo 008, implemented) is for. The Interaction Factory depends on the Feature Registry. Without it, the factory has to hardcode scale knowledge for each feature — a maintenance burden as the feature set grows.

**Implementation order:** Feature Registry first, Interaction Factory second.

---

## Naming Convention

Interaction features use the `xf_` prefix (cross-feature):

```
xf_{operation}_{feature_a}__{feature_b}
xf_{operation}_{feature_a}__{feature_b}_{window}
```

- `xf_prod_body_ratio__volume_z` — product, no additional window
- `xf_ratio_ret_lag_fast__atr_z` — ratio, windows inherited from parents
- `xf_corr_ret_lag_fast__volume_z__fast` — rolling correlation, fast window
- `xf_corr_ret_lag_fast__volume_z__slow` — rolling correlation, slow window

Double underscore between feature names avoids collision when feature names themselves contain underscores. The `xf_` prefix ensures no naming collision with tier-0 atomics.

APR keys for correlation windows: `feature.xf_corr.fast`, `feature.xf_corr.slow`.

---

## Compute and Storage Architecture

### First Principle: Atomics Are the Irreducible Information

A compound primitive `xf_prod__body_ratio__volume_z` is entirely determined by `body_ratio` and `volume_z` at the same bar. It contains zero additional information beyond its parent atomic columns. The principle "never drop data that could contain signal" applies to atomics — compounds are derived, not fundamental.

Therefore: **atomic primitives are stored; compound primitives are computed on-demand from their parents.** No schema migration per compound, no redundant state that can drift from its definition.

### The Consistency Constraint

On-demand computation has one real risk: if the formula is implemented differently in IC screening vs. IC monitoring vs. ensemble inference, training features ≠ inference features. Silent wrong answer — the worst outcome.

Solution: **one canonical `CompoundPrimitiveEvaluator`** called identically in every context. IC screening, IC monitoring, ensemble training, ensemble inference all import and call the same function. The formula is a tested unit, not an implementation detail scattered across modules.

```python
# called identically everywhere — no context-specific reimplementation
value = CompoundPrimitiveEvaluator.evaluate(
    series_a, series_b, operation="product", window=None
)
```

### Registry

**No standalone registry table.** Promoted survivors become `domain='feature_interaction'` rows in the unified `concept_registry` (`docs/ideas/metadata-governance-registries.md`) rather than a separate `compound_primitive_registry` — same shared schema as `feature`, `alpha_pattern`, etc., just a different `domain` value. `feature_a`/`feature_b`/`operation`/`xf_name` live in `concept_registry.metadata JSONB`; `ic_sharpe`/`promoted_at` are what `concept_gate_template` + `concept_transition_log` already track for every domain; `is_active` is `concept_registry.enabled`.

Raw pre-promotion screening (the ~30,000 candidate sweep) stays **outside** the unified registry entirely, in a lightweight `compound_ic_scores` table:

```sql
compound_ic_scores (
    feature_a   TEXT NOT NULL,      -- atomic column name in feature_vectors
    feature_b   TEXT NOT NULL,
    operation   TEXT NOT NULL,      -- 'product', 'ratio', 'corr_fast', 'corr_slow'
    xf_name     TEXT NOT NULL UNIQUE,
    ic_sharpe   NUMERIC,
    ic_n        INTEGER,
    eval_run_id UUID,                -- ties to concept_eval_run for FDR/provenance once promoted
    computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
```

Only rows that clear the `feature_interaction` domain's IC-Sharpe-plus-FDR gate get promoted: a `concept_registry` row is INSERTed with `domain='feature_interaction'`, `status='candidate'`, pointing back at its `compound_ic_scores` row via `metadata->>'xf_name'`. From there it goes through the same gate/promotion/decay machinery as every other domain — no bespoke lifecycle logic for interactions.

### IC Sweep

```
for each symbol:
    load feature_vectors into memory (N bars × 100 atomic columns)
    for each valid pair (i, j) × each operation:
        compute compound series via CompoundPrimitiveEvaluator
        compute IC against return targets
    aggregate IC across symbols (pooled, same methodology as Phase 138)

persist: pair-level IC scores in compound_ic_scores (small — 30k rows × a few metrics)
promote: INSERT to registry, set is_active = true, where IC Sharpe > gate and p < 0.05
```

The pair loop is embarrassingly parallel by pair, mirroring the existing IC engine. Rolling correlation windows require N-bar history — the in-memory load already provides it.

### Why Recompute Is Correct

Because atomic columns are stable stored values, computing `f_i * f_j` from stored `f_i` and `f_j` gives the exact same result every time. Recompute is not an approximation — it is exact. The only exception would be if a parent atomic column is redefined (which requires a Feature Factory migration and forces a full re-screen anyway). The canonical evaluator is the single point of truth; there is nothing else to drift from.

---

## Integration with IC Engine

The Interaction Factory is a pre-screening step, not a replacement for the IC engine. It runs once (or periodically when the tier-0 feature set changes), identifies which interactions pass IC gate, and promotes survivors. The IC engine then monitors promoted interactions the same way it monitors tier-0 features.

The pooled IC methodology (Phase 138) applies identically: minimum 20,000 bars, stride ≥ lookahead, `is_pooled = false` results drive promotion decisions.

---

## Why Not Hand-Pick

Renaissance's documented behavior: generate all candidates systematically, screen with statistics, never rely on human intuition to decide what to try. Hand-picking introduces survivorship bias before IC even runs — we test the pairs we think will work, which concentrates false confidence in the survivors.

The factory approach generates pairs we would never think to try. Some of them will have IC. Those are exactly the pairs we'd miss with hand-curation.

The current "Interaction Primitives" section in `renaissance-primitives-ohlcv.md` is a reasonable starting point and a useful sanity check, but it should not be the complete tier-1 feature set. Once the factory runs, IC results will show which of the hand-picked pairs were actually predictive vs. which were just intuitively appealing.

---

## Implementation Scope

When this gets planned as a phase, the scope is:

1. **Feature metadata**: add scale/sign metadata to all tier-0 features (may be delivered by Feature Registry phase first)
2. **Pair generator**: enumerate all valid pairs by operation type, applying ratio/product validity rules from metadata
3. **Streaming IC sweep**: integrate with Phase 138 IC engine infrastructure; compute pair IC without persisting intermediate vectors
4. **IC score table**: persist pair-level results (`xf_ic_scores` or extend `feature_ic_scores`)
5. **Promotion mechanism**: flag surviving pairs, trigger Feature Factory schema expansion, run backfill

Not in scope for initial phase: multi-way interactions (3+ features), interaction features with theory-embedded inputs, runtime computation in production alpha pipeline.

---

## Open Questions

- **Does the Feature Factory compute compound primitives inline, or is there a separate `InteractionFactory` batch service?** Probably a separate service — the computation graph for ~30k candidates is different enough from 54 atomics to warrant its own service unit.
- **How do we handle the feature explosion in the ensemble?** 100 atomics + 500 promoted compound primitives = 600 features going into the ensemble. The Correlation Engine's effective_N calculation becomes critical. May need additional constraints on how many compound primitives per parent atomic can enter the ensemble (concentration risk).
