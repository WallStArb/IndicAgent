# Design: Signal Lifecycle Stream Events

**Date:** 2026-03-06
**Status:** Shipped — _publish_terminal_event in signal_lifecycle_service.py
**Related:** Phase 17 (LLM wiring — signal_id threading), signal_lifecycle_service, SSE endpoint

---

## Problem

The `signals:SYMBOL:TF:aggregated` Redis stream is write-once at signal birth. The signal lifecycle — activation, stop-out, target hit, expiry — is tracked in `signal_ledger` (DB) but never published to the stream. This creates two failures:

1. **Dashboard staleness:** when a signal expires or stops out, the dashboard never learns about it. The last SSE signal_data event stays displayed indefinitely — even hours after the signal closed.
2. **SSE snapshot stale replay:** on reconnect, the SSE endpoint replays the last stream entry. If no new signal has fired in hours, the dashboard shows a 6-hour-old signal immediately on page load.
3. **Incomplete event log:** the stream records signal births but not outcomes. Downstream consumers (LLM writer, ML training) cannot reconstruct full signal history from the stream alone.

---

## Renaissance Framing

> "Instrument everything. No data point left uncaptured. If it happened, it should be measurable."

The stream is the source of truth for signal state. Right now it only records births — that is incomplete data. Every lifecycle transition is a first-class event. The dashboard fix is a side effect; the real thing being built is a **complete signal event log**.

The permanent record already exists (`signal_ledger` with `exit_at`, `outcome`, `pnl_r`). The stream is the real-time notification layer. Both tiers need to be complete.

---

## Design

### 1. Lifecycle Stream Events (`signal_lifecycle_service.py`)

On every terminal state transition, publish a status update event to `signals:SYMBOL:TF:aggregated`:

```python
await redis.xadd(
    stream_key,
    {
        "direction": "0",           # sentinel: no live signal
        "signal_id": str(signal_id),
        "status": outcome,          # e.g. "expired", "stopped_out", "target_1", "target_full"
        "outcome": outcome_8class,  # 8-class string from _classify_*
        "exit_price": str(exit_price) if exit_price else "",
        "symbol": symbol,
        "timeframe": timeframe,
        "timestamp": bar_ts.isoformat(),
    },
    maxlen=200,
    approximate=True,
)
```

Terminal states that trigger publication:
- `never_activated` (TTL expired before price reached entry)
- `stopped_at_entry` (stopped before T1)
- `stopped_in_trade` (stopped after T1)
- `target_1`, `target_1_2`, `target_full` (target hit)
- `ttl_expired_ahead`, `ttl_expired_behind` (TTL with position)

**Publication is unconditional** — it fires regardless of whether a newer signal has already preempted this one on the stream. The event is a data integrity record, not just a UI notification.

**Ordering invariant:** if signal A is replaced by signal B (new bar fires new winner), and then signal A reaches its terminal state, the stream will contain: `birth(A)` → `birth(B)` → `resolved(A)`. The dashboard handles this correctly via `signal_id` matching (see section 3).

### 2. SSE Snapshot Age Filter (`src/api/routes/sse.py`)

On connect, the SSE snapshot loop replays the last 2 entries per stream. For signal streams, add an age gate:

- Extract TF from stream key: `signals:ESH6:5m:aggregated` → `5m`
- Compute max age: `2 × tf_minutes × 60` seconds
- Extract entry age from Redis entry ID: `int(entry_id.split("-")[0]) / 1000` → Unix seconds
- Skip entries older than max age

TF → minutes mapping (same as dashboard `_TF_MINUTES`):
```python
_TF_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}
```

This ensures that on reconnect, an ancient signal is never replayed. If the last stream entry is stale, no signal_data event is sent — the dashboard starts with `signal: null` for that slot, which renders as "— no signal —" until the next bar fires.

### 3. Dashboard State Machine (`use-market-stream.ts`)

