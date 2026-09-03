---
phase: 151-feature-primitives-expansion-theory-motivated-interaction-la
plan: 05
subsystem: feature-factory
tags: [feature-factory, feature-vectors, apr, concept-registry, timescaledb, interaction-primitives, cross-timeframe, calendar]

# Dependency graph
requires:
  - phase: 151-04
    provides: live FeatureVector baseline (277 fields after wave 3), the _PHASE151_CROSS_ASSET_FIELD_NAMES derived-slice persistence pattern this plan extends, CrossAssetRecord NamedTuple precedent for CtfValues
  - phase: 170-feature-domain-concept-registry-migration
    provides: concept_registry/concept_gate schema + ic_engine.py's PARITY PRECONDITION gate, concept_parent join table (migration 283) for real parent_features edges
provides:
  - 5 new FeatureVector fields (282 total) -- ret_div_1m_5m/5m_1h/1h_1d (nullable, timeframe-pinned cross-TF return divergences) + opex_flag/quad_witching_flag (non-nullable calendar event flags)
  - migration 290 (feature_vectors columns, 5 feature_registry tier=1_interaction rows each with exactly 2 parents, concept_registry/concept_gate/concept_parent parity: 5/5/10)
  - CtfValues NamedTuple (services/backfill_feature_factory.py) -- extends the CTF payload with htf_last_log_ret, keyword-construction-only
  - _build_ltf_return_series -- new O(n+m) causal merge-walk builder for the 1m/5m divergence
  - _opex_flag/_quad_witching_flag pure calendar helpers (src/intelligence/feature_factory.py)
  - test_every_interaction_row_has_exactly_two_parents -- permanent live-DB regression guard against ROADMAP's parent_features=[] design-rules error
  - scan_binary_patterns.py allowlist entry for opex_flag (definitional binary event flag, not a continuous score)
affects: [151-06, 151-08, 151-09]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "CtfValues NamedTuple (keyword-construction-only) extending a growing multi-field payload -- same pattern as CrossAssetRecord (151-04), applied a second time to the CTF dict payload"
    - "O(n+m) causal merge-walk over two independently-sourced, differently-grained sorted timestamp lists (1m vs 5m) -- new pattern, distinct from the single-series _*_series_full precompute idiom used everywhere else in feature_factory.py"
    - "Live-DB-read-with-graceful-skip unit test (modeled on test_spread_leg_pair_validity.py) for a data-contract invariant that a synthetic fixture can't genuinely protect -- parent_features arity"

key-files:
  created:
    - production/migrations/290_named_interaction_primitives.sql
  modified:
    - src/intelligence/schemas.py
    - src/intelligence/feature_factory.py
    - src/intelligence/features/feature_vector_persistence.py
    - services/backfill_feature_factory.py
    - tools/scan_binary_patterns.py
    - tests/unit/intelligence/test_feature_factory_batch.py
    - tests/unit/intelligence/test_feature_factory_batch_parity.py
    - tests/unit/intelligence/test_feature_factory_p7.py
    - tests/unit/intelligence/test_feature_registry_service.py
    - tests/unit/services/test_backfill_feature_factory.py
    - tests/unit/services/test_feature_vector_writer.py
    - tests/unit/services/test_feature_vector_writer_column_mapping.py
    - tests/unit/test_canary_predictors.py
    - tests/unit/test_feature_factory.py

