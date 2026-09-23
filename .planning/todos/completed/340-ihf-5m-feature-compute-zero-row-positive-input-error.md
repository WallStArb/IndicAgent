# 340 - Feature-compute backfill stalled for 8 symbols across 12 symbol/tf cells, multi-year gaps for 7 of them -- 2026-08-21 dismissal of 11/12 as "not real gaps" was wrong

**Filed:** 2026-08-21
**Source:** Split out of todos 259/296's closure -- found while verifying `backfill_status`
against actual `feature_vectors` row counts for the 2026-08-05/06 universe expansion.
**Corrected 2026-09-18** (manual corpus audit, cross-checked against live OHLCV/feature_vectors
row counts and `backfill_status` -- see table below): 11 of the 12 cells this todo originally
dismissed as "stale checkpoint desync, not real gaps" are, in fact, real, severe, multi-year
partial backfills that silently stopped. The original check only confirmed `feature_vectors`
had *some* rows for each symbol/tf -- it never compared that row count or max timestamp against
the actual OHLCV coverage, so a backfill that completed 40% of a symbol's history and then
crashed looked identical to a stale-but-complete checkpoint.

## What

12 `backfill_status` rows at the 4 real target timeframes (5m/15m/1h/1d) are `status='failed'`,
spanning 8 distinct symbols. Verified live against `market_data_ohlcv_tradeable` (what OHLCV
actually exists) and `feature_vectors` (what got computed):

| symbol | tf(s) failed | OHLCV bars (5m) | feature rows (5m) | feature history stops | gap |
|---|---|---|---|---|---|
| BIL | 5m, 15m, 1h, 1d | 330,954 | 165,500 | 2018-03-07 | ~8.5 yrs |
| VRP | 5m, 15m | 210,856 | 16,000 | 2015-11-20 | ~10.8 yrs |
| ENPH | 5m | 275,538 | 85,000 | 2016-11-28 | ~9.8 yrs |
| GLD | 5m | 395,996 | 295,500 | 2021-07-23 | ~5 yrs |
| NAD | 5m | 294,876 | 141,500 | 2018-04-05 | ~8.4 yrs |
| SHY | 5m | 177,958 | 7,500 | 2017-12-26 | ~8.7 yrs |
| STIP | 5m | 213,666 | 87,500 | 2020-01-09 | ~6.6 yrs |
| **IHF** | 5m | 224,881 | **0** | (never started) | full history |

The first 7 (11 of the 12 failed cells) all share `error_msg='value out of range: underflow'`.
**`IHF`/`5m` is the one cell with a genuinely different signature** -- zero rows at all (not a
partial/stalled backfill) and a distinct error, `"expected a positive input, got 0.0"`. `IHF`
has full data at `15m`/`1h`/`1d` -- only `5m` never started.

**Likely shared root cause for the 7 underflow cells:** a `real`-column write overflow, not a
compute crash on the first bar -- each of these got 40-90% of its history computed and written
before failing, consistent with a specific *value*, not a structural bug, tripping a range
check partway through. Matches the CLAUDE.md gotcha on `real`-column float32-range clamping
(`_clamp_to_real_range` in `_batch_utils.py`) -- plausible trigger: a near-zero-variance
instrument (BIL is a T-bill ETF, near-zero-volatility by construction; also flagged in todos
341/362 for a related degenerate-HMM-fit failure) producing an extreme z-score or log-return
value on a specific historical bar that overflows a `real` column on write, killing the whole
symbol/tf backfill run at that point. `IHF`'s distinct `"positive input"` error suggests a
separate root cause (a literal-zero `log()`/division input), not the same bug.

## Fix shape (not investigated yet)

**For the 7 underflow cells (BIL/VRP/ENPH/GLD/NAD/SHY/STIP):**
1. Re-run `backfill_feature_factory.py --compute-only --symbols <symbol> --workers 1` for one
   of these (BIL is the best first target -- already flagged for a related near-zero-variance
   failure mode in todos 341/362, so a shared root cause is directly testable) to get a clean
   traceback and find the exact bar/feature that overflows on write.
