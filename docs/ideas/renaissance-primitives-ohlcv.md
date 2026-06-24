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

Notes:
- `body_ratio` is already partially captured by `bar_close_pos` and `range_position`
  but the signed body ratio is distinct.
- `upper_wick_ratio` and `lower_wick_ratio` are not in the factory at all.

---

## Lagged Return Series

Pure price-change primitives at fixed lookbacks. These are the most common
Renaissance inputs. Serial autocorrelation — positive or negative — is invisible
to our current momentum features (which use z-scores of price vs MA, not return lags).

| Feature | Formula | Lookback |
|---|---|---|
| `ret_lag_1` | `log(C_t / C_{t-1})` | 1 bar |
| `ret_lag_2` | `log(C_t / C_{t-2})` | 2 bars |
| `ret_lag_3` | `log(C_t / C_{t-3})` | 3 bars |
| `ret_lag_5` | `log(C_t / C_{t-5})` | 5 bars |
| `ret_lag_10` | `log(C_t / C_{t-10})` | 10 bars |
| `ret_lag_20` | `log(C_t / C_{t-20})` | 20 bars |
| `ret_lag_60` | `log(C_t / C_{t-60})` | 60 bars |

Note: these are distinct from `momentum_z_fast/mid/slow`. Those z-score price vs a
moving average. Lagged log returns measure serial return correlation directly — the
input to autocorrelation-based alpha.

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
| `realized_var_ratio` | `realized_var_N_short / realized_var_N_long` | Vol regime shift — short vol accelerating vs slow vol |
| `range_to_close` | `(H - L) / C` | Absolute range normalized to price level |
| `true_range_pct` | `TR / C` | ATR denominated as fraction of price |
| `vol_of_vol` | Rolling std of `atr_z` | Second-order volatility |
| `high_low_corr` | Correlation of H and L over N bars | Trending vs oscillating structure |

---

## Breakout Distance Primitives

No S/R zone theory — just raw distance from recent extremes.

| Feature | Formula | What it captures |
|---|---|---|
| `dist_from_N_high` | `(rolling_high_N - C) / ATR` | Distance from N-bar high, ATR-normalized |
| `dist_from_N_low` | `(C - rolling_low_N) / ATR` | Distance from N-bar low, ATR-normalized |
| `high_low_range_pct` | `(rolling_high_N - rolling_low_N) / C` | N-bar range as % of price — consolidation vs expansion |
| `new_high_flag` | `1 if C == rolling_high_N else 0` | Binary breakout detection |
| `new_low_flag` | `1 if C == rolling_low_N else 0` | Binary breakdown detection |

Typical N: 20, 60, 252 bars. Each N is a separate feature column.

---

## Return Distribution Primitives

We have `ret_skew_z`. Missing:

| Feature | Formula | What it captures |
|---|---|---|
| `ret_kurtosis_z` | z-score of rolling kurtosis of returns | Fat-tail regime — crash/melt-up risk |
| `ret_autocorr_1` | lag-1 autocorrelation of `ret_lag_1` over N bars | Mean-reversion vs momentum regime |
| `ret_autocorr_5` | lag-5 autocorrelation | Weekly mean-reversion |
| `updown_ratio` | count(positive bars) / count(negative bars) over N | Win-rate of recent bars |

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

**All of these are APR-backed.** Window lengths (N) must go into `config_state`
under `feature.*` namespace. Column names use gradient naming for tunable windows
(`dist_from_high_fast`, `dist_from_high_slow`) rather than encoding the N directly.

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
