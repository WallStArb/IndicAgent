# Design: Dashboard Completion

**Date:** 2026-03-11
**Status:** Shipped — signal-banner.tsx, signal-alert-strip.tsx, all components present
**Milestone:** v1.8
**Related todos:**
- `.planning/todos/pending/2026-03-06-dashboard-intelligence-field-gaps.md`
- `.planning/todos/pending/2026-03-11-drill-panel-signal-history-from-db.md`
- `.planning/todos/pending/2026-02-27-add-tooltips-to-intelligence-level-indicators.md`
- `.planning/todos/pending/2026-02-27-add-signal-history-view-to-dashboard.md`

---

## Problem

The intelligence pipeline produces rich data — but the dashboard doesn't fully surface it:

1. **I7 all_ranked is invisible.** The signal generator ranks all fired signals per bar (with regime eligibility, suppression reasons, composite rank) but only the winner reaches the UI. The "Signal Scorecard" — which setups competed, which won, which were suppressed and why — is never shown.

2. **Drill panel signal history is empty on load.** `RecentSignals` is populated from in-memory SSE history accumulated since page load. After a restart or refresh, it's always empty even if signals fired in the last hour.

3. **Intelligence field gaps.** Several I3/I4/I5 fields computed in the pipeline (GARCH/Kalman, Fib levels, chart patterns, SMC BSL/SSL premium/discount) are not surfaced in the drill panel.

4. **No tier tooltips.** The I1–I8 tier labels have no explanation — the UI is opaque to anyone who isn't already familiar with the pipeline architecture.

---

## Renaissance Framing

> "Instrument everything. No data point left uncaptured."

The full signal competition result exists — every bar, every symbol, every TF. Not surfacing it wastes signal about *what the model is doing and why*. The suppression reason on a rejected signal is often as informative as the winner itself. The dashboard should surface this.

---

## Design

### 1. I7 All-Ranked Panel (Signal Scorecard)

**Problem:** `intelligence_i7:SYMBOL:TF` stream exists and is published by `signal_generator_service` on every bar. It contains `all_ranked` — all fired signals with confidence, composite_rank, regime_eligible, suppression_reason. SSE does not subscribe to this stream; it's completely unreachable by the dashboard.

**What the payload contains (per signal in all_ranked):**
```json
{
  "setup_type": "trend_long",
  "confidence": 0.87,
  "direction": 1,
  "regime_eligible": true,
  "suppression_reason": null,
  "entry": 4521.50,
  "stop": 4515.25,
  "target": 4535.00,
  "composite_rank": 1,
  "is_winner": true
}
```

**Backend changes:**

`src/api/routes/sse.py` — add `intelligence_i7` to `_build_stream_list()`:
```python
from src.core.stream_keys import intelligence_i7  # existing function

# In _build_stream_list(), alongside intelligence:
for symbol in symbols:
    for tf in timeframes:
        streams.append(intelligence_i7(env_prefix, symbol, tf))
```

Parse event: stream key `intelligence_i7:SYMBOL:TF` → SSE event type `signal_scorecard`.

Payload is `{"ts": "...", "symbol": "ES", "tf": "1m", "data": "[...]"}` — `data` is a JSON-encoded string (same pattern as other I7 payloads). Parse `data` field as JSON to get the array.

**Frontend changes:**

`dashboard/src/lib/types.ts` — add type:
```typescript
export interface RankedSignal {
  setup_type: string;
  confidence: number;
  direction: number;       // 1 = long, -1 = short, 0 = none
  regime_eligible: boolean;
  suppression_reason: string | null;
  entry: number | null;
  stop: number | null;
  target: number | null;
  composite_rank: number;
  is_winner: boolean;
}

export interface SignalScorecardData {
  ts: string;
  symbol: string;
  tf: string;
  ranked: RankedSignal[];
}
```

`use-market-stream.ts` — handle `signal_scorecard` event. Add `scorecardByTf: Record<string, SignalScorecardData>` to SymbolData. Update on every `signal_scorecard` event for the current symbol.

**New component: `signal-scorecard.tsx`**

Displayed in drill panel below the I7 Signal section.