2. Confirm whether the write hits `bulk_update_by_key`'s `real`-column clamp path or fails
   further upstream (a numpy/pandas overflow before the DB write is even attempted).
3. Decide handling per the Renaissance data-retention principle (never drop data that could
   contain signal): clamp/epsilon-floor the specific feature calculation for degenerate-variance
   instruments vs. widen the column type vs. skip-and-log the specific bar -- don't silently
   truncate the backfill again.
4. Once fixed, re-run backfill for all 7 -- this is potentially 5-11 years of 5m feature history
   per symbol, a real gap in the corpus `ic_engine` trains against for these names.

**For IHF (distinct root cause, smaller blast radius -- single symbol/tf, zero rows):**
1. Find the specific bar(s) triggering this -- re-run `backfill_feature_factory.py --compute-only
   --symbols IHF` (with `--workers 1` for a clean traceback) or query `market_data_ohlcv_tradeable`
   directly for IHF/5m bars with `volume=0` or `close<=0`/`open<=0` around the failure window.
2. Locate the exact feature computation with an unguarded `log()`/division call that assumes a
   strictly-positive input (candidates: any volatility-ratio, log-return, or Wilder-RSI-style
   calc -- grep `math.log(` / `np.log(` in `src/intelligence/feature_factory.py` and
   `feature_cache.py` for calls not already guarded against zero).
3. Decide the correct handling -- skip that one bar (matches "never drop data that could contain
   signal" only if the bar itself is a genuine synthetic/flat-carry placeholder that
   `market_data_ohlcv_tradeable`'s `volume > 0` filter should have already excluded; if it slipped
   through that filter, the bug may be upstream of Feature Factory entirely) vs. guard the
   specific calculation with an epsilon floor.

**Before running any of the above:** the ic_engine full-corpus run this was blocked on finished
2026-09-22 (see completed/378) -- unblocked now. **New constraint found the hard way 2026-09-22:
`backfill_feature_factory.py --compute-only` against `feature_vectors` decompresses the ENTIRE
hypertable regardless of `--symbols` scope** (see `docs/reference/gotchas.md`'s
`compressed_hypertable_write_session` entry) -- never run it concurrently with anything else
reading/writing `feature_vectors`/`feature_ic_scores`; a single-symbol IHF run took an
`AccessExclusiveLock` on ~40 chunks and stalled a concurrent `ensemble_trainer.py` for ~10 min.

## STATUS: FULLY CLOSED 2026-09-22 -- both halves resolved and live-confirmed

## IHF root cause: RESOLVED 2026-09-22 (code fix + regression tests landed, live corpus
confirmed -- `backfill_status` IHF/5m `status='complete'`, `rows_written=226711`)

`_canary_acausal_placebo` (`src/intelligence/feature_factory.py:1950` -- a deliberate look-ahead-
leak positive-control canary, not a real trading feature) guarded `closes[i + 1] <= eps` (the
denominator) but never checked `closes[i + 2]` (the numerator). IHF/5m has exactly one bar with
`close <= 0` in both the raw table and `market_data_ohlcv_tradeable`: `2010-05-06 18:50:00 UTC`
(the Flash Crash), `open=8.03, high=8.03, low=0, close=0, volume=2000` -- a genuine historical
print (real volume), not a synthetic placeholder, so per this project's data-retention principle
the fix guards the *compute*, not the corpus. When that bar lands on `closes[i + 2]`, the ratio
evaluates to `0.0` and `math.log(0.0)` raises exactly `"expected a positive input, got 0.0"`.
This is a general-purpose bug (any symbol/tf with a near-zero print two bars after a normal bar
would trip it), not IHF-specific -- IHF/5m is just the corpus's only currently-known instance.

