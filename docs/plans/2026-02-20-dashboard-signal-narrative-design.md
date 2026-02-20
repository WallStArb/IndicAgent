# Dashboard Signal/Narrative Panel — Design

**Date:** 2026-02-20
**Status:** Approved
**Priority:** Phase 1 Task 1.3 — closes the human feedback loop

---

## Problem

The full I1→I8 pipeline is running end-to-end. The Signal Orchestrator (:9112) generates ~30 signals/day, the AI Narrative Service (:9113) produces human-readable commentary per signal — but no human ever sees them. Without a dashboard panel, there is no way to monitor signal quality, catch lifecycle bugs, or validate that the pipeline is producing sensible output.

---

## What Gets Built

Four self-contained changes:

1. **Backend SSE** — wire `signals:SYMBOL:TF:aggregated` and `narratives:SYMBOL:TF` into the existing SSE endpoint
2. **`SignalPanel.tsx`** — compact per-symbol active-signal display inside each SymbolCard
3. **`NarrativePanel.tsx`** — AI narrative text panel, global across the bottom of the dashboard
4. **`trading-dashboard.tsx` + `types.ts`** — wire both panels in, add new types

---

## Architecture

### Backend: SSE Changes (`src/api/routes/sse.py`)

Current `_build_stream_list()` includes: `ticks`, `market`, `indicators`, `intelligence`, raw `signals`.

**Change:** Replace raw `sk_signals` with `sk_signals_aggregated` and add `sk_narratives`:

```python
# Add to imports:
from ...core.stream_keys import signals_aggregated as sk_signals_aggregated
from ...core.stream_keys import narratives as sk_narratives

# In _build_stream_list():
streams.append(sk_signals_aggregated(env_prefix, contract, timeframe))
streams.append(sk_narratives(env_prefix, contract, timeframe))
```

**New event name mappings** in `_event_name_for_stream()`:
- `signals:...:aggregated` → `signal_data`
- `narratives:...` → `narrative_data`

> Note: The raw `signals:` stream (unaggregated per-plugin output) is not needed by the dashboard. The aggregated stream is what the Signal Orchestrator publishes after conflict resolution.

---

### Frontend Data Flow

```
SSE /api/sse/events
  ├─ signal_data  → useMarketStream → SymbolData.signal   → SignalPanel (per card)
  └─ narrative_data → useSignalStream (new hook)           → NarrativePanel (global bottom)
```

Signals are per-symbol/timeframe → naturally fit inside existing SymbolCard.
Narratives are text blobs, often longer → displayed in a persistent bottom panel, updated live.

---

### Layout

```
┌─────────────────────────────────────────────────────┐
│  Header (symbol selector, timeframe, status)        │
├──────────────┬──────────────┬────────────────────────┤
│ SymbolCard   │ SymbolCard   │ SymbolCard             │
│ PriceHero    │ PriceHero    │ PriceHero              │
│ Indicators   │ Indicators   │ Indicators             │
│ Structure    │ Structure    │ Structure              │
│ Context      │ Context      │ Context                │
│ Patterns     │ Patterns     │ Patterns               │
│ SmartMoney   │ SmartMoney   │ SmartMoney             │
│ Confluence   │ Confluence   │ Confluence             │
│ [SignalPanel]│ [SignalPanel]│ [SignalPanel]  ← NEW   │
├──────────────┴──────────────┴────────────────────────┤
│ [NarrativePanel — full width]                ← NEW   │
├─────────────────────────────────────────────────────┤
│  Footer                                             │
└─────────────────────────────────────────────────────┘
```

---

### `SignalPanel.tsx` — Per-Symbol Active Signal

Compact row inside each SymbolCard. Shows the most recent active/pending signal for that symbol.

**Fields displayed:**
- Direction badge: `LONG` (green) / `SHORT` (red) / `—` (no signal)
- Setup plugin: abbreviated (e.g., `TrendF`, `MeanRev`, `LiqSweep`)
- Confidence: numeric (e.g., `0.74`)
- Status pill: `PENDING` (amber) / `ACTIVE` (green) / `EXITED` (muted)
- Entry price
- Stop / Target (compact: `5842 / 5856`)

**Type additions to `types.ts`:**
```typescript
export interface SignalData {
  direction: "long" | "short";
  setup_plugin: string;
  confidence: number;
  status: "pending" | "active" | "exited";
  entry_price: number;
  stop_price: number;
  target_price: number;
  pnl_r?: number;
  timestamp: string;
}
```

**SymbolData** gets a new optional field: `signal: SignalData | null`.

---

### `NarrativePanel.tsx` — Global AI Narrative Feed

A fixed-height panel at the bottom of the dashboard. Displays the latest AI narrative across all monitored symbols. Updates live as new narratives arrive.

**Layout:** Horizontal card strip — one card per symbol that has a recent narrative (within the last 90s, matching the `narrative:SYMBOL:TF:latest` TTL). Each card shows:
- Symbol + timeframe badge
- Direction badge
- Narrative text (2–3 sentences, italic, monospace font for clarity)
- Timestamp ("3s ago")

**State:** Managed by a new `useSignalStream` hook (separate from `useMarketStream` to avoid bloating that hook). Holds `Record<string, NarrativeData>` keyed by `SYMBOL:TF`.

```typescript
export interface NarrativeData {
  symbol: string;
  timeframe: string;
  direction: "long" | "short";
  narrative_text: string;
  timestamp: string;
  receivedAt: number;
}
```

**UX Design target:** Modern, terminal-inspired but clean. Dark background, subtle glass-morphism card borders, AI text in a slightly dimmed serif/mono font. Fade in new narratives. Dim cards older than 60s.

---

### New Hook: `useSignalStream`

Separate hook that creates its own SSE connection subscribing to `signals:aggregated` and `narratives` streams. Reason: keeps `useMarketStream` focused on per-symbol OHLCV/indicator state, while signal/narrative state has different lifecycle semantics (append-only log, not latest-wins replacement).

```typescript
// Returns:
{
  latestSignals: Record<string, SignalData>;    // keyed by "SYMBOL:TF"
  latestNarratives: Record<string, NarrativeData>;  // keyed by "SYMBOL:TF"
}
```

---

## Signal Payload Format

The Signal Orchestrator publishes to `signals:SYMBOL:TF:aggregated`. Fields (from existing SignalOrchestrator source):
- `symbol`, `timeframe`, `direction` (long/short), `setup_plugin`, `confidence`, `status`
- `entry_price`, `stop_price`, `target_price`, `pnl_r` (when available)
- `timestamp`

The Narrative Service publishes to `narratives:SYMBOL:TF`:
- `symbol`, `timeframe`, `direction`, `narrative_text`, `timestamp`

Both payloads are already string-serialized Redis hash fields — same pattern as existing SSE events.

---

## Success Criteria

1. `signal_data` and `narrative_data` SSE events arrive in the browser (verify in DevTools)
2. Each SymbolCard shows the active signal when one exists (LONG/SHORT badge visible)
3. NarrativePanel shows AI text within 2–3 seconds of a new signal firing
4. No regressions to existing panels
5. All existing unit tests continue to pass

---

## Out of Scope

- Historical signal log / P&L table (Phase 2 monitoring work)
- Signal alert notifications / sounds
- Manual signal override or dismissal UI
- Mobile responsive layout (existing dashboard is desktop-only)
