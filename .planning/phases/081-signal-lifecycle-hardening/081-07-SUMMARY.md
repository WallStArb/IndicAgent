---
plan: 081-07
phase: 081-signal-lifecycle-hardening
status: complete
completed: 2026-05-09
---

## Summary

Implemented all 16 unit tests from design spec Section 8 across 7 test files. All 31 tests in `tests/unit/services/` pass. Also fixed a production bug in `signal_replay_auditor_agent.py` where `str(SignalOutcome.ENUM)` returned the full enum name instead of the value string.

## What Was Built

| Design Spec Row | Test File | Tests | Status |
|---|---|---|---|
| D-03 _load_signal canonical | test_signal_tracker_load_signal.py | 3 | ✓ |
| D-02 violation counter | test_lifecycle_tracker_d02.py | 1 | ✓ |
| no-DB-writes assertion | test_signal_tracker_no_db_writes.py | 1 | ✓ |
| backfill fast-path | test_signal_tracker_backfill_fast_path.py | 2 | ✓ |
| publisher normalization | test_intelligence_pipeline_publisher_normalization.py | 1 | ✓ |
| replay outcomes (north-star) | test_signal_replay_auditor.py | 5 (20 parametric) | ✓ |
| bar replay routing/ordering | test_bar_replay_provider.py | 3 | ✓ |

**Total:** 16 test functions / 31 collected (parametric expansion)

## Key Decisions

- **`test_replay_outcome_parametric`**: 8 outcomes × 2 directions = 16 parametric cases. Bar sequences are hand-engineered so each outcome fires exactly once — lows must stay above targets[0] for stop cases.
- **Outcome `.value` fix**: `str(SignalOutcome.NEVER_ACTIVATED)` returns `'SignalOutcome.NEVER_ACTIVATED'` not `'never_activated'` in Python's `str, Enum`. Fixed `_build_exit_transition` and `_evaluate_market_track` to use `.value`.
- **`bars_in_trade` tracking**: Rescued uncommitted improvement from 081-07 agent — MAE/MFE update and bars_in_trade increment now happen in the `transition is None` branch for active signals, enabling correct stop outcome classification.

## Self-Check: PASSED

```
.venv/bin/pytest tests/unit/services/ -v → 31 passed in 0.16s
```

## key-files

- created: tests/unit/services/test_signal_tracker_load_signal.py
- created: tests/unit/services/test_signal_tracker_backfill_fast_path.py
- created: tests/unit/services/test_intelligence_pipeline_publisher_normalization.py
- created: tests/unit/services/test_signal_replay_auditor.py
- created: tests/unit/services/test_bar_replay_provider.py
- created: tests/unit/services/test_lifecycle_tracker_d02.py
- created: tests/unit/services/test_signal_tracker_no_db_writes.py
- modified: services/signal_replay_auditor_agent.py (outcome .value fix + bars_in_trade tracking)
