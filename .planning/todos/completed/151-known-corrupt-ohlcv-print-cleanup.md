---
status: completed
priority: P2
filed: 2026-07-19
completed: 2026-07-20
source: todo 148 closeout -- its Fix item 3 ("enumerate the ~27 known rows, verify
  each underlying print, correct or tombstone") was never done. 148 shipped the
  measurement-layer guard (forward_returns.return_{scale}_suspect) and flagged the
  ~76 derived rows it produced, but the raw corrupt OHLCV prints themselves are
  still live in market_data_ohlcv, unverified and uncorrected.
---

## Disposition (2026-07-20)

`--apply` run against the live database: 18 CONFIRMED_CORRUPT rows corrected (volume
set to 0 on the raw print; price columns untouched per Renaissance retention
principle -- the row is never deleted). All 18 audited in `integrity_monitor`
(`monitor_type='price_sanity_ohlcv_correction'`, 18 rows confirmed).

Because `forward_return_writer.py` has no historical-gap-fill mode (purely
incremental off `MAX(bar_ts)`), closing the exposure this todo names ("z-score
features computed directly from these bars are contaminated... 148's guard does
nothing for that") required a full recompute of the 4 affected symbols' entire
history, not just a window around the corrected bars -- `forward_return_writer`'s
`ON CONFLICT DO NOTHING` insert means a bare re-run silently skips any bar_ts that
already has a (now-stale) row. Full pipeline for RSP/UUP/VWO/XRT (all 4 tfs, full
~20-year history): `backfill_status` reset to `pending` for these (symbol, tf) pairs
first (`fetch_complete` preserved -- `market_data_ohlcv`/source data was never
touched, no IBKR re-fetch needed) -- required, or `--compute-only` silently no-ops
on any (symbol, tf) already marked `status='complete'` (a known gotcha, same class
as the memory-tracked `--compute-only` empty-`backfill_status` no-op). Timed
empirically:
`backfill_feature_factory.py --compute-only` ~12.5 min (16/16 symbol/tf pairs, 0
below 80% coverage threshold), `forward_return_writer.py` (full history, all 4 tfs)
~4.5 min. ~17 min total for 4 symbols' full recompute -- useful reference point for
sizing any future similar full-symbol backfill.

Verified: the previously-created gap (UUP/5m 2007-06-19 to 2007-06-21, 0 rows) is
now filled (19 rows). Post-recompute row counts match or slightly exceed pre-delete
counts (small positive deltas exactly where a corrected bar's neighborhood now
computes a valid return it couldn't before). 17 residual `return_*_suspect` rows
remain across these 4 symbols' full history -- expected: the guard correctly
flagging rows outside this todo's 18-row scope, not touched, not investigated here
(a future finding if anyone re-runs `ops_known_corrupt_print_cleanup.py` again).

**Progress 2026-07-19:** tooling built --
`scripts/ops/corpus/ops_known_corrupt_print_cleanup.py`, dry-run-default, candidate
discovery via 148's `return_{scale}_suspect` flags, verification via neighbor-agreement
classification (`CONFIRMED_CORRUPT` requires an implausible field AND agreeing
neighbors -- see the script's own docstring). Live dry-run: 91 candidates -> 27
CONFIRMED_CORRUPT, 64 AMBIGUOUS. Found contaminated with real May 6 2010 Flash Crash
data (`CWB`/`RSP`/`VTV`/`VYM`) that a single-symbol neighbor-agreement check cannot
distinguish from genuine corruption -- blocked on [152](../completed/152-price-sanity-guard-flags-real-crisis-events.md).

**Unblocked 2026-07-20** -- 152 shipped its cross-symbol corroboration signal; this
todo now reuses it (`apply_cross_symbol_downgrade`, `count_corroborating_symbols`, new
`MARKET_EVENT` verdict, same two APR keys from migrations 240/241) to split
`CONFIRMED_CORRUPT` from real market events automatically. Re-ran the dry-run against
live data: CONFIRMED_CORRUPT dropped from 27 to **18 rows** (`RSP` x1 isolated
2007-08-01 print, `UUP` x10, `VWO` x6, `XRT` x1); exactly 1 row (`RSP` 2010-05-06,
`cross_symbol_corroborated_n=7`) correctly downgraded to `MARKET_EVENT`. `CWB`/`VTV`/
`VYM` dropped out of candidacy entirely once 152's own fix cleared their only suspect
flags upstream in `forward_returns`. **`--apply` still NOT run -- this is the remaining
step, and per the script's own module docstring it requires a human to review the
CONFIRMED_CORRUPT table (reproduced in the dry-run report) before running it, not an
agent.** Command: `python scripts/ops/corpus/ops_known_corrupt_print_cleanup.py --apply`.

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
