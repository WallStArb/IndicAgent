---
phase: 081-signal-lifecycle-hardening
plan: "03"
subsystem: signal-tracker
tags:
  - signal-lifecycle
  - refactor
  - compute-agent
  - metrics
dependency_graph:
  requires:
    - 081-01  # migration adding is_backfill, ttl_bars, signal_schema_version columns
    - 081-02  # TF_SECONDS in stream_keys.py
  provides:
    - _load_signal canonical intake (single point of truth for signal normalization)
    - backfill fast-path (backfill signals past TTL never enter active index)
    - zero-DB-write ComputeAgent contract restored
    - D-02 violation counter as assertion (not workaround)
  affects:
    - services/signal_tracker_compute_agent.py
    - src/intelligence/trading/lifecycle_tracker.py
    - src/observability/metrics.py
tech_stack:
  added: []
  patterns:
    - canonical intake function (_load_signal) as single normalization point
    - backfill fast-path (ingest-time TTL check for is_backfill=True signals)
    - three-branch decision tree in _ingest_signal (dedup / fast-path / normal)
key_files:
  created: []
  modified:
    - src/observability/metrics.py
    - services/signal_tracker_compute_agent.py
    - src/intelligence/trading/lifecycle_tracker.py
decisions:
  - Bootstrap SELECT uses WHERE exit_at IS NULL (no status filter) — _load_signal normalizes status downstream
  - _ingest_signal routes bootstrap rows directly to _add_to_active_index (bypass fast-path for already-active DB signals)
  - _publish_ttl_expired_transition_sync uses asyncio.ensure_future for async publish from sync context
  - D-02 violation counter (_LABELING_VIOLATIONS) retained as assertion; was_activated no longer includes PENDING+activated_at
metrics:
  duration: "33 minutes"
  completed_date: "2026-05-08T18:24:00Z"
  tasks_completed: 5
  files_modified: 3
---

# Phase 81 Plan 03: Signal Tracker Canonical Intake + Backfill Fast-Path Summary

**One-liner:** Unified all signal intake through `_load_signal()`, added backfill TTL fast-path, deleted D-03 DB sweep and D-05 activation gate, restored tracker to zero-DB-write ComputeAgent contract.

## What Was Built

### Task 1: New Prometheus Counters (metrics.py)

Two new counters registered in `src/observability/metrics.py`:

- `SIGNAL_TRACKER_INVALID_SIGNAL_TOTAL` — labeled by `reason`; incremented by `_load_signal()` on every reject
- `SIGNAL_TRACKER_BACKFILL_FAST_PATH_TOTAL` — labeled by `symbol`, `timeframe`; incremented when a backfill signal's TTL is already elapsed at ingest

### Task 2: `_load_signal()` Canonical Intake

Added `_load_signal(self, raw: dict) -> dict | None` to `SignalTrackerComputeAgent`.

Hard rejects (return None + counter):
- `missing_signal_id`: `signal_id` absent
- `missing_symbol_or_timeframe`: `symbol` or `timeframe`/`tf` empty
- `empty_timestamp`: `timestamp` is None or `""`
- `malformed_timestamp`: string that fails `fromisoformat`
- `invalid_timestamp_type`: not a `datetime` after parse
- `missing_entry_or_stop`: `entry_price` or `stop_loss` absent

Returns 17-field canonical dict:
`signal_id`, `symbol`, `timeframe`, `timestamp` (UTC-aware datetime),
`entry_price`, `stop_loss`, `is_backfill`, `ttl_bars`, `signal_schema_version`,
`status`, `direction`, `targets`, `entry_zone_low`, `entry_zone_high`,
`market_entry_price`, `activated_at`, `garch_sigma_at_fire`, `hmm_regime_at_fire`

### Task 3a: D-03 Sweep + D-05 Gate Deleted

**D-03 sweep — exact identifiers found in read-first:**
- Method: `_bootstrap_active_signals`
- Location: within `try` block, before the SELECT retry loop
- SQL: `UPDATE signal_ledger SET status = 'expired', exit_at = NOW(), exit_reason = 'ttl_expired', outcome = 'never_activated' WHERE status = 'pending' AND exit_at IS NULL AND timestamp < NOW() - INTERVAL '4 hours'`
- Comment block: `# D-03: Pre-filter to expire signals past reasonable TTL before bootstrap`
- Log line: `self.logger.info("bootstrap_ttl_sweep_complete")`
- Deleted: entire UPDATE block + comment + log line (18 lines)

