# Phase 089: Compute Performance Optimization - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-18
**Phase:** 089-compute-performance-optimization
**Areas discussed:** PERF-07 scope, Plan grouping strategy, Measurement approach, PERF-10 scope

---

## PERF-07 Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Per-key Queue + worker tasks | Each (symbol,tf) key gets its own asyncio.Queue and long-running Task. Full isolation, correct in-order processing per key, backpressure per key. Mirrors the service DAG. | ✓ |
| asyncio.gather on batch | Accumulate bars over a short window, then gather all concurrently. Simpler but requires batching window and less isolation. | |
| Per-key create_task chained | On each bar, create_task with per-key future chaining for ordering. Middle ground. | |
| Defer PERF-07 to Phase 090 | Ship PERF-01 through PERF-06 + PERF-08/09 in 089. Dedicate a separate phase to concurrency. | |

**User's choice:** Per-key Queue + worker tasks
**Notes:** User explicitly applied Renaissance/Jim Simons framing — independent streams must run independently. "Microservices DAG within the process" architecture. No sequential coupling between independent (symbol,tf) lanes.

---

## PERF-10 Scope

**Resolved without AskUserQuestion:** PERF-10 (checkpoint writes off hot path) is already delivered by Phase 088 Plan 02 via `PluginStateManager.start_checkpoint_loop(interval_sec, get_extra_fn)`. Removed from Phase 089 scope.

---

## PERF-04 Targets (Measurement Approach)

| Option | Description | Selected |
|--------|-------------|----------|
| MarketProfile + SessionLevels only | 207ms and 94ms p95 outliers, both supports_incremental=False. Bounded scope. | |
| MarketProfile + SessionLevels + BOCPDChangePoint | Add 77ms BOCPD. Already has supports_incremental=True but incremental may be O(N). | |
| All plugins > 20ms p95 | Covers 12 plugins including HMM regimes. High effort. | ✓ |
| Data-gate: gather 1 trading day first | Delay planning to get fuller histogram data. | |

**User's choice:** All plugins > 20ms p95
**Notes:** OBS-01 data was already live and queryable (Prometheus running). No data gate needed. User wants comprehensive coverage — all 12 plugins >20ms addressed. For those already with supports_incremental=True, profile first post-PERF-03 before optimizing algorithm. User reiterated Renaissance/automation/no-manual-tasks principles.

---

## Plan Grouping Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| 5 plans (01+02 parallel wave 1, 03→04 wave 2, 05 wave 3) | Clean separation by risk level and dependency. | ✓ |
| Combine plans 03 and 04 | Reduces to 4 plans but larger plan 03. | |
| Split PERF-04 per plugin | More granular, slower overall. | |
| Merge 01+02 into one plan | 4 plans total, safe to combine. | |

**User's choice:** 5 plans as described
**Notes:** User confirmed 5-plan structure while reinforcing Renaissance principles throughout — modularity, separation of concerns, automation over manual tasks, balance efficiency with simplicity.

---

## Claude's Discretion

- Exact `compute_next()` algorithm for MarketProfile (volume bucket structure and data types)
- Exact `compute_next()` algorithm for SessionLevels (rolling session tracking structure)
- Whether BOCPD incremental is truly O(N) — profile first, optimize only if confirmed
- Whether per-key worker manager is a new class or inline (prefer new class if >50 lines)
- Exact drain batch size N for PERF-06 (default 10, configurable via Settings)

## Deferred Ideas

- Phase 090 candidate: wave-level parallelism within a single bar's I1→I7 pipeline (if PERF-07 reveals it)
- HMM/BOCPD deep algorithm optimization (GPU, approximation) if post-PERF-03 profiling shows incremental still too slow
- Thread pool sizing tuning post-PERF-07
