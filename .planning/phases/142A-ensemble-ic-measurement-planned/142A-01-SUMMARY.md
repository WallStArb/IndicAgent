---
phase: 142A-ensemble-ic-measurement-planned
plan: 01

subsystem: database, batch-compute
tags: [asyncpg, timescaledb, scipy, statsmodels, process-pool-executor, apr, base-batch]

requires:
  - phase: 141.1
    provides: OOS holdout enforcement (alpha.validation.oos_start), regime_scope schema, weight-epoch fix
provides:
  - alpha_ensemble_ic hypertable (schema + APR seeds)
  - EnsembleICEngine BaseBatch service (IC measurement for ensemble alpha_score)
  - service_auditor registration
affects: [142A-02, 142B]

tech-stack:
  added: []
  patterns:
    - "IC math composition (not subclass/fork) from services/ic_engine.py private functions"
    - "ProcessPoolExecutor compute-only workers + single serial write after corpus BH-FDR"
    - "scored_at vintage pinning (run_ts pinned once per invocation, D-142A-R2)"
    - "walk_forward_stable as fold IC-magnitude ratio, swappable via APR (D-142A-R1)"

key-files:
  created:
    - production/migrations/195_alpha_ensemble_ic.sql
    - services/ensemble_ic_engine.py
    - tests/unit/test_ensemble_ic_math.py
    - tests/unit/test_ensemble_ic_config.py
    - tests/unit/test_ensemble_ic_bh_fdr.py
    - tests/unit/test_ensemble_ic_executable_returns.py
    - tests/unit/test_ensemble_ic_wf_stability.py
    - tests/unit/test_ensemble_ic_idempotency.py
    - .planning/phases/142A-ensemble-ic-measurement-planned/deferred-items.md
  modified:
    - services/service_auditor.py

key-decisions:
  - "Migration renumbered 187 -> 195: migrations 187-194 were already applied at execution time (187 itself previously used and reverted for an unrelated ensemble_weights demotion); next available number used to avoid a collision the plan could not have anticipated at planning time."
  - "walk_forward_stable computed as fold IC-magnitude max/min ratio, not fold IC-Sharpe ratio (D-142A-R1, locked in CONTEXT.md) — code comment cites the decision inline."
  - "scored_at pinned to one run_ts per EnsembleICEngine invocation (D-142A-R2) — event_row_id is run_ts-independent so ON CONFLICT (event_row_id, scored_at) DO UPDATE fires on within-run retries while separate invocations accumulate vintages."
  - "Startup gate crashes loud on empty alpha_events, forward_returns (executable_open_to_open), or market_regimes (review finding #5) — correct behavior while Phase B corpus re-run is in flight; no execution attempted against the live DB in this plan."

patterns-established:
  - "Ensemble-level batch services compose ic_engine's private IC math functions (Fisher-z CI, corpus BH-FDR, expanding-window walk-forward) rather than re-deriving methodology, keeping ensemble and feature-level IC measurement in structural parity."

requirements-completed: [EIC-01, EIC-03]

duration: ~70min
completed: 2026-07-02
---

# Phase 142A Plan 01: Ensemble IC Measurement — Schema + EnsembleICEngine Summary

**alpha_ensemble_ic hypertable (36 hold_max_bars + 6 ensemble_ic APR keys) and a BaseBatch EnsembleICEngine that composes ic_engine's Fisher-z CI + corpus-level BH-FDR + walk-forward machinery to measure IC(alpha_score, forward_return_*) per (symbol, tf, regime, lookahead), with scored_at run-vintage pinning and a magnitude-ratio walk_forward_stable gate.**

## Performance

- **Duration:** ~70 min
- **Started:** 2026-07-02T17:01:00Z
- **Completed:** 2026-07-02T17:41:57Z
- **Tasks:** 3/3 completed
- **Files modified:** 9 created, 1 modified

## Accomplishments

