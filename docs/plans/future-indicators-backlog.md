# Future Indicators Backlog

> Ideas for indicator and pattern plugins beyond current implementation.
> Prioritized by value for a multi-futures trading platform.

---

## Priority Queue — Next Up

### 1. GARCH Volatility Plugin

- **Tier:** I6 Smart Money / Probabilistic
- **Directory:** `src/intelligence/smart_money/`
- **Category:** Volatility Forecasting
- **Why:** Current volatility tools (ATR, BB width, I4 vol regime) measure *realized* volatility — what happened. GARCH forecasts *conditional* volatility — what's coming. This is the difference between "vol was high" and "vol is expanding and will likely stay elevated." Critical for position sizing, stop placement, and knowing when to avoid trading.

**Algorithm: GARCH(1,1)**
```
sigma²(t) = omega + alpha * epsilon²(t-1) + beta * sigma²(t-1)

where:
  sigma²(t) = conditional variance forecast for bar t
  epsilon(t-1) = log return at t-1 (the "shock")
  omega = long-run variance weight (baseline)
  alpha = reaction to recent shock (typically 0.05-0.15)
  beta = persistence of volatility (typically 0.80-0.95)
  alpha + beta < 1 for stationarity
```

**Default Parameters (1m futures bars):**
```python
omega = 0.00001   # ~0.3% annualized baseline
alpha = 0.10      # 10% weight on last shock
beta  = 0.85      # 85% persistence
# alpha + beta = 0.95 → vol half-life ~13 bars
```

**Incremental:** Yes — O(1) per bar. State is just `(prev_sigma2, prev_return)`. Update:
```python
epsilon = log(close / prev_close)
sigma2 = omega + alpha * epsilon**2 + beta * prev_sigma2
```

**Outputs:**
```python
outputs = frozenset({
    "garch_sigma",           # Conditional volatility forecast (sqrt of sigma²)
    "garch_sigma_annualized",# Annualized (sigma * sqrt(252*390) for 1m bars)
    "garch_vol_ratio",       # garch_sigma / realized_vol_20 — >1 means expanding
    "garch_vol_regime",      # 0=low, 1=normal, 2=high, 3=extreme (percentile-based)
    "garch_persistence",     # alpha + beta value (how sticky is vol)
    "garch_shock",           # Latest epsilon² / sigma² — standardized shock magnitude
})
```

**Integration with existing plugins:**
- Complements HMM: HMM says "trending up", GARCH says "with expanding/contracting volatility"
- Complements BOCPD: changepoint detected → GARCH shock should spike
- Complements I4 VolatilityRegime: rule-based (ATR percentile) vs model-based (conditional forecast)
- Future I7: position sizing = f(garch_sigma, hmm_regime, confluence_score)

**Parameter storage:** Same pattern as HMM — hardcoded defaults + optional `config/garch_parameters.json`

**Fallback:** Works with just OHLCV (needs only close prices for log returns). No I1 dependency.

**Estimated complexity:** ~80 lines core, simpler than HMM. 6 tests.

---

### 2. Kalman Filter Trend Plugin

- **Tier:** I6 Smart Money / Probabilistic
- **Directory:** `src/intelligence/smart_money/`
- **Category:** Adaptive Trend Estimation
- **Why:** Current trend tools (SMA/EMA, I4 TrendRegime) use fixed-window averaging — they can't adapt to changing market conditions. Kalman filter is a *statistically optimal* estimator that automatically balances responsiveness vs smoothness based on how noisy the market is. When vol is low, it tracks price closely; when vol spikes, it smooths aggressively. The uncertainty band it produces is more principled than Bollinger Bands (which assume constant variance).

**Algorithm: 1D Kalman Filter (local level model)**
```
State equation:    x(t) = x(t-1) + w(t),     w ~ N(0, Q)    # "true" price evolves with process noise Q
Observation:       z(t) = x(t) + v(t),         v ~ N(0, R)    # observed close = true price + measurement noise R

Predict:
  x_pred = x_est(t-1)                          # predicted state = last estimate
  P_pred = P_est(t-1) + Q                      # predicted uncertainty grows by Q

Update (on new close):
  K = P_pred / (P_pred + R)                     # Kalman gain (0-1)
  x_est = x_pred + K * (close - x_pred)        # weighted blend of prediction and observation
  P_est = (1 - K) * P_pred                      # updated uncertainty (always shrinks)
```

