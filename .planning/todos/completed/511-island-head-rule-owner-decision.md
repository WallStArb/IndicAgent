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

## Owner decision 2026-10-08 (relayed by the research-ledger session indicagent-6a; confirm in the 185 session before acting on live data)

Todo 511 decision: keep the ISLAND switch off. Re-ask the 8 names under the new fetcher in Task 1b, then decide on the measured answers (guard against listing_venue, D6, only if needed).

## Decision (owner, 2026-10-10)

Keep it OFF. `infra.ibkr.venue_fallback.island_failed_unlisted` stays false; the 8 names keep
their known SMART head gap. Integrity first, per owner one-line ruling. Revisit only if a named
consumer needs one of the 8 and the listing-history guard is built first.
