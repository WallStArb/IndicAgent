---
phase: 138-feature-factory-single-path
plan: P2
type: execute
wave: 2
depends_on: [P1]
files_modified:
  - services/backfill_feature_factory.py
  - tests/unit/intelligence/test_feature_factory_p7.py
autonomous: true

must_haves:
  truths:
    - "_precompute_series() function deleted from backfill_feature_factory.py"
    - "_MIN_BATCH_WINDOW constant deleted from backfill_feature_factory.py"
    - "All _*_series_full imports deleted from backfill_feature_factory.py (no direct series_full calls remain)"
    - "_compute_symbol_tf calls FeatureFactory.compute_batch(bars, symbol, tf, cache, config, warm_up_bars)"
    - "_compute_symbol_tf loops over compute_batch() results to build insert_batch"
    - "test_feature_factory_p7.py: _amihud_illiq_z, _high_52w_dist, _ret_skew_z, _ret_acf1_z imports replaced with _*_series_full equivalents"
    - "test_feature_factory_p7.py: 4 test bodies updated to call _*_series_full(...)[-1] instead of scalar functions"
    - ".venv/bin/pytest tests/unit/ -q GREEN"
  artifacts:
    - path: "services/backfill_feature_factory.py"
      provides: "simplified _compute_symbol_tf using compute_batch()"
      contains: "compute_batch"
    - path: "tests/unit/intelligence/test_feature_factory_p7.py"
      provides: "updated tests using series_full equivalents"
      contains: "_amihud_illiq_z_series_full"
  key_links:
    - from: "backfill_feature_factory._compute_symbol_tf"
      to: "FeatureFactory.compute_batch()"
      via: "Single call returns list[(bar_ts, FeatureVector)]; loop builds insert_batch from results"
      pattern: "compute_batch"
---

<objective>
Update the two consumers of the old `_precompute_series + compute(precomputed=...)` pattern.

backfill_feature_factory.py: Delete `_precompute_series`, `_MIN_BATCH_WINDOW`, and all
`_*_series_full` imports (no longer called directly). Replace the 40-line precompute + per-bar
loop with `FeatureFactory.compute_batch(bars, symbol, tf, cache, config, warm_up_bars)`.

