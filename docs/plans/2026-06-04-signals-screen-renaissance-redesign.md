# Signals Screen — Renaissance Redesign

**Date:** 2026-06-04  
**Status:** Approved  
**Scope:** Full redesign of the signals monitoring screen — new zones, upgraded ledger, redesigned detail panel, enriched API

---

## Goal

Transform the signals screen from a historical ledger into an institutional-grade live monitoring terminal that impresses on data depth, visual clarity, and real-time diagnostic power. Every pixel earns its place. Every column is meaningful in all operating contexts.

---

## Page Layout

Seven zones, top to bottom:

```
┌─────────────────────────────────────────────────────────┐
│  1. COMMAND STRIP (sticky) — enhanced                   │
├─────────────────────────────────────────────────────────┤
│  2. LIVE SIGNAL CARDS — horizontal scroll               │
├───────────────────────┬─────────────────────────────────┤
│  3a. SETUP×REGIME     │  3b. ROLLING EDGE SPARKLINE     │
│      HEAT MAP         │  3c. INTRADAY SESSION HEATMAP   │
├───────────────────────┴─────────────────────────────────┤
│  4. ATTRIBUTION ROW (existing, unchanged)               │
├─────────────────────────────────────────────────────────┤
│  5. CLUSTER STRIP (existing, unchanged)                 │
├─────────────────────────────────────────────────────────┤
│  6. FILTER BAR (existing, unchanged)                    │
├─────────────────────────────────────────────────────────┤
│  7. SIGNAL LEDGER (upgraded) │ DETAIL PANEL (redesigned)│
└─────────────────────────────────────────────────────────┘
```

Zones 4-6 are unchanged. All existing functionality is preserved.

---

## Zone 1 — Command Strip (enhanced)

**Existing pills kept:** Signals/session, Hero rate, Avg confidence, Pipeline latency, Edge 7d/30d.

**New additions:**

### Long/Short Skew
- Count of active/pending signals by direction from `/api/signals/active`
- Displayed as `▲ 7 / ▼ 3` with a mini ratio bar
- Concentration risk visible at a glance — if 90%+ is one direction, color amber

### Last-10 Streak Bar
- 10 colored squares showing last 10 resolved signals: green=win, red=loss, gray=expired (ttl)
- Data sourced from new `recent_outcomes` field in `/api/signals/stats` response
- Instant read on whether the edge is hot or cold right now

---

## Zone 2 — Live Signal Cards

Horizontally scrolling strip. One card per `pending`/`active` signal. Ordered: hero tier first, then by `abs(cis_score)` descending. Polls `/api/signals/active` every 30s.

### Card Layout (~190×108px)

```
┌─ HERO ───────────────────────────────┐
│  ES  ▲ LONG         TREND  │ 1m      │
│  failed_breakout                      │
│                                       │
│  CIS +0.72                            │
│  trend      ████████  +0.82           │
│  momentum   ██████    +0.61           │
│                                       │
│  E 5285.50  SL 5278.00  T1 5296.00   │
│  R:R 1.5x           ●●●●●●○○  12b   │
└───────────────────────────────────────┘
```

### Card Elements
- **Left border:** 3px blue for hero, transparent for monitored
- **Glow:** faint blue box-shadow for hero tier
- **Live pulse dot:** blue animated pulse on header if signal fired < 5 minutes ago
- **Symbol + direction:** large, bold, green (long) / red (short)
- **Regime badge:** `TREND` green / `RANGE` amber / `VOL` red — from `hmm_regime_at_fire`
- **Setup name:** prefix-stripped (`trad_`/`ind_`/`smc_`)
- **CIS score:** large, colored by sign
- **Top 2 CIS bucket bars:** sorted by absolute value, labeled with score
- **Price levels:** Entry / Stop / T1
- **R:R:** calculated as `(T1 - entry) / (entry - stop)` for longs, inverted for shorts
- **Age dots:** filled dots = bars elapsed, empty = remaining TTL bars (capped at 12 dots)
- **Staleness badge:** amber `⚠ STALE` if `staleness_score > 0` (hidden when null — column has sparse population currently); `⚠ REGIME SHIFT` if any other active signal on the same `(symbol, timeframe)` has a different `hmm_regime_at_fire` value — pure client-side comparison within the already-fetched active signals list, no new API needed
- **Conflict badge:** red `⚡ CONFLICT` if another active signal exists on same `(symbol, timeframe)` with opposite direction — detected client-side, no API needed
- **Empty state:** "No active signals" centered in muted text

