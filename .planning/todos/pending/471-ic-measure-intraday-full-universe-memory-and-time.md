---
status: pending
priority: P2
filed: 2026-09-30
source: plan 186-14 pass 2, real 15m dry run
---

# The fresh IC writer's intraday memory and time at the full universe are unmeasured and do not fit as configured

## What

After the kernel (todo 469), `services/ic_measure.py --tf 15m --dry-run` on 40 compute_eligible
symbols (4,170,077 feature_vectors rows, 2006 to 2026) takes 17:04 and peaks at 6.9 GB
(proposer unit 11:37, regime_volatility unit +5:25). The full compute_eligible universe is about 23
times that many rows, so at the configured block width (`alpha.ic.feature_block_columns` 32) the
memory extrapolates to well above the host's 29 GB (the block grid alone is bars x symbols x 32 x 8
bytes, about 31 GB for 131,000 bars x 931 symbols) and the time to hours of kernel time at 12
threads plus three serial fetch passes over the family. 5m has more rows still. 1d is fine: all 925
names in 7:12 at 4.0 GB peak.

## Why it matters

186-28 decides the timeframe set. If any intraday tf is in it, the run as configured can be
killed by the OOM killer, and a kill loses the unit.

## What to do

Measure 15m at a few symbol counts (40, 150, 400) with `alpha.ic.feature_block_columns` at 4 and 8
and record peak RSS and wall clock per pass, then set the operational block width (and thread
count) for the tf, or chunk the fetch by symbol range if the union grid itself does not fit. The
block width is operational (bit-identical for any width, asserted in tests), so the choice needs
no recompute of anything stored. Decide before 186-28 names its tf set.
