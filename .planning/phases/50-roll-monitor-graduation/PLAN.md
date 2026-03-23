# Phase 50: Roll Monitor & DualDivergence Graduation

**Status:** 📋 Planned

**Milestone:** v2.1 Data Foundation & Signal Confidence

**Dependencies:** Phase 49 (market_data_5m backfill required)

---

## Goals

1. **D-21 Validation** — Validate roll detection with real market_data_5m backfill
2. **Migration Application** — Apply migration 049_roll_premium_pct.sql
3. **Roll Monitor Graduation** — Enable ROLL_MONITOR_ENABLED after D-21 validation passes
4. **DualDivergence Promotion** — Promote trad_DualDivergence from shadow once D-07 gate passes

---

## Success Criteria

1. D-21 validation confirms roll detection works correctly with 5m data
2. `roll_premium_pct` column populated in intelligence_features during roll windows
3. `ROLL_MONITOR_ENABLED=true` set in production environment
4. trad_DualDivergence promoted (IS_SHADOW=False) after statistical gate passes

---

## Plans

(TBD — Planning will occur when Phase 49 is complete)
