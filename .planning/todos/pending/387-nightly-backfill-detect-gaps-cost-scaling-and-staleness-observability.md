---
status: pending
priority: P1
filed: 2026-09-22
source: /simplify's efficiency + altitude review agents on todo 382's fix (removing
  nightly-backfill's batch_size cap) -- both independently converged on the same
  underlying concern from different angles
---

# Nightly backfill's full-universe dispatch (todo 382) has two follow-ups: unverified per-symbol DB cost scaling, and the observability gauge todo 382 itself called for but didn't ship

## What

Todo 382 (P0, closed 2026-09-22) fixed the nightly OHLCV backfill's mathematically-guaranteed
staleness floor by deleting a `LIMIT batch_size` cap on candidate selection -- every
compute-eligible symbol (233, growing) is now dispatched to the delegate script
(`infrastructure_run_historical_pipeline.py`) every night instead of the stalest 20. The fix
itself is correct and shipped (see `scripts/infrastructure/backfill/infrastructure_nightly_backfill.py`'s
module docstring for the full incident writeup). Two things from that fix's own review are
worth tracking separately rather than dropping silently:

**1. `detect_gaps()` is NOT actually a near-zero-cost no-op, contrary to the fix's stated
justification.** Both the code docstring and migration 349's comment assert every
already-current symbol costs ~nothing to leave eligible. Verified false on inspection:
`detect_gaps()` (`infrastructure_run_historical_pipeline.py:782-828`) always scans the FULL
configured `fetch_days` window per timeframe (default 7300 days / 20yr -- `_TF_FETCH_CONFIG`),
not "since last known bar" -- there's no `--days` override from the nightly wrapper. Measured
live: a single mature symbol's 5m-timeframe gap check (GDX, 2.1M rows, full 20yr window) took
~500ms in raw DB read alone, before the Python-side session-slot generation and set-diff
`detect_gaps()` also does per call. Previously only ~20 stalest symbols paid this nightly;
the fix now pays it for all 233 -- an ~11.65x multiplier on DB read + Python-side gap-diff
work, independent of the IBKR rate limiter the fix correctly targeted. Likely modest in
absolute terms (probably minutes, not hours, per the review's own estimate) but never
measured against a real nightly run at full scale.

**2. Todo 382's own fix-shape explicitly called for a step 5 ("Automate": a
`corpus_ohlcv_staleness_days{symbol}` point gauge + an `alert.lag.*`-style APR threshold, so
a repeat of this exact silent-success-while-stale bug class pages someone instead of waiting
for another manual audit) that the shipped fix did not implement. This is the mechanism that
would catch finding 1 above if it turns out to matter in practice.

## Fix shape (not investigated further)

1. **Measure first** (this project's own standing rule): let a few real nightly runs land at
   full 233-symbol scale, then check wall-clock duration and DB load (`pg_stat_activity`,
   `iostat -x 1` during the run) against the pre-fix baseline. If the added cost is genuinely
   negligible, close this without further code changes -- don't build a fix for an unconfirmed
   problem.
2. **If it matters**: a free staleness pre-filter in `_select_next_batch()`'s existing query
   (it already computes `latest.latest_bar` for every symbol via one `LEFT JOIN ... GROUP BY`)
   would exclude symbols already known current before they're ever handed to the delegate,
   without reintroducing a hard count cap (todo 382's actual bug). Getting the cutoff right
   needs care -- a naive `< 1 day` threshold would make every symbol look "stale" every Monday
   after a weekend gap and defeat the filter's purpose; account for the trading calendar,
   don't guess a number.
3. **Observability regardless of (1)'s outcome**: add the `corpus_ohlcv_staleness_days{symbol}`
   gauge + `alert.lag.*` APR threshold todo 382 originally specified, following the existing
   `_load_lag_thresholds()` pattern in `service_auditor.py`. This is cheap, general-purpose
   insurance against this whole bug class recurring silently, independent of whether finding 1
   turns out to matter.

## Where

- `scripts/infrastructure/backfill/infrastructure_nightly_backfill.py` -- `_select_next_batch()`
- `scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py` -- `detect_gaps()`
  (`_TF_FETCH_CONFIG`, lines ~346-378), `_reorder_contracts_by_gap()` (lines ~531-594, an
  existing batched-query pattern for "what does each symbol already have" that a future fix
  could reuse if (2) above is pursued -- out of scope for this todo to modify, it's the
  delegate script's shared fetch-stage loop, used well beyond the nightly wrapper)
- `services/service_auditor.py` -- `_load_lag_thresholds()`, the pattern to extend

## References

- [382](../completed/382-nightly-backfill-batch-size-conflates-check-cost-with-fetch-cost.md) --
  the P0 fix this is a follow-up to

## Triage 2026-09-26 (backlog review with the owner)

Re-tiered P2 -> P1: OHLCV freshness is the input to every book. Absorbed the live item from closed todo 298: an automated end-of-run completeness summary (the `n_tf` SQL exists, not wired in).
