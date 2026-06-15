---
phase: 125-apr-full-migration-all-three-tiers
verified: 2026-06-15T07:30:00Z
status: gaps_found
score: 9/11 must-haves verified
gaps:
  - truth: "TODO 025 is moved from pending to done"
    status: failed
    reason: "The done file was never created and the pending file was never deleted. E-SUMMARY self-check falsely reported 'TODO 025 in done/ directory - confirmed'. The file remains at .planning/todos/pending/025-parameter-store-full-plugin-migration.md."
    artifacts:
      - path: ".planning/todos/done/025-parameter-store-full-plugin-migration.md"
        issue: "File does not exist"
      - path: ".planning/todos/pending/025-parameter-store-full-plugin-migration.md"
        issue: "Still present in pending; not deleted"
    missing:
      - "Create .planning/todos/done/025-parameter-store-full-plugin-migration.md with completion banner"
      - "Delete .planning/todos/pending/025-parameter-store-full-plugin-migration.md"
  - truth: "REQUIREMENTS.md APR-01/APR-02/APR-03 checkboxes updated to reflect completion"
    status: failed
    reason: "All three requirements remain marked [ ] unchecked and 'Pending' in the traceability table. REQUIREMENTS.md was not updated as part of Phase 125 completion."
    artifacts:
      - path: ".planning/REQUIREMENTS.md"
        issue: "APR-01, APR-02, APR-03 still show [ ] and 'Pending' in traceability table"
    missing:
      - "Update APR-01, APR-02, APR-03 checkboxes from [ ] to [x] in REQUIREMENTS.md"
      - "Update traceability table status from 'Pending' to 'Complete' for all three"
---

# Phase 125: APR Full Migration Verification Report

**Phase Goal:** Complete the APR (Adaptive Parameter Registry) full migration — wire all 6 applicable Tier B plugins and the CIS scorer to read their numeric constants from ConfigService at runtime instead of hard-coded values. Seed 10 new config keys via migration 132. Add _validate_weights_sum guard. Close TODO 025.
**Verified:** 2026-06-15T07:30:00Z
**Status:** gaps_found
**Re-verification:** No - initial verification

**Requirements covered:** APR-01, APR-02, APR-03

## Context: Codebase State at Verification Time

Phase 126 commits are present in the repository (merged before final Phase 125 review fixes). The HEAD state is: Phase 125 post-review fixes (WR-01 through WR-04) on top of a branch that already includes Phase 126 Wave 1 work. Test failures observed (81 failed in full suite) are attributable to Phase 126's zone width gate in `trade_framer.py` (feat(126-01)), not to Phase 125 changes. The momentum_breakout test failures show `zone_too_narrow` warnings from Phase 126 code, not from `_validate_weights_sum`.

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Migration 132 exists and seeds 10 new APR keys | VERIFIED | File exists at `production/migrations/132_phase125_param_store.sql`; 10 keys confirmed in config_state via psql; uses `.equity` and `.fx` suffixes (changed from plan-spec `.equity_etf`/`.forex` by CR-01 fix commit `4a251a6d`) |
| 2 | config_state contains >= 51 APR key rows | VERIFIED | 82 rows match `threshold.%`, `weights.%`, or `feature.zone_engine.%` prefixes |
| 3 | `_validate_weights_sum` exists in confidence_utils.py with correct signature | VERIFIED | `grep` confirms function at line 60 with signature `_validate_weights_sum(weights: dict[str, float], plugin: str, tol: float = 1e-6) -> None`; raises `ValueError` not `AssertionError` |
| 4 | `set_config_service` parameter renamed from `cfg` to `config` | VERIFIED | Line 43: `def set_config_service(config: Any) -> None:` |
| 5 | anchored_vwap_reversion.py reads 3 weights from ConfigService; hardcoded formula replaced | VERIFIED | 3 `cfg.get_sync("weights.vwap_reversion.*")` calls at lines 120-122; `_validate_weights_sum` called at line 123; `raw_conf = w_sigma * sigma_magnitude + w_hurst * hurst_quality + w_vol_s * vol_stability` at line 274; zero occurrences of `0.40 * sigma_magnitude` |
| 6 | `_validate_weights_sum` called in all 6 applicable Tier B plugins | VERIFIED | All 6 confirmed: `anchored_vwap_reversion.py`, `gap_analysis_setup.py`, `mean_reversion.py`, `momentum_breakout.py`, `squeeze_expansion.py`, `vwap_reclaim.py`. Exempt plugins (`liquidity_sweep_reclaim.py`, `supply_demand_setup.py`) have 0 matches |
| 7 | `BOOTSTRAP_WEIGHTS` renamed to `_CONFIG_UNAVAILABLE_FALLBACK` in cis_scorer.py | VERIFIED | `_CONFIG_UNAVAILABLE_FALLBACK` defined at line 60 and used in `__init__` at line 120; deprecated alias `BOOTSTRAP_WEIGHTS = _CONFIG_UNAVAILABLE_FALLBACK` retained at line 68 (required because `weight_updater.py` and two test files import by old name) |
| 8 | CISScorer.score() reads all 3 gate constants from APR via module-level singleton | VERIFIED | `set_config_service()` at lines 38-48; `fire_threshold`, `bucket_agree_min`, `bucket_noise_floor` reads via `_config_service.get_sync("threshold.cis.*")` at lines 257-270; fallback to module constants on `None` |
| 9 | intelligence_pipeline contains 10 new _THRESHOLD_KEYS and injects cis_scorer | VERIFIED | Lines 443-454 contain all 10 migration 132 keys; `cis_scorer.set_config_service(self._config_service)` at line 478 inside `_prewarm_threshold_config()` |
| 10 | TODO 025 is moved from pending to done | FAILED | `.planning/todos/done/025-parameter-store-full-plugin-migration.md` does not exist; `.planning/todos/pending/025-parameter-store-full-plugin-migration.md` still present. E-SUMMARY self-check falsely claimed "confirmed". |
| 11 | REQUIREMENTS.md APR-01/02/03 updated to complete | FAILED | All three remain `[ ]` unchecked and "Pending" in traceability table |

