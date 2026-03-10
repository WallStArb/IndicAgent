# Ideas Catalog — Research Backlog Index

**Version:** 1.0.0
**Last Updated:** 2026-03-08
**Purpose:** Single source of truth for all research ideas, their status, and implementation priority.

---

## How This Catalog Works

Each idea is a `.md` file in this directory. This index tracks:

- **Status:** `draft` | `design` | `planned` | `in-progress` | `shipped` | `archived`
- **Priority:** `high` | `medium` | `low` | `future`
- **Milestone:** Which milestone it belongs to (or `standalone`)
- **Tags:** Searchable keywords

**Workflow:**
1. Draft → Design (approved concept, ready for implementation plan)
2. Design → Planned (in `.planning/phases/` or ROADMAP)
3. Planned → In-Progress (active phase work)
4. In-Progress → Shipped (merged to main)
5. Shipped → Archived (move to `docs/archive/` or tag as shipped)

---

## All Ideas

| # | File | Title | Status | Priority | Milestone | Tags | Last Updated |
|---|-------|-------|----------|-----------|-------|--------------|
| 1 | `i6-confluence-expansion.md` | I6 Confluence Expansion — Cross-TF + Cross-Asset | design | high | v1.5? | 2026-03-08 |
| 2 | `renaissance-i7-i8-refinement.md` | Renaissance-Style Intelligence Refinement — 105 ideas across 48 sections | design | high | v1.5+ | 2026-03-07 |
| 3 | `intelligence-redo-brainstorm.md` | Intelligence Palette Expansion — I2 + I3/I4/I5/SMC/I6 depth | archived | high | v1.2 (shipped 2026-03-02) | 2026-03-10 |
| 4 | `regime-adaptive-trading.md` | Regime-Adaptive Trading — HMM + regime-specific models | design | medium | v1.5+ | 2026-02-27 |
| 5 | `renaissance-framing.md` | Renaissance Framing — 10 Simons principles applied to platform | design | — | — | 2026-03-07 |
| 6 | `timeframe-cascade-strategy.md` | Timeframe Cascade Strategy — 1m→5m→15m→30m trade scaling | reference | low | TradeAgent | 2026-02-27 |
| 7 | `tech-stack.md` | Tech Stack — Redpanda, pgvector, TimescaleDB decisions | design | — | — | — |
| 8 | `platform-architecture.md` | Platform Architecture — Unified architecture across 4 products | design | — | Future | — |
| 9 | `intelligence-stack-latency-reduction.md` | Intelligence Stack Latency Reduction — Optimization ideas | design | medium | v1.7+ | 2026-03-10 |
| 10 | `tradeagent-vision.md` | TradeAgent Vision — Autonomous trading app spec | vision | low | TradeAgent | — |
| 11 | `qualagent-vision.md` | QualAgent Vision — Qualitative intelligence platform | vision | low | QualAgent | — |
| 12 | `derivagent-vision.md` | DerivAgent Vision — Derivatives intelligence + options execution | vision | low | DerivAgent | — |
| 13 | `primeagent-vision.md` | PrimeAgent Vision — Portfolio management product | vision | low | PrimeAgent | — |
| 14 | `aegisagent-vision.md` | AegisAgent Vision — Independent risk management | vision | low | AegisAgent | — |
| 15 | `commercialization-retail-saas.md` | Commercialization — Retail SaaS go-to-market | research | low | Future | — |
| 16 | `orderflow-based-setups.md` | Order Flow Based Setups — Microstructure trading | draft | low | future (needs tick data) | — |
| 17 | `trade-journal-auto-documentation.md` | Trade Journal Auto Documentation | draft | low | v1.7+ | — |
| 18 | `momentum-acceleration-second-derivative.md` | Momentum Acceleration (2nd Derivative) Research | shipped | — | v1.6 (shipped 2026-03-10) | 2026-03-10 |
| 19 | `2nd-derivative-indicator-research.md` | 2nd Derivative Indicator Research (ExhaustionScore, AccelerationRegime, SwingMomentum, HMA) | shipped | — | v1.6 (shipped 2026-03-10) | 2026-03-10 |
| 20 | `candlestick-pattern-expansion-research.md` | Candlestick Pattern Expansion Research — 18 patterns spec'd | design | medium | v1.7 | 2026-03-10 |
| 21 | `jim-simons-renaissance-principles.md` | Jim Simons Renaissance Principles — 10 principles reference | reference | — | — | — |

---

## Status Legend

| Status | Meaning | Next Action |
|---------|-----------|--------------|
| `draft` | Rough notes, needs review | Review, refine, promote to `design` |
| `design` | Approved concept, ready for implementation plan | Create `docs/plans/` plan or add to ROADMAP |
| `planned` | In ROADMAP or `.planning/phases/` | Execute via `/gsd:execute-phase` or `/gsd:quick` |
| `in-progress` | Active phase work being implemented | Update status to `shipped` when done |
| `shipped` | Merged to main, feature live | Archive or update to `shipped` status |
| `archived` | Completed and no longer relevant | Keep for historical reference |
| `reference` | Foundational concepts, not directly implementable | Refer to when designing |

