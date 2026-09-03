---
phase: 173-broadcast-feature-significance-correction-fix-pooled-cross-s
plan: 03
subsystem: alpha (IC engine)
tags: [ic-engine, broadcast-features, cross-sectional, fingerprint-invalidation, concept-registry]

requires:
  - phase: 173-01
    provides: "concept_registry.metadata->>'broadcast' populated (38 broadcast=true rows)"
  - phase: 173-02
    provides: "CONTEXT_FEATURES daily-cadence path deleted, docstring already stated the target design"
provides:
  - "Database-sourced broadcast column split in _compute_one_cross_sectional_cell -- zero rows
    emitted for a broadcast feature by the per-symbol pooled cross-sectional cell"
  - "bar_ts row-aligned with X_raw/returns_mat/complete_mat inside _compute_cross_sectional_tf,
    with a crash-loud alignment guard, ready for Plan 04 to consume"
  - "broadcast_hash watermark component -- a broadcast-flag flip forces full cell recompute,
    not a status-only metadata refresh"
affects: [173-04]

tech-stack:
  added: []
  patterns:
    - "Positional boolean mask derived from a database-sourced name set, intersected against
      _FEATURE_NAMES before storage (T-173-01) -- the safety property of an f-string-interpolated
      SQL column list is preserved by construction, not by trust in the database value."
    - "Separate combined-mask local (cluster_input_mask) instead of mutating the pre-existing
      degenerate_mask/non_degenerate_mask -- keeps two different exclusion reasons (degenerate vs.
      symbol-invariant) from being conflated in n_skipped accounting."
    - "Fingerprint computational-key surgical key-retention: drop status_hash, keep broadcast_hash,
      inside the same legacy-registry-name filter -- lets one sub-key of a watermark component
      participate in computational validity while a sibling sub-key stays excluded."

key-files:
  created: []
  modified:
    - services/ic_engine.py
    - tests/unit/test_ic_engine_compute_split.py
    - tests/unit/test_ic_engine_fingerprint.py

key-decisions:
  - "Rule 1 auto-fix: _fingerprint_computational_key previously dropped the ENTIRE concept_registry
    watermark entry when computing computational validity. Left unfixed, a broadcast-flag flip
    would classify as status_only_stale (a cheap feature_status_at_eval-only refresh, confirmed by
    reading _FEATURE_STATUS_REFRESH_SQL) instead of invalid, silently serving IC values computed
    under the OLD column split forever. Fixed to keep broadcast_hash (still dropping status_hash)
    -- backward-compatible with every existing test fixture, verified live (no fixture carries a
    broadcast_hash key, so the old behavior for status_hash-only fingerprints is unchanged)."
  - "Full round-trip synthetic tests use n_features = len(_FEATURE_NAMES) (298), not a small
    synthetic count -- the row-emission loop iterates enumerate(_FEATURE_NAMES) directly, so a
    smaller synthetic array (as the pre-existing CellTooLargeError test uses) only exercises the
    early-return gate, never reaches row emission. bootstrap_resamples cut to 20 and a single
    active scale keep the full pipeline test under ~50ms."

requirements-completed: [D-01, D-05, D-08]

duration: ~65min
completed: 2026-08-25
---

# Phase 173 Plan 03: Broadcast-Aware Column Split + bar_ts Threading + Fingerprint Invalidation Summary

**Excluded the 38 broadcast features from the per-symbol pooled cross-sectional cell's matrix and
row-emission (the correctness fix itself), threaded bar_ts through the chunked fetch for Plan 04,
and fixed a real fingerprint-invalidation gap that would have silently served stale IC values
under the old column split after any future broadcast reclassification.**

## Performance

- **Duration:** ~65 min (including worktree base correction and full-suite verification)
- **Started:** 2026-08-25T16:49Z (approx, first commit 16:50:00Z)
- **Completed:** 2026-08-25T16:57:02Z
- **Tasks:** 3/3 completed
- **Files modified:** 3 (services/ic_engine.py + 2 test files)

## Accomplishments

- `main()` reads `concept_registry.metadata->>'broadcast'` once per invocation (no `cr.status`
  filter, no `COALESCE` -- locked read/write population alignment with Plan 01), intersects
  against `_FEATURE_NAMES` before storage (T-173-01 mitigation), and threads the resolved
  `frozenset[str]` through `_compute_cross_sectional_tf` as `broadcast_features`
- `_compute_cross_sectional_tf` converts the name set into a positional `broadcast_mask` once per
  cell and passes it to `_compute_one_cross_sectional_cell`
- `_compute_one_cross_sectional_cell` excludes broadcast columns from the clustering matrix
  (`cluster_input_mask = non_degenerate_mask & ~broadcast_mask`, a separate local so `n_skipped`
  never conflates "degenerate" with "symbol-invariant") and skips row-emission entirely for masked
  features -- no NaN row, avoiding a future collision with Plan 04's broadcast-cell row on the
  partial unique index `feature_ic_scores_cross_sectional_uq`
