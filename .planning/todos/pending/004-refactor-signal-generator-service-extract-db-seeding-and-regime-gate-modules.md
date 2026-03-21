---
created: 2026-03-17T22:21:00.742Z
title: Refactor signal_generator_service — extract DB seeding and regime gate modules
area: general
priority: 4
tier: phase-44-adjacent
phase: "44"
files:
  - services/signal_generator_service.py
---

## Problem

`signal_generator_service.py` is 1551 lines — the largest file in the codebase. It currently combines four distinct concerns in one file:

1. **Signal scheduling** — per-symbol/TF bar processing loop
2. **Regime gating** — suppressing signals based on HMM/regime state
3. **Aggregator orchestration** — calling the I7 aggregator and publishing results
4. **DB seeding** — `_seed_bar_history_from_db()` on startup (~240 concurrent queries)

Phase 38 (automated futures roll detection) will need to add roll-aware signal migration logic into this service, which will push it even larger and make the roll integration harder to reason about.

Health audit (2026-03-17) flagged this as the primary refactor candidate before Phase 38 lands.

## Solution

Refactor toward a clean DAG — each module owns one concern, is independently testable, and can be reused by other services (e.g. Phase 38 roll detection, future cross-asset service). Line count reduction is a side effect, not the goal.

Proposed module boundaries:

1. **`src/intelligence/trading/bar_history_seeder.py`** — DB seed logic as a standalone async class. Reusable by any service that needs to warm bar history on startup (signal_generator today, potentially roll detector in Phase 38). Related: `2026-03-14-aggregator-rebuild-and-db-seed-concurrency.md` (semaphore fix lands here).
2. **`src/intelligence/trading/regime_gate.py`** — pure function module: `is_regime_eligible(signal, regime_context) -> bool`. No state, no service coupling — any consumer of I7 signals can apply the gate without importing the service.
3. **`src/intelligence/trading/signal_scheduler.py`** — bar-triggered scheduling loop, decoupled from Redpanda transport. Allows the scheduling logic to be tested without a live broker.
4. Service file retains: Redpanda consumer/producer, startup/shutdown lifecycle, wiring.

Design principle: refactors should produce a cleaner DAG — modules with single responsibilities that compose upward into services, not monolithic services that accumulate logic over time. Extensibility > brevity.
