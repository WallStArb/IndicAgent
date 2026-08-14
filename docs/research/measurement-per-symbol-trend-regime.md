# Per-Symbol Trend Regime — Idea (Hurst / autocorrelation-sign re-test)

**Status:** Pre-registered 2026-08-12. Stage 1 (mechanism build + validation) already run and
PASSED under an earlier ad hoc pass; this doc formalizes the design that must govern Stage 2/3,
written before either runs. Stage 2 (Gate 0/1 re-examination) not started. Stage 3
(falsification) not started.
**Author:** Claude (Sonnet 5), interactive session, 2026-08-12 — not a Fable dispatch.
**Origin:** [todo 303](../../.planning/todos/pending/303-per-symbol-trend-regime-null-arm-tested-candidate.md).
Phase 171/172 (2026-08-08/09) found via a null-arm control that the incumbent per-symbol HMM's
K=5 `regime` labels — despite being named `trending_up`/`ranging`/`trending_down` — empirically
separate on volatility, not trend (see `docs/research/stratification-dimension-unification.md`
item 14). That falsifies the premise that killed Hurst/autocorrelation-sign at Gate 0
originally: they were rejected as redundant with the HMM's assumed trend-capture, and the HMM
never actually captured trend. The rejection is worth re-running against current evidence, not
repeating from the stale premise.
**Companion to:** `docs/research/stratification-dimension-unification.md` (candidate table,
"Explicitly rejected" section and Reconciliation pass item 15) and
[todo 304](../../.planning/todos/pending/304-per-symbol-percentile-rank-candidates-volume-skew-volatility.md)
(same session, disjoint mechanism family — percentile-rank, not Hurst/autocorrelation — same
blocker).

---

## The core point

No validated per-symbol trend axis exists in this codebase today. Test, with fresh adversarial
rigor, whether a cheap trend proxy (Hurst exponent or lag-1 autocorrelation sign) sharpens IC
beyond what `regime_volatility` (the correct, null-arm-validated volatility partition) already
provides. This is a re-test of a candidate previously killed on a premise this project's own
later work disproved — not a new idea, but not free of the burden of proof either. Gate 0's
free structural-redundancy rejection no longer applies; the candidate now has to clear Gate 1
(orthogonality) and Gate 2 (substitution test) like any other, plus the standing null-arm
control this class of failure earned.

**Comparison bar**: `feature_vectors.regime_volatility` (K=3, calm/elevated/turbulent) — the
live, `ic_engine.py`-gating stratification axis. Not `feature_vectors.regime` (K=5 legacy) —
that column is still written but no longer read by anything downstream, and comparing against a
mislabeled axis would be comparing against nothing.

## Why the Gate 0 rejection needs re-examination, not repetition

The original rejection reasoning: Hurst/autocorrelation-sign are direct proxies for
`momentum`/`vol_of_vol`, two of the incumbent HMM's five observation dimensions, so a separate
trend axis on top of a label already conditioned on them would double-count the same dynamic.
That argument is only valid if the HMM's labels actually separate on trend. Phase 171/172's
null-arm control proved they don't — the K=5 labels are empirically a volatility partition with
a misleading name. The redundancy premise is gone; what remains is an open, untested hypothesis,
not a settled rejection.

## Staged design

**Stage 1 — Mechanism build + validation (done, ad hoc pass — this doc formalizes it
retroactively).** `scripts/analysis/per_symbol_trend_candidates_stage1_pilot.py`. Two candidates,
both raw measures rolled through the same rolling-z-score-then-causal-expanding-rank template as
`vix_pct`/`volatility_pct` (`causal_rank.py::causal_expanding_rank`), never a raw value or
whole-series `pandas.rank()` used directly for bucketing:

1. **Hurst exponent** — classic single-scale rescaled-range (R/S) estimator,
   `H = log(R/S) / log(n)`, rolling window of 60 daily bars over log returns. A simple estimator,
   not the full multi-scale regression version production code would eventually want, but
   adequate for causality/non-degeneracy validation.
2. **Lag-1 autocorrelation** — rolling window of 20 daily bars, lag 1, over log returns.