Fix: widened the guard to `closes[i + 2] <= eps` as well (one-line change, matches the function's
own existing 0.0-fallback semantics). Two new regression tests added to
`tests/unit/test_canary_predictors.py` (numerator-degenerate and numerator-negative cases,
confirmed RED pre-fix / GREEN post-fix using the real IHF bar's shape). Full
`test_canary_predictors.py` (43 tests) and `test_feature_factory.py` (88 tests, incl. an
AST-pattern check on this exact function) green; `ruff`/`black` clean. Full debug record:
`.planning/debug/resolved/ihf-5m-positive-input-error.md`.

**Live end-to-end confirmation, 2026-09-22: CONFIRMED.** Once the diagnostic process (PID
118400) exited, re-ran `backfill_feature_factory.py --compute-only --symbols IHF --workers 1`
fresh (PID 234712) -- `backfill_status` for `symbol='IHF', tf='5m'` now shows
`status='complete', rows_written=226711`. **IHF half of this todo is fully closed.**

## 7-symbol underflow root cause: RESOLVED 2026-09-22 (code fix + regression tests landed,
live corpus confirmed across all 28 symbol/tf cells)

Root cause: `feature_vector_to_insert_params()` (`src/intelligence/features/feature_vector_persistence.py`)
-- the single shared row-serializer for both `feature_vectors` write paths (live asyncpg writer
and batch psycopg backfill) -- never clamped a `real`-typed float to Postgres's float4-
representable range. Two distinct, live-confirmed mechanisms produced underflowing values: (1)
HMM posterior-probability/entropy columns for ENPH/GLD/NAD/SHY/STIP/VRP (several already sitting
at the literal float4 floor in committed data), and (2) an unrounded `exp(-k*touch_count)` zone-
freshness-decay computation in `feature_factory.py` for BIL specifically (BIL's near-zero
volatility drives excessive zone retests; its HMM columns are separately, entirely NULL, a
pre-existing bug tracked in todos 341/362).

Fix: promoted the existing todo-312 clamp helper (`_clamp_to_real_range`) to a new Ring 0
module, `src/core/real_column_range.py`, and applied it column-agnostically over every tuple
element inside `feature_vector_to_insert_params()` -- fixing both write paths in the one shared
function. 3 new regression tests added to `tests/unit/test_feature_vector_persistence_completeness.py`.
Full `tests/unit/` suite green, `ruff check .` clean.

**Live end-to-end confirmation, 2026-09-22: CONFIRMED.** Ran
`backfill_feature_factory.py --compute-only --symbols BIL,VRP,ENPH,GLD,NAD,SHY,STIP --refresh --workers 1`
fresh (post-fix). All 28 originally-affected symbol/tf cells (7 symbols x 4 real timeframes) now
show `backfill_status.status='complete'` with real row counts, zero underflow errors. Confirmed
the clamp is live-firing on production data (396,500 BIL rows with `zone_friction_score=0.0`,
hundreds of `hmm_entropy=0.0` rows across the other symbols). Notably, several symbols' history
had been silently stalled for years -- e.g. BIL/5m was capped at 2018-03-07 before this fix; it
now extends through 2026-09-16, a multi-year gap in the corpus now filled. Full debug record:
`.planning/debug/resolved/underflow-7symbol-real-column.md`.

**Also flagged during this investigation, not fixed (out of scope, separate low-priority
finding):** a harmless, pre-existing false-positive logging bug in `backfill_feature_factory.py`
-- `compute_checkpoint_desynced` warnings fire even under `--refresh` mode when they're supposed
to be skipped (the row-count query is skipped by design, but the consuming log-warning logic
isn't gated the same way), producing misleading "0 actual rows" log noise during any `--refresh`
run against `status='complete'` cells. No data loss, purely cosmetic log noise -- worth a
follow-up todo if the noise becomes a real problem.

**Both halves of todo 340 are now fully closed.** This todo can be moved to `completed/`.

## Investigation progress, 2026-09-22 (superseded by the resolutions above; kept for history)
still unresolved as described)

