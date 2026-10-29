---
status: completed
priority: P1
filed: 2026-10-27
completed: 2026-10-28
source: found while closing todo 390 in the todo 553 change
---

# `amihud_illiq_z` was 0 on almost every row

Raw Amihud illiquidity, |ln(C[t]/C[t-1])| / (C[t] V[t]), is about 1e-10 on a liquid name, below the
z-score's absolute std floor (`STD_FLOOR = 1e-8`), so the z-score was 0.0 on 100% of SPY and AAPL
rows and on all but 5 of 233 names on 1d in 2026. `illiquidity_momentum_product` was 0 with it.

## Definition now

- `amihud_illiq_z` is the z-score of ln(illiq) over the last `feature.amihud.zscore_window` bars of
  one volume basis. The log removes the price-times-volume scale.
- The window restarts where `volume_basis` changes. A row is NaN until the segment holds
  ceil(`feature.amihud.min_valid_fraction` x window) valid observations (0.8, migration 534).
- A NULL-volume bar, a zero return or a non-positive close is a missing observation, never a fill.
- `illiquidity_momentum_product` reads the new z, so it is NaN where the z is. Cold-start rows are
  NaN (they were 0.0).

## Volume basis

`volume_basis` is a bar field: an integer per bar (none 0, consolidated 1, smart 2, mixed 3) from
the one (vendor, kind) table in `bars/vendor_kind.py`. An unmapped pair raises. A derived grid bar
takes its basis from its 5m constituents. Both rebuild loaders carry it and map NULL volume to
NaN (a NULL used to crash them on `float(None)`). IBKR SMART volume is 0.75 of Alpaca consolidated
at the median across 69 overlap names (p5 0.61, p95 0.95). `kernel_source` refuses a kernel that
needs the basis unless the caller supplies it, because the research panel carries no vendor
provenance and a constant would hide the seam.

## Measured (2026-10-28, stored bars, no writes)

- Non-zero share, 10 liquid names since 2025-06-01: before 0.0 on 9 of 10 on 1d (PG 0.29) and on
  all 10 on 5m. After, every finite row is non-zero; 0.38 of 1d rows are finite (the 252-bar window
  needs about 202 valid bars) and 0.93 to 0.99 of 5m rows.
- Seam, 63 names: mean z in the 59 rows after the seam is -0.125 when the window spans it
  (sd over names 0.42). With the reset those rows are NaN, and the next 50 average -0.132 (sd
  0.28). The reset removes a per-name bias; the average shift is small.

## Goldens

`tests/fixtures/kernel_parity/` (`real_golden.json`, `real_golden_sample.npz`,
`synthetic_golden.npz`) recomputed from the stored inputs. In all 17 cases only `amihud_illiq_z`
and `illiquidity_momentum_product` moved. The other volume kernels are todo 560.
