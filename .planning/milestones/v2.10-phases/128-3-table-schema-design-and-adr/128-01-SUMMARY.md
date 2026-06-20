---
phase: 128-3-table-schema-design-and-adr
plan: 01
subsystem: database
tags: [timescaledb, postgresql, adr, signal-architecture, schema-design, ml-training]

# Dependency graph
requires:
  - phase: 126-signal-universe-hardening
    provides: ECL pattern spec, signal quality fixes, Phase 128 context
  - phase: 124-signal-universe-integrity-cold-start-hardening
    provides: signal firing rate correctness; replay corpus
provides:
  - "ADR at docs/architecture/signal-trade-separation-ADR.md documenting 3-table signal schema decision"
  - "G0 audit result: signal_id hash excludes entry_type; pre-migration gate CLEARED"
  - "Full column tables: 26 signal_events, 20 trade_frames, 13 trade_executions"
  - "signal_ledger_v2 view SQL for backward-compat join"
  - "Phase 130 writer grouping contract documented"
  - "Dropped column list: staleness_score, staleness_trigger_reason, and 5 others explicitly documented"
affects:
  - 128-02 (DDL migration file)
  - 128-03 (capture_signal_features deletion)
  - 129-signal-ledger-migration
  - 130-writers-and-trackers

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "ADR format: Status / Date / Deciders header block + Context / Decision / Full Schema Tables / G0 Audit / Phase 130 Contract / Dropped Columns / FK Design / Hypertable Config / Alternatives Considered / Consequences sections"
    - "Hypertable FK constraint: FOREIGN KEY (signal_id, signal_ts) REFERENCES signal_events (signal_id, ts) -- composite FK required for TimescaleDB hypertable PKs"

key-files:
  created:
    - docs/architecture/signal-trade-separation-ADR.md
  modified: []

key-decisions:
  - "3-table separation adopted: signal_events (hypertable) / trade_frames (regular) / trade_executions (regular)"
  - "counterfactual_pnl_r is always-populated on trade_frames -- ML target variable with no null ambiguity"
  - "staleness_score and staleness_trigger_reason explicitly dropped -- no new home in 3-table design"
  - "shadow_mae/mfe/outcome archived to frame_details JSONB -- not dropped, preserved as training data"
  - "signal_ts on trade_frames is architecturally required (FK anchor to hypertable composite PK), not a convenience denormalization"
  - "G0 gate CLEARED: no plugin generates multiple entry_types per fire; Phase 129 migration safe to proceed"
  - "GIN indexes on context_features/factor_scores deferred until ML query patterns are known"

patterns-established:
  - "ADR section order: Context, Decision, Full Schema Tables, G0 Audit, Phase 130 Writer Contract, Dropped Columns, FK Design on Hypertable, Hypertable Configuration, Alternatives Considered, Consequences"

requirements-completed:
  - ARCH-01

# Metrics
duration: 12min
completed: 2026-06-15
---

# Phase 128 Plan 01: Signal-Trade Separation ADR Summary

**Architecture Decision Record for 3-table signal separation: signal_events/trade_frames/trade_executions with G0 audit clearance, FK hypertable constraint documentation, and explicit ML training bias rationale**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-06-15T22:49:36Z (approx)
- **Completed:** 2026-06-15T22:49:50Z (approx)
- **Tasks:** 1/1
- **Files modified:** 1

## Accomplishments

- Wrote complete ADR (447 lines, 10 sections) at `docs/architecture/signal-trade-separation-ADR.md` covering all required content from CONTEXT.md D-08
- Documented G0 audit finding: `make_signal_id()` excludes `entry_type` from hash; audited all 22 signal-emitting plugins; gate status CLEARED for Phase 129 migration
- Documented composite FK constraint pattern `FOREIGN KEY (signal_id, signal_ts) REFERENCES signal_events (signal_id, ts)` with full rationale (TimescaleDB hypertable PK constraint requirement)
- Explicitly listed `staleness_score` and `staleness_trigger_reason` as dropped with rationale (no new home in 3-table design)
- Documented Phase 130 writer grouping contract (group by signal_id, one signal_events row, N trade_frames rows) with current N=1 reality noted
- Rejected 2-table alternative with explicit ML bias explanation; rejected monolith enhancement with cardinality argument

## Task Commits

1. **Task 1: Write signal-trade-separation-ADR.md** - `99743783` (feat)

**Plan metadata:** (SUMMARY.md commit follows)

## Files Created/Modified

- `docs/architecture/signal-trade-separation-ADR.md` - 10-section ADR documenting the 3-table signal architecture decision, full column schemas, G0 audit result, FK design constraint, hypertable config, alternatives rejected, and migration consequences

## Decisions Made

- Documented that `signal_ledger_full` (migration 095 view) is superseded by `signal_ledger_v2` -- both names are in the ADR
- Chose to document `created_at` vs `signal_computed_at` distinction in the schema table (note in D-02: `created_at` = DEFAULT now(), `signal_computed_at` = payload write wall-clock)
- Used `production/migrations/137_3table_schema.sql` path (not `db/migrations/`) per established convention in the codebase

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- ADR complete; provides design foundation for Plan 02 (DDL migration file `production/migrations/137_3table_schema.sql`)
- G0 gate CLEARED -- Phase 129 migration may proceed once DDL is written
- No blockers

## Self-Check

- `docs/architecture/signal-trade-separation-ADR.md` exists: FOUND
- Commit `99743783` exists: FOUND
- All 8 required sections present (verified by grep): FOUND

## Self-Check: PASSED

---
*Phase: 128-3-table-schema-design-and-adr*
*Completed: 2026-06-15*
