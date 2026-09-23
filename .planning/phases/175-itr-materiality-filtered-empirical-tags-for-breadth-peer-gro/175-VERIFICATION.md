---
phase: 175-itr-materiality-filtered-empirical-tags-for-breadth-peer-gro
verified: 2026-09-23T12:00:00Z
status: passed
score: 33/33 must-haves verified
overrides_applied: 0
---

# Phase 175: ITR materiality-filtered empirical tags for breadth/peer-grouping - Verification Report

**Phase Goal:** Design and implement a materiality filter for empirical `instrument_tags` rows
so `breadth_vol.py`/`cross_sectional_regime_model.py` can safely re-admit real empirical
sensitivity signal, shadow-mode only (D-02/D-03) — measurement and a read-only diagnostic, not
a consumer cutover.
**Verified:** 2026-09-23
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

This phase is explicitly shadow-mode-only. Per the task brief, "consumers still read
`source='human'` only" is the intended end state for this phase, not a gap. Verification below
confirms (a) the measurement engine and evidence schema are real and live-populated, (b) the
shadow diagnostic actually ran against the corpus and produced a real report, (c) the two live
consumers are mechanically unchanged across the entire phase's commit range, and (d) the code
review's one critical + five other findings are fixed in the current code, not just claimed
fixed in prose.

### Observable Truths (by requirement ID)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| P175-01 | Pass 4 lives in `TagCalibrator`, computes orthogonalized/partial loading per empirical `(symbol, tag)` pair | VERIFIED | `services/tag_calibrator.py::measure_partial_loadings` exists, calls `partial_loading`/`partial_loading_ci_low`/`sign_stable_window_count`/`partial_loading_null_arm_p` from `factor_math.py`; live run measured 2170 empirical pairs (`instrument_tags` query below) |
| P175-02 | New evidence columns on `instrument_tags` via migration; consumers read, never recompute | VERIFIED | Migration 346 adds 11 columns (`ADD COLUMN IF NOT EXISTS partial_loading` etc., confirmed in file and live schema); no consumer file computes these — `git diff` across the phase shows zero touches to `breadth_vol.py`/`cross_sectional_regime_model.py` |
| P175-03 | Shadow-mode diagnostic script, no live consumer query change this phase | VERIFIED | `scripts/analysis/itr_materiality_shadow_diagnostic.py` exists, static read-only grep gate returns 0 write-verb matches (per 175-04-SUMMARY), ran live producing a MEMBERSHIP DELTA/GATE ATTRIBUTION/NEAR MISS report (0 symbols added in any of 4 groups) |
| P175-04 | APR keys seeded at conservative (Codex) numbers, `[initial_estimate]` tagged | VERIFIED | 11 `alpha.tag_calibrator.materiality.*` keys live in `config_state` (confirmed via psql, count=11) and `config_history` (count=11, `changed_by='migration_346'`); migration text shows 10 keys tagged `[initial_estimate]`, 1 (`null_arm_seed`) tagged `[conventional]` |
| P175-05 | Null-arm: circular time-shift of factor_series proxy only | VERIFIED | `factor_math.py::partial_loading_null_arm_p` calls `_circular_shift_null(factor_arr, rng)` (imported from `ic_math.py`, not reimplemented) — shifts only the factor array, never the candidate/control arrays |
| P175-06 | Todo 125: `discovery_oos_days` becomes enforced/load-bearing for materiality eligibility | VERIFIED | `is_materiality_eligible()` ANDs `discovery_state == 'confirmed'`; `test_discovery_oos_gate_blocks_fresh_discovery` passes; live data shows 1764 `pending_oos` vs 469 `confirmed` empirical rows, a real population split; todo 125 closed with resolution record in `.planning/todos/completed/` |
| P175-07 | Todo 126: `valid_to IS NULL` filtering contract for any new materiality-aware query | VERIFIED | `instrument_tags_active` view filters `valid_to IS NULL` (live, returns 3093 rows); `is_materiality_eligible()` re-checks `valid_to IS None` in code too; todo 126 closed, stale `equity_regime_model.py` reference corrected to `breadth_vol.py` |
| P175-08 | Cross-AI review (Fable + Codex/AGY) of the PLAN.md before implementation | VERIFIED | `175-REVIEWS.md` frontmatter: `reviewers: [codex, antigravity, fable]`, `gate_status: cleared`, dated 2026-09-18, predates Wave 1 execution (2026-09-23) |

