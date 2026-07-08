# 164 — Ensemble combination E-candidate queue (posterior blending, HRP-lite, Bayesian averaging, trailing-IC)

**Source:** `docs/research/fable-2026-07-07-renaissance-layer-refinements.md` §8 (L5-1 through
L5-4), executive summary item 5.
**Priority:** L5-1 highest-conviction (testable now, zero new data); L5-2 next; L5-3/L5-4 gated.
**Gate:** E1 (shrunk-IC) and E2 (mean-variance Σ⁻¹·IC) are already built (Phase 142B.1). These are
candidates for the E4+ queue, all expressible as `weight_version` variants judged by the existing
`ops_ensemble_weight_compare.py` A/B machinery, all inside the one-model-one-book invariant.

## L5-1 — Regime-posterior soft blending (highest-conviction E-candidate)

Today: `alpha_score(bar) = w[regime_label(bar)] · features(bar)` with hard argmax labels. The
HMM's own posteriors are often 55/45 and the system already stores them
(`hmm_prob_trending_up/ranging/trending_down`, `hmm_entropy`, Phase 143's `hmm_churn`). Proposal:
`alpha_score = Σ_r P(r|bar) · (w_r · features)`. Removes the alpha discontinuity at every
boundary crossing (today manufactures emission churn from label noise), degrades gracefully
exactly where the Phase 144 conditioning decision worries labels are weakest, uses zero new data.
Cross-sectional strata get the analogous treatment from `market_regimes.regime_prob_vector`
(already JSONB). One new `weight_version`, judged per-stratum by the existing D-10 win rule; zero
new parameters; a scoring-path change in `ensemble_trainer`/`alpha_publisher` behind a variant
flag, no new tables.

## L5-2 — Hierarchical family-then-feature allocation (HRP-lite)

The 152-feature registry is family-imbalanced (31 vol vs 3 macro), and `cluster_deflate_weights`
caps only pairwise-correlated clusters — a family of 31 moderately-correlated features can still
absorb outsized total weight through sheer population. Allocate across families first (by
family-level aggregate IC Sharpe), then within family — weak-signal diversification applied at
the family grain, structurally preventing "the ensemble is secretly one volatility bet." Tree
given by `feature_registry.group_name` (cheaper, stabler, no estimation risk vs. an estimated
dendrogram). A pure function in `src/intelligence/ensemble/weights.py` + a variant flag; compare
realized `effective_n` and family weight-share concentration between variants.

## L5-3 — Bayesian averaging over variants instead of champion selection (gated on 3+ variants)

Champion selection per stratum is strong-signal concentration at the meta level, with the
winner's-curse bias todo 153 documents. Once 3+ variants exist, blend variants with weights
proportional to accumulated evidence (todo 163's e-values slot in naturally as unnormalized
evidence weights). No single variant needs to be right; regime-varying variant quality handled
automatically. Just another `weight_version` in the A/B framework — if the blend can't beat its
own best constituent OOS, averaging loses and champion selection stands.

## L5-4 — Trailing-IC adaptive weighting (gated on P1)

Exponentially-weighted trailing IC as the weighter input — blocked on P1 (trailing IC series,
`measurement-ic-engine.md`), which doesn't exist yet. Queue explicitly behind P1 rather than
letting it float. Design constraint to pre-commit: decay half-life must be an APR key calibrated
against measured feature decay curves (Phase 143's monitors), not chosen by eye. Note
`measurement-ic-engine.md` OQ8: trailing/vintage/shrunk are three competing recency mechanisms —
a composition decision is required before more than one feeds the weighter.
