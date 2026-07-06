# Renaissance Primitives — OHLCV Expansion Candidates

**Status:** Idea — not planned
**Restored:** 2026-07-06 — moved from archive (was `docs/ideas/archive/renaissance-primitives-ohlcv.md`)
**Context:** Feature Factory (v3.0) produces 54 features. This doc catalogs true
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

**Related work:** These three estimators (Parkinson, Garman-Klass, Yang-Zhang) form the observation space for **E1 (volatility structure)** in `intel-stratification-dimension.md` — the volatility-regime stratification dimension. E1 proposes these as inputs to a separate HMM or percentile-rank classifier that learns volatility states (compressing, quiet, chop, expanding, panic). Implementation under that contract is gated on the simpler `volatility_pct` (percentile-rank of realized vol) proving insufficient via substitution test.

---

## Volatility Dynamics Primitives

Beyond static volatility estimators, these capture how volatility itself changes over time — acceleration, deceleration, and noise structure.

| Feature | Formula | Naming | What it captures |
|---|---|---|---|
| `parkinson_vol_velocity` | `parkinson_vol_z_t - parkinson_vol_z_{t-1}` | None (no window) | First derivative of Parkinson vol — distinguishes steady high vol from accelerating panic |
| `garman_klass_vol_velocity` | `garman_klass_vol_z_t - garman_klass_vol_z_{t-1}` | None (no window) | First derivative of GK vol — detects vol expansion/contraction onset |
| `yang_zhang_vol_velocity` | `yang_zhang_vol_z_t - yang_zhang_vol_z_{t-1}` | None (no window) | First derivative of YZ vol — most comprehensive vol acceleration signal (includes overnight gap changes) |
| `vol_velocity_z` | z-score of rolling `atr_z` velocity, N = APR `feature.vol_velocity.window` | APR-backed (single window) | Normalized vol rate-of-change — standardized across symbols and timeframes |
| `intraday_noise_ratio` | `sum(abs(1m_rets_in_session)) / abs(daily_ret)` or `sum(|ret_5m|) / |ret_1d|` over N bars, N = APR `feature.intraday_noise.window` | APR-backed (single window) | Ratio of intraday oscillation to net directional progress — high = chop (State 3), low = trend (State 2/4) |

**What "Volatility Velocity" means:** The first derivative (rate of change) of a volatility metric. A large positive value means volatility is accelerating (panic onset); a large negative value means volatility is decelerating (stabilization); near-zero means steady-state vol (quiet or stable high vol).

**What "Intraday Noise Ratio" means:** Measures how much price oscillates within a session vs. how much net progress it makes. A ratio of 10+ means price moved 10x more up-and-down than it ended up net — classic mean-reverting chop (market makers dominating). A ratio near 1 means clean directional progress (trending or drifting).

**Why these matter for regime detection:** 

- **Velocity discriminates States 4 vs 5**: Both have high vol, but State 4 (directional expansion) has low/constant velocity while State 5 (systemic liquidation) has sharply positive velocity (vol accelerating out of control).
- **Noise ratio discriminates States 2 vs 3**: Both have moderate vol, but State 2 (quiet bull drift) has low noise ratio (clean progress) while State 3 (mean-reverting chop) has high noise ratio (oscillation without progress).
- **Cross-asset**: Vol velocity on SPY vs. TLT can reveal whether vol is equity-specific (idiosyncratic risk) or systemic (cross-asset contagion).

**Natural score ranges:**
- `*_vol_velocity` (unsmoothed) — unbounded, centered near 0. Use z-score for linear models; ready as-is for tree models.
- `vol_velocity_z` — z-scored, centered at 0. Ready as-is.
- `intraday_noise_ratio` — unbounded positive [1, ∞). Log-transform or percentile for linear models; ready as-is for tree models.

**Computational notes:**
- All three `*_vol_velocity` features are O(1) — simple difference of two z-scores already computed.
- `intraday_noise_ratio` requires summing absolute returns over a session window; O(N) but small N (typically 78 bars for 5m in US equity session, 390 for 1m).
- For cross-TF noise ratio, pull the 1d bar's return from HTF cache via `feature_cache.py` and sum the current TF's absolute intraday returns.

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

## Temporal Coordinate Primitives

### Renaissance Principle: No State, No Theory, No Hand-Holding

