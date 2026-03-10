---
phase: 12-signal-integrity
plan: "03"
subsystem: signal-aggregation
tags: [regime-gating, shadow-signals, slow-clock, signal-integrity]
dependency_graph:
  requires: [12-01, 12-02]
  provides: [shadow-signal-output, regime-suppressed-status, slow-clock-gate]
  affects: [signal_generator_service, aggregator, signal_ledger]
tech_stack:
  added: []
  patterns: [shadow-signal-pattern, slow-clock-cascade, attribute-introspection]
key_files:
  created: []
  modified:
    - src/intelligence/trading/aggregator.py
    - services/signal_generator_service.py
    - src/intelligence/trading/signal_ledger.py
    - tests/unit/intelligence/test_aggregator.py
decisions:
  - "regime_data= parameter (higher-TF) drives regime gate; features= (same-TF) unchanged for CIS"
  - "Shadow signals persist to signal_ledger with status='regime_suppressed' for observability"
  - "regime_data=None skips gate entirely — no suppression on absent authority-TF data"
  - "_regime_cache uses getattr guard for backward compat with test helpers using __new__"
metrics:
  duration: "~20 minutes"
  tasks_completed: 2
  files_modified: 4
  tests_added: 0
  tests_passing: 1112
  completed_date: "2026-03-04"
---

# Phase 12 Plan 03: Regime Gate Refactor — Shadow Signals and Slow-Clock Cascade

Slow-clock regime gating with shadow signal output: suppressed signals persist to all_ranked and signal_ledger rather than being silently dropped. The aggregator replaces the name-based REGIME_ELIGIBILITY dict with attribute introspection (_REGIME_MAP + regime_type attribute), and signal_generator_service adds a _regime_cache to provide higher-TF HMM data for gating.

## What Was Built

### Task 1: aggregator.py — Shadow signal gate

Replaced the opaque `REGIME_ELIGIBILITY` dict (name-based lookup) with:

- `_REGIME_MAP: dict[str, list[int]]` — maps `regime_type` attribute value to allowed HMM regime integers
- `_regime_gate_signals(signals, regime_data)` — tags each signal in-place with `regime_eligible` and `suppression_reason`
- `aggregate(..., regime_data: dict | None = None)` — new parameter for higher-TF regime data
- Shadow signals (regime_eligible=False) appear in `all_ranked` but are excluded from `active` selection
- `_REGIME_PROB_MIN = 0.60` (raised from 0.55), `_REGIME_DUR_MIN = 5` (raised from 3)
- `regime_data=None` → gate skipped entirely (no suppression on absent data)

Gate priority order: prob check → duration check → type check. `features=` is unchanged (still used by CIS scorer only).

### Task 2: signal_generator_service.py + signal_ledger.py — Regime cache and ledger wiring

- `_REGIME_AUTHORITY_TF` constant: maps each TF to its higher-TF authority (`"1m" → "5m"`, etc.)
- `self._regime_cache: dict[str, dict[str, dict]] = defaultdict(dict)` — caches HMM regime data per (symbol, tf)
- `_process_single_message()`: updates cache on every IntelligenceEvent arrival if `event.smc.hmm_regime is not None`
- `_run_setup_plugins()`: tags each signal dict with `regime_type = getattr(plugin, "regime_type", "any")`
- `_process_bar()`: looks up authority TF → passes `regime_data` to `aggregate()`
- `build_ledger_entries()`: writes `status="regime_suppressed"` for ineligible signals; `was_selected=False` always for suppressed
- `signal_ledger._SELECT_ACTIVE_SQL`: added `'regime_suppressed'` to status IN clause

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] Test infrastructure requires getattr guard**
- **Found during:** Task 2
- **Issue:** `test_process_message_accesses_typed_attributes` constructs `SignalGeneratorService.__new__` without calling `__init__`, so `_regime_cache` attribute doesn't exist. The cache update code in `_process_single_message()` would raise `AttributeError`.
- **Fix:** Used `getattr(self, "_regime_cache", None)` with a `None` guard before accessing the cache. Functionally identical in production (cache always initialized via `__init__`); handles test construction pattern safely.
- **Files modified:** `services/signal_generator_service.py`
- **Commit:** 2cf3ec0

**2. [Rule 1 - Test update] TestRegimeEligibilityFilter adapted to new API**
- **Found during:** Task 1
- **Issue:** `TestRegimeEligibilityFilter` tests used `features=_regime_features(...)` for regime gating (old API). New API routes regime gating through `regime_data=` only. Tests also asserted `num_signals_fired == 0` for cases that now produce shadow signals instead.
- **Fix:** Updated all `features=` calls to `regime_data=`, added `regime_type` field to signal dicts in tests, adjusted `test_gate_bypassed_when_regime_prob_low` and `test_gate_bypassed_when_regime_duration_short` to verify shadow signal presence instead of num_signals_fired == 1 (because prob/duration checks DO suppress, just differently from the old drop behavior).
- **Files modified:** `tests/unit/intelligence/test_aggregator.py`
- **Commit:** 7d2de10

## Test Results

| Suite | Tests | Result |
|-------|-------|--------|
| test_aggregator.py (all) | 40 | PASSED |
| test_signal_ledger.py (all) | 14 | PASSED |
| test_i7_registration.py | 1 | PASSED |
| Full unit suite | 1112 | PASSED |

## Self-Check: PASSED

- aggregator.py: FOUND
- signal_generator_service.py: FOUND
- signal_ledger.py: FOUND
- 12-03-SUMMARY.md: FOUND
- Commit 7d2de10 (Task 1): FOUND
- Commit 2cf3ec0 (Task 2): FOUND
