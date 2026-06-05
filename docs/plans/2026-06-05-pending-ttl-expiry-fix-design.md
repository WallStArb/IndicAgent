# Pending Signal TTL Expiry Fix

**Date:** 2026-06-05
**Status:** Approved

## Problem Statement

The UX showed ~525k "active signals." The DB has ~937k pending signals with `expires_at` in the past and `exit_at IS NULL`. Two structural bugs prevent pending signals from ever expiring, causing unbounded accumulation.

**Data snapshot at diagnosis:**
```
status             | total    | exit_at IS NULL, expires_at < NOW()
-------------------+----------+-------------------------------------
pending            | 937,100  | ~937,000  (essentially all)
active             |  25,692  | ~24,000
regime_suppressed  | 1,124,591| ~1,120,000
```
Non-backfill signals alone: 702k with past `expires_at` and no `exit_at`.

---

## Root Causes

### Bug 1 — `lifecycle_tracker.py:238` (structural, ongoing)

`evaluate_signal()` hard-returns from `_check_zone_activation()` for every `PENDING` signal:

```python
if status == SignalStatus.PENDING:
    return _check_zone_activation(...)  # TTL block at line 337 unreachable
```

The TTL check (`bar_time >= expires_at`) at line 337 is structurally unreachable for pending signals. A pending signal that never touches its zone accumulates forever.

### Bug 2 — `signal_tracker.py:1153` (bootstrap path)

`_bootstrap_active_signals()` calls `_add_to_active_index()` directly:

```python
self._add_to_active_index(canonical)  # bypasses _ingest_signal() fast-path
```

`_ingest_signal()` has a correct TTL fast-path (`now_utc >= expires_at` → publish TTL exit, skip index). Bootstrap bypasses this entirely. Every service restart reloads the full 7-day pile of stale pending/suppressed signals into memory, incrementing the gauge by ~482k.

The `signal_tracker_compute_active_signals` gauge counts all signals in the in-memory active index (pending + active + regime_suppressed), not just `status='active'` signals. The dashboard labeled this "Active" — technically wrong.

---

## Design

### Fix 1 — `evaluate_signal()` pending fall-through (`lifecycle_tracker.py`)

Change the pending branch from a hard return to a conditional:

```python
# Before
if status == SignalStatus.PENDING:
    return _check_zone_activation(...)

# After
if status == SignalStatus.PENDING:
    activation = _check_zone_activation(
        sid, direction, zone_low, zone_high, high, low, bars,
        signal_timestamp=signal_timestamp, bar_time=bar_time,
    )
    if activation is not None:
        return activation
    # No activation — fall through to TTL check below
```

**Priority:** zone activation wins when both conditions are true on the same bar (correct: signal activates, then active-path TTL fires next bar if TTL also elapsed). Pending signals that exhaust TTL with no zone hit → `ttl_expired` / `never_activated`.

**Effect on `regime_suppressed`:** Already falls through to TTL (not caught by any early-return). No change needed.

### Fix 2 — Bootstrap TTL fast-path (`signal_tracker.py`)

In `_bootstrap_active_signals()`, after `_load_signal()`, apply the same routing as `_ingest_signal()` before calling `_add_to_active_index()`:

```python
canonical = self._load_signal(raw)
if canonical is None:
    continue

now_utc = datetime.now(UTC)
expires_at = canonical.get("expires_at")

if expires_at is not None and now_utc >= expires_at:
    if canonical.get("is_backfill") is True:
        # D-09: dedup-only, SignalReplayAuditor owns these
        self._signal_ids.add(canonical["signal_id"])
    else:
        # Publish TTL exit and dedup — same as live ingest fast-path
        tf_secs = TF_SECONDS.get(canonical["timeframe"], 60)
        bars_elapsed = int((now_utc - canonical["timestamp"]).total_seconds() / tf_secs)
        published = await self._publish_ttl_expired_transition(canonical, bars_elapsed)
        if published:
            self._signal_ids.add(canonical["signal_id"])
    continue

self._add_to_active_index(canonical)
self._signal_ids.add(canonical["signal_id"])
```

**Effect:** On next restart, stale pending/suppressed signals with elapsed TTL are fast-pathed out. The gauge starts near its true value. Backfill signals remain untouched (D-09 invariant preserved).

### Fix 3 — Historical data remediation (direct SQL)

Write exits for all non-backfill signals where `expires_at < NOW()` and `exit_at IS NULL`. Direct SQL update — no Kafka, no live lifecycle path. These signals have no bars to evaluate; the canonical exit data is deterministic from `expires_at`.

```sql
UPDATE signal_outcomes so
SET
    status      = 'expired',
    exit_at     = sl.expires_at,
    exit_reason = 'ttl_expired',
    outcome     = 'never_activated'
FROM signal_ledger sl
WHERE so.signal_id = sl.signal_id
  AND sl.is_backfill = false
  AND sl.expires_at < NOW()
  AND so.exit_at IS NULL
  AND so.status IN ('pending', 'active', 'regime_suppressed');
```

Backfill signals (`is_backfill = true`) are excluded — SignalReplayAuditor owns their evaluation.

**Expected rows affected:** ~702k non-backfill signals.

### Fix 4 — Dashboard label (`use-observability-stream.ts`)

Change the "Active" label to "Tracked" in the observability summary array. The gauge value is operationally correct (measures in-memory workload); the label was wrong.

```typescript
// Before
{ label: "Active",  value: activeSignals !== null ? activeSignals.toLocaleString() : "—" }

// After
{ label: "Tracked", value: activeSignals !== null ? activeSignals.toLocaleString() : "—" }
```

---

## Test Changes

### New test — pending TTL expiry (no zone hit)

In `tests/unit/intelligence/test_lifecycle_tracker.py`, add:

```python
def test_pending_expires_when_no_zone_overlap_and_ttl_elapsed():
    """Pending signal: bar_time >= expires_at, no zone hit → ttl_expired / never_activated."""
    sig = _pending_signal()
    sig["expires_at"] = _T0 + timedelta(minutes=10)
    bar_time = _T0 + timedelta(minutes=11)
    t = evaluate_signal(sig, high=5050.0, low=5040.0, close=5045.0, bar_time=bar_time)
    assert t is not None
    assert t.exit_reason == "ttl_expired"
    assert t.new_status == SignalStatus.EXPIRED
```

Bar range (5040–5050) does not overlap zone (entry ~5100). TTL elapsed. Signal should fire `never_activated`.

### Update existing comment

`test_lifecycle_tracker_d02.py` comment: "PENDING signals short-circuit to zone activation check and never reach the TTL block" — update to reflect that pending signals now fall through to TTL when zone check returns None.

---

## Invariants Preserved

- **D-09:** Backfill signals never receive fabricated EXIT from signal_tracker. Bootstrap fast-path routes them to dedup-only exactly as live ingest does.
- **D-17:** NULL `expires_at` still increments counter and skips TTL check in both paths.
- **DAG invariant 3:** Data remediation writes directly to DB via psql (one-time ops script), not through any analyzer or pipeline daemon.
- **Priority:** Zone activation wins over TTL expiry on same bar (signal activates; TTL fires next bar if still elapsed). Prevents a valid setup from being silently killed.

---

## Scope

Out of scope: splitting the gauge into per-status counters, renaming the Prometheus metric, or Grafana dashboard changes. The label fix in the TypeScript component is sufficient to eliminate the misleading "Active" display.
