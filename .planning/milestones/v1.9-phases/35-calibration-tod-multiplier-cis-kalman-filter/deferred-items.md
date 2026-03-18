
## Pre-existing Test Failure (out of scope for 35-01)

**File:** `tests/unit/api/test_signals_route.py::TestGetSignals::test_get_signals_base_symbol_resolved`
**Issue:** Test asserts `ESH6` but system now resolves ES to `ESM6` — contract quarter rolled from H to M
**Root cause:** Phase 38 contracts.py `derive_roll_chain()` returns M6 as current front month; test was written with H6 hardcoded
**Confirmed pre-existing:** Fails identically on HEAD before Phase 35 changes (verified with git stash)
**Owner:** Phase 38 cleanup or standalone test fix

## Pre-existing Ruff Issues in signal_generator_service.py (out of scope for 35-02)

**F401:** `src.config.settings.get_active_contracts` imported but unused — present before Phase 35 changes
**E501:** Line too long at line ~790 — present before Phase 35 changes
**Confirmed pre-existing:** Both errors exist identically on HEAD before Phase 35-02 changes (verified with git stash)
**Owner:** Standalone cleanup task

## Pre-existing Test Failure #2 (out of scope for 35-01)

**File:** `tests/unit/config/test_settings.py::TestHelperFunctions::test_get_active_contracts`
**Confirmed pre-existing:** Fails identically before Phase 35 changes (verified with git stash)
**Owner:** Phase 38 / settings.py follow-up
