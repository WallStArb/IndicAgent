# Future Indicators Backlog

**Version:** 1.0
**Status:** draft
**Priority:** low
**Milestone:** future
**Last Updated:** 2026-05-02
**Tags:** indicators, backlog, archived, supertrend, garch, kalman, patterns, intelligence

> **⚠️ ARCHIVED 2026-03-22**
>
> **Status: MOSTLY COMPLETED**
>
> This document has been archived as most items have been implemented or absorbed into active roadmap tracks. Remaining items are either superseded by newer approaches or no longer aligned with current priorities.
>
> **Completed items:** SuperTrend, GARCH Volatility, Kalman Filter, Chart Patterns, and many others.
>
> **See `.planning/ROADMAP.md` for current planning.**
>
> ---
>
> _Original content below for historical reference._

> Ideas for indicator and pattern plugins beyond current implementation.
> Prioritized by value for a multi-futures trading platform.

---

## Completed From This Backlog

- **SuperTrend** — `ind_SuperTrend` in `src/intelligence/indicators/` (v4.3.0)
- **GARCH Volatility Plugin** — `ctx_GARCHVolatility` in `src/intelligence/context/garch_volatility.py` (v4.3.0)
- **Kalman Filter Trend Plugin** — `ctx_KalmanTrend` in `src/intelligence/context/kalman_trend.py` (v4.5.0)
- **Chart Pattern Detection** — `patt_DoubleTB`, `patt_HeadShoulders`, `patt_TriangleWedge` in `src/intelligence/patterns/` (v4.6.0)

---

## Active Roadmap (2026-02-20)

Three planned tracks — each is a self-contained branch. Design doc: `docs/plans/2026-02-20-i1-i3-improvements-design.md`.

### Track A: New I1 Indicators — ✅ COMPLETED (v4.7.0)

| Plugin | Name | Key Outputs |
|---|---|---|
| Parabolic SAR | `ind_ParabolicSAR` | `psar_value`, `psar_direction` |
| Stochastic RSI | `ind_StochRSI` | `stoch_rsi_k_14`, `stoch_rsi_d_14` |
| Chandelier Exit | `ind_ChandelierExit` | `chandelier_long_22`, `chandelier_short_22` |
| Historical Volatility | `ind_HistoricalVolatility` | `hv_20`, `hv_ratio_20` |
| Aroon | `ind_Aroon` | `aroon_up_25`, `aroon_down_25`, `aroon_osc_25` |
| Chaikin Money Flow | `ind_CMF` | `cmf_20` |

~35 new tests. I1 count: 17 → 23.

### Track B: I3 Structure Enhancements — `feature/i3-structure-enhancements`

Enhance existing 3 plugins (no new plugins):
- `struct_SupportResistance`: add `resistance_2`, `support_2`, `sr_zone_width`, volume-weighted strength
- `struct_SwingDetector`: add `swing_high_magnitude`, `swing_low_magnitude`
- `struct_TrendStructure`: add `recent_leg_strength`, `swing_alternation`

~20 new tests.

### Track C: Momentum Composite — `feature/i1-momentum-composite`

New plugin `ind_MomentumComposite` in `src/intelligence/composites/momentum_composite.py`:
- `ema_stack_score` (−4 to +4), `golden_death_cross`, `adx_trend_qualified`, `momentum_consensus` (−3 to +3), `vol_squeeze_rank` (0–1)

~15 new tests.

---

## Deferred — Absorbed into Active Roadmap Track A

The following were previously listed as "next up" or in Batch 3 — all are now part of Track A (`feature/i1-new-indicators`). See Active Roadmap above.

- Parabolic SAR → `ind_ParabolicSAR`
- Chaikin Money Flow → `ind_CMF`
- Stochastic RSI → `ind_StochRSI`
- Aroon → `ind_Aroon`
- Chandelier Exit → `ind_ChandelierExit`
- Historical Volatility → `ind_HistoricalVolatility`

---

## Batch 4 — Advanced Volume & Realized Volatility
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
- **Status:** Absorbed into Track A — see Active Roadmap

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

### Smart Money Concepts (I6) — COMPLETED + 2 NEW PLANNED

- ~~BOS/CHoCH, Order Blocks, FVG, Liquidity Sweeps~~ → `src/intelligence/smart_money/` (6 plugins, 28 tests)
- ~~BOCPD Change Point Detection~~ → Bayesian online change point detection, O(1) amortized, pure numpy
- ~~HMM Market Regime~~ → 3-state HMM (ranging/up/down), multivariate Gaussian emissions, incremental forward algorithm, pure numpy
- **`smc_LiquidityPools`** *(planned — design: `docs/plans/2026-02-22-liquidity-pools-supply-demand-design.md`)*
  Named institutional levels: PWH/PWL, PDH/PDL, equal highs/lows (ATR × 0.75 tolerance, 2-3+ touches), session high/low. Significance scores 0.5–1.0. Premium/discount flag (20-bar range midpoint). 1m + 1d InputSpec. 13 output fields.
- **`smc_SupplyDemandZones`** *(planned — same design doc)*
  Detects Rally-Base-Drop (supply) and Drop-Base-Rally (demand) origin zones on 15m. Base = body/range < 0.5, impulse = close-to-close > ATR × 1.5. Freshness lifecycle: fresh (1.0) → tested (0.5) → mitigated (0.0, removed). Strength scoring: premium/discount alignment × 1.2, FVG-inside × 1.15, age decay. Tracks 5 active zones per side. 14 output fields.

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
