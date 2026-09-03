---
phase: 163-vp-sr-structural-primitives
verified: 2026-07-23T20:57:06Z
status: passed
score: 15/15 must-haves verified
overrides_applied: 0
---

# Phase 163: VP/SR Structural Primitives Verification Report

**Phase Goal:** Implement real, non-placeholder computation for the 4 permanently-stuck structural
`FeatureVector` columns (`poc_dist_atr`, `va_position`, `sr_support_dist`, `sr_resist_dist`) plus 17
new ATR-normalized/bounded VP+S/R columns, in both the live streaming pipeline and the batch
backfill path — closing todo 153.

**Verified:** 2026-07-23T20:57:06Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `feature_vectors` has 17 new structural columns (12 VP + 5 S/R), no raw-price columns | ✓ VERIFIED | `information_schema.columns` query returns exactly 17 matching `double precision` columns; `poc_price`/`vah`/`val`/`poc_price_rolling`/`vah_rolling`/`val_rolling`/`nearest_hvn_level`/`nearest_lvn_level` return zero rows (confirmed absent) |
| 2 | `feature_registry` has 17 new rows, `status='active'`, `added_phase='163'`, drift gate (registry name-set == `FeatureVector` dataclass field-set) passes | ✓ VERIFIED | Live query: all 17 rows present with `status=active, added_phase=163`; `registry-only: set()`, `dataclass-only: set()`, both sets = 172 fields |
| 3 | `FeatureCache.update_session_vp()` computes real session POC/VAH/VAL/HVN/LVN raw state, session-boundary reset at NY open | ✓ VERIFIED | Read `feature_cache.py:190-285` — non-incremental per-call histogram recompute, ET-date session-boundary reset (`_et_from_utc` + `ny_session_start_utc_hour/minute`), value-area tie-break bug found+fixed during Plan 01 (verified: `np.lexsort` tie-break present) |
| 4 | New `feature.session_vp.*`/`feature.sr.*` APR keys exist in `config_state`; no new hardcoded numeric constants | ✓ VERIFIED | All 8 keys present in `config_state` with correct values (`value_area_pct=0.70`, `n_buckets=50`, `hvn/lvn_threshold=0.80/0.20`, `rolling_window=480`, `sr.window=10`, `sr.cluster_atr_mult=0.5`, `sr.lookback_by_tf` valid JSON) |
| 5 | `poc_dist_atr`/`va_position` vary across bars (not frozen 0.0/0.5) in both `compute()` and `compute_batch()` | ✓ VERIFIED | `test_vp_fields_non_constant_batch` passes; code path confirmed real (`_derive_session_vp` reads live `cache._sess_*` state, not a stub) |
| 6 | 12 new VP fields carry real ATR-normalized/bounded values, equal between live and batch for the same bars | ✓ VERIFIED | `test_live_batch_parity` passes (1e-6 tolerance); single shared `_derive_session_vp()`/`_rolling_poc_price()` helpers called from both `compute()` (feature_factory.py:3841-3848) and `compute_batch()` (:4265-4273) — structural parity, not test-only |
| 7 | Stale "requires I3 intraday injection" None-branch removed from `compute_batch()`; batch computes VP for real | ✓ VERIFIED | `grep -n "requires I3\|I3 intraday" src/intelligence/feature_factory.py services/backfill_feature_factory.py` returns zero matches |
| 8 | `cache.update_session_vp()` invoked once per bar in both live pipeline and `compute_batch()` (incl. warm-up) | ✓ VERIFIED | Live: `feature_vector_pipeline.py` `_process_bar_compute` calls it before `FeatureFactory.compute()`, plus `_get_cache()` warm-up replay (CR-01 fix). Batch: `compute_batch()` line 4201, called before the `warm_up_bars` skip at line 4204 |
| 9 | `sr_support_dist`/`sr_resist_dist` vary across bars (not stuck at 0.0) in both paths | ✓ VERIFIED | `test_sr_non_constant_batch` passes |
| 10 | S/R distance expressed in ATR units (not percent) | ✓ VERIFIED | `test_sr_in_atr_units` passes (deterministic constant-true-range micro-case, ATR converges to 1.0, asserted distance ≈1.0); code confirms `(level - close_) / atr_val` conversion, not percent |
| 11 | S/R computed statelessly inline (no cache mutator), reusing `find_peaks`/`find_troughs` | ✓ VERIFIED | `_compute_sr_dist_atr()` (feature_factory.py:3332-3414) is a pure function; imports/calls `find_peaks`/`find_troughs` directly; no new `FeatureCache` mutator added for S/R |
| 12 | `resistance_strength`/`support_strength`/`resistance_age_bars`/`support_age_bars`/`sr_level_count` populated from the same clustering pass (D-19), not left null | ✓ VERIFIED | `test_sr_d19_fields_non_constant` passes; DB registry confirms all 5 columns `status=active`; code reads all 5 off the same `_cluster_levels`/`_finalize_cluster` objects used for the distance calc |
| 13 | All stale "requires I3" docstrings removed; `ctx_SRConsensus` NOT built | ✓ VERIFIED | Zero "requires I3"/"I3 intraday" matches anywhere in `feature_factory.py`/`backfill_feature_factory.py`; zero `SRConsensus`/`zone_engine`/`collect_sr_candidates` references in `feature_factory.py` |
| 14 | CR-01 (session-VP accumulator not warmed on `FeatureCache` creation) actually fixed | ✓ VERIFIED | `feature_vector_pipeline.py:_get_cache()` now replays `update_session_vp()` over buffered bar history alongside the pre-existing `update_wk_vwap()` replay, symmetric with the todo-159 precedent |
| 15 | CR-02 (live rolling-POC window silently capped below configured 480 by `BarHistory(maxlen=200)`) documented + regression-guarded | ✓ VERIFIED | Migration 256 corrects the APR description (no false "genuinely reaches 480 live" claim remains); `test_poc_rolling_dist_atr_live_cap_gap_cr02` pins the gap (full-220 vs capped-200 windows differ >0.5 ATR) — deliberately NOT structurally fixed (filed as todo 177, accepted per task context) |