**What we don't do:**

- No "bars since OPEX" — stateful, requires tracking last event, reset logic, recovery paths
- No "quarter progress" — encodes theory that quarter-end is the relevant event
- No "days to month-end" — HTF constants at LTF, or stateful countdowns
- No binary flags for events — "is_opex_day" bakes in the hypothesis that OPEX matters

**Why: State is complexity.** Every stateful feature is a bug magnet. What happens on data gaps? What's the recovery logic? How do we verify correctness? DAG violations — single-pass compute broken.

**Why: Theory-laden features bias discovery.** If OPEX matters, let the ensemble discover it from `dow`, `day_of_month`, `vol_z`, `ret_lag_1`. Don't hand it a pre-cooked OPEX counter. Renaissance's "499+ signals" were mostly log returns at different lags. Not "bars since FOMC."

**What Jim Simons would demand:**

"If OPEX causes pin risk, why can't the ensemble discover that from temporal coordinates + price/volume features? Are you telling me the pattern is so obscure it needs a hand-crafted counter? Then it's probably overfit."

### Pure Temporal Coordinates

Clean calendar arithmetic from `bar.timestamp`. No state. No event tracking. O(1) compute per bar. Sin/cos encodings preserve circular distance — Friday (dow=4) is 1 day from Thursday (3), 6 days from Wednesday (2). Raw integers don't encode this.

| Feature | Formula | Varies at | What it captures |
|---|---|---|---|
| `dow_sin`, `dow_cos` | `sin(2π * dow / 7)`, `cos(...)` | Every bar | Day-of-week cycle (preserves Friday-Monday = 3 days, not 4) |
| `hour_of_day_sin`, `hour_of_day_cos` | `sin(2π * hour / 24)`, `cos(...)` | Every bar | Intraday cycle (23:00 is 1 hour from 00:00, not 23 hours) |
| `week_of_month_sin`, `week_of_month_cos` | `sin(2π * week / 5)`, `cos(...)` | Every bar | Position within month (week 1-5), for "3rd Friday" OPEX effects |
| `day_of_month_sin`, `day_of_month_cos` | `sin(2π * day / 31)`, `cos(...)` | Every bar | Month-cycle position (for month-end, dividend dates, etc.) |
| `week_of_year_sin`, `week_of_year_cos` | `sin(2π * week / 52)`, `cos(...)` | Every bar | Intra-annual seasonality (Q1 vs Q4, holiday periods) |
| `month_sin`, `month_cos` | Already in factory | Every bar | Annual cycle (seasonal effects) |

**Existing features:** `dow_sin/cos`, `month_sin/cos`, `session_time_pos` (linear 0-1 intraday position).

**What we're adding:**
- `hour_of_day_sin/cos` — circular version of `session_time_pos`, cleaner for intraday effects
- `week_of_month_sin/cos` — NEW, precise "3rd Friday" OPEX encoding (week 3 + dow = Friday)
- `day_of_month_sin/cos` — NEW, captures month-cycle patterns (month-end, dividend dates)
- `week_of_year_sin/cos` — NEW, captures intra-annual seasonality (turn-of-month, Q-effects)

**Why sin/cos and not raw numbers?**

Raw `dow = 3` (Wednesday) doesn't encode that Thursday (4) is 1 day away and Monday (0) is 3 days away. Sin/cos preserve circular distance in 2D space. That's geometry, not market theory. The ensemble learns the pattern if it exists.

**How the ensemble discovers calendar effects:**

Given `dow_sin/cos` + `week_of_month_sin/cos` + `day_of_month_sin/cos` + `week_of_year_sin/cos` + `month_sin/cos` + price/volume features, the ensemble can discover:

- "When `week_of_month` ≈ 3 AND `dow` ≈ Friday (3rd Friday) and `vol_z` > 2, next-bar returns are negative" — OPEX pin risk, discovered
- "When `week_of_year` ≈ 51 (last week) and `volume_z` > 1.5, momentum reverses" — window dressing, discovered
- "When `dow` ≈ 1 (Monday) and `overnight_gap` > 2σ, returns are negative" — Monday effect, discovered

No theory. No state. Just coordinates.

**Implementation:**

