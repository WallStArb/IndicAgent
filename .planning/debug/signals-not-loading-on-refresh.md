---
status: awaiting_human_verify
trigger: "Diagnose why signals don't load from the DB when the dashboard is refreshed"
created: 2026-03-12T00:00:00Z
updated: 2026-03-12T00:00:00Z
---

## Current Focus

hypothesis: Confirmed — two compounding gaps: SSE age filter is too aggressive for long-lived signals, AND the frontend has no REST call on mount to pre-populate signals from DB.
test: Code inspection of sse.py snapshot loop, _signal_entry_stale, and use-market-stream.ts mount behavior.
expecting: N/A — root cause confirmed.
next_action: Implement fix — A) add /signals/active endpoint in signals.py; B) add fetchActiveSignals in use-market-stream.ts parallel to fetchSession; C) remove dead legacy stale-filter helpers from sse.py.

## Symptoms

expected: On dashboard refresh, active/pending signals that exist in the DB should be visible immediately.
actual: Signal banners are empty after refresh — no signals appear until a new live signal fires.
errors: None (silent — no errors thrown, just empty state)
reproduction: Refresh dashboard page while signals are active.
started: After Phase 27 added _signal_entry_stale() age filter to SSE snapshot replay.

## Eliminated

- hypothesis: Signals are not persisted to DB at all
  evidence: signals.py exists with /signals/{symbol} and /signals/recent endpoints — DB persistence is working
  timestamp: 2026-03-12

- hypothesis: Frontend REST API call exists but is broken
  evidence: No fetch() call for signals at all in use-market-stream.ts — there is no signal REST call on mount
  timestamp: 2026-03-12

## Evidence

- timestamp: 2026-03-12
  checked: sse.py line 184 — last_ids initialization
  found: last_ids = {s: last_event_id or "$" for s in streams} — when there is no lastEventId query param (fresh connect), all streams are initialized to "$" (tail), NOT "0" (read-all history)
  implication: The XREAD in the live loop will only see NEW messages. The snapshot loop (lines 194-221) is the only path that replays history.

- timestamp: 2026-03-12
  checked: sse.py lines 194-221 — snapshot loop
  found: Snapshot runs when not last_event_id (i.e. fresh connect, no reconnect ID). Uses xrevrange count=2 for signal streams, then applies _signal_entry_stale() to each entry.
  implication: Snapshot IS the only mechanism for replaying signals on page refresh.

- timestamp: 2026-03-12
  checked: sse.py lines 36-50 — _signal_max_age_s()
  found: Returns 2 * TF_minutes * 60 seconds. For 1m = 120s (2 min), 5m = 600s (10 min), 15m = 1800s (30 min), 1h = 7200s (2h), 4h = 57600s (16h), 1d = 172800s (48h).
  implication: A 1m signal is considered stale after 2 minutes. A 5m signal after 10 minutes. These thresholds are far shorter than signal lifecycles (signals can be pending/active for hours).

- timestamp: 2026-03-12
  checked: sse.py lines 53-67 — _signal_entry_stale()
  found: Uses Redis entry ID timestamp (Unix-ms embedded in the stream ID). Compares against time.time(). Returns True (stale) if age > max_age_s.
  implication: Any signal that was written to the Redis stream more than 2×TF ago is silently dropped during snapshot replay. For a 1m TF signal that fired 5 minutes ago (still active/pending), it is dropped.

- timestamp: 2026-03-12
  checked: use-market-stream.ts lines 282-796 — mount/connect behavior
  found: On mount, only one REST call is made: fetchSession() for session/prevClose data (line 301). There is NO fetch() call to /api/signals/{symbol} or /signals/recent on mount. Signal state (symbolData.signal, signalsByTf, tfSignals) starts empty from emptySymbolData() and is populated entirely by SSE events.
  implication: The only path to populate signals on refresh is SSE snapshot replay. Since the age filter drops old signals, nothing appears.

- timestamp: 2026-03-12
  checked: signal-banner.tsx line 39
  found: if (!signal || signal.confidence < HIGH_CONFIDENCE_THRESHOLD) return null; — banner only renders when signal is non-null AND confidence >= 0.75
  implication: Even if a low-confidence signal were somehow loaded, the banner would not show. But this is not the root cause — the signal object itself is null.

