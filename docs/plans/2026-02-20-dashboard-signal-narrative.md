# Dashboard Signal/Narrative Panel Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Wire the Signal Orchestrator's aggregated signals and AI Narrative Service output into the trading dashboard — a per-symbol signal row in each SymbolCard plus a global AI narrative panel at the bottom.

**Architecture:** The SSE endpoint already reads multiple Redis streams and emits named events. We add `signals:SYMBOL:TF:aggregated` (replacing raw `signals:`) and `narratives:SYMBOL:TF` to the stream list. The frontend hook handles the new `signal_data` and `narrative_data` events. Two new React components render the data inline.

**Tech Stack:** Python 3.13 / FastAPI SSE (backend), Next.js 15 / React 19 / TypeScript / Tailwind v4 (frontend), existing CSS var design tokens.

---

## Key Field Names (Confirmed from Source)

**Aggregated signal message** (from `signals:SYMBOL:TF:aggregated`):
- `symbol`, `timeframe`, `timestamp` — strings
- `direction` — "1" (long) or "-1" (short) as string
- `signal_type` — e.g., "trend_long", "trend_short", "mean_rev_long"
- `setup_plugin` — e.g., "ind_TrendFollowing"
- `confidence` — float as string, e.g., "0.74"
- `entry_price`, `stop_loss` — float as string (NOTE: `stop_loss` not `stop_price`)
- `regime_context` — "bullish" or "bearish"
- `targets` — NOT present (list, excluded from Redis serialization)

**Narrative message** (from `narratives:SYMBOL:TF`):
- `symbol`, `timeframe` — strings
- `narrative` — AI text string (NOTE: key is `narrative` not `narrative_text`)
- `action_bias` — "bullish" or "bearish"

---

## Task 1: Backend SSE — Add Aggregated Signals + Narratives

**Files:**
- Modify: `src/api/routes/sse.py`
- Create: `tests/unit/test_sse_stream_builder.py`

### Step 1: Write failing tests for the stream builder helpers

```python
# tests/unit/test_sse_stream_builder.py
"""Tests for SSE stream builder helper functions."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pytest

# We'll test the two pure helper functions by importing them.
# They live in src/api/routes/sse.py but we need to test them in isolation.
# Import after writing the new implementation.


def test_event_name_for_narrative_stream():
    """narratives: prefix maps to narrative_data event."""
    from src.api.routes.sse import _event_name_for_stream
    assert _event_name_for_stream("narratives:ESH6:5m") == "narrative_data"


def test_event_name_for_aggregated_signal_stream():
    """signals:...:aggregated maps to signal_data event."""
    from src.api.routes.sse import _event_name_for_stream
    assert _event_name_for_stream("signals:ESH6:5m:aggregated") == "signal_data"


def test_event_name_for_env_prefixed_narrative():
    """env-prefixed narratives stream maps correctly."""
    from src.api.routes.sse import _event_name_for_stream
    assert _event_name_for_stream("dev:narratives:ESH6:5m") == "narrative_data"


def test_event_name_for_env_prefixed_aggregated_signal():
    """env-prefixed aggregated signal stream maps correctly."""
    from src.api.routes.sse import _event_name_for_stream
    assert _event_name_for_stream("dev:signals:NQH6:15m:aggregated") == "signal_data"


def test_build_stream_list_includes_narratives():
    """Stream list includes narratives stream for each symbol."""
    from src.api.routes.sse import _build_stream_list
    streams = _build_stream_list(["ES"], "5m")
    assert any("narratives:" in s for s in streams), f"No narratives stream in {streams}"


def test_build_stream_list_uses_aggregated_not_raw():
    """Stream list uses signals:aggregated, not raw signals stream."""
    from src.api.routes.sse import _build_stream_list
    streams = _build_stream_list(["ES"], "5m")
    # Should have aggregated
    assert any("signals:" in s and ":aggregated" in s for s in streams), \
        f"No aggregated signals stream in {streams}"
    # Should NOT have raw signals (no stream ending in just ":5m" under signals)
    raw_signals = [s for s in streams if s.startswith("signals:") and not s.endswith(":aggregated")]
    assert len(raw_signals) == 0, f"Found raw (non-aggregated) signals stream: {raw_signals}"
```

### Step 2: Run tests — confirm they fail

```bash
.venv/bin/python3 -m pytest tests/unit/test_sse_stream_builder.py -v
```

