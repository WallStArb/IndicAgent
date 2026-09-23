---
slug: underflow-7symbol-real-column
status: resolved
trigger: >
  DATA_START
  7 symbols (BIL/VRP/ENPH/GLD/NAD/SHY/STIP) have partial/stalled feature_vectors backfills across
  12 backfill_status cells (5m/15m/1h/1d combos), all sharing error_msg='value out of range:
  underflow'. Todo 340 (.planning/todos/pending/340-ihf-5m-feature-compute-zero-row-positive-
  input-error.md). Each got 40-90% of its history computed and written before failing partway
  through -- not a first-bar crash, a specific value tripping a Postgres range check mid-run.
  DATA_END
created: 2026-09-22
updated: 2026-09-22
goal: find_and_fix
tdd_mode: false
---

# Debug: 7-symbol `feature_vectors` write underflow (BIL/VRP/ENPH/GLD/NAD/SHY/STIP)

## Symptoms

- **Expected behavior:** `backfill_feature_factory.py --compute-only` fully backfills each
  symbol/tf's `feature_vectors` history, matching what already happened for the other ~225
  symbols in the corpus.
- **Actual behavior:** 12 `backfill_status` cells across these 7 symbols show
  `status='failed'`, `error_msg='value out of range: underflow'`, with 40-90% of each symbol's
  history already computed and written before the failure -- a specific value tripping a
  Postgres `real`-column range check partway through, not a structural crash on the first bar.
- **Error messages:** `'value out of range: underflow'` -- a Postgres error, meaning a value
  written to a `real` (float4) column is smaller in magnitude than float4 can represent (e.g. a
  double-precision value like `1e-50`), not a Python-side exception. Matches CLAUDE.md's documented
  gotcha: `bulk_update_by_key`'s `col_types`/`_clamp_to_real_range` protection exists specifically
  for this failure class (todo 312).
- **Timeline:** Filed 2026-08-21 as part of todo 259/296 closure audit; re-confirmed live via
  corpus audit 2026-09-18. Not yet reproduced against a fresh live run this session (blocked on
  a concurrent todo-340/IHF confirmation re-run holding a `feature_vectors` write session -- see
  constraint below).
- **Reproduction:** Not yet re-run live this session. Prior filing's evidence is code-inspection
  only.

## Todo 340 constraints (read first)

- **Do not run `backfill_feature_factory.py --compute-only` concurrently with anything else
  reading/writing `feature_vectors`/`feature_ic_scores`.** It decompresses the ENTIRE hypertable
  regardless of `--symbols` scope (`docs/reference/gotchas.md`'s
  `compressed_hypertable_write_session` entry). As of this session start, a todo-340 IHF
  confirmation re-run (PID 234712) is still active holding this write session -- wait for it to
  exit (`ps aux | grep backfill_feature_factory`) before launching a live BIL run.
- This todo also tracks IHF's distinct `"expected a positive input, got 0.0"` bug -- **RESOLVED
  2026-09-22**, see `.planning/debug/resolved/ihf-5m-positive-input-error.md`. Root cause was
  unrelated to this underflow bug (a canary function's incomplete numerator guard, not a
  real-column write issue) -- do not assume a shared fix.

## Pre-verified evidence (orchestrator checked before delegating)

- Confirmed via grep (2026-09-22, this session): neither `feature_vector_persistence.py` nor
  `backfill_feature_factory.py` references `_clamp_to_real_range` or `bulk_update_by_key`
  anywhere. `feature_vectors` is written via a raw INSERT
  (`FEATURE_VECTOR_INSERT_SQL_PSYCOPG`), which never got todo 312's underflow-clamp fix -- that
  fix lives entirely inside `bulk_update_by_key` (`services/_batch_utils.py`), a different write
  path this one doesn't share.
- `feature_vectors` has 309 `real`-typed columns (confirmed live via `information_schema.columns`
  in the original filing), including `hmm_regime_prob`/`hmm_entropy` -- the exact feature *type*
  (HMM posterior probability) that caused todo 312's original bug in `regime_writer.py` (a
  highly-confident state assignment producing a residual probability smaller in magnitude than
  float4 can represent).
