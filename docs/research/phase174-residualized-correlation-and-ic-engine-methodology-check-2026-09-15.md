# Residualized correlation check + why it doesn't gate D-10 (2026-09-15)

**Author:** Claude Sonnet 5, mid-execution of Phase 174, follow-up to
`phase174-single-name-book-correlation-structure-2026-09-15.md`, in response to a design
question from Brandon about whether the raw-correlation diagnostic conflates shared market-beta
co-movement with genuine idiosyncratic redundancy.

## Method

Same 117-symbol cohort and window as the raw-correlation baseline. Regressed each symbol's daily
log return against SPY's daily log return (this project's own `equity_beta` sensitivity-tag
convention: `factor_series='SPY'`, `measurement_type='beta_regression'`, `tag_vocabulary`), via
closed-form single-regressor OLS: `beta = cov(SPY, r_i) / var(SPY)`,
`alpha = mean(r_i) - beta*mean(SPY)`, residual `e_i = r_i - alpha - beta*SPY`. Re-ran the same
correlation-structure statistics on the residual frame.

## Results

| | Raw | Residualized (vs SPY) |
|---|---|---|
| Unconditional avg pairwise corr | 0.3168 | 0.0417 |
| `high_bear` avg pairwise corr | 0.4789 | 0.0334 |
| Unconditional n_eff | 3.10 | 20.05 |
| `high_bear` n_eff | 2.07 | 23.99 |
| Unconditional PC1 share | 33.5% | 11.8% |

Mean fitted SPY beta 0.987 (std 0.366, range 0.358-2.335). Almost all of the raw-correlation
"poor diversification" in the existing book is explained by shared market beta — after removing
one factor, the existing 117-name book already shows ~20 effective independent bets, and
`high_bear` (the worst regime for raw diversification) becomes the *best* regime for residual
diversification, since the beta that drove the raw-correlation spike is exactly what gets removed.

## Why this does NOT become the D-10 gate metric

Checked `services/ic_engine.py` directly rather than assuming either way. IC is computed via
`rankdata(X_raw_block[idx], axis=0)` / `rankdata(X_sub_nd, axis=0)` — `numpy`'s `axis=0` ranks
each feature column across every row in the pooled `(tf, regime)` cell, i.e. across all symbols
AND all timestamps together, not within each timestamp's cross-section separately. `ic_engine`
does not cross-sectionally demean or z-score per timestamp before this ranking step. A common
market-wide move on a given day is therefore NOT automatically netted out of the pooled rank
correlation that becomes IC — raw price/return co-movement between symbols directly pollutes the
realized IC and effective breadth ic_engine measures.

Consequence: raw pairwise correlation (not the SPY-residualized version) is the metric that
actually corresponds to what limits `ic_engine`'s realized effective breadth for this project's
existing methodology. D-10's pre-registered thresholds (≤0.10 unconditional, ≤0.30
`high_bear`-conditioned) therefore stay raw-correlation-based, as originally committed. The
residualized view is retained in `scripts/analysis/universe_expansion_correlation_structure_check.py`'s
output as a reported, non-gating diagnostic — useful for interpreting *why* a cohort is or isn't
correlated, not for the pass/fail decision itself.

## What would change this conclusion

If `ic_engine`'s cross-sectional cell computation is later changed to cross-sectionally
standardize features per timestamp before ranking (a legitimate, separate design question, not
in this phase's scope), the residualized correlation structure would become the more relevant
proxy, and D-10's thresholds would need to be re-derived against a residualized baseline rather
than the raw one documented here.
