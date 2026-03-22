---
phase: 45-i6-i7-confluence-wiring-exhaustion-standardization
verified: 2026-03-22T06:30:00Z
status: passed
score: 6/6 must-haves verified
re_verification: null
gaps: []
human_verification:
  - test: "Live calibrated_confidence unchanged after Phase 45 wiring"
    expected: "24h signal_ledger query shows zero score distribution shift — _shadow capture does NOT modify confidence values"
    why_human: "Requires live DB with post-Phase-45 signals to compare distributions. Cannot verify statically."
---

# Phase 45: I6 → I7 Confluence Wiring + Exhaustion Standardization Verification Report

**Phase Goal:** All 36 I7 plugins capture I6 ctf_* sub-scores and exhaustion fields into a standardized `_shadow` dict per signal — zero confidence modification (Option C: Phase 49 learns weights). Expose `ctf_fvg_alignment` + `ctf_ob_alignment` from I6. `capture_confluence_features()` + `ConfluenceWeightProfile` land in `confidence_utils.py`. Lifecycle O(1) index + chandelier write guard verified via regression tests.
**Verified:** 2026-03-22T06:30:00Z
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `ctf_fvg_alignment` and `ctf_ob_alignment` emitted from `cross_timeframe.py` and added to `I6Confluence` schema | VERIFIED | Both fields in `outputs` frozenset (lines 49-50) and return dict (lines 130-131); `schemas.py` I6Confluence lines 702-703 |
| 2 | `capture_confluence_features()` exists in `confidence_utils.py`, returns shadow dict with zero confidence modification | VERIFIED | Function at line 93 of confidence_utils.py; `ConfluenceWeightProfile` at line 46; `FAMILY_PROFILES` 6-key dict at line 68 |
| 3 | All 36 I7 plugins assign `signal["_shadow"]` via `capture_confluence_features()` | VERIFIED | `grep -rl "capture_confluence_features"` returns exactly 36 plugin files (excluding confidence_utils.py itself) |
| 4 | Shadow dict structure matches spec: profile, existing_confidence, 6 ctf_* fields, 3 exhaustion fields | VERIFIED | Function body confirmed in confidence_utils.py; 7 tests pass covering all field presence scenarios |
| 5 | Exhaustion utilities wired per family — trend family uses guard, mean-reversion/session/SMC use boost, microstructure per-plugin | VERIFIED | All 7 trend plugins have `apply_exhaustion_guard` (2 references each); all 6 MR + 7 session + 7 SMC plugins have `apply_exhaustion_boost`; OFIContinuation has guard; 6 spike/divergence plugins have exemption comments; DeltaExhaustion uses `exempt_exhaustion` profile |
| 6 | SignalLifecycleService O(1) active-signal lookup via `_active_index` dict + chandelier write guard at 0.01% threshold | VERIFIED | `_active_index` at line 218; `_active_index_reseed_loop` at line 1089; `_remove_from_index` at line 1075; write guard at lines 677-682 with 0.0001 threshold; 10 regression tests pass |

