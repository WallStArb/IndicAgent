---
status: pending
priority: P2
filed: 2026-09-30
source: plan 186-14 pass 2, real 15m dry run
---

# ic_measure block width, threads and which tfs a corpus run may measure

## What

`alpha.ic.feature_block_columns` is one key for every tf, pinned in the run's APR hash; results are bit-identical at any width. At the stage 2 universe the memory is arithmetic (sizes in todo 667): 1d fits at any width, 1h at width 4 to 8, 15m only at width 4 or less, 5m at no width (the dense targets of three horizons are 54 GB).

## Ruling (lead, 2026-11-24)

1. Scope-1d pin: `alpha.ic.feature_block_columns` = 16 and `ic_tfs` = 1d only (block 9.2 GB, targets 2.3 GB, long form about 3 GB on 59 GiB).
2. No 5m and no 15m in any `ic_tfs` until the measure holds a tf in time chunks (todo 667). 1h is allowed at width 4 only if wanted. The scope-all pin is decided later with measured numbers.
3. Prerequisites of the scope-all pin, neither blocking the scope-1d pin: 667 (time-chunk mode) and 668 (checkpoint grain, todo 470 merged).

## Done when

After the block 2 rerun has finished and no heavy job is live: `ic_measure --tf 1d --dry-run --symbols <the 25 pilot names>` at widths 4, 8, 16 and 32 with peak RSS sampled, recorded here with bytes per grid cell and the digest-pass share; the NYSE-calendar grid sizes (computed 2026-11-24: 5,609 sessions from 2003-09-10 to oos_start; 1d 5,609 bars, 1h 39,110, 15m 145,222, 5m 435,666) are in todo 667. Then close this todo with the pinned width written into the scope-1d run's APR.