**Key insight:** The Kalman gain `K` automatically adapts:
- High Q/R ratio → K is large → tracks price closely (responsive, like short EMA)
- Low Q/R ratio → K is small → smooths heavily (like long SMA)
- Can also feed GARCH sigma into R for volatility-adaptive tracking

**Default Parameters (1m futures bars):**
```python
Q = 0.5    # Process noise — how much "true" price can move per bar
R = 2.0    # Measurement noise — how noisy is the observed close
# Q/R = 0.25 → moderate smoothing, similar to ~8-bar EMA responsiveness
```

**Incremental:** Yes — O(1) per bar. State is `(x_est, P_est)`. Two multiplies and two adds per bar.

**Outputs:**
```python
outputs = frozenset({
    "kalman_trend",          # Filtered price estimate (the "true" price)
    "kalman_uncertainty",    # P_est — uncertainty of estimate (like BB width but principled)
    "kalman_upper",          # kalman_trend + 2*sqrt(P_est) — upper uncertainty band
    "kalman_lower",          # kalman_trend - 2*sqrt(P_est) — lower uncertainty band
    "kalman_gain",           # Current K value (0-1) — how much we trust new data
    "kalman_slope",          # kalman_trend(t) - kalman_trend(t-1) — trend direction
    "kalman_price_position", # (close - kalman_trend) / sqrt(P_est) — standardized deviation
})
```

**Integration with existing plugins:**
- Complements HMM: Kalman slope direction + HMM regime → higher confidence trend classification
- Complements GARCH: Can feed garch_sigma into R for volatility-adaptive smoothing
- Complements I3 S/R: kalman_trend provides a "fair value" reference for support/resistance distance
- Complements I4 TrendRegime: rule-based (SMA cross) vs model-based (Kalman slope + uncertainty)
- Future I7: kalman_price_position extreme → mean reversion setup candidate

**Parameter storage:** Hardcoded defaults + optional `config/kalman_parameters.json`

**Fallback:** Works with just OHLCV (needs only close). No I1 dependency.

**Estimated complexity:** ~60 lines core, simplest of the three. 6 tests.

---

### 3. Chart Pattern Detection Plugins

- **Tier:** I5 Patterns
- **Directory:** `src/intelligence/patterns/`
- **Category:** Classical Chart Pattern Recognition
- **Why:** Double tops/bottoms, head & shoulders, and triangles/wedges are among the most widely traded patterns in futures markets. We already have the I3 swing detector (HH/HL/LH/LL) and S/R clustering — chart patterns are the natural next layer that operates on swing point sequences. These patterns provide high-conviction reversal/continuation signals with well-defined invalidation levels.

**Three plugins, each independent:**

#### 3a. Double Top / Double Bottom (`patt_DoubleTB`)

**Algorithm:**
1. Read last N swing highs/lows from I3 swing detector output (via `frames["features"]` or direct OHLCV scan)
2. **Double Top:** Two swing highs within tolerance (e.g., 0.3% of price), with a swing low between them
   - Neckline = the swing low between the two peaks
   - Confirmed when price breaks below neckline
   - Target = peak - neckline (measured move)
3. **Double Bottom:** Mirror image — two swing lows with a swing high between
4. Track pattern state: `forming` → `confirmed` → `invalidated`

**Outputs:**
```python
outputs = frozenset({
    "dt_db_pattern",         # 0=none, 1=double_top_forming, 2=double_top_confirmed,
                             # 3=double_bottom_forming, 4=double_bottom_confirmed
    "dt_db_neckline",        # Neckline price level
    "dt_db_target",          # Measured move target price
    "dt_db_confidence",      # 0-1 confidence based on symmetry, volume, time between peaks
})
```

**Incremental:** No (`supports_incremental = False`) — needs full swing sequence scan.

#### 3b. Head & Shoulders (`patt_HeadShoulders`)

**Algorithm:**
1. Scan last N swing points for the 5-point pattern: left shoulder, head, right shoulder (+ 2 troughs)
2. **Regular H&S (bearish):** SH1 < H > SH2 with SH1 ≈ SH2, neckline connects the two troughs
3. **Inverse H&S (bullish):** Mirror — SL1 > H_low < SL2
4. Tolerance: shoulders within 5% of each other, head extends at least 3% beyond shoulders
5. Confirmation: price breaks neckline
6. Target: head height projected from neckline

