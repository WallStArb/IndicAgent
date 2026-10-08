

## Unified design note (2026-09-26)

`alpha_frame_writer.py`, cited here as the reference implementation, is deleted in phase 186. Checkpointing moves into the single bulk-load primitive (refactor map item 3), keyed by provenance batch records (design section 3.3); if `backfill_status` survives, it adopts that key instead of the anti-join pattern.

## Closed 2026-10-08

Moot: `backfill_status` is gone. Plan 189-08 removed the fetch path's `fetch_complete` writer, 185-41 moved promotion to bar_integrity verdicts, 185-42 removed the rebuild writer's checkpoint, and 185-43 removed the last writer and reader and dropped the table in migration 459 (78d4e90d7; dump in `data/backups/185-43/backfill_status.dump`). Fetch progress is the `ohlcv_coverage` ledger (189-01, 94b05a333).
