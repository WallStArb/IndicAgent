# 014 — HMM State Count (K) Selection via BIC

## Problem

`regime_writer.py` hardcodes `n_components=3` (APR key `feature.hmm.n_components`).
Three states produce labels: `trending_up`, `trending_down`, `ranging`. This is a
reasonable prior but has never been validated against the actual ETF data.

K=4 is worth testing. The fourth state would capture transition periods — brief,
high-volatility, low-conviction bars between regimes — which are structurally distinct
from quiet ranging and are empirically where the highest-alpha setups fire. If K=4 wins,
labeling those bars "ranging" today is contaminating the IC engine's regime-segmented
scores with a different distribution.

## Decision Rule

Run BIC across K=2..6 on 4 representative ETFs (SPY, TLT, GLD, EWT) covering
different asset classes and vol regimes. If K=4 wins consistently (>= 3 of 4 ETFs),
fix K=4 universally and add `"transition"` as a fourth canonical label. Do NOT make K
dynamic per-symbol — inconsistent label sets break IC pooling across symbols.

If BIC is ambiguous (different K per ETF), default to K=3 and document the finding.

## Scope

**`scripts/bic_k_selection.py`** (one-time analysis script):
- Load OHLCV for SPY, TLT, GLD, EWT at 5m (most data, most sensitive to K)
- Build same 2D observation matrix as `regime_writer._build_obs_matrix()`
- Fit GaussianHMM(n_components=K, ...) for K in range(2, 7) on each symbol
- Compute BIC = -2 * log_likelihood + n_params * log(n_obs)
  - n_params for diag GaussianHMM: K*(K-1) + 2*K*d (transition + emission means/vars)
- Print BIC table per symbol; plot if matplotlib available
- Output recommendation: fix K at winning value

**If K=4 wins:**
- Add `"transition"` to canonical label set in `regime_writer.py`
- Update `_build_label_map()` to assign 4th state: highest entropy (most uncertain
  alpha vector) → `"transition"`
- Update APR seed `feature.hmm.n_components` from 3 → 4
- Requires full corpus re-run (2.5h with parallelism from todo 013)
- Note in schema docs that `regime` column has 4 valid values

## Why Not Dynamic K Per Symbol

IC engine segments by `regime` string. If SPY has K=4 (has "transition" label) and
BIL has K=3 (no "transition" label), cross-symbol IC pooling breaks and regime
distribution is incomparable. Fixed K is a hard requirement.

## Dependencies

- Todo 013 (parallelism) should ship first — if K changes, re-run is 2.5h not 40h
- Run after current corpus pipeline completes (validate end-to-end first)
