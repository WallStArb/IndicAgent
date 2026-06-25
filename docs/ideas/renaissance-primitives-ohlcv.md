# Renaissance Primitives — OHLCV Expansion Candidates

**Status:** Idea — not planned  
**Context:** Feature Factory (Phase 137) produces 54 features. This doc catalogs true
primitives derivable from OHLCV bar data that we do not yet compute. The goal is a
basket analogous to the 499+ raw signals Renaissance feeds into Medallion's ensemble
— no human theory baked in, just transformations of raw data. IC engine decides what's
predictive.

---

## What "Primitive" Means Here

A feature is a primitive if:
- It is a deterministic, stateless (or short-window) transformation of OHLCV
- It encodes no market theory (no "support zone," no "regime")
- A different researcher with the same data would compute the identical number
- It could plausibly have zero predictive power — and that's fine

Our current non-primitives: `poc_dist_atr`, `va_position`, `sr_support_dist`,
`sr_resist_dist`, `ctf_*`, `hmm_*`. These embed theory. They may have IC but they
are not primitives.

---

## Bar Anatomy Ratios

Derived from a single bar's O/H/L/C. No window needed.

| Feature | Formula | What it captures |
|---|---|---|
| `body_ratio` | `(C - O) / (H - L)` | Directional conviction; +1 = full bull body, -1 = full bear |
| `upper_wick_ratio` | `(H - max(O,C)) / (H - L)` | Rejection from highs |
| `lower_wick_ratio` | `(min(O,C) - L) / (H - L)` | Rejection from lows |
| `range_vs_atr` | `(H - L) / ATR_N` | Whether this bar is wide or narrow vs recent norm |
| `close_vs_open_direction` | `sign(C - O)` | Simple bar direction (categorical) |
| `overnight_gap` | `(O - prev_C) / prev_C` | Gap relative to prior close |
| `overnight_gap_z` | z-score of `overnight_gap` over N bars | Unusual gap signal |
| `range_efficiency` | `abs(C - prev_C) / (H - L)` | How efficiently price moved vs total range explored; 1 = closed at extreme, 0 = closed at open |

**Natural score ranges:**
- `body_ratio` — mathematically bounded [-1, 1]. No normalization needed. Usable directly in linear models.
- `upper_wick_ratio`, `lower_wick_ratio` — bounded [0, 1]. Centered at 0.5 not 0, so want `(ratio - 0.5) * 2` for linear models. Fine as-is for tree-based.
- `close_vs_open_direction` — {-1, 0, +1} categorical.
- `range_vs_atr`, `overnight_gap`, `overnight_gap_z` — unbounded, need z-scoring before linear use.
- `range_efficiency` — bounded [0, 1]. Shift to [-0.5, 0.5] for linear models. Note: does not carry directional sign (use with `body_ratio` for direction context).

Note: `body_ratio` is already partially captured by `bar_close_pos` and `range_position`
but the signed body ratio is distinct. `upper_wick_ratio` and `lower_wick_ratio` are not
in the factory at all.

---

## Lagged Return Series

Pure price-change primitives at fixed lookbacks. These are the most common
Renaissance inputs. Serial autocorrelation — positive or negative — is invisible
to our current momentum features (which use z-scores of price vs MA, not return lags).

| Feature | Formula | Naming | What it captures |
|---|---|---|---|
| `ret_lag_1` | `log(C_t / C_{t-1})` | Number (definitional) | 1-bar serial return |
| `ret_lag_2` | `log(C_t / C_{t-2})` | Number (definitional) | 2-bar return |
| `ret_lag_3` | `log(C_t / C_{t-3})` | Number (definitional) | 3-bar return |
| `ret_lag_fast` | `log(C_t / C_{t-N})`, N = APR `feature.ret_lag.fast` | **Gradient** | Short-term serial autocorrelation |
| `ret_lag_mid` | `log(C_t / C_{t-N})`, N = APR `feature.ret_lag.mid` | **Gradient** | Medium-term serial autocorrelation |
| `ret_lag_slow` | `log(C_t / C_{t-N})`, N = APR `feature.ret_lag.slow` | **Gradient** | Long-term serial autocorrelation |

