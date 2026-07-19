---
**Created:** 2026-06-28
**Closed:** 2026-07-19 — REJECTED/SUPERSEDED, not built
**Area:** intelligence
**Type:** new_feature
**Priority:** P3
**Effort:** 7-10 days for the full generator — moot, see closure note below
**Benefit:** Automatic generation of compound primitives (e.g., momentum_rank_z × volatility_rank_z), IF the pilot proves the premise
**Risk:** medium (combinatorial explosion needs capping; also see statistical risks below)
**Gate:** N/A — closed. The evidence gate (todo 037) fired 2026-07-10, but the specific
combinatorial mechanism this todo describes was independently rejected by Phase 151 on a
statistical-power ground unrelated to evidence, so no future evidence reopens it. See below.
---

# 019 — Interaction Factory

**Status: CLOSED — REJECTED/SUPERSEDED (2026-07-19).** Evidence gate fired (todo 037 PASSED,
2026-07-10), but this todo's specific combinatorial mechanism was already independently
rejected by Phase 151 (`ROADMAP.md`) on a separate ground: BH-FDR loses meaningful power at
~30K simultaneous candidates (~1,500 expected false discoveries regardless of pre-screening),
a problem orthogonal to whether the atomics are IC-saturated. Phase 151 committed instead to a
curated ≤50-feature Theory-Motivated Interaction Layer, which is the live path for pursuing
interaction effects. 037's PASS confirms interaction effects are real and worth pursuing
(validating Phase 151's direction), but does not revive this todo's full-generator design —
that would require separately overturning Phase 151's BH-FDR-power rejection, a design
decision, not an evidence threshold, so it cannot be re-triggered by citing 037 again. Moved
from `deferred/` to `completed/` (closed-as-rejected, not done) so it stops being read as
gated-and-pending. Concept preserved for reference in
`docs/research/intel-feature-interaction-factory.md`, itself already marked superseded.
**Priority:** Closed (superseded in practice by Phase 151's implementation choice; would
need a deliberate future decision to re-open)
**Depends on:** 008-feature-registry (metadata required, implemented), primitives expansion
landed (89 Renaissance primitives live, 2026-07-09), IC engine stable on full 80-symbol
corpus, **037 pilot showing real incremental IC on hand-picked interactions — CLEARED
2026-07-10, 192/864 cells (22.2%) passed BH-FDR, see
`.planning/todos/completed/037-interaction-primitives-pilot-ic-test.md`**
**Concept doc:** `docs/research/intel-feature-interaction-factory.md` (refreshed 2026-07-01 —
reframed from a service to a candidate-generation strategy, added the evidence-based trigger,
fixed statistical gaps; updated 2026-07-10 to record the trigger firing and the Phase 151
tension above)

## What

A candidate-generation strategy — not a standalone service — that systematically enumerates N*(N-1)/2 pairwise combinations of tier-0 atomic features (products, ratios, rolling correlations) and screens them through the *existing* IC engine + Concept Registry promotion pipeline. No human selection of which pairs to try. With ~100 tier-0 atomics: ~5,000 pairs × 3 ops × 2-3 windows ≈ 20,000-30,000 candidates.

## Why (and why this isn't sufficient justification by itself)

Renaissance doesn't hand-curate feature interactions — they generate all candidates and let IC statistics decide what survives, avoiding the false confidence hand-picking concentrates on pairs that seem intuitive. That's a real principle, but it only argues for *how* to search if interaction effects are being pursued at all — it doesn't establish *that* the atomic feature set has exhausted its own signal and second-order combinations are where the next real IC lives. Nothing currently establishes that. This is why 037 exists.

## Trigger — do not build on readiness alone

1. **Readiness:** primitives expansion landed (~100+ tier-0 atomics), IC engine stable, Feature Registry delivering per-feature metadata (008, already implemented).
2. **Evidence, from 037:** the ~20-30 hand-picked interaction primitives in `renaissance-primitives-ohlcv.md` show real **incremental IC after controlling for parent atomics** (partial correlation, not naive IC) when run through the IC engine that's already live. If 037 comes back null, shelve this todo outright rather than leaving it deferred indefinitely.

## Scope (when 037 triggers this)

1. Feature metadata — scale/sign properties for all tier-0 atomics (via Feature Registry / Concept Registry)
2. Pair generator — enumerate valid pairs by operation type, **canonical ordering enforced for commutative operations** (product, correlation — `feature_a < feature_b` alphabetically) to avoid computing both directions of the same candidate; ratio validity requires a non-zero positive denominator
3. Streaming IC sweep — compute pair IC in memory without persisting all ~30k intermediate vectors; **worker processes are compute-only, return results to a single serial writer** (this project's established ProcessPoolExecutor pattern — see `regime_writer`/`ic_engine`)
4. IC score persistence — `compound_ic_scores` table (new, lightweight, outside Concept Registry), keyed to an `eval_run_id`
5. **Batch-level FDR correction across the full candidate set is mandatory before promotion** — naive `p<0.05` across ~30,000 candidates produces ~1,000-1,500 false discoveries from chance alone
6. Promotion — survivors land in the **live `feature_registry`** if Concept Registry hasn't shipped yet, or `concept_registry` (`domain='feature_interaction'`) if it has. No standalone `compound_primitive_registry` table either way.
7. Demotion/decay — governed by `docs/research/intel-14-integrity-monitor.md` (interim, `feature_registry`) or Concept Registry's `decay_floor` (eventual). (Was previously scoped as todo 015, now superseded/completed — see `.planning/todos/completed/015-feature-vector-lifecycle.md`.)

## Key Design Decisions (pre-resolved in concept doc)

- **Atomics stored, compounds computed on-demand, never persisted as a hot-path column.** A compound primitive contains zero additional information beyond its parent atomic columns at the same bar — recompute is exact, not an approximation. This means IC Engine and Ensemble Trainer need an on-the-fly `CompoundPrimitiveEvaluator` invocation for promoted compounds — a real integration point not yet built anywhere, flagged in the concept doc.
- **Single canonical `CompoundPrimitiveEvaluator`.** Called identically in IC screening, IC monitoring, ensemble training, ensemble inference. One implementation, no training/inference drift.
- **Rolling correlation must be explicitly causal** — trailing window `[t-N, t]` only, never touching future bars. Stated explicitly after this project's prior HMM look-ahead incident.
- `xf_prod__{a}__{b}`, `xf_ratio__{a}__{b}`, `xf_corr__{a}__{b}_{window}` naming with `xf_` prefix and double underscore separator
- APR keys: `feature.xf_corr.fast`, `feature.xf_corr.slow`
- Ratio validity enforced via feature metadata (denominator must be always-positive, bounded away from zero)