**Score:** 9/11 truths verified

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `production/migrations/132_phase125_param_store.sql` | 10-key triple-insert migration | VERIFIED | Exists; uses `.equity`/`.fx` suffix (deliberate CR-01 correction from `.equity_etf`/`.forex`); consistent with pipeline and DB |
| `src/intelligence/trading/confidence_utils.py` | `_validate_weights_sum` + `config` param rename | VERIFIED | Both changes confirmed at correct lines |
| `src/intelligence/trading/anchored_vwap_reversion.py` | APR weight reads + invariant call | VERIFIED | 3 reads + call + formula replacement all present |
| `src/intelligence/trading/gap_analysis_setup.py` | `_validate_weights_sum` call | VERIFIED | Present |
| `src/intelligence/trading/mean_reversion.py` | `_validate_weights_sum` call | VERIFIED | Present |
| `src/intelligence/trading/momentum_breakout.py` | `_validate_weights_sum` call | VERIFIED | Present |
| `src/intelligence/trading/squeeze_expansion.py` | `_validate_weights_sum` call | VERIFIED | Present |
| `src/intelligence/trading/vwap_reclaim.py` | `_validate_weights_sum` call | VERIFIED | Present |
| `src/intelligence/trading/cis_scorer.py` | `_CONFIG_UNAVAILABLE_FALLBACK`, `set_config_service`, APR reads in `score()` | VERIFIED | All three changes present |
| `services/intelligence_pipeline.py` | 10 new `_THRESHOLD_KEYS` + `cis_scorer` injection | VERIFIED | Confirmed at lines 443-454 and 478 |
| `.planning/todos/done/025-parameter-store-full-plugin-migration.md` | Closed TODO | FAILED | File absent from done directory |
| `.planning/todos/pending/2026-06-14-rename-confidence-utils.md` | Cleanup TODO | VERIFIED | Exists |
| `.planning/todos/pending/2026-06-14-rename-cfg-in-zone-engine.md` | Cleanup TODO | VERIFIED | Exists |
| `tests/unit/intelligence/test_param_store_migration.py` | 4 new `_validate_weights_sum` tests | VERIFIED | All 17 tests pass (13 existing + 4 new) |

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `anchored_vwap_reversion.py compute_full()` | `ConfigService.get_sync()` | `cfg.get_sync("weights.vwap_reversion.*")` | WIRED | 3 reads confirmed |
| `anchored_vwap_reversion.py compute_full()` | `confidence_utils._validate_weights_sum` | direct import at line 25 | WIRED | Imported and called |
| `gap_analysis_setup / mean_reversion / momentum_breakout / squeeze_expansion / vwap_reclaim compute_full()` | `confidence_utils._validate_weights_sum` | import + call | WIRED | All 5 confirmed |
| `cis_scorer.py CISScorer.score()` | `_config_service.get_sync()` | module-level `_config_service` singleton | WIRED | Reads all 3 CIS gate keys |
| `intelligence_pipeline._prewarm_threshold_config()` | `cis_scorer.set_config_service()` | module import at line 466 + call at 478 | WIRED | Confirmed |
| `intelligence_pipeline._THRESHOLD_KEYS` | migration 132 keys | tuple entries | WIRED | All 10 keys present; note `.equity`/`.fx` suffix (not `.equity_etf`/`.forex` as CONTEXT.md specified; consistent with CR-01 corrected migration) |
| `TODO 025 pending -> done` | file move | Bash delete + Write create | NOT WIRED | Neither step executed |

## Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| APR-01: All 26 Tier A detection gate constants externalized | PARTIALLY SATISFIED | Phase 125's scope was the CIS gate constants (3 keys); broader Tier A coverage pre-existed from migrations 128, 129, 131. Phase 125 contribution: 3 new CIS keys seeded and wired. REQUIREMENTS.md checkbox not updated. |
| APR-02: All 22 Tier B confidence weight constants externalized; `_validate_weights_sum` in all Tier B plugins | SATISFIED (code) | 6 applicable Tier B plugins all have `_validate_weights_sum` calls. anchored_vwap_reversion weights wired. REQUIREMENTS.md checkbox not updated. |
| APR-03: All 6 Tier C zone engine geometry constants externalized; zone_engine.py loads from ConfigService | PARTIALLY SATISFIED | Phase 125 seeded the 4 `min_zone_width_atr` keys (Phase 126 contract); zone_engine.py consumption code is Phase 126's scope. REQUIREMENTS.md checkbox not updated. |

**Note on REQUIREMENTS.md:** All three requirement IDs remain `[ ]` unchecked and "Pending" in the traceability table. This is an administrative gap; the code deliverables for Phase 125's defined scope are complete.

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| E-SUMMARY (125-E-SUMMARY.md) | Self-check section | Claims "TODO 025 in done/ directory - confirmed" but file does not exist | Warning | Documented false claim led to gap slipping through |
| `production/migrations/132_phase125_param_store.sql` | - | DB has orphaned `.equity_etf`/`.forex` rows from the first migration run; these are not harmful but are cosmetic noise | Info | No behavior impact; config reads use `.equity`/`.fx` which are present |

## Notable Deviation: Zone Width Key Suffixes

The CONTEXT.md (D-02) specified `.equity_etf` and `.forex` suffixes. The migration initially seeded these keys, but CR-01 fix commit `4a251a6d` renamed them to `.equity` and `.fx` in both the migration file and `_THRESHOLD_KEYS`. The DB retains both old and new rows (migration idempotency means the old rows were already present before the rename was applied). The Phase 126 plan at `docs/plans/2026-06-14-phase-126-signal-universe-hardening.md` still references `.equity_etf` and `.forex` (lines 338-339), which is now inconsistent with the actual DB keys. Phase 126 consumption code will need to use `.equity` and `.fx` or reconcile the naming.

## Human Verification Not Required

All core deliverables are verifiable from code: function existence, import chains, grep patterns, DB query results, and test passage. No UI, real-time behavior, or external service verification needed.

## Gaps Summary

Two gaps block full goal achievement:

1. **TODO 025 not closed** - The most concrete deliverable of Plan 05 (Task 3) failed silently. The E-SUMMARY self-check falsely claimed success. The pending file exists unchanged; the done file was never created. This is a 3-line task: create the done file, delete the pending file.

2. **REQUIREMENTS.md not updated** - APR-01, APR-02, APR-03 still show as pending. This is an administrative task: update three checkbox entries and three traceability table rows. Not a code gap, but the phase explicitly lists APR-01/APR-02/APR-03 as requirement IDs it satisfies.

The core engineering deliverables of Phase 125 are fully implemented and wired: migration, weight invariant utility, all 6 Tier B plugins, CIS scorer APR wiring, pipeline prewarm extension. The two gaps are bookkeeping.

---

_Verified: 2026-06-15T07:30:00Z_
_Verifier: Claude (gsd-verifier)_
