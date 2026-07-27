---
phase: 167-cross-sectional-trade-construction-t3
plan: 01
subsystem: database
tags: [timescaledb, postgres, apr, config_state, migration, glossary]

# Dependency graph
requires: []
provides:
  - "construction_spreads hypertable (migration 260), applied and idempotency-verified against live indicagent"
  - "Six alpha.construction.*/infra.cross_sectional_spread_tracker.* APR keys, provenance-tagged, seeded in config_schema/config_state/config_history"
  - "Corpus-rebuild truncation registration for construction_spreads (before alpha_frames)"
  - "Glossary entry for the cross-sectional spread construction concept"
  - "Integration test proving the schema contract, APR seeds, and truncation order mechanically"
affects: [167-02, 167-03, 167-04, 167-05, 167-06]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Two flat net_spread_{fast,slow}_by_cost_bps jsonb columns instead of one nested column, since cost applies per-lookahead-scale"
    - "NULLABLE one_way_turnover / net_spread_*_by_cost_bps for the corpus's genuinely-first bar (never fake as 0.0)"

key-files:
  created:
    - production/migrations/260_construction_spreads_schema.sql
    - tests/integration/test_construction_spreads_schema.py
  modified:
    - scripts/infrastructure/backfill/infrastructure_truncate_derived_tables.sh
    - docs/foundation/glossary.md

key-decisions:
  - "Migration numbered 260, not 259: 259 (todo 183, ic_engine max_cell_rows recalibration) was already applied live but its file was untracked/not yet visible in this worktree at execution time — resolved by checking the primary repo checkout's migrations directory directly, not just this worktree's, avoiding a genuine todo-095-class collision"
  - "Two net_spread_*_by_cost_bps jsonb columns (fast/slow), not RESEARCH.md's single nested column — cost applies to a scale-independent turnover but the two lookahead scales genuinely differ, so two flat columns are explicit and easy to query"
  - "one_way_turnover and both net_spread_*_by_cost_bps columns are NULLABLE, NULL only for the corpus's genuinely-first bar — a NULL count > 1 in this table is a detectable bug signal (Pitfall 4), never a faked 0.0"

requirements-completed:
  - "TCL-MD-2: Minimal Design step 2 (ranking to buckets) - decile_fraction knob"
  - "TCL-MD-5: Minimal Design step 5 (rebalance rule) - per-bar, D-03"
  - "TCL-MD-6: Minimal Design step 6 (portfolio-level measurement) - persistence substrate"
  - "D-05: cost-hurdle treatment computed live, APR-backed"
  - "CLAUDE-APR: Adaptive Parameter Registry mandate - no hardcoded tunables"
  - "REVIEW-M1 (Codex): json-typed APR values must be validated consistently in migration and loader"
  - "REVIEW-S1 (Codex): dedicated test for the corpus truncation order, construction_spreads before alpha_frames"

duration: 9min
completed: 2026-07-27
---

# Phase 167 Plan 01: Cross-Sectional Trade Construction Schema Substrate Summary

**New `construction_spreads` TimescaleDB hypertable (migration 260) plus six provenance-tagged `alpha.construction.*`/`infra.cross_sectional_spread_tracker.*` APR keys, corpus-truncation registration, and a glossary entry — the schema contract every downstream Phase 167 plan reads and writes.**

## Performance

- **Duration:** 9 min
- **Started:** 2026-07-27T00:14:00-04:00 (approx.)
- **Completed:** 2026-07-27T00:23:02-04:00
- **Tasks:** 3/3 completed
- **Files modified:** 4 (2 created, 2 modified)

## Accomplishments
- `construction_spreads` hypertable live in `indicagent`, PK `(construction_name, tf, bar_ts)` containing the partition column per migration 205's review-H1 precedent, applied and re-run idempotency-verified
- Six new APR keys seeded across `config_schema`/`config_state`/`config_history`, each provenance-tagged; the one `json`-typed key (`cost_hurdle_bps_round_trip`) round-trips through `json.loads` to `[1, 3, 5, 10]`, verified both by direct `psql` query and by the new integration test
- `infrastructure_truncate_derived_tables.sh` truncates `construction_spreads` before `alpha_frames` in all four locations (pre-report, comment, TRUNCATE, post-report), proven by a dedicated text-based test rather than left to inspection
- `docs/foundation/glossary.md` gains a full `cross-sectional spread construction` entry (naming derivation chain, explicit "not an `alpha_frames` frame" / "not a consumer of `ensemble_alpha`" distinctions, banned synonyms) cross-referenced from the existing `counterfactual_pnl_r`/`CounterfactualTracker` entries

