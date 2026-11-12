---
status: pending
priority: P0
filed: 2026-11-12
source: todo 600 step 6, 8a day-file-against-minute check (worker run 2026-11-12); design section 3
---

# Massive 1d is built from RTH minute rows, not the served day file

## Why

The 8a check found the served day file's close differs from the regular-hours minute aggregate on 27 percent (2003) to 68 percent (2026) of names, and its volume on far more; the day file's open, high and low match RTH (2010: 5 of about 59,000 opens differ), but close and volume include extended-hours trades. Design section 3 pre-decided this case: when close mismatches on more than 1 percent of names in any era (all 24 eras are over), 1d is built from the RTH minute rows under kind sip_flat_agg at 1d, and the served day file stays archived only.

## Scope

Build the 1d raw rows for the Massive span as the RTH aggregate of the same day's minute (or the loaded 5m) rows: open of the first RTH bar, max high, min low, close of the last RTH bar, summed volume; half days and early closes follow the NYSE grid. Raw 1d rows already loaded from the day file stay as raw (nothing a vendor served is dropped) under their own kind; the new rows carry the RTH kind. Policy and the daily rule select the RTH kind for Massive spans. Step 7 does not start until this is decided in the policy plan (todo 600 step 7 builds 1d in stage 1 and 2).

## Gates

Per-year raw load gate as for 5m (compare 0 real differences, canonical unchanged, row balance against the manifest); the RTH-built 1d agrees with the incumbent post-2016 1d on the return-based measure; the 8a price-agreement 1d arm uses the RTH-built 1d.

## Open

Whether to derive from loaded 5m raw (exact for OHLCV, no minute re-read) or re-aggregate the minute files; the lead leans to deriving from raw 5m, which keeps one source of truth and lineage.
