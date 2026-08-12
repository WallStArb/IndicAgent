# Regime Boundary-Churn Diagnostic — Design

**Status:** approved, ready for implementation plan
**Origin:** todo 080, L5-1 ("regime-posterior soft blending") — see `docs/research/fable-2026-07-07-renaissance-layer-refinements.md` §8
**Author:** Claude (design), Brandon (direction/approval)

## Context

Todo 080's L5-1 proposed replacing today's hard-argmax regime scoring
(`alpha_score(bar) = w[regime_label(bar)] · features(bar)`) with a probability-weighted
blend across regimes, on the premise that hard boundary crossings "manufacture emission
churn from label noise" and that the fix is free — `market_regimes.regime_prob_vector`
already stores a posterior, "zero new data."

That premise doesn't hold. Tracing `cross_sectional_regime_model.py`'s `_assign_labels`
(services/cross_sectional_regime_model.py:207-245) shows `regime_label` is built by
independently hard-bucketing two continuous signals (`vix_pct`/`breadth_frac` for equity,
`curve_z`/`credit_z` for rates) via `_bucket()`'s strict thresholds, then concatenating
tier names. `regime_prob_vector` is literally `{sig1_key: sig1_value, sig2_key: sig2_value}`
— the raw signals that fed the bucketing, not a probability distribution over labels. There
is no existing `P(regime|bar)` to consume for the system `ensemble_trainer.py` actually
stratifies on.

**This design does not build soft blending.** It builds the diagnostic that must run first:
is hard-argmax boundary churn actually material on real data? Per this project's "earn
promotion through proof" principle, soft-blending machinery (which, per the discussion that
produced this doc, also needs a mixture-CI variance fix, cross-regime feature-set alignment,
and a new APR-backed smoothing bandwidth — real scope, not a small patch) is not justified
until the problem it fixes is shown to be real and material. If Phase 0 fails the gate
everywhere, L5-1 closes as measured-and-rejected — a real finding, not wasted effort.

## Decision gate (pre-committed before running, not tuned after seeing results)

Per `(regime_group, tf)`, soft blending is justified only if **both** hold:

1. **Materiality of exposure:** boundary-adjacent bars are ≥5% of all bars in that
   `(regime_group, tf)`. Below this, even a real per-bar effect is aggregately negligible.