```python
def hour_of_day_sin(dt: datetime) -> float:
    hour = dt.hour + dt.minute / 60
    return sin(2 * pi * hour / 24)

def hour_of_day_cos(dt: datetime) -> float:
    hour = dt.hour + dt.minute / 60
    return cos(2 * pi * hour / 24)

def week_of_month_sin(dt: datetime) -> float:
    # Week of month: 1-5 (some months have 5 partial weeks)
    # First week = week containing day 1
    week = (dt.day - 1) // 7 + 1
    return sin(2 * pi * week / 5)

def week_of_month_cos(dt: datetime) -> float:
    week = (dt.day - 1) // 7 + 1
    return cos(2 * pi * week / 5)

def day_of_month_sin(dt: datetime) -> float:
    return sin(2 * pi * dt.day / 31)

def day_of_month_cos(dt: datetime) -> float:
    return cos(2 * pi * dt.day / 31)

def week_of_year_sin(dt: datetime) -> float:
    _, week, _ = dt.isocalendar()
    return sin(2 * pi * week / 52)

def week_of_year_cos(dt: datetime) -> float:
    _, week, _ = dt.isocalendar()
    return cos(2 * pi * week / 52)
```

No APR keys needed. No state. Pure function of `bar.timestamp`.

**Natural score ranges:**

All sin/cos features are bounded [-1, 1]. Ready as-is for linear models. No normalization needed.

### Storage and Pre-Optimization: Don't

**Question:** At 5m TF, `week_of_month` is constant for all 78 bars in a day. Does this "waste space" in the feature vector?

**Renaissance answer:** Who cares? Storage is cheap. Signal is expensive.

**Cost:**
- `week_of_month` = 8 bytes per row (float64)
- 5m TF: ~196,000 rows/year/symbol → ~1.6 MB/year/symbol
- 58 ETFs: ~93 MB/year total

**Benefit:** If `week_of_month + dow = Friday` has IC Sharpe > 0.5 and p < 0.05, it pays for itself 1000x over. If it doesn't, IC engine prunes it.

**Why not HTF join?** Pull `week_of_month` from daily table at analysis time. But this breaks the DAG — features should compute from the bar in front of you, not via cross-TF join. Stateful joins add complexity. Renaissance avoided them.

**Pre-optimization is premature.** Throw everything at the wall. Let IC decide. Renaissance's "499+ signals" included many redundancies and constants at certain cadences. The ensemble pruned. Signal survived.

**Feature clustering (todo 009) handles redundancy.** `week_of_month` and `day_of_month` will cluster. If one survives IC and the other doesn't, we keep the survivor. No human judgment needed.

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
| [-1, 1] naturally | `body_ratio`, `ret_autocorr_1`, `ret_autocorr_5`, `vol_persistence`, `price_vol_corr_*`, `high_low_corr`, ALL sin/cos temporal coords (`dow_*`, `hour_of_day_*`, `day_of_month_*`, `week_of_year_*`, `month_*`) | Ready as-is | Ready as-is |
| [0, 1] naturally | `upper_wick_ratio`, `lower_wick_ratio`, `new_high_flag`, `new_low_flag`, `vol_percentile`, `up_vol_ratio_*`, `range_efficiency`, `stoch_k_*`, `mfi_*`, `price_percentile_*`, `efficiency_ratio_*`, `session_time_pos` | Shift to [-1,1]: `(x - 0.5) * 2` | Ready as-is |
| Binary {0, 1} | `new_high_flag`, `new_low_flag` | Ready as-is | Ready as-is |
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

## Feature Catalog By Computation Order

**Renaissance approach**: Build all primitives, let IC engine decide what matters. No human prioritization.

**Grouping below is for catalog organization only** — computation order, not strategic priority. IC engine determines which features have signal.

### 1st Order Primitives (Raw OHLCV Transforms)

Features computed directly from OHLCV with no intermediate features:

**From Bar Anatomy Ratios section:**
- `body_ratio`, `upper_wick_ratio`, `lower_wick_ratio`
- `range_vs_atr`, `close_vs_open_direction`
- `overnight_gap`, `overnight_gap_z`
- `range_efficiency`

**From Lagged Return Series section:**
- `ret_lag_1`, `ret_lag_2`, `ret_lag_3`
- `ret_lag_fast`, `ret_lag_mid`, `ret_lag_slow`

