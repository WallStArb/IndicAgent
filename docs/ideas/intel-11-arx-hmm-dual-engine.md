# ARX-HMM Dual-Engine Architecture

**Status:** Idea / Research
**Extends:** `intel-10-hmm-observation-vector.md`

---

## Core Concept

Instead of a single flat HMM observation vector, structure regime detection as two coupled engines:

```
[Low-Frequency Structural Anchors]  (Form PF, 13F, ADV filings)
               │
               ▼  modulates Transition Probability Matrix
┌────────────────────────────────────────────────┐
│           HMM (ARX variant)                    │
│  Latent states: Accumulation / Distribution /  │
│  Expansion / Fragile / Liquidation             │
└────────────────────────────────────────────────┘
               ▲
               │  continuous emission updates
[High-Frequency Microstructure]  (1m–1d OHLCV, volume, volatility)
```

The standard HMM transition probability is:

```
P(S_t = j | S_{t-1} = i)
```

The ARX-HMM modifies this with an exogenous regulatory flow vector `u_t`:

```
P(S_t = j | S_{t-1} = i, u_t)
```

`u_t` = Regulatory Flow Vector: AUM trends, leverage metrics, net positioning from structural filings. When `u_t` signals hedge funds are net-short or de-leveraging, it lowers transition probability into bullish states regardless of what the microstructure bars show. When `u_t` is bullish, microstructure acts as the tactical trigger.

---

## Two Timescales, Two Roles

| Layer | Data | Update Frequency | Role |
|---|---|---|---|
| Macro (slow) | Form PF, 13F, ADV | Quarterly / 45-60d lag | Constrains TPM — sets which states are reachable |
| Micro (fast) | 1m–1d OHLCV | Per bar | Updates emission probabilities — triggers state transitions |

Key insight: the macro layer doesn't need to be timely. A 45-day-lagged 13F is fine as a slow-moving prior on the TPM. It rules out regimes, not picks them. The microstructure confirms.

---

## High-Frequency Microstructure Features

These extend the current 5D observation vector (`intel-10-hmm-observation-vector.md`) with institutional footprinting signals:

### Volume-Price Coupling (VPC)
Rolling correlation between volume changes and directional price movement across 5m and 15m bars. High VPC in a confirmed high-institutional-concentration regime = active continuation signal.

```
vpc[t] = rolling_corr(Δvolume, sign(log_return) * |log_return|, window=W)
```

Distinct from `rel_volume` (dim 4 of current vector): that measures absolute volume anomaly. VPC measures whether volume is *directionally coupled* to price -- which separates informed institutional flow from random volume spikes.

### Intraday Volatility Cascade
Rolling variance of 1m and 5m true ranges. A variance spike on 1d timeframe while macro lever signals high systemic leverage = high probability shift into Fragile/Liquidation regime.

```
true_range[t] = max(high, prev_close) - min(low, prev_close)
vol_cascade[t] = rolling_var(true_range_1m, window=W_slow)
```

Distinct from `vol_of_vol` (dim 3): that's std of close-to-close realized vol. This is variance of intraday range -- captures gap risk and thin-market fragility that close-to-close vol misses.

### Garman-Klass Volatility
Range-based variance estimator that uses OHLC -- significantly more efficient than close-to-close realized vol (the current dim 1) because it incorporates intraday range information:

```
σ²_GK[t] = 0.5 * ln(H/L)² - (2*ln2 - 1) * ln(C/O)²
```

Rolled over 1h and 1d windows. More efficient than `realized_vol` for the same window length -- GK extracts ~5x more information per bar because it sees the full range, not just the close-to-close delta. At 5m timeframe where bars are noisy, this matters.

**Relationship to current dim 1 (`realized_vol`):** Not redundant. `realized_vol` is close-to-close std; GK is OHLC range-based. GK responds immediately to intraday liquidity shocks that close-to-close vol misses until the next bar's close.

### Intraday Variance Ratio
Ratio of short-timeframe realized variance to the full daily variance:

```
ivr[t] = realized_var(1m or 5m bars, last N bars) / realized_var(1d, rolling window)
```

A high ratio = massive intraday bursts relative to the daily baseline. This pattern is characteristic of institutional algorithmic block execution -- VWAP/TWAP algos create concentrated micro-bursts that look smooth on the daily but are detectable at 1m/5m. The variance ratio spikes *before* the 1d bar reflects it, giving the HMM early warning of regime transition.

**APR candidate:** `feature.hmm.ivr_fast_window` (1m bars over N bars), `feature.hmm.ivr_slow_window` (1d rolling baseline).

### Bar-Level Asymmetry / Close Skew
Position of close within the high-low range per bar, rolled over 1h and 1d:

```
bar_skew[t] = (close[t] - low[t]) / max(high[t] - low[t], ε)
close_skew_roll[t] = rolling_mean(bar_skew, window=W)
```

Range: [0, 1]. Consistently near 1.0 (closing at highs) = Accumulation emission signature. Near 0.0 = Distribution. This is NOT in the current 5D vector and is orthogonal to both realized_vol and momentum.

---

## The 5 Latent Flow Regimes

