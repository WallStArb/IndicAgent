# Phase 64: I6 Confluence Expansion - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-08 (original), 2026-04-23 (Renaissance review)
**Phase:** 64-I6 Confluence Expansion
**Areas discussed:** Plan split, Macro scope, I7 consumption, Schema strategy, Renaissance refinement

---

## Tier 1 Scope + Plan Split

| Option | Description | Selected |
|--------|-------------|----------|
| Match ROADMAP | Plan 01 = CrossTFMomentumDivergence only; Plan 03 = remaining 4 Tier 1. Validation gate between. | ✓ (original) |
| Bundle all 5 in Plan 01 | All Tier 1 plugins in one plan. Faster planning but harder validation. | |
| One plan per plugin | 5 separate plans. Maximum discipline but heavy overhead for identical patterns. | |

**Original choice:** Match ROADMAP
**Renaissance refinement (2026-04-23):** Keep same structure but swap macro to Plan 03 (deferred). Cheapest features first.

---

## MacroContextComputeAgent Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Factor factory | MacroContextComputeAgent runs self-contained macro factor plugins from src/intelligence/macro/. Start with 3 factors. Each factor independent, testable. | ✓ (original) |
| Monolithic service | All macro logic as methods in MacroContextComputeAgent. Simpler initially but harder to extend. | |

**Original choice:** Factor factory
**Notes:** Factor factory pattern retained. Architecture changed — see next section.

---

## Renaissance Review (2026-04-23)

### MacroContextComputeAgent as Separate Service vs Merged into CrossAssetComputeAgent

| Option | Description | Selected |
|--------|-------------|----------|
| Separate MacroContextComputeAgent | New service, new topic (`intelligence.macro_context`), new systemd unit, new consumer group. Independent lifecycle and scaling. | (original, revised) |
| Merge into CrossAssetComputeAgent | Extend existing service to also subscribe to `topic_market_bars` for macro instruments. Compute macro factors alongside EQ_INDEX features. Publish via existing `topic_cross_asset`. Zero new operational overhead. | ✓ |
| Compute in-process in pipeline | Compute macro factors within IntelligencePipelineComputeAgent. Cheapest but can't work — pipeline only receives bars for trading instruments, not FX/rates/ETFs. | |

**Renaissance choice:** Merge into CrossAssetComputeAgent
**Rationale:**
1. **One service, one domain.** Cross-asset intelligence is one conceptual domain. Two services doing the same thing (subscribe to market data, compute cross-market features, publish to Kafka) violates separation of concerns at the architecture level.
2. **Maintenance cost.** Every new service adds: 1 systemd unit, 1 Kafka topic, 1 consumer group, cache staleness management, deploy coordination, debugging complexity. The compute savings (avoiding ~50 redundant trivial computations per bar) don't justify the maintenance cost.
3. **Proven pattern.** `frames["cross_asset"]` injection already exists. Macro factors just add keys to the same payload. No new injection point, no new cache variable, no pipeline code changes.
4. **Jim Simons standard.** Simplest architecture that works. Don't optimize O(50 × trivial_compute) at the cost of an entire microservice.

### IC Fix — Already Shipped

| Item | Status | Impact on Plans |
|------|--------|-----------------|
| `compute_ic()` continuous pnl_r | ✅ Shipped (Phase 60/63.2) | Plan 01 Task 1 (IC fix) entirely removed |
| `compute_ic_metrics()` passes pnl_r | ✅ Shipped | No changes needed |

### Validation Gate Strengthening

| Gate | Original | Renaissance | Rationale |
|------|----------|-------------|-----------|
| Statistical significance | p < 0.05 | p < 0.01 (Bonferroni for 5 tests) | Testing 5 plugins, not 1. Uncorrected p < 0.05 guarantees false positives. |
| Effect size | None | IC > 0.05 | Significance alone is insufficient. Tiny IC with low p = enough data to detect a negligible effect. |
| Regime segmentation | None | Optional flag in validation script | A feature that only works in one regime is still useful, but we need to know WHICH regime. |

### Plan Order Swap

| Original | Renaissance | Rationale |
|----------|-------------|-----------|
| Plan 01: IC fix + first plugin + constants | Plan 01: First plugin + constants + validation script | IC fix already shipped. Plan 01 is now purely new work. |
| Plan 02: MacroContextComputeAgent (new service) | Plan 02: 4 remaining cross-TF plugins | Cheapest infrastructure first. In-process plugins cost nothing. |
| Plan 03: 4 remaining cross-TF plugins | Plan 03: Macro factors (merged, deferred) | Don't build infrastructure until cross-TF plugins prove signal. |

---

## I7 Consumption + _shadow Wiring

| Option | Description | Selected |
|--------|-------------|----------|
| Capture-only until validated | New I6 fields in _shadow via capture_signal_features(). NOT wired into I7 confidence until p < 0.05, N≥30. | ✓ |
| Wire into confidence immediately | New fields captured AND wired into I7 confidence. Faster feedback but risks unvalidated factors. | |

**Choice:** Capture-only until validated
**Notes:** Unchanged from original. "Capture everything, use nothing until proven." Shadow-only wiring confirmed correct by Renaissance review.

---

## Schema Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Flat, split later | Keep single I6Confluence TypedDict. Split only if >40 fields with concrete reason. | ✓ |
| Split now into sub-schemas | I6TFConfluence + I6AssetConfluence. More organized but premature complexity. | |

**Choice:** Flat, split later
**Notes:** Unchanged. 16 → ~26 after Tier 1. Splitting premature.

---

## Folded Todos

| Todo | Folded? | Reason |
|------|---------|--------|
| 028 (continuous gradients / IC fix) | Dropped | IC fix already shipped (Phase 60/63.2). Gradient audit stays as Phase 65. |
| 011 (cross-asset pair identifiers) | Yes | Constants in `src/intelligence/macro/constants.py` created in Plan 01. |

## Claude's Discretion

- Exact gradient formula parameters (thresholds, lookback windows)
- BaseAgent inheritance pattern (follow Phase 71 conventions: `self.settings`)
- Test fixture patterns
- Kafka consumer group naming

## Deferred Ideas

- Gradient-first audit of existing I1-I7 plugins (stays as Phase 65)
- Tier 2 macro factors (credit, sectors, factor, crypto, EM) — after initial 3 prove signal
- Tier 3 ideas (VP confluence, cascade, correlation stress, lead-lag, VIX term structure)
- Dashboard multi-dimensional confluence visualization
- Schema split into sub-schemas (only if >40 fields)
- I7 confidence wiring of validated I6 fields (separate follow-up task)