**From Volume Structure Primitives section:**
- `vol_acceleration`, `vol_percentile`

**From Open-to-Close Split section:**
- `open_ret`, `intraday_ret`, `open_vs_intraday`
- `session_time_pos` (no OHLCV, pure timestamp)

**From Temporal Coordinate Primitives section:**
- `dow_sin`, `dow_cos` (existing)
- `hour_of_day_sin`, `hour_of_day_cos` (NEW)
- `week_of_month_sin`, `week_of_month_cos` (NEW)
- `day_of_month_sin`, `day_of_month_cos` (NEW)
- `week_of_year_sin`, `week_of_year_cos` (NEW)
- `month_sin`, `month_cos` (existing)
- `session_time_pos` (existing, no OHLCV, pure timestamp)

**From Flow Activity Primitives section:**
- `volume_change`, `volume_pct_change`
- `trade_count_change`
- `range_pct_change`
- `ret_lag_1` (duplicate, listed here for context)

**From Breakout Distance Primitives section:**
- `dist_from_high_fast`, `dist_from_high_slow`
- `dist_from_low_fast`, `dist_from_low_slow`
- `range_pct_fast`, `range_pct_slow` (duplicate concept)
- `new_high_flag`, `new_low_flag`

### 2nd Order Primitives (Transforms of 1st Order Features)

Features computed from 1st-order primitives or require rolling windows:

**From Volume Structure Primitives section:**
- `dollar_vol_z`, `vol_range_ratio`, `vol_trend_ratio`
- `up_vol_ratio_fast`, `up_vol_ratio_slow`
- `vol_persistence`, `vol_std_z`
- `mfi_fast`, `mfi_slow`, `obv_z`

**From Realized Variance and Volatility Primitives section:**
- `realized_var_ratio_fast`, `realized_var_ratio_slow`
- `range_to_close`, `true_range_pct`
- `vol_of_vol`, `high_low_corr`
- `variance_ratio_fast`, `variance_ratio_slow`
- `vol_asymmetry_z`
- `bb_pct_b_fast`, `bb_pct_b_slow`
- `hv_z_fast`, `hv_z_slow`, `hv_ratio`

**From Alternative Volatility Estimators section:**
- `parkinson_vol_z`, `garman_klass_vol_z`, `yang_zhang_vol_z`

**From Breakout Distance Primitives section:**
- `stoch_k_fast`, `stoch_k_slow`
- `price_percentile_fast`, `price_percentile_slow`
- `efficiency_ratio_fast`, `efficiency_ratio_slow`

**From Return Distribution Primitives section:**
- `ret_kurtosis_z_fast`, `ret_kurtosis_z_slow`
- `ret_autocorr_1`, `ret_autocorr_5`
- `updown_ratio_fast`, `updown_ratio_slow`
- `streak_z`

**From Flow Activity Primitives section:**
- `volume_acceleration` (2nd derivative: change of change)
- `volume_z_5` (z-score = 2nd order: mean/std of 1st order)
- `trade_count_acceleration` (2nd derivative)
- `body_ratio_change` (change of 1st-order `body_ratio`)
- `trade_count_z_5` (z-score = 2nd order)

**From Interaction Primitives (Price × Volume) section:**
- `vol_body_product` (product of 2nd-order × 2nd-order)
- `ret_vol_product_fast` (product of 1st-order × 2nd-order)
- `price_vol_corr_fast`, `price_vol_corr_slow` (correlation of 1st-order × 1st-order)
- `range_vol_product` (product of 1st-order × 2nd-order)
- `up_vol_body_diff` (difference of 2nd-order × 1st-order)
- `ret_vol_ratio_fast` (ratio of 1st-order / 2nd-order)
- `vol_skew_product` (product of 2nd-order × 2nd-order)

**From Cross-Timeframe Divergences section:**
- `ret_div_1m_5m`, `ret_div_5m_1h`, `ret_div_1h_1d` (difference of 1st-order features across TFs)

### 3rd Order Primitives (Composites / Aggregates)

Features that combine or aggregate multiple lower-order features:

**From Flow Activity Primitives section (removed):**
- (Previously: `crowding_index` = weighted composite of 4 market-level aggregations)
- (Replaced with 1st/2nd-order primitives above — let ensemble discover patterns)

