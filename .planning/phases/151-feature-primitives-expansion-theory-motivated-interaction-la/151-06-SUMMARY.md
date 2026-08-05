---
phase: 151-feature-primitives-expansion-theory-motivated-interaction-la
plan: 06
subsystem: feature-factory
tags: [feature-factory, feature-vectors, apr, concept-registry, timescaledb, interaction-primitives, theory-motivated, guard-counted]

# Dependency graph
requires:
  - phase: 151-05
    provides: live FeatureVector baseline (282 fields after wave 5, 13 pre-existing tier=1_interaction rows), the _PHASE151_INTERACTION_NAMED_FIELD_NAMES derived-slice persistence pattern this plan extends, the concept_registry/concept_gate/concept_parent Phase 170 parity template
  - phase: 170-feature-domain-concept-registry-migration
    provides: concept_registry/concept_gate schema + ic_engine.py's PARITY PRECONDITION gate, concept_parent join table (migration 283) for real parent_features edges
provides:
  - 10 new FeatureVector fields (292 total) -- momentum_vol_regime_product, momentum_trend_product, breakout_volume_product, reversion_hurst_product, quarter_momentum_product, variance_ratio_momentum_product, illiquidity_momentum_product, yield_slope_momentum_product, vix_reversion_product, efficiency_volume_product -- each a single product of two tier-0 columns with a stated finance-theory hypothesis
  - migration 291 (10 feature_vectors columns, 10 feature_registry tier=1_interaction rows with hypotheses, concept_registry/concept_gate/concept_parent parity 10/10/20)
  - _guard_counted() / _report_guard_counted_substitutions() -- a COUNTED, observable finite-value tripwire distinct from plain _guard(), used only by these 10 compounds
  - test_interaction_tier_population_within_cap -- permanent live-DB regression guard for ROADMAP's <=50 tier=1_interaction design cap
  - _PHASE151_THEORY_INTERACTION_FIELD_NAMES persistence derived-slice, INSERT contract closed 291->301 columns
affects: [151-08, 151-09]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Counted-guard tripwire (_guard_counted/_report_guard_counted_substitutions) -- a variant of the existing _guard() idiom that increments a named, observable counter on substitution instead of silently collapsing, reported once per compute_batch() call (never per row); new pattern, first use in this file"
    - "Named-local reuse in compute() for values needed by both an original field kwarg and a new compound (mirrors compute_batch()'s pre-existing _val local pattern and Plan 05.5's own precedent) -- 12 of the 13 parent scalars gained a compute()-side named local that did not exist before this plan, replacing inline recompute at each of their original kwarg sites"