### API changes to `/api/signals/active`
Add to response: `staleness_score`, `staleness_trigger_reason`, `ttl_bars`, `hmm_regime_at_fire`, `bucket_scores`

---

## Zone 3a — Setup × Regime Heat Map

Grid: rows = top 15 setups by total signal volume (resolved), columns = 3 HMM regimes (Trend=0 / Range=1 / Vol=2).

### Cell content
- Primary metric: avg R (default) or win rate (toggle)
- Color: green gradient for positive, red gradient for negative, gray at zero
- Opacity: N<10 = 15%, N<30 = 50%, N≥30 = 100%
- Hover tooltip: `N=412  Win 8.3%  Avg R +0.175`
- Click: filters the Signal Ledger to that `(setup_plugin, hmm_regime_at_fire)` combo

### Metric toggle
Two buttons top-right of panel: `Avg R` / `Win%` — same grid, different coloring

### New API endpoint: `GET /api/signals/heatmap`
```sql
SELECT
  setup_plugin,
  hmm_regime_at_fire AS regime,
  COUNT(*) AS n,
  ROUND(AVG(pnl_r)::numeric, 4) AS avg_r,
  ROUND(AVG(CASE WHEN outcome IN ('target_1','target_1_2','target_full')
    THEN 1.0 ELSE 0.0 END)::numeric, 3) AS win_rate
FROM signal_ledger_full
WHERE outcome IS NOT NULL
  AND pnl_r IS NOT NULL
  AND was_selected = true
  AND timestamp >= NOW() - INTERVAL '90 days'
GROUP BY setup_plugin, hmm_regime_at_fire
ORDER BY SUM(1) OVER (PARTITION BY setup_plugin) DESC, setup_plugin, regime
```
Returns flat array of `{setup_plugin, regime, n, avg_r, win_rate}`. Frontend builds the grid.

---

## Zone 3b — Rolling Edge Sparkline

Pure SVG line chart, no external library. X axis = last 30 trading days. Two series:
- **Daily avg R** (cyan line, primary)
- **7-day rolling avg R** (dimmed white line, context)

Horizontal zero line (dashed). Area fill: red-tinted below zero, green-tinted above. Today's value as a dot + label. Hover shows date + avg R + win rate.

### New API endpoint: `GET /api/signals/edge-series`
```sql
SELECT
  DATE_TRUNC('day', signal_computed_at) AS day,
  COUNT(*) FILTER (WHERE pnl_r IS NOT NULL) AS n,
  ROUND(AVG(pnl_r) FILTER (WHERE pnl_r IS NOT NULL)::numeric, 4) AS avg_r,
  ROUND(AVG(CASE WHEN outcome IN ('target_1','target_1_2','target_full')
    THEN 1.0 ELSE 0.0 END) FILTER (WHERE outcome IS NOT NULL)::numeric, 3) AS win_rate
FROM signal_ledger_full
WHERE was_selected = true
  AND signal_computed_at >= NOW() - INTERVAL '30 days'
GROUP BY 1
ORDER BY 1
```

---

## Zone 3c — Intraday Session Heatmap

Small grid below the sparkline. Rows = hour of day (0-23, trimmed to market hours 9-17), columns = day of week (Mon-Fri). Cell = avg R, colored green/red. Opacity = N. Answers "when during the session does the edge live?"

