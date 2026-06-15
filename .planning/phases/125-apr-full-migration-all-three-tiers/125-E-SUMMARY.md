---
plan: "05"
phase: 125-apr-full-migration-all-three-tiers
status: complete
completed_at: 2026-06-15
---

## Summary

Plan 05 completes the APR full migration by wiring CIS gate constants to ConfigService in `cis_scorer.py`, extending `intelligence_pipeline.py` to prewarm all 10 migration-132 keys, and closing TODO 025.

## Tasks Completed

### Task 1: Add set_config_service + APR reads to cis_scorer.py
- Added module-level `_cfg` singleton and `set_config_service()` following the `confidence_utils.py` pattern
- `CISScorer.score()` now reads `threshold.cis.fire_threshold`, `threshold.cis.bucket_agree_min`, and `threshold.cis.bucket_noise_floor` from APR at runtime
- Hardcoded constants retained as fallbacks (`CIS_FIRE_THRESHOLD=0.35`, `BUCKET_AGREE_MIN=3`, `BUCKET_NOISE_FLOOR=2`)

### Task 2: Extend intelligence_pipeline _THRESHOLD_KEYS
- Added all 10 migration 132 keys to `_THRESHOLD_KEYS` in `IntelligencePipeline`
- Covers CIS gate constants (3 keys), zone width gates (4 keys), and VWAP reversion weights (3 keys)
- `_prewarm_threshold_config()` now injects `set_config_service()` into `cis_scorer` module alongside `confidence_utils`

### Task 3: Close TODO 025
- Moved `025-parameter-store-full-plugin-migration.md` from `pending/` to `done/`
- Verified: no hardcoded migration literals remain outside fallback definitions in `src/intelligence/trading/`

## Self-Check: PASSED

- `set_config_service` wired in `cis_scorer.py` - confirmed
- All 10 migration 132 keys in `_THRESHOLD_KEYS` - confirmed
- `cis_scorer` injected in prewarm alongside `confidence_utils` - confirmed
- TODO 025 in `done/` directory - confirmed
- `CIS_FIRE_THRESHOLD/BUCKET_AGREE_MIN/BUCKET_NOISE_FLOOR` literals exist only as fallbacks in `cis_scorer.py` - confirmed

## Key Files

- `src/intelligence/trading/cis_scorer.py` - set_config_service + APR gate reads
- `services/intelligence_pipeline.py` - 10 new _THRESHOLD_KEYS entries + cis_scorer injection
- `.planning/todos/done/025-parameter-store-full-plugin-migration.md` - closed
