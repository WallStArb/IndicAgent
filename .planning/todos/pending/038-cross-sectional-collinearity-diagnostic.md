# Cross-sectional feature collinearity diagnostic (variance-concentration vs IC)

**Found:** 2026-07-01, from a question about whether rolling PCA / eigenvector variance
monitoring should gate the HMM inputs.

**Cross-reference (2026-07-12, housekeeping audit; todo 076 folded into `docs/research/
stratification-dimension-unification.md` 2026-07-13, link updated):** that doc's "Correlation
regime" candidate dimension computes a related rolling cross-sectional correlation/co-movement
structure over the same universe, for a different end-use (stratification dimension vs. this
todo's collinearity-risk diagnostic). Not a duplicate — different purposes — but whoever builds
either should check the other first for a shareable underlying correlation-matrix computation.

## Renaissance-grade reasoning

The failure mode worth guarding against is real: feature collinearity across the
cross-sectional universe (58 ETFs feeding `market_regimes` / Feature Factory) compresses
effective dimensionality, and regime separation degrades — this is precisely what happens
when correlations spike during stress (diversification breaking down), so it's also a
signal worth detecting, not just a risk to suppress.

It does **not** belong on the per-symbol HMM obs vector in `regime_writer.py` (log_return,
realized_vol, momentum, vol_of_vol, rel_volume). That 5D vector is deliberately constructed
with distinct economic content and some correlation by design (momentum is a scaled
log-return). A rolling PCA gate there with an arbitrary "top-3 eigenvectors < 75%" threshold
would false-positive constantly and has no demonstrated link to IC — exactly the kind of
unjustified complexity to cut. Don't build it there.

Where it's legitimate: the cross-sectional feature set. But per the project's own bar
("earn promotion through proof — p<0.05, sufficient N"), the metric must prove itself
against `feature_ic_scores` before it becomes a live gate. Building the gating mechanism
first, based on intuition about what "should" degrade IC, is the same architecture
violation as any other unproven complexity in this codebase.

## Action (sequenced, gate-then-prove, not prove-then-gate)

1. **Instrument only, no gate.** Compute an effective-rank / top-k eigenvalue variance-share
   metric on the rolling correlation matrix of the cross-sectional feature set (the inputs
   to `equity_regime_model.py` / Feature Factory, not the per-symbol HMM obs vector). Log it
   per timestamp; do not act on it yet.
2. **Correlate historically.** Join the logged metric against `feature_ic_scores` over the
   existing corpus. Test whether variance concentration in the feature space actually
   precedes/predicts IC degradation, or whether it's noise uncorrelated with realized IC.
3. **Only promote to a gate if it survives that test** (p<0.05, sufficient N — same bar as
   every other promotion in this codebase, e.g. shadow_registry's `n >= 100 AND
   bootstrap_ci_lower(pnl_r) > 0.0`).
4. **APR from the start.** Any threshold ("75%", window length, top-k) is a `config_state`
   key under `feature.collinearity.*` (e.g. `feature.collinearity.pca_variance_threshold`,
   `feature.collinearity.window`), never hardcoded. Provenance tag is `[rca_analysis]` only
   after step 2/3 establish the relationship — not before, since it isn't yet an
   RCA-derived value.

**Blocked on:** nothing — can be scoped as a phase whenever cross-sectional IC work is next
picked up. Not urgent; this is a diagnostic-quality improvement, not a bug fix.