Layout:
```
┌─ Signal Scorecard ─────────────────────────────┐
│ 3 fired · 2 regime-gated · winner: TrendFollow │
│                                                  │
│ 1 ● TrendFollowing    ▲ 0.87  ✓ eligible        │
│ 2 ○ MomentumBreakout  ▲ 0.74  ✗ regime_prob     │
│ 3 ○ VWAPDeviation     ▼ 0.61  ✗ regime_duration │
└──────────────────────────────────────────────────┘
```

- Rank badge: 1 = filled dot (winner), 2+ = open dot
- Direction arrow: ▲ long, ▼ short
- Confidence: percentage
- Eligibility: ✓ green / ✗ amber + suppression_reason label
- Suppression reasons mapped: `"regime_prob"` → "< 60% conf", `"regime_duration"` → "< 5 bars", `"regime_type"` → "wrong regime"
- If `all_ranked` is empty or null: show "No signals this bar"
- No signals from previous TF carried forward — scorecard is current bar only

---

### 2. Drill Panel Signal History from DB

**Problem:** `RecentSignals` uses in-memory SSE history (`signalsHistory` accumulated since page load). On fresh load it's always empty.

**Solution:** New endpoint + merge strategy.

**Backend: new endpoint**

`GET /api/signals/recent?symbol=ESH6&timeframe=1m&limit=20`

Returns `signal_ledger` rows ordered by `computed_at DESC`. Response shape is a subset of `SignalData` — enough to render the signal card:

```json
{
  "signals": [
    {
      "signal_id": "uuid",
      "setup_plugin": "trad_TrendFollowing",
      "signal_type": "trend_long",
      "direction": 1,
      "entry_price": 4521.50,
      "stop_loss": 4515.25,
      "confidence": 0.87,
      "status": "expired",
      "outcome": "ttl_expired_ahead",
      "exit_price": null,
      "computed_at": "2026-03-11T14:23:45Z",
      "timeframe": "1m"
    }
  ]
}
```

Wire into existing signals router (`src/api/routes/signals.py`) as a new path.

**Frontend: mount effect + dedup merge**

In `DrillPanel` (or wherever RecentSignals renders), on panel open:
```typescript
useEffect(() => {
  if (!open) return;
  fetch(`/api/signals/recent?symbol=${symbol}&timeframe=${timeframe}&limit=20`)
    .then(r => r.json())
    .then(data => {
      // Merge with live SSE history, dedup by signal_id, sort by computed_at DESC
      setDbSignals(data.signals);
    });
}, [open, symbol, timeframe]);
```

Display: merged list, deduped by `signal_id`. Live SSE signals take precedence (they have more fields including `intelligence_snapshot`). DB-only signals show status/outcome badge if resolved.

---

### 3. Intelligence Field Gaps (Drill Panel)

Remaining gaps from the field audit. These are already computed in the pipeline — just not surfaced.

**Scope for v1.8 (high signal-to-effort):**

**GARCH / Kalman (I4)** — add to the I4 Context section in drill panel:
- `garch_sigma`, `garch_vol_ratio`, `garch_vol_regime` (low/mid/high), `garch_shock`
- `kalman_trend`, `kalman_slope`, `kalman_price_position`, `kalman_uncertainty`

**SMC BSL/SSL details** — already partially shown; add:
- `bsl_dist_atr`, `bsl_touches`, `bsl_significance`
- `ssl_dist_atr`, `ssl_touches`, `ssl_significance`

**SMC Premium/Discount** — add to SMC section:
- `price_in_premium` (bool), `premium_discount_pct`, `equilibrium_level`

**Deferred to v1.9+ (lower signal-to-effort or requires new layout):**
- I3 Fib/Value Area/Session levels/Weekly pivots — large number of fields, needs a new collapsible section
- I5 Chart patterns (dt_db, hs, triangle, flag) — need visual layout decisions
- MTF vol divergence scores — needs cross-TF data

---

### 4. I-Tier Tooltips

Add hover tooltips to each tier label (I1, I2, I3, I4, I5, SMC, I6, I7, I8) in the dashboard header and drill panel.

**Implementation:** Radix UI `Tooltip` (already a transitive dep via shadcn/ui). Simple wrapper:

