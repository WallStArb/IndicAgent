---
phase: 076-signal-lifecycle-labeling-activation-gate
reviewed: 2026-04-28T12:00:00Z
depth: standard
files_reviewed: 5
files_reviewed_list:
  - src/intelligence/trading/lifecycle_tracker.py
  - tests/unit/intelligence/test_lifecycle_tracker.py
  - services/signal_tracker_compute_agent.py
  - tests/unit/service_tests/test_signal_tracker_compute_agent.py
  - production/migrations/076_signal_ledger_lifecycle_constraints.sql
findings:
  critical: 3
  warning: 2
  info: 3
  total: 8
status: issues_found
---

# Phase 076: Code Review Report

**Reviewed:** 2026-04-28T12:00:00Z
**Depth:** standard
**Files Reviewed:** 5
**Status:** issues_found

## Summary

Reviewed Phase 076 implementation for signal lifecycle labeling and activation gate fixes. The implementation addresses critical bugs in signal outcome classification (D-01, D-02, D-03, D-05, D-06) through temporal guards, `activated_at`-based TTL resolution, bootstrap TTL sweeps, activation probability gates, and DB constraints. Code quality is generally high with good test coverage. However, **three critical issues** were found that could cause data corruption or incorrect outcomes: (1) SQL backfill assumes `exit_at IS NOT NULL` which may not hold for all 2,430 rows, (2) missing `bars_in_trade` enrichment for `chandelier_stop` exits, and (3) potential division by zero in staleness score calculation.

## Critical Issues

### CR-01: SQL Backfill Missing NULL Guard for `exit_at`

**File:** `production/migrations/076_signal_ledger_lifecycle_constraints.sql:15-22`
**Issue:** The backfill UPDATE statement for "impossible activations" checks `AND exit_at IS NOT NULL` (line 22), but this creates a logical gap. Rows where `activated_at < timestamp` AND `exit_at IS NULL` will NOT be corrected. These signals have corrupted activation data but remain unresolved, leaving inconsistent state in the ledger.

The migration comment states "clear all activation fields — treat as never activated" but the WHERE clause only processes already-resolved signals. Unresolved signals with corrupted `activated_at` remain in the system with impossible timestamps.

**Fix:**
```sql
-- Split into two UPDATEs: one for resolved, one for unresolved
-- Resolved signals (with exit_at)
UPDATE signal_ledger
SET activated_at = NULL,
    activation_price = NULL,
    zone_entry_pct = NULL,
    bars_to_activation = NULL
WHERE activated_at IS NOT NULL
  AND activated_at < timestamp
  AND exit_at IS NOT NULL;

-- Unresolved signals (without exit_at) — also clear impossible activations
UPDATE signal_ledger
SET activated_at = NULL,
    activation_price = NULL,
    zone_entry_pct = NULL,
    bars_to_activation = NULL
WHERE activated_at IS NOT NULL
  AND activated_at < timestamp
  AND exit_at IS NULL;
```

---

### CR-02: Chandelier Stop Exit Missing `bars_in_trade` Enrichment

**File:** `src/intelligence/trading/lifecycle_tracker.py:262-297`
**Issue:** When a signal exits via `chandelier_stop`, the `Transition` object is returned with `bars_in_trade=None` (line 268, 295). The caller (`SignalTrackerCompute._evaluate_bar`) enriches `bars_in_trade` via `_enrich_exit_transition` (lines 512-513 in agent), but this only happens for transitions where `transition.exit_reason` is truthy. While `chandelier_stop` has `exit_reason="chandelier_stop"`, the enrichment happens AFTER the transition is published (line 518), meaning the published `LifecycleTransition` will have `bars_in_trade=None`.

This breaks the data contract — exit transitions must include `bars_in_trade` for accurate outcome classification (e.g., `stopped_at_entry` vs `stopped_in_trade`). The migration constraint checks `outcome` values but can't validate missing metadata.

**Fix:**
Move `bars_in_trade` enrichment BEFORE `_transition_to_lifecycle()`:

```python
# In _evaluate_bar, line 502-518, reorder:
if transition.new_status == SignalStatus.ACTIVE:
    self._activated_at[sid] = bar_time
    self._mae[sid] = 0.0
    self._mfe[sid] = 0.0
    sig["status"] = SignalStatus.ACTIVE
elif transition.exit_reason:
    # Enrich BEFORE mapping to LifecycleTransition
    if transition.bars_in_trade is None:
        transition = self._enrich_exit_transition(transition, sid, bar_time, timeframe)

# Now map to LifecycleTransition (with bars_in_trade populated)
lifecycle_t = self._transition_to_lifecycle(transition, symbol, timeframe, bar_time)
await self._publish_transition(lifecycle_t)

if transition.exit_reason:
    self._remove_signal(sid, symbol, timeframe)
```

---

### CR-03: Staleness Score Division by Zero Risk

**File:** `src/intelligence/trading/lifecycle_tracker.py:116-125`
**Issue:** The staleness score calculation computes `math.log(max(sigma_ratio, 1.0)) / math.log(STALENESS_SIGMA_SCALE)`. While `sigma_ratio` is guarded (line 122), if `STALENESS_SIGMA_SCALE` were ever changed to `1.0` or below via configuration, `math.log(STALENESS_SIGMA_SCALE)` would be ≤ 0, causing division by zero or negative denominator issues. Currently hardcoded to `3.0` (safe), but the code lacks defensive checks.

More critically, if `sigma_ratio` is extremely large (e.g., 1e10), `math.log(sigma_ratio)` could overflow or produce unstable values, though Python's float handles this gracefully.

**Fix:**
Add defensive validation:
```python
# At module level, add assertion
assert STALENESS_SIGMA_SCALE > 1.0, (
    f"STALENESS_SIGMA_SCALE must be > 1.0 for log-ratio calculation; got {STALENESS_SIGMA_SCALE}"
)

# In compute_staleness_score, cap sigma_ratio before log
if (
    garch_sigma_now is not None
    and garch_sigma_at_fire is not None
    and garch_sigma_at_fire > 0
    and garch_sigma_now > 0
):
    sigma_ratio = garch_sigma_now / garch_sigma_at_fire
    # Cap ratio to prevent extreme values (e.g., 1000x = log(1000) ≈ 6.9)
    sigma_ratio = min(sigma_ratio, 1000.0)
    sigma_component = min(
        1.0, math.log(max(sigma_ratio, 1.0)) / math.log(STALENESS_SIGMA_SCALE)
    )
else:
    sigma_component = 0.0
```

## Warnings

### WR-01: Missing `point_value` Backfill in Bootstrap

**File:** `services/signal_tracker_compute_agent.py:698-714`
**Issue:** Bootstrap query (line 688-694) does NOT SELECT `point_value`, but the code attempts to restore it (lines 708-714). If `point_value` is NULL in the DB, the code falls back to `get_point_value(symbol)` setting. However, `point_value` is NOT persisted to `signal_ledger` in `SignalLedgerRepository` (only `activation_price`, `zone_entry_pct`, etc. are written). This means bootstrap will ALWAYS call `get_point_value()` for every signal, even if the value was computed at signal fire time and should be cached.

This is a performance issue (repeated lookups) but also a consistency risk — if `get_point_value()` returns a different value at bootstrap vs. signal fire (e.g., contract rollover changed point values), MAE/MFE calculations will be inconsistent.

**Fix:**
Either (1) persist `point_value` to `signal_ledger` at signal fire, or (2) document that bootstrap re-computes `point_value` and accept the inconsistency risk. Prefer (1) for data integrity.

---

### WR-02: Activation Probability Gate Uses Hardcoded Thresholds

**File:** `services/signal_tracker_compute_agent.py:311-339`
**Issue:** The activation probability gate (D-05) filters signals where `zone_distance_risk > 3.0 AND ttl_remaining_pct < 0.20`. These thresholds are hardcoded magic numbers. If these parameters are important enough to gate signals, they should be configurable via Settings with monitoring metrics to track filter rate.

Without telemetry, we can't detect if the gate is too aggressive (filtering viable signals) or too permissive (admitting hopeless signals). The gate also doesn't account for regime (e.g., mean-reversion regimes may have wider zones).

