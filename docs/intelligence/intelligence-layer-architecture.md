# Intelligence Layer Architecture — Layers vs. Mechanisms

**Version:** 1.0.0
**Status:** current
**Milestone:** v3.0
**Purpose:** Describe the pipeline's functional layers generically, separate from
the specific statistical mechanism each layer happens to use today. A layer name
is a contract (what goes in, what comes out); a mechanism is the current
implementation of that contract. Mechanisms are swappable. Layer names and
contracts are not, without a deliberate architecture change.

**Companion doc:** `docs/intelligence/intelligence-alphaengine.md` covers the same
pipeline in implementation detail (IC formulas, HMM parameters, ensemble math).
This doc exists because that one conflates layer and mechanism throughout — this
is the generic map; that doc is the current mechanism's manual.

---

## Why this split matters

Every layer below has, so far, exactly one implementation. That's made it easy to
use the mechanism's name (HMM, IC, Ledoit-Wolf) as if it were the layer's name.
It works today because nothing has ever needed a second mechanism for the same
layer. The moment that changes — a second regime classifier, a non-Spearman edge
measure, a second weighting scheme (142B.1 already does this for Stage 3) — code
and docs that never separated the two have to be untangled under pressure. This
doc draws the line now, while there's still only one mechanism per layer, so the
next swap is a slot-in rather than a rename.

---

## The four layers

### Stage 0 — Primitive Measurement

**Contract:** raw OHLCV bar in → a fixed-width vector of scalar measurements out.
No theory, no conditioning on state, no cross-bar judgment beyond a short
rolling window. Each value is deterministic and reproducible — a different
researcher with the same data computes the identical number.

**What it's called:** `FeatureFactory`, producing a `FeatureVector`
(`feature_vectors` table). Some individual measurements do encode theory
(`hmm_regime_prob`, `poc_dist_atr`, `ctf_momentum`) — these are Stage 0's output
even though they're computed downstream of Stage 1/2 internals, because from the
outer pipeline's perspective they're still just columns on the vector, same as
`body_ratio` or `dollar_vol_z`.

**Current mechanism:** ~61 pure Python functions in `src/intelligence/feature_factory.py`,
organized by cadence (bar-level, session-level, regime-level, cross-asset,
calendar). See `docs/research/feature-registry.md` for the proposed
`0_atomic`/`1_interaction`/`2_theory` sub-classification within this layer —
not yet built, currently informal.

**Could a different mechanism fill this slot?** Yes in principle (a different
measurement library, a different primitive catalog), but this is the layer
least likely to ever need swapping — "measure the market" doesn't have
competing schools of thought the way regime-assignment or edge-measurement do.

---

### Stage 1 — Stratification / Conditioning-State Assignment

**Contract:** the corpus of `FeatureVector`s in → a discrete label per bar out,
partitioning observations into groups that are expected to condition
downstream relationships differently. This layer doesn't claim any primitive is
predictive — it only claims "these bars belong together, those bars don't."

**What it's called:** `regime` — a discrete classified state that conditions the behavior
of indicators, signals, and factor relationships (see the `regime` glossary entry).

**Current mechanism:** two independent, coexisting implementations (see
`MEMORY.md` "Dual Regime System"):
- Per-symbol: `GaussianHMM` (`regime_writer.py`) — 5 states, forward-Viterbi
  decode, fit per (symbol, timeframe) from log-return/vol-of-vol/relative-volume
  observations.
- Cross-sectional: `equity_regime_model.py` — 9 states from realized-vol
  z-score percentile (VIX proxy) × breadth (fraction of universe above 200MA).

**Could other mechanisms fill this slot?** Yes, and it's the layer where this
question has already been asked for real: `docs/plans/archive/2026-07-01-regime-stratification-alternatives.md`
proposed adding Volume Regime, Skew/Tail Regime, Factor Regime, and alternative
HMM variants (IOHMM with exogenous transition probabilities, factor-augmented
HMM — see the 2026-07-04 conversation on time-varying transition matrices) as
*additional or alternative* stratification dimensions, gated behind an
"Orthogonality Gate" so a new dimension only ships if it's not redundant with
existing ones. That doc is currently archived/retired (its own P-numbering was
dropped 2026-07-02), but the underlying question — HMM is one way to assign
regime, not the only conceivable one — is exactly this layer's swap point.
`todo 026`'s Decision Gate (regime-IC separation query) is the live mechanism
for deciding whether a *different* Stage 1 mechanism is even worth building.

