# Deferred Items — Plan 03 (141.1-03)

## Pre-existing unit test failures (out of scope for this plan)

Observed during full-suite verification (`.venv/bin/pytest tests/unit/ -q`), 33 failures
across files this plan does not touch:

- `tests/unit/scripts/test_fetch_htf_bars.py` (3 failures)
- `tests/unit/scripts/test_roll_batch.py` (1 failure)
- `tests/unit/scripts/test_run_historical_pipeline.py` (16 failures)
- `tests/unit/services/test_regime_writer.py` (8 failures)
- `tests/unit/test_causal_hmm_decoding.py` (5 failures)
- `tests/unit/test_regime_writer.py` (1 failure)

Root cause sample (test_causal_hmm_decoding.py): `TypeError: _alpha_pass() takes 3
positional arguments but 5 were given` — a signature mismatch in HMM causal-decode code
(`regime_writer.py` / `_alpha_pass`), unrelated to config_service, alpha_events,
forward_returns, or cost-hurdle calibration. Not touched by this plan's files
(`scripts/ops/corpus/ops_cost_hurdle_calibration.py`, `tests/unit/test_cost_hurdle_calibration.py`).

This plan's own new test file (`tests/unit/test_cost_hurdle_calibration.py`, 12 tests) passes
cleanly, both in isolation and as part of the full suite run. Per SCOPE BOUNDARY rules, these
pre-existing failures are logged here, not fixed — likely from concurrent Wave 1 work
(Plan 02 touches `ic_engine.py`) or a pre-existing main-branch state. Follow up separately.
