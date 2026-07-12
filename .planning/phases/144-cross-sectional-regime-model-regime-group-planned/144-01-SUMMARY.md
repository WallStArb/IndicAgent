---
phase: 144-cross-sectional-regime-model-regime-group-planned
plan: 01
subsystem: database
tags: [postgresql, timescaledb, apr, config_schema, config_state, migration, glossary]

# Dependency graph
requires: []
provides:
  - "market_regimes.regime_group column (renamed from asset_class), index renamed, all existing rows preserved"
  - "alpha.regime.groups APR key (json) seeding equity/rates enabled=true; commodity_energy/commodity_metals/commodity_agri/fx enabled=false"
  - "Per-group signal-threshold APR keys: alpha.equity_regime.*, alpha.rates_regime.*, alpha.commodity_energy_regime.*, alpha.commodity_metals_regime.*, alpha.commodity_agri_regime.*, alpha.fx_regime.*"
  - "regime_group glossary entry cross-referencing idiosyncratic/systematic regime distinction"
affects: [144-02, 144-03, 144-04, 144-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "APR json value_type for structured group config (alpha.regime.groups)"
    - "Daily-bar-denominated window APR keys with _tf_window(daily, tf) scaling convention noted in description"

key-files:
  created:
    - production/migrations/229_regime_group.sql
  modified:
    - docs/foundation/glossary.md

key-decisions:
  - "alpha.regime.equity_model_enabled NOT retired in this migration — deferred to Plan 05 (ic_engine) after a project-wide grep confirms ic_engine is sole consumer"
  - "New alpha.equity_regime.* keys added as a fresh namespace rather than renaming alpha.regime.* in place — preserves backward compat for any code still reading the old keys until Plan 05 cuts over"
  - "Commodity/FX APR keys seeded now (not deferred to the design doc's original Task 6/7) since the plan's must_haves require all four group namespaces to exist after this plan, even though commodity/fx groups ship enabled=false pending ETF universe expansion"

patterns-established:
  - "Window params for cross-sectional regime signals are always specified in DAILY bars with a description note that Plan 04's dispatcher scales them to the target TF via _tf_window(daily, tf) — locks the convention before any consumer code exists"

requirements-completed: []

# Metrics
duration: 12min
completed: 2026-07-12
---

# Phase 144 Plan 01: Migration 229 + regime_group Glossary Entry Summary

**Renamed `market_regimes.asset_class` to `regime_group` and seeded `alpha.regime.groups` plus six per-group APR threshold namespaces (equity/rates/commodity_energy/commodity_metals/commodity_agri/fx), establishing the schema/APR foundation the Phase 144 dispatcher and ic_engine routing plans build on.**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-07-12T18:02:00Z
- **Completed:** 2026-07-12T18:14:50Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- `production/migrations/229_regime_group.sql` renames the column and its index, preserving the PK and all existing rows
- `alpha.regime.groups` APR key seeded as `json`-typed config carrying all 6 group configs (equity/rates enabled, 4 commodity/fx groups disabled pending ETF universe expansion)
- All per-group signal-threshold APR namespaces seeded in this same migration (equity_regime, rates_regime, commodity_energy_regime, commodity_metals_regime, commodity_agri_regime, fx_regime) — every window-denominated key documents the daily-bar + `_tf_window` scaling convention that Plan 04's dispatcher will implement
- `regime_group` glossary entry added, cross-referencing the existing idiosyncratic/symbol vs systematic/market regime distinction and the deliberately-deferred multi-label sensitivity job

## Task Commits

Each task was committed atomically:

1. **Task 1: Migration 229 — rename asset_class to regime_group + seed APR keys** - `9025855f` (feat)
2. **Task 2: Glossary — add regime_group entry** - `10e8aad6` (docs)

## Files Created/Modified
- `production/migrations/229_regime_group.sql` - Column/index rename + `alpha.regime.groups` json APR key + 6 per-group threshold namespaces
- `docs/foundation/glossary.md` - New `regime_group` entry, inserted immediately after the existing `regime` entry

## Decisions Made
- Seeded commodity (`commodity_energy_regime`, `commodity_metals_regime`, `commodity_agri_regime`) and `fx_regime` APR keys in this migration rather than deferring to later tasks, matching this plan's explicit must_have ("Per-group signal-threshold APR keys exist for equity/rates/commodity/fx namespaces") even though those groups ship `enabled: false` in `alpha.regime.groups` pending ETF universe expansion (per the source design doc's Task 6/7 dependency notes)
- Kept `alpha.regime.equity_model_enabled` untouched — its retirement is explicitly scoped to Plan 05 per the plan's action instructions

## Deviations from Plan

None — plan executed exactly as written. The migration ports the design doc's Task 1 SQL (`docs/plans/2026-07-01-cross-sectional-regime-model.md` lines 110-308) plus the commodity/FX APR key blocks from that doc's Task 6/7 sections, with the internal header comment corrected to `-- Migration 229: regime_group` and all window-key descriptions updated to state the daily-bar + `_tf_window` scaling convention, exactly as directed.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required. The migration itself is not applied to the live DB by this plan (per its `<verification>` section, applying it is "execute only when convenient — not gated on any code here"); it is schema/APR foundation for later Phase 144 plans to consume.

## Next Phase Readiness

`production/migrations/229_regime_group.sql` is ready to apply. Plan 04 (dispatcher) and Plan 05 (ic_engine routing) can now read `alpha.regime.groups` and the per-group threshold namespaces this plan seeded. No code in this repo yet reads `market_regimes.regime_group` or the new APR keys — that wiring is explicitly out of scope for this plan and lands in later Wave 1/2 plans of Phase 144.

---
*Phase: 144-cross-sectional-regime-model-regime-group-planned*
*Completed: 2026-07-12*

## Self-Check: PASSED

- FOUND: production/migrations/229_regime_group.sql
- FOUND: docs/foundation/glossary.md (regime_group entry, 5 mentions, single heading)
- FOUND: commit 9025855f (Task 1)
- FOUND: commit 10e8aad6 (Task 2)
- Verified: `RENAME COLUMN asset_class TO regime_group` matches exactly once
- Verified: no `Migration 189` string present
- Verified: internal header comment is exactly `-- Migration 229: regime_group`
