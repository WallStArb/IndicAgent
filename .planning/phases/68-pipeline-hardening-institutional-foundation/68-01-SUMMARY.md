---
plan: 68-01
phase: 68-pipeline-hardening-institutional-foundation
status: complete
completed: 2026-04-13
---

# Plan 68-01: Signal Pipeline Bug Fixes + Attribution

## What was built

Fixed 5 critical signal pipeline bugs and added 4 attribution/instrumentation improvements:

1. **Regime type injection** — `regime_type` on signal dicts now comes from plugin class attribute (e.g. `trend`, `mean_reversion`), not numeric HMM value
2. **HMM label separation** — `hmm_regime` (int) and `hmm_regime_label` (string) are separate keys
3. **Settings wiring** — `regime_prob_min` and `regime_dur_min` wired from `Settings` instead of hardcoded defaults
4. **Attribution vector** — 5-point confidence capture at correct pipeline stages (pre_quality, pre_regime, pre_tod, pre_calibration, calibrated)
5. **Checkpoint fix** — `_setup_last_fire` included in checkpoint state
6. **Resolution method** — stamped on every ranked signal dict
7. **Regime suppression metric** — `REGIME_GATE_SUPPRESSIONS_TOTAL` labeled counter for suppressed signals
8. **Confidence boost removed** — CIS aggregation no longer boosts confidence
9. **Long bias parameterized** — `winner_long_bias` from Settings, with `n_agreeing`/`n_opposing` capture

## Commits

- `af74f73a`: feat(68-01): fix regime type injection, attribution vector, and regime metric
- `940b78ea`: feat(68-01): remove confidence boost and parameterize long bias in winner selector

## Key Files

### Created
- `tests/unit/test_winner_selector.py` — 11 new tests for winner selector

### Modified
- `services/intelligence_pipeline_agent.py` — regime_type injection, HMM label separation, Settings wiring, attribution vector, regime suppression metric, checkpoint fix, resolution_method stamp
- `src/intelligence/pipeline/winner_selector.py` — removed confidence boost, added n_agreeing/n_opposing, parameterized long_bias
- `src/config/settings.py` — added `winner_long_bias` field
- `src/observability/metrics.py` — added `REGIME_GATE_SUPPRESSIONS_TOTAL` labeled counter
- `tests/unit/test_intelligence_pipeline_agent.py` — 13 new tests (26 total)

## Tests

37 tests pass (26 in test_intelligence_pipeline_agent + 11 in test_winner_selector)

## Deviations

None — all tasks implemented as planned.
