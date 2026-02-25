# Phase 6: Dashboard Connected - Research

**Researched:** 2026-02-25
**Domain:** SSE dashboard wiring, multi-timeframe data pipeline, frontend component field mapping
**Confidence:** HIGH — all findings based on direct inspection of live code and Redis streams

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Sequencing (critical)**
- Fix the API "internal server error" FIRST — can't audit what we can't see
- Then diagnose what data IS flowing (inspect Redis streams + service logs) before fixing field mappings
- Only then fix UI wiring gaps — otherwise we're guessing at missing fields
- Plan order: 06-01 fix API + get SSE flowing → 06-02 stream audit + field mapping fixes → 06-03 full verification

**Price Hero redesign**
- Show: **bid, ask, last** price (full spread — futures spread matters)
- **Flash animation** on tick: green flash when price goes up, red when down
- Show **H/L of current bar** alongside the live price
- **Colour the last price** green (above prev close) or red (below prev close)
- Show **+/- and % change** from BOTH:
  - Prev close (daily change — standard settlement reference)
  - Session open (intraday move)
- Show **dual range bars**:
  - Current bar H/L range (where price sits within the current bar)
  - Daily session H/L range (where price sits within today's full range)
- **Empty state**: show dashes "—" for all fields when no tick data has arrived yet (not zeros)

**Panel audit approach**
- Some panels are **entirely absent from the UI** (e.g. HMM regime, liquidity zones have no component)
- Other panels **exist but fields are empty/zero** (data not arriving or field names mismatched)
- Root cause unknown — could be pipeline not computing it, or UI mapping wrong — needs diagnosis
- Wire existing panel components where possible; only create new components for features with no UI at all
- HMM regime and liquidity zone placement: Claude's discretion (inline in relevant tier panel vs dedicated section — let the audit reveal the right fit)

**Missing data known from prior sessions**
- HMM regime (I6 SMC) — not visible in dashboard
- Liquidity zones — not visible
- Several I1 indicator fields (simpler indicators like stoch, williams_r, CCI) may not be populating correctly
- I3 structure fields partially populated
- I8 AI narratives: service is running but narratives are not appearing in the narrative panel

### Claude's Discretion
- Exact staleness thresholds for showing data as stale vs fresh
- Whether to show a "stale" badge on panels when data is old
- HMM and liquidity zone panel placement (inline vs own section)
- Skeleton/shimmer vs dashes for panels still waiting on first data

### Deferred Ideas (OUT OF SCOPE)
- I8 narrative panel behavior (TF-specific vs show newest) — was not discussed; Claude should default to showing the freshest narrative regardless of TF for now
- Empty/loading state design for intelligence panels — Claude's discretion (dashes pattern from price hero applies)
</user_constraints>

---

## Summary

Phase 6 is a data-plumbing and field-mapping phase, not a feature-building phase. The SSE infrastructure works (confirmed live), the I1–I7 pipeline flows for 1m timeframe, and all panel components exist. The work is: fix three backend pipeline gaps that block multi-TF data, fix two field-name mismatches that silently discard data, and rebuild the price hero component to the spec from CONTEXT.md.

The core pipeline discovery: **the indicator and intelligence services are configured for 1m/5m/15m/1h but only 1m data flows**. This is because `timeframes_builder_service.py` imports `from src.data.timeframe_builder import TimeframeBuilder` — but `src/data/` does not exist. The `TimeframeBuilder` class must be implemented (it aggregates 1m bars to 5m/15m/1h/4h/1d) or the service must be rewritten to inline that logic. Without it, AI narratives remain silent (they only read 5m/15m signals which stay empty), and I6 cross-timeframe confluence always returns null (it requires data from multiple timeframes).

The dashboard field-name bug: `IntelligenceEvent` uses `tf` (not `timeframe`) as the field name. The `use-market-stream.ts` hook reads `event.timeframe` which is always `undefined`, so intelligence data always gets stored under the fallback value (the user's selected timeframe) rather than the event's actual timeframe. This causes incorrect per-TF bucketing.

**Primary recommendation:** Fix the three backend blockers (timeframes builder, AI narrative consumer group scope, qualify_instrument for 6 contracts) before touching UI. Then fix the two field-mapping bugs (event.tf vs event.timeframe; deprecated `data.indicators` reference in price-hero). Then rebuild price hero per spec.

---

## Current State Audit

### What Is Working (confirmed from live Redis + API inspection)

| Component | Status | Notes |
|-----------|--------|-------|
| SSE endpoint `/api/sse/events` | WORKING | Returns tick_data, market_data, indicator_data, intelligence_data events |
| tick_data events | WORKING | bid/ask/price/sizes flowing in real time |
| market_data events (1m) | WORKING | 1m OHLCV bars flowing for all 17 active contracts |
| indicator_data events (1m) | WORKING | All 50+ indicator fields flowing for ESH6, NQH6, etc. |
| intelligence_data events (1m) | WORKING | I3/I4/I5/SMC data in event for 1m |
| signal_data events (1m) | WORKING | Aggregated signals flowing (200+ entries per symbol) |
| I3 structure data | WORKING | swing_high, swing_low, nearest_support, resistance, structure_integrity populated |
| I4 context data | WORKING | vol_regime, trend_regime, momentum_bias, GARCH, Kalman all populated |
| I5 patterns data | WORKING | rsi_div, squeeze, confluence_score, triangle pattern all populated |
| SMC data | WORKING | BOS/CHoCH, FVG, sweep_detected, HMM regime, liquidity zones populated |
| Consumer group names | WORKING | Phase 5 fix applied — stable group names, no timestamp bugs |

### What Is Broken (confirmed from live inspection)

| Component | Status | Root Cause |
|-----------|--------|-----------|
| 5m/15m/1h/4h/1d indicator streams | EMPTY | `timeframes_builder_service` broken: `ModuleNotFoundError: No module named 'src.data'` |
| 5m/15m/1h/4h/1d intelligence streams | EMPTY | Indicator service reads 5m/15m market bars that don't exist |
| I6 cross-timeframe confluence | NULL | Requires multi-TF cached intelligence — unavailable until timeframes builder runs |
| AI narratives (I8) | SILENT | Service reads 5m/15m signal streams which are empty (no data to narrate) |
| 6 contract qualify failures | FAILING | SR1H6, 6EH6, 6JH6, BTCH6, BZJ6, NGJ6 — FX/crypto/SOFR need `currency="USD"` in `Future()` |
| Intelligence data TF bucketing | BUG | Hook reads `event.timeframe` but `IntelligenceEvent` field is `event.tf` |
| Price-hero VWAP row | STALE | Reads `data.indicators?.vwap` (deprecated field) — should use `data.indicatorsByTf` |
| HMM regime | NOT DISPLAYED | Data IS in SMC stream (`hmm_regime`, `hmm_regime_prob`) but not in TypeScript types or UI |
| Liquidity zones | NOT DISPLAYED | Data IS in SMC stream (`bsl_level`, `ssl_level`, `premium_position`, etc.) but not mapped |

---

## Standard Stack

### Core (no new dependencies needed)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| redis.asyncio | existing | Python async Redis client | already used by all services |
| React | existing | UI component library | existing dashboard stack |
| EventSource API | browser native | SSE client | no library needed |
| Next.js | existing | Dashboard framework | existing |
| structlog | existing | Structured logging | project standard |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| TypeScript | existing | Type safety | all frontend changes |
| Tailwind CSS | existing | Styling | all new/modified components |

No new dependencies are required for Phase 6. All changes are plumbing and field mapping within the existing stack.

---

## Architecture Patterns

### Pattern 1: Timeframe Aggregation (1m → 5m/15m/1h/4h/1d)

**What:** Build OHLCV bars for higher timeframes by accumulating 1m bars. Emit a new bar when the higher-TF boundary is crossed.

**When to use:** Whenever the indicator and intelligence services need 5m/15m data to process.

**Approach for Phase 6:** The `TimeframeBuilderService` in `services/timeframes_builder_service.py` already exists with all config, logging, metrics, and lifecycle management. The only missing piece is the `TimeframeBuilder` class it imports from `src.data`. The simplest fix is to implement the `TimeframeBuilder` class in `src/core/timeframe_builder.py` (matching the existing import path shape) and update the import in the service. Alternatively, inline the aggregation logic directly into the service.

**TimeframeBuilder API (expected by timeframes_builder_service.py):**
```python
# Services/timeframes_builder_service.py lines 252-272 reveal the expected API:
self.timeframe_builder = TimeframeBuilder(self.streams_manager)
await self.timeframe_builder.start()
await self.timeframe_builder.subscribe_to_symbols(symbols)
# ...
builder_metrics = self.timeframe_builder.get_metrics()
await self.timeframe_builder.stop()
```

**Core aggregation logic:**
```python
# For each TF (5m, 15m, 1h, 4h, 1d):
# - Determine bar boundary: bar_open_time = floor(bar_ts, TF_minutes)
# - Accumulate OHLCV: first 1m bar opens the period, last 1m bar closes it
# - Emit to Redis stream when the period closes (next 1m bar has a different period)
```

### Pattern 2: SSE Field Mapping (event.tf vs event.timeframe)

**What:** `IntelligenceEvent` Pydantic model uses `tf` as the field name (matching Redis stream key convention `intelligence:SYMBOL:TF`). The dashboard hook reads `event.timeframe` which is always `undefined`.

**Fix location:** `dashboard/src/hooks/use-market-stream.ts`, line ~350:
```typescript
// WRONG (current):
const tf = String(event.timeframe || timeframe);

// CORRECT:
const tf = String(event.tf || timeframe);
```

### Pattern 3: Per-TF Indicator Access

**What:** `IndicatorData` is now stored in `indicatorsByTf[tf]` on `SymbolData`. The deprecated `data.indicators` field still exists but is never populated.

**Fix location:** `dashboard/src/components/price-hero.tsx` line 82:
```typescript
// WRONG (deprecated):
data.indicators?.vwap

// CORRECT:
const indicators = data.indicatorsByTf[activeTf] ?? null;
indicators?.vwap
```

But PriceHero does not receive `activeTf` — it only receives `data: SymbolData`. The component needs to either receive `indicators: IndicatorData | null` as a prop (recommended), or `activeTf: string` as a prop so it can look up from the map.

The SymbolCard passes `indicators={indicators}` to `IndicatorGrid` — follow the same pattern for PriceHero.

### Pattern 4: Adding HMM + Liquidity Zone Fields

**What:** HMM regime and buy-side/sell-side liquidity (BSL/SSL) data is already in the SMC tier of IntelligenceEvent. It's just not mapped to TypeScript types or rendered.

**Fields in `smc` tier (confirmed from live Redis):**
```
hmm_regime: 0.0 (0=ranging, 1=trending_up, 2=trending_down)
hmm_regime_prob: 0.962
hmm_prob_ranging: 0.962
hmm_prob_trending_up: 0.025
hmm_prob_trending_down: 0.012
hmm_regime_duration: 200.0
bsl_level: 6909.19 (buy-side liquidity level)
bsl_type: 0.75
bsl_significance: 0.75
bsl_dist_atr: 2.45
bsl_touches: 3.0
ssl_level: 6905.75 (sell-side liquidity level)
ssl_type: 0.75
ssl_significance: 0.75
ssl_dist_atr: 1.4
ssl_touches: 3.0
price_in_premium: 1.0 (boolean: price above equilibrium)
premium_position: 0.1683 (0=at discount, 0.5=equilibrium, 1.0=full premium)
pool_count: 8.0
```

**Fix chain:** Add fields to `SmartMoneyData` in `types.ts` → map them in `parseIntelligence()` in `use-market-stream.ts` → add display to `SmartMoneyPanel`.

### Pattern 5: AI Narrative Service Fix

**What:** The `AINarrativeService` is configured to read `["5m", "15m"]` signal streams. Those streams are empty because timeframes_builder_service is broken. The service is healthy but has nothing to narrate.

**Two-part fix:**
1. Fix timeframes_builder_service (Pattern 1 above) so 5m/15m signals get generated
2. Optionally: also configure narrative service to watch `1m` signals as fallback while timeframes pipeline recovers

**Consumer group initialization bug check:** The service uses `"0"` as the starting ID when creating consumer groups (line 299: `"0", mkstream=True`). This means on restart it re-reads ALL historical messages from the beginning. This is intentional for recovery but could be slow with large streams. For Phase 6, the 1m signal streams have 200+ entries — this is acceptable.

### Pattern 6: Price Hero Redesign

**What:** Full rebuild of `price-hero.tsx` to the spec in CONTEXT.md.

**Data availability analysis:**
- `tick.price`, `tick.bid`, `tick.ask` — available from SSE `tick_data` events
- `bar.high`, `bar.low` (current bar H/L) — available from `market_data` events (1m bars)
- `bar.open` (session open approximation) — available as first bar open of session
- `prevClose` — currently tracked as `old.bar.close` when new bar arrives (line 276 in use-market-stream.ts)
- Session H/L — NOT directly available. Must derive from max(bar.high) / min(bar.low) across session bars, or use the 1d bar when available (currently empty stream)

**Session H/L approach for Phase 6:** Track `sessionHigh` and `sessionLow` in `SymbolData`. Update them on each `market_data` event. Reset when a new session begins (timestamp date changes). This is frontend-only state.

**Flash animation:** CSS keyframe animation triggered by a state change. Pattern:
```typescript
// In use-market-stream.ts: track tick direction
const [flashDir, setFlashDir] = useState<'up' | 'down' | null>(null);
// On price update: compare to previous price, set flashDir, clear after 300ms

// In price-hero.tsx: apply CSS class
<span className={`${flashDir === 'up' ? 'animate-flash-green' : flashDir === 'down' ? 'animate-flash-red' : ''}`}>
```

Or pass `lastTick` direction as a prop and use a `useEffect` + `setTimeout` to reset the flash. The simplest approach: add a `tickFlash: 'up' | 'down' | null` field to `TickData`, set it in the `tick_data` handler, clear it after 300ms.

**Range bar component:** Two progress bars showing:
1. Current bar: `(price - bar.low) / (bar.high - bar.low)` — percentage of current bar range
2. Session: `(price - sessionLow) / (sessionHigh - sessionLow)` — percentage of session range

### Anti-Patterns to Avoid

- **Don't rebuild timeframes_builder_service from scratch** — the service shell is complete. Only the missing `TimeframeBuilder` class needs implementing.
- **Don't add `timeframe` alias to IntelligenceEvent schema** — the schema is `extra="forbid"`. Fix the consumer (dashboard) not the producer.
- **Don't try to pass session data from the backend** — the SSE stream doesn't carry session H/L. Track it in frontend state.
- **Don't change the consumer group `"0"` starting ID** — re-reading historical messages on restart is intentional recovery behavior.
- **Don't create a new session service** — session H/L is frontend state derived from bar data already available.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Flash animation timing | Custom event bus | `useEffect` + `setTimeout` for 300ms clear | React's own state is sufficient |
| Multi-TF bar aggregation | New aggregation library | Inline OHLCV accumulation math | Trivial: 4 operations per bar |
| SSE reconnection | Custom reconnect logic | Browser EventSource auto-reconnects | Already handled natively |
| Session boundary detection | External calendar service | Compare `new Date(bar.timestamp).toDateString()` | JS Date comparison is sufficient |

**Key insight:** This is a wiring phase. The data exists in Redis, the components exist in the UI. The work is fixing the connections between them, not building new abstractions.

---

## Common Pitfalls

### Pitfall 1: event.tf vs event.timeframe Field Name
**What goes wrong:** Intelligence data gets stored under the wrong timeframe key. All 1m intelligence data is stored under whatever TF the user has selected (e.g., "5m") instead of "1m". Switching timeframes then shows no data.
**Why it happens:** `IntelligenceEvent.tf` is the schema field name, but the hook reads `event.timeframe` which returns `undefined`, so it falls back to the `timeframe` hook parameter.
**How to avoid:** Fix line 350 in `use-market-stream.ts`: `event.tf || timeframe` not `event.timeframe || timeframe`.
**Warning signs:** Opening browser DevTools → Network → SSE stream, intelligence events arrive but switching TF tabs shows stale data.

### Pitfall 2: TimeframeBuilder Cannot Live in src/data
**What goes wrong:** Any new file placed at `src/data/timeframe_builder.py` creates the directory. But the existing import chain is the only user — no other module needs `src.data`. The class should go in `src/core/timeframe_builder.py` and the import in the service should be updated.
**Why it happens:** The service was written with a planned `src/data/` module that was never created.
**How to avoid:** Create `src/core/timeframe_builder.py` and update the import in `services/timeframes_builder_service.py` line 45.

### Pitfall 3: AI Narratives Remain Silent Even After Timeframes Fix
**What goes wrong:** Even after 5m/15m market bars start flowing, the AI narrative service might still not produce output if it started before signals began flowing on those TFs.
**Why it happens:** Consumer group created with `"0"` (reads from beginning) — this is actually fine. But if the service's `symbols` config hardcodes `["ESH6", "NQH6", "RTYH6"]` and the dashboard shows more symbols, narratives won't appear for other symbols.
**How to avoid:** After timeframes service is running and 5m signals start appearing, check the AI narrative service config `"symbols"` list matches the dashboard symbols.

### Pitfall 4: Session H/L Reset Logic
**What goes wrong:** Session high/low never reset. After the first session, the "session range" bar shows the wrong range for subsequent sessions.
**Why it happens:** State is initialized once and never reset.
**How to avoid:** On each `market_data` event, compare the bar's date to `sessionDate` state. If different, reset `sessionHigh = bar.high`, `sessionLow = bar.low`, `sessionOpen = bar.open`.

### Pitfall 5: Price Hero prevClose Bug
**What goes wrong:** `prevClose` starts at 0 and stays at 0 until two consecutive market_data events arrive. During this window, change calculation shows 0.
**Why it happens:** `prevClose` is set to `old.bar.close` — but on the first event, `old.bar.close` is 0 (initial state).
**How to avoid:** Show "—" when `prevClose === 0` rather than showing 0% change. `fmtPrice(0)` already returns "—" via the `!price` guard in format.ts.

### Pitfall 6: I6 Confluence Remains Null
**What goes wrong:** Even after the timeframes builder runs and 5m/15m intelligence starts flowing, the I6 CTF score remains null for the CURRENT 1m bar.
**Why it happens:** `CrossTimeframeConfluencePlugin.compute_full()` reads `frames["intel_5m"]`, `frames["intel_15m"]` etc from the `intelligence_cache`. This cache is only populated by `market_analysis_service._process_bar()` when intelligence for those higher TF bars arrives. There's a bootstrap period.
**How to avoid:** This is expected behavior during the first few minutes after startup. After ~5 bars of 5m/15m data have been processed, I6 will start producing values. Document this in the verification plan.

---

## Code Examples

### Fix 1: Intelligence Event TF Field (use-market-stream.ts)

```typescript
// dashboard/src/hooks/use-market-stream.ts ~line 350
// BEFORE (broken):
const tf = String(event.timeframe || timeframe);

// AFTER (fixed):
const tf = String(event.tf || timeframe);  // IntelligenceEvent uses 'tf' not 'timeframe'
```

Source: Confirmed from `src/intelligence/schemas.py` class `IntelligenceEvent` field `tf: str` and live Redis stream inspection showing `{"tf": "1m", "symbol": "ESH6", ...}`.

### Fix 2: Price Hero Indicators Access

```typescript
// dashboard/src/components/price-hero.tsx — add activeTf prop
interface PriceHeroProps {
  data: SymbolData;
  activeTf: string;  // Add this
}

export function PriceHero({ data, activeTf }: PriceHeroProps) {
  const { tick, bar, prevClose } = data;
  const indicators = data.indicatorsByTf[activeTf] ?? null;  // Use per-TF map
  const vwap = indicators?.vwap;
  // ...
}
```

### Fix 3: TimeframeBuilder in src/core

```python
# src/core/timeframe_builder.py — new file
# Implements the API expected by timeframes_builder_service.py

class TimeframeBuilder:
    """Aggregates 1m OHLCV bars into higher timeframe bars.

    Consumes from market:SYMBOL:1m Redis streams.
    Emits to market:SYMBOL:5m, market:SYMBOL:15m etc.
    """

    def __init__(self, streams_manager: RedisStreamsManager):
        self.streams_manager = streams_manager
        self._accumulators: dict[str, dict[str, BarAccumulator]] = {}
        # key: "SYMBOL:TF", value: BarAccumulator

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def subscribe_to_symbols(self, symbols: list[str]) -> None: ...
    def get_metrics(self) -> dict: ...
```

Source: API inferred from `services/timeframes_builder_service.py` lines 252-272, 387.

### Fix 4: HMM Regime + Liquidity in TypeScript Types

```typescript
// dashboard/src/lib/types.ts — extend SmartMoneyData
export interface SmartMoneyData {
  // ... existing fields ...

  // HMM Regime (I6 SMC)
  hmm_regime?: number;        // 0=ranging, 1=trending_up, 2=trending_down
  hmm_regime_prob?: number;   // probability of current regime (0-1)
  hmm_prob_ranging?: number;
  hmm_prob_trending_up?: number;
  hmm_prob_trending_down?: number;
  hmm_regime_duration?: number;  // bars in current regime

  // Liquidity Zones (BSL/SSL)
  bsl_level?: number;         // buy-side liquidity level (resistance above)
  bsl_significance?: number;  // 0-1 score
  bsl_dist_atr?: number;      // distance in ATR units
  bsl_touches?: number;       // times tested
  ssl_level?: number;         // sell-side liquidity level (support below)
  ssl_significance?: number;
  ssl_dist_atr?: number;
  ssl_touches?: number;
  price_in_premium?: boolean;  // true = price above equilibrium
  premium_position?: number;   // 0=discount, 0.5=equilibrium, 1=premium
  pool_count?: number;         // total liquidity pools in range
}
```

Source: Confirmed from live Redis SMC tier inspection.

### Fix 5: Session State Tracking in useMarketStream

```typescript
// dashboard/src/hooks/use-market-stream.ts — add to SymbolData state
interface SessionState {
  open: number;
  high: number;
  low: number;
  date: string;  // "YYYY-MM-DD" for reset detection
}

// In market_data handler:
es.addEventListener("market_data", (evt) => {
  const { payload } = JSON.parse(evt.data);
  const barDate = payload.timestamp?.slice(0, 10) ?? "";

  setSymbolData((prev) => {
    const old = prev[sym];
    const sess = old.session;
    const isNewSession = barDate !== sess.date;
    const newClose = parseFloat(payload.close);

    const newSession: SessionState = isNewSession
      ? { open: parseFloat(payload.open), high: parseFloat(payload.high),
          low: parseFloat(payload.low), date: barDate }
      : {
          open: sess.open,
          high: Math.max(sess.high, parseFloat(payload.high)),
          low: Math.min(sess.low, parseFloat(payload.low)),
          date: barDate,
        };
    return { ...prev, [sym]: { ...old, session: newSession, prevClose: isNewSession ? old.bar.close : old.prevClose } };
  });
});
```

### Fix 6: Tick Flash Animation

```typescript
// In SymbolData (types.ts):
tickFlash: "up" | "down" | null;

// In tick_data handler (use-market-stream.ts):
const prevPrice = prev[sym]?.tick.price ?? 0;
const dir = price > prevPrice ? "up" : price < prevPrice ? "down" : null;
// ...
tickFlash: dir,

// Clear flash after 350ms:
if (dir) {
  setTimeout(() => {
    setSymbolData(prev => ({
      ...prev,
      [sym]: { ...prev[sym], tickFlash: null }
    }));
  }, 350);
}

// In price-hero.tsx:
<span className={`transition-colors duration-150 ${
  data.tickFlash === "up" ? "text-up"
  : data.tickFlash === "down" ? "text-down"
  : ""
}`}>
```

---

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| `data.indicators` (single TF) | `indicatorsByTf[tf]` (per-TF map) | Phase 5 change — price-hero still uses old approach |
| `data.structure/context/etc` | `intelligenceByTf[tf]` (per-TF map) | Phase 5 change — panels now read from intel map |
| Flat k/v Redis stream fields | `IntelligenceEvent` JSON in `event` field | Phase 1 change — dashboard correctly parses it |
| Consumer group with timestamp ID | Stable consumer group name | Phase 5 fix — still needs to be verified for AI narrative service |

**Deprecated patterns in the dashboard (must fix in Phase 6):**
- `data.indicators` (deprecated per JSDoc in types.ts) — used by price-hero.tsx for VWAP
- `event.timeframe` in intelligence_data handler — should be `event.tf`

---

## Open Questions

1. **Timeframes builder: new class vs rewrite the service**
   - What we know: `TimeframeBuilderService` shell is complete, needs `TimeframeBuilder` class
   - What's unclear: The service uses `src.core.redis_streams_manager.RedisStreamsManager` — but the class API is more complex than a simple accumulator
   - Recommendation: Implement `TimeframeBuilder` class directly in `src/core/timeframe_builder.py` without rewriting the service. Keep API surface to `start/stop/subscribe_to_symbols/get_metrics`. The bar accumulation logic is straightforward.

2. **AI narrative service: 1m as fallback?**
   - What we know: Narratives only work on 5m/15m signals; those streams are currently empty
   - What's unclear: Should the service be updated to also watch 1m signals while 5m/15m is being fixed?
   - Recommendation: Fix timeframes_builder first. If timeframes_builder takes its own plan task, add 1m to narrative service as interim fallback in the same task.

3. **qualify_instrument fix scope**
   - What we know: SR1H6, 6EH6, 6JH6, BTCH6, BZJ6, NGJ6 fail qualification; fix is `currency="USD"` in `Future()` constructor at `src/providers/ibkr.py:183`
   - What's unclear: This only matters if TWS is running and trying to qualify these. In development with live TWS it affects 6/23 contracts.
   - Recommendation: Fix it in the same plan that covers backend fixes. It's a 1-line change per contract type, low risk.

4. **Session H/L: when is session open?**
   - What we know: Futures trade nearly 24/7 but "session" typically means the RTH (Regular Trading Hours) session for volume context
   - What's unclear: Should session open be the RTH open (9:30 AM ET) or electronic open (6 PM ET previous day)?
   - Recommendation: For Phase 6, use the simplest definition: the `open` of the FIRST 1m bar of the current UTC date. This is pragmatic and visually useful without requiring knowledge of exchange hours.

---

## Sources

### Primary (HIGH confidence)
- Direct Redis inspection: `development:intelligence:ESH6:1m` — confirmed `tf` field name, all tier data populated
- `src/intelligence/schemas.py` — `IntelligenceEvent.tf: str` (not `timeframe`)
- `dashboard/src/hooks/use-market-stream.ts` — `event.timeframe` bug confirmed at line 350
- `dashboard/src/lib/types.ts` — `SmartMoneyData` confirmed missing HMM and liquidity fields
- `services/timeframes_builder_service.py` — confirmed broken import `from src.data.timeframe_builder`
- Live `.venv/bin/python -c "from src.data.timeframe_builder import ..."` — `ModuleNotFoundError` confirmed
- Redis stream inspection: indicators:ESH6:5m = 0 entries, intelligence:ESH6:5m = 0 entries
- Redis stream inspection: signals:ESH6:5m:aggregated = 0 entries (explains silent AI narrative)

### Secondary (MEDIUM confidence)
- `services/ai_narrative_service.py` lines 211-215 — service configured for `["5m", "15m"]` timeframes, reads 5m/15m signal streams
- `src/intelligence/confluence/cross_timeframe.py` — I6 requires `frames["intel_*"]` dict from other TFs
- `src/api/routes/sse.py` — SSE endpoint confirmed working, stream list building correct

### Tertiary (LOW confidence)
- Session H/L handling (no official spec — derived from common trading terminal patterns)
- Flash animation 350ms timing (conventional — not from specification)

---

## Metadata

**Confidence breakdown:**
- Current state audit: HIGH — all from direct Redis and code inspection
- Fix locations: HIGH — all from reading actual source
- Timeframes builder implementation: MEDIUM — class API inferred from usage, core logic is well-understood
- Price hero design: HIGH — spec is locked in CONTEXT.md, implementation pattern is standard React

**Research date:** 2026-02-25
**Valid until:** 2026-03-25 (stable codebase, changes only from Phase 6 execution itself)
