# AlphaEngine V1 — Information Coefficient Methodology

**Date:** 2026-06-20
**Status:** Active — binding pre-implementation specification
**Milestone:** v3.0
**Reads alongside:**
- `docs/plans/2026-06-20-analogengine-design.md` — the technical "how"
- `docs/plans/2026-06-20-alphaengine-ic-spec.md` — the strategic "why"

---

## I. The Standard

> "We don't start with models. We start with data. We don't have any preconceived notions.
> We look for things that can be replicated thousands of times." — Jim Simons

This document specifies the exact methodology for Information Coefficient (IC) measurement,
feature extraction, ensemble weight derivation, and alpha emission in AlphaEngine V1. Every
decision here is binding on the implementation. No IC measurement begins until this specification
is settled, because methodological choices made after observing data are not methodology — they
are data mining dressed as methodology.

**The test for every decision in this document:** Would a senior quant at Renaissance accept it
as statistically sound? If a decision requires researcher judgment to make the numbers look
better, it fails. If the data forces the decision independent of what the researcher wants to
see, it passes.

---

## II. Data Inventory

**v3.0 data source: `feature_vectors`** — populated by FeatureFactory from `market_data_ohlcv`.

Before Phase A FeatureFactory backfill runs, `feature_vectors` does not exist. The data
inventory below describes what Phase A will produce and what Phase B (IC Engine) requires.

**Target state after Phase A backfill:**

| TF  | Target rows/symbol | Date range (ETFs)           | Symbols (58 ETFs) |
|-----|--------------------|-----------------------------|-------------------|
| 5m  | ~490,000           | 2021 — present (5 yr)       | SPY, QQQ, IWM, TLT + 54 others |
| 15m | ~163,000           | 2016 — present (10 yr)      | SPY, QQQ, IWM, TLT + 54 others |
| 1h  | ~40,000            | 2011 — present (15 yr)      | SPY, QQQ, IWM, TLT + 54 others |
| 1d  | ~5,040             | 2006 — present (20 yr)      | SPY, QQQ, IWM, TLT + 54 others |

**Schema:** `feature_vectors` — explicit typed columns (no JSONB), one row per
(symbol, tf, bar_ts). Columns: `pipeline_version`, `regime`, `regime_label_source` (always
`'filtered'` — forward Viterbi, causal), plus 50 named feature columns (see §VI.3). Open
prices for forward return computation come from `market_data_ohlcv` (column `open`,
time column `timestamp`, timeframe column `timeframe`).

**Prerequisite:** `market_data_ohlcv` must contain ETF bar data at the target depths above.
SPY/QQQ/IWM/TLT are the anchor symbols; all others backfill at best-available depth.

---

## III. Data Requirements (Prerequisite to Phase A)

The current data is insufficient for statistically valid IC measurement. Phase A does not begin
until these requirements are met.

### III.1 Minimum N for IC Estimation

| Computation                    | Minimum independent observations |
|-------------------------------|----------------------------------|
| IC point estimate              | 500                              |
| Bootstrap CI (reliable bounds) | 500                              |
| IC Sharpe (requires time series)| 10 non-overlapping IC windows × 500 obs = 5,000 minimum |
| Walk-forward fold              | 500 per fold                     |
| Walk-forward (3 folds)         | 1,500 + training window          |

The 500-observation floor (not 100) reflects that IC values in financial data are small
(0.02–0.08) and highly variable. At N=100, the confidence interval on IC=0.04 is
approximately ±0.10 — wider than the signal itself. At N=500, it narrows to ±0.04.

### III.2 Required Backfill

To reach 5,000 independent observations per (symbol, TF) for IC Sharpe computation, using
non-overlapping windows at the 5-bar lookahead (one observation every 5 bars):

| TF  | Obs per bar-5 | Need 5K obs → bars required |
|-----|---------------|-----------------------------|
| 1m  | 1/5           | 25,000 bars per symbol       |
| 5m  | 1/5           | 25,000 bars per symbol       |
| 15m | 1/5           | 25,000 bars per symbol       |
| 1h  | 1/5           | 25,000 bars per symbol       |

**Current shortfall:** The 1h data (42K rows across all symbols ≈ 3,500 per symbol) falls
well short. The 1m data (54K rows ≈ 4,500 per symbol, only 2 months) is insufficient for
a stable IC Sharpe.

**Resolution:** Run FeatureFactory backfill against `market_data_ohlcv` for ETF symbols.
SPY, QQQ, IWM, TLT have liquid 5m/1h/1d data going back 10+ years via IBKR. A single
ETF at 5m bars over 5 years produces ~78 bars/day × 252 days × 5 years = 98,280 bars.
At 1/5 sub-sampling, that is ~19,656 independent observations per symbol — nearly 4x the
minimum. FeatureFactory runs against raw `market_data_ohlcv` bars, not the old I1-I6
pipeline — `intelligence_features` is not used in v3.0.

**Backfill must complete before IC measurement begins.** This is a hard gate, not a
preference.

### III.3 Regime Stratification Requirement

IC measurement is **regime-stratified from the start**. Pooled IC (no regime conditioning)
is a weaker signal — it averages IC across market states where the same feature may have
positive IC in one state and negative IC in another. That averaging produces a near-zero
pooled IC for a feature that is highly predictive in both states, just in opposite
directions. The ensemble would discard it. This is a correctness failure.

The data requirement for regime stratification:

```
N_independent_per_regime_cell >= 500
Where regime_cell = (symbol, TF, regime_label)
```

With 4 HMM states and 25,000 bars per symbol (post-backfill, 1/5 sub-sampling):
~1,250 independent observations per cell. This exceeds the threshold.

**If backfill does not produce 500 independent observations per regime cell for a given
(symbol, TF), that (symbol, TF) pair is excluded from IC measurement entirely — not
downgraded to pooled.** Pooled IC is not a fallback. It is a different (weaker) statistic.

---

## IV. Data Integrity Prerequisites

These invariants must hold before any batch job writes IC data. Running IC on a corpus
without these guarantees produces measurements of unknown validity.

### IV.1 pipeline_version and regime_label_source

`feature_vectors` already has both columns in its DDL (Phase A FeatureFactory sets them
on every INSERT). No migration needed. Invariants:

- `pipeline_version` — set by FeatureFactory to the release tag at compute time
  (e.g., `'v3.0.0-alpha'`). If FeatureFactory is patched and features are recomputed,
  the new `pipeline_version` allows IC to be re-measured on corrected rows only.
- `regime_label_source` — always `'filtered'` in v3.0 (forward Viterbi, causal).
  No smoothed labels enter `feature_vectors`. The smoothed-vs-filtered bias present in
  the v2.x `intelligence_features` corpus does not apply.

### IV.2 market_data_ohlcv Completeness Check

Forward returns are computed from `open` prices in `market_data_ohlcv` using `LEAD()`.
Before the Outcome Labeler runs, verify that `open` is non-null for >= 99.9% of rows
in each (symbol, timeframe) window:

```sql
SELECT symbol, timeframe,
       count(*) FILTER (WHERE open IS NULL) AS null_opens,
       count(*) AS total
FROM market_data_ohlcv
WHERE symbol IN (SELECT symbol FROM instruments WHERE is_active = true
                 AND contract_details->>'asset_class' = 'equity')
GROUP BY symbol, timeframe
HAVING count(*) FILTER (WHERE open IS NULL) > 0;
```

If any rows return, investigate before proceeding. Null opens produce silent NULLs in
forward returns, which reduce effective N without any error.

---

## V. Forward Return Specification

### V.1 The Executable Return

The IC engine measures whether a feature score at bar T predicts price movement after T.
The relevant price movement is what a trader can actually capture — not the theoretical
return from T's close to T+N's close, but the return from the first executable entry
(open of bar T+1) to the exit (open of bar T+N+1).

```
R(T, N) = ln( open[T+N+1] / open[T+1] )
```