```typescript
<TierTooltip tier="I1" label="Technical Indicators">
  23 indicators: RSI, MACD, Bollinger Bands, ATR, Stochastic, ADX, etc.
  Foundation layer — all downstream tiers build on these outputs.
</TierTooltip>
```

One component, one content map — no per-file duplication.

**Tooltip copy:**
- **I1:** "Technical Indicators — 25 indicators (RSI, MACD, Bollinger, ATR, ADX, HMA, etc.). Foundation: raw math on price/volume."
- **I2:** "Derivative Events — Acceleration, exhaustion, momentum regime. Second-derivative layer: what's happening to the indicators."
- **I3:** "Market Structure — Swing points, S/R levels, trend integrity, Fibonacci, VWAP, session levels."
- **I4:** "Statistical Context — GARCH volatility, Kalman trend, HMM regime, BOCPD change detection. Adaptive statistical models."
- **I5:** "Pattern Detection — RSI divergence, BB squeeze, candlestick patterns, volume divergence. Structural setups forming."
- **SMC:** "Smart Money Concepts — BOS/CHoCH, FVG, order blocks, sweeps, killzones, AMD phase, premium/discount."
- **I6:** "Confluence Score — Cross-timeframe alignment: how many TFs agree with the current signal direction."
- **I7:** "Signal Generator — 17 setup plugins competing per bar. Winner selected by CIS composite scoring + regime eligibility."
- **I8:** "AI Narrative — LLM synthesis of I1–I7 outputs into a structured trading context. Three-tier: action tag → short → deep."

---

## Phase Breakdown (for plan writing)

| Plan | Scope | Est. tasks |
|------|-------|-----------|
| 28-01 | SSE: wire `intelligence_i7` domain + `signal_scorecard` event | 3 tasks |
| 28-02 | Types + hook: `RankedSignal`, `SignalScorecardData`, `scorecardByTf` state | 3 tasks |
| 28-03 | New component: `signal-scorecard.tsx` with regime gating display | 4 tasks |
| 28-04 | Backend: `GET /api/signals/recent` endpoint | 3 tasks |
| 28-05 | Drill panel: DB signal history on open, merge + dedup | 3 tasks |
| 28-06 | Drill panel: GARCH/Kalman + BSL/SSL + premium/discount field groups | 3 tasks |
| 28-07 | Tier tooltips: `TierTooltip` component + wire to all tier labels | 3 tasks |

7 plans, ~22 tasks total.

---

## What Is NOT Changing

- SSE event format for existing domains — no breaking changes
- `intelligence_i7` stream publication — `signal_generator_service` already publishes it correctly
- `signal_ledger` schema — no DB migrations needed for signal history
- `signalsHistory` in-memory accumulation — still runs, merged with DB results
- `SymbolData.signal` / `signalsByTf` — unchanged, Phase 27 handles resolved state

---

## Data Flow

```
signal_generator_service
  → xadd intelligence_i7:SYMBOL:TF {ts, symbol, tf, data: JSON(all_ranked)}

SSE endpoint (sse.py)
  intelligence_i7:SYMBOL:TF → SSE event type "signal_scorecard"
  payload: {symbol, tf, ts, data: "[{...}, {...}]"}

use-market-stream.ts
  signal_scorecard handler:
    parse payload.data (JSON.parse)
    update scorecardByTf[tf]

DrillPanel
  <SignalScorecard data={scorecardByTf[timeframe]} />

DrillPanel (on open)
  GET /api/signals/recent?symbol=ES&timeframe=1m&limit=20
  merge with signalsHistory, dedup by signal_id
  display merged list with status/outcome badges
```

---

## Testing Strategy

- **Unit:** SSE stream list includes `intelligence_i7` for each symbol/TF combination
- **Unit:** `signal_scorecard` payload is correctly parsed — `data` field JSON-decoded to array
- **Unit:** `SignalScorecard` renders winner, suppressed signals, empty state
- **Unit:** Suppression reason label mapping covers all 3 reasons
- **Unit:** `GET /api/signals/recent` returns correct signals for symbol/timeframe/limit
- **Unit:** Signal dedup merge — same `signal_id` from DB + SSE → single entry, SSE version wins
- **Unit:** TierTooltip renders correct content for each tier key
- **Integration:** SSE snapshot delivers `signal_scorecard` entries on connect
