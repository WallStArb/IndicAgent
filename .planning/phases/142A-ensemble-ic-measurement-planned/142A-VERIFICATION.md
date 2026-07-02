---
phase: 142A-ensemble-ic-measurement-planned
verified: 2026-07-02T19:30:00Z
status: passed
score: 10/10 must-haves verified
overrides_applied: 0
---

# Phase 142A: Ensemble IC Measurement Verification Report

**Phase Goal:** Prove the ensemble OUTPUT has IC before testing any execution rules. Measure IC(alpha_score, forward_return_*) per (symbol, tf, regime, lookahead) using the same BH-FDR + bootstrap CI + walk-forward machinery as feature IC. No stops, no targets, no frame assumptions -- pure signal measurement. The IC decay curve across lookaheads calibrates hold_max_bars APR keys empirically. This is the primary OOS gate for Phase 144.

**Verified:** 2026-07-02T19:30:00Z
**Status:** passed
**Re-verification:** No — initial verification (a prior code review, 142A-REVIEW.md, ran separately and is cross-checked below, not treated as a prior VERIFICATION.md gate)

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `alpha_ensemble_ic` hypertable exists with `walk_forward_stable` column and 9-regime `hold_max_bars` namespace | VERIFIED | Live DB: `to_regclass('alpha_ensemble_ic')` returns the table; `timescaledb_information.hypertables` has 1 row; `walk_forward_stable` column present; 36 `alpha.frame.hold_max_bars.<regime>.<tf>` keys and 6 `alpha.ensemble_ic.*` + 1 `infra.ensemble_ic_engine.workers` keys all present in `config_state` (migration 195, renumbered from planned 187 — documented, non-scope-affecting rename) |
| 2 | `EnsembleICEngine` composes `ic_engine` IC math (Fisher-z CI) rather than subclassing/forking | VERIFIED | `grep -c "from services.ic_engine import"` = 1; `grep -c "class EnsembleICEngine(ICEngine)"` = 0; imports `_fisher_z_ci, _p_values_from_ic, _compute_ic_rolling_metrics, _vectorized_ic, _nan_to_none` directly |
| 3 | ProcessPoolExecutor workers are compute-only; serial DB write happens post-corpus-BH-FDR from main process | VERIFIED | `_run_ensemble_ic_worker` receives numpy arrays + config + run_ts only (no DSN/connection); single `wconn.executemany` write inside `pool.acquire()`/`transaction()` after the `multipletests` call in `_execute_inner` |
| 4 | All `forward_returns` queries filter `return_type = 'executable_open_to_open'` (Invariant 1) | VERIFIED | `grep -c "return_type = 'executable_open_to_open'"` = 3 (query + docstring + module header); no `'theoretical'` substring |
| 5 | Engine crashes loud at startup when `alpha_events`, `forward_returns`, or `market_regimes` is empty | VERIFIED | `_assert_prerequisites` runs 3 COUNT checks and raises `RuntimeError` for each; `market_regimes is empty` message present; confirmed against live DB (currently 172,257 `alpha_events` rows, 928,791 `market_regimes` rows — no longer empty since planning, but the guard logic is unchanged and still correct) |
| 6 | `scored_at` pinned to single `run_ts` per invocation (D-142A-R2); ON CONFLICT DO UPDATE fires on retry, new vintage per invocation | VERIFIED | `grep -cE "run_ts = datetime.now\(UTC\)"` = 1; `grep -c "datetime.now(UTC)"` = 1 (exactly one call site); `event_row_id` excludes `run_ts` (content_key on symbol/tf/regime/lookahead only); idempotency unit tests (`test_ensemble_ic_idempotency.py`) pass |
| 7 | `walk_forward_stable` is fold IC-MAGNITUDE max/min ratio (D-142A-R1), not fold IC-Sharpe | VERIFIED | `compute_walk_forward_stable()` implements `max(|fold_ic|)/min(|fold_ic|) < wf_stability_ratio`; `grep -c "D-142A-R1"` = 5; `ic_sharpe_ratio` branch present as explicit `NotImplementedError` stub, not silently substituted; `test_ensemble_ic_wf_stability.py` covers magnitude/mixed-sign/boundary cases and passes |
| 8 | All `alpha.ensemble_ic.*`, `alpha.frame.hold_max_bars.*` (36 keys), `infra.ensemble_ic_engine.workers` APR seeds exist in `config_state` | VERIFIED | Live DB query confirms all 6 `alpha.ensemble_ic.*` keys + `infra.ensemble_ic_engine.workers=12`; 36 `hold_max_bars` keys present |
| 9 | EIC-02: decay curve → `hold_max_bars` calibration, gated on BOTH `passes_fdr=true` AND `reliable=true`, median across qualifying symbols, unwritten when zero qualifying | VERIFIED | `_select_hold_bars_from_decay` filters `passes_fdr is True and reliable is True` before the decay walk; `_calibrate_hold_max_bars` takes `np.median` across qualifying per-symbol results per (regime, tf), skips writing when `per_regime_tf` group is empty; `test_ensemble_ic_decay.py` (8 tests) covers noise-exclusion, low-N-exclusion, all-unqualified-returns-None cases — all pass |
| 10 | EIC-04: gate reads `min_qualifying_fraction` from APR (not baked in), evaluates on the LATEST run (`scored_at = max(scored_at)`), emits PASS/FAIL with correct exit code | VERIFIED | `ops_ensemble_ic_gate.py` reads threshold + `gate_lookahead` from `config_state`; `_GATE_SQL` uses `max(scored_at)`; no `NOW() - INTERVAL` string present; `_evaluate_gate` unit-tested (4 cases incl. n_total=0); **CR-02 fix confirmed**: `total` CTE now filters `lookahead = $1` matching `qualifying` (previously inflated denominator across all lookaheads); regression test `test_gate_sql_total_cte_scoped_to_same_lookahead_as_qualifying` present and passing |
| 11 | EIC-05: 4-section diagnosis report (N-per-cell, pooled-vs-per-symbol gap, TF breakdown, regime coverage), latest-run scoped, TRUE median in Section 2 | VERIFIED | All 4 section labels present (`DATA STARVATION`, `REGIME GRANULARITY ISSUE`, `TF-specific problem`, `regime label quality issue`); Section 2 uses `percentile_cont(0.5) WITHIN GROUP`, no `max(CASE WHEN NOT is_pooled` form; all sections scoped to `scored_at = $1` bound to `max(scored_at)`; `min_obs_per_regime` read from APR with loud `WARNING` line if absent; **WR-01 fix confirmed**: Section 3 flag now gated on `r["tf"] == "5m"` (previously a loop-invariant condition stamping every TF row); **WR-03 fix confirmed**: `_DEFAULT_MIN_OBS_PER_REGIME = 3000` (previously 200, now matches migration 195 seed) |