Current behaviour: `dir === 0` → `fullSignal = null` → `signal = old.signal ?? null` (keeps old signal via null coalescing).

New behaviour:

```typescript
if (dir === 0 && payload.status) {
  // Terminal event received
  const resolvedId = String(payload.signal_id || "");
  const currentId = old.signal?.signal_id || "";
  if (resolvedId === currentId) {
    // Matches displayed signal → create resolved SignalData
    fullSignal = {
      ...old.signal!,
      resolved: true,
      outcome: String(payload.status),
      exit_price: parseFloat(String(payload.exit_price || "0")) || undefined,
    };
  }
  // else: stale resolved event for preempted signal → no-op (fullSignal stays null)
}
```

The `signal_id` acts as a natural epoch tag. If signal B has already replaced signal A on screen, signal A's resolved event is silently ignored.

### 4. Signal Panel Resolved State (`signal-panel.tsx`)

When `signal.resolved === true`:
- Overall opacity dimmed to ~50%
- Outcome badge rendered above or below the entry row:
  - `EXPIRED` — `ttl_expired_*`
  - `STOPPED` — `stopped_at_entry`, `stopped_in_trade`
  - `T1 HIT` — `target_1`
  - `T1+T2 HIT` — `target_1_2`
  - `FULL TARGET` — `target_full`
- Entry / SL / target prices remain visible for context
- No staleness ratio shown (signal is definitively closed, not just old)

### 5. REST API Timeframe Filter (`src/api/routes/signals.py`)

Add `timeframe: str | None = Query(None)` parameter. Inject into both query variants:

```sql
AND ($N::text IS NULL OR sl.timeframe = $N)
```

This is a correctness fix — the parameter was accepted but silently ignored.

---

## Data Flow (complete)

```
signal_lifecycle_service
  detects terminal state (expire / stop / target)
  → xadd signals:SYMBOL:TF:aggregated {direction=0, signal_id, status, outcome, ...}
  → UPDATE signal_ledger SET exit_at, outcome, pnl_r (already exists)

SSE endpoint (on connect)
  snapshot loop: for signal streams, skip entries older than 2×TF
  live loop: pass all entries through unchanged

Dashboard (use-market-stream.ts)
  signal_data handler:
    dir !== 0 → new live signal (existing behaviour)
    dir === 0 + status + matching signal_id → resolved SignalData
    dir === 0 + no match → no-op

SignalPanel
  resolved === false/undefined → current live display (no change)
  resolved === true → dimmed + outcome badge
```

---

## What Is NOT Changing

- `signal_ledger` schema — all lifecycle columns already exist (`exit_at`, `outcome`, `pnl_r`, etc.)
- Stream key naming — `signals:SYMBOL:TF:aggregated` unchanged
- Signal birth event format — `signal_generator_service` unchanged
- `signalsByTf` per-TF matrix — continues to update for all TFs as before

---

## Testing Strategy

- **Unit:** `signal_lifecycle_service` — mock Redis xadd, assert terminal event published with correct fields for each outcome class
- **Unit:** SSE snapshot age filter — mock Redis entries with old/fresh entry IDs, assert stale signal entries are skipped
- **Unit:** `use-market-stream.ts` signal_data handler — test resolved event with matching/mismatching `signal_id`; test no-op on preempted signal
- **Unit:** `SignalPanel` — render with `resolved: true`, assert outcome badge present and opacity class applied
- **Integration:** REST API `?timeframe=5m` filter — assert only 5m signals returned

---

## Files Changed

| File | Type |
|------|------|
| `services/signal_lifecycle_service.py` | Backend — publish terminal events |
| `src/api/routes/sse.py` | Backend — snapshot age filter |
| `src/api/routes/signals.py` | Backend — timeframe query param |
| `dashboard/src/lib/types.ts` | Frontend — extend SignalData |
| `dashboard/src/hooks/use-market-stream.ts` | Frontend — resolved state handling |
| `dashboard/src/components/signal-panel.tsx` | Frontend — resolved UI |