Where:
- T is the `ts` of the observation bar (bar close time)
- T+1 is the immediately following bar (earliest executable entry)
- T+N+1 is the exit bar (lookahead of N bars from entry)
- Log return is used throughout (additive, more normally distributed than arithmetic)

**What this rejects:** `ln(close[T+N] / close[T])` is wrong because close[T] is the
observation price, not the executable entry price. The difference is material for
short-horizon IC (1-bar lookahead) and in markets with opening gaps.

### V.2 Lookahead Windows

Four lookahead windows per TF:

| N (bars) | 1m equiv  | 5m equiv  | 1h equiv  | Purpose                  |
|----------|-----------|-----------|-----------|--------------------------|
| 1        | 1 min     | 5 min     | 1 hour    | Immediate predictability |
| 5        | 5 min     | 25 min    | 5 hours   | Short momentum/reversion |
| 20       | 20 min    | 100 min   | 20 hours  | Session-scale            |
| 60       | 1 hour    | 5 hours   | 60 hours  | Swing-scale              |

The IC engine measures all four for each feature. The ensemble uses the lookahead with the
highest IC Sharpe per (feature, TF, regime). No blending across lookaheads in V1.

### V.3 Computing Returns via LEAD()

Forward returns are computed from `market_data_ohlcv` (column `open`, time column
`timestamp`, timeframe column `timeframe`). This is the authoritative OHLCV source.
`feature_vectors` does not store raw OHLCV — the IC Engine joins both tables by
(symbol, tf, bar_ts).

```sql
-- Outcome Labeler core query
WITH ordered AS (
    SELECT
        symbol,
        timeframe AS tf,
        timestamp AS bar_ts,
        open AS bar_open,
        LEAD(open, 1)  OVER w AS open_t1,
        LEAD(open, 2)  OVER w AS open_t2,   -- entry T+1, exit T+2 for N=1
        LEAD(open, 6)  OVER w AS open_t6,   -- entry T+1, exit T+6 for N=5
        LEAD(open, 21) OVER w AS open_t21,  -- N=20
        LEAD(open, 61) OVER w AS open_t61,  -- N=60
        LEAD(timestamp, 1) OVER w AS next_ts
    FROM market_data_ohlcv
    WINDOW w AS (PARTITION BY symbol, timeframe ORDER BY timestamp
                 ROWS BETWEEN CURRENT ROW AND 61 FOLLOWING)
)
SELECT
    symbol, tf, bar_ts,
    LN(open_t2  / open_t1) AS return_1bar,
    LN(open_t6  / open_t1) AS return_5bar,
    LN(open_t21 / open_t1) AS return_20bar,
    LN(open_t61 / open_t1) AS return_60bar,
    -- Completeness: NULL open means bar didn't exist (gap or end of data)
    open_t2  IS NOT NULL AS complete_1bar,
    open_t6  IS NOT NULL AS complete_5bar,
    open_t21 IS NOT NULL AS complete_20bar,
    open_t61 IS NOT NULL AS complete_60bar,
    -- Gap flag: next bar is more than expected interval away
    CASE WHEN next_ts - bar_ts > (
        CASE tf
            WHEN '5m'  THEN interval '10 minutes'
            WHEN '15m' THEN interval '30 minutes'
            WHEN '1h'  THEN interval '2 hours'
            WHEN '1d'  THEN interval '3 days'
        END
    ) THEN true ELSE false END AS has_gap_before_entry
FROM ordered;
```

`has_gap_before_entry = true` means a market-hours gap (overnight, holiday) exists between
the observation bar and the entry bar. These observations are retained but flagged. IC
measured across gaps includes overnight risk premium — a structurally different phenomenon
from intraday IC. Phase A measures gap and non-gap IC separately; if they differ
significantly, gap observations are excluded from the production ensemble.

---

## VI. Feature Universe — V1 Quant Vector

### VI.1 Pre-Specification Requirement

The feature universe is **fully specified before any IC is measured**. No feature may be
added after observing IC results. Adding features post-observation based on which ones "look
promising" is p-hacking. This list is locked at the start of Phase A.

The pre-specified feature count determines the multiple-testing correction threshold. Adding
features post-observation changes that threshold in the analyst's favor — which is exactly
what BH-FDR correction is designed to prevent.

### VI.2 Selection Criteria

A feature is eligible for V1 if:
1. Non-null rate >= 99% across eligible rows
2. Continuous or binary (categoricals excluded; treated as conditioning variables)
3. Information source not already represented by more than 3 features
   (prevents any single source from dominating the ensemble before IC measurement)
4. Present as a named column in the `feature_vectors` table schema (§XIV.2 of the
   architecture doc / §VI.3 below)

### VI.3 V1 Feature Universe (54 features)

All features are explicit typed columns in `feature_vectors` — no JSONB extraction.
Column names match the DB schema exactly.

**Parameterized features** (oscillators, trend, aroon) are measured at multiple periods
simultaneously. IC measurement selects the winning period per (symbol, tf, regime) —
the researcher does not pre-select. All periods enter the FDR correction together.

**Momentum (5 features)**
| Column          | Character                                           |
|-----------------|-----------------------------------------------------|
| `momentum_z_5`  | 5-bar log return z-scored vs rolling window         |
| `momentum_z_20` | 20-bar log return z-scored vs rolling window        |
| `range_position`| (close - low) / (high - low), intrabar position     |
| `bar_close_pos` | Buying pressure: close position within day range    |
| `gap_z`         | Overnight gap z-scored vs rolling gap distribution  |

**Oscillators — semantic scale, APR-backed periods (6 features)**
| Column      | Scale | APR key                    | Character                              |
|-------------|-------|----------------------------|----------------------------------------|
| `rsi_fast`  | fast  | `feature.period.rsi.fast`  | RSI: mean-reversion, short horizon     |
| `rsi_mid`   | mid   | `feature.period.rsi.mid`   | RSI: mid-cycle mean-reversion          |
| `rsi_slow`  | slow  | `feature.period.rsi.slow`  | RSI: longer-cycle mean-reversion       |
| `cci_fast`  | fast  | `feature.period.cci.fast`  | CCI: deviation from mean, MAD-normalized, short |
| `cci_mid`   | mid   | `feature.period.cci.mid`   | CCI: mid-cycle deviation               |
| `cci_slow`  | slow  | `feature.period.cci.slow`  | CCI: longer-cycle deviation            |

Column names encode scale (concept), not period (parameter). Periods live in APR and are
read by FeatureFactory at compute time. Changing a period updates APR and bumps
`pipeline_version` — no schema migration. RSI and CCI test different mean-reversion
hypotheses: RSI uses range normalization; CCI uses mean absolute deviation.

**Trend freshness and strength (4 features)**
| Column       | Scale | APR key                      | Character                            |
|--------------|-------|------------------------------|--------------------------------------|
| `aroon_fast` | fast  | `feature.period.aroon.fast`  | Time since recent high, short window |
| `aroon_slow` | slow  | `feature.period.aroon.slow`  | Time since recent high, long window  |
| `hma_slope_z`| —     | —                            | Hull MA slope z-scored (trend direction) |
| `adx`        | —     | —                            | Average Directional Index (trend strength) |

**Volume and order flow (7 features)**
| Column         | Character                                           |
|----------------|-----------------------------------------------------|
| `informed_flow`| Composite informed trader flow signal               |
| `volume_z`     | Bar volume z-score vs rolling mean                  |
| `ofi_z`        | Order flow imbalance z-scored                       |
| `ofi_div`      | OFI vs price divergence (informed/price disagreement)|
| `cvd_slope_z`  | Cumulative volume delta slope, z-scored             |
| `cmf`          | Chaikin money flow                                  |
| `rel_volume`   | Volume ratio vs rolling average                     |

**Volatility and market character (5 features)**
| Column         | Character                                           |
|----------------|-----------------------------------------------------|
| `vwap_dev_sigma`| Session VWAP deviation in sigma units              |
| `atr_z`        | ATR z-scored vs rolling ATR (vol regime)            |
| `vol_ratio`    | Short/long realized vol ratio                       |
| `hurst`        | Hurst exponent (trending vs mean-reverting)         |
| `shannon`      | Shannon entropy of price (uncertainty)              |

