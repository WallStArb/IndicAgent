---
status: pending
priority: P2
filed: 2026-08-08
source: found while writing docs/foundation/instrument-data-model.md -- checked
  instrument_metadata coverage for the 151 symbols added in the 2026-08-05/06
  universe expansion.
---

# `instrument_metadata` has 0% coverage for the 151 symbols added in the 2026-08-05/06 universe expansion

## What

`instrument_metadata` (listing_date, underlying_index, issuer, description) has 61 rows
total, all sharing the exact same `created_at` timestamp (2026-06-20 15:49:44.617726+00) --
a single bulk seed at Phase A's original 58-ETF launch. Verified live:

```sql
SELECT count(*) FILTER (WHERE m.symbol IS NOT NULL), count(*)
FROM instruments i LEFT JOIN instrument_metadata m ON m.symbol = i.symbol
WHERE i.created_at >= '2026-08-05';
-- 0 | 151
```

Zero of the 151 symbols added in the 111->231 universe expansion have a metadata row. Nothing
has written to this table since the original seed -- it did not silently degrade, it was never
wired into the "add an instrument" workflow at all.

## Why it matters

Low urgency by itself -- no live compute path was found reading `instrument_metadata`
(`grep`-confirmed: only referenced in `docs/foundation/instrument-tag-registry.md`'s table
listing and this new doc). It's descriptive/enrichment data, not a measurement input. Filed
because it's a clean, cheap gap now that it's visible, not because anything is broken by its
absence today.

## What to do

1. Confirm no consumer reads `instrument_metadata` before treating this as pure hygiene (a
   fresh `grep -rn instrument_metadata src/ services/` closer to execution time, in case that
   changes).
2. Backfill `listing_date`/`underlying_index`/`issuer`/`description` for the 151 new symbols --
   same manual/scripted process used for the original 58-ETF seed (not yet identified which
   script/process that was; check git history around 2026-06-20 for the seeding migration/script).
3. Consider whether "add an instrument" should write a stub `instrument_metadata` row going
   forward, so this doesn't recur on the next universe expansion.