**IHF: root cause NOT pinpointed, sequencing decided before Phase 175 (see STATE.md).** Re-ran
`backfill_feature_factory.py --compute-only --symbols IHF --workers 1` twice this session --
both times reproduced `backfill_status.error_msg = "expected a positive input, got 0.0"`,
`status='failed'`, 0 rows written, no change from before. Confirmed by direct grep: **that exact
string does not appear anywhere in this codebase** -- it's a third-party (likely scipy/numpy or
statsmodels) exception, caught generically at `backfill_feature_factory.py:1415-1417`
(`except Exception as error: error_msg = str(error); worker_log.error("worker_failed", ...)`)
and stringified without ever logging a full traceback (`exc_info=True` not passed) -- this is
itself worth fixing regardless of the underlying bug, since it's why two identical runs produced
zero additional diagnostic signal. Live run also surfaced two RuntimeWarnings worth checking
first before chasing third-party code: `feature_factory.py:2284`'s `illiq = log_rets_abs /
dollar_vols` is a genuinely unguarded division (no `np.maximum` floor, unlike the codebase's
usual pattern) -- a zero-dollar-volume bar would produce `inf`/`nan` here silently (a warning,
not the fatal error, but worth guarding regardless); `feature_factory.py:1154`'s `np.where`
division warning is confirmed benign (numpy evaluates both branches of `np.where` before
masking, result is correct despite the warning).

**Next step, not yet done:** add `exc_info=True` (or equivalent) to the worker's exception log,
or wrap the compute call in a narrower try/except to get the real traceback/library frame, before
guessing further at which call site raises this. Only then decide the fix (skip-and-log vs.
epsilon-floor per the original fix-shape below).

**7-symbol underflow bug (BIL/VRP/ENPH/GLD/NAD/SHY/STIP): strong hypothesis found via code
inspection, NOT yet verified against a live run.** `backfill_feature_factory.py` writes
`feature_vectors` through a raw INSERT (`FEATURE_VECTOR_INSERT_SQL_PSYCOPG` from
`src/intelligence/features/feature_vector_persistence.py`), not through `bulk_update_by_key` --
confirmed via grep, neither file references `_clamp_to_real_range`/`bulk_update_by_key` at all.
That means this write path never got todo 312's underflow-clamp fix. `feature_vectors` has 309
`real`-typed columns (confirmed live via `information_schema.columns`), including
`hmm_regime_prob`/`hmm_entropy` -- the exact same feature *type* (HMM posterior probability) that
caused todo 312's original bug in `regime_writer.py` (a highly-confident state assignment
producing a residual probability smaller in magnitude than float4 can represent, e.g. 1e-50).
Strongly suggests the same phenomenon here, just via a different, unprotected writer. **Not yet
confirmed live** -- didn't get to running a real BIL backfill this session to catch the exact
column/value. Do that first before implementing a fix.

**Fix shape, given the above:** likely just wiring `_clamp_to_real_range` into
`FEATURE_VECTOR_INSERT_SQL_PSYCOPG`'s value-building step (or switching this write path onto
`bulk_update_by_key`, which gets the clamp automatically) -- simpler than the original filing's
speculative "clamp vs. widen column type vs. skip-and-log" framing, IF the hypothesis confirms.
Verify against BIL live before committing to this shape.

## Where

- `services/backfill_feature_factory.py` -- `_compute_symbol_tf`, `FeatureFactory.compute_batch`
- `src/intelligence/feature_factory.py` / `src/intelligence/feature_cache.py` -- candidate
  unguarded `log()`/division call sites (IHF) and candidate degenerate-variance feature calcs
  (the other 7)
- `services/_batch_utils.py` -- `_clamp_to_real_range`, the `real`-column write-guard path
- `backfill_status` rows: all 12 listed in the table above, `symbol IN ('BIL','VRP','ENPH',
  'GLD','NAD','SHY','STIP','IHF')`
- Related: [341](341-bil-etha-ibit-zero-regime-labels.md), [362](362-bil-5m-zero-regime-volatility-labels.md)
  -- BIL's separate degenerate-HMM-fit failures, plausibly sharing the same near-zero-variance
  root cause as this todo's underflow cells
