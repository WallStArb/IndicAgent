---
status: pending
priority: P1
filed: 2026-10-27
source: found while closing todo 390 in the todo 553 change (Amihud zero-close guard)
---

# `amihud_illiq_z` is 0 on almost every row: raw illiq sits below the z-score's absolute std floor

## What

`_amihud_illiq_z_series_full` (`src/intelligence/features/kernels/volume.py`) z-scores the raw
Amihud value |ln(C[t] / C[t-1])| / (C[t] * V[t]) with `_fixed_window_zscore_series`, which returns
0.0 wherever the window std is below `STD_FLOOR = 1e-8` (`kernels/_primitives.py`). For a liquid
name the raw value is about 0.01 / 1e8 = 1e-10 and its std is of the same order, so the floor
zeroes the z-score on nearly every row.

Measured 2026-10-27 on the stored `feature_vectors` table: SPY and AAPL, 1d and 5m since
2025-06-01, `amihud_illiq_z = 0` on 100% of rows; 1d since 2026-01-01, 5 of 233 names have any
non-zero value and 1.5% of rows are non-zero. `illiquidity_momentum_product` (= `amihud_illiq_z`
times `momentum_z_fast`) is therefore 0 as well. A feature that is a constant is a silent wrong
answer: it looks computed and carries no information.

## Fix (to decide)

The z-score has to see a scale-free quantity. Candidates: z-score `ln(illiq)` (Amihud values are
log-normal-like across names and time, and the log removes the price-times-volume scale), or a
relative std floor. The first also changes the statistic's distribution, so it is a definition
change, recorded as such. Either way the parity goldens for `amihud_illiq_z` and
`illiquidity_momentum_product` regenerate with the reason recorded.

## Why now

Same window as todo 553: `kernels/` is in the 186-26 rebuild's fingerprinted import closure, so a
fix after the launch needs a follow-up rebuild of these two columns. The sequencing call belongs
with indicagent-3a (186-26 launch owner). Not fixed in the 553 change because it is a definition
change outside 390's scope (390 only guarded the zero-close divisor).

## Sequencing decision (indicagent-3a, 186-26 launch owner, 2026-10-28)

Lands before the 186-26 launch, under the same conditions as todo 553: reviewed, merged before
191-23's summary, and indicagent-3a told when merged. Owner of the change: indicagent-24.

The spec states the new definition's scale handling. 1d volume has a basis seam at 2016: from
2016 Alpaca consolidated volume (IBKR-served sessions carry NULL volume); before 2016 IBKR SMART
volume, about 0.41-0.91x of consolidated. A within-name z-score across the seam picks up a level
shift unless it is computed within each era or the feature is defined on a ratio that cancels the
basis. The spec says which, and why it holds across the seam.