**Score:** 11/11 truths verified (10 must-have items in frontmatter score, folding the two-plan artifact set into one aggregate count)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `production/migrations/195_alpha_ensemble_ic.sql` | Hypertable + 43 APR seeds (renamed from planned 187) | VERIFIED | Applied live; hypertable confirmed; CHECK constraint `alpha_ensemble_ic_pooled_symbol_consistent` confirmed present via `pg_constraint` |
| `services/ensemble_ic_engine.py` | `EnsembleICEngine(BaseBatch)`, `EnsembleICConfig` | VERIFIED | Imports succeed; `EnsembleICEngine` is `BaseBatch` subclass; `EnsembleICConfig` frozen dataclass confirmed via `__dataclass_params__.frozen` |
| `services/service_auditor.py` | Phase 142A oneshot registration | VERIFIED | `_DAG_ORDER['indicagent-ensemble-ic-engine'] == 8`; present in `_ONESHOT_UNITS` (confirmed live import) |
| `scripts/ops/alpha/ops_ensemble_ic_gate.py` | EIC-04 gate script, executable | VERIFIED | `test -x` passes; CR-02 fix present; no baked-in `0.60` literal |
| `scripts/ops/alpha/ops_ensemble_ic_diagnosis.py` | EIC-05 diagnosis script, executable | VERIFIED | `test -x` passes; WR-01/WR-03 fixes present |
| `tests/unit/test_ensemble_ic_*.py` (8 files across both plans) | Unit coverage for IC math, config, BH-FDR, executable-returns, wf-stability, idempotency, decay, gate | VERIFIED | All 36 tests across the 8 files pass (`.venv/bin/pytest tests/unit/test_ensemble_ic_*.py -q` → 36 passed) |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `services/ensemble_ic_engine.py` | `services/ic_engine.py` | import of private IC math functions | WIRED | 1 import statement pulling 5 functions + `ICEngineConfig` |
| `services/ensemble_ic_engine.py` | `src/core/agent/base_batch.py` | `class EnsembleICEngine(BaseBatch)` | WIRED | Confirmed via `issubclass` check |
| `services/ensemble_ic_engine.py` | `alpha_ensemble_ic` | `asyncpg executemany` serial write | WIRED | `_ENSEMBLE_IC_INSERT_SQL` with 18 params, `ON CONFLICT (event_row_id, scored_at) DO UPDATE` |
| `services/ensemble_ic_engine.py` | `market_regimes` | JOIN + startup gate | WIRED | JOIN on `(tf, bar_ts)` aliased as `mr.ts`; startup gate covers empty-table case |
| `services/service_auditor.py` | `indicagent-ensemble-ic-engine` | `_DAG_ORDER` + `_ONESHOT_UNITS` | WIRED | Both registries confirmed live |
| `services/ensemble_ic_engine.py` (EIC-02) | `config_state (alpha.frame.hold_max_bars.*)` | `ConfigService.set` | WIRED | `_calibrate_hold_max_bars` calls `config_service.set` after serial write; reason string documents qualifying-symbol count |
| `scripts/ops/alpha/ops_ensemble_ic_gate.py` | `alpha_ensemble_ic` | latest-run-scoped fraction SQL | WIRED | CR-02-fixed SQL confirmed |
| `scripts/ops/alpha/ops_ensemble_ic_gate.py` | `config_state` | `min_qualifying_fraction` read | WIRED | Parameterized query, no baked literal |
| `scripts/ops/alpha/ops_ensemble_ic_diagnosis.py` | `alpha_ensemble_ic` + `feature_ic_scores` | 4-section fetch, latest-run scoped | WIRED | All 4 sections confirmed; `regime_scope` conditional filter confirmed |