key-files:
  created:
    - production/migrations/291_theory_motivated_interactions.sql
  modified:
    - src/intelligence/schemas.py
    - src/intelligence/feature_factory.py
    - src/intelligence/features/feature_vector_persistence.py
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
  - "Live codebase baseline was 282 fields / 282 feature_registry rows / 291 INSERT placeholders at execution time, not the plan's stale 205/205/214 assumption (written 2026-07-24) -- 151-01 through 151-05 landed 77 intervening fields since. Scaled every downstream number (docstring tallies, migration numbering 264->291, test assertions across 8 files) to the live 282->292 / 291->301 baseline, matching every prior Phase 151 plan's own documented correction pattern. The plan's <interfaces> section had already correctly anticipated the 13-row tier=1_interaction baseline (23 after this plan), so only the TOTAL field/column counts needed correcting, not the interaction-tier math."
  - "Migration renumbered 264 (plan's provisional target) -> 291 (actual next-free number, re-verified against both `ls production/migrations/` and a live config_history query for any prior migration_291 row, both immediately before writing the file and again immediately before applying it, given the shared-DB concurrent-session risk)."
  - "The plan's read_first instruction to bind the 10 compounds to 'already-bound local variables at the FeatureVector(...) constructor site in BOTH compute() and compute_batch()' assumed compute() already had named _val locals for all 13 parents, mirroring compute_batch(). Live inspection found this false: compute() computes most fields (including 12 of the 13 parents) as inline kwarg expressions passed directly into _build_feature_vector(), not pre-bound locals -- only volume_z_val (and atr_z_val/ret_skew_z_val/up_vol_ratio_fast_val, not among this plan's 13) were already bound, by Plan 05.5's own precedent of binding a local specifically when it needs to be reused. Resolved by extending that same precedent: added a new named-local block in compute() for all 13 parents (reusing existing series/cache access, zero new computation), then updated each parent's ORIGINAL kwarg site to reference the new local instead of its inline expression -- avoiding duplicate computation and giving compute() the same 'single computation, reused local' discipline compute_batch() already had, rather than literally duplicating computation the way the codebase's single actually-inline precedent (ofi_div, a pre-Plan-05.5-era artifact) does."
  - "The 10 compounds' finite-value guard is applied ONCE, inside _build_feature_vector's shared FeatureVector(...) construction (mirroring where plain _guard() wraps every other of the ~190 other fields), not duplicated at each of compute()/compute_batch()'s two call sites. The raw (unguarded) product is computed at each call site from already-bound locals; _build_feature_vector applies _guard_counted(raw, name) exactly once per compound per row, keeping the counting logic in a single place."
  - "_report_guard_counted_substitutions() is called ONLY from compute_batch() (once per call, after the loop), never from compute() -- preserving compute()'s own docstring purity contract ('zero IO'; this project's convention treats structlog calls as an IO-adjacent side effect worth keeping out of that specific function). compute() still calls the pure, in-memory _guard_counted() itself (not IO), so a live-path substitution (structurally near-unreachable given the tripwire's own reasoning) is still counted in the shared module-level dict and would surface on the next compute_batch() report, never silently lost -- just not reported from compute() itself."
  - "Explicit range clipping rejected at design time (recorded per plan instruction): a float64 product of two z-scores cannot reach +-inf short of ~1e154 per factor -- structurally unreachable for a real z-score -- so math.isfinite firing in _guard_counted is a tripwire against a genuine numerical anomaly, never a value-shaping clamp on an extreme-but-valid number. A clip range would itself be a tunable numeric constant this plan's single-operation design rule forbids."
  - "Open Question 2 (categorical-regime encoding) resolved as implemented: momentum_vol_regime_product uses hv_ratio (volatility EXPANSION/CONTRACTION), momentum_trend_product uses adx (trend strength), reversion_hurst_product uses hurst and variance_ratio_momentum_product uses variance_ratio_fast (persistence/mean-reversion proxies), yield_slope_momentum_product uses yield_slope_z (term-structure regime), vix_reversion_product uses vix_z (market-wide volatility regime) -- all numeric tier-0 FeatureVector columns, never the categorical regime/market_regimes strings."
  - "The near-neighbour redundancy risk the plan explicitly flags (a momentum_z_fast * atr_z product sitting uncomfortably close to the existing ret_vol_ratio_fast=ret_lag_fast/atr_z and ret_vol_product_fast=ret_lag_fast*volume_z) is structurally avoided: no new compound uses atr_z (volatility LEVEL) as a parent -- hv_ratio (volatility EXPANSION/CONTRACTION) is used instead everywhere a volatility-regime proxy is needed, and momentum_z_fast (a z-scored momentum-window return) rather than ret_lag_fast (a raw single-bar lagged return) is the momentum parent throughout."
  - "A pre-existing, unrelated indentation defect in tests/unit/intelligence/test_feature_registry_service.py (4 TestIsPromotionEligible methods silently uncollected as dead nested code inside test_every_interaction_row_has_exactly_two_parents, predating this plan -- confirmed via git diff HEAD) sits directly at the natural insertion point for this plan's own new cap-guard test. Left unfixed (SCOPE BOUNDARY: pre-existing, unrelated to this plan's 10 compounds) and logged to deferred-items.md; the new test was placed at the true, unambiguous module tail instead, so it is not itself swallowed by the same defect."

requirements-completed: []

# Metrics
duration: ~110min
completed: 2026-08-05
---

# Phase 151 Plan 06: Theory-Motivated Interaction Layer Summary

**10 curated theory-motivated compound features (each a single product of two tier-0 columns, each carrying a one-sentence finance-theory hypothesis) live in both the batch and live compute paths via migration 291, guarded by a new COUNTED finite-value tripwire distinct from the codebase's existing silent-fallback `_guard()`, with Phase 170 concept_registry parity and a permanent live-DB cap-guard test.**

## Performance