key-decisions:
  - "Live codebase baseline was 277 fields at execution time, not the plan's stale 200/205/209 assumption (written 2026-07-24) -- 151-01/02/03/04 landed 77 intervening fields since. Scaled every downstream number (docstring tallies, migration numbering, INSERT SQL column count 286->291, test assertions across 7 files) to the live 277->282 baseline throughout, matching every prior Phase 151 plan's own documented correction pattern."
  - "Migration renumbered 263 (plan's provisional target) -> 290 (actual next-free number, re-verified against both `ls production/migrations/` and a live config_history query for any prior migration_290 row before applying)."
  - "_cold_start_vector's signature gained an optional bar_ts: datetime | None = None parameter -- the plan's action text asserted 'bar_ts is available' at cold start, but the live function had no bar_ts parameter at all (only cache, tf). Threaded bar_ts=bars[-1]['ts'] if bars else None from compute()'s single call site so opex_flag/quad_witching_flag compute real values whenever exactly one bar is available (len(bars)==1), falling back to 0.0 only in the true zero-bars case. Single call site, no other callers affected."
  - "Live path (compute()) has NO plumbing for the 3 cross-TF divergences -- always None, same batch-vs-live asymmetry already documented for Plan 04's cross-asset gap (todo filed at that plan's Task 4). opex_flag/quad_witching_flag need only bar_ts (in scope on both paths), so both compute real values on live too."
  - "scan_binary_patterns.py required a new allowlist entry: _opex_flag(bar_ts) == 1.0 (in _quad_witching_flag's body) and its explanatory comment in schemas.py both tripped the equality_check_continuous_1 pattern. Added `re.compile(r\"opex_flag\")` to the Day-of-week/calendar allowlist section rather than obfuscating the code to dodge the regex -- opex_flag is a definitional binary flag (always exactly 1.0 or 0.0, no accumulated float error), the same class of legitimate exact-equality the allowlist already carves out for is_friday/bos_detected/etc."
  - "test_every_interaction_row_has_exactly_two_parents implemented as a live-DB-read-with-graceful-skip test (psycopg, skip if unreachable), not a synthetic fixture, because FeatureRegistryService's own loaded-row schema does not include parent_features at all (it selects feature_name/group_name/tier/status/min_ic_sharpe/min_ic_n/fdr_required/fdr_alpha only) -- a fixture-only test inside that service's own row shape can't exercise this column. Modeled directly on tests/unit/test_spread_leg_pair_validity.py's established live-DB-read shape rather than inventing a new pattern."

requirements-completed: []

# Metrics
duration: ~65min (spans two sessions -- an API session-limit interruption occurred mid-Task-3 investigation; all prior work was verified intact on resume, not redone)
completed: 2026-08-05
---

# Phase 151 Plan 05: Named Interaction Primitives (Cross-TF Divergences + Event Flags) Summary

**5 pre-specified, Fable-reviewed tier-1 interaction primitives (3 nullable cross-TF return divergences + 2 non-nullable calendar event flags) live in the batch compute path via migration 290, with Phase 170 concept_registry/concept_gate/concept_parent parity and a permanent live-DB regression guard against ROADMAP's incorrect parent_features=[] design-rules text.**

## Performance

- **Duration:** ~65 min of active work (spans two sessions -- interrupted by an API session-limit error mid-Task-3 investigation; resumed cleanly, all prior work verified intact via `git status`/`git diff`/test re-run before continuing, nothing redone)
- **Completed:** 2026-08-05
- **Tasks:** 3
- **Files modified:** 15 (1 created: migration 290)

## Accomplishments

