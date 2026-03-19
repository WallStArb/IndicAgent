# Add SignalOutcome Enum — Replace Raw Outcome String Literals

**Created:** 2026-03-19
**Priority:** High
**Effort:** Small (1–2h)
**Source:** Phase 39 DB institutional audit

## Problem

Signal outcome is represented as raw string literals with no central definition or DB-level enforcement. The ML model is trained on these outcome labels — a single mis-typed string corrupts training data silently.

**8 valid outcomes (from 8-class taxonomy):**
```
"never_activated"
"stopped_at_entry"
"stopped_in_trade"
"target_1"
"target_1_2"
"target_full"
"ttl_expired_ahead"
"ttl_expired_behind"
```

**Files with hardcoded outcome strings:**
- `src/intelligence/trading/signal_ledger.py` — `WIN_OUTCOMES = frozenset({"target_1", "target_1_2", "target_full"})`
- `src/intelligence/trading/lifecycle_tracker.py` — `return "target_1"`, `return "stopped_in_trade"`, etc.
- `services/signal_lifecycle_service.py` — `_classify_stop_outcome()` returns raw strings
- `src/intelligence/ml/confidence_calibrator.py` — imports `WIN_OUTCOMES` (correctly) but surrounding code uses outcome comparisons
- `src/api/routes/signals.py` — `_WIN_OUTCOMES` imported but `"regime_suppressed"` check adjacent

**DB state:** No CHECK constraint — any string can be written to `outcome` column with no error.

**Risks:**
- Typo (`"target1"` vs `"target_1"`) is undetected, silently excluded from win-rate computation
- Adding a 9th outcome class requires grep hunt
- ML training dataset can contain corrupted labels with no DB-level catch

## Fix

1. Create `src/intelligence/trading/signal_outcome.py`:
   ```python
   from enum import Enum

   class SignalOutcome(str, Enum):
       NEVER_ACTIVATED = "never_activated"
       STOPPED_AT_ENTRY = "stopped_at_entry"
       STOPPED_IN_TRADE = "stopped_in_trade"
       TARGET_1 = "target_1"
       TARGET_1_2 = "target_1_2"
       TARGET_FULL = "target_full"
       TTL_EXPIRED_AHEAD = "ttl_expired_ahead"
       TTL_EXPIRED_BEHIND = "ttl_expired_behind"

   # Outcome taxonomy groupings — authoritative, single source of truth
   WIN_OUTCOMES: frozenset[str] = frozenset({
       SignalOutcome.TARGET_1,
       SignalOutcome.TARGET_1_2,
       SignalOutcome.TARGET_FULL,
   })
   STOP_OUTCOMES: frozenset[str] = frozenset({
       SignalOutcome.STOPPED_AT_ENTRY,
       SignalOutcome.STOPPED_IN_TRADE,
   })
   TTL_OUTCOMES: frozenset[str] = frozenset({
       SignalOutcome.TTL_EXPIRED_AHEAD,
       SignalOutcome.TTL_EXPIRED_BEHIND,
   })
   ```
   Use `str, Enum` mixin so asyncpg accepts values directly.

2. Move `WIN_OUTCOMES` from `signal_ledger.py` to `signal_outcome.py` and update all imports:
   - `src/intelligence/trading/signal_ledger.py` — re-export from new module
   - `src/intelligence/ml/confidence_calibrator.py` — update import path
   - `src/intelligence/weight_updater.py` — update import path
   - `production/scripts/promote_shadow.py` — update import path
   - `src/api/routes/signals.py` — update import path

3. Update `lifecycle_tracker.py` and `signal_lifecycle_service.py` to return `SignalOutcome.*` values.

4. Add DB CHECK constraint in migration (same Phase 39 DB hardening migration as status enum):
   ```sql
   ALTER TABLE signal_ledger
     ADD CONSTRAINT chk_signal_ledger_outcome
     CHECK (outcome IS NULL OR outcome IN (
       'never_activated','stopped_at_entry','stopped_in_trade',
       'target_1','target_1_2','target_full',
       'ttl_expired_ahead','ttl_expired_behind'
     ));
   ```
   Note: `outcome IS NULL` required — outcome is NULL until signal exits.

5. Update all unit tests to use enum values.

## Dependency

Depends on: Phase 39 DB hardening migration (adds the CHECK constraint).
Related: `2026-03-11-add-signal-status-enum.md` — ship both in the same PR for consistency.
