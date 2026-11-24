---
status: pending
priority: P2
filed: 2026-11-24
source: indicagent-3d, todo 471 measurement design (ruled by the lead 2026-11-24)
---

# ic_measure holds a whole tf in memory: it needs a time-chunk mode before any intraday tf runs

## What

`services/ic_measure.py` stacks every symbol chunk onto one union time grid and caches the dense float64 target stack of every horizon at once (`ic_measure.py:418`, `targets.py:143`), plus the feature block [n bars, m names, width]. At the stage 2 universe this is arithmetic, not a width choice (NYSE 2003-09-10 to oos_start: 5,609 sessions; 1h 39,110 bars, 15m 145,222, 5m 435,666; 5,192 names ever in the 5m tier, 12,857 at 1d): targets alone are 3.3 GB at 1h, 18 GB at 15m and 54 GB at 5m (three horizons); one dense 5m column is 18 GB, so no block width makes 5m fit on a 59 GiB host and 15m fits only at width 4 or less. Ruling: no 5m and no 15m in any `ic_tfs` until this lands; 1h only at width 4.

## Done when

A tf is held in time chunks (a year or a block of sessions with the warmup and the forward-horizon overlap each cross-sectional score needs), the targets are built and cached per chunk and one horizon at a time, and a unit's result is identical to the unchunked run on a tf that fits (bit-identical on 1d and 1h pilot rows, asserted in a test). Any horizon or window that spans a chunk edge is handled by overlap, never by dropping rows. Measured peak RSS at 15m on a 400-name sample is recorded before the scope-all pin.

Prerequisite of the scope-all pin; does not block the scope-1d pin. Related: 668 (checkpoint grain), 471 (width ruling).