- `bar_ts` is now fetched, accumulated per-chunk as a plain `list[np.ndarray]` (dtype=object,
  never routed through `Float32ChunkAccumulator`), concatenated once after the `X_raw is None`
  early return, and guarded by a crash-loud `RuntimeError` on any length mismatch with `X_raw`
- `_watermark_concept_registry` returns a second key, `broadcast_hash`, computed as a separate
  aggregate in the same round trip; `status_hash`'s md5 input string is byte-for-byte unchanged
  (Phase 170 invariant preserved)
- **Found and fixed a real bug during Task 3's `<action>` verification step**:
  `_fingerprint_computational_key` was dropping the entire `concept_registry` watermark entry
  (both `status_hash` and the newly-added `broadcast_hash`) from computational validity — see
  Deviations below

## Task Commits

Each task was committed atomically:

1. **Task 1: Read the broadcast set from concept_registry and exclude those columns from the
   pooled cross-sectional cell** - `71389aeeb` (feat)
2. **Task 2: Thread bar_ts through the chunked cross-sectional fetch** - `c0b16de8c` (feat)
3. **Task 3: Make a broadcast-flag change invalidate cell fingerprints** - `a59cf5e9b` (fix)

_No separate plan-metadata commit -- this SUMMARY and its self-check are the final commit for
this parallel-worktree plan; STATE.md/ROADMAP.md are updated centrally by the orchestrator after
the wave completes._

## Files Created/Modified

- `services/ic_engine.py` - broadcast-set read in `main()`, `broadcast_mask` threading through
  `_compute_cross_sectional_tf`/`_compute_one_cross_sectional_cell`, `cluster_input_mask` split,
  `bar_ts_chunks` accumulation + alignment guard, `_watermark_concept_registry`'s `broadcast_hash`,
  and the `_fingerprint_computational_key` fix (net +234/-25 lines across all 3 commits)
- `tests/unit/test_ic_engine_compute_split.py` - 12 new tests: full round-trip synthetic tests
  against `_compute_one_cross_sectional_cell` (none/all-False-mask equivalence, broadcast exclusion,
  row-count arithmetic, degenerate-non-broadcast NaN-row survival), 2 source-introspection tests
  for the broadcast-read query's no-status-filter/no-COALESCE contract and the `_FEATURE_NAMES`
  intersection guard, and 2 source-introspection tests for the `bar_ts_chunks` accumulator-free
  pattern and the alignment guard's presence/placement
- `tests/unit/test_ic_engine_fingerprint.py` - 6 new tests: `broadcast_hash` retention in the
  computational key, computational-invalidity on a `broadcast_hash`-only difference, computational-
  validity when only `status_hash` differs (broadcast_hash's addition must not widen what
  status_hash alone used to gate), `_classify_fingerprint` returning `"invalid"` (not
  `"status_only_stale"`) on a `broadcast_hash` mismatch, the fake-cursor-fixture proof that
  `_watermark_concept_registry` returns exactly `{"status_hash", "broadcast_hash"}`, and a
  source-introspection test pinning `status_hash`'s md5 input string unchanged

## Decisions Made

1. **Rule 1 auto-fix: `_fingerprint_computational_key` had to change, contrary to the plan's own
   `<action>` prediction.** Task 3's `<action>` states "No change is needed to `_fingerprint_is_valid`
   or `_classify_fingerprint`: the watermark is compared as a whole JSONB value... Verify that by
   reading the comparison code rather than assuming it, and state the finding in the SUMMARY." Read
   the comparison code as instructed and found the prediction was wrong for
   `_fingerprint_is_computationally_valid` (used by `_classify_fingerprint` to decide invalid vs.
   valid/status_only_stale): `_fingerprint_computational_key` strips the ENTIRE `concept_registry`
   sub-dict (both `status_hash` and, once added, `broadcast_hash`) from the watermark before
   comparing. `_fingerprint_is_valid` (the FULL, unfiltered comparison) does treat the watermark as
   a whole JSONB value as predicted -- but `_classify_fingerprint` calls
   `_fingerprint_is_computationally_valid` FIRST, and only falls through to the full comparison
   (via `_fingerprint_is_status_only_stale`) when that's already True. With the un-fixed code, a
   `broadcast_hash`-only difference would leave `_fingerprint_is_computationally_valid` True (the
   whole `concept_registry` entry is filtered out of the comparison), so `_classify_fingerprint`
   would return `"status_only_stale"` -- triggering only `_FEATURE_STATUS_REFRESH_SQL` (confirmed
   by reading it: `UPDATE feature_ic_scores SET feature_status_at_eval = ...`, touching no IC/CI
   column), never a real recompute. That is exactly "research's Pitfall 1 arriving through the
   metadata door" the plan's own `_watermark_concept_registry` docstring warns about, and a direct
   violation of CLAUDE.md's "silent wrong answers are worse than loud crashes." Fixed
   `_fingerprint_computational_key` to keep `broadcast_hash` (still dropping `status_hash`) inside
   the same legacy-registry-name filter loop. Verified backward-compatible: every one of the 8
   pre-existing tests referencing this function passed unchanged (none of their fixtures carry a
   `broadcast_hash` key, so the filter's behavior for `status_hash`-only fingerprints is identical
   to before). Full `tests/unit/` suite green (zero failures) after the fix.