- Confirmed live (2026-09-22, this session) via `market_data_ohlcv_tradeable`: BIL's 5m close
  price has by far the lowest relative variance of the 7 symbols -- `stddev=0.122` against a
  `~89-93` price level (BIL is a T-Bill ETF, near-zero-volatility by construction). SHY
  (`stddev=1.75` vs `~80-87`) is the next-lowest, also a short-duration bond ETF. Both plausible
  candidates for producing a near-zero or highly-confident HMM state probability that underflows
  float4 on write. VRP/ENPH/GLD/NAD/STIP have materially higher relative variance -- less
  obviously the same mechanism, worth checking whether they fail via the same column or a
  different one once BIL's exact culprit is found.
- BIL is independently flagged in todos 341/362 for a related degenerate-HMM-fit failure
  (100% NULL `regime`/`regime_volatility` labels) -- plausibly the same root phenomenon
  (near-zero-variance instrument breaking HMM-derived columns) surfacing through two different
  write paths.

## Current Focus

reasoning_checkpoint:
  hypothesis: >
    feature_vector_to_insert_params() (src/intelligence/features/feature_vector_persistence.py),
    the single shared row-serializer imported by BOTH services/feature_vector_writer.py (live
    asyncpg path) and services/backfill_feature_factory.py (batch psycopg path), returns raw
    float64 feature values with no range clamping. Some historical bar for BIL/SHY/VRP/ENPH/
    GLD/NAD/STIP produces a `real`-typed derived statistic (most likely an HMM posterior
    probability/entropy residual, the exact class todo 312 already root-caused for a sibling
    write path) with magnitude smaller than float4's smallest subnormal (~1.4e-45). Postgres
    rejects the INSERT outright with "value out of range: underflow" rather than rounding to
    zero, aborting that executemany() batch (not just the one bad row) and killing the whole
    symbol/tf backfill cell.
  confirming_evidence:
    - "grep confirms feature_vector_persistence.py has zero references to clamp/underflow/
      float32/np.finfo -- no protection exists on this path, unlike services/_batch_utils.py's
      bulk_update_by_key, which got exactly this fix for todo 312 (2026-08-14) after
      regime_writer.py hit the identical Postgres error against a different real-typed table
      (regime_state) via a different write primitive."
    - "feature_vectors has 309 real-typed columns confirmed live via information_schema,
      including hmm_regime_prob/hmm_entropy -- the same feature type (HMM posterior
      probability) that caused todo 312's original bug."
    - "git history confirms the 2026-07-29 failure predates the todo-318 write-path refactor
      (2026-08-21): at failure time, _batch_insert() committed per-chunk inside the worker
      process itself (conn.commit() at end of _batch_insert, called every insert_batch_size
      rows inside the compute loop), explaining why backfill_status shows 40-90% of each
      symbol's rows durably committed with status='failed' -- prior chunks survived, only the
      chunk containing the culprit row aborted. This is consistent with a single bad float
      value in one specific row, not a structural/first-bar crash."
    - "BIL (stddev=0.122 on a ~89-93 price level, T-bill ETF) and SHY (stddev=1.75 on ~80-87,
      short-duration bond ETF) are the 2 lowest relative-variance instruments of the 7 --
      plausible producers of a highly-confident (near-zero residual probability) HMM state
      assignment. BIL is independently flagged in todos 341/362 for a related degenerate-HMM
      failure on the same instrument."
  falsification_test: >
    If the live BIL --compute-only re-run (blocked behind the concurrent todo-340 IHF
    compress_chunk recompression holding an exclusive lock on feature_vectors, in progress
    30+ min as of this checkpoint) reproduces a DIFFERENT Postgres error class (not
    "value out of range: underflow"), or if a live query against already-committed BIL rows
    finds no real-typed column value anywhere near the float4 subnormal floor once the lock
    clears, this hypothesis is wrong and the mechanism needs re-investigation.
  fix_rationale: >
    Apply the same _clamp_to_real_range()-equivalent protection bulk_update_by_key already has
    (todo 312 pattern), but at feature_vector_to_insert_params() -- the single shared
    serialization point for both write paths -- rather than duplicating the fix separately in
    feature_vector_writer.py and backfill_feature_factory.py. This addresses the root cause
    (write path lacks the protection a sibling path already has) not a symptom (e.g. skipping
    the bad row, or catching-and-ignoring the Postgres exception). Per Ring architecture
    (src/intelligence/ = Ring 1, must not import services/ = Ring 2), the clamp helper cannot be
    imported from services/_batch_utils.py directly -- promoting it to a new Ring 0 module
    (src/core/real_column_range.py) and having BOTH services/_batch_utils.py and
    feature_vector_persistence.py import from there keeps one source of truth instead of two
    copies that can drift.
  blind_spots: >
    Have not yet empirically confirmed the exact failing row/column/value with a live query or
    reproduction run -- blocked on the concurrent todo-340 process's exclusive lock during
    hypertable recompression. The fix is being applied on strong circumstantial/mechanistic
    evidence (matches todo 312's exact failure class, on the exact write path documented to
    lack the fix, on instruments plausible for producing the triggering value) rather than a
    directly-observed underflowing value. Once the lock clears, will verify by (a) checking
    already-committed BIL/SHY rows for near-subnormal real values, and (b) re-running the
    previously-failed cells with --refresh after the fix lands, confirming they now complete
    and comparing before/after row counts against theoretical_max.

