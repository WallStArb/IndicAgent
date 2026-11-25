---
status: pending
priority: P2
filed: 2026-11-24
source: indicagent-3d, todo 471 measurement design (ruled by the lead 2026-11-24)
---

# ic_measure holds a whole tf in memory: it needs a time-chunk mode before any intraday tf runs

## What

`services/ic_measure.py` stacks every symbol chunk onto one union time grid and caches the dense float64 target stack of every horizon at once (`ic_measure.py:418`, `targets.py:143`), plus the feature block [n bars, m names, width]. At the stage 2 universe this is arithmetic, not a width choice (NYSE 2003-09-10 to oos_start: 5,609 sessions; 1h 39,110 bars, 15m 145,222, 5m 435,666; 5,192 names ever in the 5m tier, 12,857 at 1d): targets alone are 3.3 GB at 1h, 18 GB at 15m and 54 GB at 5m (three horizons); one dense 5m column is 18 GB, so no block width makes 5m fit on a 59 GiB host and 15m fits only at width 4 or less. Ruling: no 5m and no 15m in any `ic_tfs` until this lands; 1h only at width 4.

## Design constraint found 2026-11-24 (read from `src/intelligence/measure/ic.py`)

The measure is a pooled rank IC over the (bar_ts, symbol) observation set with a circular block bootstrap on dense ranks (`pooled_rank_ic`, `dense_rank_inputs`), not a per-timestamp series. Time chunks therefore cannot simply be scored one at a time: the ranks are global to the pooled set. Exact equivalence needs the dense ranks computed over the whole set (an external-memory sort or a two-pass histogram per feature) with per-block sufficient statistics kept per chunk, or the statistic changes (a methodology-change entry, not a refactor). The strided observation set (`min_stride`, `n_independent`) is the first lever: measure the strided N per tf before any design. Lead ruling 2026-11-24: do not change the statistic; this stays an open design with two exact-equivalence options (a global dense-rank pass with per-block sufficient statistics, or a two-pass histogram per feature), and the strided-N measurement is the first lever; no methodology change without a ledger line from the lead. Unclear and to verify before building: the strided N at 15m and 5m and whether per-block sums reproduce the bootstrap bit-identically.

## Done when

A tf is held in time chunks (a year or a block of sessions with the warmup and the forward-horizon overlap each cross-sectional score needs), the targets are built and cached per chunk and one horizon at a time, and a unit's result is identical to the unchunked run on a tf that fits (bit-identical on 1d and 1h pilot rows, asserted in a test). Any horizon or window that spans a chunk edge is handled by overlap, never by dropping rows. Measured peak RSS at 15m on a 400-name sample is recorded before the scope-all pin.

Prerequisite of the scope-all pin; does not block the scope-1d pin. Related: 668 (checkpoint grain), 471 (width ruling).

## Design notes 2026-11-24 (indicagent-fb, from `src/intelligence/measure/ic.py`; no code edited)

The statistic touches far fewer rows than the dense stack holds. `pooled_rank_ic_prepared` takes rows `0, stride, 2 * stride ...` of the observation sequence (`complete[0::stride]`, stride first, then the finite mask), and ranks, the Spearman IC, the p-value and the circular block bootstrap read only those strided complete rows (`Xv`, `yv`). So an exact chunked run needs the strided rows, not the dense [bars, names] block. This keeps the statistic unchanged (the lead ruling) and replaces the external-memory sort and the histogram options.

Proposed mechanism, strided-row gather in two passes over time chunks:
1. Pass 1, per chunk (a block of sessions plus the forward-horizon overlap): build that chunk's targets for one horizon, and the family's `complete` bit per observation row (target finite and every feature finite; `prepare_features` makes it block-independent). Keep only the 1-bit mask and the running global observation count, so each chunk knows its global row offset and which of its rows fall on the global stride.
2. Pass 2, per chunk and feature block: read the feature block, take the chunk's rows that are strided and complete, and append them to a gathered `Xv` (strided rows by block width) and `yv`. Memory is the strided N times the block width, not bars times names times width.
3. Rank, IC, p-value and bootstrap run once on the gathered rows, exactly as today, so `ic`, `n_obs`, `n_independent`, `p_value` and the CI are identical, and `bootstrap=False` and the per-cell seeds are untouched.