**Outputs:**
```python
outputs = frozenset({
    "hs_pattern",            # 0=none, 1=hs_forming, 2=hs_confirmed,
                             # 3=ihs_forming, 4=ihs_confirmed
    "hs_neckline",           # Neckline price level (can be sloped)
    "hs_target",             # Measured move target
    "hs_confidence",         # 0-1 based on symmetry, volume pattern, neckline slope
})
```

**Incremental:** No — needs full swing sequence.

#### 3c. Triangles & Wedges (`patt_TriangleWedge`)

**Algorithm:**
1. Take last N swing highs and last N swing lows (minimum 4 swings = 2 highs + 2 lows)
2. Fit linear regression to swing highs → upper trendline (slope_h, intercept_h)
3. Fit linear regression to swing lows → lower trendline (slope_l, intercept_l)
4. Classify by slope combination:
   - **Ascending triangle:** slope_h ≈ 0, slope_l > 0 (flat top, rising bottom) → bullish
   - **Descending triangle:** slope_h < 0, slope_l ≈ 0 (falling top, flat bottom) → bearish
   - **Symmetrical triangle:** slope_h < 0, slope_l > 0 (converging) → continuation
   - **Rising wedge:** slope_h > 0, slope_l > 0, slope_l > slope_h (converging upward) → bearish
   - **Falling wedge:** slope_h < 0, slope_l < 0, slope_h < slope_l (converging downward) → bullish
5. Apex = intersection point of trendlines → breakout expected before 75% of apex distance
6. Confirmation: price breaks trendline with volume expansion

**Outputs:**
```python
outputs = frozenset({
    "tri_pattern",           # 0=none, 1=ascending, 2=descending, 3=symmetrical,
                             # 4=rising_wedge, 5=falling_wedge
    "tri_upper_slope",       # Upper trendline slope (price/bar)
    "tri_lower_slope",       # Lower trendline slope (price/bar)
    "tri_apex_bars",         # Bars until trendlines converge
    "tri_breakout_bias",     # -1 to +1 expected breakout direction
    "tri_confidence",        # 0-1 based on R² of trendlines, number of touches
})
```

**Incremental:** No — needs full swing sequence.

**Shared dependencies for all chart pattern plugins:**
- I3 swing detector output (swing highs/lows with indices) — reads from `frames["features"]` or computes from OHLCV
- `src/intelligence/utils.py` — `find_peaks`/`find_troughs` already available

**Estimated complexity:** ~100-150 lines each, 4-6 tests each. Total: ~400 lines, 15 tests.

---

## Batch 2 — Trend & Institutional Flow

### Parabolic SAR
- **Category:** Trend
- **Why:** Trailing stop / trend reversal detection. Complements ADX (strength) with discrete flip signals.
- **Incremental:** Yes — SAR updates from previous SAR + AF (acceleration factor), pure state machine.
- **Outputs:** `psar_value`, `psar_direction` (+1/-1)

### SuperTrend
- **Category:** Trend
- **Why:** ATR-based trend direction, extremely popular in futures/crypto. Clean binary trend signal.
- **Incremental:** Yes — depends on ATR (already have) + previous SuperTrend band.
- **Outputs:** `supertrend_value`, `supertrend_direction` (+1/-1)

### Chaikin Money Flow (CMF)
- **Category:** Volume
- **Why:** Accumulation/distribution pressure over N periods. Detects institutional buying/selling that OBV misses (OBV is cumulative, CMF is windowed).
- **Incremental:** Yes — rolling window of money flow volume / total volume.
- **Outputs:** `cmf_20` (-1 to +1 range)

---

## Batch 3 — Mean Reversion & Volatility

### Stochastic RSI
- **Category:** Momentum
- **Why:** RSI of RSI — catches extreme overbought/oversold that regular RSI misses. Very effective for futures scalping.
- **Incremental:** Yes — maintain RSI rolling window, apply Stochastic formula on top.
- **Outputs:** `stoch_rsi_k_14`, `stoch_rsi_d_14`

### Aroon
- **Category:** Trend
- **Why:** Measures how many bars since the highest high / lowest low. Unique "trend age" signal not covered by any current indicator.
- **Incremental:** Yes — rolling deque of highs/lows (same pattern as Donchian).
- **Outputs:** `aroon_up_25`, `aroon_down_25`, `aroon_osc_25`

### Chandelier Exit
- **Category:** Volatility
- **Why:** ATR-based trailing stop levels. Pairs with SuperTrend for exit management. Uses highest high - ATR*multiplier for long, lowest low + ATR*multiplier for short.
- **Incremental:** Yes — rolling high/low window + ATR state (already have ATR).
- **Outputs:** `chandelier_long_22`, `chandelier_short_22`

