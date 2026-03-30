# Phase 53.2 — Discussion Log

**Date:** 2026-03-28
**Mode:** Interactive (discuss)

---

## Gray Areas Presented

Three gray areas identified after codebase scout and design doc review. All three selected for discussion. User framing: "Design like Renaissance would — Jim Simons test, SoC, modularity, no manual tasks, prefer automation, canonical OHLCV bars."

---

## Area 1: FCA Subscription Topology

**Question:** After BarAccumulator extraction, what does feature_compute_agent subscribe to? The in-process `[bar] + htf_bars` synchronous batch disappears.

**Options presented:**
1. FCA subscribes to both `market.bars` + `market.bars.htf` independently (Option A)
2. FCA subscribes only to `market.bars.htf`, BarAggregatorComputeAgent relays 1m pass-through (Option B)

**Sub-question:** Is the small ordering gap (~1-5ms between 1m and HTF IntelligenceEvents) acceptable?

**Selected:** Option A — subscribe to both, process each bar independently

**Rationale:** Each timeframe's I1-I6 pipeline uses only its own bar history. The ordering gap is not a correctness issue. Renaissance SoC: BarAggregatorComputeAgent aggregates, FCA computes intelligence — no mixing. Option B would make BarAggregatorComputeAgent a relay+aggregator, violating SRP.

---

## Area 2: Flat Bar Responsibility

**Question:** "canonical flat bars for empty minutes" is in Phase 53.2 ROADMAP scope. DataProviderAgent is responsible for flat bar *emission* per design doc. Does BarAggregatorComputeAgent enforce the 1m grid, or trust DataProviderAgent?

**Options presented:**
1. Trust + propagate only (Option A)
2. Enforce the grid too (Option B)

**Selected:** Trust + propagate only (Option A)

**Rationale:** SoC — DataProviderAgent owns grid enforcement, BarAggregatorComputeAgent owns aggregation. Dual enforcement is maintenance burden. BarAuditorAgent (Phase 53.1) handles gaps. Phase 53.3 deferred flat bar emission (D-20: rename only), so Phase 53.2 adds it to DataProviderAgent as a targeted addition alongside the BarMessage schema change.

---

## Area 3: is_flat_bar Flag + Schema

**Question:** BarMessage currently has no `is_flat_bar` field. Should 53.2 add it AND wire DataProviderAgent for flat bar emission?

**Options presented:**
1. Add field in 53.2, wire DataProviderAgent too (Option A — recommended)
2. Add field only, defer DataProviderAgent wiring (Option B)
3. Defer entirely (Option C)

**Selected:** Option A — add field and wire DataProviderAgent in 53.2

**Rationale:** The field is only useful if the source sets it. Shipping the schema change without the producer wiring creates a permanently-False field — misleading and wasteful. Do it right or don't do it.

---

## Area 4: FCA Dual-Topic Consumer

**Question:** FCA needs to consume two topics. Single consumer with both topics, or two separate consumers?

**Options presented:**
1. Single KafkaConsumerClient subscribed to both topics (Recommended)
2. Two separate consumers

**Selected:** Single consumer, multiple topics

**Rationale:** Simplest change. Same `_process_bar()` handler works for all TFs. One consumer group. No asyncio coordination overhead.

---

## Summary

All four decisions are Renaissance-aligned: clean DAG, SoC, independent bar processing, no dual enforcement, schema field + producer wired together. Phase 53.2 scope is well-bounded: new agent + FCA simplification + is_flat_bar schema + DataProviderAgent flat bar emission.
