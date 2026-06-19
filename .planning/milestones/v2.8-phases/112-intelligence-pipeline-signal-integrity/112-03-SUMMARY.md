---
phase: 112-intelligence-pipeline-signal-integrity
plan: "03"
subsystem: signal-lifecycle
tags: [canonical-immutability, backfill-routing, mae-mfe-bootstrap, regime-cache-bootstrap, earliest-offset]
dependency_graph:
  requires: [PIPE-INT-01, PIPE-INT-02]
  provides: [PIPE-INT-03]
  affects: [signal_tracker, lifecycle_writer, signal_ledger, signal_outcomes]
tech_stack:
  added: []
  patterns: [immutable-canonical-dicts, state-object-pattern, periodic-persist-trigger, bootstrap-seed]
key_files:
  created:
    - tests/unit/services/test_signal_tracker_immutability.py
  modified:
    - services/signal_tracker.py
    - tests/unit/services/test_signal_tracker_backfill_fast_path.py
    - tests/unit/services/test_signal_tracker_bootstrap.py
decisions:
  - "status and market_entry_price moved to SignalState; canonical dicts in _active_index are read-only after ingestion — sig_with_extras is the single injection point where state fields enter evaluation without writing back to canonical"
  - "Backfill signals with elapsed TTL route to dedup-only — no EXIT published. SignalReplayAuditor owns bar-by-bar evaluation. SIGNAL_TRACKER_BACKFILL_ROUTED_TO_REPLAY_TOTAL counter added."
  - "Both consumers switched to auto_offset_reset=earliest. Safety net: _bootstrap_active_signals() populates _signal_ids BEFORE consumer start in _setup(), so replay short-circuits on all known active signals via dedup check."
  - "MAE_MFE_UPDATE payload: signal_id, mae, mfe — verified against SignalLedgerRepository.batch_execute('mae_mfe_update') handler lines ~797-799"
  - "lifecycle_writer.py already wired — all non-exit transitions route to self._repo.batch_execute(ttype, items) with no allowlist gap; no code change needed"
  - "Regime cache bootstrap uses last-writer-wins across signals sharing (symbol, tf); self-corrects on first live i7.signals message"
metrics:
  duration_minutes: 7
  completed_date: "2026-06-02"
  tasks_completed: 3
  files_modified: 3
  files_created: 1
---

# Phase 112 Plan 03: Signal Lifecycle Forensic Correctness Summary

Five lifecycle fixes making signal provenance auditable and restart-safe: immutable canonical dicts, backfill routing, MAE/MFE bootstrap+persistence, regime-cache bootstrap, and earliest offset.

## One-Liner

Immutable canonical dicts via SignalState fields, backfill signals routed to dedup-only with counter, MAE/MFE bootstrapped from signal_outcomes and persisted every 10 active bars past threshold, regime cache seeded from fire-time data, both consumers on earliest offset.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 3-1 | Move status+market_entry_price onto SignalState; immutability test | 69c68253 | signal_tracker.py, test_signal_tracker_immutability.py |
| 3-2 | Backfill routing + earliest offset (1-H, 2-F) | 925fe745 | signal_tracker.py, test_signal_tracker_backfill_fast_path.py |
| 3-3 | MAE/MFE bootstrap + publish trigger + regime cache bootstrap (1-I, 1-J) | c4c54834 | signal_tracker.py, test_signal_tracker_bootstrap.py |

## Task 3-1: Canonical Immutability (CONCERN-02)

### SignalState Fields Added

Two fields added to `SignalState`:
- `status: str = "pending"` — authoritative mutable lifecycle status
- `market_entry_price: float = 0.0` — cleared to 0.0 via state on market resolution

### Migration Pattern

`_add_to_active_index` constructs `SignalState(status=..., market_entry_price=...)` from the canonical dict at ingestion time. The canonical dict is never touched again.

