# Homepage Refinement — Hero, Pillars, Signal Cards Design

**Date:** 2026-03-06
**Status:** Approved
**Scope:** Landing page UX overhaul — hero tightening, intelligence pillars section, signal card info density, TF-aware signal filtering

---

## Goals

1. Make the pipeline animation the visual star of the hero — currently buried at 40% opacity under cards
2. Tell the platform story clearly — CIS adaptive scoring, GLM-5 narratives, 88-plugin pipeline
3. Signal cards more information-dense — surface regime, ADX, killzone, AMD phase, vol regime, SMC context
4. Surface fresh, actionable signals — 5m/15m dominant, longer TF capped as structural anchors

---

## Section 1: Hero

**Current issues:** `min-h-[60vh]`, animation at 40% opacity, 4 hover-reveal feature cards sitting on top of the animation killing its visual impact. Headline is generic.

**Changes:**
- Height: `~50vh` (reduce from 60vh)
- `PipelineAnimation` opacity: `65%` (up from 40%)
- Remove `FeatureCards` from inside the hero — they move out entirely
- Headline: `"Real-Time Market Intelligence"` (keep)
- Subline: `"8-tier intelligence pipeline · 88 plugins · GLM-5 AI narratives · 24 instruments"` — replace the current vague subtitle
- **Live stat pills** (4 pills, dynamic from `symbolData` already loaded in `LandingPage`):
  - `● 24 Instruments`
  - `● N Active Signals` (count from `filteredSignals` or raw `symbolData`)
  - `● CIS Scoring Live`
  - `● GLM-5 Narratives`
  - Pulsing dot via CSS animation, `var(--accent-cyan)` color
- **CTA button:** Single centered, large — `"Open Dashboard →"` — `var(--accent-cyan)` background with glow shadow. Replaces the small CTA buried in the signals section header.

**CSS variables:** All existing — `var(--landing-bg-gradient)`, `var(--text-primary)`, `var(--accent-cyan)`, `var(--font-display)`.

---

## Section 2: Intelligence Pillars (new)

Placed between hero and live signals section. Replaces both:
- The `FeatureCards` component (removed from hero)
- The "Intelligence Pipeline Architecture" section at the bottom of the page

**3 dark cards** — consistent with `var(--surface-card)` / `var(--border-subtle)`:

| Card | Title | Body |
|------|-------|------|
| 🧠 | **Tiered Intelligence** | I1→I8 pipeline. 88 plugins: technical indicators, volatility models, Smart Money Concepts, pattern detection, signal generation, AI narrative. Regime-aware gating at every layer. |
| 📊 | **CIS + Adaptive Scoring** | Composite Intelligence Score with regime-aware gating. Shadow signals feed adaptive weight learning. Every suppressed signal trains the model. Confidence-gated signal selection. |
| 🤖 | **GLM-5 Narratives** | Per-signal LLM analysis via GLM-5. Group synthesis across 6 asset classes. Confidence-gated (>0.7), staleness-aware. Falls back to local Ollama when needed. |

Layout: `grid grid-cols-1 md:grid-cols-3 gap-4` — consistent with existing pipeline section sizing.

**Removals:**
- Delete `FeatureCards` component usage from `hero-section.tsx`
- Delete `feature-cards.tsx` component (or archive — no longer needed)
- Delete the "Intelligence Pipeline Architecture" section at bottom of `landing/page.tsx`

---

## Section 3: Live Signals

Header stays but CTA moves to hero — only a small secondary `"View all →"` link remains here.

### Signal Filtering — TF-aware staleness + long-TF cap

Replace the current single `oneHourAgo` staleness filter with per-TF logic:

```ts
const TF_STALENESS_MS: Record<string, number> = {
  "1m":  15 * 60_000,   // 15 min
  "5m":  30 * 60_000,   // 30 min
  "15m": 60 * 60_000,   // 1 hour
  "1h":  4 * 3_600_000, // 4 hours
  "4h":  8 * 3_600_000, // 8 hours
  "1d":  24 * 3_600_000,// 24 hours
};
const TF_MAX_SHOWN: Record<string, number> = {
  "1h": 3,
  "4h": 2,
  "1d": 1,
};
```

Apply in `filteredSignals` memo:
1. Check signal age against `TF_STALENESS_MS[tf]` (fallback to 1h)
2. Track count per long TF, skip once `TF_MAX_SHOWN[tf]` is reached
3. Sort remains: confidence desc, then timestamp desc

Result: page shows mostly 5m/15m signals (dominant, fresh), with ≤3 x 1h and ≤2 x 4h as structural anchors.

---

## Section 4: Signal Card — Info Density

All fields are already in the `intelligence:SYMBOL:TF` SSE stream (i1/i4/smc JSONB tiers in `IntelligenceEvent`). No backend changes. Requires hook mapping + card UI.

### New fields to surface

| Field | Source tier | Display |
|-------|-------------|---------|
| `regime` | I4 | Small badge: `TRENDING` / `MEAN_REV` / `RANGING` |
| `adx_14` + `plus_di_14` / `minus_di_14` | I1 | `ADX 32 ↑` inline with DI direction |
| Killzone | I4/SMC (`in_london_killzone`, `in_ny_killzone`, etc.) | Session tag: `NY AM` / `London` / `Asia` when active |
| `amd_phase` | SMC | `ACCUM` / `MANIP` / `DIST` badge when present |
| GARCH vol regime | I4 (`garch_vol_regime`) | `VOL ↑` / `VOL ↓` tag |
| SMC zone | SMC (`in_demand_zone`, `in_supply_zone`) | `IN DEMAND` / `IN SUPPLY` indicator if active |

### Layout placement
Add a compact intelligence context row between the price strip and the footer tags row:

```
[Entry 4872.50 | SL 4865.00]
[T1 4885.00 2.1R · T2 4900.00 4.5R]
─────────────────────────────────────
[TRENDING] [ADX 38 ↑] [NY AM] [MANIP]   ← new row
─────────────────────────────────────
[signal_type] [setup_plugin] [entry_type]
[🧠 narrative text...]
```

Only show fields that are non-null and meaningful (e.g. killzone only when active, AMD only when detected).

---

## Files Affected

- `dashboard/src/app/landing/page.tsx` — TF-aware filtering, remove pipeline section, move CTA
- `dashboard/src/components/landing/hero-section.tsx` — height, animation opacity, live pills, CTA, remove FeatureCards
- `dashboard/src/components/landing/feature-cards.tsx` — delete
- `dashboard/src/components/landing/signal-card.tsx` — add intelligence context row
- `dashboard/src/hooks/use-market-stream.ts` — verify I1/I4/SMC fields mapped in SymbolData
- `dashboard/src/lib/types.ts` — extend SymbolData / IntelligenceData types if needed

---

## Out of Scope

- Per-symbol dashboard pages (separate initiative)
- Tooltips on I1–I8 indicators (separate todo #5)
- AI narrative panel refinement (separate todo)
- Backend changes — all data already in stream
