# Pipeline Reset Sentinel Event — Design

Date: 2026-03-07
Status: Approved

## Problem

After `pipeline_reset.py` clears Redis streams and DB tables, the dashboard's React
state retains stale intelligence, signal, and narrative data from the previous session.
New SSE events overwrite fields as fresh data arrives, but fields not yet re-generated
(e.g. narratives, which require an LLM call) remain visible with stale values.

The fix must be automatic — no manual browser reload required.

## Approach

Publish a sentinel event to a dedicated `system:events` Redis stream immediately after
streams are cleared. The SSE handler forwards it to all connected clients as a
`system_event`. The dashboard clears stale intelligence/signal/narrative state on
receipt while preserving live tick, bar, and session data.

## Components

### 1. Stream key (`src/core/stream_keys.py`)

```python
def system_events(env_prefix: str) -> str:
    return f"{env_prefix}system:events"
```

This stream is intentionally excluded from `_REDIS_PATTERNS` in `pipeline_reset.py`
so it survives the clear — clients that reconnect after the reset still see the event
via the SSE snapshot (`xrevrange`).

### 2. Publisher (`production/scripts/pipeline_reset.py`)

Publish immediately after `clear_redis_streams()` (Stage 2), before services restart:

```python
r.xadd(
    system_events_key,
    {
        "event": "pipeline_reset",
        "ts": datetime.now(UTC).isoformat(),
        "symbols": json.dumps(target_symbols or [c.symbol for c in contracts]),
    },
    maxlen=50,
)
```

`maxlen=50` — this stream will rarely accumulate more than a handful of entries.
`symbols` carries the exact list of reset symbols to allow selective clearing when
`--symbols` is used.

### 3. SSE handler (`src/api/routes/sse.py`)

- `_build_stream_list()`: append `system_events(env_prefix)` once (global, not
  per-symbol — same pattern as `narratives_group`).
- `_event_name_for_stream()`: add branch `candidate.startswith("system:")` →
  `"system_event"`.

No staleness guard needed for the snapshot — clearing already-empty state is a no-op.

### 4. Dashboard (`dashboard/src/hooks/use-market-stream.ts`)

Add `system_event` listener:

```typescript
es.addEventListener("system_event", (evt) => {
  const { payload } = JSON.parse(evt.data);
  if (payload.event !== "pipeline_reset") return;

  const resetSymbols: string[] = payload.symbols
    ? (JSON.parse(String(payload.symbols)) as string[]).map(contractToBase)
    : symbols; // fallback: clear all

  setSymbolData((prev) => {
    const next = { ...prev };
    for (const sym of resetSymbols) {
      if (!next[sym]) continue;
      next[sym] = {
        ...next[sym],
        indicators: null,
        structure: null,
        context: null,
        patterns: null,
        smartMoney: null,
        confluence: null,
        signal: null,
        tfSignals: {},
        signalsByTf: {},
        indicatorsByTf: {},
        intelligenceByTf: {},
      };
    }
    return next;
  });
  setNarratives((prev) => {
    const next = { ...prev };
    for (const sym of resetSymbols) {
      for (const key of Object.keys(next).filter(k => k.startsWith(`${sym}:`))) {
        delete next[key];
      }
    }
    return next;
  });
  setGroupNarratives({});
  touch();
});
```

Preserved: `tick`, `bar`, `session`, `prevClose`.
Cleared: `indicators`, `structure`, `context`, `patterns`, `smartMoney`, `confluence`,
`signal`, `tfSignals`, `signalsByTf`, `indicatorsByTf`, `intelligenceByTf`,
`narratives`, `groupNarratives`.

## Event Timing

```
pipeline_reset.py Stage 2: clear_redis_streams()
  └─ publish sentinel to system:events
     └─ SSE clients receive system_event (~5s max, blocked xread)
        └─ Dashboard clears stale intelligence/signal/narrative state
pipeline_reset.py Stage 3-5: fetch OHLCV, replay, verify
pipeline_reset.py: pause for service restart
  └─ Services start → fresh data flows into now-empty dashboard state
```

## What Is NOT Cleared

- Tick/bid/ask data — TWS keeps streaming through the reset
- Bar/OHLCV data — not cleared by pipeline_reset.py
- Session high/low/open — still valid intraday data
- `system:events` stream itself — must survive for reconnecting clients

## Testing

- Unit: mock `xadd` call in `pipeline_reset.py`; assert correct payload shape
- Unit: assert `_build_stream_list` includes `system:events`
- Unit: assert `_event_name_for_stream("development:system:events") == "system_event"`
- Manual: run `pipeline_reset.py --dry-run` (no sentinel), then full reset and verify
  dashboard clears stale narratives without browser reload
