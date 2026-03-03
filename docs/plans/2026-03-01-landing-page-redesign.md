# Landing Page Redesign — Brainstorming Notes

**Date:** 2026-03-01
**Context:** Redesigning dashboard landing page to showcase IndicAgent + live signals

## User Requirements

### Core Purpose
- Show what IndicAgent is with major highlights
- Explain tiered intelligence, shared data bus, institutional-grade tech
- Use generic language — no "IBKR", just "live realtime streaming high frequency"
- Show high-level intelligence generated across assets

### Signal Display
- Show high-confidence signals (>65%)
- CIS-qualified signals should get special prominence ("Both layers" approach)
  - Show all high-confidence signals
  - Badge/mark the ones that also pass CIS filtering
- Show all securities and timeframes, allow filtering by:
  - Timeframe (1m, 5m, 15m, 1h, 4h, 1d)
  - Asset class (Equity, Energy, Metals, Rates, FX, Crypto, Agriculture)

### Current Pain Points
- Existing narrative scroll at bottom is too hard to use
- Can't drill into "how" the signal came to be (need better access to DrillPanel)
- Current landing page doesn't showcase IndicAgent's capabilities

### User Preferences
- **Likes cards** — wants to keep card-based design
- **Likes all three intro approaches** considered:
  1. Feature cards (clean, minimal hero, 3 cards that reveal detail on click)
  2. Interactive diagram (hero with animated pipeline flow, hover for details)
  3. Split hero (full-screen hero, features on left, mini-live-preview on right)

## Design Direction (Recommended Hybrid)

### Section 1: Hero / Intro
**What it shows:** What IndicAgent is, highlights tiered intelligence, shared data bus, institutional-grade infrastructure

**Visual approach (hybrid):**
- Clean tagline at top
- 3 feature cards below:
  - **Tiered Intelligence** — I1 through I8 pipeline
  - **Shared Data Bus** — Canonical event-driven architecture
  - **Institutional Grade** — Production-grade monitoring, real-time processing
- Cards show brief description on hover
- Subtle animated pipeline visualization in background (I1 → I3 → I6 → I7 flow)
- No specific data source mentions — generic "live realtime streaming high frequency"

### Section 2: Live Signals
**What it shows:** High-confidence signals with filtering, CIS-qualified highlighted

**Filter controls (pill-style at top):**
- **Confidence:** All / 65%+ / 75%+
- **CIS status:** All / CIS-only (with badge)
- **Timeframe:** All / 1m / 5m / 15m / 1h / 4h / 1d
- **Asset Class:** All / Equity / Energy / Metals / Rates / FX / Crypto / Agriculture

**Grid layout:**
- Responsive card grid matching filters
- CIS-qualified signals have distinct visual treatment (border glow, badge)

**Signal card content (at glance):**
- Symbol name + display name
- Direction (LONG/SHORT) with confidence % badge
- Entry / Stop Loss
- Main contributing factors (which tiers fired)
- Expand button to drill into full intelligence tiers (opens DrillPanel)

### Section 3: (Optional) Intelligence Pipeline Diagram
**What it shows:** Interactive visualization of the 4-layer intelligence architecture

**Content:**
```
Layer 4: AI Intelligence (I8)  → LLM analysis, narrative generation
Layer 3: Pattern Intelligence (I5-I7) → Pattern detection, confluence, trading signals
Layer 2: Mathematical Intelligence (I1-I4) → Technical indicators, context classification
Layer 1: Data Foundation → Tick/bar collection, aggregation, typed event bus
```

- Hovering/clicking layers reveals more detail
- Animated flow showing data movement through tiers

## Current Dashboard Context

### Existing Components to Leverage
- `SymbolCard` — full intelligence tiers per symbol
- `DrillPanel` — detailed breakdown by tier (I7, I3, I4, I5, SMC, I6, I1)
- `SignalBanner` — high-confidence signal display (currently 75%+ threshold)
- `TimeframeMatrix` — cross-TF signal view
- `NarrativePanel` — AI narratives (scrolling, user finds hard to use)

### Types Available
- `SignalData` — I7 signals with entry, SL, targets, confidence, CIS info
- `IntelligenceTfData` — Per-TF I3/I4/I5/SMC/I6
- `TfSignalMap` — Per-TF signal direction for cross-TF matrix
- `GroupNarrativeData` — Asset group narratives

### Data Flow (from CLAUDE.md)
```
Live Data Streams → Indicator Service (I1) → Market Analysis (I3→I6) →
  Signal Generator (I7) → Signal Ledger + Intelligence Features →
  Feature Writer → TimescaleDB → SSE → Dashboard
```

## Open Questions
1. Should the new landing page replace the current `/` completely, or be a separate route (e.g., `/dashboard` vs `/landing`)?
2. How many signals should show by default (before filtering)?
3. Should signals auto-refresh, or only update when new ones arrive via SSE?
4. Should there be a "detail view" for each signal that shows the full intelligence pipeline breakdown, or just reuse DrillPanel?

## Next Steps
- Install frontend-design skill
- Review this brainstorm with UX/UI specialist input
- Create detailed design specification
- Plan implementation