Expected: `ImportError` or assertion failures — tests don't pass yet.

### Step 3: Modify `src/api/routes/sse.py`

**Change 1 — imports** (around line 14, replace `signals` import):

```python
# REMOVE:
from ...core.stream_keys import signals as sk_signals

# ADD:
from ...core.stream_keys import signals_aggregated as sk_signals_aggregated
from ...core.stream_keys import narratives as sk_narratives
```

**Change 2 — `_build_stream_list()`** (around line 44-49, replace the signals line):

```python
# REMOVE:
streams.append(sk_signals(env_prefix, contract, timeframe))

# ADD:
streams.append(sk_signals_aggregated(env_prefix, contract, timeframe))
streams.append(sk_narratives(env_prefix, contract, timeframe))
```

**Change 3 — `_event_name_for_stream()`** (add before the `return "message"` line):

```python
    if candidate.startswith("narratives:"):
        return "narrative_data"
```

Note: `signals:...:aggregated` already matches `candidate.startswith("signals:")` → returns `"signal_data"`. No change needed for that branch.

### Step 4: Run tests — confirm they pass

```bash
.venv/bin/python3 -m pytest tests/unit/test_sse_stream_builder.py -v
```

Expected: All 6 tests PASS.

### Step 5: Run full unit suite — confirm no regressions

```bash
.venv/bin/python3 -m pytest tests/unit/ -q
```

Expected: 383 passed (same as before) + 6 new = 389 passed.

### Step 6: Commit

```bash
git add src/api/routes/sse.py tests/unit/test_sse_stream_builder.py
git commit -m "feat: wire signals:aggregated + narratives into SSE stream endpoint"
```

---

## Task 2: Frontend Types

**Files:**
- Modify: `dashboard/src/lib/types.ts`

### Step 1: Add SignalData and NarrativeData interfaces

Add after the `ConfluenceData` interface (around line 151), before `SymbolData`:

```typescript
// ── I7 Trading Signals ──

export interface SignalData {
  direction: "long" | "short";
  signal_type: string;           // e.g., "trend_long", "mean_rev_short"
  setup_plugin: string;          // e.g., "ind_TrendFollowing"
  confidence: number;            // 0.0–1.0
  entry_price: number;
  stop_loss: number;
  regime_context: string;        // "bullish" | "bearish"
  timestamp: string;
}

// ── I8 AI Narratives ──

export interface NarrativeData {
  symbol: string;
  timeframe: string;
  narrative: string;             // AI-generated text (key: "narrative" not "narrative_text")
  action_bias: string;           // "bullish" | "bearish"
  timestamp: string;
  receivedAt: number;            // Date.now() when received — for staleness
}
```

### Step 2: Add `signal` to SymbolData

In `SymbolData` interface, add after `confluence`:

```typescript
  signal: SignalData | null;
```

### Step 3: No test needed — TypeScript compilation is the test

Verify by running the dev server:

```bash
cd dashboard && npm run build 2>&1 | head -30
```

Expected: Build succeeds (or only pre-existing errors, none new).

### Step 4: Commit

```bash
git add dashboard/src/lib/types.ts
git commit -m "feat: add SignalData and NarrativeData types"
```

---

## Task 3: Wire Signal + Narrative Handlers into useMarketStream

**Files:**
- Modify: `dashboard/src/hooks/use-market-stream.ts`

### Step 1: Update `emptySymbolData` to include `signal: null`

Find the `emptySymbolData` function (around line 17). Add `signal: null` to the returned object:

```typescript
function emptySymbolData(symbol: string): SymbolData {
  return {
    symbol,
    tick: { price: 0, bid: 0, ask: 0, timestamp: "", lastUpdate: 0 },
    bar: { open: 0, high: 0, low: 0, close: 0, volume: 0, timestamp: "", lastUpdate: 0 },
    prevClose: 0,
    indicators: null,
    structure: null,
    context: null,
    patterns: null,
    smartMoney: null,
    confluence: null,
    signal: null,       // ← add this
    lastUpdate: 0,
  };
}
```

### Step 2: Add types import

At the top of the file, add `SignalData` and `NarrativeData` to the import:

```typescript
import type {
  SymbolData,
  IndicatorData,
  StructureData,
  ContextData,
  PatternData,
  SmartMoneyData,
  ConfluenceData,
  SignalData,        // ← add
  NarrativeData,     // ← add
  ConnectionStatus,
  Timeframe,
} from "@/lib/types";
```