- **Duration:** ~110 min
- **Completed:** 2026-08-05
- **Tasks:** 3
- **Files modified:** 13 (1 created: migration 291)

## Accomplishments

- `FeatureVector` grew from 282 to 292 fields, declared as one contiguous 10-field block immediately after 151-05's `quad_witching_flag`: `momentum_vol_regime_product`, `momentum_trend_product`, `breakout_volume_product`, `reversion_hurst_product`, `quarter_momentum_product`, `variance_ratio_momentum_product`, `illiquidity_momentum_product`, `yield_slope_momentum_product`, `vix_reversion_product`, `efficiency_volume_product` (all `float`, non-nullable -- every parent always computed, defaulting to 0.0 at cold start, so every product is always defined).
- **Redundancy pre-check** (Task 1, recorded here per-compound): queried all 282 live `feature_registry` rows before writing any code. None of the 10 proposed `feature_name` values collided with an existing row. None duplicates an existing `tier=1_interaction` row's exact parent pair -- the plan's flagged near-neighbour risk (a `momentum_z_fast * atr_z` product sitting close to `ret_vol_ratio_fast`/`ret_vol_product_fast`) is structurally avoided: `hv_ratio` (volatility expansion/contraction) substitutes for `atr_z` (volatility level) everywhere a volatility-regime proxy is needed, and `momentum_z_fast` (z-scored momentum-window return) substitutes for `ret_lag_fast` (raw single-bar lagged return) as the momentum parent throughout. None of the 3 nullable cross-sectional rank fields is used as a parent. All 13 named parents verified live `tier='0_atomic'` and bound as a local at the `_build_feature_vector` constructor call site in both `compute()` and `compute_batch()`.
  - `momentum_vol_regime_product` (momentum_z_fast * hv_ratio): novel, checked against `ret_vol_ratio_fast`/`ret_vol_product_fast` (nearest neighbours by parent-family) -- distinct parent pair.
  - `momentum_trend_product` (momentum_z_fast * adx): novel, no existing row multiplies momentum by trend strength.
  - `breakout_volume_product` (dist_from_high_fast * volume_z): novel, distinct from `vol_body_product`/`range_vol_product`/`ret_vol_product_fast` (all `volume_z` products, but none paired with `dist_from_high_fast`).
  - `reversion_hurst_product` (momentum_reversal_z * hurst): novel, no existing row.
  - `quarter_momentum_product` (quarter_position * momentum_z_fast): novel, distinct from `quarter_cycle_sin/cos` (harmonic encodings, not products).
  - `variance_ratio_momentum_product` (variance_ratio_fast * momentum_z_fast): novel.
  - `illiquidity_momentum_product` (amihud_illiq_z * momentum_z_fast): novel.
  - `yield_slope_momentum_product` (yield_slope_z * momentum_z_fast): novel, macro-conditioned.
  - `vix_reversion_product` (vix_z * momentum_reversal_z): novel, macro-conditioned.
  - `efficiency_volume_product` (efficiency_ratio_fast * volume_z): novel, distinct from the other `volume_z` products above (paired with a different, orthogonal parent).
