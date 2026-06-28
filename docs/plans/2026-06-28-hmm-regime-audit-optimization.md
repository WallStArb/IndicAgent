# HMM Regime Audit & Optimization Plan

Date: 2026-06-28
Status: OPEN

Covers both the per-symbol HMM (`services/regime_writer.py`) and the cross-sectional regime model (`services/equity_regime_model.py`). Findings are ranked by impact; correctness bugs first, then model quality, then calibration.

---

## What We Got Right

- Causal decoding via forward-filter alpha-pass only (no Viterbi) -- correct and non-obvious
- 5D observation vector: log_return + realized_vol + momentum + vol_of_vol + rel_volume
- K=5 BIC-validated (Phase 140.5-P2, 2026-06-26)
- StandardScaler applied before HMM fit
- Diagonal covariance -- defensible given data volume
- Label assignment by emission mean[:,0] -- deterministic across re-trains
- APR-backed random state (`alpha.hmm.random_state=42`)

---

## Gaps

### P1 - Correctness (Fix Immediately)

**1. Expanding rank for cross-sectional VIX proxy**
- File: `services/equity_regime_model.py:175`
- Issue: `vix_z.rank(pct=True)` ranks each bar against the full corpus including future observations. A bar from 2010 is percentile-ranked against vol from 2010-2026. This is look-ahead bias in the training data.
- Fix: `vix_z.expanding().rank(pct=True)` -- one-line change, removes the bias.

**2. TF-normalized windows for VIX z-score and breadth**
- File: `services/equity_regime_model.py:75-76`
- Issue: `_REALIZED_VOL_WINDOW = 20`, `_VIX_Z_WINDOW = 252`, `_MA_WINDOW = 200` are bar counts. At 5m these are ~100 minutes, ~21 hours, ~16 hours respectively. At 1d they are 1 month, 1 year, 200 days. The signals have completely different economic meaning across TFs.
- Fix: Define windows in trading periods per day per TF and derive bar counts. E.g., at 5m there are 78 bars/day; `_VIX_Z_WINDOW` should be `252 * bars_per_day`. APR keys: `alpha.regime.vix_window_days`, `alpha.regime.ma_window_days`, `alpha.regime.rv_window_days`.

### P2 - Model Quality

**3. Single HMM initialization -- local optima risk**
- File: `services/regime_writer.py:377-383`
- Issue: `GaussianHMM` EM is non-convex. We run one initialization (random_state=42) and accept whatever local optimum EM finds. Different initializations can produce meaningfully different models.
- Fix: Run N restarts (APR: `feature.hmm.n_restarts`, default 5). Fit each with a different seed derived from `hmm_random_state + i`. Select the model with the highest `model.score(obs_matrix)` (total log-likelihood). This is the standard approach in hmmlearn.

**4. No degenerate model detection**
- File: `services/regime_writer.py:439`
- Issue: `model.monitor_.converged` can be True for degenerate solutions where one state captures >90% of observations. We write these results without flagging them.
- Fix: After fitting, compute state occupation fractions from Viterbi or alpha-pass. If any state has < `feature.hmm.min_state_occupation` (default 0.05), log a warning and skip writing. This prevents silent garbage regime labels from entering feature_vectors.

**5. No regime stability metric -- churn detection missing**
- Files: `services/regime_writer.py:406-423`
- Issue: We compute `hmm_entropy` and `hmm_duration` but don't flag rapid label flipping (high-churn bars). A symbol oscillating trending_up/trending_down every few bars is not in a real regime -- it's sitting on a decision boundary.
- Fix: Add `hmm_churn` column to feature_vectors: rolling N-bar label-change rate (e.g., fraction of prior 10 bars where regime changed). High churn should be treated as low-confidence regime assignment in IC stratification. APR key: `feature.hmm.churn_window`.

**6. No cross-TF coherence enforcement**
- Issue: Each (symbol, tf) HMM is fully independent. A 1d `trending_up` can coexist with a 15m `trending_down` with no reconciliation. Multi-scale regime coherence is informative.
- Fix (Phase 2): Add a cross-TF coherence feature in the IC engine -- e.g., `regime_tf_agreement` boolean capturing whether the 5m and 1h labels agree directionally. Not a change to regime_writer; a derived feature in feature construction.

### P3 - Calibration

**7. Hard cross-sectional thresholds never empirically validated**
- File: `services/equity_regime_model.py:327-330`
- Issue: vix_low/high_pct=0.33/0.67 and breadth_bear/bull=0.40/0.60 are `[initial_estimate]` and have never been validated against IC distributions. The question is whether IC actually differs meaningfully between adjacent regime buckets at these cut points.
- Fix: After running IC engine, query `feature_ic_scores` grouped by `regime_label` and plot IC mean/std per bucket. Run a grid search over threshold pairs and select the partition that maximizes regime-to-regime IC divergence. Update APR with `[empirical]` provenance.

