---
phase: 162-ic-engine-corpus-pipeline-throughput-incremental-recompute-t
plan: 03
subsystem: database
tags: [ic_engine, fingerprint, apr, timescaledb, watermark, idempotency]

# Dependency graph
requires:
  - phase: 162-01
    provides: "_checkpoint_content_key() (reused verbatim as the fingerprint's code_content_key component); post-structural-extraction shape of ic_engine.py's compute functions"
  - phase: 162-02
    provides: "cross_sectional_bootstrap_threads per-tf dict (final structural state 162-03 fingerprints against)"
provides:
  - "production/migrations/251_ic_cell_fingerprints.sql -- ic_cell_fingerprints table (PK symbol/tf/pass_type/training_window_end)"
  - "services/ic_engine.py::_COMPUTATIONAL_CONFIG_FIELDS / _OPERATIONAL_CONFIG_FIELDS -- crash-loud ICEngineConfig field classification"
  - "services/ic_engine.py::_compute_apr_snapshot_key -- APR-key fingerprint component"
  - "services/ic_engine.py::_compute_upstream_watermark -- per-table upstream watermark (forward_returns.computed_at + content hashes)"
  - "services/ic_engine.py::_fingerprint_is_valid / _symbol_expected_cells -- whole-cell validity check + cell-membership routing"
  - "services/ic_engine.py::main() -- fingerprint gate wired into both per-symbol and cross-sectional dispatch paths, --refresh/--dry-run-validity flags"
affects: [162-04]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Whole-cell fingerprint gate (3-component: code_content_key + apr_snapshot_key + upstream_watermark) as the SOLE skip mechanism, replacing per-feature existing_keys snapshots"
    - "DELETE-then-insert invalidation scoped to the exact cell-key columns, never a bare training_window_end filter"
    - "Synthesized '{regime_group}:{regime_label}' key in a fingerprint table's symbol column to represent a cross-sectional cell's real (finer) grain than feature_ic_scores' own 'POOLED' sentinel"

key-files:
  created:
    - production/migrations/251_ic_cell_fingerprints.sql
    - tests/unit/test_ic_engine_fingerprint.py
  modified:
    - services/ic_engine.py
    - tests/unit/test_ic_engine_checkpoint_key.py
    - tests/unit/test_ic_engine_compute_split.py
    - tests/unit/test_ic_engine_dual_write_symbol_hmm.py

key-decisions:
  - "sign_symmetric classified COMPUTATIONAL per the plan's explicit list, despite live-code verification showing it currently gates only the post-run lifecycle-hook policy layer (ic_engine.py:798's own docstring: 'gates only the downstream eligibility/weighting/lifecycle policy layer') -- kept as a deliberate conservative safety margin against future coupling into the measurement path, not a correction of the plan"
  - "decay_materiality_threshold/guard_*/decay_recovery_*/meta_fdr_min_fraction/ic_staleness_alert_days/ensemble_weight_version classified OPERATIONAL after live-code verification confirmed each is referenced ONLY inside _apply_feature_transitions/_run_lifecycle_hook (post-run policy on feature_registry/ensemble decisions), never inside a feature_ic_scores-writing code path -- resolves the plan's own explicit 'guard_*/decay_* IF they affect the written IC rows' instruction"
  - "Cross-sectional fingerprint rows use a synthesized 'symbol' value ('{regime_group}:{regime_label}') rather than the literal feature_ic_scores.symbol ('POOLED') -- the plan's stated 4-column PK (symbol, tf, pass_type, training_window_end) cannot otherwise distinguish cross-sectional cells, since feature_ic_scores has no regime_group column and multiple (regime_group, regime_label) cells all write symbol='POOLED'"
  - "_compute_upstream_watermark signature extended with an optional symbol_list parameter beyond the plan's literal 4-arg sketch (Rule 2 addition) -- without it, an in-place correction to a cross-sectional cell's PEER symbol (not the cell's own synthesized key) would silently fail to invalidate the cell, exactly the T-162-03-01 stale-serve threat the fingerprint exists to prevent"
  - "All 3 tasks committed as one commit -- the plan's own file list places tests/unit/test_ic_engine_fingerprint.py in all three tasks' <files> (one shared, cumulative test file), and Task 3's wiring imports Task 1/2 symbols directly, so a per-task green-test split would require artificial reconstruction with no real correctness benefit"

requirements-completed: [SC-1, SC-2, SC-3]

# Metrics
duration: ~2h (extensive live-code verification of routing/watermark semantics against post-162-01/162-02 file state, per orchestrator instruction not to trust original pre-refactor line numbers)
completed: 2026-07-23
---

