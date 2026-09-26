

## Unified design note (2026-09-26)

`alpha_frame_writer.py`, cited here as the reference implementation, is deleted in phase 186. Checkpointing moves into the single bulk-load primitive (refactor map item 3), keyed by provenance batch records (design section 3.3); if `backfill_status` survives, it adopts that key instead of the anti-join pattern.