**D-05 gate — exact identifiers found in read-first:**
- Method: `_ingest_signal_payload` (now renamed `_ingest_signal`)
- Variables: `zone_distance_risk`, `ttl_remaining_pct`, `zone_distance`, `ttl_val`, `bars_val`, `zone_low_val`, `zone_high_val`
- Gate condition: `zone_distance_risk > 3.0 and ttl_remaining_pct < 0.20`
- Log line: `"activation_gate_filtered"`
- Comment: `# D-05: Activation probability gate -- skip hopeless signals`
- Deleted: entire 29-line conditional block

### Task 3b: Kafka + Bootstrap Wired Through `_load_signal`

**`_ingest_i7_payload` refactored:**
- Old: built `sig_dict` with `symbol`/`timeframe` normalization, called `_ingest_signal_payload`
- New: builds `raw` dict filling `symbol`/`timeframe`/`timestamp` from envelope, calls `_load_signal(raw)` → `_ingest_signal(canonical)` on success

**`_ingest_signal` (renamed from `_ingest_signal_payload`) — three-branch decision tree:**
1. **Dedup**: `sid in self._signal_ids` → return
2. **Backfill fast-path**: `is_backfill=True AND bars_elapsed >= ttl_bars` → `_publish_ttl_expired_transition_sync` + increment counter + skip active index
3. **Normal path**: `_add_to_active_index` + add to `_signal_ids`

**`_add_to_active_index`** (extracted helper): canonical index insert + point value lookup + MAE/MFE init + `activated_at` restore.

**`_publish_ttl_expired_transition_sync`**: schedules `LifecycleTransition(EXIT)` via `asyncio.ensure_future` with `outcome='ttl_expired_behind'`, `exit_reason='ttl_expired'`, `bars_in_trade=ttl_bars`.

**Bootstrap SELECT refactored:**
- Old columns: `signal_id, timestamp, symbol, timeframe, status, direction, entry_price, stop_loss, targets, confidence, entry_zone_low, entry_zone_high, activated_at, market_entry_price`
- New columns adds: `ttl_bars, signal_schema_version, garch_sigma_at_fire, hmm_regime_at_fire, is_backfill`
- Old WHERE: `status IN ('pending', 'active') AND exit_at IS NULL AND timestamp > NOW() - INTERVAL '3 days'`
- New WHERE: `exit_at IS NULL` (no status filter — `_load_signal` normalizes)
- Each row: `dict(row)` → `_load_signal()` → `_add_to_active_index()` (bypass `_ingest_signal` dedup/fast-path for already-active DB signals)

### Task 4: D-02 Compensating Logic Removed from `lifecycle_tracker.py`

**Old code (D-02 workaround in `evaluate_signal()` TTL block):**
```python
# D-02: Check activated_at as source of truth...
activated_at = signal.get("activated_at")
was_activated = status == SignalStatus.ACTIVE or (
    activated_at is not None and status == SignalStatus.PENDING
)
```

**New code:**
```python
activated_at = signal.get("activated_at")
# Phase 81: D-02 violation should now be impossible. Counter retained as assertion.
if activated_at is not None and status == SignalStatus.PENDING:
    _LABELING_VIOLATIONS.inc()
was_activated = status == SignalStatus.ACTIVE
```

- Auto-correction removed: `was_activated` no longer treats PENDING+activated_at as ACTIVE
- `_LABELING_VIOLATIONS` counter retained (`signal_tracker_labeling_violations_total`) as operator-visible assertion
- No "compensating" or "workaround" comments remain

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

Files verified to exist:
- `src/observability/metrics.py` — FOUND, counters registered
- `services/signal_tracker_compute_agent.py` — FOUND, compiles clean
- `src/intelligence/trading/lifecycle_tracker.py` — FOUND, compiles clean

Commits verified:
- `573690c9` — metrics counters registered
- `bb255b0d` — `_load_signal` implemented
- `1f0b51b8` — D-03 + D-05 deleted
- `e0aa0aab` — Kafka + bootstrap wired; backfill fast-path live
- `f52f92b1` — D-02 compensating logic removed