The macro regulatory data (13F, Form PF, Form D, ADV) should drive the HMM toward 5 structurally meaningful states. These are participation-centric, distinct from the current momentum-centric K=5 labels:

| # | State | Primary Driver | Macro Signal | Micro Signature |
|---|---|---|---|---|
| 1 | **Short Squeeze / De-leveraging** | NFA / Form PF | High short futures exposure + sudden leverage drop | Negative VPC, vol_cascade spike, close_skew near 0 then whipsaw |
| 2 | **Quiet Accumulation** | 13F / Form D | High institutional concentration building, AUM scaling, public offerings (Form D) rising | High close_skew, moderate VPC on up-bars, low vol_cascade |
| 3 | **Balanced / Neutral Roll** | All filings at baseline | No aggressive positioning shifts; flows match historical norms | VPC near zero, low vol_cascade, close_skew ~0.5 |
| 4 | **Institutional Distribution** | 13F / ADV | AUM flat or slightly falling despite positive price; smart money exiting into retail buying | Low/falling close_skew, high VPC on down-bars despite up-price |
| 5 | **Systemic Liquidation** | Form PF | Macro funds rushing to cash, cross-asset futures liquidation (NFA) | Massive vol_cascade, strongly negative VPC, close_skew near 0, earnings misses trigger structural gaps |

**Key distinction from current labels:** trending_down/up/ranging describe *price momentum*. These 5 states describe *institutional participation intent* -- a crowded-long distribution market and a quiet accumulation market can both show "trending_up" in the current HMM but have opposite IC profiles for trend-following features.

**K=5 consistency:** BIC already selected K=5 on the momentum-only observation vector. The flow-regime framing gives interpretive anchors for what those 5 states *mean* when extended with institutional footprinting features.

---

## IC Validation Path

Directly compatible with the existing IC engine:

1. **Micro-IC**: measure IC of 1h/1d OHLCV anomalies (close_skew, VPC) predicting post-period returns
2. **Conditional IC**: same features conditioned on macro regime (high/low 13F institutional concentration)
3. **Expected finding**: VPC and close_skew IC should be substantially higher and more stable when macro vector confirms high institutional concentration. When institutional participation is low, these signals deteriorate toward noise.

This is the same stratification approach as `feature_ic_scores` -- just with macro-regime as an additional stratification axis alongside HMM state.

---

## Data Dependencies and Availability

### Currently unavailable
- **Form PF**: hedge fund systemic risk filings to SEC. Filed quarterly, 60-day lag. Not public -- requires a data vendor (Preqin, Burgiss, SEC EDGAR for the limited public subset).
- **13F**: institutional holdings. Filed 45 days post-quarter-end. Public via SEC EDGAR. Parseable but 45-day stale.
- **ADV (Form ADV)**: RIA registration/AUM filings. Annual + amendments. Structural, very slow-moving.

### Immediately available
- All microstructure features (VPC, vol_cascade, close_skew) derive from existing OHLCV bars already in `market_data_ohlcv`. No new data required.
- `rel_volume` (already in FeatureVector) feeds into the micro layer.

### Practical near-term path
Build and validate the microstructure features first -- VPC, vol_cascade, close_skew added to the HMM observation vector or as explicit `feature_vectors` columns. Validate IC independently. When/if 13F data becomes available, layer in the ARX TPM modification. The micro engine stands alone.

---

## Relationship to Current Architecture

| Component | Current | ARX-HMM extension |
|---|---|---|
| HMM obs vector | 5D (log_return, realized_vol, momentum, vol_of_vol, rel_volume) | +3: VPC, vol_cascade, close_skew |
| Regime labels | Unsupervised K=5 trend states | Partially anchored to institutional participation states |
| TPM | Stationary (fixed transition probs) | Exogenous-modulated by `u_t` |
| Stratification | hmm_state × volatility_regime × volume_regime | + macro_regime (13F concentration bucket) |
| Data required | OHLCV only | +SEC filings for macro layer |

---

## Open Questions

1. **Hard vs. soft macro prior**: modifying the TPM directly (hard constraint) vs. adding macro features to the observation vector (soft influence) -- the latter is implementable today without changing the HMM architecture.
2. **State count**: K=5 was BIC-optimal for the current 5D vector. A richer observation vector will likely push BIC toward higher K. Re-run BIC before corpus re-run.
3. **Corpus invalidation**: any observation vector change requires full corpus re-run (as with all HMM changes). Incremental validation on 2-3 symbols first.
4. **13F staleness**: 45-day lag means 13F regimes update ~4x/year. TPM modification from 13F effectively creates 4 seasonal TPM variants. Is that enough resolution, or does it just add noise?

---

## Related Docs

- `docs/ideas/intel-10-hmm-observation-vector.md` -- current 5D vector, evaluation protocol
- `docs/ideas/intel-08-macro-cross-asset.md` -- macro/cross-asset signals
- `docs/intelligence/intelligence-alphaengine.md` -- IC engine design
- `docs/plans/2026-06-29-regime-stratification-alternatives.md` -- volatility_regime + volume_regime stratification
