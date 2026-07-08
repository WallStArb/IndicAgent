# Interaction Factory

**Status:** Idea — blocked on prerequisites (pilot test + primitives expansion + feature demotion mechanism)
**Refreshed:** 2026-07-06 — restored from archive; this is legitimate future work, not a rejected idea
**Original authorship:** 2026-07-01 — clarified what this actually is, added the missing evidence-based trigger, fixed statistical/architecture gaps, reframed from "a service" to "a candidate-generation strategy"
**Demotion mechanism:** see "Demotion" section below; implementation tracked at `.planning/todos/deferred/015-feature-vector-lifecycle.md`

---

## What This Is, In One Paragraph

Interaction Factory is **not a service and not a registry** — it's a *candidate-generation strategy*: a function that mechanically enumerates every valid pairwise combination of atomic features (product, ratio, rolling correlation — roughly 20,000-30,000 candidates at full scale) instead of a human hand-picking which combinations to try, then hands that candidate list to the *existing* IC engine and Concept Registry promotion pipeline for screening. It reuses infrastructure that already exists for every other domain (`feature`, eventually `alpha_pattern`, etc.) rather than standing up parallel machinery. If it's ever built, it should be small: one generator function plus one raw-screening table, not a new subsystem.

---

## Why It Might Exist (and Why That's Not Yet Established)

The stated motivation is bias avoidance: Renaissance's documented practice is to generate candidates systematically and let statistics decide, rather than hand-curating interactions based on domain intuition (which concentrates false confidence on the pairs a human happened to think would work). That's a real principle, but it's not by itself a sufficient reason to spend the compute.

**The actual justification this doc is missing:** evidence that the atomic feature set (61 features today, ~100 planned after primitives expansion) is IC-saturated — that first-order signal is exhausted and second-order combinations are where the next real IC lives. Nothing currently establishes this. Spending a large compute budget on pairwise combinations of features before confirming the atomics themselves have plateaued is solving the second problem before confirming the first one is solved. This reframes the trigger condition below.

---

## Build Trigger (evidence-based, not just readiness-based)

Two conditions, both required:

1. **Readiness:** primitives expansion landed (~100+ tier-0 atomics), IC engine stable on the full 58-symbol corpus, Feature Registry (or its Concept Registry successor) providing per-feature sign/scale metadata.
2. **Evidence of need — concrete pilot, not a vague finding.** `.planning/todos/pending/037-interaction-primitives-pilot-ic-test.md` is the actual test: add the ~20-30 hand-picked interaction primitives already specified in `renaissance-primitives-ohlcv.md` as ordinary Feature Factory columns (trivial cost, zero new infrastructure), and measure their **incremental IC after controlling for parent atomics** (partial correlation, not naive IC — a compound shares variance with its parents by construction, so naive IC overstates its value) through the IC Engine that's already live. This is the same partial-IC machinery as `docs/plans/2026-06-29-feature-scoring-beyond-ic.md` §0a (marginal contribution) — build it once; the pilot's parent-conditioned screening and the general promotion criterion are one implementation. If that cheap, favorably-selected cohort shows real incremental IC surviving FDR, that's the evidence to plan the full systematic build. If it shows near-zero incremental IC, shelve Interaction Factory outright — a null result on a hand-picked, domain-intuition-backed cohort is stronger evidence against the premise than a null result on randomly-generated pairs would be.

Do not build the full generator on readiness alone, and do not defer indefinitely without running the cheap test — "someday" is not a decision.

---

## Architecture: A Generator, Not a Service

### First Principle: Atomics Are the Irreducible Information

A compound primitive `xf_prod__body_ratio__volume_z` is entirely determined by `body_ratio` and `volume_z` at the same bar — it contains zero additional information beyond its parent atomic columns. "Never drop data that could contain signal" applies to atomics; compounds are derived, not fundamental. **Atomic primitives are stored; compound primitives are computed on-demand from their parents.** No schema migration per compound, no redundant state that can drift from its definition.