**Fix:**
Add to Settings:
```python
# In src/config/settings.py
class Settings(BaseSettings):
    activation_gate_zone_distance_risk_threshold: float = 3.0
    activation_gate_ttl_remaining_pct_threshold: float = 0.20
```

Add metric:
```python
# In SignalTrackerCompute.__init__
self._activation_gate_filtered = counter(
    "signal_tracker_activation_gate_filtered_total",
    "Signals filtered by activation probability gate",
)
self._activation_gate_filtered.inc()  # In _ingest_signal_payload
```

## Info

### IN-01: Test Coverage Gap for Temporal Guard Edge Cases

**File:** `tests/unit/intelligence/test_lifecycle_tracker.py:782-839`
**Issue:** Temporal guard tests (lines 782-839) cover basic cases (bar before/after/equal signal timestamp), but missing edge cases:
- Naive datetime without timezone info (should reject or assume UTC)
- Timestamps with different timezones (e.g., signal in UTC, bar in EST)
- Microsecond precision mismatches

The code at line 374 (`if isinstance(signal_timestamp, datetime)`) handles type checking but doesn't validate timezone awareness. Per CLAUDE.md, "all datetimes must be timezone-aware UTC."

**Fix:**
Add tests:
```python
def test_temporal_guard_rejects_naive_datetime(self):
    """Naive datetime (no timezone) should be treated as missing."""
    sig = _pending_with_zone(direction=1, zone_low=5095.0, zone_high=5102.0)
    signal_ts = datetime(2026, 4, 28, 12, 5)  # No tzinfo
    bar_ts = datetime(2026, 4, 28, 12, 6, tzinfo=UTC)
    t = evaluate_signal(sig, high=5098.0, low=5093.0, close=5096.0,
                       signal_timestamp=signal_ts, bar_time=bar_ts)
    # Should either reject (None) or assume UTC (activate) — document behavior
```

---

### IN-02: Migration Constraint Only Applies to Resolved Signals

**File:** `production/migrations/076_signal_ledger_lifecycle_constraints.sql:76-81`
**Issue:** The labeling integrity constraint (`chk_signal_ledger_labeling_integrity`) only fires when `exit_at IS NOT NULL`. This means active signals with corrupted labeling (`activated_at IS NOT NULL AND outcome = 'never_activated' AND exit_at IS NULL`) won't violate the constraint until they exit. The corruption can persist for days until TTL expires.

This is intentional per comments (line 72-74), but creates a detection lag. A monitoring query should periodically scan for this pattern on active signals.

**Fix:**
Add a monitoring query (not a constraint) to detect active corruption:
```sql
-- Run every 5 min via service auditor
SELECT signal_id, symbol, timeframe, activated_at, outcome
FROM signal_ledger
WHERE status = 'active'
  AND activated_at IS NOT NULL
  AND outcome = 'never_activated'
  AND exit_at IS NULL;
```

---

### IN-03: Inconsistent Status String Usage

**File:** Multiple files
**Issue:** Signal status strings are raw literals (`"pending"`, `"active"`, `"expired"`) instead of using `SignalStatus` enum. While `SignalStatus` is imported and used in some places (e.g., line 204 in lifecycle_tracker.py), mixed usage creates brittleness. For example, line 288 in lifecycle_tracker.py returns `f"target_{i + 1}_hit"` as a computed string instead of an enum value.

This violates CLAUDE.md guidance: "Avoid adding new status comparisons without consolidating."

**Fix:**
Consolidate all status strings to `SignalStatus` enum. Add missing statuses:
```python
# In SignalStatus enum
class SignalStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    REGIME_SUPPRESSED = "regime_suppressed"
    EXPIRED = "expired"
    TARGET_1_HIT = "target_1_hit"
    TARGET_2_HIT = "target_2_hit"
    TARGET_3_HIT = "target_3_hit"
    TARGET_4_HIT = "target_4_hit"
    TARGET_5_HIT = "target_5_hit"
```

---

_Reviewed: 2026-04-28T12:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
