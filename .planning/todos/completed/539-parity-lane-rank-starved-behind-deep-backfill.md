---
status: closed
priority: P2
filed: 2026-10-18
closed: 2026-10-22
source: plan 191-17 execution, rider finding (plan 16 review P3-6) (2026-10-18); closed on DB evidence verified by the 191-17 review (P2-1)
owner: 2026-10-18
---

# Weekly parity lane rank starvation behind the deep 5m backfill (premise corrected, closed)

## What actually happened (DB-verified 2026-10-22)

The premise this todo was filed on (the weekly draw is "eligible and queued but never
executes while deep 5m backfill work exists"; the original text is in git history) is false.
The week-42 draw executed end to end on 2026-10-18, the same day as the measured starvation:

- All nine week-42 names (EPD, FXC, ARRY, FSLR, GEV, PM, RSG, THRM, BMY) were fetched and
  applied: `ohlcv_request` 19 rows (15m and 1h per name plus one PM 15m retry),
  `requested_at` 2026-10-18 19:49:35Z to 19:52:36Z, source ibkr, outcome bars.
- `ohlcv_load`: the same 19 rows, destination raw, caller ibkr-history-fetch, outcome
  applied, parity-sized windows (up to 416 15m bars and 112 1h bars), not deep-backfill
  volumes. The ARRY 15m load raised a restatement flag ("changed 35 / stored 126", share
  signature), the detector working as designed.
- With plan 16's explicit URA run (2026-10-17 06:14Z) that is exactly the 21 raw-destination
  15m/1h loads since 2026-10-16.

The rank starvation was real but transient: at the 2026-10-18T07:45Z dry run the nine names
sat at queue positions 177-194 of 3025 with the 06:00Z run budget exhausted by
backfill/gap_fill items; the fetcher worked the queue down and served the parity lane about
12 hours later, same day. The D7 grid_parity 1683/3058 figure was measured at 06:12Z, before
the draw executed, so it was correct at measurement time; nothing in the plan 17 gate chain
or the drop decision is affected.

## Resolution

Closed 2026-10-22: the weekly vendor-basis cadence does not silently stop, so the filed fix
direction (per-run item floor or priority ranking, chosen by a weeks-to-execution estimate)
followed from the false premise and is withdrawn; no queue-ranking change is owed on this
evidence. The 191-17-SUMMARY rider answer is corrected by dated addendum. The structural
observation survives in weaker form: an unbounded lane can delay a weekly lane by many
hours. Re-file with measured delay data only if that delay ever becomes material against the
parity hold semantics (coverage head >= ISO week start), which stay unchanged.
