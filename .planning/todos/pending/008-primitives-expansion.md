# 008 — Feature Primitives Expansion (~60 candidates)

**Priority: Medium-High — next feature set chapter after clean corpus + IC validation on existing 54.**
**Gate: 001 (batch primitives fix) complete + clean 58-symbol corpus + IC discovery on 54 features confirms stable results.**
**Idea doc:** `docs/ideas/renaissance-primitives-ohlcv.md` — formulas, naming conventions, score ranges, full priority order.

---

## Context

Feature Factory currently produces 54 features. The idea doc catalogs ~60 additional primitives
derivable purely from OHLCV — no market theory, no S/R zones, no regime. IC engine decides
what's predictive. Adding features = adding fields to `FeatureVector` + schema migration +
`FeatureFactory` implementation. IC discovery on the new fields runs automatically in the
next corpus pipeline pass.

**Do not add features before the existing 54 are validated.** Expand after IC results on the
current set give a stable baseline.

---

## Priority Order (from idea doc)

### Tier 1 — Add first (zero/near-zero cost, clearly missing)

**Bar anatomy ratios** (no window, O(1)):
- `body_ratio` — `(C - O) / (H - L)`, bounded [-1, 1], directional conviction
- `upper_wick_ratio` — `(H - max(O,C)) / (H - L)`, rejection from highs
- `lower_wick_ratio` — `(min(O,C) - L) / (H - L)`, rejection from lows
- `range_efficiency` — `abs(C - prev_C) / (H - L)`, how efficiently price moved vs range explored
- `overnight_gap` — `(O - prev_C) / prev_C`
- `overnight_gap_z` — z-score of above, window = APR `feature.overnight_gap.window`
- `range_vs_atr` — `(H - L) / ATR_N`, bar width vs recent norm

**Session time position** (no window, pure timestamp):
- `session_time_pos` — `bar_index_in_session / total_session_bars`, continuous [0,1] intraday position

### Tier 2 — Alternative vol estimators (strictly more efficient use of OHLCV)

- `parkinson_vol_z` — z-score of `ln(H/L)^2 / (4*ln(2))`; ~5x more efficient than close-to-close
- `garman_klass_vol_z` — GK estimator using O/H/L/C: `0.5*ln(H/L)^2 - (2*ln(2)-1)*ln(C/O)^2`
- `yang_zhang_vol_z` — YZ = `var(overnight) + k*var(open-to-close) + (1-k)*var(GK)`

All three single normalization window: APR `feature.parkinson_vol.window` etc.

### Tier 3 — Breakout distance (theory-free analog of S/R features)

- `dist_from_high_fast/slow` — `(rolling_high_N - C) / ATR`, gradient windows
- `dist_from_low_fast/slow` — `(C - rolling_low_N) / ATR`, gradient windows
- `stoch_k_fast/slow` — `(C - L_N) / (H_N - L_N)`, price in rolling H/L range
- `efficiency_ratio_fast/slow` — `abs(C_t - C_{t-N}) / sum(|C_i - C_{i-1}|)`, Kaufman ER, bounded [0,1]
- `price_percentile_fast/slow` — rolling percentile rank of close in N-bar distribution
- `new_high_flag`, `new_low_flag` — binary breakout detection

### Tier 4 — Lagged return series (autocorrelation alpha)

- `ret_lag_1`, `ret_lag_2`, `ret_lag_3` — `log(C_t / C_{t-N})`, definitional (numbers, not gradient)
- `ret_lag_fast/mid/slow` — gradient windows, APR `feature.ret_lag.fast/mid/slow`
- `ret_autocorr_1`, `ret_autocorr_5` — lag-1 and lag-5 autocorrelation, bounded [-1, 1]

### Tier 5 — Open/intraday split

- `open_ret` — `log(O_t / C_{t-1})`, overnight component
- `intraday_ret` — `log(C_t / O_t)`, within-session component

### Tier 6 — Variance ratio (empirical random-walk deviation)

- `variance_ratio_fast/slow` — `var(ret, N) / (N * var(ret, 1))`; >1 = trending, <1 = mean-reverting

### Tier 7 — Volume structure (expanded)

- `vol_trend_ratio` — `vol_MA_fast / vol_MA_slow`, gradient
- `up_vol_ratio_fast/slow` — fraction of volume on up bars, bounded [0,1]
- `vol_percentile` — rolling percentile rank of volume
- `mfi_fast/slow` — Money Flow Index (volume-weighted RSI), gradient; ref: archived `i1_indicators/mfi.py`
- `obv_z` — z-score of OBV over rolling window; ref: archived `i1_indicators/obv.py`
- `dollar_vol_z` — z-score of `V * C`

### Tier 8 — Stochastic %K, Bollinger %B, HV (reference implementations in archive)

- `bb_pct_b_fast/slow` — `(C - lower_band) / (upper_band - lower_band)`, variance-normalized price position
- `hv_z_fast/slow` — close-to-close HV z-score; ref: archived `i1_indicators/historical_volatility.py`

### Tier 9 — Return distribution, vol asymmetry, streak

- `ret_kurtosis_z_fast/slow` — rolling kurtosis z-score
- `vol_asymmetry_z` — z-score of `std(ret|up) / std(ret|down)` (leverage effect without GARCH)
- `streak_z` — z-score of current directional streak length
- `updown_ratio_fast/slow` — count(up bars) / count(down bars)

### Tier 10 — Interaction primitives (after Tier 1-4 atomics land)

- `vol_body_product` — `body_ratio * volume_z`
- `price_vol_corr_fast/slow` — rolling Pearson(`|ret_lag_1|`, V)
- `ret_vol_product_fast` — `ret_lag_fast * volume_z`
- Cross-TF divergence: `ret_div_1m_5m`, `ret_div_5m_1h`, `ret_div_1h_1d` (requires HTF cache)

---

## Implementation Pattern

Each new feature follows the existing factory pattern:
1. Add field(s) to `FeatureVector` dataclass (`src/intelligence/feature_factory.py`)
2. Add schema migration (new float column(s) in `feature_vectors`)
3. Implement as `_*_series_full()` function — pure numpy, no side effects
4. Wire into `FeatureFactory.compute()` and `compute_batch()`
5. Add APR keys for any window parameters
6. Re-run `backfill_feature_factory --compute-only` and IC pipeline

**Do Tier 1 + 2 as one batch** (all no-window or single-window, low risk, fast to validate).
**Add Tiers 3-5 as second batch** after Tier 1+2 IC results confirm the pattern works.
**Interaction primitives last** — require parent atomics to be computed first.

See idea doc §"Implementation Notes" for normalization requirements per feature type.