**Score:** 15/15 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `production/migrations/255_vp_structural_primitives.sql` | 17 columns + 17 registry rows + 8 APR keys | ✓ VERIFIED | Applied live; all objects present and match migration text |
| `production/migrations/256_session_vp_rolling_window_live_cap_correction.sql` | CR-02 description correction | ✓ VERIFIED | Applied live, idempotent guard present |
| `src/intelligence/feature_cache.py` | `update_session_vp()` + internal `_sess_*` state | ✓ VERIFIED | Present, wired, tie-break bug fixed |
| `src/intelligence/feature_factory.py` | `_derive_session_vp`, `_rolling_poc_price`, `_compute_sr_dist_atr`, `_cluster_levels`, `_finalize_cluster` | ✓ VERIFIED | All present, called from both `compute()`/`compute_batch()` |
| `src/intelligence/features/feature_vector_persistence.py` | 17-column INSERT extension | ✓ VERIFIED | `_STRUCTURAL_VP_SR_FIELD_NAMES` derived-by-name slice, threaded through SQL + params tuple |
| `tests/unit/intelligence/test_volume_profile_primitives.py` | Regression: non-constant, parity, no-raw-price, CR-02 gap | ✓ VERIFIED | 4 tests, all pass |
| `tests/unit/intelligence/test_support_resistance_primitives.py` | Regression: non-constant, ATR-unit, parity, D-19 fields | ✓ VERIFIED | 4 tests, all pass |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `services/feature_vector_pipeline.py _process_bar_compute` | `cache.update_session_vp()` | per-bar call before `compute()` | ✓ WIRED | Confirmed at call site + `_get_cache()` warm-up replay |
| `feature_factory.py compute()/compute_batch()` | `cache._sess_poc`/`atr_val` | `_derive_session_vp()` | ✓ WIRED | Single shared helper, both call sites confirmed |
| `feature_factory.py compute()/compute_batch()` | `find_peaks`/`find_troughs` (`utils.py`) | `_compute_sr_dist_atr()` | ✓ WIRED | Confirmed import + call |
| `src/intelligence/schemas.py FeatureVector` | `production/migrations/255+256 feature_registry` | identical field-name set | ✓ WIRED | Live drift-gate check: 172 == 172, zero diff |