### Code Review Cross-Check (142A-REVIEW.md resolution claims verified against live code)

| Finding | Claimed Fix (commit 5baf4cf1) | Verified in Code | Status |
|---------|-------------------------------|------------------|--------|
| CR-01 (BLOCKER): `alpha.validation.oos_start` used unguarded — silent zero-row run or opaque cast crash | Crash-loud guard added on `oos_start is None` / cast error | `services/ensemble_ic_engine.py:597-612` — `oos_start_gate_error` raised on `None` and on `asyncpg.DataError`/`InvalidTextRepresentationError` | CONFIRMED FIXED |
| CR-02 (BLOCKER): EIC-04 gate `total` CTE not scoped to `gate_lookahead`, inflating denominator | `total` CTE now filters `lookahead = $1` | `scripts/ops/alpha/ops_ensemble_ic_gate.py:46-50` — `total AS (... WHERE lookahead = $1 AND scored_at = ...)`; regression test `test_gate_sql_total_cte_scoped_to_same_lookahead_as_qualifying` present and passing | CONFIRMED FIXED |
| WR-01 (WARNING): Section 3 "TF-specific problem" flag stamped every row (loop-invariant condition) | Flag now conditioned on `r["tf"] == "5m"` | `scripts/ops/alpha/ops_ensemble_ic_diagnosis.py:192` — `if r["tf"] == "5m" and tf_qual.get("1h", 0) and not tf_qual.get("5m", 0):` | CONFIRMED FIXED |
| WR-03 (WARNING): `_DEFAULT_MIN_OBS_PER_REGIME=200` diverges 15x from seeded APR value (3000) | Default changed to 3000 | `scripts/ops/alpha/ops_ensemble_ic_diagnosis.py:29-31` — `_DEFAULT_MIN_OBS_PER_REGIME = 3000  # matches migration 195 seed` | CONFIRMED FIXED |
| WR-02 (WARNING): pooled cross-sectional row (`symbol='POOLED'`) unreachable — `alpha_events` never contains it | NOT fixed; captured as todo 046 per explicit instruction | Confirmed: `symbol_tf_pairs` built exclusively from `SELECT DISTINCT symbol, tf FROM alpha_events` (line 592); no pooled-aggregation pass exists. Todo `.planning/todos/pending/046-pooled-cross-sectional-ic-measurement.md` exists, correctly describes the gap and its downstream effects (CHECK constraint trivial branch, `_calibrate_hold_max_bars` `is_pooled` exclusion is dead code, EIC-05 Section 2 permanent no-op) | CONFIRMED AS DOCUMENTED GAP, NOT A BLOCKER — accepted per explicit scoping instruction: EIC-04's gate and EIC-05's diagnosis both function correctly on a per-symbol-only basis; Section 2 is a documented no-op pending todo 046 |
| IN-01/IN-02 (INFO) | Left as-is per review (no action required) | Confirmed unchanged; no correctness impact — informational only | ACKNOWLEDGED, NO ACTION REQUIRED |