**Note**: No 3rd-order primitives in current catalog. Renaissance avoids pre-judging composites — prefers throwing 1st/2nd-order primitives at ensemble and letting models discover interactions.

---

## Flow Activity Primitives (First-Order)

**Renaissance approach**: Don't pre-judge what "crowding" means. Provide raw primitives that measure flow activity. Let the IC engine + ensemble discover patterns like "when volume_z is high across many symbols, momentum features have lower IC."

**No cross-sectional theory**: These are per-symbol primitives — no market averages, no correlation matrices, no assumptions about what counts as "synchronized."

### Feature 1: Volume Change

**Feature name**: `volume_change`

**First-order primitive** — raw change in volume from prior bar.

**Formula**:
```python
volume_change = volume_t - volume_{t-1}
```

**What it captures**: Is volume increasing or decreasing vs prior bar? (no window, no normalization)

**Natural score range**: Unbounded, centered at 0. Ready as-is for linear models.

**APR parameters**: None (no window)

**Renaissance rationale**: Pure first-order change. Ensemble discovers if "volume_change is positive for many ETFs" predicts IC decay.

### Feature 2: Volume Percentage Change

**Feature name**: `volume_pct_change`

**First-order primitive** — rate of change in volume.

**Formula**:
```python
volume_pct_change = (volume_t - volume_{t-1}) / volume_{t-1}
```

**What it captures**: Percentage change in volume (scale-independent).

**Natural score range**: Unbounded, centered at 0. For large moves: bounded approximately [-1, ∞). Ready as-is for tree models; winsorize or log-transform for linear.

**APR parameters**: None (no window)

**Renaissance rationale**: Scale-free rate of change. Ensemble discovers patterns in volume expansion rates.

### Feature 3: Volume Acceleration

**Feature name**: `volume_acceleration`

**Second-order primitive** — change in volume change.

**Formula**:
```python
volume_acceleration = volume_change_t - volume_change_{t-1}
```

**What it captures**: Is volume change speeding up or slowing down? (second derivative)

**Natural score range**: Unbounded, centered at 0. Ready as-is for tree models; z-score for linear.

**APR parameters**: None (no window beyond parent `volume_change`)

**Renaissance rationale**: Pure acceleration. Ensemble discovers if "volume_acceleration is positive for many ETFs" signals regime shift.

### Feature 4: Short-Window Volume Z

**Feature name**: `volume_z_5`

**First-order primitive** — volume z-score over short window.

**Formula**:
```python
volume_z_5 = (volume_t - mean(volume_{t-5...t})) / std(volume_{t-5...t})
```

**What it captures**: Is current volume unusual vs recent 5-bar history? (different timescale than existing `volume_z` which uses 20-bar window)

**Natural score range**: Unbounded, centered at 0. Ready as-is for linear models.

**APR parameters**:
- `feature.volume.z_5_window = 5`

**Renaissance rationale**: Short-term normalization. Different timescale may capture different dynamics. Ensemble discovers which window matters.

### Feature 5: Trade Count Change

**Feature name**: `trade_count_change`

**First-order primitive** — raw change in trade count.

**Formula**:
```python
trade_count_change = trade_count_t - trade_count_{t-1}
```

**What it captures**: Is trading activity increasing or decreasing? (no window, raw count)

**Natural score range**: Unbounded, centered at 0. Ready as-is for tree models; z-score for linear.

**APR parameters**: None (no window)

**Renaissance rationale**: Pure activity change. Ensemble discovers if "trade_count_change is positive for many ETFs" predicts momentum decay.

### Feature 6: Trade Count Acceleration

**Feature name**: `trade_count_acceleration`

**Second-order primitive** — change in trade count change.

**Formula**:
```python
trade_count_acceleration = trade_count_change_t - trade_count_change_{t-1}
```

**What it captures**: Is activity change speeding up or slowing down?

**Natural score range**: Unbounded, centered at 0. Ready as-is for tree models; z-score for linear.

**APR parameters**: None (no window beyond parent)

**Renaissance rationale**: Second derivative of activity. Ensemble discovers acceleration patterns.

### Feature 7: Range Percentage Change

**Feature name**: `range_pct_change`

**First-order primitive** — rate of change in bar range.