### New API endpoint: `GET /api/signals/intraday-heatmap`
```sql
SELECT
  EXTRACT(HOUR FROM signal_computed_at AT TIME ZONE 'America/New_York') AS hour,
  EXTRACT(DOW FROM signal_computed_at AT TIME ZONE 'America/New_York') AS dow,
  COUNT(*) FILTER (WHERE pnl_r IS NOT NULL) AS n,
  ROUND(AVG(pnl_r) FILTER (WHERE pnl_r IS NOT NULL)::numeric, 4) AS avg_r
FROM signal_ledger_full
WHERE was_selected = true
  AND signal_computed_at >= NOW() - INTERVAL '90 days'
  AND EXTRACT(DOW FROM signal_computed_at AT TIME ZONE 'America/New_York') BETWEEN 1 AND 5
GROUP BY 1, 2
ORDER BY 1, 2
```

---

## Zone 7 — Signal Ledger (upgraded columns)

Same 28px dense rows, same `@tanstack/react-virtual` scroll. Column changes:

| Col | Before | After | Width | Notes |
|-----|--------|-------|-------|-------|
| Regime | — | colored dot ● | 28px | green=Trend, amber=Range, red=Vol |
| Conf | 0.72 | R:R | 52px | `(T1-entry)/(entry-stop)`, null if no targets |
| Status | "pending" | Exit/Status | 76px | live: colored status pill; resolved: SL/TTL/T1/T2/T3 badge |
| (new) | — | Age/Cap | 52px | live: bars elapsed vs ttl (ages amber→red); resolved: `pnl_r/mfe` capture ratio |

**Full column order:**
```
Time │ Symbol │ TF │ ● Regime │ Setup │ Dir │ R:R │ Tier │ CIS │ Exit │ Outcome │ PnL R │ Age/Cap
```

### Exit column badge colors
- Live: `pending` gray pill, `active` cyan pill, `regime_suppressed` red pill
- Resolved: `SL` red, `TTL` muted gray, `T1` light green, `T2` green, `T3` bright green

### Age/Cap column logic
- `pending`/`active`: `bars_elapsed / ttl_bars` shown as `12b`, colored white→amber→red as ratio increases
- Resolved: `pnl_r / mfe` shown as `0.63`, colored green ≥ 0.7, amber 0.4-0.7, red < 0.4
- Null (no mfe or no ttl): `-`

### API changes to `/api/signals/recent`
Add to response per row: `hmm_regime_at_fire`, `exit_reason`, `mfe`, `ttl_bars`, `bars_in_trade`, targets array (for R:R calculation)

### Filter bar additions
- Regime filter: `All / Trend / Range / Vol` pill toggle (filters on `hmm_regime_at_fire`)
- The heat map click passes `(setup_plugin, regime)` into existing filter state — requires adding `regime` to `FilterState`

---

## Zone 7 — Detail Panel (redesigned)

Six sections, top to bottom. Replaces the current generic key-value grid.

### A. Signal Header
```
ES  ▲ LONG  │  HERO  │  TREND  │  1m  │  fired 14:32:07  (12 bars ago)
failed_breakout                                    CIS +0.72
```
Tier badge (colored), regime badge (colored), setup name, fire timestamp, elapsed bars, CIS score.

### B. Trade Anatomy — Price Ladder
Vertical CSS layout with prices and R-distances:
```
     T3  5310.00   +4.7R
     T2  5302.00   +3.0R
▶    T1  5296.00   +1.5R    ← active target (first unresolved)
●  ENTRY 5285.50
     SL  5278.00   -1.0R
```
Live price marker (if SSE data available) shown between levels. For short signals the ladder is inverted.

### C. CIS Breakdown — Bucket Bars
Six horizontal CSS bars, sorted by absolute value descending:
```
trend         ████████████░░░░  +0.82
momentum      ██████████░░░░░░  +0.61
structure     ████████░░░░░░░░  +0.55
institutional █████░░░░░░░░░░░  +0.15
regime        ███░░░░░░░░░░░░░  +0.19
pattern       ░░░░░░░░░░░░░░░░   0.00
```
Green bars for positive, red for negative. Value label on right.

### D. Setup Edge Context
```
failed_breakout on ES                     N=41,715
Win rate  8.3%     Avg R  +0.175     p=0.002 *
In TREND regime →  9.1%   +0.211     (this signal's regime)
```
Base stats from `setup_performance` table, then regime-conditional row from heatmap data. `*` for p<0.05. If signal is firing in a regime with negative avg R, show amber warning.

