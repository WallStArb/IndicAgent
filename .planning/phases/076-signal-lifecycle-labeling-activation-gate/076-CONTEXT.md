# Phase 76: Signal Lifecycle Labeling Fix & Activation Gate - Context

**Gathered:** 2026-04-28
**Status:** Ready for planning
**Source:** Live investigation of signal_ledger data corruption

<domain>
## Phase Boundary

Fix the data labeling bug where 2,744 signals have `activated_at IS NOT NULL` but `outcome = 'never_activated'`. Add temporal guards against impossible activations, bootstrap TTL sweep to prevent 29k pending signal accumulation causing 6-min restart cycles, backfill correction for corrupted rows, and an activation probability pre-filter to stop tracking hopeless signals.

**Does NOT include:** ML activation model (Phase 70), shadow outcome infrastructure changes, or any changes to signal generation (I7 plugins).
</domain>

<decisions>
## Implementation Decisions

### D-01: Temporal Guard in lifecycle_tracker.py (CRITICAL FIX)
- Add `bar_time >= signal_timestamp` guard in `_check_zone_activation()` — never activate a signal on a bar from before the signal was fired
- If `bar_time < signal_timestamp`, return None (no activation)
- This eliminates the 2,430 pre-fire activation cases where `activated_at < timestamp`

### D-02: TTL Outcome Fix — Check activated_at, Not Just status (CRITICAL FIX)
- In `evaluate_signal()` TTL block (line 200-223), the outcome must use `activated_at` as the source of truth, not just in-memory `status`
- When TTL fires, if the signal has `activated_at` set (either in-memory or from signal dict), the outcome should be `ttl_expired_ahead/behind`, NOT `never_activated`
- This eliminates the 314 post-fire mislabeling cases where tracker restart caused in-memory status to be PENDING despite DB having activated_at

### D-03: Bootstrap TTL Sweep (PERFORMANCE FIX)
- In `signal_tracker_compute_agent.py` `_bootstrap_active_signals()`, add a pre-filter SQL that expires signals past their TTL before loading them into memory
- SQL: `UPDATE signal_ledger SET status='expired', exit_at=NOW(), exit_reason='ttl_expired', outcome='never_activated' WHERE status='pending' AND exit_at IS NULL AND timestamp < NOW() - INTERVAL '3 days'`
- This reduces bootstrap from 29k signals to a manageable set, eliminating the 6-min restart cycle caused by OOM/timeout from processing 29k signals per bar

### D-04: Backfill Correction SQL (DATA INTEGRITY)
- One-time SQL to fix the 2,744 corrupted rows:
  - Signals with `activated_at IS NOT NULL` AND `outcome = 'never_activated'` AND `exit_reason = 'ttl_expired'`: recompute outcome based on `pnl_r` → `ttl_expired_ahead` if `mfe > 0`, else `ttl_expired_behind`
  - Signals with `activated_at < timestamp` (impossible activation): clear `activated_at`, `activation_price`, `zone_entry_pct`, `bars_to_activation` — treat as never activated
- Add DB CHECK constraint or periodic audit that flags `activated_at IS NOT NULL AND outcome = 'never_activated'` as a data quality violation

### D-05: Activation Probability Gate (EFFICIENCY)
- In `signal_tracker_compute_agent.py`, add a simple heuristic pre-filter when ingesting new signals from i7.signals
- If zone distance > 3× ATR from current close AND less than 20% of TTL bars remain, immediately publish a TTL-expired transition instead of adding to active index
- This prevents the vast majority of hopeless signals from entering the tracking pipeline
- No ML model needed — pure distance heuristic. The ML activation model (Phase 70) can refine this later

### D-06: Data Quality Audit Metric
- Add Prometheus counter `signal_tracker_labeling_violations_total` incremented when `evaluate_signal()` detects a signal with `activated_at` set but status=PENDING at TTL time
- Add periodic log warning if more than 1% of signals have labeling violations

