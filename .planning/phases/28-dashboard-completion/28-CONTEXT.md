# Phase 28: Dashboard Completion - Context

**Gathered:** 2026-03-12
**Status:** Ready for planning
**Source:** Design doc `docs/plans/2026-03-11-dashboard-completion-design.md` + codebase audit

<domain>
## Phase Boundary

Surface the full intelligence pipeline in the dashboard. Four gaps remain:
1. **I7 Signal Scorecard** — `all_ranked` data exists in `intelligence_i7` stream but SSE never subscribes; dashboard is blind to which signals competed and why the winner won.
2. **Drill panel signal history** — populated from in-memory SSE accumulation (empty on fresh load); needs DB-backed `GET /api/signals/recent` merged with SSE history.
3. **I4 GARCH/Kalman field gaps** — computed every bar, not shown in drill panel at all.
4. **Tier tooltips** — I1–I8 labels are opaque; no hover explanations.

</domain>

<decisions>
## Implementation Decisions

### Already Done — Do NOT Re-implement
- `bsl_dist_atr` and `ssl_dist_atr` are already in `drill-panel.tsx` BSL/SSL rows (lines 477, 482)
- `premium_discount_pct` already shown in drill-panel.tsx SMC section (lines 496-499)
- `SignalData.resolved`, `.outcome`, `.exit_price`, `.pnl_r` already in `dashboard/src/lib/types.ts` (from Phase 27-05 NO-OP verification)

### SSE Domain for Signal Scorecard
- Stream key: `intelligence_i7:SYMBOL:TF` (already published by `signal_generator_service`)
- SSE event type: `signal_scorecard`
- Payload format: `{"ts": "...", "symbol": "ES", "tf": "1m", "data": "[{...}]"}` where `data` is JSON-encoded string (same pattern as other I7 payloads)
- Wire into `_build_stream_list()` in `src/api/routes/sse.py` alongside existing `intelligence:` streams

### Signal Scorecard Component Layout
```
┌─ Signal Scorecard ─────────────────────────────┐
│ 3 fired · 2 regime-gated · winner: TrendFollow │
│                                                  │
│ 1 ● TrendFollowing    ▲ 0.87  ✓ eligible        │
│ 2 ○ MomentumBreakout  ▲ 0.74  ✗ regime_prob     │
│ 3 ○ VWAPDeviation     ▼ 0.61  ✗ regime_duration │
└──────────────────────────────────────────────────┘
```
- Rank 1 = filled dot (winner), 2+ = open dot
- Direction: ▲ long, ▼ short
- Suppression reason mapping: `"regime_prob"` → "< 60% conf", `"regime_duration"` → "< 5 bars", `"regime_type"` → "wrong regime"
- Empty state: "No signals this bar"
- No cross-bar carry — scorecard is current bar only

### DB Signal History Endpoint
- Path: `GET /api/signals/recent?symbol=ESH6&timeframe=1m&limit=20`
- Wire into existing `src/api/routes/signals.py`
- Returns `signal_ledger` rows ordered by `computed_at DESC`
- Response fields: `signal_id`, `setup_plugin`, `signal_type`, `direction`, `entry_price`, `stop_loss`, `confidence`, `status`, `outcome`, `exit_price`, `computed_at`, `timeframe`
- Frontend: fetch on drill panel open, merge with `signalsHistory` deduplicated by `signal_id`, SSE version wins on conflict

### I4 Fields to Add to Drill Panel
GARCH section (new group in I4 context section):
- `garch_sigma`, `garch_vol_ratio`, `garch_vol_regime` (low/mid/high), `garch_shock`

Kalman section (new group in I4 context section):
- `kalman_trend`, `kalman_slope`, `kalman_price_position`, `kalman_uncertainty`

SMC additional fields (add to existing SMC section — bsl/ssl already have dist_atr wired):
- `bsl_touches`, `bsl_significance`
- `ssl_touches`, `ssl_significance`
- `price_in_premium` (bool), `equilibrium_level`

### Tier Tooltip Copy
- **I1:** "Technical Indicators — 25 indicators (RSI, MACD, Bollinger, ATR, ADX, HMA, etc.). Foundation: raw math on price/volume."
- **I2:** "Derivative Events — Acceleration, exhaustion, momentum regime. Second-derivative layer: what's happening to the indicators."
- **I3:** "Market Structure — Swing points, S/R levels, trend integrity, Fibonacci, VWAP, session levels."
- **I4:** "Statistical Context — GARCH volatility, Kalman trend, HMM regime, BOCPD change detection. Adaptive statistical models."
- **I5:** "Pattern Detection — RSI divergence, BB squeeze, candlestick patterns, volume divergence. Structural setups forming."
- **SMC:** "Smart Money Concepts — BOS/CHoCH, FVG, order blocks, sweeps, killzones, AMD phase, premium/discount."
- **I6:** "Confluence Score — Cross-timeframe alignment: how many TFs agree with the current signal direction."
- **I7:** "Signal Generator — 17 setup plugins competing per bar. Winner selected by CIS composite scoring + regime eligibility."
- **I8:** "AI Narrative — LLM synthesis of I1–I7 outputs into a structured trading context. Three-tier: action tag → short → deep."
- Implement via Radix UI `Tooltip` (already available as transitive dep via shadcn/ui)
- One `TierTooltip` component with content map — no per-file duplication

### Claude's Discretion
- Exact drill panel placement of GARCH/Kalman groups (below existing I4 section or as collapsible)
- Tooltip trigger styling (underline, info icon, or bare label)
- Whether signal scorecard is in a collapsible section or always expanded

</decisions>

<specifics>
## Specific Implementation References

**SSE wiring:**
```python
# src/api/routes/sse.py — add to _build_stream_list()
from src.core.stream_keys import intelligence_i7  # existing function
for symbol in symbols:
    for tf in timeframes:
        streams.append(intelligence_i7(env_prefix, symbol, tf))
```

**Stream → event type mapping in sse.py:**
- `intelligence_i7:SYMBOL:TF` → event type `signal_scorecard`

**Frontend types to add in types.ts:**
```typescript
export interface RankedSignal {
  setup_type: string;
  confidence: number;
  direction: number;
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

**State in SymbolData (use-market-stream.ts):**
- Add `scorecardByTf: Record<string, SignalScorecardData>`
- Handle `signal_scorecard` event: `JSON.parse(payload.data)` → update `scorecardByTf[tf]`

**DB endpoint SQL sketch:**
```sql
SELECT signal_id, setup_plugin, signal_type, direction,
       entry_price, stop_loss, confidence, status, outcome,
       exit_price, computed_at, timeframe
FROM signal_ledger
WHERE symbol = $1 AND ($2::text IS NULL OR timeframe = $2)
ORDER BY computed_at DESC
LIMIT $3
```

</specifics>

<deferred>
## Deferred Items

- I3 Fib/Value Area/Session levels/Weekly pivots — large number of fields, needs new collapsible section layout
- I5 Chart patterns (dt_db, hs, triangle, flag) — need visual layout decisions
- MTF vol divergence scores — needs cross-TF data flow design
- `next build` + nginx production mode — deferred to Auth phase

</deferred>

---

*Phase: 28-dashboard-completion*
*Context gathered: 2026-03-12 via design doc + codebase audit*
