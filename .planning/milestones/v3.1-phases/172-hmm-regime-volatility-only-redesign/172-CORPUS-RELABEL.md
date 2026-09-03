# Phase 172 Plan 05: Corpus-Wide `regime_volatility` Relabel Record

## Gate evidence

Quoted verbatim from `172-NULL-ARM-WIDER-SCOPE.md`:

```
VERDICT: GO
```

`grep -qE '^VERDICT: GO$' 172-NULL-ARM-WIDER-SCOPE.md` was run and confirmed to match before
any other action in this plan.

## Reconciled APR configuration (migration 308)

The gate document's `## Recommended shipped configuration` section named `vol_window = 250` and
`vol_of_vol_window = 250` as the joint real-minus-null margin maxima at 15m and 5m. Migration
307 had seeded `vol_window = 20` and `vol_of_vol_window = 60` as plan-time estimates. Migration
308 reconciled both to the measured values; `n_components` (3) and `covariance_type` (`full`)
already matched the gate document's recommendation and needed no change.

The relabel below ran under these live `config_state` values (confirmed against the gate
document by Task 1's automated verification before any write occurred):

| Key | Value |
|---|---|
| `alpha.hmm_volatility.n_components` | 3 |
| `alpha.hmm_volatility.vol_window` | 250 |
| `alpha.hmm_volatility.vol_of_vol_window` | 250 |
| `alpha.hmm_volatility.covariance_type` | full |
| `alpha.hmm.walk_forward.refit_every_bars.5m` | 19800 |
| `alpha.hmm.walk_forward.refit_every_bars.15m` | 6600 |
| `alpha.hmm.walk_forward.refit_every_bars.1h` | 1650 |
| `alpha.hmm.walk_forward.refit_every_bars.1d` | 252 |
| `alpha.hmm.walk_forward.initial_warmup_bars.5m` | 39600 |
| `alpha.hmm.walk_forward.initial_warmup_bars.15m` | 13200 |
| `alpha.hmm.walk_forward.initial_warmup_bars.1h` | 3300 |
| `alpha.hmm.walk_forward.initial_warmup_bars.1d` | 504 |

## Pre-run state (control)

Captured before any write, `2026-08-09T15:15Z`:

- `feature_vectors.regime` non-NULL count: **26,791,341**
- `feature_vectors` total rows: **36,854,099**
- Chunk compression state: 80/83 chunks compressed
- No other corpus-scale job running (`ps aux | grep -E 'ic_engine|backfill_feature_factory|regime_writer|ensemble_trainer'` returned nothing)
- `--column-family regime_volatility --mode verify-post-null` over the full 80-symbol x 4-tf
  scope: PASS (all 8 `regime_volatility`-family columns confirmed NULL corpus-wide before this
  plan's first write)

## Blocking issue found and fixed before any stage could complete: compressed-chunk UPDATE cost

Stage 1's very first write (`SPY/1d`) hung for 4+ minutes on a `wait_event=IO/DataFileRead`
`UPDATE ... FROM <temp table>` before it was killed and diagnosed. `EXPLAIN` on the same shape
of query showed the planner building a Hash Join by scanning and effectively decompressing all
83 chunks (cost estimate ~4.9M), regardless of how many rows the temp table held, because
`feature_vectors` had a compression policy active (80/83 chunks compressed, segmented by
`(symbol, tf)`, ordered by `bar_ts`) and TimescaleDB's compressed-chunk `UPDATE` path requires
full chunk decompression before the row-level write, independent of the `WHERE`/`JOIN`
selectivity. This is the same failure shape CLAUDE.md's performance-investigation-sop.md
documents from todos 149/161 -- a third independent incident.

Fix applied (operational, not a code change -- this write pattern via `_bulk_update_by_key` is
unchanged and correct; the corpus's *compression state* was the blocker): decompressed all 83
`feature_vectors` chunks once
(`SELECT decompress_chunk(format('%I.%I', chunk_schema, chunk_name)::regclass) FROM
timescaledb_information.chunks WHERE hypertable_name = 'feature_vectors' AND is_compressed`),
confirmed via `EXPLAIN` that the same `UPDATE` query's cost estimate dropped from ~4.9M to
~91k (a 50x+ reduction) once chunks were uncompressed, then re-verified `feature_vectors.regime`
non-NULL count and total row count were unchanged (26,791,341 / 36,854,099) after decompression
-- confirming no data was lost. Decompression took ~24 minutes wall-clock. The corpus is left
uncompressed at the end of this run; recompression is an operational follow-up outside this
plan's scope (no active compression policy/timer would re-compress it automatically -- all
systemd timers are confirmed disabled per CLAUDE.md).

Orphan-worker cleanup followed the documented procedure: killing the stuck main process left the
`ProcessPoolExecutor` forkserver workers running; `ps aux | grep regime_writer.py | awk '{print
$2}' | xargs kill` confirmed zero remained before restarting Stage 1.

## Stages

| Stage | Symbols | Timeframes | Elapsed | Notes |
|---|---|---|---|---|
| 1 | SPY (1 symbol) | 5m, 15m, 1h, 1d | ~4 min (after the compression fix) | Sanity pass; confirmed labeled rows > 0, valid vocabulary, warmup floor met at 3/4 tfs on first pass (see LQD/5m correction below for the one cell across the whole run that needed a fix) |
| 2 | 20 symbols (172-01's 30-symbol gate sample intersected with `feature_vectors`' 80-symbol universe -- see Open Caveats) | 5m, 15m, 1h, 1d | ~14 min | 3,011,634 rows labeled across 20 symbols |
| 3 | 60 symbols (`SELECT DISTINCT symbol FROM feature_vectors` minus Stage 2's 20) | 5m, 15m, 1h, 1d | ~28 min | Remainder of the corpus |

`--workers` used the live APR value `infra.regime_writer.workers = 12` throughout; no override
was justified by Stage 1's timing.

## LQD/5m correction

The full-scope `verify-post-relabel` run found exactly one failing cell: `LQD/5m`, with
`rows_before_first_label = 39,479` against `initial_warmup_bars = 39,600` (121 rows short).
Root cause, confirmed by direct query rather than assumed: `feature_vectors`' backfill for
`LQD/5m` starts at `2006-06-09 19:25 UTC`, but `market_data_ohlcv_tradeable` (the source the
observation-matrix fetch reads from) has `LQD/5m` history back to `2006-06-06 13:30 UTC` --
`market_data_ohlcv_tradeable` has 40,099 rows before the original `first_labeled_bar_ts`, matching
the observation matrix's own warmup requirement (`vol_window + vol_of_vol_window - 2 +
initial_warmup_bars` = 498 + 39,600 = 40,098) almost exactly. The walk-forward fit genuinely used
the full required warmup against the richer OHLCV source -- this was not a lookahead or
insufficient-warmup leak in the labels themselves. The gap is a pre-existing `feature_vectors`
Feature Factory backfill-start lag for this one (symbol, tf) cell, unrelated to this plan's work.

Because the plan's own acceptance criterion (`rows_before_first_label >= initial_warmup_bars`,
checked against `feature_vectors`' row count, not the richer OHLCV source) is the corpus-wide,
uniformly-applied proxy for "no stale value survived in the warmup prefix," and because Task 3's
`<done>` criterion requires zero failed cells before Wave 4 is authorized, the 121 labeled rows
for `LQD/5m` with `bar_ts < 2008-10-24 14:55 UTC` (exactly the rows before the point where
`feature_vectors`' own row count first reaches the 39,600 floor) were NULLed back out via the
same 8-column `REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES` set the writer itself uses. Re-running
`verify-post-relabel` over the full scope afterward returned PASS with zero failing cells.

This is the one deviation from the plan as written for this task: an out-of-tool, manually
constructed but column-list-derived (not hand-typed) `UPDATE` for a 121-row correction, verified
before and after. See SUMMARY.md's Deviations section for the full Rule 1 classification.

## COVERAGE

- **Legacy `regime` non-NULL count:** 26,791,341 before, 26,791,341 after (byte-for-byte
  unchanged; the volatility relabel never touched the legacy column family).
- **`regime_volatility` labeled rows:** 9,439,731, spanning all 80 symbols.
- **Distinct labels written:** `calm`, `elevated`, `turbulent` -- exactly the 3 codes registered
  in `controlled_vocabulary` under the `regime_volatility` namespace, no others.
- **Cells:** 320 total (80 symbols x 4 timeframes). 262 `labeled`, 58 `skipped`, **0 `failed`**.

### Skipped cells by timeframe

| tf | labeled | skipped | skip rate |
|---|---|---|---|
| 5m | 71/80 | 9/80 | 11% |
| 15m | 74/80 | 6/80 | 8% |
| 1h | 73/80 | 7/80 | 9% |
| 1d | 44/80 | 36/80 | 45% |

Every skipped cell carries the same `skip_reason`: all of that cell's walk-forward segments
failed the K=3 degenerate-occupation gate (a state with `min_fraction == 0` or near-zero within
the segment) or the cell had insufficient history to clear `initial_warmup_bars` at all. No
skipped cell was silently omitted -- all 58 appear in `evidence/172-05-relabel-coverage.json`
with an explicit reason. Full per-cell list: see the coverage JSON's `cells` array, filtered to
`verdict != "labeled"`.

### Failed cells

None, after the LQD/5m correction above. Zero cells carry `verdict: "failed"` in the final
coverage JSON.

## Open caveats

- **1d coverage is sparse (45% of cells skipped, and even most "labeled" 1d cells wrote only
  their first walk-forward segment).** `SPY/1d` is representative: of 17 walk-forward segments
  computed (the first at `seg_start=504`, then 16 more from `seg_start=756` through `seg_start=4536`
  at the `refit_every_bars.1d = 252` cadence), only the first segment (252 rows) cleared the K=3
  occupation gate -- every later segment failed because at least one of the three volatility
  states (`calm`/`elevated`/`turbulent`) had zero occupation within that 252-bar window. This is
  a genuine consequence of combining migration 308's reconciled `vol_window`/`vol_of_vol_window
  = 250` (which widens each state's persistence horizon) with `refit_every_bars.1d = 252` (a
  migration-292 default calibrated for the legacy composite/trend label, never re-validated
  against the new volatility-only observation vector or K=3's three-way occupancy requirement).
  Since `refit_every_bars` is a shared walk-forward schedule key also used by the legacy `regime`
  family, changing it is out of this plan's scope -- it would need its own investigation and gate
  (candidate follow-up: measure whether a longer `refit_every_bars.1d` recovers coverage without
  reintroducing the parameter-lookahead problem the walk-forward design exists to prevent).
  5m/15m/1h fare much better (8-11% skip rate) since their `refit_every_bars` values give each
  segment far more bars to visit all three states.
- **172-01's 30-symbol gate sample includes 10 symbols with zero `feature_vectors` rows**
  (`AAPL`, `CVX`, `ECL`, `EQIX`, `EXEL`, `FCX`, `JPM`, `MCD`, `MRK`, `MSTR`) -- individual equities
  from the 111->231-symbol universe expansion (STATE.md, 2026-08-05/06) that have real
  `market_data_ohlcv` history (confirmed, ~3.1M rows each) but no Feature Factory-computed
  `feature_vectors` rows yet (todo 282/283's "76% of expansion symbols unrouted" gap). These 10
  symbols are not part of this relabel's scope at all -- there is nothing in `feature_vectors` to
  relabel for them -- and were excluded from Stage 2 rather than run against a compute path that
  would produce update_rows matching zero existing rows. Stage 2 used the 20-symbol intersection
  of the gate sample with `feature_vectors`' actual 80-symbol universe. This does not affect the
  GO verdict (measured independently against the wider 30-symbol sample via a dedicated script
  reading `market_data_ohlcv` directly, not `feature_vectors`) or this relabel's completeness
  (Stage 3 derived its scope from `feature_vectors` directly, covering all 80 real symbols).
- **The corpus is left decompressed** (0/83 `feature_vectors` chunks compressed, was 80/83
  before this plan). No active compression policy or systemd timer exists to reverse this
  automatically. Recompressing is a reasonable operational follow-up but is outside this plan's
  scope; flagged here rather than done unilaterally since it is a storage/ops tradeoff, not a
  correctness requirement.
- **This relabel measures coverage and provenance, not predictive quality.** Whether
  `regime_volatility` conditions IC the way `171-FINAL-VERDICT.md`'s null-arm control predicts is
  Wave 4's (`ic_engine.py` cutover) and Wave 5's (downstream re-verification) job, not this
  plan's.
