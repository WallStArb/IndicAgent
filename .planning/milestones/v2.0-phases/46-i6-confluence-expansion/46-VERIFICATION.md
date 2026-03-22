---
phase: 46-i6-confluence-expansion
verified: 2026-03-22T06:10:00Z
status: human_needed
score: 6/7 success criteria verified
re_verification: false
human_verification:
  - test: "Query intelligence_features.i6 for a live ES 1m bar and confirm ctf_vix_level and ctf_vix_z are non-None"
    expected: "Both fields populated with float values when VIX data has >= 20 bars in bar_history"
    why_human: "Requires live service running with VIX contract active; cannot verify against DB offline"
  - test: "Query intelligence_features.i6 for ES (EQ_INDEX) vs GC (non-EQ_INDEX) bars and confirm ctf_eq_spread_z/ctf_eq_pairs_confirming are non-None for ES, None for GC"
    expected: "EQ_INDEX symbols show populated spread fields; non-EQ_INDEX symbols show None for both"
    why_human: "Requires cross_asset_enabled=True and live cross_asset topic data flowing; cannot verify offline"
  - test: "Compare ctf_score distribution in intelligence_features.i6 for a 24h window before vs after Phase 46 deploy"
    expected: "ctf_score mean/stddev/percentiles are statistically identical — new fields are independent, formula unchanged"
    why_human: "Requires DB access and sufficient post-deploy data accumulation; formula unchanged verified in code but runtime distribution requires live data"
---

# Phase 46: I6 Confluence Expansion Verification Report

**Phase Goal:** Extend I6 Confluence with VIX and cross-asset awareness — add 4 new fields to schema, wire FeaturePipelineService with VIX/cross-asset frame injection, and extend capture_confluence_features() to capture the new fields.
**Verified:** 2026-03-22T06:10:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | I6Confluence schema has 4 new float\|None fields: ctf_vix_level, ctf_vix_z, ctf_eq_spread_z, ctf_eq_pairs_confirming | VERIFIED | `src/intelligence/schemas.py` lines 711-714: all 4 fields present with `float \| None = None` type |
| 2 | compute_vix_context() returns {level, z_score, ready: True} when >= z_window bars available, {ready: False} when not | VERIFIED | `src/intelligence/context/vix_context.py` implements full logic; 16 unit tests pass |
| 3 | CrossTimeframeConfluencePlugin emits new fields from frames["vix"] and frames["cross_asset"]; None when data unavailable | VERIFIED | `cross_timeframe.py` lines 126-168: exact logic implemented; 8 tests pass covering all guard conditions |
| 4 | ctf_score formula unchanged — new fields are independent columns | VERIFIED | W_TREND=0.4, W_STRUCTURE=0.3, W_REGIME=0.2, W_PATTERN=0.1, W_I2=0.1 unchanged; new fields not included in weighted sum |
| 5 | FeaturePipelineService subscribes to cross_asset topic, caches payloads, injects frames["vix"] for ALL symbols and frames["cross_asset"] for EQ_INDEX only | VERIFIED | Lines 59,66-67,106,228-235,656-665,1004,1016-1020,1136-1137 in feature_pipeline_service.py confirm all injection points |
| 6 | capture_confluence_features() shadow dict includes 4 new fields with None default (not 0.0) | VERIFIED | `confidence_utils.py` lines 125-128: `features.get("ctf_vix_level")` with no default; 12 tests pass including None vs 0.0 semantics |
| 7 | New I6 fields appear as non-None values in live intelligence_features for appropriate symbols | ? HUMAN NEEDED | Requires live pipeline running with VIX and cross-asset data; cannot verify programmatically |