test_feature_factory_p7.py: The 4 tests that import deleted scalar functions
(`_amihud_illiq_z`, `_high_52w_dist`, `_ret_skew_z`, `_ret_acf1_z`) switch to their
`_*_series_full` equivalents. Semantics preserved — cold-start behavior is identical.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@docs/plans/2026-06-23-feature-factory-single-path-refactor.md
@services/backfill_feature_factory.py
@tests/unit/intelligence/test_feature_factory_p7.py
@src/intelligence/feature_factory.py
@CLAUDE.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Simplify backfill_feature_factory.py</name>
  <files>services/backfill_feature_factory.py</files>
  <read_first>
    - services/backfill_feature_factory.py (full read — find _precompute_series function; find _MIN_BATCH_WINDOW; find all _*_series_full imports at module level; find _compute_symbol_tf and the series = _precompute_series(...) + per-bar loop)
    - docs/plans/2026-06-23-feature-factory-single-path-refactor.md (spec — backfill_feature_factory.py changes section)
    - src/intelligence/feature_factory.py (FeatureFactory.compute_batch signature — already added in P1)
  </read_first>
  <action>
    Four targeted deletions and one replacement in backfill_feature_factory.py:

    **1. Delete _precompute_series() function.**
    Find the function definition (def _precompute_series) and delete the entire function
    including its docstring. It is approximately 60 lines. Verify it ends before the
    next function/class definition.

    **2. Delete _MIN_BATCH_WINDOW constant.**
    Find and delete the line `_MIN_BATCH_WINDOW: int = 50` (and its comment block if any).

    **3. Delete _*_series_full imports.**
    In the module-level imports from src.intelligence.feature_factory, remove all
    `_*_series_full` names. These are the imports that were used only by _precompute_series.
    Keep all other imports from feature_factory (FeatureFactory, FeatureFactoryConfig, etc.).
    Also remove `_rolling_zscore_series` from the imports if it was imported.
    After deletion, run `ruff check services/backfill_feature_factory.py` to confirm no
    unused import warnings remain for these names.

    **4. Add FeatureFactory.compute_batch to imports (if not already imported via FeatureFactory).**
    FeatureFactory is already imported; compute_batch is a static method so no additional
    import is needed.

    **5. Replace the precompute + loop pattern in _compute_symbol_tf.**
    Find this block in _compute_symbol_tf:
    ```python
    series = _precompute_series(bars, config)
    insert_batch: list[tuple] = []
    total_inserted = 0
    for i in range(1, total_bars):
        window_start = max(0, i - _MIN_BATCH_WINDOW)
        window = bars[window_start : i + 1]
        if i % config.regime_cache_refresh_bars == 0:
            cache.refresh_regime(window, config)
        if i < warm_up_bars:
            continue
        bar_ts = window[-1]["ts"]
        last_bar = window[-1]
        fv = FeatureFactory.compute(
            window, symbol, tf, cache, config,
            precomputed={k: float(arr[i]) for k, arr in series.items()},
        )
        cache.advance_bar(bar_ts, last_bar["high"], last_bar["low"], last_bar["close"], last_bar["volume"])
        row = _vector_to_params(symbol=symbol, tf=tf, bar_ts=bar_ts, pipeline_version=pipeline_version, regime=None, fv=fv)
        insert_batch.append(row)
        if len(insert_batch) >= _INSERT_BATCH_SIZE:
            _batch_insert(conn, insert_batch)
            total_inserted += len(insert_batch)
            insert_batch = []
    ```

    Replace with:
    ```python
    batch_results = FeatureFactory.compute_batch(
        bars, symbol, tf, cache, config, warm_up_bars=warm_up_bars
    )
    insert_batch: list[tuple] = []
    total_inserted = 0
    for bar_ts, fv in batch_results:
        row = _vector_to_params(
            symbol=symbol,
            tf=tf,
            bar_ts=bar_ts,
            pipeline_version=pipeline_version,
            regime=None,
            fv=fv,
        )
        insert_batch.append(row)
        if len(insert_batch) >= _INSERT_BATCH_SIZE:
            _batch_insert(conn, insert_batch)
            total_inserted += len(insert_batch)
            insert_batch = []
    ```

    The `_logger.info("compute_bars_loaded", ...)` call and all surrounding context (the
    early-return for warm_up_bars >= total_bars check, the coverage logging, the final
    _batch_insert flush) remain unchanged — only the precompute + loop block is replaced.
  </action>
  <acceptance_criteria>
    - `grep -c "def _precompute_series" services/backfill_feature_factory.py` returns 0
    - `grep -c "_MIN_BATCH_WINDOW" services/backfill_feature_factory.py` returns 0
    - `grep -c "_series_full" services/backfill_feature_factory.py` returns 0
    - `grep -c "precomputed=" services/backfill_feature_factory.py` returns 0
    - `grep -c "compute_batch" services/backfill_feature_factory.py` returns >= 1
    - `.venv/bin/ruff check services/backfill_feature_factory.py` passes (no unused import errors)
    - `.venv/bin/python -c "from services.backfill_feature_factory import BackfillFeatureFactory; print('import ok')"` exits 0
    - `.venv/bin/pytest tests/unit/services/test_backfill_feature_factory.py -q` GREEN (if test file exists)
  </acceptance_criteria>
  <verify>.venv/bin/python -c "from services.backfill_feature_factory import BackfillFeatureFactory; print('backfill import: ok')"</verify>
  <done>_precompute_series deleted; _MIN_BATCH_WINDOW deleted; _*_series_full imports removed; _compute_symbol_tf uses FeatureFactory.compute_batch().</done>
</task>