- Migration 195 (`alpha_ensemble_ic` hypertable): composite PK `(event_row_id, scored_at)`, `walk_forward_stable` column (EIC-03 surface), `alpha_ensemble_ic_pooled_symbol_consistent` CHECK constraint enforcing `(symbol = 'POOLED') = is_pooled` as the single source of truth for the pooled/per-symbol distinction. 6 `alpha.ensemble_ic.*` + 1 `infra.ensemble_ic_engine.workers` APR seeds. 36 `alpha.frame.hold_max_bars.<regime>.<tf>` seeds for the 9 LIVE `market_regimes` labels x 4 TFs (OQ-1 resolution — not the stale 4-label namespace from the 2026-06-25 schema doc).
- `EnsembleICEngine(BaseBatch)`: reads `alpha_events` joined to `forward_returns` (executable_open_to_open only) and `market_regimes` (9-label cross-sectional stratification) entirely in the main process; dispatches pure-compute `ProcessPoolExecutor` workers per (symbol, tf) that receive numpy arrays (never a DSN or connection) and return `list[dict]` rows; applies ONE corpus-level `multipletests` BH-FDR call; writes serially via `asyncpg.executemany` with `ON CONFLICT (event_row_id, scored_at) DO UPDATE`.
- `compute_walk_forward_stable()`: EIC-03 gate as the fold IC-**magnitude** max/min ratio (D-142A-R1) — swappable via `alpha.ensemble_ic.wf_stability_metric`, with an explicit `NotImplementedError` stub for the future `ic_sharpe_ratio` branch.
- `build_ensemble_ic_row()`: `scored_at` stamped from a single `run_ts` pinned once at the top of `_execute_inner` (D-142A-R2); `event_row_id = BaseBatch.content_key(symbol, tf, regime, lookahead)` is run_ts-independent.
- `service_auditor.py`: `indicagent-ensemble-ic-engine` registered at DAG priority 8 and in `_ONESHOT_UNITS`; no `_AGENT_ID_TO_UNIT` entry needed (BaseBatch emits `job=`, not `agent_id=`).
- 6 new unit test files (23 tests), all pure-numpy/pure-Python — no DB, no Kafka.

## Task Commits

1. **Task 1: Migration 195 — alpha_ensemble_ic hypertable + APR seeds** - `a3d8f4c8` (feat)
2. **Task 2: EnsembleICEngine service — BaseBatch shell + IC math composition + Wave 0 unit tests** - `78995a08` (feat)
3. **Task 3: Register indicagent-ensemble-ic-engine in service_auditor** - `fa1072c3` (feat)

_Note: tdd="true" tasks (1 and 2) followed RED-then-GREEN internally within a single commit per task — new tests were written and confirmed failing (ModuleNotFoundError / missing table) before the implementation was added, per the plan's TDD flow, but committed together as the task's atomic unit per plan Task boundaries._

## Files Created/Modified

