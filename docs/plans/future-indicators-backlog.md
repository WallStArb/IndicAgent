# Future Indicators Backlog

> Ideas for indicator and pattern plugins beyond current implementation.
> Prioritized by value for a multi-futures trading platform.

---

## Completed From This Backlog

- **SuperTrend** — `ind_SuperTrend` in `src/intelligence/indicators/` (v4.3.0)
- **GARCH Volatility Plugin** — `ctx_GARCHVolatility` in `src/intelligence/context/garch_volatility.py` (v4.3.0)
- **Kalman Filter Trend Plugin** — `ctx_KalmanTrend` in `src/intelligence/context/kalman_trend.py` (v4.5.0)
- **Chart Pattern Detection** — `patt_DoubleTB`, `patt_HeadShoulders`, `patt_TriangleWedge` in `src/intelligence/patterns/` (v4.6.0)

---

## Priority Queue — Next Up

### 1. Parabolic SAR
- **Category:** Trend
- **Why:** Trailing stop / trend reversal detection. Complements ADX (strength) with discrete flip signals.
- **Incremental:** Yes — SAR updates from previous SAR + AF (acceleration factor), pure state machine.
- **Outputs:** `psar_value`, `psar_direction` (+1/-1)

### 2. Chaikin Money Flow (CMF)
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