---

## Priority Legend

| Priority | Threshold | Examples |
|----------|-----------|----------|
| `high` | Core signal intelligence, immediate alpha impact | I6 confluence, regime gating, I2 events |
| `medium` | Enhances existing signals, requires infrastructure | Cross-asset, market microstructure, correlation tracking |
| `low` | Future product features or long-horizon research | TradeAgent, QualAgent, AegisAgent, DerivAgent |
| `future` | Product vision beyond current scope | All *Agent visions, commercialization |

---

## Milestone Context

| Milestone | Focus | Status |
|-----------|-------|--------|
| **v1.7** | Not yet defined — planning next | — |
| **v1.6** | Signal Quality — signal gate, 2nd-derivative acceleration | Shipped 2026-03-10 |
| **v1.5** | Production Hardening — financial math, circuit breakers, I8 redesign | Shipped 2026-03-10 |
| **v1.4** | Quant Foundation — signal lifecycle, feedback loop, LLM layer | Shipped 2026-03-07 |
| **TradeAgent** | Autonomous trading execution | Vision only, not started |
| **QualAgent** | Qualitative intelligence platform | Vision only, not started |
| **PrimeAgent** | Portfolio management | Vision only, not started |
| **AegisAgent** | Independent risk management | Vision only, not started |
| **DerivAgent** | Derivatives + options execution | Vision only, not started |

---

## Recent Changes

| Date | Action | Details |
|-------|--------|---------|
| 2026-03-10 | Marked shipped | `momentum-acceleration-second-derivative.md`, `2nd-derivative-indicator-research.md` — shipped in v1.6 Phase 24 |
| 2026-03-10 | Archived | `intelligence-redo-brainstorm.md` — v1.2 shipped 2026-03-02 |
| 2026-03-10 | Updated milestones | `i6-confluence-expansion.md` → v1.7+; `candlestick-pattern-expansion-research.md` → design/v1.7; `intelligence-stack-latency-reduction.md` → v1.7+ |
| 2026-03-08 | Added `i6-confluence-expansion.md` | New cross-TF + cross-asset I6 expansion |
| 2026-03-07 | Created `renaissance-i7-i8-refinement.md` | 105 ideas across 48 sections |
| 2026-03-01 | Created `intelligence-redo-brainstorm.md` | v1.1 design (now archived) |

---

## Search Tags

| Tag | Ideas |
|------|--------|
| `i6` | i6-confluence-expansion.md |
| `i7` | renaissance-i7-i8-refinement.md |
| `i2` | intelligence-redo-brainstorm.md |
| `regime` | regime-adaptive-trading.md, renaissance-i7-i8-refinement.md |
| `cross-asset` | i6-confluence-expansion.md, renaissance-i7-i8-refinement.md |
| `correlation` | i6-confluence-expansion.md, renaissance-i7-i8-refinement.md |
| `vix` | i6-confluence-expansion.md, renaissance-i7-i8-refinement.md |
| `sector` | i6-confluence-expansion.md, renaissance-i7-i8-refinement.md |
| `cointegration` | i6-confluence-expansion.md, renaissance-i7-i8-refinement.md |
| `pairs` | i6-confluence-expansion.md, renaissance-i7-i8-refinement.md |
| `momentum` | regime-adaptive-trading.md, renaissance-i7-i8-refinement.md |
| `volatility` | regime-adaptive-trading.md, renaissance-i7-i8-refinement.md |
| `hmm` | regime-adaptive-trading.md |
| `latency` | intelligence-stack-latency-reduction.md |
| `renaissance` | renaissance-framing.md, renaissance-i7-i8-refinement.md |

---

## Notes

- **21 total ideas** cataloged
- **4 in design** status: `i6-confluence-expansion.md` (high), `renaissance-i7-i8-refinement.md` (high), `candlestick-pattern-expansion-research.md` (medium), `intelligence-stack-latency-reduction.md` (medium)
- **2 shipped** in v1.6: `momentum-acceleration-second-derivative.md`, `2nd-derivative-indicator-research.md`
- **1 archived**: `intelligence-redo-brainstorm.md` (v1.2)
- **6 product visions** (TradeAgent, QualAgent, DerivAgent, PrimeAgent, AegisAgent, Platform)
- **1 blocked on data**: `orderflow-based-setups.md` (needs tick-by-tick from IBKR)

**Next steps:**
1. Define v1.7 milestone (`/gsd:new-milestone`)
2. Include `i6-confluence-expansion.md` and `renaissance-gap-analysis.md` Tier 1 items in v1.7
3. Promote `candlestick-pattern-expansion-research.md` from design → planned for v1.7

---

## Related Files

- `.planning/IDEAS.md` — Rough bullet captures (deprecated, use this index)
- `.planning/ROADMAP.md` — Current milestone phases and backlog
- `docs/plans/` — Design docs and architecture decisions
- `.planning/todos/pending/` — Fixes, refactors, small improvements