### Step 3: Add narratives state to the hook

Inside `useMarketStream` function body, after the `lastUpdate` state:

```typescript
const [narratives, setNarratives] = useState<Record<string, NarrativeData>>({});
```

### Step 4: Add `signal_data` event listener

Inside the `useEffect` SSE setup, after the `intelligence_data` listener (around line 305), add:

```typescript
    // --- Aggregated signal data (I7) ---
    es.addEventListener("signal_data", (evt) => {
      const { payload } = JSON.parse(evt.data);
      const sym = contractToBase(payload.symbol || "");
      if (!sym) return;
      const dir = parseInt(String(payload.direction || "0"));
      if (dir === 0) return; // Skip no-signal entries

      const signal: SignalData = {
        direction: dir > 0 ? "long" : "short",
        signal_type: String(payload.signal_type || ""),
        setup_plugin: String(payload.setup_plugin || ""),
        confidence: parseFloat(String(payload.confidence || "0")),
        entry_price: parseFloat(String(payload.entry_price || "0")),
        stop_loss: parseFloat(String(payload.stop_loss || "0")),
        regime_context: String(payload.regime_context || ""),
        timestamp: String(payload.timestamp || ""),
      };

      setSymbolData((prev) => {
        const old = prev[sym];
        if (!old) return prev;
        return { ...prev, [sym]: { ...old, signal, lastUpdate: Date.now() } };
      });
      touch();
    });

    // --- AI narrative data (I8) ---
    es.addEventListener("narrative_data", (evt) => {
      const { stream, payload } = JSON.parse(evt.data);
      const sym = contractToBase(payload.symbol || "");
      if (!sym || !payload.narrative) return;

      // Key by "SYMBOL:TF" parsed from stream name (e.g., "narratives:ESH6:5m")
      const parts = stream.split(":");
      const tf = parts[parts.length - 1] || timeframe;
      const key = `${sym}:${tf}`;

      setNarratives((prev) => ({
        ...prev,
        [key]: {
          symbol: sym,
          timeframe: tf,
          narrative: String(payload.narrative),
          action_bias: String(payload.action_bias || ""),
          timestamp: String(payload.timestamp || ""),
          receivedAt: Date.now(),
        },
      }));
      touch();
    });
```

### Step 5: Return narratives from hook

Change the return statement (last line of `useMarketStream`):

```typescript
  return { symbolData, connectionStatus, lastUpdate, narratives };
```

### Step 6: Verify build

```bash
cd dashboard && npm run build 2>&1 | grep -E "error|Error" | head -20
```

Expected: No new TypeScript errors.

### Step 7: Commit

```bash
git add dashboard/src/hooks/use-market-stream.ts
git commit -m "feat: handle signal_data and narrative_data SSE events in useMarketStream"
```

---

## Task 4: SignalPanel Component

**Files:**
- Create: `dashboard/src/components/signal-panel.tsx`

### Step 1: Create the component

```tsx
"use client";

import type { SignalData } from "@/lib/types";
import { fmtPrice, fmtNum } from "@/lib/format";

interface SignalPanelProps {
  signal: SignalData | null;
}

/** I7 Active signal — compact row inside SymbolCard */
export function SignalPanel({ signal }: SignalPanelProps) {
  if (!signal) {
    return (
      <div className="px-2 py-1">
        <div className="flex items-center gap-2">
          <span className="zone-label shrink-0 w-10">SIG</span>
          <span className="text-[0.6rem] text-[var(--text-muted)] italic">—</span>
        </div>
      </div>
    );
  }

  const isLong = signal.direction === "long";
  const pluginShort = _abbreviatePlugin(signal.setup_plugin);

  return (
    <div className="px-2 py-1">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="zone-label shrink-0 w-10">SIG</span>

        {/* Direction badge */}
        <span
          className={`inline-flex items-center px-1.5 py-0 rounded text-[0.55rem] font-bold uppercase tracking-widest ${
            isLong
              ? "bg-[var(--green-dim)] text-[var(--green)]"
              : "bg-[var(--red-dim)] text-[var(--red)]"
          }`}
        >
          {isLong ? "LONG" : "SHORT"}
        </span>

        {/* Setup plugin */}
        <span className="text-[0.6rem] text-[var(--text-muted)] font-medium">
          {pluginShort}
        </span>

        {/* Confidence */}
        <span className="text-[0.6rem] font-data text-[var(--text-secondary)]">
          {fmtNum(signal.confidence * 100, 0)}%
        </span>

        {/* Entry → Stop */}
        <span className="text-[0.6rem] font-data text-[var(--text-muted)] whitespace-nowrap">
          {fmtPrice(signal.entry_price)}
          <span className="text-[var(--text-muted)] opacity-50 mx-0.5">→</span>
          {fmtPrice(signal.stop_loss)}
        </span>
      </div>
    </div>
  );
}

/** Shorten plugin name for compact display: "ind_TrendFollowing" → "TrendF" */
function _abbreviatePlugin(name: string): string {
  const bare = name.replace(/^(ind_|patt_|ctx_|smc_)/, "");
  if (bare.length <= 8) return bare;
  return bare.slice(0, 6);
}
```