Both raw series pass through a rolling z-score (60-day window) then `causal_expanding_rank`
before use, identical mechanism to `volatility_pct`/`skew_tail`/`volume_pct` (todo 304's
sibling), for consistency and because even a naturally-bounded statistic (Hurst in [0,1],
autocorrelation in [-1,1]) can still drift in its own baseline level across market eras.

Sample: SPY, AAPL, XOM, JPM, TLT (index, tech, energy, financial, bonds) — a mechanism check,
not a corpus-wide measurement.

**Stage 2 — Re-examine the Gate 0 rejection via orthogonality study.** Same protocol as the
stratification doc's Gate 1: Pearson correlation on the continuous rank/z-score, or normalized
mutual information on discretized labels, between each candidate (`hurst_rank`, `autocorr_rank`)
and `regime_volatility`. Gate: below `alpha.regime_stratification.max_correlation` (APR key, no
default asserted until this study runs — first measurement, not a guessed constant). **Data
dependency: `feature_vectors.regime_volatility` populated** — gated on the concurrent corpus
pipeline's `regime_writer` step (step 2 of `ops_corpus_pipeline_run.sh`) finishing. Do not read
`regime_volatility` for this study while that step is still writing — a partial, in-flight
column would give a stale/inconsistent cross-symbol read, the same shape of hazard the
orchestrator's own `check_regime_consistency` gate exists to catch for full-pipeline runs.

**Stage 3 — Falsification bar + mandatory null-arm control.** Same protocol as the
stratification doc's Gate 2 (substitution test):

```
IC_partial = Corr(X_bar, Y_forward | S_candidate)
```

- Query IC stratified by `(regime_volatility, candidate_rank)` joint cells on the 5 sample
  symbols first — never commit to a full-corpus run on an unvalidated candidate.
- **Pass criterion:** IC Sharpe increases by more than 10% in at least one joint cell, with
  N > 20,000 bars in that cell.
- **Data dependency: `feature_ic_scores`** — gated on `ic_engine` (step 5), the same step that
  gates `statistical_factor_residual`'s Stage 3.

**The null-arm control (mandatory, pre-registered here before any Stage 3 run — no separation
number gets cited as real evidence without clearing this first):**

