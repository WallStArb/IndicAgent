# 2nd Derivative Indicator Research

**Created:** 2026-03-02
**Status:** Reference — candidates evaluated against existing pipeline

---

## Context

This doc surveys 2nd-derivative-style indicators from TradingView/trading literature and assesses fit with the IndicAgent I2 pipeline. The `MomentumAcceleration` I2 plugin (implemented 2026-03-02) already covers the most obvious candidates — this doc focuses on what remains genuinely new.

## What We Already Have

| What | Where | Covers |
|------|-------|--------|
| `rsi_accel` = Δ(RSI) | `evt_MomentumAcceleration` I2 | First diff of RSI momentum |
| `macd_accel` = Δ(MACD) | `evt_MomentumAcceleration` I2 | First diff of MACD line |
| `roc_accel` = Δ(ROC) | `evt_MomentumAcceleration` I2 | ≈ d²(price)/dt² |
| `inflection_flag` | `evt_MomentumAcceleration` I2 | Sign-change detection on all three |
| `stoch_rsi_*` | I1 + `StochasticEvents` I2 | RSI-of-RSI (a form of 2nd deriv) |
| `macd_hist_turning_up` | `MACDEvents` I2 | Histogram direction change |

---

## Candidates Evaluated

### 1. Derivative Oscillator (Constance Brown) — WORTH BUILDING

**Source:** "Technical Analysis for the Trading Professional" by Constance Brown

**Formula (4 steps):**
1. `RSI` = standard RSI(14)
2. `DS1` = EMA(RSI, 5) — first smooth
3. `DS2` = EMA(DS1, 3) — second smooth (double-smoothed RSI)
4. `Signal` = SMA(DS2, 9)
5. **Output:** `deriv_osc = DS2 - Signal`

**What it does:** Produces an oscillator centered around zero. Zero-line crossovers and divergence with price are the primary signals. The double-smoothing removes RSI's short-term noise; subtracting the signal line removes medium-term drift. Result leads MACD by approximately 1-2 bars.

**Why it's different from `rsi_accel`:** `rsi_accel` is a raw first difference — noisy, unbounded, no signal line. The Derivative Oscillator applies structured smoothing (EMA5 → EMA3) before differencing against a 9-period SMA. It produces a bounded, trader-readable oscillator with crossover events.

**Architecture fit:** I2 plugin. Consumes `rsi_14` from I1 features, maintains internal EMA state for the double-smooth chain and signal line.

**Outputs:** `deriv_osc`, `deriv_osc_signal`, `deriv_osc_cross_bullish`, `deriv_osc_cross_bearish`, `deriv_osc_divergence` (optional)

**Parameters:** EMA1=5, EMA2=3, Signal=9 (standard)

**Warmup:** Needs ~26 bars of RSI history before the double-smooth and signal stabilize.

---

### 2. Ehlers "Elegant Oscillator" (John Ehlers, S&C 2022) — INTERESTING, COMPLEX

**Source:** "Inverse Fisher Transform" series, Stocks & Commodities magazine 2022

**Formula:**
1. `Deriv = Close[0] - Close[2]` (2-bar price difference → effectively d²price/dt² + whitens spectrum)
2. `RMS = sqrt(mean(Deriv² over 50 bars))` — normalize to standard deviations
3. `NDeriv = Deriv / RMS`
4. Apply inverse Fisher transform (soft-limits NDeriv to ±1): `IFT = (e^(2*NDeriv) - 1) / (e^(2*NDeriv) + 1)`
5. Pass through SuperSmoother filter (2-pole IIR, critical period ~20): **Output**

**What it does:** Near-zero-lag oscillator. By differencing price (whitening), normalizing, soft-limiting, then smoothing, it produces a cycle-sensitive indicator with minimal lag and clean peaks/troughs. Excellent for mean-reversion timing.

**Why different:** Pure price derivative (no RSI dependency), DSP-based normalization, inverse Fisher soft-limiting. The SuperSmoother is a 2-pole IIR that outperforms EMA for noise rejection.

**Architecture fit:** I1 plugin (consumes only `close`, no dependency on other I1 outputs). Internal state: rolling RMS over 50 bars + two prior SuperSmoother values.

**Complexity:** Medium-high. Inverse Fisher transform and SuperSmoother require careful incremental implementation. Not a one-afternoon job.

**Outputs:** `ehlers_elegant_osc`, `ehlers_elegant_peak`, `ehlers_elegant_trough`

---

### 3. Redundant — Skip

| Indicator | Why redundant |
|-----------|--------------|
| MaxWarren's Pine Acceleration | Same concept as `rsi_accel` / `roc_accel` |
| jas9360 2nd Derivative | `roc_accel` ≈ d²(close)/dt² already |
| StochRSI "as 2nd deriv" | Already in I1 + `StochasticEvents` |

---

---

## Additional Candidates (Round 2, 2026-03-02)

### 4. MACD Histogram Acceleration — PARTIAL GAP

**What it is:** The MACD histogram = MACD line − signal. A _shrinking_ histogram (consecutive bars getting closer to zero) signals momentum deceleration before the crossover. The 1st derivative of the histogram (`Δhist`) is the acceleration of momentum divergence.

