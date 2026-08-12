---
phase: 146-empirical-instrument-tag-calibrator
plan: 02
subsystem: database
tags: [postgresql, migration, tag_vocabulary, instrument_tags, apr, config_state]

# Dependency graph
requires: []
provides:
  - "Migration 238: tag_vocabulary gains factor_series/measurement_type/lookback_days/loading_threshold/half_life_days"
  - "Migration 238: instrument_tags gains loading/p_value/bh_adjusted_p/passes_fdr/consecutive_fails/sample_n/estimated_at/valid_from/valid_to (D-10 expiry columns)"
  - "12 measurable Phase-1 primitive tags seeded with real-live-name factor_series contracts (D-02/D-05)"
  - "New equity_beta tag_vocabulary row (category=sensitivity, factor_series=SPY)"
  - "Self-describing schema invariant: every other tag_vocabulary row flipped to measurement_type='definitional' (D-12, Option A)"
  - "fed_policy/geopolitical owner annotations (D-06, TAG-03)"
  - "7 alpha.tag_calibrator.* APR keys in config_schema/config_state/config_history"
affects: [146-04-tag-calibrator-service]

# Tech tracking
tech-stack:
  added: []
  patterns: ["3-table APR seed pattern (config_schema/config_state/config_history, ON CONFLICT DO NOTHING) per migration 235 precedent", "self-describing measurement_type sweep (Option A) to eliminate NULL-factor_series ambiguity"]

key-files:
  created: [production/migrations/238_tag_calibrator_measurement_contract.sql]
  modified: []

key-decisions:
  - "Used real live tag names (rate_sensitive, dollar_strength, china_demand, credit_risk, inflation, yield_curve, oil_price, volatility, semi_cycle, yen_carry, em_flows) per D-02/D-05, not the _beta-suffixed shorthand in CONTEXT.md/RESEARCH.md which does not exist live"
  - "Inserted a NEW equity_beta row (category=sensitivity, factor_series=SPY) rather than reusing high_beta, which is confirmed to be a different exposure concept"
  - "Long-short factor series encoded as 'LONG-SHORT' string (HYG-IEF, TIP-IEF, IEF-SHY, XLE-SPY) for Plan 04's service to parse on the hyphen"
  - "volatility tag's factor_series is the sentinel string 'SPY_REALIZED_VOL' (not a tradeable symbol) — Plan 04 maps this to breadth_vol.py's proxy"
  - "Applied the Option A self-describing sweep: UPDATE tag_vocabulary SET measurement_type='definitional' WHERE factor_series IS NULL, guaranteeing zero beta_regression rows with NULL factor_series"

patterns-established:
  - "measurement_type='beta_regression' AND factor_series IS NOT NULL <=> measurable Phase-1 tag; measurement_type='definitional' <=> everything else (self-describing schema contract for Plan 04)"

requirements-completed: [TAG-01, TAG-03]

# Metrics
duration: 15min
completed: 2026-07-17
---

# Phase 146 Plan 02: Migration 238 - Measurement Contract Summary

**Migration 238 adds the tag_vocabulary/instrument_tags measurement-contract schema and seeds the factor-series contract for 12 Phase-1 primitives (under their real live tag names) plus the 7 alpha.tag_calibrator.* APR keys, unblocking the TagCalibrator service build (Plan 04).**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-07-17T04:07:00-04:00 (approx)
- **Completed:** 2026-07-17T04:09:37-04:00
- **Tasks:** 3/3 completed
- **Files modified:** 1

## Accomplishments
- `tag_vocabulary` and `instrument_tags` both carry the revised measurement-contract schema; all 410 pre-existing `instrument_tags` rows preserved with no data loss.
- Every measurable Phase-1 primitive tag (12 total: rate_sensitive, dollar_strength, china_demand, credit_risk, inflation, yield_curve, oil_price, volatility, equity_beta, semi_cycle, yen_carry, em_flows) carries its correct `factor_series` under the real live tag name, verified against live `market_data_ohlcv_tradeable` bar counts (all clear the 252-day lookback by 8-20x margin).
- The schema is now fully self-describing (D-12, Option A): zero `tag_vocabulary` rows have `measurement_type='beta_regression'` with a NULL `factor_series` — the Plan 04 engine can drive purely off `(symbol, factor_series, measurement_type)` with no hard-coded tag list.
- All 7 `alpha.tag_calibrator.*` APR tunables are live in `config_schema`/`config_state`/`config_history`.