Equivalence test: on a tf that fits (1d and 1h pilot rows), the chunked and unchunked cells are bit-identical, including with a chunk edge falling inside a horizon overlap. Two edge cases to test: the global stride phase across a chunk boundary, and a degenerate column whose standard deviation is judged over the whole observation set (it must be computed over the full set, so pass 1 also accumulates per-column count, sum and sum of squares, or pass 2 recomputes it from the gathered rows if the degenerate rule reads only strided rows; check which `prepare_features` does before building).

Measure first, before any code: the strided complete N per tf at the scope-1d pin (the `n_independent` of existing cells gives it for 1d; for 15m and 5m take it from the observation count over the stride). If strided N times width exceeds RAM at 5m, the gather itself must spill, and then the two exact-equivalence options in the ruling above come back; if not, this mechanism is enough. It does not touch `ic.py`, only `services/ic_measure.py` (context, target stack, feature fetch), which the corpus run does not import; confirm with `rebuild_code_key()` before and after.

## Strided N per tf, 2026-11-24 (indicagent-fb; read-only, arithmetic from stored counts)

The rebuilt `feature_vectors` is not loaded at the intraday tfs (about 357,000 rows in the table now), so the observation counts below are ceilings computed from the stage 2 membership, not row counts; the exact numbers come from the scope-all rebuild. Inputs: `universe_membership` before `alpha.validation.oos_start` (2025-12-24): 978,350 name-months over 11,970 names, of which 375,782 name-months over 4,775 names have `tier_5m`; 21.17 sessions per month (5,609 sessions over 265 months); bars per session from the NYSE grid sizes in todo 471 (1h 7.0, 15m 25.9, 5m 77.7). Assumed: every present name has a feature row at every bar of its months (an upper bound: untraded and warmup-masked bars drop out), and 1h, 15m and 5m use the `tier_5m` names. Stride is `max(alpha.ic.subsample_min_stride = 5, horizon)` (`targets.stride`), horizons from `alpha.ic_measure.horizons`.

| tf | observation rows | horizon | stride | strided N | y | X gather at width 16 | at width 4 |
|---|---|---|---|---|---|---|---|
| 1d | 20.7 M | 1, 2, 5 | 5 | 4.1 M | 0.03 GB | 0.5 GB | 0.1 GB |
| 1d | 20.7 M | 10 | 10 | 2.1 M | 0.02 GB | 0.3 GB | 0.1 GB |
| 1h | 55.5 M | 1, 2 | 5 | 11.1 M | 0.09 GB | 1.4 GB | 0.4 GB |
| 15m | 205.9 M | 2, 5 | 5 | 41.2 M | 0.33 GB | 5.3 GB | 1.3 GB |
| 15m | 205.9 M | 10 | 10 | 20.6 M | 0.16 GB | 2.6 GB | 0.7 GB |
| 5m | 617.8 M | 6 | 6 | 103.0 M | 0.82 GB | 13.2 GB | 3.3 GB |
| 5m | 617.8 M | 12 | 12 | 51.5 M | 0.41 GB | 6.6 GB | 1.6 GB |
| 5m | 617.8 M | 39 | 39 | 15.8 M | 0.13 GB | 2.0 GB | 0.5 GB |

Reading: the strided-row gather holds 8 bytes times N times the block width, against the dense 54 GB of targets at 5m. At width 4 every tf stays under 3.5 GB of gathered X plus 1 GB of y; 5m at horizon 6 at width 16 (13.2 GB) is the only cell that needs the width lowered. So the gather fits without spilling and the two exact-equivalence options of the ruling stay unused, unless the bootstrap's own working set (`block_bootstrap_ci` ranks the gathered matrix; its per-column arrays are a small multiple of N) pushes the 103 M row cell over the budget, which the 15m 400-name RSS measurement in Done-when covers. The per-chunk pass 1 mask is one byte per observation row: 618 MB at 5m, held per tf, or a bit mask of 77 MB.

Not measured: the true observation counts (needs the rebuilt intraday `feature_vectors`) and the bootstrap's peak RSS at N of 40 M and above. Both are the first two build tasks.