### The Consistency Constraint

If the compound formula is implemented differently in IC screening vs. IC monitoring vs. ensemble inference, training features ≠ inference features — a silent wrong answer, the worst outcome. Solution: **one canonical `CompoundPrimitiveEvaluator`**, called identically in every context.

```python
# called identically everywhere — no context-specific reimplementation
value = CompoundPrimitiveEvaluator.evaluate(
    series_a, series_b, operation="product", window=None
)
```

Because atomic columns are stable stored values, recomputing `f_i * f_j` from stored `f_i`/`f_j` gives the exact same result every time — not an approximation, exact. The only exception is if a parent atomic column is redefined, which forces a Feature Factory migration and a full re-screen anyway regardless of how compounds are stored.

### Candidate Generation → Existing Pipeline, Not a New One

The generator's only job is producing a stream of `(feature_a, feature_b, operation, window)` tuples. Everything downstream reuses what already exists:

- **Raw screening** — a lightweight table, outside Concept Registry's scope (same pattern as `feature_ic_scores`):

```sql
compound_ic_scores (
    feature_a   TEXT NOT NULL,      -- alphabetically canonical ordering for commutative ops (see below)
    feature_b   TEXT NOT NULL,
    operation   TEXT NOT NULL,      -- 'product', 'ratio', 'corr_fast', 'corr_slow'
    xf_name     TEXT NOT NULL UNIQUE,
    ic_sharpe   NUMERIC,
    ic_n        INTEGER,
    p_value     NUMERIC NOT NULL,   -- raw, pre-correction
    eval_run_id UUID NOT NULL,      -- ties every row to one batch — see FDR section below
    computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
```

- **Promotion, once Concept Registry ships** — survivors become `domain='feature_interaction'` rows in the unified `concept_registry` ([Concept Registry](platform-unified-concept-registry.md)), through the *same* gate/promotion/decay machinery every other domain uses. `feature_a`/`feature_b`/`operation`/`xf_name` live in `concept_registry.metadata JSONB`; a `concept_registry` row is INSERTed with `status='candidate'` pointing back at its `compound_ic_scores` row. No bespoke lifecycle logic, no separate `compound_primitive_registry` table.
- **Promotion, interim state (Concept Registry not built, likely true when the pilot or an early full build runs)** — survivors land in the live `feature_registry` instead, as ordinary rows alongside atomic features, governed by whatever demotion mechanism `.planning/todos/deferred/015-feature-vector-lifecycle.md` ships. No separate table needed here either — the interim path reuses live infrastructure exactly like the eventual path reuses Concept Registry.

This is the concrete reason the earlier "is it a service" framing was wrong: the only genuinely new code is the generator and the raw-screening table. Screening, gating, promotion, decay, and knowledge annotation are all inherited for free.

---

## Statistical Correctness (the gaps that actually mattered)

**1. Multiple-testing correction must be explicit and batch-scoped, not implied.** The naive rule "IC Sharpe > gate and p < 0.05," applied uncorrected across ~30,000 candidates, produces roughly 1,000-1,500 false "discoveries" from pure chance even if zero real interaction effects exist. `compound_ic_scores.eval_run_id` above exists specifically so a corpus-level Benjamini-Hochberg FDR correction can be applied across the full batch before any promotion — same principle the IC engine already applies at the corpus level (Phase 142A), extended to cover this specific candidate pool. The corrected significance threshold, not the raw `p < 0.05`, is what gates promotion into `concept_registry`.

**2. Rolling correlation must be explicitly causal.** `corr(f_i, f_j, N)` is only a valid feature if computed strictly trailing — window `[t-N, t]`, never touching `t+1` or later. This project has already had one real look-ahead incident (HMM regime model fitting on the full corpus before its causal decode); an unstated assumption in a second rolling-window computation is worth closing explicitly rather than risking a repeat.

