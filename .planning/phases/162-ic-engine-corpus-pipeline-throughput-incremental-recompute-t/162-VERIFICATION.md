---
phase: 162-ic-engine-corpus-pipeline-throughput-incremental-recompute-t
verified: 2026-07-23T00:00:00Z
status: human_needed
score: 7/7 must-haves verified (mechanism-level); 3 items need a full-corpus live run for final empirical confirmation
overrides_applied: 0
human_verification:
  - test: "Run a full 80-symbol corpus no-op re-run (all cells fingerprint-valid) end to end and measure wall clock"
    expected: "Completes in minutes, not 25-30 hours (SC-1's stated bar)"
    why_human: "162-04's live-DB proof measured a 5-symbol/1-tf subset only (93.9s forced-fresh vs 3.0s skip, ~31x). The skip-before-worker_args mechanism is proven correct at that scale; extrapolation to 80 symbols x 4 tfs is architecturally sound (skip is O(1) per cell, not O(cell size)) but was explicitly deferred to 'whoever runs the next real corpus pass' by both 162-03's and 162-04's own SUMMARYs -- not re-derived at full scale in this verification."
  - test: "Perturb 1 symbol's upstream data (e.g. bump one bar's price_sanity_status) in a live corpus and re-run; confirm only that symbol's cells recompute, wall clock <4h"
    expected: "SC-2's surgical-invalidation bar met at real corpus scale"
    why_human: "Unit-tested (DELETE SQL scoped to exact cell key, not a bare training_window_end filter) and architecturally guaranteed by the whole-cell fingerprint gate, but no live run actually perturbed one symbol and measured the blast radius/wall clock against the full 80-symbol corpus."
  - test: "Benchmark 15m/1h/1d cross-sectional cells at cross_sectional_bootstrap_threads=1 vs the pre-162-02 scalar default against the post-162-01 loop"
    expected: "SC-5's '~10% of measured serial wall time' bar, 5m keeps its threading speedup"
    why_human: "Explicitly flagged as a resource-contention-gated ops measurement not run in either 162-02's or any later plan's sandbox (`ps aux | grep ic_engine` must be clear); informs seed tuning but doesn't gate any unit test. Seeds (5m=6, 15m/1h/1d=1) are in production but unvalidated against a live wall-clock comparison."
---

# Phase 162: ic_engine Corpus Pipeline Throughput / Incremental Recompute Verification Report

**Phase Goal:** A re-run of the 80-symbol corpus whose inputs haven't changed completes in
minutes, not 25-30 hours. Every compute cell carries a persisted fingerprint (code content-key
+ APR snapshot + upstream data watermarks) written alongside its `feature_ic_scores` rows; the
compute loop skips fingerprint-valid cells and recomputes exactly the invalidated subset, with a
mismatch replacing (not silently discarding via `ON CONFLICT DO NOTHING`) stale rows.