### E. Capture Efficiency Bar (resolved only)
Horizontal bar centered on entry:
```
◄─────────────────────────────────────────────►
MAE -1.0R        ENTRY         EXIT     MFE +2.4R
   [███░░░░░░░░░░  ●  ░░░░░░░░████████░░░░░░░░]
                              ▲ +1.5R captured
   Capture efficiency: 63%
```
Red zone left of entry (adverse excursion), green zone right (favorable). Exit marker shown. Null if signal unresolved.

### F. Lifecycle Timeline
```
14:32:07  ◉  Signal fired
14:32:09  ●  Activated at 5285.75   +2 ticks slippage   (2 bars to activation)
14:58:41  ◉  Exited T1              +1.5R               (26 bars held)
```
For pending signals: fire time + live "⏱ waiting for activation — 12 bars" counter.
For active signals: fire time + activation time/price + "⏱ in trade — 8 bars" counter.

### G. Raw Data (collapsible)
Existing bucket_scores JSON + full signal payload. Collapsed by default, chevron toggle.

---

## API Summary

| Endpoint | Change | Data source |
|----------|--------|-------------|
| `GET /api/signals/active` | Add fields: `staleness_score`, `staleness_trigger_reason`, `ttl_bars`, `hmm_regime_at_fire`, `bucket_scores` | `signal_ledger_full` |
| `GET /api/signals/recent` | Add fields: `hmm_regime_at_fire`, `exit_reason`, `mfe`, `ttl_bars`, `bars_in_trade`, `targets` | `signal_ledger_full` |
| `GET /api/signals/stats` | Add field: `recent_outcomes` (last 10 resolved: array of `{outcome, pnl_r}`) | `signal_ledger_full` |
| `GET /api/signals/heatmap` | New endpoint | `signal_ledger_full` aggregation |
| `GET /api/signals/edge-series` | New endpoint | `signal_ledger_full` aggregation |
| `GET /api/signals/intraday-heatmap` | New endpoint | `signal_ledger_full` aggregation |

---

## Frontend Components

| Component | Type | Notes |
|-----------|------|-------|
| `LiveSignalCards` | New | horizontal scroll, card per active/pending signal |
| `SignalCard` | New | individual card, staleness/conflict badges |
| `EdgeIntelligenceStrip` | New | container for heat map + sparklines |
| `SetupRegimeHeatMap` | New | CSS grid, metric toggle, click-to-filter |
| `EdgeSparkline` | New | pure SVG, no library |
| `IntradayHeatMap` | New | CSS grid, hour×dow |
| `SignalLedger` | Upgrade | new columns: Regime dot, R:R, Exit, Age/Cap |
| `SignalDetailPanel` | Redesign | 6 sections replacing key-value dump |
| `CommandStrip` | Upgrade | skew pill, streak bar |
| `FilterBar` | Upgrade | add Regime pill toggle, add `regime` to FilterState |

---

## TypeScript Type Changes

```typescript
// FilterState additions
interface FilterState {
  // ... existing fields ...
  regime: number[];   // [] = all, [0] = trend only, [0,1] = trend+range
}

// LedgerSignal additions
interface LedgerSignal {
  // ... existing fields ...
  hmm_regime_at_fire: number | null;
  exit_reason: string | null;
  mfe: number | null;
  ttl_bars: number | null;
  bars_in_trade: number | null;
  targets: number[];
  r_ratio: number | null;  // computed by API
}
```

---

## Constraints

- No new npm dependencies — sparkline and heat maps are pure SVG/CSS
- All new API endpoints use existing `signal_ledger_full` view — no schema changes
- Conflict detection is pure client-side logic on already-fetched data
- Regime shift detection on cards is client-side — compare `hmm_regime_at_fire` values across active signals for the same `(symbol, timeframe)`; if values differ, the most recent signal wins and older ones show the badge
- `staleness_score` and `staleness_trigger_reason` columns are already populated in `signal_ledger_full`
