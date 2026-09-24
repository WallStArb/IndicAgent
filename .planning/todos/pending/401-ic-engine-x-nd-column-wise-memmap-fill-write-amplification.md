---
status: pending
priority: P1
filed: 2026-09-24
source: Phase 176-08 corpus run, cross-sectional stage stall diagnosed live 2026-09-24 ~02:45 UTC
---

# ic_engine: column-wise fill of the row-major X_nd memmap causes terabyte-scale write amplification

## What

`_build_column_wise_x_nd` (`services/ic_engine.py`, Phase 174 Plan 09) builds a disk-backed
cross-sectional cell's non-degenerate feature slice one column at a time:

```python
X_nd_mm = np.memmap(..., mode="w+", shape=(n_raw, n_nd))   # C order, row-major
for out_idx, src_idx in enumerate(src_indices):
    X_nd_mm[:, out_idx] = X_raw[:, src_idx]
```

A row of X_nd is `n_nd * 4` bytes (~1.1 KB at ~260 features), so every 4 KB page holds a few rows,
and each single-column assignment dirties every page of the file and reads every page of X_raw.
Under the default kernel dirty-page limits (`vm.dirty_ratio=20`, `dirty_expire_centisecs=3000`) the
whole file is written back between column passes, so one cell's build writes roughly
`n_nd x size(X_nd)` bytes.

Measured on the 176-08 run (2026-09-24, equity/5m/high_bear, 9.4M rows, X_nd 9.5 GB): the main
process wrote 710 GB in 18 minutes at ~800 MB/s, sat in D state in `balance_dirty_pages`, with the
NVMe at 94-99% utilization and I/O pressure at 82%, and 5.9% CPU. This is very likely the real cause
of the previous full run's 11.5-hour cross-sectional stage (todo 385, leg C), not the fetch.

## Mitigation in place (operational, 176-08 only)

`sysctl -w vm.dirty_background_ratio=60 vm.dirty_ratio=80 vm.dirty_expire_centisecs=720000`, applied
2026-09-24 ~02:48 UTC, so X_nd's pages stay dirty in RAM across all column passes and are written
once. Runtime only, not persisted; revert to 10/20/3000 when 176-08 finishes. PostgreSQL durability
is unaffected (WAL and checkpoints fsync explicitly).

## Fix

Fill in contiguous row blocks instead:

```python
for r0 in range(0, n_raw, block_rows):
    r1 = min(r0 + block_rows, n_raw)
    X_nd_mm[r0:r1] = X_raw[r0:r1][:, src_indices]
```

Each page of X_nd is written once and X_raw is read once, sequentially. The transient is
`block_rows x n_nd x 4` bytes (for example 262,144 rows x 260 x 4 = ~270 MB), so `block_rows`
belongs in APR as an operational `infra.ic_engine.*` key. The copy is exact, so results are
identical. Regression test: blocked and column-wise builds produce byte-identical X_nd on a
synthetic disk-backed cell, including a non-contiguous `src_indices` mask.

Audit the same pattern elsewhere: any other column-wise assignment into a row-major memmap
(`Float32ChunkAccumulator` consumers, `_blocked_column_moments`, the streaming correlation pass).

## Gate

Edits `services/ic_engine.py` and moves `code_content_key`, so it lands with the next change that
forces a recompute (todo 389's post-176-08 landing, with todo 399), never mid-run.