**HMM regime state (4 features)**
| Column           | Character                                         |
|------------------|---------------------------------------------------|
| `hmm_regime_prob`| HMM confidence in current regime state            |
| `hmm_entropy`    | HMM regime distribution entropy (clarity)         |
| `hmm_duration`   | Bars spent in current regime (maturity signal)    |
| `garch_ratio`    | GARCH conditional vol vs realized vol ratio       |

`hmm_duration` and `hmm_entropy` are orthogonal: entropy measures certainty of the
current state; duration measures how long we have been in it. Young regimes often behave
differently from entrenched ones regardless of certainty.

**Market structure (4 features)**
| Column           | Character                                         |
|------------------|---------------------------------------------------|
| `poc_dist_atr`   | Distance from Point of Control in ATR units       |
| `va_position`    | Position within Value Area (0=VAL, 1=VAH)         |
| `sr_support_dist`| Distance to nearest support level in ATR units    |
| `sr_resist_dist` | Distance to nearest resistance level in ATR units |

**Macro context (3 features)**
| Column           | Character                                         |
|------------------|---------------------------------------------------|
| `vix_z`          | VIX level z-scored vs rolling mean                |
| `flight_quality` | Flight-to-quality signal (equity/bond ratio)      |
| `yield_slope_z`  | Yield curve slope z-scored                        |

**Calendar / session (9 features)**
| Column           | Character                                         |
|------------------|---------------------------------------------------|
| `in_ny_session`  | NY session active (binary)                        |
| `in_london_kz`   | London killzone active — distinct from overlap    |
| `in_overlap`     | London/NY overlap active (binary)                 |
| `power_hour`     | 3-4 PM ET active (binary)                         |
| `opening_range`  | First 30 min of session active (binary)           |
| `above_wk_vwap`  | Price above weekly VWAP (institutional bias)      |
| `dow_sin`        | Day-of-week cyclical encoding (sin)               |
| `dow_cos`        | Day-of-week cyclical encoding (cos)               |
| `month_position` | Position within month [0,1]                       |

`in_london_kz` and `in_overlap` are not redundant: London-only flow (before NY open)
has a different institutional character than the overlap window. `power_hour` and
`opening_range` capture binary session structure that continuous `dow_sin/cos` cannot.

**Cross-timeframe (3 features)**
| Column            | Character                                        |
|-------------------|--------------------------------------------------|
| `ctf_momentum`    | HTF/LTF momentum divergence                      |
| `ctf_vwap_align`  | Cross-TF VWAP alignment                          |
| `ctf_regime_align`| Cross-TF HMM regime agreement                   |

**Statistical process / liquidity (4 features)**
| Column          | Character                                                           |
|-----------------|---------------------------------------------------------------------|
| `amihud_illiq_z`| `|return| / dollar_volume`, z-scored rolling — price impact proxy; high illiquidity predicts higher subsequent returns (Amihud 2002) |
| `high_52w_dist` | `(close - rolling_max_252d) / rolling_max_252d` — distance from 52-week high; George & Hwang (2004) momentum anchor |
| `ret_skew_z`    | Rolling skewness of returns (z-scored vs own history) — negative skew predicts drawdowns; positive skew predicts underperformance |
| `ret_acf1_z`    | Spearman autocorrelation of return[t] vs return[t-1], rolling window, z-scored — positive = momentum microstructure, negative = mean-reversion |

`amihud_illiq_z` uses `close × volume` as the dollar_volume proxy (no tick data required).
`ret_acf1_z` is distinct from `momentum_z`: momentum is cumulative return; autocorrelation
measures serial dependence of individual bar returns — orthogonal information dimensions.

**Total: 54 features. Zero redundancy. One distinct information dimension each.**

### VI.3a Feature-to-Vector Domain Registry

Every feature has a declared `vector_domain`. This mapping is a static constant in
`src/intelligence/feature_factory.py` (`FEATURE_VECTOR_DOMAIN: dict[str, str]`).
The IC Engine reads it at startup and writes `vector_domain` to every `feature_ic_scores`
and `ensemble_weights` row — enabling per-vector IC aggregation and decay monitoring.

| Group                          | `vector_domain` | Features |
|--------------------------------|-----------------|---------|
| Momentum                       | `'quant'`       | `momentum_z_5`, `momentum_z_20`, `range_position`, `bar_close_pos`, `gap_z` |
| Oscillators                    | `'quant'`       | `rsi_fast`, `rsi_mid`, `rsi_slow`, `cci_fast`, `cci_mid`, `cci_slow` |
| Trend freshness and strength   | `'quant'`       | `aroon_fast`, `aroon_slow`, `hma_slope_z`, `adx` |
| Volume and order flow          | `'quant'`       | `informed_flow`, `volume_z`, `ofi_z`, `ofi_div`, `cvd_slope_z`, `cmf`, `rel_volume` |
| Volatility and market char     | `'quant'`       | `vwap_dev_sigma`, `atr_z`, `vol_ratio`, `hurst`, `shannon` |
| HMM regime state               | `'quant'`       | `hmm_regime_prob`, `hmm_entropy`, `hmm_duration`, `garch_ratio` |
| Market structure               | `'quant'`       | `poc_dist_atr`, `va_position`, `sr_support_dist`, `sr_resist_dist` |
| Statistical process / liquidity| `'quant'`       | `amihud_illiq_z`, `high_52w_dist`, `ret_skew_z`, `ret_acf1_z` |
| Macro context                  | `'macro'`       | `vix_z`, `flight_quality`, `yield_slope_z` |
| Calendar / session             | `'calendar'`    | `in_ny_session`, `in_london_kz`, `in_overlap`, `power_hour`, `opening_range`, `above_wk_vwap`, `dow_sin`, `dow_cos`, `month_position` |
| Cross-timeframe                | `'quant'`       | `ctf_momentum`, `ctf_vwap_align`, `ctf_regime_align` |

V2 Microstructure features (tick/L2 data, not yet ingested) will carry `'micro'`. When V2
enters `feature_vectors`, adding rows to `FEATURE_VECTOR_DOMAIN` is the only registration
step required — the IC Engine and decay monitor are vector-agnostic.

### VI.4 Initial APR Period Seeds

FeatureFactory reads all periods from APR. Initial seeds (marked `[initial_estimate]` in
`config_schema` — subject to IC-driven optimization):

| APR key                    | Initial value | Rationale                              |
|----------------------------|---------------|----------------------------------------|
| `feature.period.rsi.fast`  | 7             | Half of Wilder's canonical             |
| `feature.period.rsi.mid`   | 14            | Wilder canonical — baseline            |
| `feature.period.rsi.slow`  | 28            | Double of canonical                    |
| `feature.period.cci.fast`  | 7             | Short deviation window                 |
| `feature.period.cci.mid`   | 14            | Lambert canonical                      |
| `feature.period.cci.slow`  | 28            | Longer deviation window                |
| `feature.period.aroon.fast`| 25            | ~1 month of daily bars                 |
| `feature.period.aroon.slow`| 50            | ~2 months of daily bars                |

IC measurement will reveal which periods carry predictive power per (symbol, tf, regime).
Period updates flow through APR — no schema migration required.

### VI.5 Explicit Exclusions from V1

The following are excluded with stated reasons:

| Excluded                         | Reason                                                              |
|----------------------------------|---------------------------------------------------------------------|
| FX pairs (EURUSD, GBPUSD, etc.) | 21 rows — statistically negligible; different market microstructure |
| Candlestick patterns (boolean)   | Very low base rates; IC measurement requires sufficient true events  |
| `ctf_highest_aligned_tf`         | Categorical; excluded from predictor universe                       |
| `swing_low_type`, `trend_direction` | Categorical                                                      |
| `obv` (raw)                      | Unbounded level; meaningless without normalization to price         |
| `macd_line` (raw)                | In price units; not cross-sectionally comparable                    |
| `smc.amd_phase`                  | Categorical                                                         |
| `smc.breaker_block_type`         | Categorical                                                         |
| Any feature with null rate > 1%  | Missing data biases IC estimates; excluded until coverage improves  |
| Cross-sectional relative strength | Requires inter-symbol dependency at compute time (SPY return at bar T while computing symbol X) — breaks pure per-symbol FeatureFactory model; revisit when cross-sectional FeatureCache is designed |

Patterns and SMC binary features (in_supply_zone, in_demand_zone, etc.) are candidates for
**V2** after sufficient occurrence count is verified. A binary feature needs at least 500
`true` observations for IC estimation. Most pattern features will not meet this at current
scale.

---

## VII. Feature Normalization

### VII.1 Cross-Sectional Rank Transform

All features are normalized via cross-sectional percentile rank before IC computation.
`feature_vectors` stores raw computed values; rank normalization is applied by the IC
Engine at measurement time (not at write time).

```
pct_rank(v, window) = (rank_of_v_in_window - 0.5) / count_non_null_in_window
```

Result: (0, 1) exclusive. The `- 0.5` centers the distribution (avoids 0 and 1 boundary
effects in correlation).

The ranking window is: all observations of the same (symbol, TF) within the training
period. This is **within-symbol normalization** — rank within SPY's history, not relative
to QQQ. Cross-symbol rank normalization requires verifying comparable distributions first,
which is a V2 decision.

### VII.2 Why Rank Transform, Not Z-Score

Z-score normalization assumes a distribution shape. RSI is bounded [0,100]. Volume z-score
is right-skewed. ATR is in price units that change with the price level of the underlying.
Rank normalization makes none of these assumptions and produces comparable, unit-free
outputs that are correct inputs for Spearman IC (which is already a rank correlation).

Z-score normalization on financial features is wrong except for features that are
themselves z-scores (e.g., `volume_z_score` — but even these get rank-normalized because
their z-score distribution may be non-Gaussian in a given window).

### VII.3 Direction Centering

After rank normalization, features are centered at 0.5. For the IC-weighted ensemble, we
need signed scores:

```
centered_score = pct_rank - 0.5     -- range: (-0.5, +0.5)
```

A centered score of +0.4 means the feature value is at the 90th percentile of its window
(very high). A centered score of -0.4 means it is at the 10th percentile (very low).

Whether high = bullish or high = bearish is determined by the sign of IC, which is
discovered empirically. The same feature (e.g., RSI) may have positive IC in trending
regimes (high RSI predicts continuation) and negative IC in ranging regimes (high RSI
predicts reversal).

### VII.4 Binary Feature Handling

Binary features (values {0, 1}) are rank-normalized identically. The `true` class maps to
a higher percentile than `false`. With a non-trivial base rate (e.g., 30% true), rank
normalization produces two clusters in the percentile space. Spearman IC handles this
correctly because it operates on ranks.

---

## VIII. IC Estimation Procedure

### VIII.1 The Estimator

For each (feature, symbol, TF, regime, lookahead), IC is estimated as:

```
IC = Spearman( centered_score_t, R(t, N) )
```

Where the correlation is computed over all non-null observations in the training window
where `complete_{N}bar = true` (the forward return window is complete) and
`has_gap_before_entry = false` (no overnight gap distortion, for V1 conservative start).

**Spearman over Pearson** because: Spearman is a correlation on ranks; since the input
feature is already rank-normalized, Spearman and Pearson would converge for features, but
Spearman is more robust to non-normal return distributions (returns have fat tails).

### VIII.2 Serial Autocorrelation: Non-Overlapping Sub-Sampling

Consecutive bars are not independent. The 5-bar return at T and the 5-bar return at T+1
share bars T+1 through T+5 — they are heavily correlated. If we use every bar as an
observation, our IC standard errors are far too small, p-values are too significant, and
we will promote features that carry no genuine signal.

**Solution:** Use non-overlapping windows. For lookahead N, sample every Nth bar:

```
observations = rows where (row_index % N) == 0
```

Where `row_index` is the rank of each bar within (symbol, TF), ordered by `ts`.

This ensures that no forward return window overlaps with any other in the sample. Each
(feature, return) pair is genuinely independent given no structural break in the data.

**Effective N:** The sub-sampled observation count is `floor(T / N)` where T is the total
bar count in the training window. For 25,000 bars and N=5: 5,000 independent observations.

### VIII.3 Bootstrap Confidence Interval

2,000 bootstrap resamples (percentile method, with replacement on the sub-sampled pairs).
Report `ic_ci_lower` (2.5th percentile) and `ic_ci_upper` (97.5th percentile).

**Gate:** A feature is eligible for IC Sharpe computation only if `ic_ci_lower > 0.0`
in the training window. This is a one-tailed test: the lower bound of the 95% CI must
exceed zero. Features where the CI includes zero may have positive IC by chance.

### VIII.4 Minimum N and Reliability Flag

| Condition                       | Flag in feature_ic_scores      |
|---------------------------------|-------------------------------|
| n_independent < 100             | `reliable = false` — excluded from ensemble |
| 100 <= n_independent < 500      | `reliable = true` — included, but IC Sharpe not computed |
| n_independent >= 500            | `reliable = true` — IC Sharpe eligible |

Features with `reliable = false` are computed and stored for monitoring but never enter
the ensemble.

---

## IX. Multiple Testing Protocol

### IX.1 Test Count

V1 feature universe: 54 features × 58 symbols × 4 TFs (5m/15m/1h/1d) × 1 regime
(pooled, Phase A) × 4 lookaheads = 50,112 IC tests.

At BH-FDR q=0.05: expected false discoveries ≈ 0.05 × 50,112 = 2,506, assuming all tests
are pure noise. FDR correction is necessary but not sufficient.

**Note on multi-period features:** RSI (×3), CCI (×3), and aroon (×2) produce correlated
tests within each (symbol, tf, regime, lookahead) group. BH-FDR is conservative under
positive correlation (Benjamini-Yekutieli bound holds), so the correction is valid. The
Ledoit-Wolf step at ensemble construction further down-weights redundant period variants
that carry the same information.

### IX.2 Benjamini-Hochberg FDR Correction

Applied within the full test batch:
1. Sort all p-values ascending: p(1) <= p(2) <= ... <= p(M)
2. Find the largest k such that p(k) <= (k/M) × q
3. Reject H₀ for all p(i) with i <= k

`q = 0.05` (5% false discovery rate across the test batch).

All tests within the pre-specified feature universe are included in the correction. There
is no separate correction per feature or per TF — the correction is applied globally.

### IX.3 Walk-Forward Validation — The Primary Guard

BH-FDR surviving features are validated on held-out data. Walk-forward validation is the
primary statistical guard. FDR controls the false discovery rate within the training window;
walk-forward confirms those discoveries replicate out-of-sample.

**Walk-forward protocol:**

```
Training start:     earliest available bar after prerequisites complete
Initial training end: training_start + 70% of available data
Fold size:          10% of available data
Number of folds:    3

Fold 1: train on [start, training_end], validate on [training_end, training_end + fold_size]
Fold 2: train on [start, training_end + fold_size], validate on [training_end + fold_size, ...]
Fold 3: train on [start, training_end + 2×fold_size], validate on [...]
```

Expanding window training (not rolling) — each fold includes all prior data, because
we are looking for persistent effects, not regime-specific ones in V1.

**Validation criteria per feature:**

| Criterion                        | Threshold      |
|----------------------------------|---------------|
| IC > 0 in validation fold        | >= 2 of 3 folds |
| IC Sharpe across all folds       | >= 0.4         |
| IC direction consistent (sign)   | Same sign in >= 2 of 3 folds |

A feature fails walk-forward if any criterion is not met. Failure is permanent for V1 —
failed features are not re-evaluated with adjusted parameters. They are candidates for
the next measurement cycle with additional data.