**Score:** 6/7 truths verified (1 requires human)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/intelligence/context/vix_context.py` | VIX context pure function module | VERIFIED | 61 lines; exports `compute_vix_context()`; zero service/kafka/settings imports |
| `tests/unit/test_vix_context.py` | Unit tests for VIX context | VERIFIED | 16 test functions (plan required 8+); all pass |
| `src/intelligence/schemas.py` | I6Confluence with 4 new fields | VERIFIED | ctf_vix_level, ctf_vix_z, ctf_eq_spread_z, ctf_eq_pairs_confirming at lines 711-714 |
| `src/intelligence/confluence/cross_timeframe.py` | CrossTimeframeConfluencePlugin emitting new fields | VERIFIED | New fields in outputs frozenset (lines 52-55) and return dict (lines 162-165) |
| `tests/unit/test_cross_timeframe_confluence.py` | Unit tests for new field emission | VERIFIED | 8 test functions; all pass |
| `services/feature_pipeline_service.py` | Frame injection for cross_asset + vix before I6 | VERIFIED | Imports, constant, cache, topic subscription, routing, and frame injection all present |
| `tests/unit/service_tests/test_feature_pipeline_vix_injection.py` | Unit tests for frame injection logic | VERIFIED | 6 test functions; all pass |
| `src/intelligence/trading/confidence_utils.py` | Extended capture_confluence_features with 4 new fields | VERIFIED | Lines 125-128: 4 new keys with None-default semantics |
| `tests/unit/test_capture_confluence_features.py` | Updated tests covering new shadow fields | VERIFIED | 12 test functions including `test_new_fields_none_when_missing` and `test_new_fields_preserve_none_not_zero` |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `services/feature_pipeline_service.py` | `src/intelligence/context/vix_context.py` | `from src.intelligence.context.vix_context import compute_vix_context` | WIRED | Line 66: import present; line 663: called with `vix_deque` |
| `services/feature_pipeline_service.py` | `src/core/stream_keys.py` | `topic_cross_asset` | WIRED | Line 59: import; lines 1004, 1137: used for routing and subscription |
| `services/feature_pipeline_service.py` | `src/intelligence/cross_asset_features.py` | `resolve_eq_index_base` | WIRED | Line 67: import; line 656: used as EQ_INDEX guard |
| `src/intelligence/confluence/cross_timeframe.py` | `src/intelligence/schemas.py` | Return dict keys match I6Confluence field names | WIRED | Return dict keys `ctf_vix_level/z/eq_spread_z/eq_pairs_confirming` match schema fields exactly |
| `src/intelligence/trading/confidence_utils.py` | `src/intelligence/schemas.py` | Shadow dict keys match I6Confluence field names | WIRED | Shadow dict keys added at lines 125-128 match I6Confluence field names from schema |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| CONF-04 | 46-02 | Cross-TF FVG + OB alignment fields exposed as independent I6 output fields | SATISFIED | `ctf_fvg_alignment` and `ctf_ob_alignment` exist in I6Confluence schema (lines 702-703) and are emitted by cross_timeframe.py (lines 159-160); these were present from Phase 45 and are confirmed unchanged |
| CONF-05 | 46-01, 46-02, 46-03 | I6Confluence exposes 4 new raw measurement fields; vix_context.py pure function; FeaturePipelineService injects frames | SATISFIED | All 4 fields in schema; vix_context.py implemented and tested; FeaturePipelineService injects frames["vix"] (all symbols) and frames["cross_asset"] (EQ_INDEX) |
| CONF-06 | 46-04 | capture_confluence_features() extended to include all 4 new fields in shadow dict; None (not 0.0) when upstream data unavailable | SATISFIED | confidence_utils.py lines 125-128: `features.get(key)` with no default; 2 dedicated tests verify None vs 0.0 semantics |

No orphaned requirements — CONF-01/02/03 belong to Phase 45 (verified in ROADMAP.md line 623). No CONF requirements assigned to Phase 46 are unaccounted for.

### Anti-Patterns Found

No anti-patterns found. Scan of all 4 modified source files and 5 new/modified test files:
- No TODO/FIXME/PLACEHOLDER comments
- No empty return stubs
- No hardcoded 0.0 defaults on z-score fields (deliberate None semantics enforced and tested)
- vix_context.py has no forbidden imports (services/, kafka_utils, src.config)

### Human Verification Required

#### 1. VIX fields non-None in live intelligence_features

**Test:** With services running and VIX contract active, query:
```sql
SELECT i6->>'ctf_vix_level', i6->>'ctf_vix_z'
FROM intelligence_features
WHERE symbol = 'ES' AND feature_tf = '1m'
ORDER BY ts DESC LIMIT 5;
```
**Expected:** Both columns return float values (not null) once VIX bar_history has accumulated >= 20 bars (1m bars — ready within 20 minutes of service start).
**Why human:** Requires live FeaturePipelineService with VIX contract in active contracts and cross_asset_enabled=False check — VIX injection is unconditional (not gated by cross_asset_enabled), so should work regardless.

#### 2. EQ_INDEX vs non-EQ_INDEX field population

**Test:** With cross_asset_enabled=True in settings, query:
```sql
-- Should have non-null ctf_eq_spread_z for ES (EQ_INDEX)
SELECT i6->>'ctf_eq_spread_z', i6->>'ctf_eq_pairs_confirming'
FROM intelligence_features WHERE symbol = 'ES' AND feature_tf = '1m'
ORDER BY ts DESC LIMIT 5;

-- Should have null ctf_eq_spread_z for GC (non-EQ_INDEX)
SELECT i6->>'ctf_eq_spread_z', i6->>'ctf_eq_pairs_confirming'
FROM intelligence_features WHERE symbol = 'GC' AND feature_tf = '1m'
ORDER BY ts DESC LIMIT 5;
```
**Expected:** ES shows float values for both fields; GC shows null for both fields.
**Why human:** Requires cross_asset_enabled=True and cross_asset service publishing to topic; currently cross_asset_enabled defaults to False in settings.

#### 3. ctf_score distribution unchanged

**Test:** Compare pre- and post-deploy ctf_score statistics:
```sql
SELECT avg(i6->>'ctf_score'::float), stddev(i6->>'ctf_score'::float)
FROM intelligence_features
WHERE ts > NOW() - INTERVAL '24 hours';
```
**Expected:** Mean and stddev consistent with pre-Phase 46 baseline — new fields are independent, formula unchanged.
**Why human:** Requires sufficient post-deploy data accumulation; code inspection confirms formula unchanged (W_TREND/W_STRUCTURE/W_REGIME/W_PATTERN/W_I2 constants verified unchanged).

### Gaps Summary

No automated gaps found. All 8 commits verified in git log. All 42 unit tests pass. All key links confirmed wired. All 3 CONF requirements satisfied. The 3 human verification items are runtime/data questions that cannot be verified programmatically — they do not block the code correctness determination.

---

_Verified: 2026-03-22T06:10:00Z_
_Verifier: Claude (gsd-verifier)_
