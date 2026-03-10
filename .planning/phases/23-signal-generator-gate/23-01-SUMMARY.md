---
phase: 23-signal-generator-gate
plan: 01
subsystem: testing
tags: [signal-generator, tdd, gate, cooldown, direction-flip]

# Dependency graph
requires: []
provides:
  - "Failing TDD stubs for 5 signal gate behaviors in test_signal_generator_service.py"
  - "Codified behavioral contract for _check_gate() before implementation"
affects:
  - "23-02-PLAN.md — GREEN implementation must satisfy these test contracts"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "__new__ bypass pattern: SignalGeneratorService.__new__(SignalGeneratorService) with manual _signal_gate = {} for isolated unit tests"
    - "TDD RED stub pattern: stubs call non-existent method to fail with AttributeError — not pytest.raises, just AttributeError on call"

key-files:
  created: []
  modified:
    - tests/unit/service_tests/test_signal_generator_service.py

key-decisions:
  - "5 gate stubs cover: first-signal allowed, cooldown suppresses within window, cooldown allows after window, flip suppressed while unresolved, flip allowed after resolution"
  - "_check_gate(symbol, tf, direction, timestamp) returns bool: True=gated/suppress, False=not gated/allow"
  - "All stubs use __new__ bypass + manual _signal_gate = {} dict seeding — consistent with existing test_process_message_accesses_typed_attributes pattern"

patterns-established:
  - "Gate test pattern: __new__ bypass + svc._signal_gate[key] = {...} dict seeding before _check_gate call"
  - "Stub RED state: AttributeError on non-existent method is acceptable RED — no pytest.raises needed"

requirements-completed:
  - gate-init
  - gate-cooldown
  - gate-flip-suppressed
  - gate-flip-allowed

# Metrics
duration: 2min
completed: 2026-03-10
---

# Phase 23 Plan 01: Signal Generator Gate - RED Stubs Summary

**5 failing TDD stubs codifying signal gate behavioral contract: first-signal allow, cooldown window, direction flip suppression and release**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-03-10T06:35:43Z
- **Completed:** 2026-03-10T06:37:30Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- Appended 5 failing gate test stubs under `# Signal gate` section in `test_signal_generator_service.py`
- All 5 stubs fail with `AttributeError: 'SignalGeneratorService' object has no attribute '_check_gate'` — correct RED state
- All 21 pre-existing tests in the file continue to pass
- Behavioral contract fully codified before implementation: `_check_gate(symbol, tf, direction, timestamp) -> bool`

## Task Commits

1. **Task 1: Write failing gate test stubs** - `3418765` (test)

## Files Created/Modified

- `tests/unit/service_tests/test_signal_generator_service.py` - Appended 5 gate test stubs under `# Signal gate` section (92 lines added)

## Decisions Made

- `_check_gate` returns `False` for "not gated / publish allowed" and `True` for "gated / suppress" — semantics match plan spec
- Cooldown test at bars_since=1 (60s delta on 1m) confirms < MIN_BARS=3 suppresses; bars_since=4 (240s delta) confirms >= MIN_BARS=3 allows
- Flip suppression test seeds `resolved=False` with 10-min gap (well past cooldown) to isolate flip logic from cooldown
- Flip resolution test seeds `resolved=True` with same 10-min gap to confirm flip is allowed after resolution

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

- RED stubs are in place — Plan 23-02 (GREEN implementation) can proceed immediately
- `_check_gate` method needs to be added to `SignalGeneratorService` with `_signal_gate: dict[tuple[str,str], dict]` initialized in `__init__`
- `MIN_BARS_BETWEEN_SIGNALS` and `TF_SECONDS` constants needed in the service module
- Lifecycle resolution listener (for setting `gate["resolved"] = True`) is separate from gate logic itself

---
*Phase: 23-signal-generator-gate*
*Completed: 2026-03-10*
