# GSD Debug Knowledge Base

Resolved debug sessions. Used by `gsd-debugger` to surface known-pattern hypotheses at the start of new investigations.

---

## underflow-7symbol-real-column — feature_vectors write underflow on real-typed columns (BIL/VRP/ENPH/GLD/NAD/SHY/STIP)
- **Date:** 2026-09-23
- **Error patterns:** value out of range: underflow, real column, float4, Postgres underflow, executemany batch abort, feature_vectors, HMM posterior probability, hmm_entropy, zone_friction_score, freshness_decay, exp underflow, backfill_feature_factory, FeatureVectorWriter
- **Root cause:** feature_vector_to_insert_params() (src/intelligence/features/feature_vector_persistence.py), the single shared row-serializer for both feature_vectors write paths (live asyncpg FeatureVectorWriter and batch psycopg backfill_feature_factory), never clamped a real-typed float to what Postgres's real (float4) column type can represent. Two distinct feature families can legitimately produce a value smaller in magnitude than float4's smallest subnormal (~1.4e-45): (1) HMM posterior-probability/entropy columns for low-variance/highly-confident-regime instruments, and (2) unrounded exp(-k*touch_count) zone-freshness-decay computations (src/intelligence/feature_factory.py) for near-zero-volatility instruments whose supply/demand zones get retested far more than normal before invalidating. Either mechanism triggers Postgres's "value out of range: underflow", aborting the whole executemany() batch containing that row and permanently stalling that symbol/tf's backfill at whatever row it reached.
- **Fix:** Promoted the existing todo-312 clamp helper (previously private in services/_batch_utils.py, used only by bulk_update_by_key for a different table/write primitive) to a new Ring 0 module, src/core/real_column_range.py (clamp_to_real_range() + REAL_MIN_MAGNITUDE/REAL_MAX_MAGNITUDE from np.finfo(np.float32)), importable by both Ring 2 services and Ring 1 domain code without violating the Ring import rule. feature_vector_to_insert_params() now maps clamp_to_real_range() over every element of its return tuple -- deliberately column-agnostic (not a hardcoded HMM/SMC column list) so it covers any current or future underflow-prone column, fixing both write paths in the one function they already share.
- **Files changed:** src/core/real_column_range.py (new), services/_batch_utils.py, src/intelligence/features/feature_vector_persistence.py, tests/unit/test_feature_vector_persistence_completeness.py
---
