# HMM Observation Vector Design

**Status:** Live (5D vector, v2.10 HMM improvement plan, 2026-06-25)
**Owner:** regime_writer.py `_build_obs_matrix()`

---

## Current Vector (5D)

| Dim | Feature | Formula | Window |
|---|---|---|---|
| 0 | `log_return` | `ln(close[t] / close[t-1])` | 1 bar |
| 1 | `realized_vol` | rolling std of log_returns | `vol_window` (APR: `feature.hmm.obs_vol_window`) |
| 2 | `momentum` | `sum(log_returns[-W:]) / realized_vol` | `momentum_window` (APR: `feature.hmm.obs_momentum_window`) |
| 3 | `vol_of_vol` | rolling std of `realized_vol` | `vol_of_vol_window` (APR: `feature.hmm.obs_vol_of_vol_window`) |
| 4 | `rel_volume` | `log(volume[t]) - rolling_mean(log(volume))` | same as `vol_window` |

All windows default to 20 bars. Each column is StandardScaler-normalized before fitting. Covariance type is `diag`.

---

## Design Philosophy

The HMM observation vector should answer: **what market microstate am I in right now?**

The goal is NOT feature engineering for prediction. The vector defines the latent space the HMM carves into K regimes. Criteria for inclusion:

1. **Causal** -- computed from t and earlier only (no look-ahead)
2. **Regime-discriminating** -- different market states should produce different emission distributions
3. **Non-redundant** -- correlated dimensions don't add information, they distort the covariance estimate
4. **Stationary** -- or at least mean-reverting at the bar level; levels (raw price, raw volume) are excluded

---

## What the Current Vector Captures

- **Directional momentum** (dims 0, 2): is price trending?
- **Volatility level** (dim 1): is price moving a lot?
- **Volatility regime** (dim 3): is the volatility itself unstable (vol-of-vol)?
- **Volume anomaly** (dim 4): is participation above or below normal?

This captures trending vs. ranging, high vs. low vol, and volume participation. The K=5 labels that emerged (trending_down / transition_down / ranging / transition_up / trending_up) confirm the vector gives the HMM enough structure to separate meaningful states.

---

## The Volume Redundancy Question

`rel_volume` (dim 4) is in the observation vector. The IC stratification design (todo 030) proposes a separate explicit `volume_regime` column (low/mid/high buckets from rel_volume percentile rank).

These are NOT equivalent:

| | HMM implicit (dim 4) | Explicit volume_regime |
|---|---|---|
| **How used** | Informs which K-state is assigned | Direct stratification key |
| **Interaction** | Blended with 4 other dims; a high-volume bar with no momentum may map to "ranging" | Isolates volume effect independently |
| **Interpretability** | Opaque (which states are high-vol states?) | Explicit (IC table has volume_regime column) |
| **Risk** | HMM may not separate cleanly on volume if momentum dominates | Always separates; may find redundant patterns |

**Verdict:** Not double-counting. The HMM uses volume as one signal among five to assign a latent state. Explicit volume_regime stratification answers a different question: "holding HMM state constant, does IC differ by volume participation?" Those can both be true simultaneously. A trending_up HMM state at high volume may have very different IC than trending_up at low volume.

---

## Candidate Dimensions Not in Current Vector

### Near-term additions (low risk)

**Spread / microstructure proxy**
- `(high - low) / close` (normalized range) captures intraday volatility and bid-ask proxy
- Orthogonal to realized_vol (which is close-to-close); range-based vol responds faster to illiquidity
- Risk: correlated with `realized_vol` at daily timeframes; more useful at 1m/5m

**Volume-price confirmation**
- `sign(log_return) * rel_volume` -- positive when price direction and volume agree
- Captures the "conviction" dimension: big move on thin volume vs. big move on heavy volume
- Could be redundant if HMM already captures this via joint distribution of dims 0 and 4

### Structural additions (higher risk, require validation)

**Cross-asset spread**
- SPY/TLT ratio z-score or VIX proxy (SPY realized vol percentile, as used in equity_regime_model.py)
- Per-symbol HMM would get a market-wide signal; useful if individual symbol regimes are dominated by macro
- Risk: adds non-stationarity; macro regime changes on longer timescales than the HMM bar frequency

**Autocorrelation / mean-reversion signal**
- Short-lag (1-5 bar) autocorrelation of log_returns
- Positive autocorr = trending market; negative = mean-reverting
- Computationally heavier; window must be much longer than lag to estimate reliably

### What to avoid

**Raw price levels, raw volume** -- not stationary. HMM Gaussians will fit to the level, not the regime.

**Long-horizon features** (50+ bars) -- at 5m timeframe, 50 bars = 4+ hours. The HMM is meant to track microstate, not macro trend. Use equity_regime_model.py for that.

**Too many dimensions** -- with K=5 and `diag` covariance, each dim adds K parameters to the covariance. Going from 5D to 10D doubles the covariance parameter count and requires more data per symbol to converge. The BIC will catch this if dimensions are added one at a time and re-evaluated.

---

## Evaluation Protocol for Vector Changes

Any change to the observation vector invalidates all `feature_ic_scores` and requires a full corpus re-run. This is expensive. Before changing:

1. Train on 1-2 symbols only; evaluate K selection via BIC; confirm K=5 still wins or justify a new K
2. Check regime label stability: do the sorted-emission labels still map cleanly to trending/ranging semantics?
3. Run IC on those symbols; compare IC Sharpe vs. current 5D vector
4. If pass, full corpus re-run; treat as a migration-class change

APR key `feature.hmm.obs_vector_version` (not yet seeded) should increment on any vector change so corpus lineage is traceable in `feature_ic_scores`.

---

## Related Docs

- `docs/intelligence/intelligence-alphaengine.md` -- IC engine design
- `docs/plans/2026-07-01-regime-stratification-alternatives.md` -- volatility_regime + volume_regime as IC stratification dimensions
- `.planning/todos/pending/026-hmm-improvement-plan.md` -- P3/P4 gated HMM work
- `.planning/todos/pending/030-regime-stratification-alternatives.md` -- volume_regime implementation
- `services/regime_writer.py:137` -- `_build_obs_matrix()` implementation
