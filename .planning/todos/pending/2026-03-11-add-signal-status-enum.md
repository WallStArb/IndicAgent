# Add SignalStatus Enum — Replace Raw String Literals

**Created:** 2026-03-11
**Priority:** High
**Effort:** Small (1–2h)
**Source:** CONCERNS.md audit

## Problem

Signal status is represented as raw string literals spread across 5 files with no central definition:

- `src/intelligence/trading/signal_ledger.py` — `status: str = "pending"`
- `src/intelligence/trading/lifecycle_tracker.py` — `if status == "pending"`
- `services/signal_generator_service.py` — `"pending" if ... else "regime_suppressed"`
- `services/signal_lifecycle_service.py` — 4 status comparisons

**Valid statuses:** `"pending"`, `"active"`, `"regime_suppressed"`

**Risks:**
- Typo in any status string is a silent bug (comparison fails, signal quietly skipped)
- Adding a 4th status requires touching all 5 files
- No IDE autocomplete, no validation

## Fix

1. Create `src/intelligence/trading/signal_status.py`:
   ```python
   from enum import Enum

   class SignalStatus(Enum):
       PENDING = "pending"
       ACTIVE = "active"
       REGIME_SUPPRESSED = "regime_suppressed"
   ```
2. Update all 5 files to use `SignalStatus.PENDING.value` for DB writes, `SignalStatus.PENDING` for comparisons
3. Add DB CHECK constraint in a new migration: `CHECK (status IN ('pending','active','regime_suppressed'))`
4. Update tests to use enum values

## Notes

- Keep `.value` for DB writes (asyncpg expects strings, not enum objects)
- `signal_ledger.py` INSERT SQL uses positional `$N` params — pass `.value` there