**Score:** 6/6 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/intelligence/trading/confidence_utils.py` | `capture_confluence_features()`, `ConfluenceWeightProfile`, `FAMILY_PROFILES` | VERIFIED | All 3 exports present; FAMILY_PROFILES has exactly 6 keys |
| `src/intelligence/confluence/cross_timeframe.py` | `ctf_fvg_alignment` and `ctf_ob_alignment` in output dict and `outputs` frozenset | VERIFIED | 2 occurrences of `ctf_fvg_alignment` (frozenset + return dict) |
| `src/intelligence/schemas.py` | `I6Confluence` has `ctf_fvg_alignment: float | None` and `ctf_ob_alignment: float | None` | VERIFIED | Lines 702-703 |
| `tests/unit/test_capture_confluence_features.py` | 5+ unit tests for `capture_confluence_features` and `ConfluenceWeightProfile` | VERIFIED | 7 tests; all pass |
| `src/intelligence/trading/trend_following.py` (and 6 other trend plugins) | Shadow capture + exhaustion guard | VERIFIED | All 7 files have `capture_confluence_features` and `apply_exhaustion_guard` (2 refs each) |
| `src/intelligence/trading/mean_reversion.py` (and 5 other MR plugins) | Shadow capture + exhaustion boost | VERIFIED | All 6 files have `capture_confluence_features` and `apply_exhaustion_boost` |
| `src/intelligence/trading/session_extremes_setup.py` (and 6 other session plugins) | Shadow capture + exhaustion boost + profile="session" | VERIFIED | All 7 session files have both imports and `_shadow` assignment |
| `src/intelligence/trading/divergence_stack.py` | Shadow capture + exhaustion guard + profile="microstructure" | VERIFIED | `apply_exhaustion_guard` and `capture_confluence_features` present |
| `src/intelligence/trading/fvg_fill.py` (and 6 other SMC plugins) | Shadow capture + exhaustion boost + profile="smc" | VERIFIED | All 7 SMC files have `apply_exhaustion_boost` (2 refs each) |
| `src/intelligence/trading/delta_exhaustion.py` | Shadow capture with `exempt_exhaustion` profile + D-09 comment | VERIFIED | Line 134: profile `"exempt_exhaustion"`; exemption comment present |
| `src/intelligence/trading/ofi_continuation.py` | Shadow capture + exhaustion guard | VERIFIED | `apply_exhaustion_guard` (2 refs) + `_shadow` assignment |
| `src/intelligence/trading/ofi_divergence.py` (and 5 other spike/divergence plugins) | Shadow capture + "exhaustion: not applicable" comment | VERIFIED | All 6 have `capture_confluence_features` and exemption comment |
| `services/signal_lifecycle_service.py` | `_active_index`, `_active_index_reseed_loop`, `_remove_from_index`, `_last_written_stop` write guard | VERIFIED | All 4 present; `_active_index` 16 refs, `_last_written_stop` 4 refs |
| `tests/unit/service_tests/test_lifecycle_active_index.py` | 6+ regression tests for O(1) index and write guard | VERIFIED | 10 tests; all pass |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `confidence_utils.py` | All 36 I7 plugins | `from .confidence_utils import capture_confluence_features` | WIRED | All 36 plugin files import and call; verified by grep count = 36 |
| `cross_timeframe.py` | `frames["features"]` in I7 plugins | `IntelligenceEvent` pipeline, ctf_fvg/ob_alignment keys | WIRED | Fields added to outputs frozenset + return dict; I7 plugins read via `features.get("ctf_fvg_alignment", 0.0)` as mapped in `capture_confluence_features` |
| `trend_following.py` (ref impl) | `confidence_utils.py` | `from .confidence_utils import capture_confluence_features` | WIRED | Import confirmed, `signal["_shadow"]` assigned post-return dict construction |
| `mean_reversion.py` (ref impl) | `exhaustion_utils.py` | `from .exhaustion_utils import apply_exhaustion_boost` | WIRED | Import confirmed, boost called before compose_confidence |
| `signal_lifecycle_service.py` | `_active_index` dict | `active_index.get((symbol, tf), [])` O(1) lookup | WIRED | Pattern at lines 932-934; index seeded at startup, reseeded every 60s |

---

### Requirements Coverage

| Requirement | Source Plan | Phase 45 Description | REQUIREMENTS.md Definition | Status | Evidence |
|-------------|------------|---------------------|---------------------------|--------|----------|
| CONF-01 | 45-01-PLAN.md | Expose ctf_fvg/ob_alignment from I6; add capture_confluence_features() infrastructure | REQUIREMENTS.md: "market_analysis_service subscribes to cross_asset topic" — DIFFERENT MEANING | SATISFIED (Phase 45 scope) | Phase 45 ROADMAP uses CONF-01 with local meaning (I6 infrastructure); ROADMAP.md Phase 45 section confirms this scope |
| CONF-02 | 45-02-PLAN.md | Wire shadow capture + exhaustion to trend/MR/session families | REQUIREMENTS.md: "CrossTimeframeConfluencePlugin scores VIX regime" — DIFFERENT MEANING | SATISFIED (Phase 45 scope) | 14 plugins wired per ROADMAP Phase 45 scope |
| CONF-03 | 45-03-PLAN.md | Wire shadow capture + exhaustion to SMC + microstructure families | REQUIREMENTS.md: "CrossTimeframeConfluencePlugin scores sector rotation" — DIFFERENT MEANING | SATISFIED (Phase 45 scope) | 15 plugins wired; all 36 I7 plugins now emit `_shadow` |
| PERF-04 | 45-04-PLAN.md | Lifecycle O(1) active-signal index regression tests | REQUIREMENTS.md: "Calibration curve breakpoints pre-converted to np.ndarray" — DIFFERENT MEANING | SATISFIED (Phase 45 scope) | Implementation verified in signal_lifecycle_service.py; 10 regression tests pass |

**Note on requirement ID collision:** CONF-01/02/03 and PERF-04 in the plan frontmatter match ROADMAP.md Phase 45-local definitions, NOT REQUIREMENTS.md global definitions. The REQUIREMENTS.md global definitions for these IDs are already marked `[x]` (completed in prior phases). The ROADMAP.md Phase 45 section (lines 623, 643-646) maps these IDs explicitly to Phase 45-local work items. This is a naming reuse issue — both the prior-phase completions and Phase 45 deliverables claim the same IDs. Functionally all Phase 45 work is implemented and verified. No blocking issue; informational flag for future naming hygiene.

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `src/intelligence/confluence/cross_timeframe.py` | 1 | Ruff I001: import block unsorted | Info | Pre-existing issue (same before Phase 45 commits); not introduced by this phase |
| `src/intelligence/confluence/cross_timeframe.py` | 91 | Ruff E501: line too long (102 chars) | Info | Pre-existing; line is a function call that can't easily be shortened without aliasing |
| `src/intelligence/trading/mean_reversion.py` | 70 | Ruff F841: `bb_middle` assigned but never used | Info | Pre-existing variable from prior code; not introduced by Phase 45 (file was already wired on read) |
| `src/intelligence/trading/divergence_stack.py` | 108-112, 188, 194 | Ruff E501: lines too long | Info | Pre-existing or from Phase 44 divergence_stack refactor (commit 89b4ccc predates Phase 45) |
| `src/intelligence/trading/signal_ledger.py` | 24, 39 | Ruff E402/I001 | Info | Pre-existing; not a Phase 45 modified file |

All ruff violations are either pre-existing or in files not modified by Phase 45. The plans' verification steps confirmed ruff clean on Phase 45-modified files at commit time. The violations now showing are in files touched by earlier phases.

---

### Human Verification Required

#### 1. Live Confidence Score Distribution Unchanged

**Test:** Query `signal_ledger` for signals computed after Phase 45 deploy date (2026-03-22). Compare `calibrated_confidence` distribution (mean, P25, P75, P95) against pre-Phase-45 baseline.
**Expected:** No shift in confidence distributions — `_shadow` capture is data-only; `compose_confidence()` is still the sole confidence pipeline.
**Why human:** Requires a live DB with post-Phase-45 signals. Cannot verify statically from code alone; must confirm end-to-end that no plugin's confidence accidentally changed.

---

### Gaps Summary

No gaps. All 6 observable truths are verified. All 36 I7 plugins emit `signal["_shadow"]`, exhaustion utilities are wired per family spec, I6 emits the new `ctf_fvg_alignment`/`ctf_ob_alignment` fields, and the lifecycle O(1) index with write guard has 10 passing regression tests. Full unit suite passes (2681 tests).

---

### Test Results

```
.venv/bin/pytest tests/unit/test_capture_confluence_features.py
  tests/unit/service_tests/test_lifecycle_active_index.py -q
17 passed, 10 warnings in 0.13s

.venv/bin/pytest tests/unit/ -q
2681 passed, 325 warnings in 46.06s
```

---

_Verified: 2026-03-22T06:30:00Z_
_Verifier: Claude (gsd-verifier)_