### Behavioral Spot-Checks / Test Execution

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| VP+SR regression suites | `.venv/bin/pytest tests/unit/intelligence/test_volume_profile_primitives.py tests/unit/intelligence/test_support_resistance_primitives.py -v` | 8 passed | ✓ PASS |
| Full unit suite (regression check) | `.venv/bin/pytest tests/unit/ -q` | all pass, 3 pre-existing unrelated skips | ✓ PASS |
| Lint | `.venv/bin/ruff check` on all 6 touched source files | All checks passed | ✓ PASS |
| Debt-marker scan | `grep TBD\|FIXME\|XXX` on all touched files + both migrations | zero matches | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|--------------|------------|--------------|--------|----------|
| TODO-153 | 01/02/03 | VP/SR features permanently null | ✓ SATISFIED (code) | Real computation verified end-to-end; **todo file itself still sits in `pending/`, not moved to `completed/`** — see Housekeeping Note below |
| D-03, D-06, D-13, D-16, D-19 | 01 | Data contract, APR keys, port source, no-raw-price rule, S/R free-field additions | ✓ SATISFIED | All verified live in DB/dataclass |
| D-05 | 02/03 | Remove stale "requires I3" comments | ✓ SATISFIED | Zero occurrences remain |
| D-02, D-04, D-14 | 03 | S/R port source, stateless computation, `ctx_SRConsensus` deferral | ✓ SATISFIED | Verified in code |

### Anti-Patterns Found

None blocking. No `TBD`/`FIXME`/`XXX`/placeholder/stub patterns in any file touched by this phase.

## Housekeeping Notes (non-blocking, informational only)

1. **Todo 153 not moved to `completed/`.** The phase's own CONTEXT.md/SUMMARY narrative states this
   phase "closes todo 153," and the code truth backs that up (real computation now exists
   end-to-end), but `.planning/todos/pending/153-vp-sr-features-null-in-batch-corpus.md` has not
   been moved to `completed/` or annotated with the resolution. This is a tracking/bookkeeping gap,
   not a code-truth gap — does not affect the phase goal's achievement, but should be closed out
   now that this verification confirms the real fix.
2. **ROADMAP.md still shows Phase 163 as "📋 PLANNED"** (line 2128) despite all 3 plans being
   checked off `[x]` with commits, a code review, and follow-up fixes already landed on `main`.
   Cosmetic/process staleness only; does not affect the verified code truth.

Neither item is included in the `gaps:` YAML — both are documentation bookkeeping, not evidence
against the phase's actual, verified deliverable.

## Deferred Items (accepted, not gaps)

Per the task's explicit framing, these are known, accepted, out-of-scope items and are NOT
flagged as failures:

| Item | Status | Where tracked |
|------|--------|----------------|
| 17 new columns NULL on pre-existing historical rows | Accepted — migration only affects new rows | todo 176 (delete + full corpus recompute) |
| `BarHistory(maxlen=200)` systemic cap affecting other pre-existing windows beyond VP | Accepted, documented, regression-guarded (CR-02) | todo 177 |
| WR-02 (DST-boundary edge case), WR-03 (hot-reload gap), IN-01/IN-02/IN-03 | Accepted, deliberately deferred | todo 178 |

## Gaps Summary

No gaps found against this phase's must-haves. All 17 new columns exist in the live schema with
correct types and are registered `active` in `feature_registry` with the drift gate satisfied
(172 == 172 fields). Both the live pipeline and batch backfill path compute real, non-constant,
ATR-normalized values for all 21 structural fields via a single shared derivation helper per
sub-feature (VP: `_derive_session_vp`/`_rolling_poc_price`; S/R: `_compute_sr_dist_atr`), not
independent/divergent implementations. The two CRITICAL findings from the phase's own code review
(CR-01: session-VP accumulator not warmed on restart; CR-02: live rolling-POC window capped below
its configured value) were independently confirmed present in the code as fixed — CR-01
structurally (warm-up replay added), CR-02 via documentation correction + a new regression test
pinning the known live/backfill window-size gap (a reasonable choice for a gap gated on a separate
systemic todo, not a phase-163-introduced defect). All 8 regression tests (4 VP + 4 S/R) pass, and
the full unit suite (all `tests/unit/`) remains green with no regressions introduced.

---

*Verified: 2026-07-23T20:57:06Z*
*Verifier: Claude (gsd-verifier)*
