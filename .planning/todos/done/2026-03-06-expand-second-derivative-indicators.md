---
created: 2026-03-06T00:00:00.000Z
title: Expand second-derivative indicator coverage (I2/I3)
area: intelligence
files:
  - docs/plans/2026-03-10-second-derivative-indicators-design.md
  - docs/plans/2026-03-10-second-derivative-indicators-plan.md
  - src/intelligence/composites/
  - src/intelligence/structure/swing_momentum.py
  - src/intelligence/register_plugins.py
  - tests/unit/intelligence/composites/
---

## Status (2026-03-10) — Design + Plan Complete

**Ready to build.** Research session completed, scope narrowed to highest-alpha items.

- **Design doc:** `docs/plans/2026-03-10-second-derivative-indicators-design.md`
- **Implementation plan:** `docs/plans/2026-03-10-second-derivative-indicators-plan.md`

Planned scope (~4d, 5 chunks):
1. Extend `MomentumAcceleration` → `rsi_curvature`, `macd_hist_slope`, `price_accel`
2. New `ExhaustionScore` I2 plugin (3-condition danger score 0–1)
3. New `AccelerationRegime` I2 plugin (`building`/`peak`/`waning`/`trough`)
4. New `SwingMomentum` I3 plugin (structural amplitude + velocity)
5. Wire exhaustion guard into `MomentumBreakout`/`TrendFollowing`; boost into `LiquiditySweepReclaim`/`LiquidityHunt`

To execute: start fresh session, reference the plan doc, use `superpowers:subagent-driven-development`.

---

## Original Context

`MomentumAcceleration` (I2) already computes second derivatives of RSI, MACD, and ROC. The same approach has clear value applied to volume and volatility series. Before building, run a correlation/predictive analysis against `signal_ledger` outcomes to confirm which outputs have statistically meaningful edge before adding pipeline weight.

## Candidate plugins to research and build

**Volume acceleration (I2)**
- `obv_accel`: second derivative of OBV — is accumulation/distribution speeding up or slowing
- `cmf_accel`: second derivative of CMF — flow exhaustion before price stalls
- `volume_accel`: second derivative of raw volume — detects climactic volume expansion/contraction before it peaks

**Volatility acceleration (I2)**
- `atr_accel`: second derivative of ATR — is volatility expanding faster or contracting
- `garch_accel`: second derivative of GARCH vol estimate — leading signal for vol regime transitions before HMM/vol_regime flips
- `bb_width_accel`: second derivative of Bollinger Band width — squeeze/expansion inflection earlier than the squeeze plugin fires

**Structural acceleration (I2 or I3)**
- `sr_strength_accel`: second derivative of S/R level test count — levels gaining or losing significance
- `adx_accel`: second derivative of ADX — trend strength accelerating or exhausting (distinct from existing ADX events which use level thresholds)

## Research step (do first)

Before building any of the above, run analysis against `signal_ledger` + `intelligence_features`:
- Correlate inflection flag co-occurrence with profitable outcomes by setup type and regime
- Check which series have the cleanest second derivatives (low noise after one-bar diff) vs which need smoothing first
- Identify which complement existing I2/I4 outputs vs which are redundant with HMM/BOCPD

Existing related todos to coordinate with:
- `2026-03-04-add-derivative-oscillator-i2-plugin.md` — Derivative Oscillator (RSI double-smooth)
- `2026-03-04-extend-macd-events-histogram-accel.md` — MACD histogram acceleration
