# Signal & Lifecycle Architecture Review
Date: 2026-06-02
Lens: Renaissance Technologies — correctness, data integrity, low-latency alpha

## Goal Context
The signal pipeline is the alpha-generation core. Every data integrity defect here corrupts ML training labels, disables protective exits, or silently drops signals — directly undermining the fund's ability to measure and extract edge.

---

## Critical Bugs (Silent Data Corruption)

### BUG-01: Bootstrap query omits `expires_at` — TTL disabled on every restart
- **File:** `services/signal_tracker.py:898-913`
- **Impact:** All bootstrapped signals have `expires_at=None` → TTL expiry disabled → signals can run forever past their TTL. D-17 counter is permanently saturated on every restart (false positives for every bootstrapped signal).
- **Fix:** Add `sl.expires_at` to the bootstrap SELECT. One line.
- **Status:** FIXED

### BUG-02: Staleness regime drift component is permanently zero
- **File:** `services/signal_tracker.py:653-654`
- **Root cause:** `sig.get("hmm_regime")` reads from the signal dict (fire-time values). Bar events only carry OHLCV. Current regime state is never injected into the signal dict → `hmm_now == hmm_regime_at_fire` always → `regime_drift = 0.0` always → 0.6-weight component does nothing.
- **Impact:** `condition_expired` exits via regime flip are silently suppressed. ML labels for staleness exits are wrong.
- **Fix:** Subscribe to feature-enriched bar topic carrying HMM/GARCH state, OR maintain a per-symbol regime cache updated from intelligence events.
- **Status:** FIXED (per-symbol regime cache from intelligence.i7.signals)

### BUG-03: TTL fast-path fire-and-forget can ghost signal IDs
- **File:** `services/signal_tracker.py:486-534`
- **Root cause:** `asyncio.ensure_future()` is fire-and-forget. `_signal_ids.add(sid)` runs before the coroutine completes. If publish fails, signal_id is deduped forever, signal_outcomes stays `pending` forever.
- **Fix:** Use async publish with confirmation, or buffer locally before deduping.
- **Status:** FIXED

### BUG-04: `pnl_ticks` never persisted on live lifecycle path
- **File:** `services/lifecycle_writer.py:124-138`
- **Root cause:** `_EXIT_IDEMPOTENT_SQL` has 12 columns; `pnl_ticks` is absent. Lifecycle_tracker computes it correctly but lifecycle_writer drops it.
- **Impact:** `pnl_ticks` is NULL for all live signals in `signal_outcomes`.
- **Fix:** Add `pnl_ticks` to `_EXIT_IDEMPOTENT_SQL` and `_exit_to_params`.
- **Status:** FIXED

---

## Significant Concerns

### CONCERN-01: Chandelier trailing stop state evaporates on restart
- **File:** `services/signal_tracker.py:474, 637-651`
- **Root cause:** `SignalState.chandelier_state` is initialized lazily, never persisted. On restart, highest_high/lowest_low since activation are lost; stop regresses to current bar's range.
- **Fix:** Persist chandelier state into `signal_outcomes.trailing_stop_price` (JSONB column already exists). Bootstrap reads it back.
- **Status:** FIXED

### CONCERN-02: Mutable signal dicts in active index
- **File:** `services/signal_tracker.py:705, 622`
- **Root cause:** `sig["status"] = ACTIVE` and `sig["market_entry_price"] = 0` mutate the canonical dict in `_active_index`.
- **Fix:** Route all mutable state through `SignalState`. Active index dicts are read-only after ingestion.
- **Status:** DEFERRED — medium refactor, no data corruption risk

### CONCERN-03: Dual consumer groups create signal ingestion race window
- **Description:** Two separate consumer group offsets (bar consumer, signal consumer) can diverge on restart. A signal may be in neither bootstrap DB read nor signal consumer backlog.
- **Fix:** Architectural — bootstrap reconciliation pass or single-consumer fan-out.
- **Status:** DEFERRED — low probability, hard fix

### CONCERN-04: SETUP_PRIORITY completeness not validated at startup
- **File:** `src/intelligence/trading/aggregator.py:34`
- **Fix:** `assert set(SETUP_PRIORITY.keys()) == set(TIER_I7_names)` at module load.
- **Status:** FIXED

### CONCERN-05: Target list ordering assumed but not enforced
- **File:** `src/intelligence/trading/lifecycle_tracker.py:476-493`
- **Fix:** Sort targets in ascending order in `_check_active_exit` and `evaluate_market_entry` before iteration.
- **Status:** FIXED

### CONCERN-06: Backfill fast-path unconditionally labels `ttl_expired_behind`
- **File:** `services/signal_tracker.py:518`
- **Impact:** Biases ML training labels for historical backfill signals.
- **Fix:** Deferred replay evaluation using historical OHLCV.
- **Status:** DEFERRED — requires replay infrastructure

---

## Priority Execution Order
1. BUG-01 — trivial, fixes D-17 alert immediately
2. BUG-04 — trivial, restores pnl_ticks to all future exits
3. CONCERN-04 — trivial, adds safety invariant
4. CONCERN-05 — low, protects P&L label accuracy
5. BUG-03 — medium, eliminates ghost signal_ids
6. CONCERN-01 — medium, preserves trailing stop across restarts
7. BUG-02 — medium, requires regime cache architecture
8. CONCERN-02 — deferred refactor
9. CONCERN-03 — deferred architectural
10. CONCERN-06 — deferred, requires replay infrastructure
