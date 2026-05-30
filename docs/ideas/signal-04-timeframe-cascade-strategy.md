# Structured Strategy to Execute the Transition

**Version:** 1.0.0
**Status:** draft
**Priority:** low
**Milestone:** future (post-v2.8)
**Last Updated:** 2026-02-27
**Tags:** timeframe, cascade, strategy, trailing-stop, momentum, trade-lifecycle

---

## Overview

A phased approach to taking a trade from micro entry (1m) through momentum hold (5m) to trend capture (15m–30m), with clear stop logic and transition triggers at each stage.

---

## Phase 1: The Micro Entry and Initial Trail (1m)

Goal: survive the "infant" stage of the trade where volatility is highest relative to position size.

- **The signal:** Enter on your 1m setup.
- **Initial stop:** Place at the recent 1m swing low or 1.5 ATR (1m).
- **The pivot:** Once price reaches a 2:1 reward-to-risk ratio, move the stop to breakeven.
- **Transition trigger:** After price makes two successful higher highs and higher lows on the 1m chart, stop looking at the 1m "noise" and zoom out.

---

## Phase 2: The Momentum Hold (5m)

Once the trade is "in the money," avoid being stopped out by minor 1m pullbacks.

- **Stop logic:** Move the stop to the last 5m swing low or the 5m 20-period EMA.
- **Liquidity focus:** Look for sell-side liquidity (unfilled gaps or old lows) on the 5m chart. Place the stop just below these zones; price often "pokes" these areas before continuing higher.
- **ATR buffer:** Use a 1.5 ATR buffer (5m) to allow for standard mean reversion.

---

## Phase 3: The Trend Capture (15m–30m)

If the 5m trend sustains for more than 30–60 minutes, the trade is no longer a scalp—it is a day trend.

- **The logic:** At this stage, only move the stop when a 15m candle closes.
- **Stop placement:** Use the low of the previous 15m candle or the 15m Parabolic SAR dots.
- **Why it works:** Ignores 5m micro-whips and only exits when the broader momentum of the hour shifts.

---

## The Timeframe Cascade: Cheat Sheet

| Phase   | Timeframe   | Stop logic                    | Goal                  |
|---------|-------------|-------------------------------|-----------------------|
| Entry   | 1m          | Recent swing low / 1.5 ATR    | Risk reduction and BE |
| Growth  | 5m          | 20 EMA / liquidity sweeps     | Lock in core profit   |
| Trend   | 15m / 30m   | Previous candle low           | Capture the daily move|
| Exit    | 1H+         | Structure break               | Maximum run potential |

---

## Key Rules for Success

1. **Never move backwards:** Once the stop is graduated to 5m logic, never move it back down to a 1m level.
2. **Volatility weighting:** Use Average True Range (ATR) so the stop is not mathematically too tight.
3. **Liquidity zones:** Always look for value area lows or volume nodes. If price is above a high-volume area on a higher timeframe, that area acts as a floor. Keep the stop on the other side of that floor.