`_evaluate_bar` builds `sig_with_extras = {**sig, "status": state.status, "market_entry_price": state.market_entry_price, ...}` — this is the single injection point where mutable state enters the evaluation dict WITHOUT writing back to canonical.

Mutations removed from `_evaluate_bar`:
- `sig["status"] = SignalStatus.ACTIVE` → `state.status = SignalStatus.ACTIVE`
- `sig["market_entry_price"] = 0` → `state.market_entry_price = 0.0`

### Immutability Test

`tests/unit/services/test_signal_tracker_immutability.py` — 4 tests (Gate 1-G):
1. Pending signal canonical dict byte-identical before/after `_evaluate_bar`
2. Nested sub-dict (`trailing_stop_price`) not mutated even with ACTIVE signal
3. market_entry_price clearance goes to state, not canonical
4. status activation goes to state, not canonical

All tests verify both direct top-level key mutations AND nested dict mutations using JSON snapshots.

## Task 3-2: Backfill Routing + Earliest Offset

### Backfill Routing (1-H / D-09)

In `_ingest_signal`, at the `now_utc >= expires_at` (TTL-elapsed) branch:

**New path for `is_backfill=True`:**
```
→ self._signal_ids.add(sid)  # dedup only
→ SIGNAL_TRACKER_BACKFILL_ROUTED_TO_REPLAY_TOTAL.add(1, {"symbol": symbol})
→ return early  # no EXIT published, no _add_to_active_index
```

**Non-backfill path:** unchanged — still publishes TTL-expired EXIT via `_publish_ttl_expired_transition`.

`SIGNAL_TRACKER_BACKFILL_ROUTED_TO_REPLAY_TOTAL` counter created via `counter()` from `src/observability/metrics.py` at module level, matching the existing pattern of `SIGNAL_TRACKER_BACKFILL_FAST_PATH_TOTAL`.

### Earliest Offset (2-F / D-10)

Both consumer constructions changed from `auto_offset_reset="latest"` to `auto_offset_reset="earliest"`.

**Dedup ordering safety**: `_bootstrap_active_signals()` is called in `_setup()` BEFORE either consumer is started. The `_signal_ids` set is fully populated with all active signals from DB before replay begins. Any re-consumed known signal hits `if sid in self._signal_ids: return` and is a no-op.

### Test Updates

`test_signal_tracker_backfill_fast_path.py` updated:
- `test_backfill_fast_path_expired` → renamed `test_backfill_routed_to_replay` — verifies no EXIT published, counter incremented
- Added `test_non_backfill_fast_path_still_publishes_exit` — confirms non-backfill TTL-elapsed path unchanged
- `test_backfill_fast_path_publish_failure_does_not_dedup` — updated to use `is_backfill=False` (tests non-backfill publish failure)

## Task 3-3: MAE/MFE Bootstrap + Publish Trigger + Regime Cache Bootstrap

### MAE/MFE Bootstrap (1-I / D-18)

Bootstrap SELECT extended with `sl.mae` and `sl.mfe` — these are exposed by `signal_ledger_full` via LEFT JOIN to `signal_outcomes`.

`_add_to_active_index` now constructs `SignalState(mae=float(canonical.get("mae") or 0.0), mfe=float(canonical.get("mfe") or 0.0))`. Live signals (not from bootstrap) start at 0.0 which is the correct default.

### MAE/MFE Publish Trigger (1-I / D-18)

`SignalState.active_bar_count: int = 0` — incremented only when signal is ACTIVE and bar has real price range (`high != low`).

In `_evaluate_bar`, after existing MAE/MFE update (`_update_mae_mfe`), publish `MAE_MFE_UPDATE` when:
```python
is_active_bar and state.active_bar_count > 0 and state.active_bar_count % 10 == 0 and (abs(state.mae) > 0.05 or abs(state.mfe) > 0.05)
```

`_publish_mae_mfe_update()` method publishes `LifecycleTransition(TransitionType.MAE_MFE_UPDATE)` with payload `{"signal_id": sid, "mae": state.mae, "mfe": state.mfe}`.