### Step 2: Verify it compiles

```bash
cd dashboard && npm run build 2>&1 | grep -E "signal-panel|error" | head -10
```

Expected: No errors referencing signal-panel.tsx.

### Step 3: Commit

```bash
git add dashboard/src/components/signal-panel.tsx
git commit -m "feat: add SignalPanel component (I7 active signal row)"
```

---

## Task 5: NarrativePanel Component

**Files:**
- Create: `dashboard/src/components/narrative-panel.tsx`

### Step 1: Create the component

```tsx
"use client";

import { useMemo } from "react";
import type { NarrativeData } from "@/lib/types";

interface NarrativePanelProps {
  narratives: Record<string, NarrativeData>;
}

const STALE_AFTER_MS = 90_000; // matches narrative:latest 90s TTL

/** I8 AI Narrative feed — full-width horizontal strip of narrative cards */
export function NarrativePanel({ narratives }: NarrativePanelProps) {
  const entries = useMemo(
    () => Object.values(narratives).sort((a, b) => b.receivedAt - a.receivedAt),
    [narratives]
  );

  if (entries.length === 0) {
    return (
      <div className="px-3 py-2 flex items-center gap-2 border-t border-[var(--border-subtle)]">
        <span className="text-[0.55rem] font-semibold uppercase tracking-widest text-[var(--text-muted)] shrink-0">
          AI
        </span>
        <span className="text-[0.6rem] text-[var(--text-muted)] italic">
          Waiting for signals...
        </span>
      </div>
    );
  }

  return (
    <div className="border-t border-[var(--border-subtle)] bg-[var(--bg-surface)]">
      <div className="flex items-stretch gap-0 overflow-x-auto scrollbar-hide">
        {entries.map((n) => (
          <NarrativeCard key={`${n.symbol}:${n.timeframe}`} data={n} />
        ))}
      </div>
    </div>
  );
}

function NarrativeCard({ data }: { data: NarrativeData }) {
  const now = Date.now();
  const ageMs = now - data.receivedAt;
  const isStale = ageMs > STALE_AFTER_MS;
  const ageSec = Math.floor(ageMs / 1000);
  const ageLabel = ageSec < 60 ? `${ageSec}s ago` : `${Math.floor(ageSec / 60)}m ago`;

  const isBullish = data.action_bias === "bullish";
  const accentColor = isBullish ? "var(--green)" : "var(--red)";

  return (
    <div
      className="shrink-0 flex flex-col gap-1 px-3 py-2 min-w-[260px] max-w-[340px] border-r border-[var(--border-subtle)]"
      style={{
        borderLeftWidth: "2px",
        borderLeftStyle: "solid",
        borderLeftColor: accentColor,
        opacity: isStale ? 0.4 : 1,
        transition: "opacity 0.5s ease-out",
      }}
    >
      {/* Header row */}
      <div className="flex items-center gap-1.5">
        <span className="text-[0.55rem] font-bold text-[var(--text-primary)] font-data">
          {data.symbol}
        </span>
        <span className="text-[0.5rem] text-[var(--text-muted)] bg-[var(--bg-elevated)] px-1 rounded">
          {data.timeframe.toUpperCase()}
        </span>
        <span
          className="text-[0.5rem] font-semibold uppercase"
          style={{ color: accentColor }}
        >
          {data.action_bias}
        </span>
        <span className="ml-auto text-[0.5rem] text-[var(--text-muted)]">
          {ageLabel}
        </span>
      </div>

      {/* Narrative text */}
      <p className="text-[0.6rem] text-[var(--text-secondary)] italic leading-relaxed line-clamp-3">
        {data.narrative}
      </p>
    </div>
  );
}
```

