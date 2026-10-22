---
status: pending
priority: P2
filed: 2026-10-09
source: 189-10 Task 2 pilot review (185 session, 2026-10-09): a read-only archive query appeared to show a bar dated in the future; not reproducible, zero future-dated rows live in the archive or canonical
---

# Guard: no ingested bar may be dated in the future

## What

During the 5m pilot a query appeared to return a CSCO archive bar dated about 36 hours ahead; a recheck found zero rows with `timestamp > now()` in `ohlcv_intraday_raw_archive` or `market_data_ohlcv`, so the reading was most likely a misread of the MM-DD grouping. But nothing in the ingest path would have caught it. IBKR does serve the forming (in-progress) bar for the current slot, and any clock or vendor-label defect that yields a future-dated bar would flow silently into the archive and from there into canonical bars and features: a silent wrong answer.

## Fix

One cheap guard at the ingest boundary, written once: a row whose bar timestamp is later than the fetch wall clock plus a small APR tolerance (seed `infra.backfill.future_bar_tolerance_s`, [initial_estimate], a few minutes to allow clock skew) is refused at observation/archive write time (logged, counted, listed in the run summary), never stored. Plus one D7 1d check condition (or an extension of an existing check) counting any stored canonical bar dated in the future: 0 is the pass line. Tests: a future bar is refused and counted; a bar within tolerance passes; the D7 condition fails on a planted future row (in a temp table).

## Done when

The guard is in the writer path with tests; the D7 condition exists and is green on live data; the refusal counter appears in the run summary.

## Status 2026-10-22 (phase 191 plan 18)

Delivered by plan 191-02: the one raw writer `services/ohlcv_raw_writer.py` refuses a bar
dated past the fetch wall clock plus the APR tolerance (`threshold.bar_integrity.future_bar_tolerance_s`),
with tests. Still open, and explicitly deferred as D-191-H (design doc section "D-191-H:
explicit deferrals"; planner decision, owner acknowledgement pending): the D7 1d condition
counting stored canonical bars dated in the future. The todo stays open for that remainder
only.