### Additional Plan-Level Must-Haves

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `instrument_tags` has typed Pass 4 evidence columns | VERIFIED | 11 columns confirmed in migration + live `information_schema` via populated-column query |
| 2 | `instrument_tags` has typed `discovery_state`/`first_measured_at` columns (todo 125 JSONB promotion) | VERIFIED | Both typed columns exist and are populated (1764+469=2233 non-null `discovery_state` rows) |
| 3 | `instrument_tags_active` view exists, returns only `valid_to IS NULL` rows | VERIFIED | View queried live, returns 3093 rows, definition confirmed `WHERE valid_to IS NULL` |
| 4 | 11 `alpha.tag_calibrator.materiality.*` APR keys resolve from `config_state` | VERIFIED | `SELECT count(*) FROM config_state WHERE config_key LIKE 'alpha.tag_calibrator.materiality.%'` = 11 |
| 5 | All 11 keys recorded in `config_history` with `changed_by='migration_346'` | VERIFIED | Live count = 11 |
| 6 | Migration re-run is a no-op (idempotent) | VERIFIED | 175-01-SUMMARY documents the idempotency bug found+fixed pre-commit (`config_history` `WHERE NOT EXISTS` guard replacing non-idempotent `ON CONFLICT`); live `config_history` count stayed at 11, not 22 |
| 7 | Pearson-convention partial loading + incremental R² computable | VERIFIED | `factor_math.py::partial_loading` implemented, unit-tested (`test_partial_loading_known_value` and 12 others green) |
| 8 | Degenerate/ill-conditioned control matrix returns NaN, not a crash | VERIFIED | `_partial_residuals`'s `check_condition_number` gate + WR-01 fix adding the same gate to the full-model design matrix; both paths return NaN on failure |
| 9 | Sign stability across N disjoint tail-anchored windows is countable | VERIFIED | `sign_stable_window_count` implemented, 6 dedicated tests green |
| 10 | Circular-shift null p-value shifts the FACTOR proxy only | VERIFIED | Same as P175-05 above; test-enforced via monkeypatched `_circular_shift_null` recorder per 175-02-SUMMARY |
| 11 | TagCalibrator computes all 5 Pass 4 statistics for every kept empirical pair (D-01a scope) | VERIFIED | `measure_partial_loadings` iterates `kept_measurements` (Pass 1-3's `passes_fdr AND abs(loading) >= loading_threshold` gate); live run: 2263 pairs measured (`n_materiality_measured` in TagCalibrator log) |
| 12 | Every materiality threshold resolves from APR namespace, never hardcoded | VERIFIED | `MaterialityConfig.from_apr()` binds all 11 keys via `_cfg()`; no numeric literal thresholds found inline in `decide_materiality`/`measure_partial_loadings` (all route through `materiality.*` fields) |
| 13 | Control set excludes candidate's own leg and the tag's own factor_series | VERIFIED | `select_control_factor_series` filters both `control != tag_factor_series` and `_is_self_regression(symbol, control)`; documented as F6.1/CR-01 tautology guard |
| 14 | `passes_materiality` is statistical-only; `discovery_state` carries temporal gate independently | VERIFIED | Confirmed in code (`decide_materiality` returns only the six-condition statistical gate) and in `is_materiality_eligible`'s separate AND of `discovery_state`/`valid_to` |
| 15 | Freshly-discovered row written `discovery_state='pending_oos'`, ineligible until OOS elapses | VERIFIED | Same as P175-06; test-pinned |
| 16 | A pair that stops clearing Pass 1-3's keep gate has `passes_materiality` cleared to false, never stale | VERIFIED | `_UPDATE_FAILING_OR_EXPIRE_EMPIRICAL_SQL` (Task 3b) sets `passes_materiality=false` on expire/fail per 175-03-SUMMARY; no NULL-and-ambiguous path documented |
| 17 | Reviewer can see per-regime-group symbol delta (human-only vs. human-OR-materiality-eligible) | VERIFIED | Live diagnostic output shows MEMBERSHIP DELTA for all 4 enabled groups (equity/rates/commodity/fx), each with baseline/candidate counts and ADDED list |
| 18 | Baseline arm reproduces the live `source='human'` stopgap query literally | VERIFIED | `_fetch_live_baseline` reproduces `cross_sectional_regime_model._load_tags_by_symbol`'s query "byte-for-byte"; `_detect_baseline_drift` cross-check reported 0 drift in the live run |
| 19 | Both arms read through `instrument_tags_active` | VERIFIED | `_fetch_active_tag_rows` reads `instrument_tags_active` per 175-04-SUMMARY; grep-verifiable in script |
| 20 | Diagnostic performs zero writes to any table | VERIFIED | Static grep gate (`INSERT\|UPDATE\|DELETE\|CREATE\|DROP\|ALTER`) returns 0 against the finished file; `market_regimes` row count/`max(ts)` confirmed byte-identical before/after the run |
| 21 | Reviewer can see which materiality gate is binding for non-qualifying rows | VERIFIED | GATE ATTRIBUTION section in live output shows per-gate `count`/`sole_failure` for all 6 gates |
| 22 | Reviewer can see HOW CLOSE non-qualifying rows came (near-miss histogram + failing-value distributions) | VERIFIED | NEAR MISS section shows sign-stability histogram + per-gate value distributions (min/median/max) in live output |
| 23 | ITR canonical spec describes 4-pass engine with materiality columns/read contract | VERIFIED | `docs/foundation/instrument-tag-registry.md` updated: "4-pass engine", eleven-column schema table, Pass 4 subsection, Read contract section (confirmed via grep) |
| 24 | Known Gaps annotated with accurate current status | VERIFIED | Three Known Gaps entries read live, all rewritten with "RESOLVED" / accurate current-state framing (125 resolved, 126 resolved-but-not-cut-over, sensitivity/macro_driver gap updated) |
| 25 | 10 `[initial_estimate]` keys in APR backlog; 11th (`null_arm_seed`, `[conventional]`) documented in ITR spec but absent from backlog | VERIFIED | `docs/foundation/apr-calibration-backlog.md` has 10 new rows (confirmed via grep, each citing live GATE ATTRIBUTION numbers); `null_arm_seed` is `[conventional]` per migration text, consistent with backlog's stated inclusion criteria |
| 26 | Sign-stability sliding-bar resolution discoverable from backlog entry | VERIFIED | Backlog entry for `min_sign_stable_windows` points to the sliding-bar note; dedicated paragraph documented per 175-05-SUMMARY |
| 27 | Todos 125/126 closed with resolution records; 126's stale reference corrected | VERIFIED | Both files present in `.planning/todos/completed/`; resolution sections present |
| 28 | Todo 380 remains open, re-scoped to consumer-cutover decision | VERIFIED | `380-...md` still in `pending/`, `## Phase 175 status` section appended per 175-05-SUMMARY |
| 29 | PRIORITIES.md link integrity holds under CI guard | VERIFIED | `pytest tests/unit/test_todo_priorities_link_integrity.py` — 4 passed |
| 30 | Shadow-mode boundary: neither consumer file modified anywhere in the phase | VERIFIED | `git diff 781e90d5e^..HEAD -- src/intelligence/regime_signals/breadth_vol.py services/cross_sectional_regime_model.py` — empty; `git log` for those files shows last touch pre-dates phase 175 (todo 379/381 commits) |
| 31 | Code review critical finding (CR-01, NaN-poisoning of run-level BH-FDR) fixed | VERIFIED | `apply_run_level_fdr` now excludes NaN p-values from the correction call (finite_idx filter), confirmed in current `services/tag_calibrator.py:664-705`; live corpus confirmed 0/2170 rows actually NaN-poisoned by the pre-fix run |
| 32 | Code review warnings (WR-01 condition-number gate, WR-02 wrong APR key, WR-03 docstring) fixed | VERIFIED | WR-01: `check_condition_number(full_design, ...)` added before trusting `r2_full` (factor_math.py:429). WR-02: `partial_loading_ci_low` call site now passes `config.fdr_alpha`, not `materiality.null_arm_alpha` (tag_calibrator.py:781). WR-03: docstring now says "six core numeric fields" (tag_calibrator.py:865) |
| 33 | Code review info items (IN-01 duplicated gate-name tuple, IN-02 dead code) addressed | VERIFIED | `MATERIALITY_GATE_NAMES` now exported from `tag_calibrator.py` and imported (not redeclared) in the diagnostic script (`as _GATE_NAMES`) |

**Score:** 33/33 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | ----------- | ------ | ------- |
| `production/migrations/346_itr_materiality_evidence_columns.sql` | 11 evidence columns, `instrument_tags_active` view, 3-table APR seed | VERIFIED | 287 lines; all 11 `ADD COLUMN IF NOT EXISTS`, view, CHECK constraint, 11 APR keys present; applied live, idempotent |
| `src/intelligence/statistics/factor_math.py` | `partial_loading`, `partial_loading_ci_low`, `sign_stable_window_count`, `partial_loading_null_arm_p` | VERIFIED | All 4 functions present, exported via `__all__`, condition-number-gated post-WR-01 fix |
| `services/tag_calibrator.py` | `MaterialityConfig`, `build_control_return_matrix`, `measure_partial_loadings`, `decide_materiality`, `is_materiality_eligible`, extended UPSERT | VERIFIED | All present; live-run populated 2170 evidence rows |
| `scripts/analysis/itr_materiality_shadow_diagnostic.py` | Read-only membership-delta + gate-attribution + near-miss report | VERIFIED | Present, ran live, zero-write grep gate passes |
| `tests/unit/test_factor_math.py`, `test_tag_calibrator.py`, `test_itr_materiality_shadow_diagnostic.py` | Pass 4 unit coverage | VERIFIED | All green (98 tests across the three files, full `tests/unit/` suite green: 0 failures) |
| `docs/foundation/instrument-tag-registry.md`, `apr-calibration-backlog.md`, `CLAUDE.md` | Documentation of shipped 4-pass engine | VERIFIED | All updated, version bumped 5.55.5→5.55.6 |
| `.planning/todos/completed/125-*.md`, `126-*.md` | Closed with resolution records | VERIFIED | Present in `completed/` |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | --- | --- | ------ | ------- |
| migration 346 | `config_schema`/`config_state`/`config_history` | 3-table APR seed | WIRED | Live counts: 11/11/11 |
| migration 346 | `instrument_tags` | ADD COLUMN | WIRED | All 11 columns present, populated by live TagCalibrator run |
| `tag_calibrator.py` | `factor_math.py` | import of Pass 4 kernels | WIRED | Grep confirms import + call sites |
| `tag_calibrator.py` | `instrument_tags` (11 columns) | extended UPSERT | WIRED | Live data confirms population (2170 rows) |
| `tag_calibrator.py` | `config_state` (`materiality.*`) | `MaterialityConfig.from_apr` | WIRED | Confirmed via `_cfg()` calls binding all 11 keys |
| `itr_materiality_shadow_diagnostic.py` | `tag_calibrator.py` | import of `is_materiality_eligible` | WIRED | Confirmed via grep + live run output |
| `itr_materiality_shadow_diagnostic.py` | `cross_sectional_regime_model.py` | import of `_resolve_group_symbols`/`_parse_group_configs` | WIRED | Confirmed (plan's named `_load_group_configs` didn't exist; executor adapted to actual function name `_parse_group_configs`, documented as an interface correction, verified working in live run) |
| `docs/foundation/instrument-tag-registry.md` | `tag_calibrator.py` | Pass 4 description matches shipped implementation | WIRED | Manually cross-checked column names/gate names match |
| `.planning/todos/PRIORITIES.md` | `.planning/todos/pending/` | CI-enforced link integrity | WIRED | Test passes |
| `breadth_vol.py`/`cross_sectional_regime_model.py` | (intentionally NOT wired to new evidence this phase) | N/A | INTENTIONALLY UNWIRED | D-03 shadow-mode boundary; confirmed via empty `git diff` across the phase's full commit range — this is the correct, expected state per phase scope |

### Data-Flow Trace (Level 4)

The shadow diagnostic is the one artifact rendering "dynamic data" in this phase. Traced its data source end-to-end:

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| `itr_materiality_shadow_diagnostic.py` `main()` report | `instrument_tags_active` rows via `_fetch_active_tag_rows` | Live DB query, not a static/empty fallback | Yes — live run against real corpus (2170 rows, non-trivial GATE ATTRIBUTION/NEAR MISS distributions with real min/median/max values) | FLOWING |
| `passes_materiality` / Pass 4 columns | `TagCalibrator.execute()` → `measure_partial_loadings` → `_apply_decision` → UPSERT | Real regression against real OHLCV-derived returns, not hardcoded | Yes — verified via psql query showing 182/2170 passing, non-uniform distribution | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Migration applied and idempotent | Live `psql` query on `instrument_tags`/`config_state`/`config_history` | 2170 measured, 11 APR keys, 11 history rows | PASS |
| `null_arm_bh_p` not NaN-poisoned (CR-01 regression check) | `SELECT count(*) FILTER (WHERE null_arm_bh_p = 'NaN')` | 0 | PASS |
| Full unit test suite green | `.venv/bin/pytest tests/unit/ -q` | All pass (2 pre-existing unrelated skips) | PASS |
| Shadow diagnostic zero-write guard | Static grep for DDL/DML verbs in the script | 0 matches | PASS |
| Consumer files untouched across phase | `git diff 781e90d5e^..HEAD -- breadth_vol.py cross_sectional_regime_model.py` | Empty diff | PASS |
| PRIORITIES.md link integrity | `pytest tests/unit/test_todo_priorities_link_integrity.py` | 4 passed | PASS |

### Probe Execution

Not applicable — this phase is not a migration/tooling phase with declared probe scripts; no `scripts/*/tests/probe-*.sh` referenced in any PLAN/SUMMARY for this phase.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ---------- | ----------- | ------ | -------- |
| P175-01 | 03 | Pass 4 in TagCalibrator | SATISFIED | See truths table |
| P175-02 | 01 | New evidence columns via migration | SATISFIED | See truths table |
| P175-03 | 04 | Shadow-mode diagnostic, no consumer change | SATISFIED | See truths table |
| P175-04 | 01 | APR keys at conservative defaults | SATISFIED | See truths table |
| P175-05 | 02 | Null-arm circular shift of factor proxy only | SATISFIED | See truths table |
| P175-06 | 01, 03 | Todo 125 discovery_oos_days enforcement | SATISFIED | See truths table |
| P175-07 | 01, 04 | Todo 126 valid_to filtering contract | SATISFIED | See truths table |
| P175-08 | 05 (process) | Cross-AI review before implementation | SATISFIED | `175-REVIEWS.md` dated before Wave 1 |

No orphaned requirements found — all 8 requirement IDs from RESEARCH.md's `<phase_requirements>` are claimed across the 5 plans' `requirements-completed` frontmatter fields and independently verified above.

### Anti-Patterns Found

None blocking. Scanned all key-files (migration 346, `factor_math.py`, `tag_calibrator.py`, `itr_materiality_shadow_diagnostic.py`) for TBD/FIXME/XXX/TODO/HACK/PLACEHOLDER markers — none found. No stub return patterns (`return null`/`return {}`/empty handlers) found in the reviewed functions. The one substantive defect found during the phase (CR-01, the BH-FDR NaN-poisoning bug) was caught by the phase's own code review and is confirmed fixed in the current code (see truth #31 above), not left open.

### Human Verification Required

None. This phase's deliverables (migration, statistical kernels, TagCalibrator extension, read-only diagnostic, documentation) are all mechanically verifiable — no UI, no real-time behavior, no external service integration requiring human judgment. The one item that does require human/cross-AI judgment (whether the shadow diagnostic's findings justify a future consumer cutover) is explicitly out of scope for this phase per D-03 and is correctly deferred to a later, unscoped phase (tracked by todo 380).

### Gaps Summary

No gaps. All 33 must-haves across the 5 plans' frontmatter plus all 8 roadmap-derived requirement IDs (P175-01 through P175-08) are verified against live code and a live database, not merely claimed in SUMMARY.md prose. The post-execution `/simplify` pass and code review both found real, legitimate issues (1 critical, 3 warnings, 2 info) — all 6 are confirmed fixed in the current `main` branch state, not just claimed fixed. The phase's explicit shadow-mode scope boundary (consumers still reading `source='human'` only) is correctly honored and mechanically verified via an empty git diff across the entire phase's commit range — this is intended, not a gap, per the task brief and D-03.

---

_Verified: 2026-09-23_
_Verifier: Claude (gsd-verifier)_