### Step 2: Verify it compiles

```bash
cd dashboard && npm run build 2>&1 | grep -E "narrative-panel|error" | head -10
```

Expected: No errors.

### Step 3: Commit

```bash
git add dashboard/src/components/narrative-panel.tsx
git commit -m "feat: add NarrativePanel component (I8 AI narrative feed)"
```

---

## Task 6: Wire Into TradingDashboard

**Files:**
- Modify: `dashboard/src/components/trading-dashboard.tsx`

### Step 1: Add imports at the top

```typescript
import { SignalPanel } from "./signal-panel";
import { NarrativePanel } from "./narrative-panel";
```

### Step 2: Destructure `narratives` from the hook

Find the `useMarketStream` call (around line 29):

```typescript
// BEFORE:
const { symbolData, connectionStatus, lastUpdate } = useMarketStream(timeframe, symbols);

// AFTER:
const { symbolData, connectionStatus, lastUpdate, narratives } = useMarketStream(timeframe, symbols);
```

### Step 3: Add `NarrativePanel` between the grid and footer

Find the footer element (around line 116) and insert NarrativePanel before it:

```tsx
      {/* ── AI Narrative Feed ── */}
      <NarrativePanel narratives={narratives} />

      {/* ── Footer ── */}
      <footer ...>
```

### Step 4: Add `SignalPanel` inside `SymbolCard`

Find `SymbolCard` (around line 131). Add `SignalPanel` after `ConfluencePanel`:

```tsx
      <div className="border-t border-[var(--border-subtle)]">
        <ConfluencePanel confluence={data.confluence} />
      </div>
      <div className="border-t border-[var(--border-subtle)]">
        <SignalPanel signal={data.signal} />
      </div>
```

### Step 5: Full build check

```bash
cd dashboard && npm run build 2>&1 | grep -E "error|Error" | grep -v "^\s*//"
```

Expected: No TypeScript or build errors.

### Step 6: Commit

```bash
git add dashboard/src/components/trading-dashboard.tsx
git commit -m "feat: wire SignalPanel and NarrativePanel into TradingDashboard"
```

---

## Task 7: Verify End-to-End + Final Tests

### Step 1: Run full unit suite

```bash
.venv/bin/python3 -m pytest tests/unit/ -q
```

Expected: 389 tests passed, 0 failed.

### Step 2: Start backend + frontend (requires live services)

```bash
# Terminal 1: backend
.venv/bin/python3 -m uvicorn src.api.main:app --host 0.0.0.0 --port 8000

# Terminal 2: frontend
cd dashboard && npm run dev
```

### Step 3: Open browser DevTools → Network → EventStream

Navigate to `http://localhost:3000`. In DevTools:
1. Open Network tab, filter by "EventSource" or "eventsource"
2. Click on the SSE connection
3. Look for `signal_data` and `narrative_data` events in the Messages tab

Expected: Both event types appear (may take 1–5 min depending on when next signal fires).

### Step 4: Verify visual output

- Each SymbolCard has a `SIG` row at the bottom
- When a signal is received: direction badge (LONG/SHORT), plugin abbreviation, confidence %, and price levels
- Bottom of dashboard: NarrativePanel strip (empty until first signal fires)
- After a signal + narrative: NarrativeCard appears with colored left border, AI text, timestamp

### Step 5: Final commit tag

```bash
git add -A
git commit -m "chore: dashboard signal/narrative panel complete (Phase 1 Task 1.3)"
```

---

## Rollback

If anything breaks:
```bash
git log --oneline -8          # find last good commit
git revert HEAD               # revert last commit only
```

No DB schema changes, no config changes — all changes are additive to SSE and frontend only.

---

## Success Criteria

- [ ] 389 unit tests pass (383 existing + 6 new SSE tests)
- [ ] `signal_data` and `narrative_data` events visible in browser DevTools
- [ ] SignalPanel renders LONG/SHORT badge in each SymbolCard when a signal is active
- [ ] NarrativePanel renders AI text cards at bottom of dashboard
- [ ] Cards dim after 90s (matching narrative TTL)
- [ ] No regressions to existing panels (Structure, Context, Patterns, SMC, Confluence)
