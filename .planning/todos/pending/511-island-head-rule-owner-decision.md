---
status: pending
priority: P2
filed: 2026-10-08
source: carried from todo 500 (closed by plan 185-43)
owner: Brandon (owner decision)
---

# ISLAND head rule: owner decision on `infra.ibkr.venue_fallback.island_failed_unlisted`

## What

The APR switch `infra.ibkr.venue_fallback.island_failed_unlisted` was set false on 2026-10-07 for
integrity. When on, it resolves 8 names whose SMART head fails by reading the ISLAND (Nasdaq)
route, but it can misread a former Nasdaq listing as empty history (QXO was SilverSun before its
rename). Off, those 8 names keep their failed head.

## Decision needed

Keep it off (integrity first; the 8 names keep a known gap), or turn it on with a guard that
checks the ISLAND answer against the name's listing history (`listing_venue`, D6) before trusting
an empty answer. Recommendation (plan 185-43): keep it off until 189-10's fetch has re-asked the
8 names under the new fetcher, then decide on the measured answers.

## Related

Todo 500 (closed), 185-34, `services/listing_venue_writer.py`, `src/providers/ibkr.py` venue
fallback.
