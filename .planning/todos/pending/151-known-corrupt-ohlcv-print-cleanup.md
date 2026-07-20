---
status: pending
priority: P2
filed: 2026-07-19
source: todo 148 closeout -- its Fix item 3 ("enumerate the ~27 known rows, verify
  each underlying print, correct or tombstone") was never done. 148 shipped the
  measurement-layer guard (forward_returns.return_{scale}_suspect) and flagged the
  ~76 derived rows it produced, but the raw corrupt OHLCV prints themselves are
  still live in market_data_ohlcv, unverified and uncorrected.
---

# ~27 known corrupt OHLCV prints are still live in `market_data_ohlcv` -- verify and correct/tombstone

## Problem

Todo 148 added a plausibility guard on `forward_returns` (derived data) but never touched
the underlying corrupt bars in `market_data_ohlcv` (source data) that caused the problem.
Confirmed still present, e.g.:

```
symbol | timeframe |       timestamp        | open | high |  low  | close | volume
UUP    | 5m        | 2007-06-20 19:00:00+00 | 1000 | 1000 | 28.97 | 28.97 |    200
```

This matters beyond `forward_returns`: 148's own problem statement flagged that
z-score features computed directly from these bars (`momentum_z_*`, `volatility_rank`)
are contaminated for the affected windows, and 148's guard does nothing for that --
it only protects mean-based consumers of `forward_returns`. Anything reading
`market_data_ohlcv`/`market_data_ohlcv_tradeable` directly for these (symbol, tf,
timestamp) neighborhoods is still exposed.

## Fix

1. Re-run the live scan from 148 (or reuse its forensic queries in
   `docs/research/fable-2026-07-19-emission-threshold-alpha-verdict.md` Q4 appendix)
   to get the current, authoritative list -- the original ~27 count is from
   2026-07-19 and may have drifted with any backfill since.
2. For each row: verify against a second source if available (IBKR re-fetch, or
   cross-check against a neighboring bar/vendor) whether the print is genuinely
   corrupt (not a real crisis move).
3. Correct (re-fetch the real print) where possible; tombstone (a documented,
   flagged exclusion, not silent deletion -- Renaissance retention principle) where
   not. Re-run `forward_return_writer` and any feature computation for the affected
   neighborhoods so derived tables pick up the fix.

## Sizing

Todo-sized: ~27 rows, bounded verification + correction, one targeted re-run of
downstream writers for the affected neighborhoods. Not urgent -- 148's guard already
protects the specific failure mode (mean-based `forward_returns` consumers) that
caused a real problem; this closes the remaining exposure (raw-OHLCV-reading
consumers, feature-level contamination) at lower urgency.

## References

- `.planning/todos/completed/148-forward-return-corrupt-print-guard.md` -- Fix item 3,
  never completed
- `.planning/todos/pending/149-bar-ingestion-price-sanity-guard.md` -- the forward-
  looking sibling (prevents future occurrences at ingestion); this todo is the
  backward-looking cleanup of the known historical ones, not the same fix
- `docs/research/fable-2026-07-19-emission-threshold-alpha-verdict.md` -- Q4 forensic
  queries, original ~27-row scan