---

### Stage 2 — Predictive Relationship / Edge Measurement

**Contract:** a `FeatureVector` column (optionally stratified by a Stage 1
label) plus subsequent forward returns in → a statistic quantifying predictive
relationship, with a confidence interval, out. This layer doesn't combine
anything — it scores one feature (in one regime, one timeframe, one lookahead
window) in isolation.

**What it's called:** `IC Engine` / "IC discovery" (glossary L699).

**Current mechanism:** Spearman rank correlation between feature value at bar
T and forward return at T+N (`Information Coefficient`), computed per feature ×
timeframe × regime × lookahead window, with bootstrap confidence intervals and
`IC Sharpe` (mean/std of a rolling IC time series) as the stability-adjusted
summary statistic. Executable-return invariant applies:
`return_type = 'executable_open_to_open'` only.

**Could other mechanisms fill this slot?** Yes — this is a real, open question,
not hypothetical. Spearman IC measures monotonic rank relationship; it is blind
to relationships that are predictive but non-monotonic (a feature that's bad
at extremes and good in the middle, for instance). Mutual information (already
used elsewhere in this codebase for a different purpose — the `regime_classifier`
tag, per glossary L286) captures nonlinear dependence generically but has no
direction/CI apparatus as mature as bootstrap-IC today. Nothing stops multiple
edge-measurement statistics from running side by side per feature (Spearman IC
as primary, a nonlinear measure as a secondary screen) — that would be a Stage 2
mechanism *addition*, not a replacement, and nothing in the schema
(`feature_ic_scores`) currently reserves room for a second statistic type per
feature/regime/timeframe cell. Worth a schema note if this is ever pursued.

---

### Stage 3 — Combination / Weighting

**Contract:** many Stage-2-scored features in → one scalar composite score per
bar out. This is where "which features actually matter, and how much" gets
decided.

**What it's called:** `Ensemble`.

**Current mechanism:** IC-Sharpe-weighted linear combination of rank-normalized
feature values, covariance-adjusted via Ledoit-Wolf shrinkage
(`ensemble_alpha.alpha_score`). As of Phase 142A/142B.1, this is explicitly
multi-mechanism by design: `weight_method` is a first-class parameter
(`alpha.ensemble.weight_method`), with `ic_proportional` (v1, live default),
`v1_shrunk` (E1, shrunk-IC input), and `mean_variance` (E2, `Σ⁻¹·IC`) as
concrete alternative mechanisms for the same layer, A/B-judged per (timeframe,
regime) stratum by `ops_ensemble_weight_compare.py`. E3 (hierarchical
partial-pooling) and E4 (per-feature decay half-lives) are specced but not
built. **This is the one layer where "mechanism is swappable, layer contract
isn't" is already operational, not aspirational** — it's the model for how the
other three layers should eventually work if they ever need a second mechanism.

---

### Stage 4 — Emission

**Contract:** a per-bar composite score in → a discrete, timestamped tradeable
event out, only when the score is both large enough and statistically
confident enough to act on.

**What it's called:** "Alpha Emitter."

**Current mechanism:** threshold crossing — `|alpha_score| > threshold[symbol][tf][regime]
AND ci_lower > 0` — writing to `alpha_events`.

---

## The two gaps this doc does not resolve

Two things came up in discussion that don't map onto any layer above, because
no mechanism for them exists yet anywhere in the codebase:

1. **Statistical proof of cross-vector orthogonality.** The `intelligence
   vector` concept (V1 Quant, V3 Macro, V5 Flow, V7 Qual) asserts these are
   "statistically independent by design" — but nothing measures that
   assertion today at the vector level. The closest existing mechanisms
   (`concept_correlation` in the unbuilt Concept Registry design; the
   archived Orthogonality Gate for regime dimensions) are both narrower in
   scope than "prove V1 and V3 don't secretly share information."