Lags 1/2/3 are definitional - the number IS the statistic (same logic as `momentum_z_5`).
Lags for "short/medium/long-term" autocorrelation effects are calibration choices - gradient
naming, APR-backed window lengths. Distinct from `momentum_z_fast/mid/slow`, which z-score
price vs a moving average. Lagged log returns measure serial return correlation directly.

---


## Volume Structure Primitives

Beyond z-scores of volume level. `vol_body_product` moved to Interaction Primitives below.

| Feature | Formula | Naming | What it captures |
|---|---|---|---|
| `vol_acceleration` | `V_t / V_{t-1}` | None (bar-relative, no window) | Volume surge relative to prior bar |
| `dollar_vol_z` | z-score of `V * C` over N bars, N = APR `feature.dollar_vol.window` | APR-backed (single window) | Size-adjusted flow — large caps vs small get comparable signal |
| `vol_range_ratio` | `V_t / (H - L)` normalized over N, N = APR `feature.vol_range_ratio.window` | APR-backed (single window) | Volume per unit of price range — volume efficiency |
| `vol_trend_ratio` | `vol_MA_fast / vol_MA_slow`, windows = APR `feature.vol_trend.fast/slow` | **Gradient** | Is volume participation expanding or contracting? Pure volume trend |
| `up_vol_ratio_fast` | `sum(V where C > O) / sum(V)` over N bars, N = APR `feature.up_vol_ratio.fast` | **Gradient** | Fraction of volume occurring on up bars — bounded [0,1], no price level theory |
| `up_vol_ratio_slow` | same, N = APR `feature.up_vol_ratio.slow` | **Gradient** | Same at slower window |
| `vol_percentile` | rolling percentile rank of `V_t` over N bars, N = APR `feature.vol_percentile.window` | APR-backed (single window) | Where does today's volume rank in recent distribution? More robust than z-score for fat-tailed volume |
| `vol_persistence` | lag-1 autocorrelation of volume over N bars, N = APR `feature.vol_persistence.window` | APR-backed (single window) | Does high volume beget high volume? Regime detection for sustained participation |
| `vol_std_z` | z-score of rolling std(V) over N bars, N = APR `feature.vol_std.window` | APR-backed (single window) | Second-order volume — are we in a high-volatility-of-volume regime? |
| `mfi_fast` | Money Flow Index: `100 * sum(tp*V \| tp rising) / sum(tp*V)`, N = APR `feature.mfi.fast` | **Gradient** | Volume-weighted RSI — distinct from CMF (Chaikin A/D) and OFI (per-bar delta); captures whether volume flows into up or down typical prices |
| `mfi_slow` | same, N = APR `feature.mfi.slow` | **Gradient** | Longer-window money flow participation |
| `obv_z` | z-score of OBV (cumulative `+V` on up bars, `-V` on down bars), N = APR `feature.obv.window` | APR-backed (single window) | Longer-horizon volume accumulation/distribution; raw OBV is path-dependent and unscaled, z-score over rolling window makes it comparable across symbols and time |

**Natural score ranges:**
- `up_vol_ratio_*` — bounded [0, 1]. Shift to [-0.5, 0.5] for linear models: `ratio - 0.5`.
- `vol_persistence` — bounded [-1, 1]. Ready as-is for linear models.
- `vol_trend_ratio`, `vol_acceleration`, `vol_range_ratio` — unbounded positive ratios. Need log or percentile transform for linear models; ready as-is for tree-based.
- `vol_percentile` — bounded [0, 1]. Shift for linear models.
- `vol_std_z`, `dollar_vol_z` — z-scored, centered at 0. Ready as-is.

---

## Realized Variance and Volatility Primitives

