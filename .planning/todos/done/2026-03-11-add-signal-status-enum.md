# Add SignalStatus Enum — Replace Raw String Literals

**Created:** 2026-03-11
**Updated:** 2026-03-19
**Priority:** High
**Effort:** Small (1–2h)
**Source:** CONCERNS.md audit → expanded in Phase 39 DB institutional audit (added `expired` status, DB CHECK constraint, dependency note)

## Problem

Signal status is represented as raw string literals spread across 5+ files with no central definition:

- `src/intelligence/trading/signal_ledger.py` — `status: str = "pending"`, `_SELECT_ACTIVE_SQL` hardcodes `('pending','active','regime_suppressed')`
- `src/intelligence/trading/lifecycle_tracker.py` — `if status == "pending"` comparisons
- `services/signal_generator_service.py` — `"pending" if ... else "regime_suppressed"`
- `services/signal_lifecycle_service.py` — 4+ status comparisons
- `src/api/routes/signals.py` — `_TERMINAL_STATUSES = frozenset({"pending", "active"})`, `"regime_suppressed"` literal in summary loop

**Valid statuses (all 4):** `"pending"`, `"active"`, `"regime_suppressed"`, `"expired"`

> Note: `"expired"` was added in Phase 23 when 1.8M old pending signals were bulk-expired. The original todo only listed 3 statuses — this is now stale.

**Risks:**
- Typo in any status string is a silent bug (comparison fails, signal quietly skipped)
- Adding a new status requires a grep hunt across all 5 files
- No IDE autocomplete, no validation
- DB has no CHECK constraint — bad status values can be written silently

## Fix

1. Create `src/intelligence/trading/signal_status.py`:
   ```python
   from enum import Enum

   class SignalStatus(str, Enum):
       PENDING = "pending"
       ACTIVE = "active"
       REGIME_SUPPRESSED = "regime_suppressed"
       EXPIRED = "expired"

   # Convenience sets (mirror DB partial index predicates)
   OPEN_STATUSES: frozenset[str] = frozenset({
       SignalStatus.PENDING, SignalStatus.ACTIVE, SignalStatus.REGIME_SUPPRESSED
   })
   TERMINAL_STATUSES: frozenset[str] = frozenset({
       SignalStatus.EXPIRED
   })
   ```
   Use `str, Enum` mixin so asyncpg accepts values directly without `.value`.

2. Update all 5 files to use `SignalStatus.PENDING` (comparisons) and `SignalStatus.PENDING.value` for explicit SQL params where needed.

3. Replace `_TERMINAL_STATUSES = frozenset({"pending", "active"})` in `signals.py` with import from `signal_status.py`.

4. Add DB CHECK constraint in migration (Phase 39 DB hardening migration):
   ```sql
   ALTER TABLE signal_ledger
     ADD CONSTRAINT chk_signal_ledger_status
     CHECK (status IN ('pending','active','regime_suppressed','expired'));
   ```

5. Update all unit tests to use enum values.

## Dependency

Phase 39 DB hardening migration adds the CHECK constraint. Python enum migration should happen in the same phase or immediately after — they are independent (Python enum is backward-compatible, CHECK constraint only needs consistent values).

## Notes

- `_SELECT_ACTIVE_SQL` SQL literal `('pending','active','regime_suppressed')` cannot use enum directly — keep as `.value` joined string or hardcoded (it's inside a SQL string constant).
- `signal_ledger.py` INSERT SQL uses positional `$N` params — pass `.value` there.
- The partial index `idx_ledger_open_signals` predicate `WHERE status IN ('pending','active','regime_suppressed')` is a SQL string — does not need code changes.
