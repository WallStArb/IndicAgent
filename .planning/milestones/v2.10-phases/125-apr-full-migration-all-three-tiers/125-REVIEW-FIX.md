---
phase: 125-apr-full-migration-all-three-tiers
fixed_at: 2026-06-15T10:48:00Z
review_path: .planning/phases/125-apr-full-migration-all-three-tiers/125-REVIEW.md
iteration: 1
findings_in_scope: 8
fixed: 7
skipped: 1
status: partial
---

# Phase 125: Code Review Fix Report

**Fixed at:** 2026-06-15T10:48:00Z
**Source review:** `.planning/phases/125-apr-full-migration-all-three-tiers/125-REVIEW.md`
**Iteration:** 1

**Summary:**
- Findings in scope: 8 (3 Critical + 5 Warning; WR-05 explicitly skipped per instructions)
- Fixed: 7
- Skipped: 1 (WR-05 — test coverage gap, tracked separately)

## Fixed Issues

### CR-01: Zone-width APR keys use wrong asset-class suffixes

**Files modified:** `production/migrations/132_phase125_param_store.sql`, `services/intelligence_pipeline.py`
**Commit:** 4a251a6d
**Applied fix:** Renamed all three occurrences of `.equity_etf` to `.equity` and `.forex` to `.fx` in the migration (config_schema, config_state, config_history sections). Updated the matching entries in `_THRESHOLD_KEYS` in `intelligence_pipeline.py`. Descriptions updated to match the corrected asset-class names.

### CR-02: SqueezeExpansionPlugin passes hardcoded empty strings for symbol/timeframe/timestamp

**Files modified:** `src/intelligence/trading/squeeze_expansion.py`
**Commit:** c9b9440f
**Applied fix:** Replaced the three blank string literals in the `make_signal_from_frame()` call with `frames.get("symbol", "") or frames.get("__symbol__", "")`, `features.get("timeframe", "")`, and `features.get("timestamp", "")` — the same pattern used by all peer plugins (anchored_vwap_reversion, gap_analysis_setup, momentum_breakout).

### CR-03: Duplicate migration prefix 132 creates ambiguous migration state

**Files modified:** `production/migrations/134_phase126_apr_seeds.sql` (renamed from `132_phase126_apr_seeds.sql`), `.planning/phases/126-signal-universe-hardening/126-01-PLAN.md`, `.planning/phases/126-signal-universe-hardening/126-01-SUMMARY.md`
**Commit:** f0511bda
**Applied fix:** Renamed `132_phase126_apr_seeds.sql` to `134_phase126_apr_seeds.sql` (134 is the next unused number after 133 which is taken by `133_phase126_mean_reversion.sql`). Updated all filename references in the Phase 126 plan and summary docs. The migration numbering invariant is restored.

### WR-01: geo_score in GapAnalysisSetup hardcodes 0.8 instead of using the live APR gate

**Files modified:** `src/intelligence/trading/gap_analysis_setup.py`
**Commit:** b114e8b4
**Applied fix:** Replaced the hardcoded `0.8` in `geo_score = clamp01((gap_size_atr - 0.8) / 1.7)` with `min_gap_atr` (already loaded from ConfigService at the top of `compute_full`). Added a `_geo_range = 1.7` local constant with a comment so the intent is clear. The confidence score zero-point now tracks the live gate threshold.

### WR-02: vwap_reclaim volume fallback includes current bar in baseline mean

**Files modified:** `src/intelligence/trading/vwap_reclaim.py`
**Commit:** 1967a2a0
**Applied fix:** Changed `float(df["volume"].mean())` to `float(df["volume"].iloc[:-1].mean()) if len(df) > 1 else float(df["volume"].mean())` in the fallback path. The current (potentially high-volume cross) bar is now excluded from the average, consistent with `gap_analysis_setup.py`.

### WR-03: momentum_breakout vol_sma includes current bar in 20-bar window

**Files modified:** `src/intelligence/trading/momentum_breakout.py`
**Commit:** 1770c8c5
**Applied fix:** Changed `volume[-20:]` to `volume[-21:-1]` (guarded by `len(volume) >= 21`), with a fallback of `volume[:-1]` when fewer bars are available. The breakout bar is now excluded from the SMA baseline. Added an explanatory comment.

### WR-04: AnchoredVWAPReversionPlugin and SqueezeExpansionPlugin missing shadow_only

**Files modified:** `src/intelligence/trading/anchored_vwap_reversion.py`, `src/intelligence/trading/squeeze_expansion.py`
**Commit:** cfaaac9e
**Applied fix:** Added `shadow_only: bool = True` to both dataclasses, positioned after `requires_i6_confluence: bool = True` to match the ordering in peer plugins (gap_analysis_setup, momentum_breakout, vwap_reclaim, mean_reversion).

## Skipped Issues

### WR-05: No test coverage for Phase 125 APR code paths

**File:** `tests/unit/intelligence/test_param_store_migration.py`
**Reason:** Skipped per instructions — tracked as a separate concern.
**Original issue:** None of the new Phase 125 APR paths (cis_scorer config injection, anchored_vwap weights validation, per-plugin compute paths) have test coverage. If any `if cfg else` branch inverts or is removed, no test catches it.

---

_Fixed: 2026-06-15T10:48:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