- `production/migrations/195_alpha_ensemble_ic.sql` - alpha_ensemble_ic hypertable + 43 APR seeds (renumbered from plan's 187 — see Deviations)
- `services/ensemble_ic_engine.py` - EnsembleICEngine(BaseBatch), EnsembleICConfig, compute_walk_forward_stable, build_ensemble_ic_row, _run_ensemble_ic_worker, _assert_prerequisites
- `tests/unit/test_ensemble_ic_math.py` - IC parity vs scipy.stats.spearmanr, Fisher-z CI signal/null fixtures
- `tests/unit/test_ensemble_ic_config.py` - EnsembleICConfig.from_apr binding, frozen + pickle-safe
- `tests/unit/test_ensemble_ic_bh_fdr.py` - single corpus-level multipletests call, offset-index scatter pattern
- `tests/unit/test_ensemble_ic_executable_returns.py` - Invariant 1 grep-as-test on source file
- `tests/unit/test_ensemble_ic_wf_stability.py` - EIC-03 fold IC-magnitude ratio behavior (D-142A-R1)
- `tests/unit/test_ensemble_ic_idempotency.py` - scored_at/event_row_id run_ts independence (D-142A-R2)
- `services/service_auditor.py` - `_DAG_ORDER` + `_ONESHOT_UNITS` registration
- `.planning/phases/142A-ensemble-ic-measurement-planned/deferred-items.md` - 33 pre-existing HMM causal-decode test failures logged, confirmed unrelated to this plan

## Decisions Made

- Migration renumbered 187 → 195 (see Deviations below) — no content change from plan intent, purely a numbering correction.
- `is_pooled`/`symbol='POOLED'` consistency enforced via a DB-level CHECK constraint rather than relying on application discipline alone (matches the plan's explicit review-finding guidance).
- `alpha.ensemble_ic.min_obs_per_regime` seeded at 3000 to mirror the live `alpha.ic.min_obs_per_regime` value (verified via live query before hardcoding, per plan instruction).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug/correctness] Migration renumbered from 187 to 195**

- **Found during:** Task 1 (pre-migration verification)
- **Issue:** The plan specified `production/migrations/187_alpha_ensemble_ic.sql`. At execution time, migrations 186 and 188-194 were already applied in the repo (a gap exists at 187 and 189 — git history shows 187 was previously used for an unrelated `ensemble_weights` demotion migration that was later reverted). Using 187 again would either collide with a stale filename convention or create ambiguity about which "migration 187" is authoritative.
- **Fix:** Renumbered the migration to 195 (next available number after the highest applied migration, 194). Added an explanatory comment block at the top of the file documenting the renumbering and rationale. No content change from the plan's specified DDL/APR seeds — Task 1's `<action>` was followed exactly, only the filename/number changed.
- **Files modified:** `production/migrations/195_alpha_ensemble_ic.sql` (created directly at this number; no separate 187 file was ever created in this worktree)
- **Verification:** `ls production/migrations/ | sort -t_ -k1 -n | tail` confirmed 194 was the highest applied migration before this change; migration applied cleanly and idempotently (verified via double-application test); all Task 1 acceptance criteria pass under the new number.
- **Committed in:** `a3d8f4c8` (Task 1 commit)

**2. [Rule 1 - Bug] Fixed floating-point boundary test fixture**

- **Found during:** Task 2 (writing `test_ensemble_ic_wf_stability.py`)
- **Issue:** The original boundary test used fold ICs `[0.1, 0.3]` expecting the ratio to equal exactly `3.0`, but `0.3/0.1 == 2.9999999999999996` in IEEE-754 double precision, causing a false test failure unrelated to the implementation's correctness.
- **Fix:** Changed the fixture to `[0.05, 0.25]` with `wf_stability_ratio=5.0` (both exactly representable in binary floating point; `0.25/0.05 == 5.0` exactly), preserving the intent of testing the `< threshold` (not `<=`) boundary condition.
- **Files modified:** `tests/unit/test_ensemble_ic_wf_stability.py`
- **Verification:** Test passes; `compute_walk_forward_stable` implementation logic was not changed.
- **Committed in:** `78995a08` (Task 2 commit)

**3. [Rule 1 - Bug] Removed docstring/comment collisions with the "exactly-once" grep gate**

- **Found during:** Task 2 (running the plan's `grep -c "datetime.now(UTC)"` acceptance check)
- **Issue:** Two explanatory comments/docstrings in `services/ensemble_ic_engine.py` used the literal string `datetime.now(UTC)` in prose (describing what `run_ts` is and how `scored_at` is stamped), which caused the plan's grep-based "exactly 1 occurrence" acceptance check to see 3 matches instead of 1, even though the actual code only calls `datetime.now(UTC)` once.
- **Fix:** Reworded the two prose references to describe the same concept without using the literal function-call string (e.g., "UTC 'now' at start" instead of "datetime.now(UTC)").
- **Files modified:** `services/ensemble_ic_engine.py`
- **Verification:** `grep -c "datetime.now(UTC)" services/ensemble_ic_engine.py` now returns exactly 1; `grep -cE "run_ts = datetime.now\(UTC\)"` returns exactly 1; full test suite for this file still green after the edit.
- **Committed in:** `78995a08` (Task 2 commit)

---

**Total deviations:** 3 auto-fixed (2 Rule 1 bug/correctness, 1 Rule 1 numbering collision)
**Impact on plan:** All three are mechanical corrections with zero change to the plan's design intent (methodology, schema shape, APR keys, or IC math composition). No scope creep.

## Issues Encountered

- The full `pytest tests/unit/ -q` suite (5452 tests) takes ~10 minutes to run, dominated by HMM/regime-writer numeric tests; several bash-tool-level timeouts (120s/180s/300s) were hit before letting it run to completion in the background. Not a plan issue — just suite runtime characteristics.
- 33 pre-existing test failures discovered in the full suite run, all in HMM causal-decode / regime-writer files (`test_causal_hmm_decoding.py`, `test_regime_writer.py`, `test_fetch_htf_bars.py`, `test_roll_batch.py`, `test_run_historical_pipeline.py`). Verified via `git diff --stat 8cd562f6 HEAD -- <those files>` returning empty — zero relationship to this plan's changes. Logged to `deferred-items.md`, not fixed (out of scope per CLAUDE.md scope boundary — these are pre-existing failures in files this plan never touched).

## User Setup Required

None - no external service configuration required. Note: `EnsembleICEngine` cannot be executed against the live DB yet — `alpha_events`/`market_regimes` prerequisites depend on the Phase B corpus re-run, and the startup gate will correctly crash loud until that data exists. No execution was attempted in this plan (by design — see plan's `<verification>` section).

## Next Phase Readiness

- Plan 02 (Wave 2: EIC-02 decay calibration, EIC-04 gate, EIC-05 diagnosis) can proceed — it depends on `alpha_ensemble_ic` rows existing, which requires running `EnsembleICEngine` once the Phase B corpus re-run completes and populates `alpha_events`/`market_regimes` with in-sample data.
- `EnsembleICConfig` already carries all fields Plan 02 will need (`decay_threshold`, `min_qualifying_fraction`, `wf_stability_ratio`, `gate_lookahead`, `wf_stability_metric`, `min_obs_per_regime`), so no additional APR binding work should be needed there.
- 33 pre-existing HMM/regime-writer test failures are flagged in `deferred-items.md` for separate investigation — not a blocker for 142A-02 or Phase 142B, but worth triaging before those areas are touched again.

---
*Phase: 142A-ensemble-ic-measurement-planned*
*Completed: 2026-07-02*