- **next_action:** DONE. Live re-run completed successfully (PID 313403, 2026-09-22T22:04:19Z
  to 2026-09-23T00:10:50Z, exit code 0). Verified zero underflow errors and all previously-
  failed cells now `status='complete'`. See Evidence and Resolution.verification below. Ready
  for archive_session.

## Evidence

- timestamp: 2026-09-22T21:15Z
  checked: `backfill_status` rows for the 7 symbols (`error_msg`, `rows_written`, `completed_at`)
  found: All 12 failed cells' `error_msg` is exactly `"value out of range: underflow"` --
    Postgres's raw primary message with no DETAIL/column context (confirms `str(psycopg
    error)` alone can't name the culprit column; matches this being the literal Postgres
    `float4in()` message, not a wrapped/decorated one). BIL's 4 cells show `rows_written`
    values (328033/121330/28496/4569) close to but below `theoretical_max`, with real
    `completed_at` timestamps all on 2026-07-29 -- consistent with a partial-then-aborted
    run, not a first-bar crash.
  implication: Confirms "40-90% written before failing" from the trigger. rows_written on a
    'failed' row is a stale value from before the failure (not reset to 0 by
    `_mark_cell_failed`), so it reflects whatever was true when the code path that set it last
    ran -- worth checking whether that value is durably reflected in `feature_vectors` itself
    (blocked, see below) or just a stale status-table artifact.

- timestamp: 2026-09-22T21:20Z
  checked: `_batch_insert`/`run_compute_stage`/`_run_compute_worker` in
    `services/backfill_feature_factory.py` (current version) plus git history of the same
    functions at the 2026-07-29 failure date
  found: Current code (post todo-318/2026-08-21 refactor) computes ALL rows for a symbol/tf
    in an isolated worker subprocess (compute-only, no DB writes), returns them to the main
    process, which writes via `_batch_insert` in `insert_batch_size` chunks inside ONE
    transaction per cell -- a failure partway through now rolls back the ENTIRE cell (comment:
    "a late-chunk failure discards every already-transmitted row in this cell, not just the
    failing chunk"). But `git show 2755213d3~1` (the commit immediately before the todo-318
    refactor, i.e. the code actually running on 2026-07-29) shows the OLD `_batch_insert` called
    `conn.commit()` internally, and was called directly inside the worker's per-symbol/tf
    compute+write loop every `insert_batch_size` rows -- i.e. each chunk committed durably and
    independently at the time of the original failure.
  implication: At the time of the original 2026-07-29 failures, prior chunks' rows ARE durably
    committed in `feature_vectors` for these 7 symbols (not rolled back) -- the atomicity
    refactor that would roll back partial writes postdates the failure by 3+ weeks. This means
    the already-written BIL/SHY/etc. rows in `feature_vectors` are real, inspectable evidence of
    where the run got to before hitting the underflow row -- confirmed live query blocked (see
    next entry), not yet inspected.

- timestamp: 2026-09-22T21:30Z
  checked: Attempted `SELECT count(*), min(bar_ts), max(bar_ts) FROM feature_vectors WHERE
    symbol IN (...)` against the live DB; `pg_stat_activity` for lock/wait state
  found: Query blocked indefinitely on `wait_event_type=Lock, wait_event=relation`. The
    concurrent todo-340 IHF confirmation run (PID 234712, still active) is mid-`compressed_
    hypertable_write_session` exit phase, running a single `compress_chunk(...)` call that has
    now run 70+ minutes with `wait_event=IO/DataFileExtend` (confirmed via `iostat -x` showing
    real sustained disk write throughput, not a hung/idle process) -- legitimately slow, not
    stuck, but blocking ALL reads against `feature_vectors` (not just writes) for the duration.
  implication: Cannot empirically inspect committed BIL/SHY rows or run a live reproduction
    this session without an indefinite wait (matches the todo-340 constraint documented at the
    top of this file). Proceeding on code-level/mechanistic evidence instead (see reasoning
    checkpoint in Current Focus) -- root cause confirmed via source-code inspection +
    Postgres's already-independently-confirmed (todo 312, live-tested 2026-08-14) real-column
    boundary behavior, not via a freshly observed failing value.

- timestamp: 2026-09-22T21:35Z
  checked: `src/intelligence/features/feature_vector_persistence.py`'s
    `feature_vector_to_insert_params()` (the single row-serializer both write paths import),
    `services/feature_vector_writer.py`, `services/backfill_feature_factory.py` call sites,
    `services/_batch_utils.py`'s `_clamp_to_real_range`/`bulk_update_by_key` (todo 312's fix)
  found: Both `feature_vector_writer.py` (live asyncpg) and `backfill_feature_factory.py`
    (batch psycopg) call `feature_vector_to_insert_params()` to build their INSERT tuple --
    confirmed the single shared choke point the module's own docstring claims. Confirmed (grep)
    zero clamp/underflow protection anywhere in this function before this session's fix.
    `_clamp_to_real_range` in `_batch_utils.py` is architecturally the right pattern to mirror
    but lives in `services/` (Ring 2); `feature_vector_persistence.py` is Ring 1 and must not
    import Ring 2 per CLAUDE.md's Ring rule.
  implication: Root cause confirmed at the mechanism level. Fix: promote the clamp helper to a
    new Ring 0 module (`src/core/real_column_range.py`) importable by both `_batch_utils.py`
    and `feature_vector_persistence.py`, then apply it inside
    `feature_vector_to_insert_params()`'s return tuple -- fixes both write paths in the one
    shared function, per the module's own "one schema definition, two consumers" design intent.

- timestamp: 2026-09-22T22:00Z
  checked: The todo-340 lock cleared briefly mid-session (compress_chunk phase finished, moved
    to a VACUUM step) -- got one clean read window against live `feature_vectors` data before
    it re-locked. Queried committed rows for all 7 symbols: row counts/date ranges confirm
    partial coverage for all 7 (matches "40-90% written"). Then, for each symbol, computed
    `min(abs(col)) FILTER (WHERE col != 0)` across all 309 `real` columns to find the
    closest-to-underflow committed value.
  found: >
    Two DISTINCT underflow-prone feature families confirmed live, not one:
    (1) HMM posterior-probability family -- for ENPH/GLD/NAD/SHY/STIP, multiple columns
    (hmm_entropy, hmm_prob_ranging, hmm_prob_trending_up/down, hmm_vol_entropy,
    hmm_vol_prob_calm/elevated) are ALREADY sitting at exactly `1e-45`/`3e-45` -- Postgres's
    smallest representable float4 subnormal, i.e. these rows already survived a round-to-the-
    floor on write; the next bar's true value plausibly rounds to 0 and gets rejected outright.
    VRP's closest is hmm_prob_ranging at 2.1e-44, same family.
    (2) SMC zone freshness-decay family -- for BIL specifically, ALL HMM columns are 100% NULL
    (confirmed: min/max/avg all NULL across all 4 tfs) -- consistent with todos 341/362's
    already-documented degenerate-HMM-fit bug for this exact symbol, so BIL's underflow is NOT
    via HMM at all. BIL's closest-to-zero column is `zone_friction_score` at exactly `1e-43`,
    with `demand_freshness`/`supply_freshness` also in the 1e-25 to 1e-27 range. Traced to
    src/intelligence/feature_factory.py line ~5639: `zone["freshness"] =
    freshness_decay(test_count, k=freshness_k)` (src/intelligence/utils/gradient_utils.py,
    `exp(-k * touch_count)`) computed and stored RAW, with no rounding/clamping -- unlike the
    archived I5/SMC-tier plugin (src/intelligence/features/smc_context/supply_demand_zones.py,
    no live consumer per CLAUDE.md) which happens to round to 4dp at the same computation (that
    version would never produce a sub-1e-4 value; the LIVE FeatureFactory version has no such
    guard). BIL is a near-zero-volatility T-bill ETF -- price barely moves, so the same
    supply/demand zone gets retested (`test_count`) far more times than a normal instrument
    before ever invalidating, driving `exp(-0.5 * test_count)` deep into subnormal territory
    (test_count ~200 -> ~1e-44).
  implication: >
    Confirms the fix must NOT be narrowly scoped to HMM columns (the debug session's original
    working hypothesis) -- BIL alone disproves "HMM posterior probability" as the universal
    mechanism. The column-agnostic fix already implemented (clamp_to_real_range() mapped over
    EVERY element of feature_vector_to_insert_params()'s return tuple, not a hardcoded list of
    HMM column names) correctly covers both confirmed mechanisms and any future one, without
    needing to enumerate which specific columns are at risk. No code change needed as a result
    of this finding -- it validates the fix's existing design (generality over enumeration) was
    the right call, and rules out a narrower alternative fix that would have missed BIL.

- timestamp: 2026-09-22T22:10Z
  checked: Implemented the fix; ran `tests/unit/test_batch_utils.py`,
    `tests/unit/test_feature_vector_persistence_completeness.py` (incl. 3 new tests added this
    session asserting underflow->0.0, overflow->REAL_MAX_MAGNITUDE, and ordinary-value
    passthrough on `feature_vector_to_insert_params()`), all tests touching the two write paths
    (`test_feature_vector_persistence_column_ownership.py`, `test_ensemble_trainer_meta_cols.py`,
    `test_compressed_hypertable_write_boundary.py`, `test_feature_factory_p7.py`,
    `test_feature_vector_writer_column_mapping.py`, `test_feature_vector_pipeline_threshold_keys.py`,
    `test_context_writer.py`, `test_regime_writer.py`), then the full `tests/unit/` suite and
    `ruff check .`
  found: All green. Full unit suite: 0 failures, 2 pre-existing unrelated skips. Ruff: all
    checks passed, no unintended changes outside the 3 touched files + 1 new file.
  implication: Fix is structurally correct and does not regress any existing write-path
    behavior. Still missing: a live reproduction/re-run against the actual previously-failed
    BIL/SHY/etc. cells, blocked on the concurrent process's lock (see above) -- this is the one
    remaining verification gap before declaring this fully resolved end-to-end.

- timestamp: 2026-09-23T00:10Z
  checked: Live end-to-end re-run, `backfill_feature_factory.py --compute-only --symbols
    BIL,VRP,ENPH,GLD,NAD,SHY,STIP --refresh --workers 1` (PID 313403, ran 2026-09-22T22:04:19Z
    to 2026-09-23T00:10:34Z, ~2h6m including bar loads + hypertable decompress/recompress).
    Checked `logs/backfill_feature_factory.log` for `underflow`/`compute_cell_write_failed`,
    `backfill_status` for all 28 (7 symbol x 4 tf) cells, `feature_vectors` row counts/max(bar_ts)
    per cell, and directly queried for `hmm_entropy = 0.0` / `zone_friction_score = 0.0` counts
    to confirm the clamp is actually firing on real data, not just structurally present but
    never triggered.
  found: >
    Zero underflow errors, zero write failures, anywhere in the run (`grep -c underflow` on the
    full log = 0; zero `compute_cell_write_failed`/error entries in the run's time window). All
    28 cells reached `compute_complete` and `backfill_status.status='complete'` with fresh
    `completed_at` timestamps. `feature_vectors` row counts match the log's `rows_written`
    exactly, and `max(bar_ts)` per cell now extends to current dates (e.g. BIL 5m: was capped
    at 2018-03-07 before the fix, now 2026-09-16 -- the full history, past the point that
    previously failed). Direct query confirms the clamp is live-firing, not just theoretically
    present: 396,500 BIL rows have `zone_friction_score = 0.0` (plus 4,835 with a tiny nonzero
    value under 1e-30 that survived without needing clamping) and hundreds of
    `hmm_entropy = 0.0` rows across ENPH/GLD/NAD/SHY/STIP (VRP: 0 exact-zero rows this run --
    fix is a no-op when the underflow condition doesn't occur, as expected, not evidence
    anything is wrong).
    Note: `backfill_status.error_msg` still shows the STALE text "value out of range:
    underflow" for cells that previously failed -- confirmed this is because
    `_MARK_COMPUTE_COMPLETE_SQL` only touches `status`/`rows_written`/`theoretical_max`/
    `completed_at`, never clears `error_msg` on a subsequent success. Cosmetic only
    (`status='complete'` is the authoritative field and is correct for all 28 cells) -- flagged
    as a minor separate follow-up, not blocking this resolution.
  implication: >
    Fix fully verified end-to-end against real production data for all 7 originally-affected
    symbols across all 4 timeframes. Root cause eliminated, not just theoretically addressed.
    Ready to archive.

## Eliminated

- hypothesis: >
    All 7 symbols underflow via the same single mechanism (an HMM posterior-probability/
    entropy residual).
  evidence: >
    Live query of committed feature_vectors rows shows BIL's hmm_regime_prob/hmm_entropy (and
    every other hmm_* column) are 100% NULL across all 4 tfs -- BIL has zero HMM-derived data
    at all (matches todos 341/362's already-documented degenerate-HMM-fit bug for this
    symbol). BIL's actual closest-to-underflow committed value is zone_friction_score at
    exactly 1e-43, traced to an unrounded exp(-k*touch_count) freshness-decay computation in
    feature_factory.py -- a completely different feature family. Refined, not fully wrong: the
    other 6 symbols (ENPH/GLD/NAD/SHY/STIP confirmed via hmm_* columns already sitting at the
    float4 subnormal floor; VRP's closest value is also hmm_prob_ranging) DO match the original
    HMM hypothesis. The fix implemented is column-agnostic (clamps every float in the INSERT
    tuple, not a hardcoded HMM column list) so this refinement required no code change -- it
    only changes what's cited as "the" root cause vs. "a" root cause pattern.
  timestamp: 2026-09-22T22:00Z

## Resolution

root_cause: >
  feature_vector_to_insert_params() (src/intelligence/features/feature_vector_persistence.py)
  is the single shared row-serializer for both feature_vectors write paths (live asyncpg
  FeatureVectorWriter and batch psycopg backfill_feature_factory), but never clamped a
  real-typed float to what Postgres's `real` (float4) column type can represent. Two distinct,
  confirmed-live feature families can legitimately produce a value smaller in magnitude than
  float4's smallest subnormal (~1.4e-45): (1) HMM posterior-probability/entropy columns
  (hmm_entropy, hmm_prob_ranging, hmm_prob_trending_up/down, hmm_vol_entropy,
  hmm_vol_prob_calm/elevated) for ENPH/GLD/NAD/SHY/STIP/VRP, several of which are already
  sitting at the exact float4 floor in already-committed rows; and (2) the SMC zone
  freshness-decay family (zone_friction_score/demand_freshness/supply_freshness =
  exp(-k*touch_count), unrounded) for BIL specifically, whose HMM columns are entirely NULL
  (a separate, already-tracked degenerate-HMM-fit bug, todos 341/362) -- BIL's near-zero
  volatility as a T-bill ETF causes the same supply/demand zone to be retested far more times
  than normal before invalidating, driving the decay deep into subnormal territory. Either
  mechanism triggers the identical Postgres "value out of range: underflow" rejection, aborting
  the whole executemany() batch containing that row and permanently stalling that symbol/tf's
  backfill at whatever row it reached (40-90% coverage, matching the code running at the time
  of the original 2026-07-29 failure, which committed per-chunk rather than per-cell).
fix: >
  Promoted the existing todo-312 clamp helper (previously a private function in
  services/_batch_utils.py, Ring 2, used only by bulk_update_by_key for a different table/write
  primitive) to a new Ring 0 module, src/core/real_column_range.py (clamp_to_real_range() +
  REAL_MIN_MAGNITUDE/REAL_MAX_MAGNITUDE constants derived from np.finfo(np.float32)) --
  importable by both a Ring 2 batch service and Ring 1 domain code without violating the Ring
  import rule. services/_batch_utils.py now imports from there instead of defining its own
  copy (old private names kept as module-level aliases so its existing callers/tests didn't
  need to change). feature_vector_to_insert_params() now maps clamp_to_real_range() over EVERY
  element of its return tuple before returning it -- deliberately column-agnostic (not a
  hardcoded list of HMM/SMC column names) so it covers both confirmed mechanisms above and any
  future one, fixing both write paths in the one function they already share.
verification: >
  Unit-level (complete): 3 new regression tests in
  tests/unit/test_feature_vector_persistence_completeness.py assert
  feature_vector_to_insert_params() clamps an underflowing value (1e-50) to 0.0, an overflowing
  value (1e50) to REAL_MAX_MAGNITUDE, and leaves an ordinary value (0.42) and non-float
  structural columns untouched -- all pass. Full tests/unit/ suite green (0 failures, 2
  pre-existing unrelated skips). ruff check . clean, no unintended changes.
  Live-data confirmation (complete): direct query against already-committed feature_vectors
  rows for all 7 symbols found real values already at or within a few orders of magnitude of
  the float4 subnormal floor in exactly the columns/mechanisms the root-cause analysis
  predicted (see Evidence entries above) -- this is not circumstantial, it's the actual
  live data exhibiting the trend toward the failure boundary.
  Live end-to-end re-run (COMPLETE, 2026-09-23T00:10Z): ran backfill_feature_factory.py
  --compute-only --symbols BIL,VRP,ENPH,GLD,NAD,SHY,STIP --refresh --workers 1 against
  production data. Zero underflow errors, zero write failures across all 28 (7 symbol x 4 tf)
  cells. All reached backfill_status.status='complete'; feature_vectors row counts match
  rows_written exactly; max(bar_ts) per cell now extends to current dates (previously capped
  at the original 2026-07-29 failure boundary, e.g. BIL 5m: 2018-03-07 -> 2026-09-16). Directly
  confirmed the clamp is live-firing on real data: 396,500 BIL rows now hold
  zone_friction_score=0.0, hundreds of hmm_entropy=0.0 rows across ENPH/GLD/NAD/SHY/STIP --
  values that would previously have triggered the Postgres underflow rejection instead landed
  cleanly at their mathematically-correct clamped value. Incident fully closed end-to-end.
files_changed:
  - src/core/real_column_range.py (new)
  - services/_batch_utils.py
  - src/intelligence/features/feature_vector_persistence.py
  - tests/unit/test_feature_vector_persistence_completeness.py