| Feature | Formula | Naming | What it captures |
|---|---|---|---|
| `realized_var_ratio` | `realized_var_fast / realized_var_slow`, windows = APR `feature.realized_var.fast/slow` | **Gradient** | Vol regime shift — short vol accelerating vs long vol |
| `range_to_close` | `(H - L) / C` | None (no window) | Absolute range normalized to price level |
| `true_range_pct` | `TR / C` | None (no window) | ATR as fraction of price |
| `vol_of_vol` | Rolling std of `atr_z`, N = APR `feature.vol_of_vol.window` | APR-backed (single window) | Second-order volatility |
| `high_low_corr` | Correlation of H and L over N bars, N = APR `feature.high_low_corr.window` | APR-backed (single window) | Trending vs oscillating structure |
| `variance_ratio_fast` | `var(ret, N_fast) / (N_fast * var(ret, 1))`, N = APR `feature.variance_ratio.fast` | **Gradient** | Short-window random walk deviation; >1 = trending, <1 = mean-reverting |
| `variance_ratio_slow` | same, N = APR `feature.variance_ratio.slow` | **Gradient** | Long-window random walk deviation |
| `vol_asymmetry_z` | z-score of `std(ret \| up bars) / std(ret \| down bars)`, N = APR `feature.vol_asymmetry.window` | APR-backed (single window) | Leverage effect — vol is higher on down moves; captures asymmetry without GARCH |
| `bb_pct_b_fast` | `(C - lower_band_N) / (upper_band_N - lower_band_N)`, N = APR `feature.bb_pct_b.fast` | **Gradient** | Price position within its own rolling standard deviation envelope; only feature that normalizes price by its variance distribution rather than ATR or return z-score; >1 = beyond upper band, <0 = below lower band |
| `bb_pct_b_slow` | same, N = APR `feature.bb_pct_b.slow` | **Gradient** | Longer-window band position |
| `hv_z_fast` | z-score of `std(log(C_t/C_{t-1}), N_fast)`, N = APR `feature.hv.fast` | **Gradient** | Close-to-close HV — the classic estimator; distinct from ATR (true-range based) and Parkinson/GK/YZ (OHLC based); reference formula in archived `i1_indicators/historical_volatility.py` |
| `hv_z_slow` | same, N = APR `feature.hv.slow` | **Gradient** | Longer-window close-to-close HV |
| `hv_ratio` | `hv_fast / rolling_mean(hv, N)`, N = APR `feature.hv.ratio_window` | APR-backed (single window) | Current HV relative to recent average HV — vol regime indicator using close-to-close estimator; analogous to `vol_ratio` but for HV not ATR |

**Natural score ranges:**
- `variance_ratio_*` — unbounded positive, centered at 1.0 under random walk. For linear models: use `(vr - 1)` then z-score. For tree models: ready as-is.
- `vol_asymmetry_z` — z-scored, centered at 0.
- `bb_pct_b_*` — nominally [0, 1] but unbounded in practice (price can exit bands). Useful as-is for tree models; z-score for linear.
- `range_to_close`, `true_range_pct` — unbounded positive. Z-score or percentile for linear models.
- `vol_of_vol` — z-scored, centered at 0.
- `high_low_corr` — bounded [-1, 1]. Ready as-is.
- `realized_var_ratio` — unbounded positive ratio. Log-transform then z-score for linear models.

---

## Alternative Volatility Estimators

ATR uses only close-to-close (with true range adjustment). Three estimators from the literature
use more of the available OHLC information and are strictly more efficient for the same bar data.

| Feature | Formula | Naming | What it captures |
|---|---|---|---|
| `parkinson_vol_z` | z-score of `ln(H/L)^2 / (4*ln(2))`, N = APR `feature.parkinson_vol.window` | APR-backed (single window) | H/L-only vol estimator; ~5x more efficient than close-to-close; no overnight gap |
| `garman_klass_vol_z` | z-score of GK estimator using O/H/L/C, N = APR `feature.garman_klass_vol.window` | APR-backed (single window) | Most efficient single-bar OHLC estimator; accounts for open drift within bar |
| `yang_zhang_vol_z` | z-score of YZ estimator using O/H/L/C + prev_C, N = APR `feature.yang_zhang_vol.window` | APR-backed (single window) | GK + overnight gap component; best overall for assets with significant overnight moves |

GK formula: `0.5 * ln(H/L)^2 - (2*ln(2) - 1) * ln(C/O)^2`

YZ formula: `var(overnight) + k * var(open-to-close) + (1 - k) * var(GK)`, k ≈ 0.34

These are not replacements for `atr_z` — ATR has different properties (max-based, not variance-based).
All three will cluster in IC space with `atr_z` and `vol_ratio` but carry incremental signal from
the OHLC dimensions ATR ignores. IC engine determines which survives.

**Natural score ranges:** all z-scored, centered at 0. Ready as-is for linear and tree models.