Mirrors the null arm already validated in this codebase for exactly this failure shape
(`scripts/analysis/hmm_candidate_regime_axes_identifiability_sweep.py`'s "THE NULL ARM" section,
the mechanism that caught Phase 171/172's mislabeling): **per-symbol IID time-permutation.**

- For each of the 5 sample symbols, independently permute the order of that symbol's own daily
  log-return series (`numpy.random.default_rng` with a fixed seed per replicate) — this destroys
  all temporal/trend structure while preserving the exact unconditional marginal distribution
  (same mean, variance, skew, kurtosis).
- Recompute the candidate label series (Hurst or autocorrelation, same rolling windows, same
  rank transform) on the permuted series, then recompute the same joint-cell IC Sharpe uplift
  statistic used in the real run.
- Repeat for **200 replicates** (matching `alpha_score_residual_diagnostic_15m.py`'s
  `null_shuffles` convention, the existing shuffled-null-p pattern in this codebase).
- **Null p-value:** fraction of the 200 null replicates whose IC Sharpe uplift meets or exceeds
  the real (unpermuted) uplift. **Pass requires null p < 0.05** — the real-arm separation must
  sit outside the top 5% of what pure noise with the same marginal distribution produces, not
  merely be numerically positive.
- Both candidates (Hurst, autocorrelation) get their own independent null-arm run — a pass on
  one does not license skipping the control on the other.

This control exists specifically because Hurst/autocorrelation-sign are the *same kind of risk*
Phase 171/172 already caught once: a statistic that looks like it's separating on the thing it's
named for, but is actually fitting to noise or an artifact of the rank transform's own boundary
behavior. The null arm is what turns "the number is positive" into "the number means something."

## Reuse plan — what's new vs. existing primitives

| Need | Source |
|---|---|
| Causal expanding rank | `src/intelligence/regime_signals/causal_rank.py::causal_expanding_rank` (pure function, no DB, directly reusable) |
| Raw OHLCV fetch | Same query pattern as `scripts/analysis/per_symbol_regime_candidates_stage1_pilot.py` (`market_data_ohlcv_tradeable`) |
| Day-clustered bootstrap CI (Stage 3) | `src/intelligence/statistics/ic_math.py::_circular_block_bootstrap_ic` |
| BH-FDR (Stage 3) | `src/intelligence/statistics/ic_math.py::apply_bh_fdr` |
| Orthogonality correlation (Stage 2) | New, small — Pearson/mutual-info on already-computed rank series (same primitive todo 304's Stage 2 needs; write once, share) |
| Null-arm time-permutation harness | New, but mirrors `hmm_candidate_regime_axes_identifiability_sweep.py`'s existing null-arm shuffle pattern and `alpha_score_residual_diagnostic_15m.py`'s `_shuffled_null_p` percentile-test pattern — no new statistical machinery invented |

## Promotion boundary

A PASS at Stage 3 (including the null-arm control) does not auto-promote to a production
per-symbol trend provider. That is Step 3 in todo 303's own plan — scoping what a
`regime_writer.py`-hosted trend dimension would look like, with its own BIC-selected K (the
stratification doc's own caveat: "K=5" is a naive placeholder for the incumbent's price/vol
observation space specifically, not a settled count for any new fitted dimension) — a separate,
later decision, not bundled into this candidate's falsification.

## Result — Stage 1 (mechanism build + validation), run 2026-08-12

**Clean pass.** 5 symbols (SPY/AAPL/XOM/JPM/TLT) × 2 candidates = 10 checks:

- **Causality: 10/10 PASS**, `0.00e+00` truncated-vs-full diff on every candidate/symbol pair —
  zero look-ahead, confirmed not assumed.
- **Distribution: non-degenerate on all 10** — rank `std` 0.285–0.298, matching the theoretical
  uniform[0,1] value (`1/sqrt(12) ≈ 0.289`) tightly.
- **Side observation, not a finding** (no IC touched): raw Hurst averaged 0.51–0.52 across all 5
  symbols (barely above the random-walk midpoint of 0.5 — very mild persistence at this
  window/scale); raw lag-1 autocorrelation averaged slightly negative (-0.03 to -0.09) across all
  5, consistent with short-horizon mean-reversion microstructure (bid-ask bounce and similar)
  rather than strong trending. Interesting context for Stage 3, not evidence of anything yet.

**Stage 2 and Stage 3 code both built 2026-08-14, neither run yet** — both gated on
`regime_writer`'s `regime_volatility` pass finishing (in progress as of this writing).
`per_symbol_regime_candidates_stage2_orthogonality.py` (shared with todo 304) and
`per_symbol_regime_candidates_stage3_falsification.py` (also shared with todo 304, 16 unit
tests on synthetic data, all green). **Correction to this doc's own Stage 3 spec above**: the
`N > 20,000 bars` pass criterion is a full-corpus/intraday-scale threshold, unreachable at a
5-symbol/1d probe (tops out in the low hundreds per cell) — Stage 3 runs at 5m/15m instead
(never 1m), where real bar counts clear the gate. Does NOT need `ic_engine`/`feature_ic_scores`
after all — only `forward_returns` and `feature_vectors.momentum_z_fast`/`momentum_z_mid`
(already-populated pipeline stages), both read directly rather than through `ic_engine`'s
corpus-wide machinery. See the script's own docstring for the full corrected design.

## References

- `docs/research/stratification-dimension-unification.md` — candidate table, Gate 0/1/2
  protocol, the item-14/15 reconciliation entries this doc's origin traces to
- `docs/research/measurement-per-symbol-percentile-rank-candidates.md` — sibling candidate
  (todo 304), same blocker, disjoint mechanism family
- `scripts/analysis/hmm_candidate_regime_axes_identifiability_sweep.py` — null-arm precedent
  this doc's control mirrors
- `scripts/analysis/alpha_score_residual_diagnostic_15m.py` — shuffled-null-p percentile-test
  pattern this doc's null-arm decision rule mirrors
- `src/intelligence/statistics/ic_math.py` — reused statistical primitives (Stage 3)