### Claude's Discretion
- Exact placement of the activation gate heuristic (in `_ingest_signal_payload` vs `_evaluate_bar`)
- Whether to add a DB migration for a CHECK constraint or use the existing `service_auditor_agent` for periodic auditing
- Test structure and naming conventions
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Signal Lifecycle
- `src/intelligence/trading/lifecycle_tracker.py` — pure function `evaluate_signal()` that determines outcomes; BUG: TTL check at line 200 runs before activation check at line 225, and uses in-memory status which can be stale after restart
- `services/signal_tracker_compute_agent.py` — DB-ignorant lifecycle evaluation agent; BUG: bootstraps 29k signals on restart causing 6-min crash cycle; missing temporal guard
- `services/lifecycle_writer_agent.py` — persists transitions to signal_ledger via batch_execute
- `src/persistence/repository/signal_ledger_repository.py` — SignalLedgerRepository with batch_execute() for transitions
- `src/intelligence/trading/signal_outcome.py` — SignalOutcome enum (8-class taxonomy)

### Bootstrap & Restart
- `services/signal_tracker_compute_agent.py:624-723` — `_bootstrap_active_signals()` loads pending+active from DB with 3-day window; NO pre-filter on TTL-expired signals
- Tracker restarts every ~6 min (29k signals × per-bar evaluation = memory/timeout pressure)

### Data Model
- `src/persistence/repository/signal_ledger_repository.py:22-34` — SignalStatus enum (PENDING, ACTIVE, REGIME_SUPPRESSED, EXPIRED)
- `src/intelligence/trading/signal_outcome.py` — SignalOutcome enum: NEVER_ACTIVATED, STOPPED_AT_ENTRY, STOPPED_IN_TRADE, TARGET_1, TARGET_1_2, TARGET_FULL, TTL_EXPIRED_AHEAD, TTL_EXPIRED_BEHIND
- `signal_ledger` columns: `exit_at` (not exit_ts), `activated_at`, `outcome`, `exit_reason`, `pnl_r`, `mae`, `mfe`, `bars_in_trade`

### Observability
- `src/observability/metrics.py` — metric registration; label key is `agent_id` (not `agent=`)
</canonical_refs>

<specifics>
## Specific Ideas

### Bug Analysis Data (from live investigation)
- Total resolved signals: 170,924
- never_activated: 170,551 (99.78%)
- Mis-labeled (activated_at + never_activated): 2,744
  - 2,430: activated_at BEFORE signal timestamp (impossible activation from stale bars)
  - 314: activated_at >= timestamp but still got never_activated (tracker restart race)
- Current pending signals in DB: 29,221 (accumulated over 20 days)
- Current active signals: 84
- Tracker restart frequency: every ~6 minutes
- Tracker bootstrap time: ~6 seconds for 29k signals
- Outcome distribution for activated signals: 2744 never_activated, 295 ttl_expired_behind, 16 target_1, 8 target_full, 5 target_1_2

### Root Cause Chain
1. 99.78% of signals never activate (zones too far from price)
2. Signals accumulate in pending state for days
3. Tracker bootstraps ALL 29k pending signals on every restart
4. Memory pressure from 29k signals × per-bar evaluation → 6-min restart cycle
5. On restart, bars from different timestamps can activate signals impossibly (stale HTF bars in topic OR bars from restart-concurrent pipeline runs)
6. TTL check runs before activation check in evaluate_signal() — if bars_elapsed >= ttl, signal gets never_activated even if zone activation would have occurred on the same bar
7. After tracker restart, in-memory status resets to whatever DB has — if lifecycle writer hasn't persisted the activation yet, status=PENDING in DB → never_activated on next TTL expiry
</specifics>

<deferred>
## Deferred Ideas

- ML activation model (Phase 70 — binary classification "will this signal activate?")
- Shadow outcome recomputation for backfilled signals
- Changes to I7 signal generation or zone sizing
- Parallelization of signal evaluation per bar
</deferred>

---
*Phase: 076-signal-lifecycle-labeling-activation-gate*
*Context gathered: 2026-04-28 via live investigation*