---

## Breakout Distance Primitives

No S/R zone theory — just raw distance from recent extremes.

| Feature | Formula | What it captures |
|---|---|---|
| Feature | Formula | Naming | What it captures |
|---|---|---|---|
| `dist_from_high_fast` | `(rolling_high_N - C) / ATR`, N = APR `feature.breakout.lookback_fast` | **Gradient** | Distance from recent high, ATR-normalized |
| `dist_from_high_slow` | `(rolling_high_N - C) / ATR`, N = APR `feature.breakout.lookback_slow` | **Gradient** | Distance from longer-term high |
| `dist_from_low_fast` | `(C - rolling_low_N) / ATR`, N = APR `feature.breakout.lookback_fast` | **Gradient** | Distance from recent low |
| `dist_from_low_slow` | `(C - rolling_low_N) / ATR`, N = APR `feature.breakout.lookback_slow` | **Gradient** | Distance from longer-term low |
| `range_pct_fast` | `(rolling_high_N - rolling_low_N) / C` | **Gradient** | Short-window consolidation vs expansion |
| `range_pct_slow` | `(rolling_high_N - rolling_low_N) / C` | **Gradient** | Long-window consolidation vs expansion |
| `new_high_flag` | `1 if C == rolling_high_N else 0` | Number optional (binary flag) | Breakout detection |
| `new_low_flag` | `1 if C == rolling_low_N else 0` | Number optional (binary flag) | Breakdown detection |
| `stoch_k_fast` | `(C - L_N) / (H_N - L_N)`, N = APR `feature.stoch_k.fast` | **Gradient** | Price position within rolling H/L range — distinct from RSI (uses close-change ratios) and `bar_close_pos` (uses single-bar H/L); captures range location over N bars |
| `stoch_k_slow` | same, N = APR `feature.stoch_k.slow` | **Gradient** | Longer-window range position |
| `price_percentile_fast` | rolling percentile rank of `C_t` within N-bar close distribution, N = APR `feature.price_percentile.fast` | **Gradient** | Where current close ranks in its own recent price distribution; more robust than distance-from-extreme for fat-tailed price series; directly analogous to `vol_percentile` |
| `price_percentile_slow` | same, N = APR `feature.price_percentile.slow` | **Gradient** | Longer-window price distribution rank |
| `efficiency_ratio_fast` | `abs(C_t - C_{t-N}) / sum(\|C_i - C_{i-1}\|)`, N = APR `feature.efficiency_ratio.fast` | **Gradient** | Kaufman Efficiency Ratio — bounded [0, 1]; 0 = pure chop, 1 = perfectly linear trend; single formula, no model; distinct from Hurst (fractal), ADX (directional movement), HMM (regime) |
| `efficiency_ratio_slow` | same, N = APR `feature.efficiency_ratio.slow` | **Gradient** | Longer-window trend purity |

Window N is pure calibration ("what counts as recent vs long-term") - gradient naming,
APR-backed. No migration needed to change window lengths.

**Natural score ranges:**
- `dist_from_high_*`, `dist_from_low_*` — unbounded positive (ATR units). Z-score or percentile for linear models.
- `range_pct_*` — unbounded positive ratio. Z-score or percentile for linear models.
- `new_high_flag`, `new_low_flag` — {0, 1} binary. Ready as-is.
- `stoch_k_*` — bounded [0, 1]. Shift to [-0.5, 0.5] for linear models.

---

## Return Distribution Primitives

We have `ret_skew_z`. Missing:

| Feature | Formula | Naming | What it captures |
|---|---|---|---|
| `ret_kurtosis_z_fast` | z-score of rolling kurtosis, N = APR `feature.ret_kurtosis.fast` | **Gradient** | Short-window fat-tail regime |
| `ret_kurtosis_z_slow` | z-score of rolling kurtosis, N = APR `feature.ret_kurtosis.slow` | **Gradient** | Long-window fat-tail regime |
| `ret_autocorr_1` | lag-1 autocorrelation over N bars | Number (definitional) | Mean-reversion vs momentum |
| `ret_autocorr_5` | lag-5 autocorrelation over N bars | Number (definitional) | Weekly mean-reversion |
| `updown_ratio_fast` | count(up bars) / count(down bars), N = APR `feature.updown_ratio.fast` | **Gradient** | Short-term win-rate |
| `updown_ratio_slow` | count(up bars) / count(down bars), N = APR `feature.updown_ratio.slow` | **Gradient** | Medium-term win-rate |
| `streak_z` | z-score of current directional streak length (positive = up streak, negative = down streak), normalization window = APR `feature.streak.window` | APR-backed (single window) | Momentum continuation — distinct from rolling win-rate; resets to 0 on first bar reversing direction |

