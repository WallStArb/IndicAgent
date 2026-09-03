# Deferred Items — Phase 142B.1

## Pre-existing failing tests (out of scope for Wave 1)

`.venv/bin/pytest tests/unit/ -q` run after Wave 1 (migration 196 + pooled cross-sectional
dispatch [Plan 01], shrinkage.py + mean_variance_weights [Plan 02]) consistently shows the
same cluster of pre-existing failures, none in files touched by either plan:

- `tests/unit/intelligence/test_binary_pattern_scanner.py::test_zero_binary_violations`
- `tests/unit/scripts/test_fetch_htf_bars.py` (3 tests)
- `tests/unit/scripts/test_roll_batch.py::TestDetectRolls::test_roll_decision_fields`
- `tests/unit/scripts/test_run_historical_pipeline.py` (14-16 tests, count varies slightly run to run)
- `tests/unit/services/test_regime_writer.py` (8 tests)
- `tests/unit/test_causal_hmm_decoding.py::TestCausalVsViterbi` (5 tests)
- `tests/unit/test_regime_writer.py::test_causal_decode_vectorized_matches_original`

All are in the HMM regime_writer / historical-pipeline / roll-batch / HTF-backfill
subsystems — unrelated to `services/ensemble_ic_engine.py`, `src/intelligence/ensemble/shrinkage.py`,
or `src/intelligence/ensemble/weights.py::mean_variance_weights`. Confirmed via
`git diff --name-only` against each plan's commits. Per the scope-boundary rule, these are
not fixed here. Not investigated further; flagging for a future todo/investigation.

Full-suite counts observed across runs: ~5414-5421 passed, ~33-34 failed (count drift is the
binary-pattern-scanner test, which is flaky/order-dependent, not new breakage), 41 skipped.

## Plan 01-specific notes

`tests/unit/test_ensemble_ic_pooled_dispatch.py` (this plan's new tests) all pass green.

## Plan 02-specific notes

`tests/unit/test_ensemble_shrinkage.py` and `tests/unit/test_ensemble_mean_variance.py`
(this plan's new tests) and `tests/unit/test_ensemble_math.py` (pre-existing sibling suite)
all pass green.