- timestamp: 2026-03-12
  checked: signals.py — /signals/{symbol} and /signals/recent endpoints
  found: Both endpoints exist and query signal_ledger. /signals/recent returns status, outcome, direction, entry_price, stop_loss, confidence, timeframe. /signals/{symbol} returns full signal row with optional features JOIN.
  implication: The DB-side infrastructure for loading signals on mount IS present. It is just not called by the frontend.

## Resolution

root_cause: |
  Two compounding gaps combine to produce zero signals on refresh:

  1. SSE age filter too aggressive: _signal_entry_stale() drops signal stream entries older than 2×TF seconds.
     For 1m signals this is 2 minutes — far shorter than a signal's lifetime (can be pending/active for hours).
     For 5m signals: 10 minutes. For 15m: 30 minutes. Almost any realistic active signal will be filtered out.
     The filter's intent was to prevent stale replay — but it is calibrated at TF granularity,
     not at signal lifecycle duration. Result: snapshot loop silently emits nothing for signals.

  2. No REST pre-population on mount: use-market-stream.ts has no fetch() call for signals at mount.
     The only REST call on connect is fetchSession() for session OHLCV data.
     Signal state starts as null (emptySymbolData) and can only be populated by incoming SSE events.
     Without a REST seed, signals only appear when a NEW signal fires after the page loads.

fix: |
  Two-part fix needed:

  A. Add REST signal seed on mount in use-market-stream.ts:
     - On SSE connect (inside the useEffect alongside fetchSession), call /api/signals/active or
       /api/signals/{symbol}?status=pending,active&limit=N for each symbol.
     - Map the DB response into SignalData objects and call setSymbolData to populate signalsByTf / signal.
     - This runs in parallel with SSE snapshot, same pattern as fetchSession.
     - Requires either a new /api/signals/active endpoint or adding a status filter to the existing
       /signals/{symbol} endpoint.

  B. Fix or remove the SSE age filter for snapshot replay (sse.py):
     - Option 1 (preferred): Remove _signal_entry_stale() entirely from the snapshot loop.
       The snapshot only reads the last 2 entries (count=2) from the signal stream — that is already
       a sufficient recency guard. Age filtering is redundant and harmful here.
     - Option 2: Raise the threshold to match signal TTL (e.g. 4h or 8h), not 2×TF.
     - Option 3: Only apply the filter in the LIVE loop (not the snapshot loop), so reconnects
       after brief drops don't replay old events, but fresh page loads always get the latest signal.

  The cleanest fix is (A) + (B-Option 1): remove the stale filter from snapshot, add REST seed.
  The REST seed is the authoritative source; SSE snapshot is a fast-path supplement.

verification: |
  Self-verified checks:
  - ruff check: 0 new errors in changed Python files (pre-existing long line in sse.py excluded)
  - tsc --noEmit: 0 TypeScript errors
  - pytest tests/unit/api/ tests/unit/test_sse_snapshot_filter.py: 47 passed, 1 pre-existing failure
    (test_get_signals_base_symbol_resolved — confirmed pre-existing via git stash check)
  - Removed test_sse_routes.py tests for now-deleted legacy Redis helpers
  - Updated test_sse_snapshot_filter.py: removed TestSnapshotLoopNoAgeFilter (imported deleted function),
    kept TestSseSnapshotFilter (uses local _is_signal_entry_stale helper) and TestIntelligenceI7Routing
  - Verified DB columns: query uses only existing signal_ledger columns
    (stop_basis for stop_type, no entry_type/framing_method/calibration cols — not in DB yet)
  - /signals/active route confirmed to filter is_shadow=false (shadow signals excluded from seed)

  Awaiting user confirmation that signals appear on dashboard page refresh.

files_changed:
  - src/api/routes/signals.py: added GET /signals/active endpoint returning all pending/active signals
  - src/api/routes/sse.py: removed legacy _signal_entry_stale, _signal_max_age_s, _TF_MINUTES (no longer used; SSE is Kafka-based)
  - dashboard/src/hooks/use-market-stream.ts: added fetchActiveSignals() parallel to fetchSession on SSE connect
  - tests/unit/api/test_sse_routes.py: deleted (tested removed functions)
  - tests/unit/test_sse_snapshot_filter.py: removed TestSnapshotLoopNoAgeFilter class, updated imports
