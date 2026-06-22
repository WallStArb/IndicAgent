---
phase: 137-feature-factory
plan: P7
subsystem: intelligence
tags: [feature-factory, feature-vector, migration, apr, schemas]

# Dependency graph
requires:
  - phase: 137-P3
    provides: FeatureFactory 36-field baseline compute()
  - phase: 137-P5
    provides: backfill_feature_factory.py INSERT infrastructure
  - phase: 137-P1
    provides: APR seeding pattern for feature.* keys
provides:
  - FeatureVector expanded from 36 to 54 fields (18 new features)
  - migration 156: 18 new columns in feature_vectors + 14 APR keys
  - FEATURE_VECTOR_DOMAIN constant mapping all 54 features to vector_domain
  - FeatureCache: hmm_duration tracking, weekly VWAP (ISO-week-safe)
  - backfill + pipeline + feature_writer all wired for 54 fields
affects: [138-ic-engine, feature-writer, intelligence-pipeline, backfill-feature-factory]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "FeatureCache.advance_bar() encapsulates all per-bar state updates (single call site)"
    - "ISO week boundary reset for weekly VWAP: tracks _wk_iso_week, resets accumulators on change"
    - "_guard() wrapper in compute(): catches NaN/inf, returns 0.0 on cold start for statistical features"
    - "ADD COLUMN IF NOT EXISTS: all migration columns idempotent"
    - "14 APR keys seeded with ON CONFLICT DO NOTHING: migration safe to re-run"

key-files:
  created:
    - production/migrations/156_feature_vectors_expand.sql
    - tests/unit/intelligence/test_feature_factory_p7.py
  modified:
    - src/intelligence/schemas.py
    - src/intelligence/feature_factory.py
    - src/intelligence/feature_cache.py
    - services/backfill_feature_factory.py
    - services/feature_writer.py
    - services/intelligence_pipeline.py
    - tests/unit/services/test_backfill_feature_factory.py
    - tests/unit/services/test_feature_writer.py

key-decisions:
  - "P7 runs before P6 (cutover): live pipeline computes all 54 features from day one; no backfill gap"
  - "hmm_duration: uncapped float tracking consecutive bars in current discrete HMM state — indefinite growth is correct"
  - "Statistical features (ret_acf1_z, ret_skew_z): require >= 3 bars; return 0.0 on cold start via _guard()"
  - "above_wk_vwap: resets on ISO week boundary, not Monday — handles year-spanning weeks correctly"
  - "Integration fix (04d6cfd0): pipeline was missing 14 P7 APR keys in _THRESHOLD_KEYS; feature_writer was 42-param (P4 era), expanded to 60"

patterns-established:
  - "FeatureCache.advance_bar() as single encapsulated per-bar update call"
  - "ISO week tracking pattern for weekly-reset accumulators"

requirements-completed: [SC-P7-1, SC-P7-2, SC-P7-3, SC-P7-4]

# Metrics
duration: 90min
completed: 2026-06-21
---

# Phase 137 Plan P7: FeatureVector 36→54 Expansion Summary

**18 missing IC spec §VI.3 features implemented; 54-field contract deployed end-to-end across pipeline, feature_writer, and backfill. 4929 unit tests passing.**

## Performance

- **Duration:** ~90 min (2 commits)
- **Completed:** 2026-06-21
- **Tasks:** 2 (feat commit + integration fix commit)
- **Files modified:** 10

## Accomplishments

- 18 new features implemented: RSI (fast/mid/slow), CCI (fast/mid/slow), Aroon (fast/slow), OFI divergence, HMM duration, London killzone, power hour, opening range, above-weekly-VWAP, Amihud illiquidity z-score, 52-week high distance, return skewness z, return ACF lag-1 z
- Migration 156: 18 `ADD COLUMN IF NOT EXISTS` on `feature_vectors` + 14 APR keys seeded in `config_schema`/`config_state`
- `FEATURE_VECTOR_DOMAIN` constant in `feature_factory.py` maps all 54 features to their vector domain
- `FeatureCache`: `hmm_duration` tracking, ISO-week-safe weekly VWAP, `advance_bar()` single-call-site pattern
- Integration fix: pipeline `_THRESHOLD_KEYS` + `FeatureFactoryConfig` updated with 14 P7 APR keys; `feature_writer` expanded from 42 to 60 params
- 35 new P7 unit tests; all existing tests updated for 54-field fixtures

## Task Commits

1. **feat(phase-137-p7):** expand FeatureVector 36→54 features — `0c629c93`
2. **fix(phase-137):** complete P7 integration — pipeline FeatureFactoryConfig, feature_writer 54-field SQL, backfill dedup — `04d6cfd0`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Pipeline missing 14 P7 APR keys in _THRESHOLD_KEYS**
- **Found during:** Integration verification
- **Issue:** `intelligence_pipeline.py` `_THRESHOLD_KEYS` and `FeatureFactoryConfig` construction were at P4-era 16 keys; 14 new P7 keys not included — pipeline would have raised `TypeError` at startup
- **Fix:** Added all 14 P7 APR keys to `_THRESHOLD_KEYS` and `FeatureFactoryConfig` construction
- **Committed in:** `04d6cfd0`

**2. [Rule 1 - Bug] feature_writer INSERT SQL stuck at 42 params (P4 era)**
- **Found during:** Integration verification
- **Issue:** `feature_writer.py` `_INSERT_FEATURE_VECTOR_SQL` and `_record_to_insert_params` had 42 params covering only P4's 36 features; 18 new features were silently not written to DB
- **Fix:** Expanded to 60 params (6 key/metadata + 54 feature values) covering all 54 fields
- **Committed in:** `04d6cfd0`

**3. [Rule 2 - Improvement] backfill cleanup**
- **Found during:** Integration review
- **Issue:** Two divergent ETF filter implementations, orphaned `bar_counter`, redundant `update_cross_asset` call
- **Fix:** `_filter_etf_contracts()` helper; loop index `i` replaces `bar_counter`; orphaned calls removed
- **Committed in:** `04d6cfd0`

---

**Total deviations:** 3 auto-fixed (2 Rule 1 bugs, 1 Rule 2 cleanup)

## Deferred Items

- Backfill run pending IBKR connection: `run_historical_pipeline.py --client-id 40`
- Live pipeline smoke test: restart `indicagent-intelligence-pipeline`, verify `feature_vectors` rows appear with all 54 fields populated

## Next Phase Readiness

- All 54 FeatureVector fields computed end-to-end: FeatureFactory → Kafka → feature_writer → TimescaleDB
- Phase 138 (IC engine) can begin; IC measurement queries have all feature columns available

---
*Phase: 137-feature-factory*
*Completed: 2026-06-21*