**Natural score ranges:**
- `ret_autocorr_1`, `ret_autocorr_5` — mathematically bounded [-1, 1]. No normalization needed. Pure mean-reversion = -1, pure momentum = +1. Directly usable in linear models.
- `ret_kurtosis_z_*` — z-scored, unbounded but centered at 0.
- `updown_ratio_*` — [0, ∞), needs log or percentile transform for linear models.
- `streak_z` — z-scored, signed. Centered at 0. Ready as-is for linear models.

Note: `streak_z` and `updown_ratio_*` are complementary, not redundant. `updown_ratio` counts direction over a rolling window (smoothed). `streak_z` measures the current unbroken run (resets). A market that alternates up/down perfectly has `updown_ratio ≈ 1` but `streak_z ≈ 0` every bar. A trending market accumulates streak length.

---

## Open-to-Close Split

| Feature | Formula | What it captures |
|---|---|---|
| `open_ret` | `log(O_t / C_{t-1})` | Overnight component of return |
| `intraday_ret` | `log(C_t / O_t)` | Within-session component |
| `open_vs_intraday` | `open_ret - intraday_ret` | Whether overnight or intraday component dominates |
| `session_time_pos` | `bar_index_in_session / total_session_bars` | Continuous [0, 1] position within trading day — no window, no OHLCV, pure timestamp arithmetic; existing calendar features are all binary or multi-day cycle; nothing captures intraday time position continuously |

These decompose total return into its two structural pieces. Overnight gaps driven by
news; intraday driven by order flow. Predictability differs by regime.

`session_time_pos` requires no APR key (no window parameter). It is 0_atomic in the
calendar group alongside `dow_sin`, `dow_cos`, `month_position`.

---

## Interaction Primitives

### What "interaction" means here

An interaction primitive is a deterministic combination of two atomic OHLCV-derived
values — a product, ratio, or rolling correlation between two features from the sections
above. No market theory is embedded: no S/R zones, no regime labels, no cross-asset
structure. The combination itself encodes no hypothesis about what is predictive. IC
decides.

**Taxonomy:**
- **Atomic** — single dimension of OHLCV, fixed window. `body_ratio`, `ret_lag_1`, `volume_z`. Irreducible inputs.
- **Interaction** — deterministic combination of two atomics. One abstraction level deeper, still fully reproducible, still theory-free.
- **Theory-embedded** — encodes structure, regime, cross-asset model. Not primitives.

Both atomic and interaction features are valid IC candidates. The distinction matters
for feature clustering (009): correlated atomics cluster with their interaction child.
An interaction feature that has IC after controlling for its two parent features carries
genuine incremental information; one that doesn't is redundant.

### Price × Volume Interactions

These capture the joint behavior of price movement and volume participation — something
neither dimension captures alone.

| Feature | Formula | Naming | What it captures |
|---|---|---|---|
| `vol_body_product` | `body_ratio * volume_z` | None (no window beyond parents) | Direction conviction × volume confirmation — do strong-bodied bars come with high volume? |
| `ret_vol_product_fast` | `ret_lag_fast * volume_z` | **Gradient** (inherits from `ret_lag_fast`) | Signed: up-move with high volume = large positive; down-move with high volume = large negative |
| `price_vol_corr_fast` | rolling Pearson(`\|ret_lag_1\|`, `V`) over N, N = APR `feature.price_vol_corr.fast` | **Gradient** | Do large price moves come with large volume? Institutional signature |
| `price_vol_corr_slow` | same, N = APR `feature.price_vol_corr.slow` | **Gradient** | Same at slower window — structural vs noise |
| `range_vol_product` | `range_vs_atr * volume_z` | None (no window beyond parents) | Wide bar + high volume — neither alone is sufficient |
| `up_vol_body_diff` | `up_vol_ratio_fast - body_ratio` | None | Volume skew vs price direction divergence — volume bullish but bar bearish |