**Verified:** 2026-07-23
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (mapped to ROADMAP SC-1..SC-7)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| SC-7 | Structural-pass equivalence: post-refactor bit-identical output, `build_walk_forward_folds` extracted+tested, connection leak fixed | VERIFIED | `short_lived_conn(dsn)` in `services/_batch_utils.py:41` used at all 3 worker dsn sites; `build_walk_forward_folds` in `src/intelligence/statistics/ic_math.py:540`, replacing 4 inline copies; `test_ic_math_walk_forward_folds.py` + `test_batch_utils_short_lived_conn.py` pass; `test_subsample_and_rank_feature_blocked_matches_unblocked` proves bit-identical feature-blocked-vs-unblocked output on a synthetic array |
| SC-6 | Peak transient memory no longer scales with n_features; oversized cell fails loudly | VERIFIED | `CellTooLargeError` class (`services/ic_engine.py:225`), raised when `n_rows > config.max_cell_rows` (line 806-809), re-raised through `_run_ic_worker` (not swallowed, line 3477); `alpha.ic.max_cell_rows`/`alpha.ic.feature_block_columns` seeded via migration 249 and confirmed live in `config_state` (1200000 / 32); feature-axis-only chunking confirmed in `_subsample_and_rank`; `test_cell_too_large_error_raised_by_both_cell_functions` passes. Live multi-GB synthetic-oversized-cell memory run itself was not executed in this verification (matches both plan's own "closing manual gate, not a unit test" framing) — not treated as a gap since the crash-loud code path and its test coverage are the phase's actual deliverable, not a benchmark |
| SC-5 | 15m/1h/1d cross-sectional cells serial, ~10% of measured wall time; 5m keeps threading | VERIFIED (mechanism) / HUMAN NEEDED (benchmark) | Migration 250 live in DB (`5m=6, 15m=1h=1d=1`); `ICEngineConfig.cross_sectional_bootstrap_threads` is a per-tf dict assembled in `from_apr()`; call site indexes `[tf]` (`test_cross_sectional_cell_indexes_bootstrap_threads_by_tf`); per-symbol path never references the dict (`test_per_symbol_cell_never_indexes_cross_sectional_bootstrap_threads`). Wall-clock ~10% bar itself unmeasured — see Human Verification |
| SC-1 | No-op re-run: 100% cells skipped, wall clock <30min vs 25-30h (80-symbol corpus) | VERIFIED (mechanism) / HUMAN NEEDED (full-corpus timing) | Fingerprint gate computed and checked BEFORE `worker_args` construction and before each cross-sectional cell call (`main()`, lines ~4340-4420); live-DB run (162-04) measured 3.0s skip vs 93.9s forced-fresh on a 5-symbol/1-tf subset with `n_symbols_skip=5, n_symbols_compute=0` confirmed in `ic_engine.log` — proves the skip-before-fetch mechanism works, not the 80-symbol/4-tf wall clock itself |
| SC-2 | Perturbing 1 symbol invalidates/recomputes only that symbol's cells, <4h | VERIFIED (mechanism) / HUMAN NEEDED (full-corpus blast-radius+timing) | `_FINGERPRINT_INVALIDATE_DELETE_SQL` scoped to exact `(symbol, tf, pass_type via regime, training_window_end)` cell key, never a bare `training_window_end` filter (`test_invalidate_delete_sql_scoped_to_full_cell_key`, `test_invalidate_delete_sql_is_not_a_bare_training_window_end_filter`); a fingerprint-valid sibling cell is never touched. Live single-symbol-perturbation run against the full corpus was not executed |
| SC-3 | Computational APR key change invalidates all dependents; operational key change invalidates zero; unclassified field crashes loud; mid-run APR drift closes todo 122 | VERIFIED | All 39 `ICEngineConfig` fields partitioned into `_COMPUTATIONAL_CONFIG_FIELDS`/`_OPERATIONAL_CONFIG_FIELDS`, disjoint and exhaustive (`test_computational_and_operational_fields_partition_dataclass_exactly`, `..._are_disjoint` — both pass, and the partition test fails loud on a missing field by construction); `test_apr_snapshot_key_moves_on_computational_field_change` / `..._unchanged_by_operational_field_change` pass; `.pkl` checkpoint system (`_checkpoint_dir`/`_load_checkpoint`/`_save_checkpoint`) deleted outright (grep confirms zero remaining references except explanatory comments), closing todo 122's APR-drift surface |
| SC-4 | Skip-path `feature_ic_scores` content identical to forced `--refresh`, incl. `bh_adjusted_p`/`passes_fdr` | VERIFIED | Empirically proven live in 162-04: 5890 rows byte-identical between run A (`--refresh`) and run B (fingerprint-skip), including post-backfill `bh_adjusted_p`/`passes_fdr`; `computed_at` unchanged on run B confirming zero rows were touched (not just coincidentally-identical recompute). `scripts/ops/corpus/ops_ic_fingerprint_equivalence.py` implements the two-signal diff (value divergence vs. skip-did-not-occur) and a resource-contention + production-data-corruption pre-flight guard |
| CR-01 fix | Per-symbol cross-sectional fingerprint watermark previously silently scoped to `None` instead of `[symbol]` for every regime-group-routed symbol | VERIFIED FIXED | `_compute_upstream_watermark` now takes an explicit keyword-only `is_group_pooled: bool = False` parameter (`services/ic_engine.py:956`); the per-symbol pre-pass call site (line 4346-4354) does NOT pass it, defaulting to `False`, so `symbols_for_fr_fv` now resolves to `[symbol]` regardless of `pass_type` string; only the true group-pooled `cs_cell_plan` call site (line 4404-4415) passes `is_group_pooled=True` explicitly. Confirmed only 2 call sites of `_compute_upstream_watermark` exist in the file (no other caller left unfixed). 2 new regression tests (`test_compute_upstream_watermark_per_symbol_cross_sectional_scopes_to_own_symbol`, `..._group_pooled_scopes_to_regime_group_and_peer_symbols`) pass. `ic_cell_fingerprints` confirmed empty (0 rows) in the live production DB — no data remediation was needed, consistent with the fix commit's own claim |

**Score:** 7/7 mechanism-level truths VERIFIED. 3 (SC-1, SC-2, SC-5) have their empirical full-corpus wall-clock component still outstanding — routed to Human Verification below, not treated as FAILED, since (a) the underlying mechanism for each is independently proven correct via live-DB run or unit test, (b) all three plans' own SUMMARYs explicitly and consistently flag the full-corpus benchmark as deferred ops-level work rather than a phase-execution gate, and (c) CLAUDE.md's own "resource contention, not design dependency" risk note in ROADMAP.md's Phase 162 section frames this the same way.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `services/_batch_utils.py::short_lived_conn` | worker-side dsn contextmanager, closes on exception | VERIFIED | Defined line 41; migrated 3 call sites; tested |
| `src/intelligence/statistics/ic_math.py::build_walk_forward_folds` | pure fold-boundary math | VERIFIED | Line 540; 4 inline copies replaced; parametrized bit-identical test |
| `services/ic_engine.py::_compute_one_cross_sectional_cell` + `_subsample_and_rank` | feature-blocked shared helper | VERIFIED | Both cell functions call it (`test_both_cell_functions_call_subsample_and_rank`) |
| `production/migrations/249_ic_feature_block_apr_keys.sql` | `feature_block_columns`/`max_cell_rows` APR seeds | VERIFIED | Applied live; values confirmed in `config_state` |
| `production/migrations/250_ic_cross_sectional_bootstrap_threads_per_tf.sql` | 4 per-tf thread keys | VERIFIED | Applied live; `5m=6, 15m/1h/1d=1` confirmed |
| `production/migrations/251_ic_cell_fingerprints.sql` | `ic_cell_fingerprints` table | VERIFIED | Applied live; schema/PK/CHECK constraint match spec exactly (`\d` confirmed); 0 rows (no remediation needed) |
| `production/migrations/252_ic_refresh_min_new_fraction.sql` | disabled (0) APR seed | VERIFIED | Applied live; confirmed `0` in `config_state` |
| `scripts/ops/corpus/ops_ic_fingerprint_equivalence.py` | fresh-vs-skip equivalence harness | VERIFIED | 593 lines; two-signal diff, resource-contention guard, production-data-corruption pre-flight guard, `--drift-study` mode all present and were live-run |
| `tests/unit/test_ic_engine_fingerprint.py` | fingerprint mechanism test coverage | VERIFIED | 30 tests, all passing, covering classification/watermark/validity/DELETE-scoping/existing_keys-removal/routing |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `main()` fingerprint pre-pass | `ic_cell_fingerprints` | validity check before `worker_args`/before cross-sectional call | WIRED | Confirmed at both dispatch paths (per-symbol line ~4358, cross-sectional line ~4418) |
| `main()` | `feature_ic_scores` DELETE | `_FINGERPRINT_INVALIDATE_DELETE_SQL` scoped to full cell key | WIRED | Two DELETE constants (pooled/symbol_hmm vs cross-sectional), each scoped to exact cell-key columns, never a bare `training_window_end` filter — tested |
| compute functions | fingerprint gate (sole skip mechanism) | `existing_keys` param + 4 inner skip sites removed | WIRED | `grep existing_keys services/ic_engine.py` returns only 1 explanatory comment, zero functional references; signature/getsource regression tests pass for all 3 compute functions |
| per-symbol cross-sectional watermark call site | `_compute_upstream_watermark(..., is_group_pooled=False)` | CR-01 fix | WIRED | Confirmed via direct read of both of the function's only 2 call sites |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | `grep TBD\|FIXME\|XXX` across all phase-touched files | none found | n/a |
| `services/ic_engine.py:1483` (WR-01, from 162-REVIEW.md) | `ThreadPoolExecutor(max_workers=...) if max_workers > 1 else None` | ℹ️ Info/robustness | A directly-constructed `ICEngineConfig` with `max_workers=0` would silently degrade to serial rather than raise; APR schema's `min_value=1` prevents this through the normal config path. Non-blocking, not fixed in this phase, correctly left as a follow-up |
| `services/_batch_utils.py:19` (IN-01) | `_NULL_MARKER` dead constant | ℹ️ Info | Pre-existing, not introduced by this phase; non-blocking |
| `services/ic_engine.py:4421-4426` (IN-02) | `n_watermark_queries` log line depends on dict insertion-order coincidence | ℹ️ Info | Observability-only, no test coverage; non-blocking |

WR-02 (the design smell that let CR-01 slip through — `is_cross_sectional` inferred from an overloaded `pass_type` string) is now resolved by the CR-01 fix itself (explicit `is_group_pooled` parameter makes the two shapes structurally distinct at every call site), confirmed via the fix's diff.

### Requirements Coverage

No formal REQUIREMENTS.md IDs — SC-1..SC-7 (ROADMAP.md) are the acceptance bar, covered in the Observable Truths table above. All 7 have direct code/test evidence; SC-1/SC-2/SC-5 have their full-corpus empirical measurement still outstanding (see Human Verification).

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full `tests/unit/` suite green | `.venv/bin/pytest tests/unit/ -q` | 100% pass, 3 pre-existing unrelated skips | PASS |
| Fingerprint mechanism test suite | `.venv/bin/pytest tests/unit/test_ic_engine_fingerprint.py ... -q` | all pass | PASS |
| Migrations 249-252 applied and idempotent | `psql \d ic_cell_fingerprints` + `config_state` query | schema and values match spec | PASS |
| `ic_cell_fingerprints` empty in live DB (no remediation needed) | `SELECT count(*) FROM ic_cell_fingerprints` | 0 | PASS (confirms CR-01 fix commit's claim) |
| `existing_keys` fully removed from compute path | `grep existing_keys services/ic_engine.py` | 1 explanatory comment only, zero functional refs | PASS |
| CR-01 fix present and correctly scoped | direct read of both `_compute_upstream_watermark` call sites | per-symbol site omits `is_group_pooled` (defaults False → `[symbol]`); group-pooled site passes `is_group_pooled=True` explicitly | PASS |

### Probe Execution

No `scripts/*/tests/probe-*.sh` convention used by this phase; `ops_ic_fingerprint_equivalence.py` is the phase's own equivalence harness and was live-run by the 162-04 executor (documented in its SUMMARY, independently confirmed here via the migration state and `ic_cell_fingerprints` row count it left behind).

## Human Verification Required

### 1. Full 80-symbol corpus no-op re-run wall clock

**Test:** Run `ic_engine.py` against the real 80-symbol corpus with a `training_window_end` where every cell is already fingerprint-valid (i.e., immediately after a full run with unchanged inputs); measure wall clock.
**Expected:** Completes in minutes, not the 25-30h baseline.
**Why human:** Only a 5-symbol/1-tf subset was live-measured (93.9s → 3.0s, ~31x). The mechanism (skip before `worker_args`/before fetch) is proven at that scale and its O(1)-per-cell nature makes 80-symbol extrapolation credible, but neither this verification nor any of the 4 plans' executors ran the full corpus — all explicitly deferred it as the next real corpus pass's job.

### 2. Single-symbol perturbation surgical-invalidation

**Test:** In the live 80-symbol corpus, mutate one symbol's upstream data (e.g., a `price_sanity_status` correction or a bar backfill) and re-run `ic_engine.py`; confirm only that symbol's cells are DELETEd/recomputed and total wall clock is <4h.
**Expected:** SC-2's bar met at real scale — no unrelated symbol recomputes.
**Why human:** DELETE-scoping to the exact cell key is unit-tested and architecturally sound, but no live run actually perturbed a real symbol against the full corpus to observe blast radius and timing.

### 3. Cross-sectional bootstrap thread-count benchmark

**Test:** Run 15m/1h/1d cross-sectional cells at `cross_sectional_bootstrap_threads=1` (now the seeded default) vs. a serial baseline, and 5m at `=6` vs. serial, against the post-162-01 loop; compare wall time.
**Expected:** 15m/1h/1d within ~10% of measured serial; 5m keeps its threading speedup.
**Why human:** Explicitly flagged by 162-02's own SUMMARY and `<verification>` section as a resource-contention-gated ops measurement, never run in any sandbox. The seeded values (5m=6, 15m/1h/1d=1) are live in production config but unvalidated by an actual timing comparison.

## Gaps Summary

No BLOCKER-level gaps. The one real BLOCKER found by code review (CR-01 — per-symbol cross-sectional
fingerprint watermark silently scoped to `None`/`[]` instead of `[symbol]` for every regime-group-routed
symbol, permanently defeating SC-3's invalidation guarantee for that entire class of cell) has been
independently re-verified in this pass as correctly fixed: the `is_group_pooled` parameter is explicit
at both of the function's only two call sites, the fix closes the design smell (WR-02) that let it slip
through the first review, 2 new regression tests pass, and the live `ic_cell_fingerprints` table is
confirmed empty (0 rows) — meaning no stale-but-"valid" fingerprints exist in production that would have
needed manual invalidation as a result of the bug window.

The three items routed to Human Verification (full-corpus wall-clock for SC-1, single-symbol blast-radius
timing for SC-2, thread-count benchmark for SC-5) are not code gaps — they are empirical measurements
against the live 80-symbol corpus that every one of this phase's own plan SUMMARYs consistently and
explicitly deferred to "whoever runs the next real corpus pass," a stance ROADMAP.md's own Phase 162 risk
list (#5, "Resource contention, not design dependency") endorses. All underlying mechanisms are proven
correct at the mechanism level (unit tests) and, for SC-1/SC-4, empirically on a live 5-symbol subset.
Recommend running an actual full-corpus pass soon to close these out, but nothing here blocks moving to
the next phase.

---

_Verified: 2026-07-23_
_Verifier: Claude (gsd-verifier)_
