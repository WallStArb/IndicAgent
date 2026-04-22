# Regime Classification

**Last Updated:** 2026-04-22

## Overview

Regime classification answers a fundamental question: *What kind of market are we in right now?*

A trend-following strategy that works beautifully in a trending market will bleed out in a ranging one. A mean-reversion strategy that profits from oscillation fails in a momentum breakout. Trading without regime awareness is like sailing without checking the weather.

IndicAgent classifies regime across multiple dimensions — volatility, trend, momentum, and hidden state — using a combination of statistical models and classical indicators.

---

## Regime Dimensions

### Volatility Regime (I4: `VolatilityRegime`)

**Question:** Is the market quiet or explosive?

Uses ATR percentile rank over a rolling window to classify:
- `low` — ATR below 33rd percentile (compression, coiling)
- `normal` — ATR in the 33rd–67th percentile (baseline)
- `high` — ATR above 67th percentile (expansion, momentum)

Bollinger Band width provides a secondary signal for volatility expansion/contraction detection.

**Why it matters:** I7 setup plugins check volatility regime before firing. `SqueezeExpansion` only fires in `low → high` transitions. `MeanReversion` requires `low` or `normal` volatility.

---

### Trend Regime (I4: `TrendRegime`)

**Question:** Is price trending or ranging?

Uses SMA-20 / SMA-50 alignment with ADX strength:
- `uptrend_strong` / `uptrend_weak` — price above both MAs, ADX above/below threshold
- `downtrend_strong` / `downtrend_weak` — price below both MAs
- `sideways` — MAs interleaved, ADX below threshold

**Why it matters:** `TrendFollowing` and `MTFAlignment` setups require a trend regime. The regime gate in I7 rejects these plugins when the market is sideways.

---

### Momentum Context (I4: `MomentumContext`)

**Question:** Is momentum building or fading?

Scores four oscillators simultaneously (RSI, MACD histogram, Stochastic %K, CCI) and produces a composite momentum state:
- `accelerating` — majority of oscillators pointing strongly in one direction
- `decelerating` — oscillators diverging or flattening
- `neutral` — no clear momentum signal

---

### GARCH Volatility Forecast (I4: `GARCHVolatility`)

**Question:** What is tomorrow's expected volatility?

GARCH(1,1) (Generalized Autoregressive Conditional Heteroskedasticity) models volatility clustering — the empirical observation that high-volatility periods tend to follow high-volatility periods.

The model captures two effects:
- **ARCH effect (α):** Today's volatility is partially explained by yesterday's squared return
- **GARCH effect (β):** Today's volatility is partially explained by yesterday's conditional variance

```
σ²_t = ω + α × ε²_(t-1) + β × σ²_(t-1)
```

The one-step forecast `σ²_t` is used as a quality gate in I7: setups that require stable volatility conditions (`MeanReversion`, `VWAPDeviation`, `SqueezeExpansion`) are rejected when GARCH forecasts elevated volatility.

---

### Kalman Trend Filter (I4: `KalmanTrend`)

**Question:** What is the underlying trend, stripped of noise?

The Kalman filter is an optimal estimator that separates a signal (true price trend) from noise (random tick-by-tick variation). It maintains two state variables:
- **Position** — smoothed price level
- **Velocity** — rate of change (trend speed)

The observation noise `R` is optionally adaptive: when GARCH forecasts high volatility, `R` is increased, making the filter trust new observations less and rely more on its internal model. This prevents the trend estimate from being whipsawed during volatile periods.

The filter produces 7 output fields used by downstream plugins:
- `kalman_price` — smoothed price
- `kalman_velocity` — trend speed
- `kalman_trend_direction` — `+1` / `0` / `-1`
- `kalman_uncertainty` — posterior variance
- `kalman_innovation` — how surprising the latest bar was
- `kalman_signal_to_noise` — trend confidence
- `kalman_regime` — trend / ranging / uncertain

---

### HMM Regime (I6 SMC: `HMMRegime`)

**Question:** What hidden market state are we in?

A **Hidden Markov Model** (HMM) assumes that markets transition between a small number of hidden states (regimes), and that observed returns are drawn from distributions specific to each state. The states cannot be observed directly — only inferred from price behavior.

IndicAgent uses a 3-state HMM trained on recent returns:
- **State 0:** Ranging — low-volatility, mean-reverting
- **State 1:** Trending up — positive drift, higher volatility
- **State 2:** Trending down — negative drift, higher volatility

The **Viterbi algorithm** decodes the most likely sequence of hidden states given the observed returns. The **forward algorithm** computes the marginal probability of being in each state at the current bar.

**Critical use in I7:** The CISScorer applies a regime eligibility filter:
- Trend-following plugins → only active when HMM state is 1 or 2
- Mean-reversion plugins → only active when HMM state is 0
- Gate is bypassed when `hmm_regime_prob < REGIME_PROB_MIN` (settings-configurable, default 0.30) or `hmm_regime_duration < REGIME_DUR_MIN` (default 1 bar)

---

### BOCPD Changepoint Detection (I6 SMC: `BOCPDChangepoint`)

**Question:** Did the regime just change?

**Bayesian Online Changepoint Detection** (BOCPD) computes the probability that a structural break occurred at the current bar. Unlike HMM (which classifies what state we're in), BOCPD detects *when* the state changed.

A changepoint signal means: whatever you knew about recent market behavior may no longer be valid. Downstream plugins can use this to reset state or reduce confidence.

---

## Regime Integration in I7

The I7 tier does not just read regime signals — it enforces them as hard gates:

```python
# CISScorer regime filter (simplified)
if plugin.category == "trend":
    if hmm_state not in (1, 2) and hmm_prob >= 0.55:
        skip_plugin()  # not a trending regime
elif plugin.category == "mean_reversion":
    if hmm_state != 0 and hmm_prob >= 0.55:
        skip_plugin()  # not a ranging regime
```

This prevents the system from generating trend signals in ranging markets and mean-reversion signals in trending ones — the primary source of false signals in unregimed systems.

---

## Related Documentation

- [Intelligence Tiers](intelligence-tiers.md) — I4 and I6 tier details
- [Signal Lifecycle](signal-lifecycle.md) — how regime gates affect which signals survive to become trades
- [Incremental Computation](incremental-computation.md) — how GARCH/Kalman state is maintained across bars
- **Code:** `src/intelligence/context/`, `src/intelligence/smart_money/hmm_regime.py`, `src/intelligence/smart_money/bocpd_changepoint.py`