### IX.4 Holdout Integrity

The walk-forward validation windows are used exactly once:
- Never examined during feature selection, normalization fitting, or parameter choice
- If the first measurement cycle produces disappointing results, the validation windows are
  NOT re-used with adjusted features or parameters (that is p-hacking)
- The re-measurement path is: add more data, re-run the full protocol from scratch

The validation window split date and fold boundaries are recorded in `feature_ic_scores`
(`training_window_end` column) so the integrity of each IC estimate is auditable.

---

## X. IC Sharpe Computation

IC Sharpe is the primary ensemble weighting signal. Raw IC penalizes features with low
average predictive power; IC Sharpe penalizes features with inconsistent predictive power.
A feature with IC=0.04 and IC std=0.01 is far more valuable than IC=0.06 and IC std=0.10.

### X.1 Rolling IC Time Series

For each feature that passes FDR + walk-forward:

```
IC Sharpe = mean(IC_t) / std(IC_t)

Where IC_t is computed on non-overlapping windows of W = 2,000 independent observations:
    - Window 1: observations [0, 2000)
    - Window 2: observations [2000, 4000)
    - Window 3: observations [4000, 6000)
    - ...
```

Each `IC_t` is computed on the sub-sampled (non-overlapping-return) observations within
that window. Non-overlapping windows ensure IC_t estimates are independent of each other,
which is required for IC Sharpe to be well-defined.

**Minimum:** IC Sharpe requires at least 10 IC observations (IC_t values). With W=2,000
and the minimum 5,000 independent observations for IC Sharpe eligibility, the minimum
is 2.5 IC observations — too few. The 5,000-observation minimum is therefore overridden:
IC Sharpe computation requires 20,000 independent observations (10 windows × 2,000).

At 1m bars with 5-bar sub-sampling, 20,000 independent observations requires 100,000 raw
bars. This is achievable with the ETF backfill. It is not achievable with the current
commodity-only dataset.

**There is no interim approach.** If the data does not support 20,000 independent
observations for a given (feature, symbol, TF, regime), IC Sharpe is not computed and
that feature is not eligible for ensemble weighting. A feature with insufficient
observations for IC Sharpe is in the same category as a feature that failed IC
significance — it does not enter the ensemble. The ensemble runs no features until each
feature meets the full data requirement. Get more data.

### X.2 Annualization

IC Sharpe is computed in bar units. For comparability across TFs, annualize:

```
IC_Sharpe_annualized = IC_Sharpe_bar × sqrt(bars_per_year)
```

Where `bars_per_year` = 252 × bars_per_trading_day for each TF. This is stored separately
from the raw IC Sharpe and used for cross-TF comparison only, not for weighting.

---

## XI. Ensemble Weight Derivation

### XI.1 The Problem with Simple IC Weighting

Naive IC-proportional weighting fails when features are correlated. If `f_rsi_14` and
`f_roc_14` both have IC=0.04 and their IC time series are highly correlated (both drop
in choppy markets, both spike in trending markets), giving each full IC weight
double-counts the same source of predictability. The ensemble Sharpe is lower than if we
had assigned one of them zero weight.

### XI.2 Ledoit-Wolf Covariance Shrinkage

The correct treatment: compute the covariance matrix of IC time series across features,
apply Ledoit-Wolf shrinkage, and solve for the minimum-variance weighting of IC streams.

```python
# IC time series matrix: shape (n_features × n_ic_windows)
IC = build_ic_time_series(passing_features)  # each column is IC_t sequence for one feature

# Sample covariance is poorly conditioned when n_features > n_windows
# Ledoit-Wolf produces a well-conditioned estimate via analytical shrinkage
lw = LedoitWolf()
cov_ic = lw.fit(IC.T).covariance_   # shape: (n_features × n_features)

# Mean IC vector: expected IC per window
mu_ic = IC.mean(axis=1)             # shape: (n_features,)

# Maximum Sharpe ratio weights (long-only: negative weights would mean shorting a feature's
# signal, which is captured by the IC sign instead)
# Solve: max μ'w / sqrt(w'Σw) subject to sum(w)=1, w>=0
weights = maximize_sharpe(mu_ic, cov_ic, long_only=True)
```

**Why long-only:** Features with negative IC are handled by negating the centered score
at ensemble computation time (see §XI.3). The weight optimizer sees all features as
contributing positively; direction is handled separately.

### XI.3 Signed Weight Application

The IC sign (positive or negative) is stored separately from the weight magnitude:

```python
# At ensemble computation time:
alpha_score = sum(
    sign(ic[f]) × (centered_score[f]) × weight[f]
    for f in active_features
)
```

Where `sign(ic[f])` is +1 if the feature's IC is positive (high value predicts positive
return) or -1 if negative (high value predicts negative return). This is stored in
`ensemble_weights.ic_sign`.

The result is an ensemble score where positive means the composite of features predicts
upward price movement, and negative means downward. The magnitude represents the strength
of the composite prediction.

### XI.4 Weight Bounds

- Minimum weight: 0 (features with IC Sharpe below threshold contribute nothing)
- Maximum weight per feature: 0.20 (no single feature dominates more than 20% of the
  ensemble; prevents over-concentration in one source)
- The weight cap is enforced post-optimization by normalization if any weight exceeds 0.20

### XI.5 Weight Versioning

Every re-run of the Ensemble Builder that changes any weight produces a new `weight_version`
(integer, monotonically increasing). The ensemble uses the latest `weight_version` with
`is_active = true`. Old versions are retained for audit and comparison.

---

## XII. Ensemble Score and Emission Threshold

### XII.1 Ensemble Alpha Score

For each bar (symbol, TF, ts) after weights are available:

```python
alpha_raw = sum(
    sign(ic[f]) × centered_score[f] × weight[f]
    for f in features where weight[f] > 0
)
```

The raw score is z-scored within a rolling 20-day window:

```python
alpha_score = (alpha_raw - rolling_mean(alpha_raw, 20d)) / rolling_std(alpha_raw, 20d)
```

The z-scored alpha is in standard deviation units. Positive means above-average bullish
signal; negative means above-average bearish signal.

This score is written to `ensemble_alpha` for every bar. It is the unconditional output
of the ensemble — every bar is scored regardless of whether it will trigger an emission.

### XII.2 Empirical Emission Threshold

The threshold for emitting an `alpha_event` is not researcher-set. It is derived from the
ensemble IC and estimated transaction costs:

```
For each candidate threshold θ ∈ linspace(0.1, 3.0, 100):
    obs = ensemble_alpha where |alpha_score| >= θ
    expected_return = abs(obs.alpha_score) × IC_ensemble
    
    if expected_return > estimated_transaction_cost:
        threshold[symbol][tf] = θ
        break
```

Where `IC_ensemble` is the Spearman IC between `alpha_score` and subsequent returns,
measured on training data. Transaction costs are estimated from observed bid-ask spreads
in `market_data_ohlcv` plus fixed commission.

The threshold is stored in APR under `alpha.threshold.<symbol>.<tf>`. It is
re-derived after each weight update that changes ensemble IC by more than 15%.

### XII.3 Alpha Event Direction

An alpha event carries a direction: `'long'` if `alpha_score > threshold`, `'short'`
if `alpha_score < -threshold`. Directionless signals (absolute value above threshold but
direction ambiguous) do not exist — the IC-weighted sum carries directional information
by construction via the `ic_sign` values.

---

## XIII. Alpha Decay Protocol

### XIII.1 Architectural Invariants

Two invariants govern the entire decay system and cannot be violated:

**Invariant 1 — `ensemble_weights` is the only valid weight store.**
Ledoit-Wolf weights are jointly optimal across the full active feature set. They cannot
be updated individually. When any feature's active status changes, the only valid response
is a full Ledoit-Wolf re-solve producing a new `weight_version`. Writing `weight = 0` to
APR for a single feature while leaving all other weights unchanged produces an internally
inconsistent ensemble — the covariance adjustment is invalid for the remaining features.
APR stores emission thresholds, Kelly parameters, and governance gates. Not feature weights.

