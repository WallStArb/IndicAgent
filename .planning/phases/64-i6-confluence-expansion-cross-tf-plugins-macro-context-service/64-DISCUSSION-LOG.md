# Phase 64: I6 Confluence Expansion - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-08
**Phase:** 64-I6 Confluence Expansion
**Areas discussed:** Plan split, Macro scope, I7 consumption, Schema strategy

---

## Tier 1 Scope + Plan Split

| Option | Description | Selected |
|--------|-------------|----------|
| Match ROADMAP | Plan 01 = CrossTFMomentumDivergence only; Plan 03 = remaining 4 Tier 1. Validation gate between. | ✓ |
| Bundle all 5 in Plan 01 | All Tier 1 plugins in one plan. Faster planning but harder validation. | |
| One plan per plugin | 5 separate plans. Maximum discipline but heavy overhead for identical patterns. | |

**User's choice:** Match ROADMAP
**Notes:** Renaissance principle — plan architecture coherently, execute with ruthless validation gates. CrossTFMomentumDivergence establishes the pattern; remaining 4 are structurally identical.

---

## MacroContextComputeAgent Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Factor factory | MacroContextComputeAgent runs self-contained macro factor plugins from src/intelligence/macro/. Start with 3 factors. Each factor independent, testable. | ✓ |
| Monolithic service | All macro logic as methods in MacroContextComputeAgent. Simpler initially but harder to extend. | |

**User's choice:** Factor factory
**Notes:** Renaissance approach — build the factory, not the product. Each macro factor is an independent module. Adding a new factor = new file + register. Start with 3 orthogonal factors: USD strength (currency/risk), yield curve slope (rates/growth), flight-to-quality (risk sentiment). Initial 3 need ~10 instruments (4 FX + 4 rate futures + TLT + SPY + VX).

**User framing:** "Design like Renaissance would. Senior engineer/quant perspective. Jim Simons standards. Modularity, reuse, separation of concerns, balance efficiency with simplicity."

---

## I7 Consumption + _shadow Wiring

| Option | Description | Selected |
|--------|-------------|----------|
| Capture-only until validated | New I6 fields in _shadow via capture_confluence_features(). NOT wired into I7 confidence until p < 0.05, N≥30. | ✓ |
| Wire into confidence immediately | New fields captured AND wired into I7 confidence. Faster feedback but risks unvalidated factors. | |

**User's choice:** Capture-only until validated
**Notes:** "Capture everything, use nothing until proven." Fields flow through pipeline naturally (I6Confluence schema → DB → _shadow). The validation gate controls whether they influence trading decisions. Post-validation wiring is a separate follow-up task.

---

## Schema Growth Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Flat, split later | Keep single I6Confluence TypedDict. Split only if >40 fields with concrete reason. | ✓ |
| Split now into sub-schemas | I6TFConfluence + I6AssetConfluence. More organized but premature complexity. | |

**User's choice:** Flat, split later
**Notes:** 38 fields is not a problem for TypedDict, JSONB, or memory (~400 bytes/instance). Premature splitting adds code, tests, union types without measurable benefit. Architecture note already says "future concern — not actionable now."

---

## Folded Todos

| Todo | Folded? | Reason |
|------|---------|--------|
| 028 (continuous gradients) | Partial — IC fix only | IC fix is prerequisite for validation (signal_metrics_ic all NULL). Gradient audit of existing I1-I7 stays as separate todo. |
| 011 (cross-asset pair identifiers) | Yes | MacroContextComputeAgent needs shared constants for FX pairs, rate futures, ETFs. |

## Claude's Discretion

- Exact gradient formula parameters (thresholds, lookback windows)
- BaseAgent inheritance pattern for MacroContextComputeAgent
- Test fixture patterns
- Kafka consumer group naming

## Deferred Ideas

- Gradient-first audit of existing I1-I7 plugins (stays as separate todo from #028)
- Tier 2 macro factors (credit, sectors, factor, crypto, EM) — after initial 3 prove signal
- Tier 3 ideas (VP confluence, cascade, correlation stress, lead-lag, VIX term structure)
- Dashboard multi-dimensional confluence visualization
- Schema split into sub-schemas (only if >40 fields)
