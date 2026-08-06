# 080 — Ensemble combination E-candidate queue (posterior blending, HRP-lite, Bayesian averaging, trailing-IC)

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

**Correction 2026-08-02: the cross-sectional-strata claim above does not hold, per
`docs/plans/2026-07-15-regime-boundary-churn-diagnostic-design.md`'s own Context section**
(this todo's Phase 0 prerequisite, written to design the diagnostic that must run before L5-1
is built). That doc traced `cross_sectional_regime_model.py`'s `_assign_labels` directly:
`market_regimes.regime_prob_vector` is `{sig1_key: sig1_value, sig2_key: sig2_value}` — the
raw signals that fed hard-threshold bucketing, **not a probability distribution over labels.**
There is no `P(regime|bar)` to consume for cross-sectional strata; "the analogous treatment"
does not exist without inventing one (a real design task, not "already JSONB"). The per-symbol
HMM side (`hmm_prob_*`) is unaffected by this correction — those genuinely are posteriors.

**Sequencing dependency, also 2026-08-02:** `docs/plans/2026-08-02-regime-label-transition-quality-measurement-design.md`
(todo 005) investigates the same `_bucket()`/`_assign_labels()` hard-threshold mechanics from
a different angle — IC measurement contamination, not scoring churn. If todo 005's diagnostic
finds combined-label smoothing worth implementing at the source, that independently reduces
the label flicker feeding this todo's boundary-churn question too. **Run todo 005 first.**
Running this todo's Phase 0 diagnostic (`scripts/analysis/regime_boundary_churn_check.py`,
built and tested, never executed) against today's unsmoothed labels risks a materiality
reading inflated by flicker that todo 005 might independently eliminate — re-run this
diagnostic after todo 005 resolves, don't trust a pre-005 result as final.

One new `weight_version`, judged per-stratum by the existing D-10 win rule; zero new
parameters; a scoring-path change in `ensemble_trainer`/`alpha_publisher` behind a variant
flag, no new tables. Cross-sectional-strata soft-blending scope is now open (needs its own
posterior-construction design, not a free reuse of `regime_prob_vector`) rather than the
"zero new data" claim originally stated.

## L5-2 — Hierarchical family-then-feature allocation (HRP-lite)

**Evidence refreshed 2026-08-05 (this section was stale — "152-feature registry" and "31 vol vs
3 macro" both predate Phase 151, which alone added 43 columns).** Live `feature_registry`
(292 rows, all `added_phase` through 151) `group_name` distribution:

```
structure: 72   session: 62   volatility: 36   volume: 34
calendar: 30    momentum: 19  macro: 12        regime: 10
cross_tf: 6     oscillator: 6 control: 5
```

The imbalance is real and, if anything, more dramatic than the stale numbers implied —
`structure` + `session` alone are 134 of 292 fields (46%) — but the original "31 vol vs 3
macro" framing no longer matches reality and should not be cited as the motivating example
going forward. `cluster_deflate_weights` still only caps pairwise-correlated clusters, so a
72-member family can still absorb outsized total weight through sheer population regardless of
pairwise correlation — the structural gap this candidate addresses is unchanged, just needs
re-derivation against current group sizes before being written up as a real plan.

**New open question, did not exist when this was last substantively written (2026-08-02):**
"Tree given by `feature_registry.group_name`" is no longer a safe anchor as stated.
`concept_registry` (domain='feature') already has its own `group_name` column (confirmed live,
`concept_registry_group_name_idx`), and todo 118 (P1, "migrate feature_registry into
concept_registry ASAP, don't leave two governance systems running in parallel") is being
executed RIGHT NOW by Phase 170, a separate concurrent session
(`.planning/STATE.md`: "Phase 170 ... running in a separate, concurrent session as of
2026-08-04"). Building L5-2's family tree on `feature_registry.group_name` today risks building
on a table mid-retirement — if Phase 170 merges while L5-2 is in flight, the family tree's
source of truth moves out from under it. **Sequence L5-2 behind Phase 170's merge**, same
discipline already applied elsewhere in this backlog to avoid two overlapping migration-scale
efforts running at once (matches the corpus-recompute sequencing pattern). Once Phase 170
lands, re-derive the group_name distribution above against `concept_registry` instead of
`feature_registry` before starting design.

E1/E2 mechanism claims re-verified 2026-08-05, still accurate: `mean_variance_weights` (E2)
exists in `src/intelligence/ensemble/weights.py`, `scripts/ops/alpha/ops_ensemble_weight_compare.py`
exists as the A/B judge this candidate would use.

Original scoping (still the right shape, just needs the anchor question resolved first):
allocate across families first (by family-level aggregate IC Sharpe), then within family — weak-
signal diversification applied at the family grain, structurally preventing "the ensemble is
secretly one [structure/session] bet." A pure function in `src/intelligence/ensemble/weights.py`
+ a variant flag; compare realized `effective_n` and family weight-share concentration between
variants.

## L5-3 — Bayesian averaging over variants instead of champion selection (gated on 3+ variants)

Champion selection per stratum is strong-signal concentration at the meta level, with the
winner's-curse bias todo 069 documents. Once 3+ variants exist, blend variants with weights
proportional to accumulated evidence (todo 079's e-values slot in naturally as unnormalized
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