- **Open Question 2 resolution** (categorical-regime encoding, `151-RESEARCH.md`): implemented via numeric tier-0 proxy substitution -- `hv_ratio` for volatility regime, `adx` for trend strength, `hurst`/`variance_ratio_fast` for persistence/mean-reversion, `vix_z` for market-wide volatility, `yield_slope_z` for term-structure regime. No compound multiplies the categorical `regime`/`market_regimes` strings.
- **Compute wiring**: both `compute()` and `compute_batch()` funnel into `_build_feature_vector`'s single shared `FeatureVector(...)` construction site. `compute_batch()` already had named `_val` locals for all 13 parents; `compute()` did not (12 of 13 were inline kwarg expressions) -- extended compute()'s own Plan-05.5 precedent by binding all 13 as named locals, reusing them both for each parent's original field kwarg (replacing its inline expression, avoiding duplicate computation) and for the 10 new compound calculations.
- **`_guard_counted()`**: a new counted, observable tripwire distinct from the existing `_guard()` -- increments a named, module-level per-compound substitution counter when a product is non-finite, applied ONCE inside `_build_feature_vector`'s constructor (matching the single-application-point discipline every other field's `_guard()` already has). `_report_guard_counted_substitutions()` emits one structured `theory_interaction_guard_substitutions` log line naming only non-zero-count compounds (nothing when all are zero), called exactly once per `compute_batch()` call, then resets. Explicit range clipping deliberately rejected (recorded in migration header + schema docstring): a float64 product of two z-scores cannot reach +-inf short of ~1e154 per factor, so `math.isfinite` firing is a tripwire against a genuine anomaly, never a value-shaping clamp -- and a clip range would itself be a forbidden tunable constant.
- `_cold_start_vector()` returns `0.0` for all 10 (product of two cold-start-zero parents).
- `feature_vector_persistence.py`'s INSERT contract closed: new `_PHASE151_THEORY_INTERACTION_FIELD_NAMES` derived slice, 301 total columns/placeholders (was 291).
- Migration 291 applied to the live DB: 10 `feature_vectors` columns, 10 `feature_registry` rows (`tier='1_interaction'`, `added_phase='151'`, every row with exactly 2 parents and `formula_short` carrying the hypothesis via a `--` delimiter), 10 matching `concept_registry`/`concept_gate` rows, 20 `concept_parent` edges (Phase 170 parity). Zero `config_history` rows for `migration_291` (zero tunables by design).
- `feature_registry` row count verified live: 292, matching `FeatureVector`'s 292 dataclass fields. `tier='1_interaction'` population: 23 of the <=50 cap (13 pre-existing + 10 new), all with exactly 2 parents.
- `test_interaction_tier_population_within_cap` (new permanent live-DB regression test) added, citing ROADMAP's BH-FDR power rationale.
- `ops_interaction_primitives_pilot.py`'s `_load_interaction_features` run directly against the live DB: returns 23 rows without raising the arity `ValueError`.
- Full `tests/unit/` suite green (0 failures beyond one pre-existing, unrelated failure -- see Issues Encountered) after every task's commit; `ruff check`/`black --check` clean on all touched Python.

## Task Commits

Each task was committed atomically:

1. **Tasks 1+2 (combined -- redundancy pre-check + schema/compute + persistence wiring, tightly coupled: 10 contiguous fields, same pattern every prior Phase 151 plan used for its own Tasks 1+2)** - `62485540` (feat)
2. **Task 3: Migration 291, live apply, and permanent cap-guard test** - `d55a9985` (feat)

_No separate plan-metadata commit -- this is a parallel worktree execution; SUMMARY.md is committed by the orchestrator's post-wave merge step per `parallel_execution` instructions._

## Files Created/Modified

- `production/migrations/291_theory_motivated_interactions.sql` (new) - 10 columns, 10 feature_registry rows, 10 concept_registry/concept_gate parity rows, 20 concept_parent edges
- `src/intelligence/schemas.py` - `FeatureVector` +10 fields, docstring tally 282->292
- `src/intelligence/feature_factory.py` - `_guard_counted`/`_report_guard_counted_substitutions` (new tripwire idiom), `FEATURE_VECTOR_DOMAIN` +10 entries, `_build_feature_vector` signature/body +10 params (guarded once), `compute()` gains 13 named parent locals (replacing 12 inline expressions) + 10 compound locals + 10 new kwargs, `compute_batch()` gains 10 compound locals (reusing its pre-existing 13 `_val` locals) + 10 new kwargs + the report call site, `_cold_start_vector` +10 kwargs at `0.0`
- `src/intelligence/features/feature_vector_persistence.py` - `_PHASE151_THEORY_INTERACTION_FIELD_NAMES` slice, INSERT contract closed (291->301 columns)
- `tests/unit/intelligence/test_feature_factory_batch.py` - new `TestTheoryMotivatedInteractionProducts` (live-path + batch-path product-correctness to 1e-12), `TestGuardCountedTripwire` (finite passthrough, non-finite substitution + counter increment across 2 compounds), `TestGuardCountedReport` (one-line report naming only non-zero compounds, silent-when-zero, reset-after-report, end-to-end compute_batch() silence on realistic data)
- `tests/unit/intelligence/test_feature_factory_batch_parity.py` - 2 `_build_feature_vector` direct-call sites extended with the 10 new kwargs
- `tests/unit/intelligence/test_feature_factory_p7.py` - `test_feature_vector_domain_complete` 282->292
- `tests/unit/intelligence/test_feature_registry_service.py` - new `test_interaction_tier_population_within_cap` (placed at module tail, see Deviations)
- `tests/unit/services/test_backfill_feature_factory.py` - `_make_zero_vector` +10 fields, `test_vector_to_params_all_features_present` 291->301
- `tests/unit/services/test_feature_vector_writer.py` - `_make_valid_feature_vector` +10 fields, 3 hardcoded length assertions 291->301
- `tests/unit/services/test_feature_vector_writer_column_mapping.py` - sentinel record +10 fields, `test_params_length_is_159` 291->301, renamed `test_quad_witching_flag_at_index_290_is_last_element` -> `test_quad_witching_flag_at_index_290` (no longer last), new `test_efficiency_volume_product_at_index_300_is_last_element`
- `tests/unit/test_canary_predictors.py` - `test_field_count_increased_by_five` and `test_cold_start_vector_returns_all_canary_fields` 282->292
- `tests/unit/test_feature_factory.py` - `test_all_fields_are_finite_floats` 282->292