2. **Vector orthogonalization / signal cleaning.** No residualization,
   whitening, or decorrelation step exists anywhere in the pipeline. Ledoit-Wolf
   ensemble weighting (Stage 3) re-weights around correlated features; it does
   not clean or transform the features themselves to remove shared variance
   before they're combined.

Both are real design gaps, not naming gaps — they'd need new mechanisms, and
probably a fifth layer (between Stage 0 and Stage 2, operating across vectors
rather than within one) if ever built. Not scoped here; flagged so they don't
get silently assumed solved just because the layer language now exists.

### Sequencing note (2026-07-05) — how this relates to intel-12's gate, and what not to build yet

`intel-12` (Stage 1, StratificationDimension) already has a working three-gate design for
exactly this class of problem — structural redundancy pre-filter → orthogonality study
(Pearson/mutual-information) → substitution test (partial IC) — applied to ~10 candidate
regime dimensions. That gate's *protocol shape* generalizes cleanly to features and vectors.
Its *statistical test* does not: Pearson/MI is a scalar-vs-scalar comparison; "does vector V3
leak into vector V1" is a group-vs-group question needing canonical correlation or a
leakage-regression (predict one vector's columns from the other's, check R²), not a single
correlation coefficient.

Where each level actually stands:
- **Regime dimensions (Stage 1):** fully specified — `intel-12`, gated on Phase 144/145.
- **Features (Stage 0):** has a natural, cheap home once it's needed — `feature_registry`'s
  existing `candidate → active` promotion gate (IC Sharpe + FDR already designed in) just needs
  one more condition added: reject/merge a candidate that's redundant with an already-`active`
  feature. No new infrastructure — this rides `feature_registry`'s migration into
  `concept_registry` (`domain='feature'`), not a separate build.
- **Cross-vector (this doc's two gaps above):** the only level with no home and no consumer —
  only one vector (V1 Quant) exists today, so there is nothing to check against yet.

**Do not build any of this yet.** No real caller exists for a generic orthogonality function
today — `intel-12` isn't built, `concept_registry` isn't built, and v3.1 itself hasn't cleared
its OOS gate (EIC-04 failed 2026-07-03 on data starvation; see `STATE.md`). Building ahead of a
proven consumer risks guessing the wrong shape, same as everything else this milestone has
already had to walk back once. When a real caller does exist: the *compute* (pairwise
correlation, partial-IC) should extend `src/intelligence/statistics/ic_math.py` — the existing
shared home for this codebase's correlation/Fisher-z/CI machinery — not get reimplemented
per domain. The *governance* (gate status, promotion, transition log) stays inside
`concept_registry`, scoped per domain, until at least two real domains are live; `regime_model`
(intel-12) already surfaced a schema gap (per-stratum status, found in the 2026-07-04 cluster
review) that should get fixed from real experience before a second domain's needs are guessed
at too. **Build trigger:** whichever lands first — Phase 144/145, or the Feature Registry →
Concept Registry migration.

---

## Stage summary table

| Stage | Contract | Current mechanism | Swappable? |
|---|---|---|---|
| 0 — Primitive Measurement | bar → scalar vector | `FeatureFactory`, ~61 pure functions | in principle, unlikely to need it |
| 1 — Stratification | vectors → discrete conditioning label | `GaussianHMM` (per-symbol) + cross-sectional VIX×breadth model | yes — real alternatives proposed, archived pending orthogonality proof |
| 2 — Edge Measurement | (feature, label) → predictive statistic + CI | Spearman `IC`, bootstrap CI, IC Sharpe | yes — nonlinear/mutual-information alternatives are a real open question |
| 3 — Combination | many scored features → one composite score | Ledoit-Wolf ensemble; `weight_method ∈ {ic_proportional, v1_shrunk, mean_variance}` | **already multi-mechanism today** — the model for the others |
| 4 — Emission | composite score → discrete event | threshold + CI crossing → `alpha_events` | not currently questioned |
