# Continuous Contracts & Roll Adjustment

**Date:** 2026-02-24
**Context:** Designing multi-TF historical backfill for ML training data

## Decision

Use **back-adjusted continuous contracts** (ContFuture + ADJUSTED_LAST) for all deep history fetches. Named contracts for 1m only (no rolls in 35 days).

| TF | Days | Contract type | Rationale |
|----|------|--------------|-----------|
| 1m | 35 | Named (ESH6) | No roll crossings |
| 5m | 365 | Continuous adjusted | ~4 rolls |
| 15m | 365 | Continuous adjusted | ~4 rolls |
| 1h | 730 | Continuous adjusted | ~8 rolls |
| 1d | 1825 | Continuous adjusted | ~20 rolls |

## Why back-adjustment

Our I1–I7 plugins compute indicators on price continuity. Naively stitching ESZ5→ESH6→ESM6 creates artificial jumps that produce false RSI/MACD/BB signals at every roll. Back-adjustment (additive, Panama method) eliminates these jumps.

Ratio adjustment is theoretically better for percentage-return features but adds complexity with no meaningful gain for our indicator-based approach.

## IBKR implementation

ib_insync `ContFuture(symbol=base, exchange=exchange)` with `whatToShow='ADJUSTED_LAST'`. IBKR handles the roll stitching and adjustment natively. `IBKRProvider.fetch_historical_bars()` now accepts `continuous=True` to use this path.

The named contract must still be pre-qualified (to resolve base symbol + exchange), then `ContFuture` is built inline from those attributes.

## Live pipeline

Live services always use named contracts — correct for trading (you trade the named contract). Back-adjustment is only for historical feature computation. At roll dates, live bars have a one-time price gap in `market_data_ohlcv`; acceptable for live operation.

## Future considerations

- **Days-to-expiry** as an ML feature (see IDEAS.md) — behavior near expiry differs
- **Roll premium/discount** as a feature — the spread IS the contango/backwardation signal
- A parallel continuous series for live indicator computation (not yet needed)
