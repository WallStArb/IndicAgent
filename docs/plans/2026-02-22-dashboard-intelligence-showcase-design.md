# Dashboard Intelligence Showcase — Design Document

**Date:** 2026-02-22
**Status:** Design / Pre-implementation
**Scope:** `dashboard/` — Next.js 15.4, React 19, Tailwind v4, shadcn/ui

---

## Vision

The IndicAgent dashboard should feel like a **live intelligence instrument**, not a data table. At a glance, a viewer should understand what the market is doing and whether anything is worth acting on. When the AI says "buy", the data should be there to prove it — one drill-down at a time.

The design principle is **progressive disclosure**: calm and minimal at the surface, arbitrarily deep for those who want the raw math.

**Two audiences, one surface:**

| Audience | Entry point | Goal |
|---|---|---|
| External viewer / showcase | Confidence ring + AI narrative | "Is this worth attention?" |
| Internal / power user | Plugin audit layer | "Is this signal correct and why?" |

---

## Information Architecture — The 5 Levels

Each level answers one question. You drill by tapping/clicking. Back collapses.

```
Level 0 — WHAT IS HAPPENING?
  Confidence ring (0–100) · AI narrative prose · Signal direction badge
  Regime ambiance (background tint reflects GARCH vol regime)

        ↓ tap card

Level 1 — ACROSS WHAT?
  Cross-timeframe convergence matrix: 1m · 5m · 15m · 1h · 4h · 1d
  Each cell: green (long) / red (short) / grey (no signal)
  Confluence badge when 4+ timeframes align
  GARCH vol regime label + ATR percentile

        ↓ tap a timeframe cell

Level 2 — WHY LONG / SHORT?
  Tier-by-tier breakdown (I3 → I7) for selected timeframe
  Each tier shows: label · status · brief reason
  Example: "SqueezeExpansion — BLOCKED: GARCH regime=3, vol too high"
  Example: "MeanReversion — LONG: Kalman displacement +1.4σ"

        ↓ tap a tier row

Level 3 — WHAT TRIGGERED IT?
  Plugin-level table: plugin name · raw output value · threshold · pass/fail
  Timestamp of last calculation
  All gates shown including blocked ones — not just what passed

        ↓ tap a plugin value

Level 4 — IS THIS CORRECT?
  Raw calculation view: input values per bar, intermediate steps, final output
  Sparkline of this plugin's output over last N bars
  Comparison to reference value if available (for validation)
```

---

## Visual Design

### Aesthetic
- **Dark OLED** — existing theme kept, deep backgrounds, high contrast
- **Restraint** — most of the time the dashboard is calm and low-contrast
- **Charged state** — when confidence is high + AI narrative fires, the card glows and the narrative rises to dominance
- No blinking, no excessive animation. Motion is purposeful (150–300ms transitions).

### Confidence Ring
- Large circular ring at the top of each SymbolCard
- Derived from: `confluence.ctf_score` (normalized 0–100) weighted with `signal.confidence`
- Color: dim grey (low) → teal (moderate) → bright green/red (high, direction-colored)
- Soft pulse animation only when confidence > 80
- Center of ring: price + direction arrow

### Regime Ambiance
- Subtle background gradient on each card body driven by `context.volatility_regime`:
  - `low` → deep navy (calm)
  - `normal` → default dark (neutral)
  - `high` → warm amber tint (elevated)
  - `extreme` → muted red wash (caution)
- Never garish — opacity ~8–12% max, just enough to register subconsciously

### Cross-Timeframe Matrix (Level 1)
- Compact row of pills: `1m · 5m · 15m · 1h · 4h · 1d`
- Each pill colored by signal direction for that TF
- "CONFLUENCE" badge appears when `ctf_timeframes_aligned >= 4`
- Tapping a pill locks Level 2 to that timeframe

### AI Narrative Elevation
- At rest: narrative lives in a compact footer strip (current `NarrativePanel` behavior)
- **Elevated state** (triggered when `signal.confidence > 0.75` AND narrative is fresh < 5 min):
  - Narrative expands to fill the top third of the card
  - Displayed as prose, not data
  - `action_bias` badge (BULLISH / BEARISH) in corner
  - Card border glows subtly (teal for long, red for short)