# Phase 162 Plan 03: ic_engine Whole-Cell Fingerprint Gate Summary

**`ic_cell_fingerprints` table (migration 251) plus a 3-component whole-cell fingerprint (code content hash + APR-computational-key + per-table upstream watermark) wired into `main()` as the SOLE skip/recompute decision on both the per-symbol and cross-sectional dispatch paths, replacing the legacy `existing_keys` per-feature snapshot outright and deleting the `.pkl` checkpoint system.**

## Performance

- **Duration:** ~2h (most of it live-code verification: reading post-162-01/162-02 `ic_engine.py` in full to re-derive exact line numbers, field-classification rationale, and cross-sectional cell granularity, per the orchestrator's explicit instruction not to trust the plan's pre-refactor line references)
- **Tasks:** 3/3 completed
- **Files modified:** 6 (4 modified, 2 created)

## Accomplishments

- Migration 251 creates `ic_cell_fingerprints` (plain table, PK `symbol, tf, pass_type, training_window_end`), with a `COMMENT ON TABLE` documenting the synthesized cross-sectional symbol-key convention and the "all three components must match" skip-eligibility rule.
- `_COMPUTATIONAL_CONFIG_FIELDS` / `_OPERATIONAL_CONFIG_FIELDS` classify all 39 `ICEngineConfig` fields (20 computational, 19 operational) with one-line rationale comments each; `test_computational_and_operational_fields_partition_dataclass_exactly` fails loudly if a future field is left unclassified.
- `_compute_apr_snapshot_key` hashes only COMPUTATIONAL fields (sorted, dict-serialization-order-independent) via `BaseBatch.content_key()`.
- `_compute_upstream_watermark` resolves RESEARCH Open Question #1: `forward_returns.MAX(computed_at)` (the primary in-place-mutation detector) plus content hashes for `market_regimes`/`instrument_tags`/`feature_registry` -- a naive `MAX(bar_ts)/COUNT(*)` alone is blind to a price-sanity correction or HMM relabel that touches zero rows/timestamps.
- `_fingerprint_is_valid` (all-3-components-match, partial match is a full miss) + `_symbol_expected_cells` (mirrors `main()`'s own routing logic for pooled/symbol_hmm/cross_sectional/dual-write pass-type membership) drive the gate.
- `main()` computes the fingerprint partition for every candidate symbol AND every `(regime_group, tf, regime_label)` cross-sectional cell BEFORE building `worker_args` or calling `_compute_cross_sectional_tf` -- a fully-valid symbol/cell is never dispatched (fetch+compute skipped, not just the insert). Only cells found invalid are `DELETE`-then-recomputed, scoped to the exact cell key.
- `existing_keys` parameter and all 4 inner skip sites (`_compute_one_regime_cell`, the daily context-features loop in `_compute_symbol_tf`, `_compute_one_cross_sectional_cell`, the whole-regime `issubset` short-circuit in `_compute_cross_sectional_tf`) removed outright -- proven via `inspect.signature`/`inspect.getsource` regression tests that no compute function can ever receive a stale pre-delete snapshot.
- `--refresh` (bypass fingerprint, force recompute) and `--dry-run-validity` (log skip/compute partition counts, exit before any fetch/compute/write) CLI flags added.
- `.pkl` checkpoint system (`_checkpoint_dir`, `_load_checkpoint`, `_save_checkpoint`) deleted outright, closing todo 122's APR-drift surface; `_checkpoint_content_key` kept, reused as the fingerprint's `code_content_key`.

## Task Commits

All 3 tasks landed in one commit (see Decisions Made / key-decisions for why a per-task split wasn't meaningful here):

1. **Tasks 1-3: ic_cell_fingerprints table + field classification + watermark + validity wiring + existing_keys/.pkl removal** - `34bc82e9` (feat)

## Files Created/Modified

- `production/migrations/251_ic_cell_fingerprints.sql` - `ic_cell_fingerprints` table, plain (not hypertable), idempotent `CREATE TABLE IF NOT EXISTS`
- `services/ic_engine.py` - field classification frozensets + `_compute_apr_snapshot_key`; `_compute_upstream_watermark`; `_fingerprint_is_valid` + `_FINGERPRINT_INVALIDATE_DELETE_SQL`/`_FINGERPRINT_INVALIDATE_DELETE_CROSS_SECTIONAL_SQL`/`_FINGERPRINT_UPSERT_SQL` + `_symbol_expected_cells`; `_upsert_cell_fingerprints`; `existing_keys` removed from `_compute_one_regime_cell`/`_compute_symbol_tf`/`_compute_one_cross_sectional_cell`/`_compute_cross_sectional_tf`/`_run_ic_worker`; `.pkl` checkpoint system deleted; `main()` rewritten (fingerprint pre-pass, DELETE-then-dispatch, fingerprint UPSERT after each symbol/cell write, `--refresh`/`--dry-run-validity`); `pickle` import removed (no longer used)
- `tests/unit/test_ic_engine_fingerprint.py` - new, 30 tests covering all 3 tasks: classification partition/disjointness, apr_snapshot_key computational-vs-operational sensitivity, watermark in-place-mutation inequality (DB-free dict construction), `_fingerprint_is_valid` component-match semantics, DELETE SQL cell-key scoping, `_symbol_expected_cells` routing correctness (unrouted/disabled/routed/dual-write), and the `existing_keys`-removal signature/getsource regression
- `tests/unit/test_ic_engine_checkpoint_key.py` - `_checkpoint_dir` import + its one test removed (function deleted); `_checkpoint_content_key`'s own tests untouched
- `tests/unit/test_ic_engine_compute_split.py` - `existing_keys` removed from the `_compute_symbol_tf` expected-params list and from two `CellTooLargeError` test call sites
- `tests/unit/test_ic_engine_dual_write_symbol_hmm.py` - `existing_keys=frozenset()` removed from 2 structural tests; `test_existing_keys_dedup_skips_cell` (tested the now-removed per-feature dedup mechanism) replaced with `test_compute_one_regime_cell_always_recomputes_every_feature` (proves the inverse: identical inputs always produce the identical full row set, no in-function suppression)

## Decisions Made

- **`sign_symmetric` classified COMPUTATIONAL despite live-code evidence it's currently lifecycle-hook-only** -- `ic_engine.py:798`'s own docstring states `alpha.ensemble.sign_symmetric` "gates only the downstream eligibility/weighting/lifecycle policy layer," and a full grep confirmed the only 2 non-docstring reads are inside `_apply_feature_transitions`/`_run_lifecycle_hook`. The plan's example list placed `sign_symmetric` in COMPUTATIONAL without an "IF it affects written rows" qualifier (unlike the adjacent `guard_*/decay_*` fields, which the plan explicitly hedged). Kept COMPUTATIONAL as the conservative direction: misclassifying it OPERATIONAL risks silent staleness if it's ever coupled into the measurement path later; misclassifying it COMPUTATIONAL costs at most one unnecessary-but-safe recompute per change. Documented with a one-line rationale comment at the classification site.
- **The `guard_*`/`decay_*`/`meta_fdr_min_fraction`/`ic_staleness_alert_days`/`ensemble_weight_version` fields classified OPERATIONAL** -- same grep-verification method, applied per the plan's own explicit instruction to check "IF they affect the written IC rows." All confirmed lifecycle-hook-only or pure-observability, never touching a `feature_ic_scores` row.
- **Cross-sectional fingerprint cell identity synthesized as `'{regime_group}:{regime_label}'`** -- `feature_ic_scores` has no `regime_group` column (confirmed via `_compute_cross_sectional_tf`'s own docstring: "regime_group is NOT persisted on the result row... group identity stays implicit in regime_label string uniqueness"), and every cross-sectional row's `symbol` is the literal `'POOLED'` sentinel regardless of which `(regime_group, regime_label)` produced it. Reusing `'POOLED'` literally in `ic_cell_fingerprints.symbol` for `pass_type='cross_sectional'` would collapse every cell for a `tf` into one fingerprint row. The synthesized key fits the plan's stated 4-column PK without adding a 5th column, and is documented in the migration's `COMMENT ON TABLE`.
- **`_compute_upstream_watermark` given an additional `symbol_list` parameter (Rule 2)** -- the plan's literal signature sketch was `(conn, symbol, tf, pass_type, regime_group)`, 4 positional args with no way to represent a cross-sectional cell's peer-symbol set for the `forward_returns`/`feature_vectors` components. Without `symbol_list`, an in-place correction to any PEER symbol's data would silently fail to invalidate the cross-sectional cell -- exactly T-162-03-01, the phase's own highest-severity threat register entry. Added as a keyword-only optional parameter, defaulting to `None` (no functional change for the pooled/symbol_hmm call sites, which never pass it).
- **DELETE SQL split into two constants** (`_FINGERPRINT_INVALIDATE_DELETE_SQL` for pooled/symbol_hmm, `_FINGERPRINT_INVALIDATE_DELETE_CROSS_SECTIONAL_SQL` for cross-sectional) -- pooled/symbol_hmm cells scope correctly on `symbol/tf/regime_scope/training_window_end` alone (a `symbol_hmm` cell's rows span multiple regime labels, all belonging to the same fingerprinted cell), but a cross-sectional cell's fingerprint grain is finer than `feature_ic_scores.symbol='POOLED'` alone can express, requiring an additional `regime=%(regime_label)s` predicate to avoid deleting a sibling regime_label's valid rows.
- **DELETE scoped only to cells actually found invalid, never the whole dispatched symbol** -- per T-162-03-06's explicit mitigation text: a fingerprint-valid sibling cell within a partially-invalid symbol is NOT deleted (its harmless recompute hits `ON CONFLICT DO NOTHING`); deleting it unnecessarily would create a narrow crash-window where its rows are transiently MISSING between the DELETE and the recompute-write.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed 2 pre-existing test files broken by this plan's own required `existing_keys` removal**
- **Found during:** Task 3 (running the plan's own `<verification>` command against `tests/unit/`)
- **Issue:** `tests/unit/test_ic_engine_compute_split.py` (`test_compute_symbol_tf_return_keys` hardcoded `existing_keys` in the expected-params list; 2 `CellTooLargeError` call sites passed `existing_keys=set()`) and `tests/unit/test_ic_engine_dual_write_symbol_hmm.py` (2 structural tests passed `existing_keys=frozenset()`; `test_existing_keys_dedup_skips_cell` directly tested the per-feature dedup mechanism this plan's Task 3 explicitly requires removing) both asserted against the pre-162-03 signature/behavior, as a direct, intended consequence of Task 3's own instructions.
- **Fix:** Removed the `existing_keys` kwarg from all affected call sites; replaced `test_existing_keys_dedup_skips_cell` with `test_compute_one_regime_cell_always_recomputes_every_feature`, which proves the inverse invariant (no per-feature suppression happens inside the function anymore -- the whole-cell gate in `main()` is the sole skip decision).
- **Files modified:** `tests/unit/test_ic_engine_compute_split.py`, `tests/unit/test_ic_engine_dual_write_symbol_hmm.py`
- **Verification:** `.venv/bin/pytest tests/unit/test_ic_engine_compute_split.py tests/unit/test_ic_engine_dual_write_symbol_hmm.py -q` -- all pass.
- **Committed in:** `34bc82e9`

**2. [Rule 1 - Bug] Fixed `tests/unit/test_ic_engine_checkpoint_key.py`'s `_checkpoint_dir` import broken by the required `.pkl` checkpoint deletion**
- **Found during:** Task 3 (full `tests/unit/` collection failed with `ImportError: cannot import name '_checkpoint_dir'`)
- **Issue:** The plan's own Task 3 instructions require deleting `_checkpoint_dir`/`_load_checkpoint`/`_save_checkpoint` outright; this pre-existing test file imported and tested `_checkpoint_dir` directly.
- **Fix:** Removed the `_checkpoint_dir` import and its one dedicated test (`test_checkpoint_dir_embeds_content_key`); `_checkpoint_content_key`'s own tests (kept per the plan) are untouched.
- **Files modified:** `tests/unit/test_ic_engine_checkpoint_key.py`
- **Verification:** `.venv/bin/pytest tests/unit/test_ic_engine_checkpoint_key.py -q` -- 3/3 pass.
- **Committed in:** `34bc82e9`

**3. [Rule 2 - Missing Critical] Extended `_compute_upstream_watermark` with a `symbol_list` parameter**
- **Found during:** Task 2 (writing the cross-sectional watermark path)
- **Issue:** The plan's literal 4-arg signature sketch has no way to scope the `forward_returns`/`feature_vectors` components to a cross-sectional cell's peer-symbol set, meaning an in-place correction to any peer symbol would silently fail to invalidate the cell -- exactly T-162-03-01, the phase's own highest-severity threat.
- **Fix:** Added `symbol_list: list[str] | None = None` as a keyword-only optional parameter; cross-sectional calls pass the group's peer symbols, pooled/symbol_hmm calls (the majority) are unaffected (parameter unused, defaults to `None`).
- **Files modified:** `services/ic_engine.py`
- **Verification:** `test_watermark_differs_on_forward_returns_computed_at_change_alone` and siblings in `test_ic_engine_fingerprint.py` prove the underlying watermark-inequality invariant DB-free; live-corpus verification of the cross-sectional peer-symbol scoping itself is deferred to Plan 04's equivalence harness (real DB), matching the phase's own documented split.
- **Committed in:** `34bc82e9`

---

**Total deviations:** 3 auto-fixed (2 test-currency/bug, 1 missing-critical)
**Impact on plan:** All three are necessary corollaries of executing the plan as written, not scope creep. #1/#2 are required maintenance for tests whose target code the plan's own instructions moved/deleted. #3 closes a real gap against the plan's own stated threat model (T-162-03-01) that the literal signature sketch left unaddressed.

## Issues Encountered

**Worktree base was stale at spawn time** -- this worktree's branch had diverged from the expected base commit (`f72342301f91f38ba3ce2302ba84153c8de1c852`, the post-162-02-merge commit this plan depends on). Per the mandatory `worktree_branch_check` step, ran `git reset --hard f72342301f91f38ba3ce2302ba84153c8de1c852` to align (sanctioned, not a self-recovery on a protected branch -- HEAD was and remained on `worktree-agent-a1fcdecb372517cee` throughout). Same pattern as 162-02's own session.

**No `.venv` in this worktree** (documented project gotcha, same as 162-01/162-02): symlinked `<worktree>/.venv -> /home/bg/dev/indicagent/.venv` to resolve the pre-commit hook's ruff/black tool discovery. Filesystem-only, not a tracked change (`.venv` is gitignored).

**Extensive live-code re-derivation required** -- the orchestrator's note correctly warned that the plan's pre-162-01/162-02 line numbers and some of its illustrative examples (e.g. the cross-sectional cell-identity assumption, the `sign_symmetric`/`guard_*` classification examples) didn't fully match the post-refactor file state or the actual runtime behavior. Resolved by reading the live functions in full (`_compute_symbol_tf`, `_compute_one_regime_cell`, `_compute_cross_sectional_tf`, `_compute_one_cross_sectional_cell`, `main()`) before writing any fingerprint-gate code, rather than trusting the plan's `<interfaces>` section's line-number references verbatim.

## User Setup Required

None - no external service configuration required.

## Known Limitations / Follow-ups

- **Live-DB equivalence check (SC-1/SC-2/SC-3's empirical proof) not run in this environment.** The plan's own `<verification>` section states this explicitly: "Empirical skip/invalidate equivalence is proven in Plan 04's harness (real DB) -- NOT here." This worktree sandbox has no live TimescaleDB connection. What WAS verified: the full DB-free `tests/unit/` suite (including all 30 new `test_ic_engine_fingerprint.py` tests) is green; the field-classification partition/disjointness tests prove the crash-loud requirement; the watermark-inequality tests prove the in-place-mutation detection logic via directly-constructed dicts (not a live query, since no DB is available here).
- **Cross-sectional `symbol_list`-scoped watermark component's live behavior is unverified against a real `instrument_tags`/`market_regimes` corpus** in this sandbox -- the SQL was written and reviewed against the live schema (confirmed via direct grep of `_compute_cross_sectional_tf`'s own queries), but the actual query execution/hash-stability under real data is Plan 04's equivalence harness's job.
- **`n_watermark_queries` cost at full-corpus scale** (~80 symbols x up to 3 pass_types x 4 tfs, plus cross-sectional cells) was not benchmarked here -- each is a cheap COUNT/MAX aggregate (not a data fetch), but the actual wall-time cost of the pre-pass itself (before any fetch+compute is even skipped) is an ops-level measurement for whoever runs the next real corpus pass, same category as 162-02's own deferred benchmark validation.

## Next Phase Readiness

- **162-04 (equivalence harness)** is the direct next step and the natural home for: (a) the live-corpus fingerprint skip/invalidate equivalence proof this plan's `<verification>` section explicitly defers to it, (b) a fresh-compute-vs-fingerprint-skip comparison against a real training_window_end, and (c) benchmarking the fingerprint pre-pass's own wall-time cost at full-corpus scale.
- No blockers. Full `tests/unit/` suite green (only 3 pre-existing, unrelated skips, unchanged from 162-01/162-02's baseline).

---
*Phase: 162-ic-engine-corpus-pipeline-throughput-incremental-recompute-t*
*Plan: 03*
*Completed: 2026-07-23*

## Self-Check: PASSED

All 6 created/modified files confirmed present on disk. Commit hash `34bc82e9`
confirmed present in `git log`. `_COMPUTATIONAL_CONFIG_FIELDS`/
`_OPERATIONAL_CONFIG_FIELDS`/`_compute_apr_snapshot_key`/`_fingerprint_is_valid`
confirmed defined in `services/ic_engine.py` via grep. Migration 251's PK
confirmed `(symbol, tf, pass_type, training_window_end)` via grep. 30 tests
confirmed in `tests/unit/test_ic_engine_fingerprint.py`. Full `tests/unit/`
suite green (only 3 pre-existing, unrelated skips). No missing items.