### Cross-Timeframe Divergences

Raw return divergence between timeframes. No judgment about which direction is correct —
that would be theory. These measure disagreement as a raw number; IC decides whether
disagreement is signal or noise.

(Previously under a separate section; moved here as these are products of two atomic
per-TF returns, which is the interaction definition.)

| Feature | Formula | What it captures |
|---|---|---|
| `ret_div_1m_5m` | `ret_1m_last - ret_5m_last` | Intraday vs 5m drift disagreement |
| `ret_div_5m_1h` | `ret_5m_last - ret_1h_last` | Short vs medium disagreement |
| `ret_div_1h_1d` | `ret_1h_last - ret_1d_last` | Intraday vs daily disagreement |

These require pulling the corresponding bar from the HTF cache — already available
via `feature_cache.py`.

### Volatility × Return Interactions

| Feature | Formula | Naming | What it captures |
|---|---|---|---|
| `ret_vol_ratio_fast` | `ret_lag_fast / atr_z` | **Gradient** | Return per unit of recent volatility — Sharpe-like single-bar quality |
| `vol_skew_product` | `ret_skew_z * volume_z` | None | Fat left tail with high volume (institutional distribution pressure) |

**Natural score ranges:**
- `vol_body_product`, `ret_vol_product_*`, `range_vol_product` — unbounded, symmetric around 0. Ready as-is for tree models; z-score for linear.
- `price_vol_corr_*` — bounded [-1, 1]. Ready as-is.
- `up_vol_body_diff` — bounded approximately [-1, 1] (both parents bounded or near-bounded). Ready as-is.
- `ret_div_*` — unbounded, centered near 0. Z-score for linear models.
- `ret_vol_ratio_*` — unbounded, needs z-score or winsorization.

---

## Implementation Notes

**Natural score ranges — which features need normalization.**

| Range | Features | Linear model | Tree model |
|---|---|---|---|
| [-1, 1] naturally | `body_ratio`, `ret_autocorr_1`, `ret_autocorr_5`, `vol_persistence`, `price_vol_corr_*`, `high_low_corr` | Ready as-is | Ready as-is |
| [0, 1] naturally | `upper_wick_ratio`, `lower_wick_ratio`, `new_high_flag`, `new_low_flag`, `vol_percentile`, `up_vol_ratio_*`, `range_efficiency`, `stoch_k_*`, `mfi_*`, `price_percentile_*`, `efficiency_ratio_*`, `session_time_pos` | Shift to [-1,1]: `(x - 0.5) * 2` | Ready as-is |
| Unbounded, centered | z-scored features (`ret_kurtosis_z_*`, `overnight_gap_z`, `dollar_vol_z`, `vol_std_z`, `vol_body_product`, `parkinson_vol_z`, `garman_klass_vol_z`, `yang_zhang_vol_z`, `vol_asymmetry_z`, `streak_z`, `obv_z`, `bb_pct_b_*`, etc.) | Ready as-is | Ready as-is |
| Centered around 1, unbounded | `variance_ratio_*` | Use `(vr - 1)` then z-score | Ready as-is |
| Unbounded, uncentered | Raw ratios (`range_vs_atr`, `vol_acceleration`, `vol_trend_ratio`, `updown_ratio_*`, log returns, `ret_vol_ratio_*`, `realized_var_ratio`) | Need z-score or percentile | Ready as-is |

The [-1, 1] features are especially valuable: they carry directional sign and bounded magnitude
with no preprocessing. The IC engine can use them raw.

**Gradient naming rule.** The test: would you update APR to change this number without
a column migration? If yes - gradient. If the number IS the statistical definition
(lag-1 autocorrelation, 3-bar return) - keep the number.