2. **Materiality of effect:** for boundary-adjacent transition bars, the median
   `|alpha_score(actual regime weights) − alpha_score(neighbor regime weights)|` exceeds
   1.5× the *clean* same-regime bar-to-bar `alpha_score` volatility (see "Clean noise
   floor" below — this is not corpus-wide volatility).

Any `(regime_group, tf)` failing either criterion is not a blending candidate. A future
Phase 1 (if triggered) is scoped only to the cells that pass both.

## Phase 0 architecture

**Script:** `scripts/analysis/regime_boundary_churn_check.py` — read-only, standalone,
not part of the live DAG (same class as `ic_sharpe_stride_bias_check.py`,
`crowding_proxy_regression.py`). No writes, no new tables, no Kafka. Zero coupling to the
in-flight corpus pipeline beyond reading already-committed rows — safe to run concurrently.

**Validity window:** results reflect the *current* (pre-143.1-07-fix) `ensemble_weights`/
`ensemble_alpha`. Cheap to re-run once the corrected corpus lands (same shape of caveat as
the E1/E2 A/B judgment) — this is a preliminary read, not a final verdict, and should be
reported as such.

### Data flow

```
market_regimes (regime_prob_vector, regime_label,      ─┐
  one row per (regime_group, tf, ts) — no symbol dim)   │
build_tiers() [imported from src/intelligence/          ├─► per-timestamp boundary
  regime_signals/<group>.py — NOT retyped]               │   classification (per-axis)
                                                         │
ensemble_weights (current weight_version)              ─┘
        │
        ▼
stratified sample of (ts, symbol) rows at boundary-adjacent
timestamps (~50k total, proportional-to-cell-size with a per-cell cap)
        │
        ▼
feature_vectors (X for sampled bars)  ──► reuse ensemble_trainer.py's
                                           X @ (weights * ic_signs) pattern,
                                           scored under (a) actual regime's weights,
                                           (b) each relevant neighbor regime's weights
        │
        ▼
ensemble_alpha (same-regime-only bar pairs) ──► clean noise floor
        │
        ▼
per-(regime_group, tf) gate verdict, same shape as ops_ensemble_ic_gate.py
```

### Core algorithm, in order

1. **Load cut points via the real code, not retyped constants.** For each enabled group in
   `alpha.regime.groups`, import `build_tiers(params)` from that group's own
   `src/intelligence/regime_signals/<group>.py` module — the exact function
   `cross_sectional_regime_model.py` calls in production. Never hand-copy threshold values.

2. **Derive the boundary window from the data, not a fixed percentage.** For each
   `(regime_group, tf, axis)`, compute the empirical median absolute bar-to-bar step size
   of that axis's signal (`vix_pct`, `breadth_frac`, `curve_z`, `credit_z`). Boundary window
   = ±2× that step size around each tier cut. This is self-calibrating and generalizes
   across bounded `[0,1]` signals (equity) and unbounded z-scores (rates) without
   group-specific window logic.

3. **Classify each *timestamp* by which axis (if any) is boundary-adjacent.**
   `market_regimes` is keyed `(regime_group, tf, ts)` with no symbol dimension — the
   cross-sectional regime is one market-wide value per timestamp, shared by every symbol.
   So boundary-adjacency is a property of `(regime_group, tf, ts)`, not of any individual
   symbol's row. A timestamp can be axis-1-adjacent, axis-2-adjacent, both (corner case),
   or neither. For axis-1-adjacent timestamps, the only relevant "neighbor regime" is the
   one reached by crossing axis 1 (holding axis 2's tier fixed) — never an indiscriminate
   compare against all 8 grid neighbors. Corner-case timestamps (both axes adjacent)
   compare against all 3 reachable neighbors (2 edge + 1 diagonal), each attributed to its
   own transition.

4. **Sample, don't pull the full corpus.** First select the set of boundary-adjacent
   timestamps per `(regime_group, tf)` (step 3). Then sample `(ts, symbol)` rows from
   `feature_vectors` at those timestamps — allocation proportional to each
   `(regime_group, tf)` cell's share of boundary-adjacent timestamps, with a per-cell cap
   so no single large cell (e.g. 5m, which has far more bars than 1d) starves the others of
   representation. Target ~50k `(ts, symbol)` rows total. Statistically equivalent
   gate-decision power to a full pull, at a fraction of the I/O and memory footprint —
   relevant given the box's confirmed memory pressure while the corpus pipeline is also
   running.

5. **Handle untrained-neighbor bars explicitly, never silently drop.** If a bar's actual
   regime or its neighbor regime has no row in `ensemble_weights` (stratum never trained —
   `_process_stratum`'s `min_passing_features`/zero-weight early returns), exclude that bar
   from the effect-size calculation but count and report it separately per
   `(regime_group, tf)`. A neighbor that never trained is itself informative about
   instability, not a bar to quietly discard.

6. **Align weight vectors onto the union of selected features before scoring.** Each
   regime's `ensemble_weights` rows may cover a different feature set. Before scoring a bar
   under both the actual and neighbor regime's weights, zero-pad each vector onto the union
   of both regimes' selected features so a feature present in one but absent in the other
   contributes correctly rather than being silently misaligned.

7. **Score via the production pattern, not a rederived formula.** For each sampled bar,
   compute `alpha_score = X[bar] @ (weights * ic_signs)` for the actual regime and each
   relevant neighbor — the exact expression `ensemble_trainer.py`'s Step 6 uses. No second
   implementation of the scoring math.

8. **Clean noise floor, not a contaminated one.** From `ensemble_alpha`, compute bar-to-bar
   `|Δalpha_score|` **only for consecutive-bar pairs where `regime_label` did not change**
   — i.e., pure feature-driven movement, with zero contribution from the churn effect under
   test. This is the volatility floor gate criterion 2 compares against. (Using
   corpus-wide bar-to-bar volatility here — including transition bars — would bias the test
   toward false negatives, since the baseline would already contain the effect being
   measured.)

9. **Emit one verdict row per `(regime_group, tf)`:** boundary-adjacent fraction, median
   effect size, clean noise floor, untrained-neighbor bar count, PASS/FAIL per criterion,
   overall gate verdict. Same reporting shape as `ops_ensemble_ic_gate.py`.

### Implementation conventions

- `asyncpg` + connection pool for DB access (matches `ensemble_trainer.py`/
  `alpha_publisher.py`'s idiom) — single-process bulk reads at this sample size, no
  multiprocessing worker pool needed.
- Pure functions for the boundary-classification and weight-alignment logic, unit-testable
  without a DB (matching `weights.py`/`alpha_score.py`'s pure-function convention) —
  DB access confined to the fetch layer only.
- No APR keys required: this is an analysis script (`scripts/analysis/`), not `src/` or
  `services/`, so it's outside the APR mandate's scope. Constants (sample size, window
  multiplier, effect-size multiplier) live as named module-level constants with the gate
  criteria's rationale in a docstring, since they're pre-committed thresholds, not
  operator-tunable calibration.

### Testing plan

- Unit tests (no DB) for: boundary-window derivation from a synthetic step-size series;
  axis classification (single-axis, corner-case, neither); weight-vector union-alignment
  zero-padding; untrained-neighbor exclusion-and-count logic.
- One integration-shaped test against a small synthetic `market_regimes`/`ensemble_weights`/
  `feature_vectors`/`ensemble_alpha` fixture set, asserting the gate verdict shape and that
  a manufactured "obviously churny" cell fails while an "obviously stable" cell passes.

## Phase 1 (gated, sketched only — not built now)

If Phase 0 passes the gate for one or more `(regime_group, tf)` cells, Phase 1 designs
soft-membership scoring for those cells specifically:

- Replace each axis's hard `_bucket()` threshold with a smooth membership function
  (bandwidth per axis, APR-backed under `alpha.regime.soft_membership_bandwidth.*` since
  this *is* live `services/` code at that point) — outer product across the two axes gives
  a soft distribution over the `3×3` grid.
- Fix the mixture-CI understatement: `compute_alpha_score`'s margin must account for
  between-regime variance (law of total variance), not just each regime's own IC-CI width.
- `ensemble_alpha.regime` keeps the hard-argmax label for downstream stratified
  re-measurement continuity (it's descriptive, not part of the uniqueness key) — only
  `alpha_score` reflects the blend.
- Scoring restructures from one matmul per stratum (today) to one matmul per regime over
  all bars in that `(tf, regime_group)`, combined via each bar's soft-membership weights —
  still fully vectorized, no per-bar loop.
- Judged via the existing `ops_ensemble_weight_compare.py` A/B machinery as a new
  `weight_version` variant, same D-10 win-rule framework as every other E-candidate.

This section is intentionally not detailed further — designing it in full before Phase 0's
gate is passed would be exactly the premature-investment mistake this diagnostic exists to
prevent.

## Out of scope

- Retargeting to the per-symbol HMM regime system (`feature_vectors.hmm_prob_*`) —
  considered and rejected; `ensemble_trainer.py` doesn't stratify on that system today, and
  introducing it would be a materially larger architectural change than L5-1 as scoped.
- Any change to how regimes are trained (`_process_stratum`'s per-regime weight fitting
  stays hard-partitioned regardless of Phase 0's outcome — only *scoring* is a blending
  candidate).
