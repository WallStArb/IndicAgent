# Momentum Acceleration (Second-Derivative Analysis)

**Version:** 1.0.0
**Status:** draft
**Priority:** medium
**Milestone:** future (post-v2.8)
**Last Updated:** 2026-02-27
**Tags:** momentum, second-derivative, acceleration, indicators, rsi, macd, roc, intelligence

**Detail / implementation plan:** [docs/plans/2026-02-25-momentum-acceleration-analysis.md](../plans/2026-02-25-momentum-acceleration-analysis.md)

---

## The Big Idea

Stop asking only *whether* momentum is up or down. Ask *whether momentum is accelerating or decelerating* — the second derivative of the series.

- **f''(x) > 0** — momentum increasing (trend speeding up)
- **f''(x) < 0** — momentum decreasing (trend slowing)
- **f''(x) = 0** — inflection point: peak or trough of momentum, and the **earliest** reversal signal

Inflection points show up *before* price or RSI cross a level. RSI decelerating toward 50 is an earlier signal than RSI crossing 50.

---

## Why RSI, MACD, and ROC (Not Raw Price)

Second derivative of raw price is too noisy; you end up smoothing so much that you lose the early-detection benefit.

RSI, MACD, and ROC are already smoothed. Their second derivatives stay clean and interpretable:

- **RSI acceleration** — sign change of d(RSI)/dt marks momentum exhaustion.
- **MACD acceleration** — slope of the MACD line (histogram slope) = acceleration of trend divergence.
- **ROC acceleration** — d(ROC)/dt = whether rate of price change is increasing or decreasing.

---

## Inflection Points as Trading Signals

| Inflection type | Interpretation | Use |
|-----------------|----------------|-----|
| Peak momentum   | Trend continuing but slowing | Reduce size or tighten stops |
| Trough momentum| Momentum reversing          | Early reversal / entry trigger |

These plug into existing I5 pattern detection (divergence, exhaustion) and I4 momentum context without changing the rest of the pipeline.

---

## Proposed Shape

- **New I1 plugin:** `MomentumAcceleration`, consuming existing `rsi_14`, `macd_12_26_9`, `roc_14`.
- **Outputs:** `rsi_accel`, `macd_accel`, `roc_accel`, plus an `inflection_flag` when any crosses zero.
- **Implementation:** Stateful; one bar lookback (difference from previous value). No extra history beyond what RSI/MACD/ROC already use.

Downstream: I4 momentum context, I5 exhaustion/divergence, I8 narratives, and ML features all gain from “slope of the slope” without pipeline restructuring.

For architecture, trade-offs, and dashboard ideas, see the [full plan](../plans/2026-02-25-momentum-acceleration-analysis.md).
