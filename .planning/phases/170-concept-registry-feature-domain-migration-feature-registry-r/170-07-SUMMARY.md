---
phase: 170-concept-registry-feature-domain-migration-feature-registry-r
plan: 07
subsystem: database
tags: [postgresql, psycopg, asyncpg, concept_registry, feature_registry, ic_engine, ensemble_ablation, ic_shrinkage, broadcast_audit, vocabulary_drift, lifecycle-governance]

requires:
  - phase: 170-06
    provides: "ic_engine/ensemble_trainer's writer-side cutover to concept_registry (domain='feature') plus the registry_dual_write_verified shadow-mode evidence, and the concept_gate-scoped tombstone-exclusion counting convention this plan's queries reuse"
provides:
  - "Every remaining read-only feature_registry consumer (canary integrity, ensemble ablation, IC shrinkage, broadcast-feature audit, lookahead-horizon diagnostic, interaction-primitives pilot, vocabulary drift audit) now reads concept_registry (domain='feature') instead, with BEFORE/AFTER result-set equality demonstrated per query"
  - "The lineage reorder forced by concept_parent's lack of an ordinality column is backed by an executed invariance test (tests/unit/test_interaction_primitives_parent_order.py), not just a plan-doc trace"
  - "A concept_registry-native operator lifecycle actuator (ops_concept_registry_override.py) replacing the retired feature_registry actuator, with a --domain flag and a fixed transaction-commit bug found live during verification"
  - "Zero test modules assert against feature_registry any more (rewired to concept_registry equivalents), so Plan 08's DROP cannot break test collection"
affects: [170-08]

tech-stack:
  added: []
  patterns:
    - "concept_gate INNER JOIN as the standard tombstone-exclusion idiom for any raw-SQL concept_registry(domain='feature') read that does its own row-count-sensitive aggregation (SELECT DISTINCT / plain SELECT into a Python dict) -- reused from Plan 06's ic_engine.py precedent in ic_shrinkage.py, broadcast_feature_audit.py, ops_lookahead_horizon_response.py, and the row-count integration test. Filters that already narrow on a non-NULL discriminating column (is_control=true, group_name IS NOT NULL, metadata->>'tier'='1_interaction') exclude the 2 gate-less tombstones naturally and need no extra join."
    - "psycopg3 conn.transaction() as a NESTED savepoint, not an outer commit, whenever a prior cursor.execute() on the same autocommit=False connection already opened an implicit transaction -- any short-lived CLI actuator that reads-then-writes on one connection needs an explicit conn.commit() after the write; ConceptRegistryService.record_transition_sync's own conn.transaction() cannot supply that by itself unless it happens to be the very first statement on a fresh connection."

key-files:
  created:
    - tests/unit/test_interaction_primitives_parent_order.py
    - tests/unit/scripts/test_ops_concept_registry_override.py  # renamed from test_ops_feature_registry_override.py
  modified:
    - scripts/ops/alpha/ops_canary_integrity_assert.py
    - scripts/ops/alpha/ops_ensemble_ablation.py
    - scripts/ops/alpha/ops_ic_shrinkage.py
    - scripts/ops/alpha/ops_broadcast_feature_audit.py
    - scripts/ops/alpha/ops_lookahead_horizon_response.py
    - scripts/ops/alpha/ops_interaction_primitives_pilot.py
    - scripts/ops/alpha/ops_concept_registry_override.py  # renamed from ops_feature_registry_override.py
    - src/config/vocabulary_drift.py
    - tests/integration/test_feature_vectors_schema.py
    - tests/unit/intelligence/test_swing_fib_trend_structure_primitives.py
    - tests/unit/test_ic_shrinkage_step.py
    - src/intelligence/feature_factory.py
    - src/intelligence/schemas.py
    - src/intelligence/statistics/ic_math.py
    - src/observability/metrics.py
    - scripts/ops/corpus/ops_corpus_pipeline_run.sh
    - scripts/analysis/ops_primitive_discovery_report.py
    - tests/unit/scripts/test_ops_ic_null_calibration_feature_filter.py

