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

**Natural score ranges:**
- `body_ratio` — mathematically bounded [-1, 1]. No normalization needed. Usable directly in linear models.
- `upper_wick_ratio`, `lower_wick_ratio` — bounded [0, 1]. Centered at 0.5 not 0, so want `(ratio - 0.5) * 2` for linear models. Fine as-is for tree-based.
- `close_vs_open_direction` — {-1, 0, +1} categorical.
- `range_vs_atr`, `overnight_gap`, `overnight_gap_z` — unbounded, need z-scoring before linear use.

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

## Cross-Timeframe Return Divergence

We have CTF features but they encode alignment theory. These are raw divergences
between timeframe returns — no judgment about which direction is "right."

| Feature | Formula | What it captures |
|---|---|---|
| `ret_div_1m_5m` | `ret_1m_last - ret_5m_last` | Intraday vs 5m drift disagreement |
| `ret_div_5m_1h` | `ret_5m_last - ret_1h_last` | Short vs medium disagreement |
| `ret_div_1h_1d` | `ret_1h_last - ret_1d_last` | Intraday vs daily disagreement |

These require pulling the corresponding bar from the HTF cache — already available
via `feature_cache.py`.

---

## Volume Structure Primitives

Beyond z-scores of volume level.

| Feature | Formula | What it captures |
|---|---|---|
| `vol_acceleration` | `V_t / V_{t-1}` | Volume surge (not mean-relative, bar-relative) |
| `dollar_vol_z` | z-score of `V * C` | Size-adjusted flow — large caps vs small get comparable signal |
| `vol_body_product` | `body_ratio * volume_z` | Direction x volume confirmation — no theory, just product |
| `vol_range_ratio` | `V_t / (H - L)` normalized | Volume per unit of price range |

---

## Realized Variance and Volatility Primitives

| Feature | Formula | What it captures |
|---|---|---|
| Feature | Formula | Naming | What it captures |
|---|---|---|---|
| `realized_var_ratio` | `realized_var_fast / realized_var_slow`, windows = APR `feature.realized_var.fast/slow` | **Gradient** (via APR window keys) | Vol regime shift — short vol accelerating vs long vol |
| `range_to_close` | `(H - L) / C` | None (no window) | Absolute range normalized to price level |
| `true_range_pct` | `TR / C` | None (no window) | ATR as fraction of price |
| `vol_of_vol` | Rolling std of `atr_z`, N = APR `feature.vol_of_vol.window` | APR-backed (single window, no gradient needed) | Second-order volatility |
| `high_low_corr` | Correlation of H and L over N bars, N = APR `feature.high_low_corr.window` | APR-backed (single window) | Trending vs oscillating structure |

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

Window N is pure calibration ("what counts as recent vs long-term") - gradient naming,
APR-backed. No migration needed to change window lengths.

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

**Natural score ranges:**
- `ret_autocorr_1`, `ret_autocorr_5` — mathematically bounded [-1, 1]. No normalization needed. Pure mean-reversion = -1, pure momentum = +1. Directly usable in linear models.
- `ret_kurtosis_z_*` — z-scored, unbounded but centered at 0.
- `updown_ratio_*` — [0, ∞), needs log or percentile transform for linear models.

---

## Open-to-Close Split

| Feature | Formula | What it captures |
|---|---|---|
| `open_ret` | `log(O_t / C_{t-1})` | Overnight component of return |
| `intraday_ret` | `log(C_t / O_t)` | Within-session component |
| `open_vs_intraday` | `open_ret - intraday_ret` | Whether overnight or intraday component dominates |

These decompose total return into its two structural pieces. Overnight gaps driven by
news; intraday driven by order flow. Predictability differs by regime.

---

## Implementation Notes

**Natural score ranges — which features need normalization.**

| Range | Features | Linear model | Tree model |
|---|---|---|---|
| [-1, 1] naturally | `body_ratio`, `ret_autocorr_1`, `ret_autocorr_5` | Ready as-is | Ready as-is |
| [0, 1] naturally | `upper_wick_ratio`, `lower_wick_ratio`, `new_high_flag`, `new_low_flag` | Shift to [-1,1]: `(x - 0.5) * 2` | Ready as-is |
| Unbounded, centered | z-scored features (`ret_kurtosis_z_*`, `overnight_gap_z`, etc.) | Ready as-is | Ready as-is |
| Unbounded, uncentered | Raw ratios (`range_vs_atr`, `vol_acceleration`, `updown_ratio_*`, log returns) | Need z-score or percentile | Ready as-is |

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
| `updown_ratio_fast/slow` | |

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

1. **Bar anatomy ratios** - zero cost, clearly missing, analogous to known Simons inputs
2. **Lagged return series** - foundational; autocorrelation alpha is well-documented
3. **Open/intraday split** - low cost, captures overnight vs session structure
4. **Breakout distance** - raw version of what S/R features approximate with theory
5. **Volume structure** - extends existing OFI/CMF coverage
6. **Cross-TF divergence** - requires HTF cache, already available
7. **Return distribution** - kurtosis/autocorr require longer windows, higher variance

---

## What This Is Not

This is not a plan. No phase assigned. These are candidates for IC testing when we
have the full 58-symbol corpus running and the IC engine is stable. The right trigger
is: IC engine producing stable results on current 54 features, corpus complete,
and a deliberate decision to expand the primitive basket.
