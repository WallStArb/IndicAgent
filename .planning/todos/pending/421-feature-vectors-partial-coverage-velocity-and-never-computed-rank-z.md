---
status: pending
priority: P1
filed: 2026-09-24
source: per-feature coverage scan of feature_vectors at the 2025-12-24 window (Phase 179 pre-freeze check)
---

# feature_vectors: 6 velocity features cover 10/233 symbols; 3 rank_z features were never computed

## What

Scan (count of non-null values per symbol, per column, bar_ts <= 2025-12-24 05:15 UTC):

- `rsi_velocity_fast/mid/slow`, `ofi_z_velocity`, `cvd_slope_z_velocity`, `volume_z_velocity`:
  populated for 10 of 233 symbols (BIL, EMLC, ENPH, GLD, IHF, NAD, SHY, STIP, VIXY, VRP) at every
  tf (1d 32,117 of 930,977 rows; 5m 2.55M of 72.4M). Added 2026-08-15 (3706c21ea, todo 320); only
  those symbols were recomputed afterwards, and `backfill_feature_factory` default mode skips
  `complete` pairs, so the rest stayed NULL. Every IC row for these features is measured on that
  non-random subset. None is weighted in the champion today; 179 excludes them (pre-reg 12.1).
- `momentum_rank_z`, `volume_rank_z`, `volatility_rank_z`: `feature_factory` hard-codes None at
  every tf (lines ~6727, ~8728); they are active concept_registry features that have never had a
  value.

Nothing detects this class: no check compares a feature's populated-symbol count with the
universe, so a new column can sit at 4% coverage for weeks while its IC looks like any other.

## What to do

1. Populate the velocity columns for every symbol: a `--refresh` compute (with 411's catch-up;
   `backfill_feature_factory` has no `--tf` flag yet, so add one to refresh 1d alone cheaply).
   Run it BEFORE the next ic_engine recompute, not after: the feature_vectors watermark is
   MAX/COUNT only, so an in-place refresh after the fingerprints are stamped would not invalidate
   the cells (todo 412 update).
2. rank_z: implement (a cross-sectional rank needs the whole universe per bar, so it belongs in a
   post-compute pass, not the per-symbol factory) or deprecate the three concepts.
3. Add a coverage integrity check (per active feature, per tf: populated symbols / universe,
   APR threshold, integrity_monitor fact) and have ic_engine refuse, or flag, cells for a
   feature below it.