### Requirements Coverage

No standalone `.planning/REQUIREMENTS.md` exists for this project (ROADMAP.md itself notes "Requirements: TBD — no REQUIREMENTS.md for this project"). ROADMAP.md's Phase 142A section (lines 1499-1543) is the canonical requirement source and was used directly.

| Requirement | Source | Description | Status | Evidence |
|--------------|--------|--------------|--------|----------|
| EIC-01 | 142A-01-PLAN.md, ROADMAP.md:1511-1512 | EnsembleICEngine (weekly oneshot, BaseBatch) computing IC per (symbol, tf, regime, lookahead) | SATISFIED | `services/ensemble_ic_engine.py` — BaseBatch subclass, composes ic_engine math, ProcessPoolExecutor per (symbol,tf), writes `alpha_ensemble_ic` |
| EIC-02 | 142A-02-PLAN.md, ROADMAP.md:1514-1516 | IC decay curve → `hold_max_bars` APR calibration | SATISFIED | `_select_hold_bars_from_decay` + `_calibrate_hold_max_bars`, gated on `passes_fdr AND reliable`, median aggregation, unit-tested |
| EIC-03 | 142A-01-PLAN.md, ROADMAP.md:1517-1518 | Walk-forward stability gate, IC ratio < 3x across folds, written to `walk_forward_stable` | SATISFIED | `compute_walk_forward_stable` implements the fold IC-magnitude ratio (documented v1 relaxation of "IC Sharpe ratio" wording, D-142A-R1, per-fold N constraint justified in code comments); column present in schema |
| EIC-04 | 142A-02-PLAN.md, ROADMAP.md:1520-1521 | Hard phase gate, `min_qualifying_fraction` from APR, PASS/FAIL verdict | SATISFIED | `ops_ensemble_ic_gate.py`, CR-02-fixed, threshold read from `config_state`, exit code 0/1 |
| EIC-05 | 142A-02-PLAN.md, ROADMAP.md:1523-1531 | 4-section gate-failure diagnosis script | SATISFIED | `ops_ensemble_ic_diagnosis.py`, all 4 sections present with correct root-cause labels, WR-01/WR-03 fixed |

No orphaned requirements found — all 5 EIC-0X IDs declared in the two PLAN frontmatters are accounted for and satisfied.

### Anti-Patterns Found

