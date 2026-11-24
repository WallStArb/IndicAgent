# 529 (closed): Test-suite cleanup: delete remnants of deleted systems, consolidate redundancy, cut runtime

Filed: 2026-10-10
Owner: closed 2026-11-23
Priority: P1 (owner directive; the suite burns time and tokens every session)
Evidence: /tmp/test_suite_audit.md (2026-10-10 audit; regenerate before deleting)

Owner directive 2026-10-10: "cleanup and organize all tests; many are remnants of old
code and many redundant; the suite burns way too much time and tokens."

Rules for the pass:
- Nothing deletes without evidence: the audited report must show the subject under
  test no longer exists (deleted in 185-45 / the v2.x archive) or a duplicate with a
  named survivor.
- Remnants of the v2.x I1-I7 path, the I8 AI stack, AlphaEngine, ensemble_trainer,
  the old ic_engine, forward_returns and the Tradier loader are the first targets;
  vacuously-passing tests are worse than none.
- Consolidation prefers one load-bearing test over three stale ones; renaming to the
  live concept beats deletion when the coverage is real.
- Speed wins second: module-scoped fixtures for per-test recomputation, stubs for
  disk/network, before any deletion of slow-but-load-bearing tests.
- CI must stay green at every commit; run the full unit suite per batch.

Deliverables:
1. Deletable-now list executed in batches with per-batch full-suite runs.
2. Redundancy consolidations with the surviving test named.
3. Speed fixes for the top offenders that survive.
4. A recorded baseline (runtime, counts) before/after.

## Progress

- Baseline 2026-10-26: 7,834 unit tests collected (wall time not captured; pytest.ini's -q hides
  the summary line, so time runs with `-o addopts="-ra"`).
- Batch 1, 2026-10-26 (23056ccca, todo 509 item 1): 42 test files whose only subject was v2.x
  code deleted in the same commit (executor, signal stages, trade framer, zone engine, CIS
  scorer, plugin observer, I1/I3 plugins, CacheManager); the instrument-row tests moved to
  `tests/unit/config/test_settings.py`. 6,970 collected; full run 6,970 passed, 1 skipped,
  299 s (306 s wall). Evidence: the AST reachability check in the commit message, every deleted
  test failed import against the trimmed tree.
- Batch 2, 2026-10-26 (speed): pytest-xdist added (dev group, requirements.txt, uv.lock);
  `tests/conftest.py` pins OMP/OpenBLAS/MKL/numba to one thread inside each worker (unpinned,
  12 workers each started a 24-thread pool and every test ran about 5x slower: 191 s) and caps
  `-n auto` at half the cores. Full unit run 306 s -> 70 s wall, same 6,970 passed. Fixed what
  parallel runs exposed: a uuid4 test id that differed per worker
  (`test_api_routes_smoke.py`) and a wall-clock scaling test now timed by CPU time
  (`test_regime_signals_causal_rank.py`). CI and CLAUDE.md commands use `-n auto`.
- Batch 3, 2026-10-26 (redundancy): an AST hash of every test body (over 200 chars, docstring
  stripped) found 22 copies of another test in the same file: 7 of the Settings
  no-contracts check (`test_settings.py`), the 5 "vectorized matches original" peak/trough
  copies (`test_utils.py`), 3 gradient continuity copies, 2 ETF field checks, and one each in
  base_agent, d1_gaps, backfill_feature_factory, batch_utils and canary_predictors. The
  survivor is the copy with the rationale docstring. Cross-file matches left alone: they read
  a per-file migration constant, so the bodies match but the subjects differ. 6,953 passed,
  1 skipped, 88 s wall.
- Batch 4, 2026-10-26 (speed and consolidation):
  - `test_feature_kernels.py`: the per-kernel probe test (278 cases, 128 s of CPU) re-ran the
    causality probe and memory check that the three `probe_registry` tests already run on every
    kernel on the same rows; the partition test keeps every kernel inside one of them. Deleted.
  - `test_swing_fib_trend_structure_primitives.py`: the live/batch parity replays called
    `compute()` on every bar over the growing history (quadratic; 26 s, 10 s, 10 s), but
    `compute()` leaves no state, so the replay now applies the per-bar mutators and calls
    `compute()` once. `test_per_bar_compute_equals_the_single_call_replay` holds that
    equivalence on every FeatureVector field over a 100-bar prefix. Shared module fixtures for
    the batch runs. Module: 46 s -> 8.5 s serial.
  - 6,680 passed, 1 skipped; 58 s wall on a quiet box (88 s with a second suite running).
- Batch 5, 2026-10-26: `tests/unit/intelligence/live_parity.py` replaces 8 copied live/batch
  parity loops (one mutator order, compute() once with a per-fixture cache-purity check, a
  per-group nonzero vacuity guard; it caught the FVG test comparing 0.0 with 0.0, now on an open
  gap). 6,680 passed, 60 s wall.
- Batch 6, 2026-11-23 (indicagent-af), closing pass. Baseline before: 8,431 passed, 17 skipped, 226 s
  wall at `-n 4` (a memtester run held the host). Remnant audit: no test imports a deleted
  module (CI is green, every deleted subject fails import), and the remaining mentions of
  `ensemble_trainer`, `EnsembleICEngine`, `forward_return_writer` and the like are docstring
  history, absence guards or the live `CorpusManifest`. Three files test nothing of the repo and
  are deleted: `test_bh_fdr_mapping.py` (5 tests) and `test_ic_bh_fdr.py` (3 tests) call only
  statsmodels `multipletests` on literals, for the deleted old ic_engine; the repo's own
  `apply_bh_fdr` keeps its four tests in `test_ic_math.py`, which also keeps the Fisher-z, p-value
  and circular-shift tests. `scripts/test_nightly_overlap.py` held a constant block and no test
  function. Speed: `mtf_fixtures.session_bounds` called `nyse_sessions(day, day)` per day, so a
  long grid thrashed that function's 32-entry cache and rebuilt the pandas calendar schedule for
  each day (0.15 s a day); it now builds one schedule per year. `test_runner_feature_members.py`
  went from 68 s to 7 s serial, and the same fixture serves three other research test files.
  Left alone as load-bearing and not redundant: the stepm family-wise error simulation (15 s),
  the probe registry statuses (13 s and 10 s), the regime goldens (7 s each).
  After: 8,422 passed, 17 skipped (8 deleted tests; one more test collected than the arithmetic
  gives because the earlier run counted a dirty-tree skip), 128 s wall at `-n 4`, exit 0.