**8. No EM log-likelihood tracking**
- Issue: We don't log the final training log-likelihood per (symbol, tf). This makes it impossible to compare model quality across symbols or detect degraded fits.
- Fix: Log `model.monitor_.history[-1]` (final EM log-likelihood) and `model.score(obs_matrix)` (per-observation log-likelihood) per (symbol, tf) cell. Store in a diagnostics table or structured log for trend monitoring.

### P0 - Performance (Blocking for Full Corpus)

**0. `_causal_decode` forward-filter is a Python loop over 116M passes (todo 007)**
- File: `services/regime_writer.py:190-253`
- Issue: 58 symbols × 4 TFs × 500K+ bars = ~116M forward-filter iterations. The sequential `for t in range(n)` loop in `_causal_decode` is pure Python (numpy ops per iteration, but Python loop overhead at 116M scale). Current runtime: 20+ hours with 12 workers.
- Fix: Numba JIT the forward-filter. Keep `hmmlearn.GaussianHMM` for fitting (fast, one-time). Replace inference path with `@jit(nopython=True, parallel=True, cache=True)` forward filter in `src/intelligence/hmm_jit.py`. Extract trained parameters from hmmlearn after fit, pass to JIT filter. Estimated runtime: ~30 min (40x speedup).
- Gate: After corpus pipeline stabilizes and K=5 labels validated. `numba` added to `pyproject.toml`.
- APR: none needed (pure performance change).

---

### P4 - Future / Phase 2

**9. Rolling HMM refit to eliminate parameter look-ahead bias (todo 023)**
- File: `services/regime_writer.py` -- `_compute_symbol_tf()`
- Issue: HMM is fit on full available history then causally decoded. The forward-filter is correct, but emission parameters and transition matrix were estimated using future data relative to any training bar. This is parameter look-ahead bias distinct from the causal decoding issue.
- Option A: Growing window refit -- fit on all data up to bar T, decode only bar T. True walk-forward. ~N fits per (symbol, tf). Prohibitively slow at scale.
- Option B: Fixed 3-year rolling window, annual step. ~15 fits per cell, ~3,480 total fits. Estimated 3-6 hours even with workers. **Recommended.**
- Gate: Requires Numba JIT (P0) first to be feasible. Full corpus re-run required after. APR keys: `alpha.hmm.rolling_window_bars`, `alpha.hmm.rolling_step_bars`.

**10. Scaler look-ahead in per-symbol HMM**
- File: `services/regime_writer.py:375`
- Issue: `scaler.fit_transform(obs_matrix)` uses full-history statistics to normalize early bars. This is a subtle look-ahead bias. For a batch historical corpus the impact is small (scaler is approximately stationary over long horizons) but it is not strictly causal.
- Fix: Expanding StandardScaler -- fit on obs[0:t] for each t, transform obs[t]. Expensive but correct. Defer until the simpler fixes are validated.

**11. Per-symbol HMMs ignore cross-asset correlation**
- Issue: SPY and QQQ regimes are ~90% correlated but are fit completely independently. A panel HMM or shared latent factor would use cross-asset information to improve state estimation.
- Fix: Probabilistic: low value for single-name regime labeling (correlations are already captured by the cross-sectional model). Defer indefinitely unless IC validation shows strong residual signal.

---

## Implementation Order

```
P0:  Numba JIT forward-filter (regime_writer.py + hmm_jit.py) -- unblocks full corpus
P1a: Expanding VIX rank (equity_regime_model.py:175) -- 1 line, run today
P1b: TF-normalized windows (equity_regime_model.py) -- APR + per-TF window mapping
P2a: HMM restarts (regime_writer.py) -- APR n_restarts, loop + score selection
P2b: Degenerate model detection (regime_writer.py) -- occupation fraction check
P2c: Churn feature (regime_writer.py + schema migration) -- new hmm_churn column
P3:  Threshold calibration (post IC-engine data) -- analysis then APR update
P4a: Rolling HMM refit / parameter look-ahead fix (requires P0 first)
P4b: Expanding scaler -- after P4a validated
```

---

## Files Changed

- `services/equity_regime_model.py` -- P1a, P1b
- `services/regime_writer.py` -- P2a, P2b, P2c
- Schema migration -- add `feature_vectors.hmm_churn` (P2c)
- APR migrations -- new keys for `alpha.regime.vix_window_days`, `alpha.regime.ma_window_days`, `alpha.regime.rv_window_days`, `feature.hmm.n_restarts`, `feature.hmm.min_state_occupation`, `feature.hmm.churn_window`