---

## Batch 4 — Advanced Volume & Realized Volatility

### Accumulation/Distribution Line (ADL)
- **Category:** Volume
- **Why:** Cumulative volume-weighted close position within bar range. Divergence between ADL and price is a classic institutional signal.
- **Incremental:** Yes — cumulative (same pattern as OBV).
- **Outputs:** `adl_value`, `adl_slope_14`

### Volume-Weighted Moving Average (VWMA)
- **Category:** Volume
- **Why:** MA weighted by volume — when VWMA > SMA, heavy volume on up-bars (bullish). Simple but powerful divergence from SMA.
- **Incremental:** Yes — rolling sum of (close * volume) / rolling sum of volume.
- **Outputs:** `vwma_20`

### Historical Volatility (HV)
- **Category:** Volatility
- **Why:** Realized volatility (annualized std of log returns). Critical for VIX futures traders — compare HV to implied vol.
- **Incremental:** Yes — online variance (same pattern as Bollinger Bands).
- **Outputs:** `hv_20`, `hv_ratio_20` (HV / HV_SMA for vol regime)

---

## Batch 5 — Momentum & Volume Depth

### Ultimate Oscillator
- **Category:** Momentum
- **Why:** Triple-timeframe weighted momentum (7/14/28 periods). Reduces false signals by blending short, medium, and long cycles.
- **Incremental:** Yes — maintain 3 rolling sums of buying pressure / true range per timeframe.
- **Outputs:** `ult_osc` (0-100 range)

### True Strength Index (TSI)
- **Category:** Momentum
- **Why:** Double-smoothed momentum — two nested EMAs on price change. Superior signal-to-noise ratio vs RSI.
- **Incremental:** Yes — two nested EMA states (same pattern as MACD but applied to price change).
- **Outputs:** `tsi_25_13`, `tsi_signal_25_13`

### Force Index
- **Category:** Volume
- **Why:** Combines price change direction with volume magnitude. Spikes reveal institutional conviction.
- **Incremental:** Yes — EMA of (price_change * volume), single state value.
- **Outputs:** `force_2`, `force_13`

### Volume Rate of Change (VROC)
- **Category:** Volume
- **Why:** Volume momentum — detects volume surges before price moves.
- **Incremental:** Yes — rolling deque of volume (same pattern as ROC).
- **Outputs:** `vroc_14`

### Chaikin Oscillator
- **Category:** Volume
- **Why:** MACD applied to ADL. Measures momentum of money flow.
- **Incremental:** Yes — two EMAs of ADL value (3-period and 10-period).
- **Outputs:** `chaikin_osc_3_10`
- **Dependency:** Requires ADL (Batch 4).

---

## Future Pattern Ideas

### Smart Money Concepts (I6) — COMPLETED
- ~~BOS/CHoCH, Order Blocks, FVG, Liquidity Sweeps~~ → `src/intelligence/smart_money/` (6 plugins, 28 tests)
- ~~BOCPD Change Point Detection~~ → Bayesian online change point detection, O(1) amortized, pure numpy
- ~~HMM Market Regime~~ → 3-state HMM (ranging/up/down), multivariate Gaussian emissions, incremental forward algorithm, pure numpy

### Probabilistic & ML Models
- ~~**BOCPD Change Point Detection**~~ — COMPLETED. `src/intelligence/smart_money/bocpd_changepoint.py`
- ~~**HMM Market Regime**~~ — COMPLETED. `src/intelligence/smart_money/hmm_regime.py` (pure numpy, no hmmlearn)
- **Monte Carlo VaR** — probabilistic risk assessment (future I7 dependency)

### Cross-Market Intelligence (I6+)
- **Contango/Backwardation** — futures term structure (specific to this platform)
- **Cross-Contract Momentum** — relative strength across ES/NQ/RTY
- **VIX-SPX Correlation** — volatility regime confirmation

---

## Not Prioritized (revisit later)

- **Ichimoku Cloud** — complex (5 components), more relevant for forex/equities than futures scalping
- **Elder-Ray (Bull/Bear Power)** — largely redundant with existing +DI/-DI from ADX
- **Hurst Exponent** — interesting but computationally expensive, better suited for I4 context tier
- **Fractal Indicator** — Williams fractals, overlaps with I3 swing detector