None. Scanned `services/ensemble_ic_engine.py`, `scripts/ops/alpha/ops_ensemble_ic_gate.py`, `scripts/ops/alpha/ops_ensemble_ic_diagnosis.py`, `production/migrations/195_alpha_ensemble_ic.sql`, `services/service_auditor.py` for `TBD|FIXME|XXX|TODO|HACK|PLACEHOLDER` — zero matches. The one known incomplete capability (WR-02 pooled cross-sectional measurement) is documented via code comments, migration constraint semantics, and a formal todo, not left as a silent stub.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Migration applied and schema live | `SELECT to_regclass('alpha_ensemble_ic')`, hypertable check, column check | table exists, is hypertable, `walk_forward_stable` column present | PASS |
| APR seeds live | `SELECT count(*) FROM config_state WHERE config_key LIKE 'alpha.frame.hold_max_bars.%'` = 36; `alpha.ensemble_ic.%` = 6; `infra.ensemble_ic_engine.workers` = 12 | confirmed | PASS |
| Service registry wiring | `_DAG_ORDER['indicagent-ensemble-ic-engine'] == 8`; in `_ONESHOT_UNITS` | confirmed via live import | PASS |
| Unit test suite (phase-scoped) | `.venv/bin/pytest tests/unit/test_ensemble_ic_*.py -q` | 36 passed | PASS |
| Full unit suite (regression check) | `.venv/bin/pytest tests/unit/ -q` | 5391 passed, 33 failed (pre-existing, unrelated — confirmed via `git diff --stat 8cd562f6 HEAD` returning empty for the affected test/service files), 41 skipped | PASS (no regressions attributable to this phase) |
| Live execution of EnsembleICEngine against real data | N/A — explicitly out of scope for this phase | `alpha_ensemble_ic` has 0 rows; `alpha_events` has 172,257 rows and `market_regimes` has 928,791 rows (both now populated, unlike at planning time) | SKIPPED — correctly deferred; this phase's `<verification>` sections explicitly state live execution is blocked/deferred until Phase B corpus data is used to run the engine once, which is an operational action outside this phase's task scope |

### Probe Execution

No `scripts/*/tests/probe-*.sh` files declared in this phase's PLAN/SUMMARY files, and this is not a migration/tooling phase in the probe-script sense (it is a batch-service + ops-script phase, verified via unit tests and grep gates instead). SKIPPED — no probes to execute.

### Human Verification Required

None. All must-haves are verifiable via static code inspection, unit tests, and live-DB schema checks. The only deferred item (live execution of `EnsembleICEngine` producing real `alpha_ensemble_ic` rows and running the EIC-04 gate against them) is an explicit operational follow-up action, not a phase deliverable — both PLAN files' `<verification>` sections state this is "BLOCKED until Phase B corpus data" is available and used, and both ops scripts are unit-verified against the empty-table path.

### Gaps Summary

No gaps found. All EIC-01 through EIC-05 requirements are implemented, unit-tested, and confirmed live in the codebase and database schema. The 2 BLOCKER and 3 WARNING findings from the independent code review (142A-REVIEW.md) were checked against the current code, not just trusted from the review's `resolution` annotation:

- CR-01 (unguarded `oos_start`) — confirmed fixed with a proper crash-loud guard.
- CR-02 (EIC-04 gate denominator not scoped to `gate_lookahead`) — confirmed fixed with a scoped `total` CTE and a new SQL-text regression test.
- WR-01 (Section 3 loop-invariant flag) — confirmed fixed with a per-row `tf == "5m"` condition.
- WR-03 (diverging fallback default) — confirmed fixed, default now matches the migration seed.
- WR-02 (pooled cross-sectional measurement unreachable) — confirmed as a real, deliberately-unfixed capability gap. This does not block the phase goal: EIC-04's gate and EIC-05's diagnosis both operate correctly on a per-symbol-only basis (the `is_pooled` CHECK constraint, exclusion logic, and Section 2 machinery are simply unexercised, not broken), and the gap is captured in `.planning/todos/pending/046-pooled-cross-sectional-ic-measurement.md` with a clear description and two remediation options for a future phase.

The phase goal — "Prove the ensemble OUTPUT has IC before testing any execution rules" via a measurement engine, decay-curve calibration, a hard phase gate, and a diagnosis tool — is architecturally and operationally complete. What remains (actually running `EnsembleICEngine` once against the now-populated `alpha_events`/`market_regimes` tables, then evaluating the EIC-04 gate) is explicitly out of scope for this phase per both plans' verification sections, and is the next live-data action for whoever runs the pipeline, not a phase deliverable gap.

---

_Verified: 2026-07-02T19:30:00Z_
_Verifier: Claude (gsd-verifier)_