key-decisions:
  - "The lineage reorder (feature_registry.parent_features' insertion order -> concept_parent's alphabetical array_agg) is accepted as proven-inert per the plan's own 5-point trace, now backed by two executed tests (partial_spearman_ic and _compute_not_null_mask invariance under a parent swap) rather than left as an assertion -- live-verified against the 8 real interaction primitives: 6 of 8 pairs already sort alphabetically, 2 reorder, matching the plan's prediction exactly."
  - "concept_gate INNER JOIN added to ic_shrinkage.py, broadcast_feature_audit.py, ops_lookahead_horizon_response.py, and the feature_vectors_schema row-count test, beyond what the plan's literal SQL specified -- the plan's own literal `WHERE domain = 'feature'` (no join) queries return 251 rows (249 real + migration 284's 2 gate-less tombstones), never matching feature_registry's 249, which would have permanently broken the BEFORE/AFTER equality this plan's own acceptance criteria demand. Matches Plan 06's own established convention and its explicit 'Next Phase Readiness' warning to reuse it."
  - "feature_factory.py's group_name commentary needed more than a name substitution: concept_registry.group_name is deliberately UNCONSTRAINED TEXT (migration 283 L-10), unlike feature_registry's 11-value CHECK -- a blind find/replace would have asserted a now-false constraint claim, so the comment was rewritten to state the current (unconstrained) reality."
  - "The operator actuator's transaction-commit bug (see Deviations) is fixed with an explicit conn.commit() in main(), not by changing ConceptRegistryService.record_transition_sync's own conn.transaction() usage -- that method is correctly designed for ic_engine's multi-statement, single-final-commit call pattern (Plan 06); the actuator's single-shot CLI shape is the caller-side context that needs the extra commit, not a defect in the shared service."

patterns-established:
  - "Any new read-only script or test that aggregates/counts concept_registry(domain='feature') rows must INNER JOIN concept_gate unless its own WHERE clause already excludes rows with NULL group_name/metadata keys (the 2 tombstones carry neither) -- otherwise it will silently diverge from feature_registry's row count by exactly 2."

requirements-completed: [S-3, L-10]

duration: ~25min active (3 commits, 19:28-19:49 local)
completed: 2026-08-04
---

# Phase 170 Plan 07: feature_registry Reader Repoint + Operator Actuator Replacement Summary

**Eight scripts/modules and four test files repointed from `feature_registry` to `concept_registry` (domain='feature'), with per-query BEFORE/AFTER result-set equality proven live, a new executed test settling the lineage parent-order question, a concept-native operator actuator replacing the retired one, and a real transaction-commit bug found and fixed in that actuator during its own verification step.**

## Performance

- **Duration:** ~25 min active execution across 3 tasks (commits at 19:28, 19:38, 19:49 local, 2026-08-04)
- **Tasks:** 3/3 complete
- **Files modified:** 18 (2 created, 16 modified — 2 of the 16 are git-renamed files)

## Accomplishments

- **Task 1** repointed the four identity/family readers — `ops_canary_integrity_assert.py`, `ops_ensemble_ablation.py`, `ops_ic_shrinkage.py`, `ops_broadcast_feature_audit.py` — from `feature_registry` to `concept_registry(domain='feature')`, with a live BEFORE/AFTER psql comparison per query (all four byte-identical after the concept_gate-join fix described below).
- **Task 2** repointed the status/tier/lineage readers (`ops_lookahead_horizon_response.py`, `ops_interaction_primitives_pilot.py`, `src/config/vocabulary_drift.py`), added the executed lineage-invariance test, and replaced the operator actuator (`ops_feature_registry_override.py` → `ops_concept_registry_override.py`, git mv + full rewrite against `ConceptRegistryService`).
- **Task 3** repointed the three named test modules and swept six comment-only files, plus two Rule-3 fixes for test breakage the Task 2 rename directly caused.
- **Found and fixed 3 real bugs** during this plan's own mandated verification steps (see Deviations): a tombstone-row row-count divergence affecting 4 files (repeat of Plan 06's already-documented finding, now applied consistently), a missing-argparse safety gap in `ops_ic_shrinkage.py` that let `--help` silently execute the live compute-and-write pass, and a transaction-commit bug in the operator actuator that silently discarded every write.

## Task Commits

Each task was committed atomically:

1. **Task 1: Repoint the four identity/family readers** - `9bd1a5c4` (feat)
2. **Task 2: Repoint status/tier/lineage readers, prove the parent reorder inert, replace the operator actuator** - `a5c54003` (feat)
3. **Task 3: Repoint the three test modules and sweep comment-only references** - `fb638e86` (test)

## Files Created/Modified