## Decisions Made

See `key-decisions` in frontmatter for the full list. Most consequential: the plan's assumption that compute() already had named locals for all 13 parents (mirroring compute_batch()) was false for 12 of them -- resolved by extending Plan 05.5's own "bind once, reuse" precedent into compute(), rather than duplicating computation the way the codebase's one pre-05.5-era inline precedent (`ofi_div`) does. Second most consequential: the guard is applied exactly once, inside `_build_feature_vector`, not at each call site -- keeping the counting logic in a single place matching every other field's single-`_guard()`-application convention.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Plan's stale field-count/column-count baseline (205/205/214) corrected to the live baseline (282/282/291 -> 292/292/301)**
- **Found during:** Task 1, before writing any code (verified live baseline via direct Python check: `len(dataclasses.fields(FeatureVector))` = 282, not the plan's assumed 205)
- **Issue:** The plan's `<interfaces>` section (written 2026-07-24) asserts "This plan takes them to 215 / 215 / 224" -- factually false for the live codebase, which already carries 282/282/291 after 151-01 through 151-05 landed.
- **Fix:** Scaled every arithmetic reference (docstring "Total: N" tally, migration header comments, `feature_registry` row-count math, all hardcoded test assertions across 8 test files) to the live 282->292 / 291->301 baseline instead of the plan's stale 205->215 / 214->224.
- **Files modified:** `src/intelligence/schemas.py`, `production/migrations/291_theory_motivated_interactions.sql`, all 8 touched test files, `feature_vector_persistence.py`
- **Verification:** `len(dataclasses.fields(FeatureVector))` -> 292; live `feature_registry` count -> 292 (post-migration); `FEATURE_VECTOR_INSERT_SQL_PSYCOPG.count('%s')` -> 301; full `tests/unit/` suite green.
- **Committed in:** `62485540`, `d55a9985`

**2. [Rule 3 - Blocking] Migration number collision with intervening work landed since plan authoring**
- **Found during:** Task 3, before writing the migration file
- **Issue:** The plan's provisional migration number (264) was long taken -- `ls production/migrations/` showed the sequence had advanced through 290 (151-05's own migration).
- **Fix:** Used 291 (verified next-free via both `ls` and a live `config_history` query for `changed_by='migration_291'`, re-checked a second time immediately before applying), updated every internal reference consistently.
- **Files modified:** `production/migrations/291_theory_motivated_interactions.sql`, `feature_vector_persistence.py`, test docstrings
- **Verification:** Migration applied cleanly; live queries confirm 292/23/10/10/20 across every acceptance-criteria check.
- **Committed in:** `d55a9985`

