# Deferred Items — Phase 142B.1

## Pre-existing failing tests (out of scope for Plan 02)

`.venv/bin/pytest tests/unit/ -q` run after Plan 02 (shrinkage.py + mean_variance_weights)
shows 34 pre-existing failures, none in files touched by this plan:

- `tests/unit/intelligence/test_binary_pattern_scanner.py::test_zero_binary_violations`
- `tests/unit/scripts/test_fetch_htf_bars.py` (3 tests)
- `tests/unit/scripts/test_roll_batch.py::TestDetectRolls::test_roll_decision_fields`
- `tests/unit/scripts/test_run_historical_pipeline.py` (14 tests)
- `tests/unit/services/test_regime_writer.py` (8 tests)
- `tests/unit/test_causal_hmm_decoding.py::TestCausalVsViterbi` (5 tests)
- `tests/unit/test_regime_writer.py::test_causal_decode_vectorized_matches_original`

All are in the HMM regime_writer / historical-pipeline / roll-batch / HTF-backfill
subsystems — unrelated to `src/intelligence/ensemble/shrinkage.py` or
`src/intelligence/ensemble/weights.py::mean_variance_weights`. Per the executor's
scope-boundary rule, these are not fixed here. Full suite: 5421 passed, 34 failed,
41 skipped (621s).

`tests/unit/test_ensemble_shrinkage.py` and `tests/unit/test_ensemble_mean_variance.py`
(this plan's new tests) and `tests/unit/test_ensemble_math.py` (pre-existing sibling
suite) all pass green.