| Use gradient | Keep number |
|---|---|
| `ret_lag_fast/mid/slow` | `ret_lag_1`, `ret_lag_2`, `ret_lag_3` |
| `dist_from_high_fast/slow` | `ret_autocorr_1`, `ret_autocorr_5` |
| `range_pct_fast/slow` | `body_ratio`, `upper_wick_ratio` (no window) |
| `ret_kurtosis_z_fast/slow` | `open_ret`, `intraday_ret` (no window) |
| `updown_ratio_fast/slow` | `vol_body_product`, `range_vol_product` (no window beyond parents) |
| `variance_ratio_fast/slow`, `stoch_k_fast/slow`, `bb_pct_b_fast/slow`, `mfi_fast/slow` | `range_efficiency` (no window), `streak_z`, `obv_z` (single normalization window each — no fast/slow distinction) |
| `vol_trend_ratio`, `up_vol_ratio_*`, `price_vol_corr_*` | `parkinson_vol_z`, `garman_klass_vol_z`, `yang_zhang_vol_z`, `vol_asymmetry_z` (single normalization window each) |

**All of these are APR-backed.** Window lengths must go into `config_state`
under `feature.*` namespace. Gradient columns get APR keys; single-window features
get one APR key; no-window features need no APR entry.

**No theory features.** None of these should reference S/R zones, HMM state,
CTF alignment, or volume profile. If a formula requires those, it belongs in a
different category.

**Compute cost.** Bar anatomy and lag returns are O(1) per bar. Autocorrelations and
realized variance are O(N). Rolling high/low extremes are O(1) with a deque. All
are fast enough for the 5m batch path.

**IC discovery first.** Add to the factory, run `backfill_feature_factory.py`, run
IC engine, observe IC and decay. Promote only features with IC Sharpe > 0 and
p < 0.05 across sufficient N. Do not assume any of these will be predictive.

---

## Priority Order

Based on likely IC and computation cost:

1. **Bar anatomy ratios** - zero cost, clearly missing, analogous to known Simons inputs; `range_efficiency` included
2. **Alternative vol estimators** - strictly more efficient use of existing OHLCV; Parkinson/GK/YZ cluster with `atr_z` but carry incremental information from dimensions ATR ignores; high likelihood of IC given vol is the strongest factor in our current feature set
3. **Breakout distance** - raw version of what S/R features approximate with theory; if S/R features have IC their theory-free analogs likely do too
4. **Lagged return series** - foundational; autocorrelation alpha is well-documented
5. **Open/intraday split** - low cost, captures overnight vs session structure; also fixes overnight gap contamination identified in IC methodology review
6. **Variance ratio** - direct empirical test of random walk deviation; complement to Hurst without the estimation noise at short windows
7. **Volume structure (expanded)** - `vol_trend_ratio`, `up_vol_ratio_*`, `vol_percentile`, `vol_persistence`, `mfi_fast/slow`, `obv_z` extend well beyond existing z-score coverage; reference formulas exist in archived `i1_indicators/mfi.py` and `obv.py` — all need Feature Factory implementation
8. **Stochastic %K + Bollinger %B + HV** - reference formulas in archived `i1_indicators/stochastic.py`, `bollinger.py`, `historical_volatility.py`; all need Feature Factory implementation with gradient windows; `stoch_k` is the rolling-window version of `bar_close_pos`; `bb_pct_b` is the only variance-normalized price position feature; `hv_z_*` is the classic close-to-close estimator missing from the current set
9. **Price percentile rank + Efficiency Ratio** - no reference implementation exists; efficiency ratio is the most novel addition: single formula, bounded [0,1], directly measures trend purity; `price_percentile` fills the gap that `vol_percentile` fills for volume
10. **Session time position** (`session_time_pos`) - zero compute cost, pure timestamp; the only missing continuous intraday time feature
9. **Conditional vol asymmetry** (`vol_asymmetry_z`) - leverage effect without GARCH; low compute cost
9. **Streak** (`streak_z`) - complementary to `updown_ratio`; captures unbroken directional runs rather than rolling win-rate
10. **Interaction primitives (price × volume)** - `price_vol_corr_*`, `ret_vol_product_*` — requires parent atomics to be computed first; high likely IC
11. **Cross-TF divergence / interaction** - requires HTF cache, already available
12. **Return distribution** - kurtosis/autocorr require longer windows, higher variance estimation noise

---

## What This Is Not

This is not a plan. No phase assigned. These are candidates for IC testing when we
have the full 58-symbol corpus running and the IC engine is stable. The right trigger
is: IC engine producing stable results on current 54 features, corpus complete,
and a deliberate decision to expand the primitive basket.