### Signal Banner
- When `SignalData` is present with high confidence: a slim banner at card top
- Shows: direction · signal type · confidence % · entry price · stop
- Tapping banner → jumps to Level 2 for the signal's timeframe

---

## Component Plan

### Changes to existing components

**`TradingDashboard`**
- Add multi-timeframe subscription: stream all TFs simultaneously per symbol (or subscribe to CTF summary stream) so Level 1 matrix has per-TF data
- Add `activeCard` state for drill-down tracking

**`SymbolCard`** (refactor)
- Becomes a stateful drill-down container
- Renders Level 0 by default
- Manages which level is active and animates transitions
- Slide-in panel from right for Levels 2–4

### New components

| Component | Level | Description |
|---|---|---|
| `ConfidenceRing` | 0 | Circular ring with animated fill, price center |
| `RegimeAmbiance` | 0 | Background gradient wrapper driven by vol_regime |
| `NarrativeElevated` | 0 | Full expanded narrative card with bias badge |
| `SignalBanner` | 0 | Slim high-confidence signal strip |
| `TimeframeMatrix` | 1 | Cross-TF pill row with per-TF direction coloring |
| `TierBreakdown` | 2 | I3→I7 tier list with status + reason |
| `PluginAuditTable` | 3 | Plugin name / value / threshold / pass-fail table |
| `RawCalculationView` | 4 | Input values, sparkline, reference comparison |

### Data model additions needed

The existing `SymbolData` / `ConfluenceData` types have CTF aggregate scores but not per-TF signal direction. To power the Level 1 matrix:

**Option A (preferred):** Extend `intelligence_data` SSE payload to include per-TF direction array from I6
**Option B:** Subscribe to all 6 timeframes simultaneously and track per-TF `SignalData` in state

For Levels 3–4 (plugin audit): needs a new SSE event type `plugin_audit_data` or a REST endpoint `GET /api/audit/{symbol}/{timeframe}` returning plugin-level detail. This is separate from the live stream — fetched on demand when user drills to Level 3.

---

## Deployment

### Local (dev)
```bash
cd dashboard && npm run dev   # localhost:3000
```

### Public (showcase)
- **Cloudflare Tunnel** → exposes FastAPI backend at a public HTTPS URL
- Dashboard deployed to **Cloudflare Pages** (free, git-connected) or served from FastAPI `StaticFiles`
- `NEXT_PUBLIC_API_BASE_URL` points to the Cloudflare Tunnel URL
- No auth required — read-only, public showcase
- Optional: shared-secret query param for light obscurity if desired

---

## Debug Route

A separate `/debug` route (not linked from the public dashboard) provides:
- All plugin outputs in tabular form for a selected symbol + timeframe
- Signal ledger query: last N signals, full detail
- Indicator health: which plugins are outputting null / stale values
- GARCH/Kalman state inspection
- Reference comparison: our value vs. expected for known formulas (RSI, VWAP, etc.)

This route can also be a slide-in panel from the main dashboard via a `?debug=true` param — accessible to developers without a separate deployment.

---

## Out of Scope (this design)

- Charting / candlestick view (future addition, likely Lightweight Charts)
- User accounts or authentication
- Alert / notification system
- Mobile native app
- Historical replay UI (separate project)

---

## Build Sequence (when ready to implement)

1. **Confidence ring + regime ambiance** on existing SymbolCard — visible immediately with current data
2. **Cross-TF matrix** — requires multi-TF subscription or I6 payload extension
3. **Narrative elevation** — logic gate on `signal.confidence` + narrative freshness
4. **Slide-in drill panels** (Levels 2–3) — shell + animation, then wire real data
5. **Plugin audit endpoint** — backend work, Level 3 data source
6. **Raw calculation view** (Level 4) — most complex, lowest priority
7. **Cloudflare Tunnel + Pages deployment**
8. **Debug route**