**3. Compute cost needs a real estimate or a two-stage funnel, not a TODO.** "Profile before running at full corpus scale" is not a plan. With ~4,950 pairs × up to 3 operations × 2-3 correlation windows across 58 symbols × 5 timeframes × years of bars, the honest move is a cheap prefilter stage (short-sample or approximate correlation check) to cut the candidate set before committing full walk-forward IC computation to all ~30,000 candidates — not screening everything at full cost by default.

**4. Worker/writer separation follows the project's existing pattern.** The IC sweep is embarrassingly parallel by pair, but per this project's established rule (bitten once already by `regime_writer`), `ProcessPoolExecutor` workers must be compute-only — return `(candidate, ic_sharpe, ic_n, p_value)` tuples to the main process; a single serial connection performs all writes to `compound_ic_scores`. No worker opens a write connection.

**5. Canonical pair ordering avoids doubling compute for free.** Product and correlation are commutative (`f_i * f_j = f_j * f_i`; `corr(f_i,f_j) = corr(f_j,f_i)`); ratio is not (`f_i/f_j ≠ f_j/f_i`, and only one direction is typically valid per the denominator-positivity rule below). The `C(100,2) = 4,950` pair count already assumes unordered pairs — the generator must enforce that explicitly (e.g. `feature_a < feature_b` alphabetically for commutative operations) or risk silently generating and screening both `xf_prod_a__b` and `xf_prod_b__a` as distinct candidates, doubling compute on 2 of 3 operation types for zero additional information.

---

## The Three Interaction Operations

### 1. Product: f_i × f_j

Captures joint behavior. Most meaningful when both features carry sign — a large positive product means both features agree directionally. **Valid when** both features are reasonably bounded or z-scored; unbounded × unbounded produces a heavy-tailed distribution that inflates IC variance — pre-normalize unbounded inputs first. Example: `body_ratio * volume_z` — directional conviction × volume confirmation.

### 2. Ratio: f_i / f_j

Relative magnitude — "feature i relative to feature j." **Valid when** the denominator is always positive and bounded away from zero. **Valid denominators:** `atr_z + offset`, `volume_z + offset`, any `[0, ∞)` feature with a floor. **Invalid denominators:** `body_ratio`, `ret_lag_fast` (both cross zero). Requires per-feature sign/scale metadata — the Feature Registry / Concept Registry dependency below.

### 3. Rolling Correlation: corr(f_i, f_j, N), strictly trailing

Time-varying joint behavior over a causal window ending at the current bar. Captures whether two features agree or disagree in a rolling period — a shift from +1 to -1 signals a regime change even if neither feature alone has moved. **Valid when** both features have meaningful variance in the window; constant features produce undefined correlations. Window choices: `fast`/`slow` (APR-backed: `feature.xf_corr.fast`, `feature.xf_corr.slow`), same gradient convention as other features.

---

## Feature Metadata Dependency

The factory cannot run without knowing each atomic feature's `sign_type` (`signed`/`positive`/`bounded_01`/`binary`) and `scale` (`z_scored`/`natural_bounded`/`raw_ratio`/`raw_unbounded`) — this is what determines ratio validity and whether to pre-normalize before a product. This metadata is provided by `feature_registry` (61 rows, live in production) and will be absorbed into `concept_registry` per [Concept Registry](platform-unified-concept-registry.md). Historical design: `docs/research/archive/feature-registry.md`. Without this metadata, the factory has to hardcode scale knowledge per feature — a maintenance burden that grows with the feature set. **Implementation order, if built:** feature_registry already satisfied; Interaction Factory second.

---

## Naming Convention

`xf_` prefix (cross-feature), double underscore between feature names to avoid collision with feature names that already contain underscores:

```
xf_{operation}_{feature_a}__{feature_b}
xf_{operation}_{feature_a}__{feature_b}_{window}
```