**Invariant 2 — Decay is regime-stratified.**
A feature decaying in one HMM regime does not imply it has decayed in others. The decay
monitor evaluates each (feature, symbol, tf, regime) cell independently. Global IC drop
across all regimes simultaneously is a market regime shift — a different response is
required (see §XIII.5).

### XIII.2 Rolling IC Monitor

`AlphaDecayMonitor` runs daily. For each (feature, symbol, tf, regime) cell with an
active weight in the current `weight_version`:

1. Pull the most recent W=2,000 independent observations (same N-bar sub-sampling as
   §VIII.2) from `feature_vectors` × `outcome_labels`
2. Compute Spearman IC + 2,000-resample bootstrap CI
3. Write a new row to `feature_ic_scores` with `training_window_end = today`

This is the same computation as the IC Engine (§VIII), windowed to recent data. The
decay monitor does not introduce a new statistical procedure — it applies the same
procedure on a rolling basis.

### XIII.3 Decay Trigger

Decay is flagged — not acted upon directly — when:

```
rolling_ic_ci_lower <= alpha.decay.ci_lower_threshold   (default: 0.0)
AND
weight[feature][tf][regime] × |rolling_ic_ci_lower| > alpha.decay.materiality_threshold
```

The materiality filter prevents a feature contributing 0.5% of ensemble weight from
triggering a full re-solve on a marginal CI exceedance. Only cells where the product of
weight magnitude and decay severity exceeds the threshold fire the rebuild.

**Regime-shift detection (global IC drop):** If `>= alpha.decay.regime_shift_fraction`
(default: 0.60) of features across all regimes simultaneously show `ic_ci_lower <= 0`,
this is classified as a market regime shift, not individual feature decay. Response:
flag the condition in `config_history` with `changed_by = 'alpha_decay_monitor'`,
`reason = 'suspected_regime_shift'`. Do not zero weights. Wait for the regime to
normalize. A regime shift does not imply the features lost their edge — it implies the
market stopped rewarding them temporarily.

**Automated decay response (no human approval required):**
1. Set `feature_ic_scores.is_decaying = true` for the affected (feature, symbol, tf, regime) rows
2. Trigger `EnsembleBuilder` (oneshot run): full Ledoit-Wolf re-solve excluding decayed cells
3. New `weight_version` written to `ensemble_weights` atomically — all weights updated together
4. Log trigger to `config_history` with `changed_by = 'alpha_decay_monitor'`,
   `reason = 'ic_ci_lower <= threshold, materiality exceeded'`

The Ensemble Builder is the only writer to `ensemble_weights`. The decay monitor triggers
it; it does not write weights directly.

### XIII.4 Recovery Gate

Recovery requires genuinely new evidence — not the same data re-examined.

A decayed (feature, symbol, tf, regime) cell is eligible for recovery only after
`W_recovery = 2,000` new independent observations arrive that were not part of the window
that detected the decay. At 5m with N=5 sub-sampling: 2,000 new independent observations
= 10,000 new raw bars ≈ 128 trading days. At 1h: ≈ 26 trading days.

This is the minimum before recovery can even be evaluated. "2 consecutive daily checks"
on overlapping data is not new evidence — two daily rolling windows at 5m share 127/128
days of observations (99.2% overlap). The recovery gate enforces non-overlap:

```
recovery_eligible_at = decay_triggered_at + (W_recovery × N_subsample × bar_duration)
```

When `now() >= recovery_eligible_at`:
1. Compute IC on a non-overlapping window starting after `decay_triggered_at`
2. If `ic_ci_lower > 0`: mark cell as `recovered`, trigger `EnsembleBuilder` re-solve
3. Recovered feature re-enters at full IC Sharpe weight (not a fractional partial restore —
   the Ledoit-Wolf re-solve assigns the correct weight; no human-chosen fraction needed)

**Why no partial restoration:** The old "restore to 50% of prior weight" rule is a
researcher intervention in a process that should be purely empirical. If the feature's
IC on the recovery window supports, say, 12% weight, the re-solve produces 12%. If it
supports 2%, it produces 2%. The algorithm determines the weight, not a hard-coded
fraction.

### XIII.5 Update Cadence

- Rolling IC: computed daily by `AlphaDecayMonitor`
- Decay trigger evaluation: daily, after rolling IC completes
- `EnsembleBuilder` re-solve: triggered same day as decay detection; completes before
  next nightly `AlphaEmitter` run
- `ensemble_alpha` recomputed for recent bars: nightly `AlphaEmitter` run uses new
  `weight_version` automatically (reads latest active version from `ensemble_weights`)
- Recovery check: not run until `recovery_eligible_at` is reached (may be weeks/months)

---

## XIV. Schema Definitions

All tables use UTC timestamps. All tables are created in the `public` schema.

### XIV.1 outcome_labels

```sql
CREATE TABLE outcome_labels (
    symbol              text             NOT NULL,
    tf                  text             NOT NULL,
    bar_ts              timestamptz      NOT NULL,  -- ts of the observation bar
    pipeline_version    text             NOT NULL,
    regime_label_source text             NOT NULL DEFAULT 'smoothed',
    -- Executable log returns: ln(open[T+N+1] / open[T+1])
    return_1bar         double precision,
    return_5bar         double precision,
    return_20bar        double precision,
    return_60bar        double precision,
    -- Completeness flags
    complete_1bar       boolean          NOT NULL DEFAULT false,
    complete_5bar       boolean          NOT NULL DEFAULT false,
    complete_20bar      boolean          NOT NULL DEFAULT false,
    complete_60bar      boolean          NOT NULL DEFAULT false,
    -- Gap flag: true if a market-hours gap exists before the entry bar
    has_gap_before_entry boolean         NOT NULL DEFAULT false,
    computed_at         timestamptz      NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, tf, bar_ts)
);
SELECT create_hypertable('outcome_labels', 'bar_ts',
    chunk_time_interval => INTERVAL '3 months');
CREATE INDEX ON outcome_labels (symbol, tf, bar_ts);
```

### XIV.2 feature_vectors (replaces both feature_candidates and feature_matrix)

v3.0 eliminates the research/production split. All 50 features are first-class columns
from day one. IC Engine reads directly from `feature_vectors`. Promotion from candidate
to production status is tracked via IC results in `feature_ic_scores` and
`ensemble_weights`, not by a schema migration between tables.

Full DDL in `docs/plans/2026-06-20-alphaengine-architecture.md` §Data Model.

### XIV.4 feature_ic_scores

```sql
CREATE TABLE feature_ic_scores (
    feature_name            text             NOT NULL,
    vector_domain           text             NOT NULL,   -- 'quant' | 'micro' | 'macro' | 'calendar'
    symbol                  text             NOT NULL,
    tf                      text             NOT NULL,
    regime                  text,                        -- NULL = pooled
    lookahead_bars          int              NOT NULL,
    training_window_end     timestamptz      NOT NULL,   -- IC measured on data up to this date
    -- Sample information
    n_independent           int              NOT NULL,   -- sub-sampled observation count
    reliable                boolean          NOT NULL,   -- true if n_independent >= 100
    -- IC point estimate
    ic_value                double precision,
    ic_sign                 smallint,                    -- +1 or -1
    p_value                 double precision,
    -- Bootstrap CI
    ic_ci_lower             double precision,
    ic_ci_upper             double precision,
    passes_ci_gate          boolean,                     -- ic_ci_lower > 0.0
    -- FDR correction (computed across full batch)
    bh_adjusted_p           double precision,
    passes_fdr              boolean,
    -- Walk-forward results
    wf_fold_count           int,
    wf_pass_count           int,                         -- folds where IC > 0
    wf_ic_sharpe            double precision,            -- IC Sharpe across WF folds
    passes_walkforward      boolean,
    -- IC Sharpe (rolling window computation)
    ic_sharpe               double precision,            -- NULL if < 10 IC windows
    ic_sharpe_n_windows     int,
    -- Regime source tracking
    regime_label_source     text             NOT NULL DEFAULT 'smoothed',
    -- Decay state (written by AlphaDecayMonitor on daily rolling IC runs)
    is_decaying             boolean          NOT NULL DEFAULT false,
    decay_detected_at       timestamptz,
    recovery_eligible_at    timestamptz,     -- earliest timestamp new evidence can be evaluated
    -- Bookkeeping
    computed_at             timestamptz      NOT NULL DEFAULT now(),
    PRIMARY KEY (feature_name, symbol, tf, regime, lookahead_bars, training_window_end)
);
CREATE INDEX ON feature_ic_scores (passes_walkforward, passes_fdr, symbol, tf);
CREATE INDEX ON feature_ic_scores (vector_domain, symbol, tf);  -- cross-vector IC queries
```