**Payload shape verification**: Read `SignalLedgerRepository.batch_execute("mae_mfe_update")` at lines ~797-799 of `signal_ledger_repository.py`. Handler extracts exactly `signal_id`, `mae`, `mfe`:
```python
params = [(d["signal_id"], d.get("mae"), d.get("mfe")) for d in items]
```
Payload matches handler exactly. A comment in `_publish_mae_mfe_update()` cites this as authoritative source.

### Lifecycle Writer Already Wired

`lifecycle_writer.py:_flush_batch()` routes all non-exit transitions via `self._repo.batch_execute(ttype, items)` — no allowlist, all `TransitionType` values pass through. `mae_mfe_update` already present in `SignalLedgerRepository.batch_execute()`. No code change needed. Documented as "already wired."

### Regime Cache Bootstrap (1-J / D-19)

After the bootstrap loop, seeds `_regime_cache[(symbol, tf)]` for each signal that has `hmm_regime_at_fire` or `garch_sigma_at_fire`. Uses same dict shape as the live update site (`_ingest_i7_payload`):
```python
self._regime_cache[cache_key] = {"hmm_regime": hmm_at_fire, "garch_sigma": garch_at_fire}
```

Last-writer-wins for signals sharing a `(symbol, tf)`. Collision count logged in `bootstrap_complete`. Self-corrects on first live `i7.signals` message.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] test_signal_tracker_backfill_fast_path.py expected old backfill behavior**

- **Found during:** Task 3-2 — test run after implementing backfill routing
- **Issue:** `test_backfill_fast_path_expired` expected `_publish_ttl_expired_transition` to be called for `is_backfill=True` signals. New behavior: backfill + elapsed TTL routes to dedup-only, never publishes EXIT.
- **Fix:** Rewrote tests to verify new routing: `test_backfill_routed_to_replay` checks no EXIT published + counter incremented; added `test_non_backfill_fast_path_still_publishes_exit` for non-backfill path; updated publish-failure test to use `is_backfill=False`.
- **Files modified:** `tests/unit/services/test_signal_tracker_backfill_fast_path.py`
- **Commit:** 925fe745

**2. [Rule 1 - Bug] test_signal_tracker_bootstrap.py missing _regime_cache in _make_agent()**

- **Found during:** Task 3-3 — bootstrap tests failing after adding regime cache bootstrap
- **Issue:** `_make_agent()` uses `__new__` to bypass `__init__`. Bootstrap method now accesses `self._regime_cache`. Tests failed with `AttributeError: 'SignalTracker' object has no attribute '_regime_cache'`.
- **Fix:** Added `agent._regime_cache = {}` to `_make_agent()` factory in bootstrap tests.
- **Files modified:** `tests/unit/services/test_signal_tracker_bootstrap.py`
- **Commit:** c4c54834

## Verification Results

Gates passed:
- Gate 1-G: canonical dict byte-identical before/after `_evaluate_bar` — 4 unit tests pass including nested key check
- 1-H: `SIGNAL_TRACKER_BACKFILL_ROUTED_TO_REPLAY_TOTAL` counter added; backfill returns before EXIT publish and before `_add_to_active_index`; non-backfill path still builds `outcome="ttl_expired_behind"`
- 1-I: bootstrap SELECT includes mae/mfe; state.mae/state.mfe initialized from canonical; active_bar_count incremented; `% 10` trigger with abs threshold
- 1-J: `_regime_cache[(symbol, tf)]` seeded from hmm_regime_at_fire/garch_sigma_at_fire during bootstrap loop
- 2-F: both consumers `auto_offset_reset="earliest"`; bootstrap ordering documented in code comments
- lifecycle_writer.py `mae_mfe_update` already wired via `batch_execute` delegation
- 4090 unit tests pass, 31 skipped

## Self-Check: PASSED
