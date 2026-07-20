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

**Progress 2026-07-19:** tooling built --
`scripts/ops/corpus/ops_known_corrupt_print_cleanup.py`, dry-run-default, candidate
discovery via 148's `return_{scale}_suspect` flags, verification via neighbor-agreement
classification (`CONFIRMED_CORRUPT` requires an implausible field AND agreeing
neighbors -- see the script's own docstring). Live dry-run: 91 candidates -> 27
CONFIRMED_CORRUPT, 64 AMBIGUOUS. **BLOCKED on [152](152-price-sanity-guard-flags-real-crisis-events.md)
before any `--apply`:** manually cross-checked the 27-row CONFIRMED_CORRUPT list against
every other symbol trading at the same timestamps and found it's contaminated with real
May 6 2010 Flash Crash data -- `CWB`, `RSP`, `VTV`, `VYM` all show 5+ OTHER unrelated ETFs
(`ITA`, `VUG`, and dozens more) trading normally except for a coincident collapse at the
exact same 5-minute bar, the textbook stub-quote signature, not corruption. The
neighbor-agreement heuristic cannot distinguish a genuine V-shaped flash-crash recovery
from actual corruption -- both produce an "isolated spike, neighbors agree" signature.
`RSP` specifically has BOTH a genuine bad print (2007-08-01, `high=499.99`, confirmed
isolated -- zero other symbols affected at that timestamp) AND Flash Crash rows
(2010-05-06) in the SAME symbol's CONFIRMED_CORRUPT bucket, so a symbol-level `--apply`
cannot safely separate them. The other 23 rows (`UUP` x11 across dates, `VWO` x4, `XRT`
x1, `RSP`'s 2007-08-01 row) were manually verified isolated -- zero other symbols
affected at their exact timestamps -- and are safe to apply once 152's cross-symbol
check lands and produces a clean re-classification (expected to move the 4 contaminated
rows to AMBIGUOUS/PLAUSIBLE automatically, no manual row-picking needed). Do not run
`--apply` before 152 lands.

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
