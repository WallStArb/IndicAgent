---
**Created:** 2026-06-28
**Area:** intelligence
**Type:** new_feature
**Priority:** P3
**Effort:** 7-10 days
**Benefit:** Automatic generation of compound primitives (e.g., momentum_rank_z × volatility_rank_z)
**Risk:** medium (combinatorial explosion needs capping)
**Gate:** Primitives expansion complete
---

# 019 — Interaction Factory

**Status:** Pending
**Priority:** Post-primitives-expansion
**Depends on:** 008-feature-registry (metadata required, implemented), primitives expansion landed (~100+ tier-0 atomics), IC engine stable on full 58-symbol corpus
**Concept doc:** `docs/ideas/interaction-factory.md`

## What

Build a batch component that systematically generates all N*(N-1)/2 pairwise combinations of tier-0 atomic features (products, ratios, rolling correlations) and screens them through the IC engine. No human selection of which pairs to try. With ~100 tier-0 atomics: ~5,000 pairs × 3 ops × 2 windows ≈ 30,000 candidates.

## Why

Renaissance doesn't hand-curate feature interactions. They generate all candidates and let IC statistics decide what survives. Hand-picking concentrates false confidence on pairs that seem intuitive; the factory finds pairs we'd never think to try.

## Trigger

IC engine producing stable results on current 54-feature corpus, primitives expansion (renaissance-primitives-ohlcv.md) landed and backfilled, Feature Registry (008, implemented) delivering feature metadata.

## Scope (when planned)

1. Feature metadata — scale/sign properties for all tier-0 atomics (via Feature Registry)
2. Pair generator — enumerate valid pairs by operation type (ratio validity requires non-zero positive denominator)
3. Streaming IC sweep — compute pair IC in memory without persisting all ~30k intermediate vectors
4. IC score persistence — extend or add to `feature_ic_scores`
5. Promotion mechanism — schema expansion + backfill for survivors

## Key Design Decisions (pre-resolved in concept doc)

- **Atomics stored, compounds computed.** Compound primitives contain zero additional information beyond their parent atomic columns. No schema migration per compound. No redundant state.
- **Single canonical `CompoundPrimitiveEvaluator`.** Called identically in IC screening, IC monitoring, ensemble training, ensemble inference. One implementation, no training/inference drift.
- **`compound_primitive_registry` is the schema.** Promotion = INSERT + set is_active = true. Not a migration.
- `xf_prod__{a}__{b}`, `xf_ratio__{a}__{b}`, `xf_corr__{a}__{b}_{window}` naming with `xf_` prefix and double underscore separator
- APR keys: `feature.xf_corr.fast`, `feature.xf_corr.slow`
- Ratio validity enforced via feature metadata (denominator must be always-positive, bounded away from zero)
