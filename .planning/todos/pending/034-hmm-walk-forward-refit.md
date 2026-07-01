---
**Created:** 2026-07-01
**Area:** intelligence
**Type:** bug
**Priority:** P0 — URGENT
**Effort:** 3-5 days
**Benefit:** Removes look-ahead bias baked into every regime-stratified IC score
**Risk:** high if left unfixed (silently overstates alpha); medium effort to fix (requires re-deriving HMM fit windows + full corpus re-run)
**Gate:** none — this is foundational and BLOCKS trusting any regime-stratified result until fixed; must land before Phase 142B

**BLOCKING:** Every `feature_ic_scores` and `alpha_ensemble_ic` row that is regime-stratified is potentially contaminated by this bias right now, in production data. Do not treat any regime-conditional IC/alpha number as ground truth until this is resolved. Phase 142B must not begin (or must be re-run) until this lands.

---

# 034 — HMM regime model: non-causal fit contaminates causal decode

**Priority: P0 URGENT — every regime-stratified IC number downstream inherits this bias, right now, in production**
**Source:** Ultrareview statistical audit, 2026-07-01 (see conversation `session_01Enzn9qcB9KpXHeUaryJVfX` origin thread)

---

## Problem

`services/regime_writer.py:437` calls `model.fit(obs_matrix)` on the **entire** (symbol, tf) history in one batch call before the causal alpha-pass decode (`_alpha_pass_jit`, line 493) runs. The decode itself is genuinely causal — a forward-filter only, no Viterbi/smoothing (confirmed at lines 248-277; the docstring explicitly rejects `model.predict()`).

But the *emission means, covariances, and transition matrix* baked into the fitted `GaussianHMM` were estimated using data from the entire corpus, including bars far in the future relative to any early timestamp being labeled. Regime labels at t=100 are therefore influenced by the statistical structure of data through t=end.

Since `feature_ic_scores` and `alpha_ensemble_ic` (Phase 142A) are stratified by these regime labels, any regime-conditional IC computed on early-history bars carries indirect information about future regime structure — a subtle but real form of look-ahead bias. This is distinct from (and not fixed by) the causal decode framing; the decode being causal only means the label *assignment* at each t doesn't see future bars, not that the *model doing the assigning* was estimated without them.

This is the single largest risk of silently overstating regime-stratified alpha in the current pipeline, since it affects every regime-gated table downstream (`feature_ic_scores`, `alpha_ensemble_ic`, and any Phase 142B counterfactual scoring that stratifies on regime).

## Fix

Refit the HMM on an expanding or rolling window, not the full corpus, so that at any timestamp t the model parameters used to label t were estimated only on data <= t (or <= t - embargo, matching the walk-forward embargo pattern already used in `ic_engine.py`).

Two viable approaches, in order of rigor:

**Option A — Periodic refit (recommended first pass):** Refit the HMM at a fixed cadence (e.g. every N trading days or every full corpus re-run), always training only on data up to the refit date, and only use that fit to label bars *forward* from the refit date until the next refit. This mirrors how the model would actually be run in production (no access to future data at decision time) and is the natural walk-forward analog of `ic_engine.py`'s expanding-window folds.

**Option B — True expanding-window fit per label (most rigorous, most expensive):** Refit before every label — computationally prohibitive at current corpus scale (58 symbols x 4 TFs x tens of millions of bars); likely not practical without approximation (e.g. incremental/online HMM parameter updates).

Start with Option A. Validate the practical impact first: re-run regime labeling with periodic refit on one symbol/TF (e.g. SPY 1h) and compare regime-stratified IC before/after — if the shift is negligible, the bias is small in practice and this can be deprioritized; if IC materially changes, this must land before any regime-stratified result (including Phase 142A/142B) is trusted.

## Secondary finding bundled here

**No seed-stability check on HMM fits** (`services/regime_writer.py:822`, `HMM_RANDOM_STATE=42` fixed via APR `alpha.hmm.random_state`). The retry-on-non-convergence path (lines 442-465) reuses the same seed on retry rather than testing whether regime labels / log-likelihood are stable across different random inits. A model that only converges to a good BIC/log-likelihood under one particular seed produces brittle regime labels without anyone knowing. When doing the Option A refit work, add a cheap seed-stability check (e.g. fit with 3-5 seeds, compare log-likelihood spread and label agreement) as part of the same effort — same file, same validation harness.

## Scope

- `services/regime_writer.py` — refit cadence logic, embargo-consistent training window
- Full corpus re-run required after this change (regime labels shift corpus-wide, same class of change as the Phase A ic_engine methodology fixes)
- Should land before Phase 142B trusts regime-stratified counterfactual scoring