2. **Full round-trip synthetic tests over source-introspection-only.** The plan's `<action>` for
   Task 1 asks for tests covering the `<behavior>` block "with synthetic numpy fixtures." Built
   these against the REAL `_compute_one_cross_sectional_cell` end-to-end (not a mocked/truncated
   path), using `n_features = len(_FEATURE_NAMES)` (298) rather than a small synthetic feature
   count -- the row-emission loop iterates `enumerate(_FEATURE_NAMES)` directly, so any smaller
   synthetic array only exercises the early-return gate (as the pre-existing
   `test_cell_too_large_error_raised_by_both_cell_functions` does), never reaches row emission.
   Cut `bootstrap_resamples` to 20 and used a single active scale to keep each full-pipeline test
   under ~50ms (measured live).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `_fingerprint_computational_key` silently defeated broadcast-flag invalidation**
- **Found during:** Task 3's `<action>`-mandated verification step ("Verify that by reading the
  comparison code rather than assuming it")
- **Issue:** See Decision 1 above -- `_fingerprint_computational_key` dropped the entire
  `concept_registry` watermark sub-dict, so a `broadcast_hash`-only difference classified as
  `"status_only_stale"` instead of `"invalid"`, meaning a broadcast reclassification would never
  trigger a real recompute.
- **Fix:** Changed the filter to retain `broadcast_hash` (a `dict` comprehension check for the key
  inside the legacy-registry-name branch) while still dropping `status_hash` for the same reason
  documented in the function's pre-existing docstring.
- **Files modified:** `services/ic_engine.py`
- **Verification:** All 8 pre-existing tests exercising this function pass unchanged; 5 new tests
  added covering the fixed behavior directly (`test_fingerprint_computational_key_keeps_broadcast_hash`,
  `test_computationally_invalid_when_only_broadcast_hash_differs`,
  `test_computationally_valid_when_only_status_hash_differs_broadcast_hash_matches`,
  `test_classify_fingerprint_invalid_on_broadcast_hash_mismatch_alone`, plus the fake-cursor
  fixture test for `_watermark_concept_registry`'s return shape). Full `tests/unit/` suite
  (full run) green, zero failures.
- **Committed in:** `a59cf5e9b` (Task 3 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - bug, explicitly surfaced by the plan's own
verification instruction, not scope creep). No other deviations -- Tasks 1 and 2 executed exactly
as specified.

## Known Stubs

None -- `bar_ts_arr` is deliberately unconsumed by this plan (`<action>`'s explicit instruction:
"Do not yet consume `bar_ts_arr` for anything; Plan 04 does that"). This is not a stub; it is
correctly-scoped incomplete wiring that Plan 04 owns per the phase's task split.

## Self-Check: PASSED

- `services/ic_engine.py` - FOUND (modified)
- `tests/unit/test_ic_engine_compute_split.py` - FOUND (modified)
- `tests/unit/test_ic_engine_fingerprint.py` - FOUND (modified)
- Commit `71389aeeb` (Task 1) - FOUND in `git log`
- Commit `c0b16de8c` (Task 2) - FOUND in `git log`
- Commit `a59cf5e9b` (Task 3) - FOUND in `git log`
- `grep -c "broadcast_mask" services/ic_engine.py` = 9 (>= 3 required) - PASS
- `grep -c "metadata->>'broadcast'" services/ic_engine.py` = 1 (exactly 1 required) - PASS
- `grep -c "JOIN concept_gate" services/ic_engine.py` = 4 (>= 2 required) - PASS
- `grep -c "bar_ts_chunks" services/ic_engine.py` = 4 (>= 3 required) - PASS
- `grep -c "np.concatenate(bar_ts_chunks)" services/ic_engine.py` = 1 (exactly 1 required) - PASS
- `grep -c "broadcast_hash" services/ic_engine.py` = 9 (>= 2 required) - PASS
- `git diff --stat services/_batch_utils.py` = empty (D-05 accumulator constraint held) - PASS
- `.venv/bin/python -c "import services.ic_engine"` exits 0 - PASS
- `.venv/bin/pytest tests/unit/ -q` = full suite green, zero failures, 2 skipped (pre-existing, unrelated) - PASS
- `.venv/bin/ruff check services/ic_engine.py tests/unit/test_ic_engine_compute_split.py tests/unit/test_ic_engine_fingerprint.py` = All checks passed - PASS
- `.venv/bin/black --check` on the same 3 files = All done, unchanged - PASS
