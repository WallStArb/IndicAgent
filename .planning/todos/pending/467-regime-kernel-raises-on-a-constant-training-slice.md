---
status: pending
priority: P3
filed: 2026-09-30
source: plan 186-13, found while adding a flat-series test
---

# Regime kernels raise (hmmlearn ValueError) when a training slice has no variance

## What

`hmm_trend_walk_forward` and `hmm_volatility_walk_forward` fit a GaussianHMM on the observations
before each refit boundary. If the whole training slice is constant (a close that never moves, a
dead or halted name), `GaussianHMM.fit` raises `ValueError: 'covars' must be symmetric,
positive-definite` instead of returning a degenerate fit that the occupation gate would skip.
The old writer raised the same way; its worker caught the error per cell (`worker_cell_failed`).

## Why it matters

The rebuild (186-25) computes regime columns through the kernels in one pass. A kernel exception
there fails the whole (symbol, tf) unit unless the per-unit failure isolation from `bulk_load`
catches it, and the cell then has no regime labels and no reason recorded in the segment status.

## Fix

Catch the fit failure inside `_walk_forward_hmm_full`, report the segment as degenerate with
reason `fit_failed` (status 4, `segment_status` already has an "other gate reason" code), and
add a test on a constant close after a valid warmup. Check whether any live universe name has a
constant 600-bar prefix before deciding it is worth doing before 186-25.

## Measured (2026-10-02, against `market_data_ohlcv_tradeable`)

No trigger exists in stored data: zero (symbol, tf) pairs have a constant close prefix reaching
the first refit boundary (warmup 39,600 at 5m, 13,200 at 15m, 3,300 at 1h, 504 at 1d; per-symbol
window query), and zero series are fully constant (min(close) = max(close) per symbol and tf).
The exception is therefore unreachable on today's universe; the fix is hardening for the one-shot
186-26 rebuild (where a raise loses a whole (symbol, tf) unit with no recorded reason), not a
live defect. Cheap insurance if the executor has room; no evidence-based urgency.
