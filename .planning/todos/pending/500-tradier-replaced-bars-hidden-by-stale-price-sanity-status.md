---
status: pending
priority: P2
filed: 2026-10-07
source: 185-34 D-28 gate, condition 1
---
# Ten clean Tradier bars are hidden from research by a stale price_sanity_status

## What

`market_data_ohlcv_tradeable` still filters on the legacy `price_sanity_status` column. The Tradier load replaced 12 legacy-flagged IBKR bars but left the status on the stored row, so 10 clean bars are invisible to research: DBC, FXI, FXY, GLD, IWM, RSP, SPY, VWO (two dates) and XRT 2007-09-18. D-28 condition 1 counts them as replaced and lists them.

## Fix

Clear the status on the replaced rows through the one canonical writer (185-36's daily writer or the 185-33 verdict work), not by hand, and retire the column filter when `bar_quality_flag` is the only source of truth (185-43). Check with the D-28 evidence line.

## Related

185-34, 185-36, 185-43. Owner decision also pending on the ISLAND head rule (APR `infra.ibkr.venue_fallback.island_failed_unlisted`, set false 2026-10-07 for integrity: it resolves 8 names but can misread a former Nasdaq listing as empty; QXO was SilverSun).
