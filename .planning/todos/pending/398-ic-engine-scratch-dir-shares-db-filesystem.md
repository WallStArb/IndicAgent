---
status: pending
priority: P2
filed: 2026-09-23
source: Phase 174 code review WR-05 and the /simplify altitude review of its fix
---

# ic_engine's memmap scratch directory shares a filesystem with the TimescaleDB volume

## What

`infra.ic_engine.memmap_scratch_dir` is `/var/tmp/ic_engine_scratch`, on `/`, the same
logical volume as the TimescaleDB data volume. A disk-backed cross-sectional cell writes up
to about 2.2x its float32 footprint there (X_raw plus X_nd), and memmap files are sparse, so
the space is consumed as rows land, while the database keeps writing WAL and results. That
is the shape of the 2026-08-13 disk-full incident.

The fix branch added a reserve (`infra.ic_engine.scratch_min_free_after_fraction`, 0.15 of
the filesystem must stay free after the cell's files are written; migration 352). That makes
the check safe but works around the shared filesystem instead of removing it.

## Fix

Put `memmap_scratch_dir` on storage that does not hold the database (a separate LV or
disk), and document why in the APR key's description. Keep the reserve as a second guard.
This is an infrastructure decision (which device, how large), not a code change.

## Gate

None. Worth doing before cells approach the `alpha.ic.max_cell_rows` cap (restored to 15M
by todo 386), where a single cell's scratch is tens of GB.
