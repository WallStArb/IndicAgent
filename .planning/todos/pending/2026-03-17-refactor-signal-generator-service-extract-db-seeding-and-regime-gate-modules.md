---
created: 2026-03-17T22:21:00.742Z
title: Refactor signal_generator_service — extract DB seeding and regime gate modules
area: general
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

Extract into focused modules before Phase 38 execution:

1. **`src/intelligence/trading/bar_history_seeder.py`** — DB seed logic (`_seed_bar_history_from_db`, semaphore, fallback) extracted from service into standalone async class. Related to `2026-03-14-aggregator-rebuild-and-db-seed-concurrency.md` (semaphore fix can be done together).
2. **`src/intelligence/trading/regime_gate.py`** — regime suppression logic (`_check_regime_gate`, `_is_regime_eligible`) extracted into a pure function module.
3. Service file retains: event loop, Redpanda consumer, signal publishing, startup/shutdown lifecycle.

Target: service file under 800 lines after extraction. No behavior changes — pure structural move with test coverage verifying identical output.