**3. [Rule 1 - Bug] `compute()` had no named locals for 12 of the 13 required parents, contradicting the plan's read_first assumption and its literal "already-bound local variables" instruction**
- **Found during:** Task 2, before implementing the 10 compounds (grepped for `<parent>_val =` assignments per the plan's own read_first step)
- **Issue:** The plan's read_first instructs verifying each parent "is bound as a local variable at the FeatureVector(...) constructor site in BOTH compute() and compute_batch()," and cites the precedent `ofi_div_val = ofi_z_val - momentum_z_fast_val` -- but that exact local-binding form only exists in `compute_batch()`; in `compute()`, the equivalent `ofi_div` kwarg is a fully inline expression (`_series_last(s.ofi_z, 0.0) - _series_last(s.momentum_z_fast, 0.0)`), duplicating computation already done for the `ofi_z`/`momentum_z_fast` kwargs on the same call. Of the 13 named parents, only `volume_z_val` already had a compute()-side local (bound by Plan 05.5 specifically because it needed reuse).
- **Fix:** Rather than literally duplicate computation to match `ofi_div`'s older, pre-Plan-05.5 inline style, extended Plan 05.5's own later, cleaner "bind once, reuse" precedent (already used for `volume_z_val`/`atr_z_val`/`ret_skew_z_val`/`up_vol_ratio_fast_val`): added a new named-local block for all 13 parents in `compute()`, then updated each parent's ORIGINAL kwarg site (`momentum_z_fast=`, `adx=`, `hurst=`, `hv_ratio=`, `variance_ratio_fast=`, `efficiency_ratio_fast=`, `dist_from_high_fast=`, `amihud_illiq_z=`, `quarter_position=`, `vix_z=`, `yield_slope_z=`, `momentum_reversal_z=`) to reference the new local instead of recomputing inline.
- **Files modified:** `src/intelligence/feature_factory.py`
- **Verification:** Live/batch parity smoke test confirmed identical output before and after (`momentum_vol_regime_product` matches `momentum_z_fast * hv_ratio` to 1e-12 on both paths); full suite green; `TestTheoryMotivatedInteractionProducts` unit tests pass.
- **Committed in:** `62485540`

**4. [Rule 3 - Blocking] `nan_to_num` literal string in a docstring tripped the plan's own `grep -c "nan_to_num"` == 0 acceptance criterion**
- **Found during:** Task 2's acceptance-criteria self-check, before the Tasks 1+2 commit
- **Issue:** `_guard_counted`'s docstring explained the rejected alternative idiom by name (`np.nan_to_num(..., posinf=0.0, neginf=0.0)`), which itself contains the literal string the acceptance criteria checks is absent from the file.
- **Fix:** Rephrased the docstring to describe the rejected idiom in prose ("a bare numpy clamp call") without using the literal function name.
- **Files modified:** `src/intelligence/feature_factory.py`
- **Verification:** `grep -c "nan_to_num" src/intelligence/feature_factory.py` -> 0; `grep -c "_guard_counted"` -> 20 (>= 11 required).
- **Committed in:** `62485540`

---

**Total deviations:** 4 auto-fixed (1 bug fix -- stale baseline, 1 blocking-issue fix -- migration numbering, 1 bug fix -- missing compute()-side locals contradicting the plan's own read_first claim, 1 blocking-issue fix -- docstring self-reference tripping the plan's own acceptance criterion). All four were necessary for correctness, for the plan's own stated success criteria (full unit suite green, migration applies cleanly, no numbering collision, all acceptance-criteria greps passing exactly as specified), or for the plan's own literal claims to actually hold against the live codebase. No scope creep beyond what was required to keep the plan's own deliverable internally consistent against a codebase that grew since the plan's authoring (2026-07-24) plus one self-referential docstring gap discovered mid-execution.

## Issues Encountered

- **Worktree venv missing (pre-existing, documented pattern):** the worktree has no local `.venv` (gitignored). Used `/home/bg/dev/indicagent/.venv/bin/python`/`pytest`/`ruff`/`black` invoked with the worktree as cwd throughout, and prepended the same `bin/` to `PATH` at commit time for the pre-commit hook's own ruff/black checks.
- **Worktree base drift at spawn time:** the worktree's initial HEAD (506a1d02) was several commits behind the expected wave-5 base (edd6cd48, "after wave 4" tracking commit, which already included 151-09's out-of-numeric-order merge). Reset to edd6cd48 per the `worktree_branch_check` step before any work began -- a legitimate correction, not a destructive operation on concurrent work (verified `git merge-base` showed the worktree's own HEAD was a strict ancestor of the target, i.e. purely behind, not diverged).
- **Pre-existing test suite failure, unrelated to this plan:** `tests/unit/test_migration_number_uniqueness.py::test_no_new_migration_number_collisions` fails on the pre-existing `287_calendar_velocity_atomics.sql`/`287_single_name_equity_expansion.sql` duplicate-prefix collision (tracked separately as todo 260, explicitly called out as "not yours to fix" in this session's orchestrator instructions). Confirmed via direct re-run that this failure is independent of migration 291 (which introduces no new prefix collision -- verified `ls production/migrations/ | sort -t_ -k1 -n | tail` immediately before and after applying). Full suite otherwise green; this one test excluded via `--deselect` for all full-suite verification runs in this plan.
- **Pre-existing, unrelated indentation defect discovered while writing Task 3's cap-guard test:** see key-decisions and `deferred-items.md` for full detail -- 4 `TestIsPromotionEligible` methods in `test_feature_registry_service.py` are silently uncollected as dead nested code (predates this plan). Logged, not fixed (SCOPE BOUNDARY); this plan's own new test placed at the module tail to avoid the same defect.

## User Setup Required

None - no external service configuration required. The migration was applied directly to the live DB as part of Task 3 (`PGPASSWORD=postgres psql ... -f production/migrations/291_theory_motivated_interactions.sql`).

## Known Stubs

None. All 10 new fields have real compute logic wired into both the live and batch paths from day one -- no asymmetry like plan 151-05's cross-TF divergences (those 10 named parents are all in-scope for both `compute()`'s and `compute_batch()`'s existing plumbing; nothing here is gated on a future plan).

## Threat Flags

None beyond what the plan's own `<threat_model>` already covers (T-151-11 and T-151-12, both mitigated as designed -- `test_interaction_tier_population_within_cap` makes the <=50 design rule a machine-enforced invariant, and every new row's `formula_short` carries its hypothesis via the `--` delimiter, verified live: 10/10 rows).

## Next Phase Readiness

- Plan 151-08's IC screen will produce the first measured verdict on all 23 `tier=1_interaction` rows (13 pre-existing + 5 named + 10 theory-motivated), including whether the `_guard_counted` tripwire ever actually fires against the real historical corpus (expected: never, per the design-time "structurally unreachable" argument -- but now observable if it does).
- `FeatureVector` is now at 292 fields / 292 `feature_registry` rows / 301 INSERT placeholders -- any subsequent Phase 151 plan's own migration must re-verify the next-free migration number (292+) against both `ls production/migrations/` and `config_history` before applying, same discipline as every prior plan in this phase.
- The `_guard_counted`/`_report_guard_counted_substitutions` pattern is a direct template for any future plan that needs a counted (not silent) finite-value tripwire on a small, named subset of fields without perturbing the ~190 pre-existing fields' plain `_guard()`.
- No blockers to 151-08/151-09. Full `tests/unit/` suite green (excluding the one pre-existing, unrelated, explicitly-out-of-scope migration-number-collision failure); live DB migration applied and verified (`feature_registry`=292 rows, `tier='1_interaction'`=23 rows all with exactly 2 parents, `concept_registry`/`concept_gate`/`concept_parent` parity clean 10/10/20).

## Self-Check: PASSED

- FOUND: `production/migrations/291_theory_motivated_interactions.sql`
- FOUND: commit `62485540` (Tasks 1+2)
- FOUND: commit `d55a9985` (Task 3)
- Verified live: `SELECT count(*) FROM feature_registry` = 292 (matches `FeatureVector` field count)
- Verified live: `SELECT count(*) FROM feature_registry WHERE tier='1_interaction'` = 23, all with `array_length(parent_features,1) = 2`
- Verified live: `concept_registry`/`concept_gate`/`concept_parent` parity = 10/10/20 for this plan's rows
- Verified live: `SELECT count(*) FROM config_history WHERE changed_by='migration_291'` = 0
- Verified live: `ops_interaction_primitives_pilot.py._load_interaction_features` returns 23 rows without raising
- Verified: `len(dataclasses.fields(FeatureVector))` = 292; `FEATURE_VECTOR_INSERT_SQL_PSYCOPG.count('%s')` = 301
- Verified: `grep -c "_guard_counted" src/intelligence/feature_factory.py` = 20 (>= 11); `grep -c "nan_to_num"` = 0; `grep -c "_PrecomputedSeries"` = 4 (unchanged from pre-task baseline)

---
*Phase: 151-feature-primitives-expansion-theory-motivated-interaction-la*
*Completed: 2026-08-05*