## Task Commits

Each task was committed atomically:

1. **Task 1: Write and apply the construction_spreads migration** - `75539177` (feat)
2. **Task 2: Register construction_spreads in corpus truncation and the glossary** - `e3e43001` (docs)
3. **Task 3: Integration test for the schema, APR seeds, and truncation order** - `fa14a709` (test)

_No plan-metadata commit in this worktree — SUMMARY.md/STATE.md/ROADMAP.md updates are the orchestrator's responsibility per this plan's worktree execution mode._

## Files Created/Modified
- `production/migrations/260_construction_spreads_schema.sql` - `construction_spreads` hypertable DDL + six-key APR seed triad; applied to live `indicagent`
- `tests/integration/test_construction_spreads_schema.py` - six tests: hypertable registration, column contract, PK partition-column containment, APR seed provenance, json round-trip, truncation order
- `scripts/infrastructure/backfill/infrastructure_truncate_derived_tables.sh` - added `construction_spreads` to pre-report, comment block, TRUNCATE (before `alpha_frames`), post-report
- `docs/foundation/glossary.md` - new `cross-sectional spread construction` entry + "See also" cross-references from `counterfactual_pnl_r`/`CounterfactualTracker`

## Decisions Made
- **Migration number 260, not the plan's illustrative placeholder.** `ls production/migrations/ | sort -n | tail -5` inside this worktree topped out at 258, but the primary repo checkout (not this worktree — untracked files don't propagate across worktrees) already had `259_ic_max_cell_rows_recalibration.sql` (todo 183) applied live. Checked the primary checkout directly and confirmed via `config_state` that 259's change was already live, then numbered this migration 260 to avoid a genuine collision — exactly the risk todo 095 documents and this plan's Task 1 explicitly calls out.
- **Two flat `net_spread_{fast,slow}_by_cost_bps` jsonb columns, not RESEARCH.md's single nested column** — matches this plan's `<design_decisions>` item 1: the construction measures two lookahead scales against a scale-independent turnover, so two flat columns are more explicit and less error-prone to query than a nested `{"fast": {...}, "slow": {...}}` shape.
- **`one_way_turnover` and both `net_spread_*_by_cost_bps` columns are NULLABLE**, NULL exactly for the corpus's genuinely-first bar — matches `<design_decisions>` item 2 (Pitfall 4): persisting NULL instead of a faked `0.0` makes a broken incremental implementation mechanically detectable (a NULL count > 1 is a bug signal).

## Deviations from Plan

None - plan executed exactly as written, including the migration-number resolution described above (the plan's own Task 1 text anticipated exactly this class of collision risk and instructed resolving it at execution time rather than trusting RESEARCH.md's illustrative number).

## Issues Encountered
- `.venv` is absent from this worktree (known gotcha — worktrees don't carry the gitignored virtualenv). Ran all `pytest`/`ruff`/`black` invocations via `/home/bg/dev/indicagent/.venv/bin/<tool>` (the primary checkout's venv) instead, and added that path to `PATH` for the Task 3 commit so the project's pre-commit hooks (which shell out to `ruff`/`black`) could find them.
- `tests/integration/test_migration_schema_sync.py` failed once with `relation "signal_events" already exists` while rebuilding the shared `indicagent_test` database — a transient race with a concurrent process (most likely the sibling 167-02 worktree agent's own integration test run against the same shared database, consistent with this project's known "concurrent sessions, shared dir" behavior). Retried immediately and it passed cleanly; no code or migration issue.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- The `construction_spreads` schema, all six APR keys, corpus-truncation registration, and glossary entry are live and verified — Plans 02-05 can read/write this table and these keys directly with no further schema exploration needed.
- `services/cross_sectional_spread_tracker.py` (the compute/persist service) does not yet exist — that is explicitly out of this plan's scope, per RESEARCH.md's recommended sequencing into later Phase 167 plans.

## Self-Check: PASSED

All created files verified present on disk; all three task commit hashes verified present in
`git log --oneline --all`. No missing items.

---
*Phase: 167-cross-sectional-trade-construction-t3*
*Completed: 2026-07-27*
