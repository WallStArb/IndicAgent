# Milestones

## v1.0 MVP (Shipped: 2026-02-28)

**Phases completed:** 9 phases, 29 plans, 4 tasks

**Key accomplishments:**
- 62 plugins + 4 aggregation components + feature store + typed intelligence bus
- 796 tests passing
- 22 contracts active across equity index, energy, metals, rates, volatility, agriculture, FX, crypto
- 8 systemd services + weight-updater timer running in production
- 413K signals + 482K feature rows in TimescaleDB

---

## v1.1 Code Quality Sprint (Shipped: 2026-03-01)

**Phases completed:** 1 phase, 1 plan

**Key accomplishments:**
- Ruff errors: 206 → 0 (entire codebase)
- Tests: 787 → 803 passing
- Service startup: 9.2s → 1-2s (parallel warmup reads)
- 3 pattern files O(N²) → O(N)
- All 6 services use `ensure_consumer_group_with_reset`
- VX contract rolled to VXM6

---