- `xf_prod_body_ratio__volume_z` — product, no additional window
- `xf_ratio_ret_lag_fast__atr_z` — ratio, windows inherited from parents
- `xf_corr_ret_lag_fast__volume_z__fast` — rolling correlation, fast window

---

## Why Not Hand-Pick, and Why That's Not the Whole Argument

Renaissance's documented practice is to generate all candidates systematically and screen with statistics, rather than relying on human intuition — hand-picking introduces survivorship bias before IC even runs, concentrating false confidence in the pairs someone guessed would work. The hand-picked "Interaction Primitives" in `renaissance-primitives-ohlcv.md` (`vol_body_product`, `price_vol_corr`, etc.) are a reasonable starting point and sanity check, but not necessarily the complete tier-1 feature set.

That principle argues for *why systematic generation is better than hand-picking, if interaction effects are being pursued at all*. It does not establish *that* they should be pursued right now — see "Build Trigger" above. The two questions are separate; this doc previously conflated them.

---

## Does This Generalize Beyond Features?

Yes, as a *methodology* — "generate candidates combinatorially, screen through the existing gate/promotion pipeline" applies just as well to combining `alpha_pattern`s into meta-patterns or `hmm_variant` configurations as it does to feature pairs. It does **not** generalize as a *service* right now — building a generalized combinatorial-generation subsystem today, for domains (`alpha_pattern`, `hmm_variant`) that have zero real candidates, would repeat the exact premature-abstraction mistake already caught and reversed in Concept Registry's design (see [Concept Registry](platform-unified-concept-registry.md), "Status check, applied honestly"). If a future domain needs this pattern, it gets its own thin generator function feeding the same shared pipeline — not a shared "Combinatorial Factory" framework built ahead of need.

---

## Concentration Risk (open question, correctly unresolved)

100 atomics + however many promoted compound primitives survive = a larger feature set entering the ensemble. The Correlation Engine's `effective_N` calculation becomes load-bearing — without it, a compound primitive that's highly correlated with its own parents (or with other compounds) inflates apparent diversity without adding real orthogonal information. `concept_correlation` (Concept Registry's reference architecture, not yet built) is the eventual mechanism for this; until then, this remains a genuinely open question rather than a false one, since no compounds exist yet to measure.

---

## Demotion — Why Compound Primitives Make This Urgent, Not Just Relevant

Promotion alone is not a complete lifecycle. Right now, in the live system, a feature that clears the IC gate once stays in the ensemble forever — the demotion side is unwired (full mechanism and design decisions: `docs/research/feature-vector-lifecycle.md`, implementation tracked at `.planning/todos/deferred/015-feature-vector-lifecycle.md`). With 61-100 hand-reasoned atomic features, an analyst could plausibly notice a stale feature by inspection. That stops being true the moment compound primitives enter the picture: even a modest, FDR-corrected survivor count (see "Build Trigger" — realistically single digits to low tens after proper correction, not hundreds) means the ensemble now contains features nobody chose by hand and nobody is positioned to notice decaying by inspection. A compound primitive's edge can disappear silently — its parent atomics still update every bar, the compound still computes a number, but the *relationship* that gave it IC in the first place can erode without any visible symptom short of an actual re-measurement.

This mechanism doesn't need Interaction Factory to justify building it — it's needed for the 61 atomic features already in production today, independent of whether compound primitives ever exist, and P2-tracked at todo 015 regardless of this doc's own status. Interaction Factory is only the reason demotion stops being optional-nice-to-have and becomes a real risk if skipped: more features, none hand-reasoned, none easy to eyeball. That's the whole contribution this section makes — a reason to prioritize 015, not a restatement of what 015 already covers.

---

## Not In Scope

Multi-way interactions (3+ features), interaction features with theory-embedded inputs (HMM state, S/R zones — those have their own governance track), runtime computation in the production alpha pipeline (compounds are screening-time and training-time only, recomputed from stored atomics, never persisted as a separate hot-path computation).