### XIV.5 ensemble_weights

```sql
CREATE TABLE ensemble_weights (
    weight_version      int              NOT NULL,
    feature_name        text             NOT NULL,
    vector_domain       text             NOT NULL,   -- 'quant' | 'micro' | 'macro' | 'calendar'
    symbol              text             NOT NULL,
    tf                  text             NOT NULL,
    regime              text,
    lookahead_bars      int              NOT NULL,
    -- Ledoit-Wolf optimized weight (magnitude only; direction via ic_sign)
    weight              double precision NOT NULL CHECK (weight >= 0),
    ic_sign             smallint         NOT NULL CHECK (ic_sign IN (-1, 1)),
    ic_sharpe           double precision NOT NULL,
    ic_ci_lower         double precision NOT NULL,
    -- Decay state
    is_active           boolean          NOT NULL DEFAULT true,
    decay_triggered_at  timestamptz,
    recovery_confirmed_at timestamptz,
    -- Bookkeeping
    computed_at         timestamptz      NOT NULL DEFAULT now(),
    PRIMARY KEY (weight_version, feature_name, symbol, tf, regime, lookahead_bars)
);
CREATE INDEX ON ensemble_weights (symbol, tf, regime, is_active, weight_version DESC);
CREATE INDEX ON ensemble_weights (vector_domain, symbol, tf, is_active);  -- per-vector decay queries
```

### XIV.6 ensemble_alpha

```sql
CREATE TABLE ensemble_alpha (
    symbol              text             NOT NULL,
    tf                  text             NOT NULL,
    bar_ts              timestamptz      NOT NULL,
    weight_version      int              NOT NULL,
    regime              text,
    -- Scores
    alpha_raw           double precision NOT NULL,   -- pre-normalization IC-weighted sum
    alpha_score         double precision NOT NULL,   -- z-scored within rolling 20d window
    alpha_ci_lower      double precision,
    alpha_ci_upper      double precision,
    -- Composition
    active_feature_count int             NOT NULL,
    top_contributors    jsonb,                        -- [{feature, contribution, ic_sign}], top 5
    -- Bookkeeping
    computed_at         timestamptz      NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, tf, bar_ts)
);
SELECT create_hypertable('ensemble_alpha', 'bar_ts',
    chunk_time_interval => INTERVAL '3 months');
CREATE INDEX ON ensemble_alpha (symbol, tf, bar_ts, alpha_score);
```

### XIV.7 alpha_events

```sql
CREATE TABLE alpha_events (
    symbol              text             NOT NULL,
    tf                  text             NOT NULL,
    bar_ts              timestamptz      NOT NULL,
    direction           text             NOT NULL CHECK (direction IN ('long', 'short')),
    alpha_score         double precision NOT NULL,
    threshold_used      double precision NOT NULL,
    weight_version      int              NOT NULL,
    regime              text,
    -- Decomposition (top 5 features by contribution for interpretability)
    top_features        jsonb,
    -- Lifecycle
    status              text             NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'labeled', 'expired')),
    emitted_at          timestamptz      NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, tf, bar_ts)
);
SELECT create_hypertable('alpha_events', 'bar_ts',
    chunk_time_interval => INTERVAL '3 months');
CREATE INDEX ON alpha_events (symbol, tf, status, bar_ts);
```

---

## XV. Batch Job DAG

Four batch services run in strict dependency order. No service begins before its
upstream services have completed for the same data window.

```
feature_vectors   (source, written by FeatureFactory in-process)
market_data_ohlcv (source, written by BarWriter)
        │
        ▼
[1] Outcome Labeler (oneshot on demand + nightly increment)
    Reads:  market_data_ohlcv (open, timestamp, timeframe, symbol)
    Writes: outcome_labels
    Idempotent: yes (upsert on PK)
    High-water mark: last bar_ts processed per (symbol, tf)

        (runs in parallel with [1])
[2] — no Feature Extractor in v3.0 —
    feature_vectors is the direct IC input; no extraction step needed.

        (both [1] must complete first)
        ▼
[3] IC Engine (weekly full re-run + daily incremental)
    Reads:  feature_vectors (all 50 feature columns, rank-normalized at read time)
            outcome_labels (forward returns)
    Writes: feature_ic_scores
    Idempotent: yes (upsert on PK including training_window_end)
    Trigger: weekly on Sunday 02:00 UTC
        │
        ▼
[4] Ensemble Builder (after IC Engine completes; weekly)
    Reads:  feature_ic_scores (passes_fdr AND passes_walkforward)
    Writes: ensemble_weights (new weight_version)
            ensemble_alpha (for all bars since last weight_version)
    Idempotent: yes (upsert on PK; new weight_version on each run)
    Trigger: after IC Engine completes
        │
        ├──────────────────────────────┐
        ▼                              ▼
[5] Alpha Decay Monitor (daily)    [6] Alpha Emitter (nightly)
    Reads:  feature_vectors,           Reads:  ensemble_alpha
            outcome_labels (rolling)           APR alpha.threshold.*
    Writes: ensemble_weights           Writes: alpha_events
            APR alpha.weights.*        Trigger: nightly after [4]
    Trigger: daily at 06:00 UTC
```

Job [1] has no dependency. Job [3] depends on [1]. Jobs [4], [5], [6] depend on [3].
Jobs [5] and [6] run in parallel after [4].

---

## XVI. Batch Job Requirements

### XVI.1 Idempotency

Every job must be safe to re-run without producing duplicate data or incorrect state:
- Use `INSERT ... ON CONFLICT (pk_columns) DO UPDATE SET ...` throughout
- Never use `INSERT ... SELECT` without a conflict clause
- On restart, re-process from the high-water mark (not from the beginning)

### XVI.2 Determinism

Given identical input data, every job must produce byte-identical output:
- `LedoitWolf` from scikit-learn: deterministic (no random state)
- Bootstrap CI: seeded with `random.seed(42)` at job start (reproducible resampling)
- Rank computation: explicit tie-breaking rule — ties broken by `ts` (ascending) to ensure
  deterministic rank assignment when feature values are equal

### XVI.3 High-Water Marks

Each job stores its progress in APR under `batch.hwm.<job_name>.<symbol>.<tf>` as a
timestamptz string. On restart, the job resumes from the stored high-water mark. If
the APR key is absent, the job starts from the beginning of the available data.

### XVI.4 Failure Behavior

Jobs fail loudly. Silent partial completion (catching exceptions and continuing) is
forbidden. If a job fails mid-run:
- The high-water mark reflects only fully committed batches
- The next run resumes cleanly from the last high-water mark
- No compensating transactions or rollback logic is needed because writes are idempotent

---

## XVII. V1 Exclusions and Progression Conditions

### XVII.1 V1 Exclusions