<task type="auto">
  <name>Task 2: Update test_feature_factory_p7.py</name>
  <files>tests/unit/intelligence/test_feature_factory_p7.py</files>
  <read_first>
    - tests/unit/intelligence/test_feature_factory_p7.py (full read — find the 4 imports of deleted scalar functions and all test bodies that call them)
    - docs/plans/2026-06-23-feature-factory-single-path-refactor.md (spec — Test Updates section with before/after examples)
    - src/intelligence/feature_factory.py (verify _amihud_illiq_z_series_full, _high_52w_dist_series_full, _ret_skew_z_series_full, _ret_acf1_z_series_full signatures — already exist from Phase 137)
  </read_first>
  <action>
    Update imports and test bodies for the 4 scalar functions being deleted.

    **Imports — replace 4 scalar imports with series_full equivalents:**
    Before:
    ```python
    from src.intelligence.feature_factory import (
        _amihud_illiq_z,
        _high_52w_dist,
        ...
        _ret_acf1_z,
        _ret_skew_z,
        ...
    )
    ```
    After: replace each deleted function with its series_full equivalent:
    - `_amihud_illiq_z` → `_amihud_illiq_z_series_full`
    - `_high_52w_dist` → `_high_52w_dist_series_full`
    - `_ret_skew_z` → `_ret_skew_z_series_full`
    - `_ret_acf1_z` → `_ret_acf1_z_series_full`

    **Test bodies — update calls from scalar to series_full[-1].**

    Per the spec's before/after example:
    ```python
    # Before
    assert _amihud_illiq_z(closes, volumes, 20) == 0.0
    # After
    assert _amihud_illiq_z_series_full(closes, volumes, 20)[-1] == 0.0
    ```

    Apply the same pattern to all 4 functions. Read each test body carefully:
    - Amihud tests (3 assertions): `_amihud_illiq_z(closes, volumes, 20)` → `_amihud_illiq_z_series_full(closes, volumes, 20)[-1]`
    - high_52w_dist tests (3 assertions): `_high_52w_dist(closes, 20)` → `_high_52w_dist_series_full(closes, 20)[-1]`
    - ret_skew_z tests (2 assertions): `_ret_skew_z(closes, 10, 20)` → `_ret_skew_z_series_full(closes, 10, 20)[-1]`
    - ret_acf1_z tests (2 assertions): `_ret_acf1_z(closes, 5, 20)` → `_ret_acf1_z_series_full(closes, 5, 20)[-1]`

    The test arrays (closes, volumes) must have sufficient length for the series_full call.
    Series_full functions return 0.0 at cold-start positions by construction, so the semantics
    of "cold-start returns 0.0" assertions are preserved when calling `[-1]` on a short array.
    Verify each test array length against the function's window argument before replacing.

    Do NOT change any other test logic — only the import names and call sites for these 4 functions.
  </action>
  <acceptance_criteria>
    - `grep -c "_amihud_illiq_z\b[^_]" tests/unit/intelligence/test_feature_factory_p7.py` returns 0 (scalar version gone)
    - `grep -c "_high_52w_dist\b[^_]" tests/unit/intelligence/test_feature_factory_p7.py` returns 0
    - `grep -c "_ret_skew_z\b[^_]" tests/unit/intelligence/test_feature_factory_p7.py` returns 0
    - `grep -c "_ret_acf1_z\b[^_]" tests/unit/intelligence/test_feature_factory_p7.py` returns 0
    - `grep -c "_amihud_illiq_z_series_full" tests/unit/intelligence/test_feature_factory_p7.py` returns >= 3 (import + assertions)
    - `grep -c "_high_52w_dist_series_full" tests/unit/intelligence/test_feature_factory_p7.py` returns >= 3
    - `grep -c "_ret_skew_z_series_full" tests/unit/intelligence/test_feature_factory_p7.py` returns >= 2
    - `grep -c "_ret_acf1_z_series_full" tests/unit/intelligence/test_feature_factory_p7.py` returns >= 2
    - `.venv/bin/pytest tests/unit/intelligence/test_feature_factory_p7.py -v` GREEN (all tests pass)
  </acceptance_criteria>
  <verify>.venv/bin/pytest tests/unit/intelligence/test_feature_factory_p7.py -v 2>&1 | tail -15</verify>
  <done>4 scalar imports replaced with _*_series_full equivalents; all test call sites updated to _*_series_full(...)[-1]; all p7 tests green.</done>
</task>

<task type="auto">
  <name>Task 3: Full test suite green</name>
  <files></files>
  <read_first>
    - (no reads needed — run tests and fix any failures)
  </read_first>
  <action>
    Run the full unit test suite and fix any failures:
    .venv/bin/pytest tests/unit/ -q

    Expected failures that require attention:
    - Any test importing a deleted scalar function from feature_factory.py
    - Any test that calls FeatureFactory.compute() with precomputed= kwarg

    If failures are found, grep for the failing import/call pattern and fix:
    - `grep -r "from src.intelligence.feature_factory import.*_rolling_zscore\|_gap_z\b\|_ofi_z\|_cvd_accumulate\|_cvd_slope_z\|_volume_z\b\|_momentum_z\b\|_atr_z\|_rolling_stat_z\|_vwap_dev_sigma\b\|_amihud_illiq_z\b\|_high_52w_dist\b\|_ret_skew_z\b\|_ret_acf1_z\b" tests/`
    - `grep -r "precomputed=" tests/`

    For each hit: replace scalar import with series_full equivalent; replace call sites with
    `_*_series_full(...)[-1]` pattern. Follow the same approach as Task 2.

    Also run ruff:
    .venv/bin/ruff check src/intelligence/feature_factory.py services/backfill_feature_factory.py
  </action>
  <acceptance_criteria>
    - `.venv/bin/pytest tests/unit/ -q` GREEN (no failures)
    - `.venv/bin/ruff check src/intelligence/feature_factory.py services/backfill_feature_factory.py` passes
  </acceptance_criteria>
  <verify>.venv/bin/pytest tests/unit/ -q 2>&1 | tail -5</verify>
  <done>Full unit test suite green; ruff clean on changed files.</done>
</task>

</tasks>

<verification>
- _precompute_series, _MIN_BATCH_WINDOW, _*_series_full imports deleted from backfill_feature_factory.py
- compute_batch() call in _compute_symbol_tf; loop over results builds insert_batch
- test_feature_factory_p7.py: 4 scalar imports replaced; all test bodies use _*_series_full[-1]
- .venv/bin/pytest tests/unit/ -q GREEN
- .venv/bin/ruff check src/intelligence/feature_factory.py services/backfill_feature_factory.py passes
</verification>

<success_criteria>
- All 3 task acceptance criteria pass
- .venv/bin/pytest tests/unit/ -q GREEN
- .venv/bin/ruff check passes on both changed files
</success_criteria>

<output>
After completion, create `.planning/phases/137b-feature-factory-single-path/137b-P2-SUMMARY.md` documenting:
- Lines deleted from backfill_feature_factory.py (_precompute_series LOC count)
- Test updates made
- Final test counts and pass status
</output>