**What we have:** `MACDEvents` already detects `macd_hist_turning_up` (histogram sign flip from negative to rising) and `macd_hist_positive`. What we _don't_ have: `macd_hist_accel` = `hist[t] - hist[t-1]` and a `hist_expanding` / `hist_contracting` flag.

**Gap:** Small but real. Histogram contraction (negative `macd_hist_accel` while histogram still positive) is a widely-used early warning of trend exhaustion — earlier than `macd_hist_turning_up`.

**Recommendation:** Extend `MACDEventsPlugin` with two new outputs — `macd_hist_accel` and `macd_hist_contracting` (flag: 1 if positive hist is shrinking or negative hist is expanding toward zero). No new plugin needed.

---

### 5. AC Oscillator (Bill Williams Acceleration/Deceleration) — NEW, BUILDABLE

**Formula:**
1. `midpoint = (high + low) / 2`
2. `AO` (Awesome Oscillator) = SMA(midpoint, 5) − SMA(midpoint, 34)
3. `AC = AO − SMA(AO, 5)`

**What it measures:** AO = momentum of midpoints (1st derivative-ish). AC = rate of change of AO (2nd derivative). Williams called it "the acceleration of momentum itself." The AC crosses zero before AO does, giving an earlier signal.

**What we have:** Nothing. We don't have AO or AC anywhere in the pipeline. We have MACD (EMA-based momentum) but not midpoint SMA-based momentum.

**Architecture fit:** Two-step I1 plugin (`ac_oscillator.py`) computing both AO and AC incrementally. Inputs: `high`, `low`. Outputs: `ao`, `ac`, optionally `ac_bullish` / `ac_bearish` (zero-cross flags — could be I2 events instead).

**Signals:** AC > 0 and rising = accelerating upward momentum. AC turns positive before AO does. AC histogram color changes (green/red relative to prior bar) are Williams' primary signal.

**Implementation complexity:** Low-medium. Two rolling SMAs (5 and 34 of midpoint) + rolling SMA(5) of AO. All incremental-friendly.

---

### 6. Ehlers Simple Deriv (TradingView script) — ALREADY DOCUMENTED

Same as the Ehlers Elegant Oscillator in the previous section (Section 2). The TradingView script wraps the same d²price/dt² → normalize → SuperSmoother approach. No new information.

---

### 7. Hull Moving Average Derivatives — INTERESTING, DEFERRED

**What it is:** HMA = WMA(2×WMA(n/2) − WMA(n), sqrt(n)). Taking 1st derivative (HMA[t] − HMA[t-1]) gives HMA slope. 2nd derivative detects when the slope itself reverses — earlier entry signal than the price crossing HMA.

**What we have:** No HMA in I1. We have many MAs (`ma_plugin` covers EMA/SMA/WMA) but HMA requires WMA-of-combination-WMA.

**Prerequisite:** Add HMA to I1 first. Then HMA 1st and 2nd derivatives are natural I2 plugin outputs.

**Gap assessment:** Genuine gap — HMA is widely used and its derivative is a cleaner signal than price-crosses-HMA. But blocked until HMA lands in I1.

**Recommendation:** Add HMA as a todo for `ma_plugin` or a new `hma_plugin`. Once there, 2nd derivative is trivial (same pattern as `MomentumAcceleration`).

---

## Recommendation

**Priority order:**

| Priority | Indicator | Effort | Notes |
|----------|-----------|--------|-------|
| 1 | **Derivative Oscillator** (Constance Brown) | Low | I2 plugin, RSI from I1, EMA chain in `_state` |
| 2 | **MACD Histogram Accel** | Very low | Extend `MACDEventsPlugin` — 2 new outputs |
| 3 | **AC Oscillator** (Bill Williams) | Low-med | New I1 plugin — AO + AC from high/low midpoints |
| 4 | **HMA + derivatives** | Med | I1 HMA first, then I2 accel trivial |
| 5 | **Ehlers Elegant Oscillator** | Med-high | I1 plugin, inverse Fisher + SuperSmoother IIR |

**Immediate:** Derivative Oscillator is the highest signal-to-effort ratio — well-documented, clean I2 fit, leads MACD.

**Quick win:** MACD histogram acceleration extends an existing plugin with ~10 lines of code.

**Interesting pipeline expansion:** AC Oscillator brings Bill Williams' framework in; if we later add Williams Alligator / Fractals, AC fits that family.

---

## Implementation Notes (when ready)

**Derivative Oscillator I2:**
```python
# _state keys: ema1, ema2, signal, prev_osc
alpha1 = 2 / (5 + 1)  # EMA(5)
alpha2 = 2 / (3 + 1)  # EMA(3)
# signal is SMA(9) — need rolling 9-bar buffer of DS2
```
Warmup: suppress outputs for first 26 bars (RSI needs 14 + double-smooth needs ~12 more).

**Ehlers SuperSmoother (for future reference):**
```python
# 2-pole IIR, critical period P
a1 = exp(-sqrt(2) * pi / P)
b1 = 2 * a1 * cos(sqrt(2) * pi / P)
c2 = b1; c3 = -a1**2; c1 = 1 - c2 - c3
ss[t] = c1 * (x[t] + x[t-1]) / 2 + c2 * ss[t-1] + c3 * ss[t-2]
```