- `FeatureVector` grew from 277 to 282 fields, declared as one contiguous 5-field block immediately after 151-04's `rate_beta_z`: `ret_div_1m_5m`, `ret_div_5m_1h`, `ret_div_1h_1d` (`float | None`, no default -- required-but-nullable, same idiom as `equity_beta_z`/`rate_beta_z`) + `opex_flag`, `quad_witching_flag` (`float`, non-nullable).
- **Cross-TF divergences** (todo 066): `ret_div_5m_1h`/`ret_div_1h_1d` reuse `CtfValues.htf_last_log_ret` (the CTF payload extended from a bare 3-tuple to a 4-field `NamedTuple`, keyword-construction-only at its single call site) via the same bisect join `ctf_momentum` already uses. `ret_div_1m_5m` reads a new `_build_ltf_return_series` -- an O(n+m) causal merge-walk over sorted 1m/5m timestamp lists, built only at `tf=="5m"`. All three are `None` at every timeframe other than their pinned lower timeframe; `ret_div_1m_5m` is additionally `None` wherever 1m OHLCV coverage is absent (~99% of the 5m corpus by design -- 1m coverage is 2026-03-23..2026-06-23 versus 5m's 2006-06-02..2026-07-07, a documented data limitation, not a defect). Coverage counts logged once per `(symbol, tf)`, never per row.
- **Calendar event flags** (todo 104): `_opex_flag(bar_ts)` (Friday AND third week of month) and `_quad_witching_flag(bar_ts)` (calls `_opex_flag` directly, AND quarter-end month) -- pure functions of `bar_ts` alone, no market-holiday table (source doc explicitly rejects one as nonstationary). Fire exactly 12x/year and 4x/year respectively, proven by a full synthetic-year unit test. Real values on both live and batch paths, and at cold start whenever `bar_ts` is available (`len(bars)==1`).
- `feature_vector_persistence.py`'s INSERT contract closed: new `_PHASE151_INTERACTION_NAMED_FIELD_NAMES` derived slice, 291 total columns/placeholders (was 286).
- Migration 290 applied to the live DB: 5 `feature_vectors` columns, 5 `feature_registry` rows (`tier='1_interaction'`, `added_phase='151'`, every row with exactly 2 non-empty `parent_features` -- the plan's own binding correction to ROADMAP's `parent_features=[]` text), 5 matching `concept_registry`/`concept_gate` rows, 10 `concept_parent` edges (Phase 170 parity).
- `feature_registry` row count verified live: 282, matching `FeatureVector`'s 282 dataclass fields. All 13 live `tier='1_interaction'` rows (8 pre-existing Renaissance price-volume + 5 new) carry exactly 2 parents -- confirmed by direct query and guarded permanently by a new live-DB regression test.
- `ops_interaction_primitives_pilot.py`'s `_load_interaction_features` run directly against the live DB: returns 13 rows without raising the arity `ValueError`.
- Full `tests/unit/` suite green (0 failures, 2 pre-existing unrelated skips) after every task's commit; `ruff check` clean on all touched Python.

## Task Commits

Each task was committed atomically:

1. **Tasks 1+2 (combined -- schema/compute + persistence wiring, tightly coupled: 5 contiguous fields, same pattern 151-04 used for its own Tasks 1+2)** - `148cc32d` (feat)
2. **Task 3: Migration 290 and permanent parent-arity regression test** - `76f2eb5a` (feat)

_No separate plan-metadata commit -- this is a parallel worktree execution; SUMMARY.md is committed by the orchestrator's post-wave merge step per `parallel_execution` instructions._

## Files Created/Modified

- `production/migrations/290_named_interaction_primitives.sql` (new) - 5 columns, 5 feature_registry rows, 5 concept_registry/concept_gate parity rows, 10 concept_parent edges
- `src/intelligence/schemas.py` - `FeatureVector` +5 fields, docstring tally 277->282
- `src/intelligence/feature_factory.py` - `_opex_flag`/`_quad_witching_flag` helpers, `FEATURE_VECTOR_DOMAIN` +5 entries, `_build_feature_vector` signature/body +5 params, `compute()`/`compute_batch()` both wired (batch via `ltf_ret_by_ts` + `CtfValues.htf_last_log_ret`, live via `None`/real `bar_ts` computation per field), `_cold_start_vector` gains optional `bar_ts` param
- `services/backfill_feature_factory.py` - `CtfValues` NamedTuple, `_build_ctf_series` extended to emit `htf_last_log_ret`, new `_build_ltf_return_series`, `_compute_symbol_tf` fetches 1m bars at `tf=="5m"` and logs coverage once per `(symbol, tf)`
- `src/intelligence/features/feature_vector_persistence.py` - `_PHASE151_INTERACTION_NAMED_FIELD_NAMES` slice, INSERT contract closed (286->291 columns)
- `tools/scan_binary_patterns.py` - allowlist `opex_flag` (definitional binary flag, not a continuous score)
- `tests/unit/intelligence/test_feature_factory_batch.py` - new `TestPhase151CrossTfDivergences` (3 tests: 15m-never-populates guard, 5m parity-to-1e-12, ctf_momentum-unaffected regression)
- `tests/unit/intelligence/test_feature_factory_batch_parity.py` - 2 `_build_feature_vector` direct-call sites extended with the 5 new kwargs
- `tests/unit/intelligence/test_feature_factory_p7.py` - `test_feature_vector_domain_complete` 277->282, 8 new `_opex_flag`/`_quad_witching_flag` unit tests including the full-synthetic-year 12x/4x count proof
- `tests/unit/intelligence/test_feature_registry_service.py` - new `test_every_interaction_row_has_exactly_two_parents` (live-DB-read-with-graceful-skip, T-151-09's first line of defense)
- `tests/unit/services/test_backfill_feature_factory.py` - `_make_zero_vector` +5 fields, `test_vector_to_params_all_features_present` 286->291, new `TestBuildLtfReturnSeries` (4 tests including causality guard)
- `tests/unit/services/test_feature_vector_writer.py` - `_make_valid_feature_vector` +5 fields, 3 hardcoded length assertions 286->291
- `tests/unit/services/test_feature_vector_writer_column_mapping.py` - sentinel record +5 fields, `test_params_length_is_159` 286->291, new `test_quad_witching_flag_at_index_290_is_last_element` replacing the stale tail claim on `test_rate_beta_z_at_index_285`
- `tests/unit/test_canary_predictors.py` - `test_field_count_increased_by_five` and `test_cold_start_vector_returns_all_canary_fields` 277->282
- `tests/unit/test_feature_factory.py` - `test_all_fields_are_finite_floats` 277->282

## Decisions Made

See `key-decisions` in frontmatter for the full list. Most consequential: `_cold_start_vector` needed a real signature change (new optional `bar_ts` param) because the plan's claim that "bar_ts is available" at cold start was not actually true of the live function -- threaded it through cleanly via a single call site rather than leaving the plan's claim unfulfilled.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Plan's stale field-count baseline (200/205/209) corrected to the live baseline (277/282/291)**
- **Found during:** Task 1, before writing any code (verified live baseline via direct Python check: `len(dataclasses.fields(FeatureVector))` = 277, not the plan's assumed 200)
- **Issue:** The plan's `<interfaces>` section (written 2026-07-24) asserts "After plan 151-04: `len(dataclasses.fields(FeatureVector))` == 200... This plan takes them to 205 / 205 / 214" -- factually false for the live codebase, which already carries 277 fields after 151-01/02/03/04 landed.
- **Fix:** Scaled every arithmetic reference (docstring "Total: N" tally, migration header comments, `feature_registry` row-count math, all hardcoded test assertions across 7 test files, `FEATURE_VECTOR_INSERT_SQL_PSYCOPG` column count) to the live 277->282 baseline instead of the plan's stale 200->205.
- **Files modified:** `src/intelligence/schemas.py`, `production/migrations/290_named_interaction_primitives.sql`, all touched test files, `feature_vector_persistence.py`
- **Verification:** `len(dataclasses.fields(FeatureVector))` -> 282; live `feature_registry` count -> 282 (post-migration); full `tests/unit/` suite green.
- **Committed in:** `148cc32d`, `76f2eb5a`

**2. [Rule 3 - Blocking] Migration number collision with intervening work landed since plan authoring**
- **Found during:** Task 3, before writing the migration file
- **Issue:** The plan's provisional migration number (263) was long taken -- `ls production/migrations/` showed the sequence had advanced through 289 (151-04's own migration in this same phase).
- **Fix:** Used 290 (verified next-free via both `ls` and a live `config_history` query for `changed_by='migration_290'`), updated every internal reference consistently.
- **Files modified:** `production/migrations/290_named_interaction_primitives.sql`, `feature_vector_persistence.py`, test docstrings
- **Verification:** Migration applied cleanly; live queries confirm 282/13/0/3/5/5/10 across every acceptance-criteria check.
- **Committed in:** `76f2eb5a`

**3. [Rule 1 - Bug] `_cold_start_vector` had no `bar_ts` parameter despite the plan claiming "bar_ts is available"**
- **Found during:** Task 2, before wiring `opex_flag`/`quad_witching_flag` into `_cold_start_vector`
- **Issue:** The plan's action text says "Wire both into `compute()`, `compute_batch()`, and `_cold_start_vector()` (compute the real value at cold start — `bar_ts` is available)." The live function signature was `_cold_start_vector(cache: FeatureCache, tf: str) -> FeatureVector` -- no `bar_ts` parameter existed at all.
- **Fix:** Added an optional `bar_ts: datetime | None = None` parameter, threaded from `compute()`'s single call site as `bars[-1]["ts"] if bars else None` (real when exactly one bar is available, `None` in the true zero-bars case). `opex_flag`/`quad_witching_flag` compute real values when `bar_ts is not None`, else fall back to the existing neutral-`0.0` convention.
- **Files modified:** `src/intelligence/feature_factory.py`
- **Verification:** `test_cold_start_vector_returns_all_canary_fields` (unchanged call signature `_cold_start_vector(cache, "5m")`, still valid since `bar_ts` defaults to `None`) passes; full suite green.
- **Committed in:** `148cc32d`

**4. [Rule 3 - Blocking] `scan_binary_patterns.py` flagged the new `opex_flag`/`quad_witching_flag` equality checks as violations**
- **Found during:** Task 2's full-suite run, before the Tasks 1+2 commit
- **Issue:** `tests/unit/intelligence/test_binary_pattern_scanner.py::test_zero_binary_violations` failed: `_quad_witching_flag`'s `_opex_flag(bar_ts) == 1.0` and a schemas.py comment restating the same condition both tripped the `equality_check_continuous_1` pattern (`==\s*1\.0`).
- **Fix:** Added `re.compile(r"opex_flag")` to the scanner's "Day-of-week / calendar" allowlist section -- `opex_flag` is a definitional binary flag (always exactly `1.0`/`0.0`, no accumulated float error), the same class of legitimate exact-equality already carved out for `is_friday`/`bos_detected`/etc. Did not obfuscate the code (e.g. `>= 1.0`) to dodge the regex.
- **Files modified:** `tools/scan_binary_patterns.py`
- **Verification:** `test_zero_binary_violations` passes; scanner still catches 0 violations project-wide.
- **Committed in:** `148cc32d`

---

**Total deviations:** 4 auto-fixed (1 bug fix -- stale baseline, 1 blocking-issue fix -- migration numbering, 1 bug fix -- missing cold-start parameter, 1 blocking-issue fix -- scanner allowlist)
**Impact on plan:** All four were necessary for correctness, for the plan's own stated success criteria (full unit suite green, migration applies cleanly, no numbering collision, `feature_registry` row count matches the dataclass field count), or for the plan's own literal claim about `_cold_start_vector` to actually hold. No scope creep beyond what was required to keep the plan's own deliverable internally consistent against a codebase that grew 77 fields between the plan's authoring (2026-07-24) and this plan's own execution (2026-08-05), plus one tooling allowlist gap discovered mid-execution.

## Issues Encountered

- **Worktree venv missing (pre-existing, documented pattern):** the worktree has no local `.venv` (gitignored, per `feedback_gsd_worktree_venv_missing` memory). Used `/home/bg/dev/indicagent/.venv/bin/python`/`pytest`/`ruff` invoked with the worktree as cwd throughout -- confirmed this resolves `src.*`/`services.*` imports against the worktree's own files, not the main repo's, before relying on it for any verification. The pre-commit hook's `ruff`/`black` checks needed the same venv's `bin/` prepended to `PATH` at commit time (`REPO_ROOT` inside the hook resolves to the worktree root via `git rev-parse --show-toplevel`, which has no local `.venv/bin/ruff`).
- **Session interruption:** an API session-limit error terminated the prior execution turn mid-investigation of Task 3's exact registry column list (before any Task 3 code was written). On resume, `git status`/`git diff` confirmed Tasks 1+2 were already fully implemented, tested green, and about to be committed -- verified rather than re-derived, then committed as planned, and Task 3 proceeded fresh with no rework.

## User Setup Required

None - no external service configuration required. The migration was applied directly to the live DB as part of Task 3 (`PGPASSWORD=postgres psql ... -f production/migrations/290_named_interaction_primitives.sql`).

## Known Stubs

None. All 5 new fields have real compute logic wired into the batch path from day one. The one genuine gap -- the 3 cross-TF divergences are NOT yet computed on the live path -- is not a stub in the silent-wrong-answer sense: `compute()` explicitly passes `None` for all three (matching the class docstring's "None means not measured" convention), and this asymmetry is documented inline at both the field-comment and function-docstring level, mirroring 151-04's own documented live-path gap for the cross-asset fields.

## Threat Flags

None beyond what the plan's own `<threat_model>` already covers (T-151-09 and T-151-10, both mitigated as designed -- the parent_features arity contract is now guarded by both `ops_interaction_primitives_pilot.py`'s existing `ValueError` and this plan's new permanent regression test; `_build_ltf_return_series` is a causal merge-walk with a dedicated causality unit test).

## Next Phase Readiness

- Plan 151-06 (designed interactions) can proceed against the now-282-field `FeatureVector` baseline.
- Plan 151-08's IC screen will produce the first measured verdict on `ret_div_1m_5m`'s ~1% coverage limitation -- flagged in the migration comment and here, not worked around.
- `_PHASE151_INTERACTION_NAMED_FIELD_NAMES` derived-slice pattern and migration 290's `concept_registry`/`concept_gate`/`concept_parent` parity block are direct templates for any subsequent Phase 151 plan's own migration (same Phase 170 parity requirement applies to every wave, now including the `concept_parent` edge-insert block for any future `tier=1_interaction` row).
- No blockers to 151-06/151-08/151-09. Full `tests/unit/` suite green; live DB migration applied and verified (`feature_registry`=282 rows, 13/13 tier=1_interaction rows carry exactly 2 parents, `concept_registry`/`concept_gate`/`concept_parent` parity clean 5/5/10).
- Reminder for the next migration in this phase: re-verify the next-free migration number against BOTH `ls production/migrations/` AND `config_history` before applying -- confirmed necessary again this plan (263->290), same discipline as every prior Phase 151 plan.

## Self-Check: PASSED

- FOUND: `production/migrations/290_named_interaction_primitives.sql`
- FOUND: commit `148cc32d` (Tasks 1+2)
- FOUND: commit `76f2eb5a` (Task 3)
- Verified live: `SELECT count(*) FROM feature_registry` = 282 (matches `FeatureVector` field count)
- Verified live: `SELECT count(*) FROM feature_registry WHERE tier='1_interaction'` = 13, all with `array_length(parent_features,1) = 2`
- Verified live: `concept_registry`/`concept_gate`/`concept_parent` parity = 5/5/10 for this plan's rows
- Verified live: `ops_interaction_primitives_pilot.py._load_interaction_features` returns 13 rows without raising

---
*Phase: 151-feature-primitives-expansion-theory-motivated-interaction-la*
*Completed: 2026-08-05*
