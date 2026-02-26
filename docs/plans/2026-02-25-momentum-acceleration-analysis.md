# Momentum Acceleration (Second-Derivative Analysis)

Date: 2026-02-25
Status: Idea — not scheduled

## Concept

Second-derivative rate-of-change analysis computes `f''(x)` — the rate of change of
the first derivative. In trading terms: not whether momentum is positive, but whether
it is *accelerating or decelerating*.

Key properties:
- `f''(x) > 0` → concave up → momentum increasing (trend speeding up)
- `f''(x) < 0` → concave down → momentum decreasing (trend slowing)
- `f''(x) = 0` → inflection point → peak or trough of momentum (earliest reversal signal)

## Why RSI and MACD, not raw price

Applying the second derivative to raw price is too noisy — the signal requires heavy
smoothing before differentiation, defeating the early-detection purpose.

RSI and MACD are already first-order smoothed series. Their second derivatives are clean
and interpretable without additional filtering.

- **RSI acceleration**: RSI *decelerating toward 50* is an earlier reversal signal than
  RSI *crossing 50*. Sign change of `d(RSI)/dt` marks momentum exhaustion.
- **MACD acceleration**: MACD histogram is already `Δ(MACD line)`, so the second
  derivative of the MACD line is essentially histogram slope — acceleration of trend divergence.
- **ROC acceleration**: `d(ROC)/dt` measures whether the rate of price change is
  itself increasing or decreasing — pure price acceleration signal.

## Inflection Points → Trading Signals

Inflection points (zero-crossings of the second derivative) indicate:
- **Peak momentum** → likely trend continuation but slowing → reduce position or tighten stops
- **Trough momentum** → potential momentum reversal → early entry trigger

These map naturally onto I5 pattern detection (divergence, exhaustion) and could enrich
I4 momentum context classification without pipeline restructuring.

## Proposed Architecture

**New I1 plugin: `MomentumAcceleration`**

Consumes: `rsi_14`, `macd_12_26_9`, `roc_14` (already in I1 stream)

Outputs:
- `rsi_accel` — `Δ(rsi_14)` over 1 bar (or smoothed over N bars)
- `macd_accel` — `Δ(macd_12_26_9)` over 1 bar
- `roc_accel` — `Δ(roc_14)` over 1 bar
- `inflection_flag` — bool, true when any of the above crosses zero this bar

Implementation: stateful deque holding previous indicator values; `compute_next()` does
single subtraction. Zero extra lookback needed beyond what ROC/MACD/RSI already require.

## Downstream Value

- I4 `MomentumContext` gets richer: not just "momentum is positive" but "momentum is
  accelerating / decelerating / at inflection"
- I5 divergence patterns can cross-reference `inflection_flag` to confirm exhaustion
- I8 LLM narrative gains a more precise description of momentum phase
- ML training dataset gets `rsi_accel` / `macd_accel` features which are highly
  predictive of short-term reversals

## Trade-offs

| Approach | Pro | Con |
|---|---|---|
| Second derivative of price | Mathematically pure | Too noisy without heavy smoothing |
| Second derivative of RSI/MACD/ROC | Clean signal, already smoothed | One step removed from price |
| Generalized wrapper (any series) | Flexible | Over-engineered for current needs |

**Recommended**: second derivative of RSI + MACD + ROC as a single I1 plugin.

## Dashboard Visualization (future)

A small sparkline or oscillator panel showing `rsi_accel` centered on zero, with
inflection points marked, would make momentum phase immediately visible — the "slope of
the slope" chart concept that motivated this idea.