- `scripts/ops/alpha/ops_canary_integrity_assert.py` - `_CANARY_ROWS_SQL` joins `concept_registry` on `name`/`domain='feature'`; docstring updated.
- `scripts/ops/alpha/ops_ensemble_ablation.py` - `_WEIGHTS_SQL` joins `concept_registry`; `_FAMILIES_SQL` adds a `group_name IS NOT NULL` guard (new, necessary: the column is nullable for `domain='ensemble_strategy'` rows and the 2 tombstones).
- `scripts/ops/alpha/ops_ic_shrinkage.py` - `_FEATURE_GROUP_SQL` aliases `name AS feature_name` (byte-identical downstream dict key) plus an `INNER JOIN concept_gate` to exclude the 2 tombstones; added a minimal `argparse.ArgumentParser` (`_parse_args()`) so `--help`/an unrecognized flag exits before any DB connection opens — this script previously had none at all.
- `scripts/ops/alpha/ops_broadcast_feature_audit.py` - `_FEATURE_REGISTRY_SQL` → `_CONCEPT_REGISTRY_SQL`, same `concept_gate` join fix, docstring/report-text updates.
- `scripts/ops/alpha/ops_lookahead_horizon_response.py` - `_FEATURE_REGISTRY_SQL` → `_CONCEPT_REGISTRY_SQL` with the same `concept_gate` join (belt-and-suspenders here; the 2 tombstones aren't in `_FEATURE_NAMES`), docstring/`--help` text updated.
- `scripts/ops/alpha/ops_interaction_primitives_pilot.py` - `_load_interaction_features` reads `concept_registry`/`concept_parent` via `array_agg(p.name ORDER BY p.name)` instead of `feature_registry.parent_features`; the exactly-2-parents `ValueError` guard preserved verbatim with an updated message; new comment points at the parent-order test as evidence.
- `scripts/ops/alpha/ops_concept_registry_override.py` (renamed from `ops_feature_registry_override.py`, `git mv`) - rewritten against `ConceptRegistryService.record_transition_sync`; new `--domain` flag (default `'feature'`); same four behaviors (not-found/noop/lock-miss/applied) with renamed structlog events; **added an explicit `conn.commit()` after a successful apply** (see Deviations).
- `src/config/vocabulary_drift.py` - `_UNWINDOWED_NAMESPACE_QUERIES["tier"]` → `SELECT DISTINCT metadata->>'tier' FROM concept_registry WHERE domain = 'feature' AND metadata ? 'tier'`; live-verified identical 3-value result to the old query.
- `tests/unit/test_interaction_primitives_parent_order.py` (new) - `test_partial_ic_invariant_under_parent_swap` and `test_not_null_mask_invariant_under_parent_swap`, both passing.
- `tests/integration/test_feature_vectors_schema.py` - renamed `test_feature_registry_row_count_matches_gate` → `test_concept_registry_feature_row_count_matches_gate`; replaced the `_REGISTRY_ROW_COUNT` import with a locally-derived `len(dataclasses.fields(FeatureVector))`; count query joins `concept_gate`.
- `tests/unit/intelligence/test_swing_fib_trend_structure_primitives.py` - `added_phase='165'` cross-check repointed to `concept_registry(domain='feature')`; still asserts 41 rows.
- `tests/unit/test_ic_shrinkage_step.py` - docstring naming update only.
- `src/intelligence/feature_factory.py`, `src/intelligence/schemas.py`, `src/intelligence/statistics/ic_math.py`, `src/observability/metrics.py` (description string only, metric name unchanged), `scripts/ops/corpus/ops_corpus_pipeline_run.sh`, `scripts/analysis/ops_primitive_discovery_report.py` - comment-only sweep.
- `tests/unit/scripts/test_ops_concept_registry_override.py` (renamed, `git mv`, from `test_ops_feature_registry_override.py`) - rewritten against `ConceptRegistryService`; added a default-domain test and a `conn.commit()`-called assertion covering the transaction-commit fix. **Not named in the plan** — Rule 3 fix, see Deviations.
- `tests/unit/scripts/test_ops_ic_null_calibration_feature_filter.py` - fixed a stale cross-reference to the pre-rename filename. **Not named in the plan** — Rule 3 fix, see Deviations.

## Decisions Made

See `key-decisions` in frontmatter. Summary: the lineage parent-order question is settled by two executed invariance tests, not just the plan's trace; `concept_gate` INNER JOIN is applied to every raw-SQL `concept_registry(domain='feature')` read whose own WHERE clause doesn't already exclude the 2 gate-less tombstones by a non-NULL discriminant; `feature_factory.py`'s constrained-vocabulary comment was rewritten (not just renamed) because the underlying fact changed; the operator actuator's missing commit is fixed at the CLI call site, not inside the shared `ConceptRegistryService`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Four literal-plan queries would have returned 251 rows instead of 249, breaking their own BEFORE/AFTER equality acceptance criteria**
- **Found during:** Task 1 (ic_shrinkage, broadcast_feature_audit) and Task 2/3 (ops_lookahead_horizon_response, the feature_vectors_schema row-count test), while running the plan's own mandated BEFORE/AFTER psql comparison
- **Issue:** Migration 284 seeded 2 gate-less "tombstone" `concept_registry` rows (`new_high_flag`/`new_low_flag`, preserved only for orphaned `feature_transition_log` history). Any plain `WHERE domain = 'feature'` read with no other discriminating filter returns 251 rows (249 real + 2 tombstones), never matching `feature_registry`'s 249 — this is the exact same divergence Plan 06 already found and fixed for `ic_engine.py`, and its SUMMARY explicitly warned Plan 07/08 to reuse the same `concept_gate`-scoped counting convention.
- **Fix:** Added `INNER JOIN concept_gate cg ON cg.concept_id = cr.concept_id` to `ops_ic_shrinkage.py`'s `_FEATURE_GROUP_SQL`, `ops_broadcast_feature_audit.py`'s `_CONCEPT_REGISTRY_SQL`, `ops_lookahead_horizon_response.py`'s `_CONCEPT_REGISTRY_SQL`, and `test_feature_vectors_schema.py`'s row-count query — matching `services/ic_engine.py`'s `_watermark_concept_registry` and `ConceptRegistryService`'s own `_LOAD_CONCEPTS_SYNC_SQL`. (Task 1's canary/families/weights queries and Task 2's vocabulary-drift/interaction-pilot queries did NOT need this fix — their own WHERE clauses (`is_control=true`, `group_name IS NOT NULL`, `metadata ? 'tier'`, `metadata->>'tier'='1_interaction'`) already exclude the tombstones naturally, since neither carries a group_name, control flag, or tier key.)
- **Files modified:** `scripts/ops/alpha/ops_ic_shrinkage.py`, `scripts/ops/alpha/ops_broadcast_feature_audit.py`, `scripts/ops/alpha/ops_lookahead_horizon_response.py`, `tests/integration/test_feature_vectors_schema.py`.
- **Verification:** Live psql BEFORE/AFTER md5 comparison for all four, all byte-identical after the fix (recorded below). `test_concept_registry_feature_row_count_matches_gate` passes.
- **Committed in:** `9bd1a5c4` (Task 1), `a5c54003`/`fb638e86` (Task 2/3).

**2. [Rule 2 - Missing Critical] `ops_ic_shrinkage.py` had no argument parsing at all — `--help` silently ran the live compute-and-write pass**
- **Found during:** Task 1, running the plan's mandated `--help` exit-0 acceptance check
- **Issue:** The script's `main()` took no arguments and had no `argparse.ArgumentParser`. Running `--help` (as the plan's own acceptance criteria requires) did not print usage — it silently fell through into the real DB-connecting compute-and-write pass (E1 shrinkage compute + the out-of-fold gate that can flip `alpha.ensemble.ic_input` in `config_state`). Caught this live: the backgrounded `--help` invocation was still running 13+ seconds later, holding a DB connection and fetching multi-million-row tables.
- **Fix:** Killed the runaway process immediately (`kill -9`); confirmed via `config_history` that no `alpha.ensemble.ic_input` write landed from the killed run (most recent entry predates this session). Added a minimal `_parse_args()`/`ArgumentParser` (no real flags, matching the module docstring's documented zero-argument usage) so `--help` or any unrecognized flag now exits before any DB connection opens.
- **Files modified:** `scripts/ops/alpha/ops_ic_shrinkage.py`.
- **Verification:** `timeout 10 .venv/bin/python scripts/ops/alpha/ops_ic_shrinkage.py --help` exits 0 with a usage message, in well under a second, no DB connection attempted.
- **Committed in:** `9bd1a5c4`.

**3. [Rule 1 - Bug] The operator actuator's transaction never committed — every transition it applied would have silently never landed**
- **Found during:** Task 2, running the plan's mandated end-to-end dry-run verification against `indicagent_test`
- **Issue:** `main()` reads the concept's current status via a plain `cursor.execute()` SELECT before calling `ConceptRegistryService.record_transition_sync`. On an `autocommit=False` connection, that SELECT already opens the connection's implicit transaction; `record_transition_sync`'s own `with conn.transaction():` then runs as a NESTED savepoint (not the outer transaction) and only releases the savepoint on success — it never commits the connection itself. `main()`'s `finally: conn.close()` then implicitly rolls back the whole uncommitted transaction. First dry run against `indicagent_test` logged `applied`/exit 0, but a follow-up query showed the feature's status unchanged and no new `concept_transition_log` row. Reproduced with a minimal standalone psycopg3 script to confirm the exact mechanism (SELECT-then-`conn.transaction()`-then-close loses the write; `conn.transaction()` as the sole/first statement on a connection commits correctly). Checked production `feature_transition_log` for historical evidence: the only 2 `operator_override` rows there are dated 2026-07-09, ten days before the (now-renamed) actuator script was created (2026-07-19) — they predate it and don't contradict this finding.
- **Fix:** Added an explicit `conn.commit()` in `main()` immediately after a successful `record_transition_sync()` call, before the "applied" log line.
- **Files modified:** `scripts/ops/alpha/ops_concept_registry_override.py`, `tests/unit/scripts/test_ops_concept_registry_override.py` (new `conn.commit.assert_called_once()`/`assert_not_called()` coverage).
- **Verification:** Re-ran the fixed script against `indicagent_test`: transition persisted (`status` changed to `deprecated`), `concept_transition_log` row landed with the correct `from_status`/`to_status`/`reason`/`notes`. Confirmed production `indicagent` database completely untouched throughout (`feature_registry.status`/`concept_registry.status` both re-checked as unchanged). Not-found path re-verified (exit 1, no commit).
- **Committed in:** `a5c54003`.

**4. [Rule 3 - Blocking] Task 2's script rename broke an existing unit test's import entirely**
- **Found during:** Task 3, the repo-wide `feature_registry` sweep
- **Issue:** `tests/unit/scripts/test_ops_feature_registry_override.py` (not named anywhere in the plan) directly imports `from scripts.ops.alpha.ops_feature_registry_override import main` — a module Task 2 renamed away. This would fail at collection with an `ImportError`.
- **Fix:** `git mv` to `test_ops_concept_registry_override.py`; rewrote all patch targets against `ConceptRegistryService`/the new module path; added a default-`--domain` test and `conn.commit()` coverage for Deviation 3's fix.
- **Files modified:** `tests/unit/scripts/test_ops_concept_registry_override.py` (renamed).
- **Verification:** All 5 tests pass.
- **Committed in:** `fb638e86`.

**5. [Rule 1 - Bug, minor] Stale filename cross-reference from the Task 2 rename**
- **Found during:** Task 3, the repo-wide sweep
- **Issue:** `tests/unit/scripts/test_ops_ic_null_calibration_feature_filter.py`'s docstring named `test_ops_feature_registry_override.py` as a pattern-mirroring example — now a nonexistent filename after Deviation 4's rename.
- **Fix:** Updated the docstring to name the new filename.
- **Files modified:** `tests/unit/scripts/test_ops_ic_null_calibration_feature_filter.py`.
- **Verification:** Test still passes (comment-only change).
- **Committed in:** `fb638e86`.

**6. [Rule 1 - Bug, prose accuracy] `feature_factory.py`'s comment sweep required more than a literal name substitution**
- **Found during:** Task 3, the comment sweep
- **Issue:** The plan's Task 3 instructs "Each should say `concept_registry (domain='feature')` where it currently says `feature_registry`" for six named files. `feature_factory.py`'s specific comment (line ~302) asserted `feature_registry`'s group_name is "CHECK-constrained" — true of the retiring table, but `concept_registry.group_name` is deliberately UNCONSTRAINED TEXT (migration 283 L-10, by explicit design). A literal find/replace would have shipped a now-false claim.
- **Fix:** Rewrote the comment to state the current (unconstrained) reality and explain why, rather than swap only the table name.
- **Files modified:** `src/intelligence/feature_factory.py`.
- **Verification:** Comment reviewed against migration 283's own header text for accuracy.
- **Committed in:** `fb638e86`.

**7. [Rule 4-adjacent, resolved by inspection, not a fix] The final repo-wide sweep returns 12 files, not the plan's literal 3**
- **Found during:** Task 3, the mandated final verification (`grep -rl "feature_registry" --include=*.py --include=*.sh src/ services/ scripts/ tests/`)
- **Issue:** The plan's acceptance criteria states this grep "returns EXACTLY" 3 paths (`feature_registry_service.py`, `test_feature_registry_service.py`, `services/ic_engine.py`). After all three tasks' edits, it returns 12: those 3 plus 9 more — `src/intelligence/concept_registry_service.py`, `tests/unit/test_ic_engine_fingerprint.py`, `tests/unit/test_ic_engine_lifecycle_hook.py`, `tests/unit/services/test_ic_engine.py`, `tests/unit/services/test_ensemble_trainer_alignment_gate.py`, `tests/integration/test_concept_registry_sync_lifecycle.py`, `tests/integration/test_concept_parent_lineage.py`, `tests/integration/test_migration_schema_sync.py`, `scripts/ops/alpha/ops_concept_feature_migration_verify.py`.
- **Resolution (not a code change):** Confirmed via `git diff --stat` against this plan's base commit that none of these 9 files were touched by any of this plan's three tasks — they are pre-existing Plan 06 artifacts (or, for the parity-verify script, an intentionally dual-table-reading script) that already contained "feature_registry" text before this plan started, and none is named anywhere in Plan 07's task list. Spot-checked each for legitimacy rather than assuming: `ops_concept_feature_migration_verify.py` literally must query both `feature_registry` and `concept_registry` to compare them — that comparison IS its purpose, until Plan 08 drops the old table; `test_ic_engine_fingerprint.py` intentionally uses the literal string `"feature_registry"` as fixture data proving Plan 06's dual-key watermark-safety net drops BOTH the old and new key names; the remaining files are prose/docstring references to the retiring module or table by name in test coverage-mapping comments, none of them broken or stale. Per the deviation rules' scope boundary ("only auto-fix issues DIRECTLY caused by the current task's changes... pre-existing warnings in unrelated files are out of scope"), these were left untouched rather than edited beyond the plan's actual task list.
- **Files modified:** None (investigation only).
- **Committed in:** N/A — documented here as the plan's stated acceptance criterion could not be satisfied literally without touching files outside this plan's declared scope.

---

**Total deviations:** 7 (3 correctness bugs found via the plan's own mandated verification steps — tombstone row-count divergence, a missing-argparse safety gap, and a real transaction-commit bug; 2 Rule 3 blocking fixes directly caused by Task 2's rename; 1 prose-accuracy correction; 1 documented scope-boundary explanation for the final grep's file count)
**Impact on plan:** All code changes were necessary for correctness, safety, or to keep the test suite collectible after Task 2's rename — none represent scope creep beyond what those specific changes required. The tombstone-join and transaction-commit findings are exactly the kind of thing this plan's own BEFORE/AFTER and end-to-end dry-run verification steps exist to catch, and did.

## BEFORE/AFTER Query Comparisons (Task 1, recorded per plan requirement)

All four comparisons below used live `psql` against the `indicagent` database; BEFORE = the literal `feature_registry` query, AFTER = the repointed `concept_registry` query, compared via `md5sum` on identically-formatted CSV output.

**(a) `ops_canary_integrity_assert.py` — `_CANARY_ROWS_SQL`:**
```sql
-- BEFORE
SELECT s.feature_name, s.symbol, s.tf, s.regime, s.is_pooled, s.ic_ci_lower, s.ic_ci_upper,
       s.passes_fdr, s.cumulative_e_value, r.control_expectation
FROM feature_ic_scores s JOIN feature_registry r ON r.feature_name = s.feature_name
WHERE r.is_control = true AND s.training_window_end = (SELECT MAX(training_window_end) FROM feature_ic_scores);
-- AFTER
SELECT s.feature_name, s.symbol, s.tf, s.regime, s.is_pooled, s.ic_ci_lower, s.ic_ci_upper,
       s.passes_fdr, s.cumulative_e_value, r.control_expectation
FROM feature_ic_scores s JOIN concept_registry r ON r.name = s.feature_name AND r.domain = 'feature'
WHERE r.is_control = true AND s.training_window_end = (SELECT MAX(training_window_end) FROM feature_ic_scores);
```
Result: 58,715 rows both sides, md5 `b941d83f4938afcebea11402e451c7dc` == `b941d83f4938afcebea11402e451c7dc`. IDENTICAL. (No `concept_gate` join needed — `is_control = true` naturally excludes the tombstones, which default `is_control = false`.)

**(b) `ops_ensemble_ablation.py` — `_FAMILIES_SQL` and `_WEIGHTS_SQL`:**
```sql
-- _FAMILIES_SQL BEFORE/AFTER
SELECT DISTINCT group_name FROM feature_registry ORDER BY group_name;
SELECT DISTINCT group_name FROM concept_registry WHERE domain = 'feature' AND group_name IS NOT NULL ORDER BY group_name;
-- _WEIGHTS_SQL BEFORE/AFTER (sample: weight_version='run_2025122405150000', tf='15m', regime='high_bear')
SELECT ew.feature_name, ew.weight, ew.ic_sharpe, freg.group_name FROM ensemble_weights ew
  JOIN feature_registry freg ON freg.feature_name = ew.feature_name
  WHERE ew.weight_version = 'run_2025122405150000' AND ew.symbol = 'UNIVERSE' AND ew.tf = '15m' AND ew.regime = 'high_bear' ORDER BY ew.feature_name;
SELECT ew.feature_name, ew.weight, ew.ic_sharpe, freg.group_name FROM ensemble_weights ew
  JOIN concept_registry freg ON freg.name = ew.feature_name AND freg.domain = 'feature'
  WHERE ew.weight_version = 'run_2025122405150000' AND ew.symbol = 'UNIVERSE' AND ew.tf = '15m' AND ew.regime = 'high_bear' ORDER BY ew.feature_name;
```
`_FAMILIES_SQL`: 11 rows both sides, md5 `168ce895c6956089fe0a77c27de23ff1` == `168ce895c6956089fe0a77c27de23ff1`. IDENTICAL (`group_name IS NOT NULL` naturally excludes the tombstones).
`_WEIGHTS_SQL`: 13 rows both sides, md5 `ab82144e162c25f82f582341784a6f39` == `ab82144e162c25f82f582341784a6f39`. IDENTICAL.

**(c) `ops_ic_shrinkage.py` — `_FEATURE_GROUP_SQL`:**
```sql
-- BEFORE
SELECT feature_name, group_name FROM feature_registry ORDER BY feature_name;
-- AFTER (literal plan SQL, no join) -- DIVERGED: 251 rows vs 249, md5 mismatch
SELECT name AS feature_name, group_name FROM concept_registry WHERE domain = 'feature' ORDER BY name;
-- AFTER (fixed, with concept_gate join)
SELECT cr.name AS feature_name, cr.group_name FROM concept_registry cr
  JOIN concept_gate cg ON cg.concept_id = cr.concept_id WHERE cr.domain = 'feature' ORDER BY cr.name;
```
BEFORE: 249 rows, md5 `f3ebfe825d53ff6b72f37cd62e601c6f`. Literal-plan AFTER: 251 rows, md5 `974553a8efe6fcd227c9b68d94614ead` — MISMATCH (2 extra rows: `new_high_flag`, `new_low_flag`). Fixed AFTER (with `concept_gate` join): 249 rows, md5 `f3ebfe825d53ff6b72f37cd62e601c6f` == `f3ebfe825d53ff6b72f37cd62e601c6f`. IDENTICAL.

**(d) `ops_broadcast_feature_audit.py` — `_FEATURE_REGISTRY_SQL`:**
```sql
-- BEFORE
SELECT feature_name, group_name, status FROM feature_registry ORDER BY feature_name;
-- AFTER (fixed, with concept_gate join)
SELECT cr.name AS feature_name, cr.group_name, cr.status FROM concept_registry cr
  JOIN concept_gate cg ON cg.concept_id = cr.concept_id WHERE cr.domain = 'feature' ORDER BY cr.name;
```
BEFORE: 249 rows, md5 `2bef1387c63e1381d1c9658be9e56661`. Fixed AFTER: 249 rows, md5 `2bef1387c63e1381d1c9658be9e56661` == `2bef1387c63e1381d1c9658be9e56661`. IDENTICAL.

**Vocabulary tier query (Task 2d):**
```sql
SELECT DISTINCT tier FROM feature_registry ORDER BY tier;                                          -- BEFORE: 0_atomic, 1_interaction, 2_theory
SELECT DISTINCT metadata->>'tier' FROM concept_registry WHERE domain='feature' AND metadata ? 'tier' ORDER BY 1;  -- AFTER: 0_atomic, 1_interaction, 2_theory
```
Both return exactly the same 3 values. IDENTICAL.

**Lineage query (Task 2b) — parent order divergence, expected and proven inert:**
```sql
SELECT feature_name, parent_features FROM feature_registry WHERE tier = '1_interaction' AND status = 'active' ORDER BY feature_name;
SELECT c.name AS feature_name, array_agg(p.name ORDER BY p.name) AS parent_features
  FROM concept_registry c JOIN concept_parent cp ON cp.child_concept_id = c.concept_id
  JOIN concept_registry p ON p.concept_id = cp.parent_concept_id
  WHERE c.domain = 'feature' AND c.metadata->>'tier' = '1_interaction' AND c.status = 'active'
  GROUP BY c.name ORDER BY c.name;
```
Both return the same 8 feature names with the same 2 parents each; 6 of 8 pairs are already alphabetical (byte-identical), 2 (`ret_vol_ratio_fast`, `up_vol_body_diff`) reorder alphabetically — exactly the plan-predicted, now test-proven-inert divergence.

## Actuator Transcript (Task 2e, run against `indicagent_test`, production untouched)

```
$ DATABASE_URL=postgresql://postgres:postgres@localhost:5432/indicagent_test \
    .venv/bin/python scripts/ops/alpha/ops_concept_registry_override.py \
    --domain feature --feature-name totally_bogus_feature_xyz --to-status deprecated --reason "test: not-found path"
2026-08-04 19:34:01 [error] ops_concept_registry_override.not_found domain=feature feature_name=totally_bogus_feature_xyz
exit: 1

$ DATABASE_URL=postgresql://postgres:postgres@localhost:5432/indicagent_test \
    .venv/bin/python scripts/ops/alpha/ops_concept_registry_override.py \
    --domain feature --feature-name nearest_hvn_above_dist_atr --to-status deprecated \
    --reason "test: Phase 170 Plan 07 actuator dry run (post-commit-fix)"
2026-08-04 19:37:14 [info] concept_registry.transition_recorded_sync domain=feature from_status=active name=nearest_hvn_above_dist_atr reason=operator_override to_status=deprecated
2026-08-04 19:37:14 [info] ops_concept_registry_override.applied domain=feature feature_name=nearest_hvn_above_dist_atr from_status=active operator_reason='test: Phase 170 Plan 07 actuator dry run (post-commit-fix)' to_status=deprecated
exit: 0
```
Post-run verification (indicagent_test): `concept_registry.status = 'deprecated'` (was `active`); `concept_transition_log` row landed with `trigger_reason='operator_override'`, correct `from_status`/`to_status`/`notes`. Production `indicagent` database re-checked after both runs: `feature_registry.status` and `concept_registry.status` for `nearest_hvn_above_dist_atr` both still `active` — completely untouched.

## Issues Encountered

An early `ops_ic_shrinkage.py --help` invocation (before the argparse fix) silently ran the script's real compute-and-write pass in the background; caught within ~15 seconds via `ps aux` and killed with `kill -9` before it reached its DB-write phase (confirmed via `config_history` — no new `alpha.ensemble.ic_input` entry from this session). See Deviation 2.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Every read-only consumer of `feature_registry` now reads `concept_registry` (domain='feature'), with the sole remaining reference set (12 files, not the plan's literal 3 — see Deviation 7) confirmed to be pre-existing, legitimate, and out of this plan's scope.
- `feature_registry_service.py`, `test_feature_registry_service.py`, and `ic_engine.py`'s retained dual-write import/calls are the only in-scope survivors — exactly Plan 08's expected DROP-gate targets.
- The operator actuator's transaction-commit bug is fixed and covered by a regression test; this same bug pattern (read-then-write-no-final-commit on a psycopg3 `autocommit=False` connection) is worth checking in any other short-lived CLI actuator built the same way.
- `ops_concept_feature_migration_verify.py` still reports `VERDICT: PASS` (11/11 checks) against live `indicagent` after all of this plan's edits.
- `.venv/bin/pytest tests/unit/ -q` fully green; `tests/integration/test_feature_vectors_schema.py -m integration -q` passes; full-repo `ruff check .`/`black --check .` clean.

---
*Phase: 170-concept-registry-feature-domain-migration-feature-registry-r*
*Completed: 2026-08-04*

## Self-Check: PASSED

- FOUND: tests/unit/test_interaction_primitives_parent_order.py
- FOUND: tests/unit/scripts/test_ops_concept_registry_override.py
- FOUND: scripts/ops/alpha/ops_concept_registry_override.py
- FOUND: 9bd1a5c4 (Task 1 commit)
- FOUND: a5c54003 (Task 2 commit)
- FOUND: fb638e86 (Task 3 commit)
