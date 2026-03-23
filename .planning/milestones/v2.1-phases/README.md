# v2.1 Data Foundation & Signal Confidence

**Status:** 🚧 In Progress (Phase 48 active)

**Phases:** 48-52

## Phase Breakdown

- [ ] **Phase 48:** Tick Aggregation & I7 Quality (IN PROGRESS)
  - Location: `.planning/phases/48-tick-aggregation/`
  - Status: Plan created, tick aggregation work committed, I7 refactoring pending
- [ ] **Phase 49:** DB Performance & Signal Ledger Hardening (PLANNED)
  - Location: `.planning/phases/49-db-performance/`
  - Dependencies: Phase 48 completion
- [ ] **Phase 50:** Roll Monitor & DualDivergence Graduation (PLANNED)
  - Location: `.planning/phases/50-roll-monitor-graduation/`
  - Dependencies: Phase 49 (market_data_5m backfill)
- [ ] **Phase 51:** Signal & Indicator Validation Framework (PLANNED)
  - Location: `.planning/phases/51-signal-validation-framework/`
  - Dependencies: None (can run in parallel with 49-50)
- [ ] **Phase 52:** Infrastructure Hardening (PLANNED)
  - Location: `.planning/phases/52-infrastructure-hardening/`
  - Dependencies: Phase 51 (validation framework in place)

## Milestone Goal

Establish data foundation quality and signal confidence through DB optimization, validation frameworks, and infrastructure hardening. Clean data for ML scoring foundation (v2.3).

## Archive Plan

When v2.1 is complete, move all phase directories from `.planning/phases/` to `.planning/milestones/v2.1-phases/`.