| Exclusion                     | Reason                              | V2 Unlock Condition                    |
|-------------------------------|-------------------------------------|----------------------------------------|
| FX pairs                      | 21 rows — backfill required first   | Backfill to >= 25,000 bars per symbol  |
| 4h and 1d TFs                 | 4,000 rows — backfill required      | Backfill to >= 25,000 bars per symbol  |
| Candlestick pattern features  | Low base rate (true events < 500)   | Occurrence count >= 500 per feature    |
| Cross-symbol pooling           | Assumes comparable IC distributions | Verified by cross-symbol IC correlation |
| AnalogEngine (non-parametric)  | Not started until AlphaEngine shows IC > 0 with p < 0.05 | IC gate passed |
| Microstructure vector (V2)    | Requires tick/L2 data not yet ingested | L2 data pipeline built and backfilled |
| Hot-path ensemble (in-process) | Batch IC measurement validates first | Walk-forward IC Sharpe >= 0.5 on held-out |

### XVII.2 Feature promotion (IC gate)

In v3.0, all 50 features are always present in `feature_vectors`. "Promotion" means
earning non-zero weight in `ensemble_weights`, not a schema migration.

A feature earns weight when all of the following hold in `feature_ic_scores`:
1. `passes_fdr = true`
2. `passes_walkforward = true`
3. `wf_pass_count >= 2` (direction consistent across 3 folds)
4. `n_independent >= 500`

Features that fail the gate remain in `feature_vectors` and continue accumulating IC
observations. They are re-evaluated on each weekly IC Engine run with the expanded data
window. There is no removal from `feature_vectors` for underperformance — all firings are
training data (Renaissance retention rule).

---

## XVIII. Success Criteria for Phase A

| Signal                                          | Threshold                                |
|-------------------------------------------------|------------------------------------------|
| IC Engine completes on all (symbol, TF, lookahead) | No errors; `feature_ic_scores` populated |
| At least 10 features with `ic_ci_lower > 0`    | Ensemble has something to weight         |
| At least 5 features pass walk-forward           | Ensemble is not in-sample only           |
| IC Sharpe >= 0.4 for at least 3 features        | Some predictors are stable over time     |
| IC report produced: `docs/analysis/ic-discovery-report-{date}.md` | Human-readable findings |
| Ensemble weights computed and stored            | `ensemble_weights` populated             |
| `ensemble_alpha` populated for all training bars | Full historical scoring complete         |

If fewer than 5 features pass walk-forward, Phase A is considered inconclusive. The path
forward is additional backfill (more data), not relaxing the statistical thresholds.

---

## XIX. Observability Contract

The IC Engine is a oneshot batch service. Every run must be fully observable in Grafana and fully auditable in the DB without reading log files.

### OTel Setup

```python
init_otel_providers(service_name="indicagent-alpha-ic-engine")
# ... run ...
flush_and_shutdown_metrics()  # mandatory before process exit — drains OTLP exporter
```

`flush_and_shutdown_metrics()` is non-negotiable for oneshots. Without it, `job_completed_total` never reaches the collector and the run appears to have never happened.

### Spans

Every run emits a root span wrapping the full batch, and a child span per `(symbol, tf, regime)` cell group:

```python
with observed_span("ic_engine.run", n_symbols=n, n_features=n, n_cells_total=n):
    for symbol, tf in pairs:
        with observed_span("ic_engine.symbol_tf", symbol=symbol, tf=tf):
            for regime in regimes:
                with observed_span("ic_engine.cell", symbol=symbol, tf=tf, regime=regime):
                    ...
```

The cell span auto-records `StatusCode.ERROR` on any exception and re-raises, so a crash mid-run surfaces in Tempo with the exact `(symbol, tf, regime)` cell that failed.

### Metrics (add to `metrics.py` in Phase B)

All metrics labeled `agent_id="alpha-ic-engine"` for the mandatory OTel health contract.

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `ic_engine_run_started_total` | Counter | _(none)_ | Confirms run entry — pair with `job_completed_total` to detect silent hangs |
| `ic_engine_cells_attempted_total` | Counter | `symbol`, `tf`, `regime` | Progress tracking — rises throughout the run |
| `ic_engine_cells_completed_total` | Counter | `symbol`, `tf`, `regime` | Cells with a committed `feature_ic_scores` row |
| `ic_engine_cells_skipped_total` | Counter | `symbol`, `tf`, `regime`, `skip_reason` | Skipped cells; `skip_reason` in {`already_computed`, `insufficient_n`, `all_nan`} |
| `ic_engine_features_passing_fdr_total` | Counter | `symbol`, `tf`, `regime` | Features surviving BH-FDR correction — primary discovery rate signal |
| `ic_engine_ic_score` | Gauge | `feature`, `symbol`, `tf`, `regime`, `lookahead` | Current IC per cell — the primary health metric in Grafana |
| `ic_engine_ic_ci_lower` | Gauge | `feature`, `symbol`, `tf`, `regime`, `lookahead` | Bootstrap CI lower bound — emission gate is `> 0.0` |
| `ic_engine_observations_n` | Gauge | `feature`, `symbol`, `tf`, `regime` | Independent observation count — tracks approach to n=500 |
| `ic_engine_walk_forward_stability` | Gauge | `feature`, `symbol`, `tf` | IC Sharpe across walk-forward folds — low = regime-specific, not structural |
| `ic_engine_nan_feature_total` | Counter | `feature`, `symbol`, `tf` | Cells skipped due to all-NaN feature column — indicates FeatureFactory gaps |
| `ic_engine_run_duration_seconds` | Histogram | _(none)_ | Full run duration — budget baseline for weekly schedule |
| `job_completed_total` | Counter | `job="alpha-ic-engine"`, `status` | Mandatory oneshot exit signal (D-06 pattern) |

### Traceability

Every `feature_ic_scores` row must carry `computed_at` (UTC timestamp of this IC Engine run). This is the audit trail linking an IC estimate to the data window it was computed on. When IC changes between runs, `computed_at` + `n_independent` identifies whether the change was driven by new data or a code change.

Cross-reference with ground-up architecture doc Observability Contract → IC Engine section for Grafana panel requirements.

---

## XX. Resilience Contract

### Idempotency

Every `feature_ic_scores` write uses:

```sql
INSERT INTO feature_ic_scores (feature, symbol, tf, regime, lookahead_bars, ...)
VALUES (...)
ON CONFLICT (feature, symbol, tf, regime, lookahead_bars, computed_at) DO NOTHING;
```

A re-run after crash is fully safe. Completed cells are skipped silently.

### Partial Completion (the output table is the checkpoint)

On startup, the IC Engine queries `feature_ic_scores` for the current run's `computed_at` timestamp (set once at process start and held constant for the entire run) and skips any `(feature, symbol, tf, regime, lookahead_bars)` tuple already present. No separate checkpoint table — the output table is the checkpoint.

```python
RUN_TS = datetime.now(UTC)  # set once; constant for the entire run

completed = set(await conn.fetch(
    "SELECT feature, symbol, tf, regime, lookahead_bars FROM feature_ic_scores WHERE computed_at = $1",
    RUN_TS
))
# Skip any cell in `completed`
```

### NaN Handling

A feature column that is entirely NaN for a `(symbol, tf)` pair produces no IC row for that cell — it does not write `ic_value = NULL` or `ic_value = 0`. A missing row is unambiguous: no data. A row with `ic_value = NULL` is ambiguous. Enforce this as an explicit skip with `ic_engine_cells_skipped_total{skip_reason="all_nan"}` incremented.

### Atomicity

Each `feature_ic_scores` row is inserted individually — one `INSERT` per cell. No transaction wrapping multiple cells. The failure unit is a single cell, not a batch. A crash between two cell inserts produces one missing row, which a re-run fills.

The exception is `ensemble_weights`: the Ensemble Builder (separate service) wraps its entire weight version in a single transaction. See ground-up architecture doc Resilience Contract → Ensemble Builder section.

### Silent Failure Guard

The run must emit `job_completed_total{job="alpha-ic-engine", status="success"}` as its final act before process exit. If this counter is absent in Prometheus after the scheduled run window, the run either never started or crashed before reaching the exit path. Alertmanager fires on this absence. There is no acceptable silent failure mode for the IC Engine — it is the foundation of every downstream weight.