## Task Commits

Each task was committed atomically:

1. **Task 1: Migration 238 — revised schema DDL (both tables)** - `dda09142` (feat)
2. **Task 2: Seed the factor-series measurement contract for the Phase-1 primitive set** - `5311d6db` (feat)
3. **Task 3: Seed the 7 alpha.tag_calibrator.* APR keys** - `48e2496a` (feat)

_Note: this migration is SQL-only (no `.py` files changed); each task's own live-DB `psql` verification query served as the acceptance check per the plan's `<verify>` blocks._

## Files Created/Modified
- `production/migrations/238_tag_calibrator_measurement_contract.sql` - Revised measurement-contract DDL (both ALTER TABLE blocks), factor-series seeding for 12 Phase-1 primitives + new `equity_beta` row + self-describing sweep + owner annotations, and the 7-key `alpha.tag_calibrator.*` APR seed.

## Decisions Made
- Followed the plan's explicit "real live tag names" guidance verbatim — verified against live `tag_vocabulary` before writing any UPDATE statement (no `_beta`-suffixed row exists; `high_beta` is confirmed a different concept, not reused).
- Applied all three `BEGIN`/`COMMIT` blocks within the migration file (DDL, seeding, APR keys) as separate transactions per the plan's task boundaries, matching how the file was actually executed against the live DB incrementally across the three tasks.
- No new package/dependency surface (SQL-only plan, per the threat model's `T-146-SC: accept` disposition).

## Deviations from Plan

None - plan executed exactly as written. All acceptance criteria for all three tasks verified against the live DB:
- Task 1: `\d instrument_tags`/`\d tag_vocabulary` show all specified new columns; 410 rows preserved; category CHECK and `instrument_annotations` untouched.
- Task 2: all 12 measurable rows carry correct `factor_series`; `equity_beta` row created with `category='sensitivity'`; self-describing invariant (`beta_regression` + NULL `factor_series`) count = 0; exactly 12 measurable rows; zero gold tags; `fed_policy`/`geopolitical` have owner annotations (count = 2).
- Task 3: all 7 `alpha.tag_calibrator.*` keys present in `config_state` with the specified default values; matching `config_schema` and `config_history` rows (count = 7 each).

## Issues Encountered

None during actual execution. (One re-run of the full migration file during idempotency verification hit an expected non-idempotent `INSERT` conflict on the `equity_beta` row from Task 2's seeding — this is an artifact of re-running an already-applied one-time migration file twice for verification purposes, not a defect in the migration itself; the file is designed to run once against a live DB, matching the house pattern set by migration 227/228, which also use plain `INSERT` without `ON CONFLICT` for one-time tag-vocabulary seeding. State was verified unaffected: `equity_beta` remained exactly 1 row, and the APR-key transaction, which does use `ON CONFLICT DO NOTHING`, completed cleanly on the re-run.)

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Migration 238 is live on the shared `indicagent` database. Plan 04 (`TagCalibrator` service) can now drive its measurement loop off `(symbol, factor_series, measurement_type)` with zero ambiguous rows and read/write the full expiry-column set (`valid_from`/`valid_to`/`consecutive_fails`) that D-10's design requires. No blockers for Plan 04's build.

Note for the orchestrator: this plan's `depends_on: []` frontmatter and the RESEARCH.md's Pitfall-4/live-verification notes indicate migration 237 (Wave 0 taxonomy cleanup — credit_cycle merge, housing_cycle delete, spread_leg backfill, likely owned by plan 146-01) had NOT yet landed on the shared DB as of this plan's execution (`credit_cycle`/`housing_cycle` rows were still present, confirmed via live query before Task 2 ran). This migration's self-describing sweep and factor-series UPDATEs are written to be robust regardless of migration 237's landing order — the sweep only affects rows still lacking a `factor_series`, and none of Task 2's UPDATEs target `credit_cycle`/`housing_cycle` by name — but the phase's overall Wave 0/Wave 1 sequencing (137-01 before 146-04) should still be confirmed complete before Plan 04 runs.

---
*Phase: 146-empirical-instrument-tag-calibrator*
*Completed: 2026-07-17*