**Formula**:
```python
range_pct_change = ((high_t - low_t) - (high_{t-1} - low_{t-1})) / (high_{t-1} - low_{t-1})
```

**What it captures**: Is volatility expanding or contracting? (percentage change in range)

**Natural score range**: Unbounded, centered at 0. For large moves: bounded approximately [-1, ∞). Ready as-is for tree models; winsorize for linear.

**APR parameters**: None (no window)

**Renaissance rationale**: Volatility expansion rate. Ensemble discovers if "range_pct_change is positive across market" signals regime shift.

### Feature 8: Body Ratio Change

**Feature name**: `body_ratio_change`

**Second-order primitive** — change in directional conviction.

**Formula**:
```python
body_ratio_change = body_ratio_t - body_ratio_{t-1}
# where body_ratio = (close - open) / (high - low)
```

**What it captures**: Is directional conviction strengthening or weakening?

**Natural score range**: Bounded [-2, 2] (body_ratio is [-1, 1], change is difference). Ready as-is for linear models.

**APR parameters**: None (no window beyond parent `body_ratio`)

**Renaissance rationale**: Conviction acceleration. Ensemble discovers if "body_ratio_change is negative for many ETFs" (conviction weakening) predicts momentum reversal.

### Feature 9: Return Lag-1 (Fast)

**Feature name**: `ret_lag_1`

**First-order primitive** — 1-bar log return (already in Lagged Return Series section, duplicated here for flow activity context).

**Formula**:
```python
ret_lag_1 = log(close_t / close_{t-1})
```

**What it captures**: Raw 1-bar return (foundation for all return-based features).

**Natural score range**: Unbounded, centered near 0. Ready as-is for linear models.

**APR parameters**: None (definitional)

**Renaissance rationale**: Foundational primitive. Ensemble discovers serial autocorrelation patterns.

### Feature 10: Trade Count Z-Score (Short Window)

**Feature name**: `trade_count_z_5`

**First-order primitive** — trade count z-score over short window.

**Formula**:
```python
trade_count_z_5 = (trade_count_t - mean(trade_count_{t-5...t})) / std(trade_count_{t-5...t})
```

**What it captures**: Is current activity unusual vs recent 5-bar history? (short-term burst detection)

**Natural score range**: Unbounded, centered at 0. Ready as-is for linear models.

**APR parameters**:
- `feature.trade_count.z_5_window = 5`

**Renaissance rationale**: Short-term activity normalization. Different timescale than standard windows. Ensemble discovers if bursts predict anything.

### Expected Renaissance Discovery

If flow synchronization/crowding is a real phenomenon, the ensemble will discover patterns like:

- "When `volume_z_5` > 1.0 for >70% of ETFs, `momentum_z_fast` IC drops by 40%"
- "When `trade_count_change` is positive for SPY, QQQ, IWM simultaneously, next-bar returns are negative"
- "When `range_pct_change` > 0.5 across market, volatility regime is shifting"

**No human theory required** — just raw primitives + IC engine + ensemble discovery.

### Priority Assessment

**Where these fit in the overall priority order**:

These are **P2-P3** (high priority) because:

1. **True primitives**: First or second-order transforms, no cross-sectional theory
2. **Zero or low cost**: Most require no window beyond the parent feature
3. **Fill gaps**: We have `volume_z` (window=20) but no short-window versions; we have no acceleration features
4. **Renaissance-grade**: Exactly the type of simple transform Medallion uses by the thousands

**Recommended trigger**: Alongside foundational primitives (bar anatomy, lagged returns). These are raw inputs that the ensemble needs to discover ANY flow-related patterns.

**Implementation order**:
1. Add to `feature_factory.py` (straightforward, same pattern as existing primitives)
2. Backfill via `corpus_pipeline_run.sh`
3. IC engine evaluates independently
4. If any have IC, ensemble trainer discovers cross-symbol patterns automatically

**See also**: `comomentum-crowding-metric.md` for the theory-heavy approach we chose NOT to use. Renaissance's approach is: provide raw primitives, let the data speak.
## What This Is Not

This is not a plan. No phase assigned. These are candidates for IC testing when we
have the full 58-symbol corpus running and the IC engine is stable. The right trigger
is: IC engine producing stable results on current 54 features, corpus complete,
and a deliberate decision to expand the primitive basket.
