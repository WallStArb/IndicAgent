# Indicator Tooltips Design

Date: 2026-02-26
Status: Approved — ready for implementation

## Problem

The dashboard displays 30+ indicator values across I1–I7 tiers with no explanation of what each value means. Traders must already know that RSI 72 is overbought or that BOS means "Break of Structure." New users and context-switching moments need inline guidance.

## Design

### Tooltip component

A single `<Tooltip>` wrapper in `dashboard/src/components/tooltip.tsx`. CSS-only using Tailwind `group/group-hover` — zero JS on hover, zero re-renders, zero new dependencies. Appears above the wrapped element (`bottom-full`). Two-line content: static description on line 1, value-contextual interpretation on line 2 (when the current value changes the meaning).

```
┌──────────────────────────────────────┐
│ Relative Strength Index (0–100)      │  ← always shown
│ Overbought — momentum may be fading  │  ← only when RSI > 70
└──────────────────────────────────────┘
        ▼ (arrow pointing down to label)
   RSI  72
```

### Content file

`dashboard/src/lib/indicator-tooltips.ts` — pure functions, no computation, just string maps and simple range checks on values already in scope. Exported as `getIndicatorTooltip(name, value?) → { description, context | null }`.

### Tooltip placement

- **Indicator grid** (`indicator-grid.tsx`): wraps the `<M>` component's label+value span. Tooltip lifts upward into card header space.
- **Drill panel** (`drill-panel.tsx`): wraps the `<KV>` component's label. More vertical room, same direction (above).

### Coverage

**I1 Indicators (both locations):**
| Indicator | Contextual thresholds |
|-----------|----------------------|
| RSI | < 30 oversold, 30–70 neutral, > 70 overbought |
| MACD | histogram > 0 bullish momentum, < 0 bearish |
| Stoch K/D | < 20 oversold, > 80 overbought; K/D crossover signal |
| CCI | < −100 oversold, > +100 overbought |
| Williams %R | < −80 oversold, > −20 overbought |
| ATR | description only (asset-relative, no universal threshold) |
| BB | description only (price relative to bands shown separately) |
| MFI | < 20 oversold, > 80 overbought (volume-weighted RSI) |
| OBV | description only (trend direction matters, not absolute) |
| VWAP | description only (compare to price in the card) |
| SMA 20/50 | description only (compare to price) |
| EMA 13/21 | description only (crossover signal in relative position) |

**Drill panel only (I3–I7):**
| Field | Contextual |
|-------|-----------|
| I3 Trend integrity | < 0.4 weak, 0.4–0.7 moderate, > 0.7 strong |
| I3 Support/Resistance strength | > 0.7 = significant level |
| I4 Vol regime | low/normal/high/extreme — explanation of each |
| I4 ATR percentile | > 80th = elevated, < 20th = compressed |
| I4 Vol expanding | yes = breakout risk, no = contraction |
| I4 Trend regime | strong_up/weak_up/neutral/weak_down/strong_down |
| I4 Momentum bias | > 0.2 bullish, < −0.2 bearish, between = neutral |
| I5 RSI divergence | bullish/bearish — what it implies |
| I5 BB squeeze | yes/no + bar count context |
| I5 Vol divergence | bullish/bearish explanation |
| I5 Confluence score | > 0.7 high, 0.4–0.7 moderate, < 0.4 low |
| SMC BOS | bullish/bearish break of structure |
| SMC CHoCH | change of character — trend reversal warning |
| SMC FVG | fair value gap — price may revisit |
| SMC Order block | institutional supply/demand zone |
| SMC Sweep | liquidity sweep — potential reversal setup |
| SMC HMM regime | ranging/trending with confidence % |
| SMC BSL/SSL | buy-side / sell-side liquidity levels |
| I6 CTF score | > 0.7 strong alignment, < 0.4 conflicted |
| I6 TFs aligned | N/4 description |
| I6 Trend/Structure alignment | numerical interpretation |

## Implementation Scope

1. `dashboard/src/components/tooltip.tsx` — new `<Tooltip>` wrapper component
2. `dashboard/src/lib/indicator-tooltips.ts` — new content lookup file
3. `dashboard/src/components/indicator-grid.tsx` — wrap `<M>` with `<Tooltip>`
4. `dashboard/src/components/drill-panel.tsx` — wrap `<KV>` with `<Tooltip>` for I1–I7 fields

## Success Criteria

- Hovering any indicator label in the compact grid shows a styled tooltip above it
- Hovering any field label in the drill panel shows a tooltip
- Value-contextual line appears when the current reading crosses a meaningful threshold
- Zero new npm dependencies
- No layout shift or z-index conflicts with existing panels
- TypeScript build passes with 0 errors
