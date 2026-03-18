---
phase: 31-cis-learning-loop-signal-feature-snapshots
verified: 2026-03-17T01:40:50Z
status: passed
score: 13/13 must-haves verified
re_verification: false
---

# Phase 31: CIS Learning Loop + Signal Feature Snapshots Verification Report

**Phase Goal:** The CIS scorer self-improves — loading learned weights from DB at runtime, training on binary win/loss labels, segmenting by asset cluster and timeframe, and capturing mid-bar feature snapshots for every new signal as the ML training dataset foundation.
**Verified:** 2026-03-17T01:40:50Z
**Status:** PASSED
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| #  | Truth                                                                                    | Status     | Evidence                                                                 |
|----|------------------------------------------------------------------------------------------|------------|--------------------------------------------------------------------------|
| 1  | CISScorer accepts runtime weight updates without recreating the instance                | VERIFIED   | `update_weights()` method exists at cis_scorer.py:100; mutates `_weights`, `_weights_version`, `_weights_array` in place |
| 2  | Signal generator loads CIS weights from DB at startup and every 30 minutes              | VERIFIED   | `_load_cis_weights_from_db()` called at startup (line 1470) and in `_cis_weights_refresh_loop` (line 1451); task registered at line 1477 |
| 3  | When DB has learned weights with sample_size >= 100, CISScorer uses them                | VERIFIED   | SQL at line 1398: `WHERE sample_size >= 100`; `update_weights()` called at line 1431 |
| 4  | When DB unavailable or sample_size < 100, CISScorer falls back to BOOTSTRAP_WEIGHTS     | VERIFIED   | `_load_cis_weights_from_db` returns early on None db_manager; logs "using bootstrap" on empty result |
| 5  | cis_weights table has asset_cluster column with unique index on (asset_cluster, timeframe, version) | VERIFIED | Live DB confirmed: `asset_cluster` column present; migration 034 section 1 creates `idx_cis_weights_cluster_tf_version` |
| 6  | Weight updater trains on binary outcome labels (WIN_OUTCOMES = win, everything else = loss) | VERIFIED | `WIN_OUTCOMES` frozenset at weight_updater.py:44; `y = np.array([1.0 if ... in WIN_OUTCOMES else 0.0])` at line 152 |
| 7  | Weight updater trains separate models per (asset_cluster, timeframe) when N >= 100      | VERIFIED   | Cluster grouping loop at weight_updater.py:283–297; skips cluster when `len(group_rows) < MIN_SAMPLES_FULL` |
| 8  | Weight updater filters out is_shadow=TRUE signals from training data                    | VERIFIED   | SQL at weight_updater.py:265: `AND is_shadow = FALSE` |
| 9  | Weight updater writes asset_cluster and timeframe to cis_weights rows                   | VERIFIED   | `_write_weights_to_db()` INSERT at line 220 includes `asset_cluster` column |
| 10 | Every new signal_ledger row has matching signal_features rows (atomic write)            | VERIFIED   | `_write_signal_with_features()` wraps both writes in `conn.transaction()` at service line 1340 |
| 11 | LedgerEntry has is_shadow field; to_insert_params returns 39 elements                  | VERIFIED   | `is_shadow: bool = False` at signal_ledger.py:80; docstring "39-element tuple" at line 83; `self.is_shadow` at line 127 |
| 12 | signal_features hypertable exists with 7-day chunks for ML training data               | VERIFIED   | Live DB confirmed; migration 034 section 2 creates hypertable with `INTERVAL '7 days'` |
| 13 | CLI promotion gate exits 0 only when p < 0.05 AND N >= 200 per variant                 | VERIFIED   | `promote_shadow.py`: `MIN_SAMPLES = 200`; `alternative="larger"` one-sided z-test; `if p_value >= 0.05: return 1` |

**Score:** 13/13 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `production/migrations/034_cis_learning_loop.sql` | Schema foundation for Phase 31 | VERIFIED | All three sections present: cis_weights cluster extension, signal_features hypertable (7-day chunks), signal_ledger is_shadow; idempotent; no CONCURRENTLY |
| `src/intelligence/trading/cis_scorer.py` | `update_weights()` method | VERIFIED | Method at line 100; updates `_weights`, `_weights_version`, `_weights_array` |
| `services/signal_generator_service.py` | 30-min CIS weight refresh loop | VERIFIED | `_cis_weights_refresh_loop` at line 1437; `_REFRESH_INTERVAL = 1800`; startup call at line 1470; task registered at line 1477 |
| `src/intelligence/weight_updater.py` | Binary labels + cluster segmentation | VERIFIED | `WIN_OUTCOMES` frozenset, `ASSET_CLUSTER_MAP` (21 symbols, 5 clusters), `get_asset_cluster()`, `compute_new_weights()` with binary target, `_write_weights_to_db()`, `run_weight_update()` with per-cluster training |
| `src/intelligence/trading/signal_ledger.py` | LedgerEntry.is_shadow + _build_feature_rows | VERIFIED | `is_shadow: bool = False`; 39-param `to_insert_params()`; `_INSERT_SQL` with `$39`; `FEATURE_BUCKET_MAP` (34 mappings); `_build_feature_rows()`; `_INSERT_FEATURES_SQL` with `ON CONFLICT DO NOTHING` |
| `production/scripts/promote_shadow.py` | Statistical promotion gate CLI | VERIFIED | `proportions_ztest` from statsmodels (scipy 1.17+ compatible); `MIN_SAMPLES = 200`; one-sided test; exits 0 on PROMOTED, 1 on REJECTED |
| `tests/unit/intelligence/test_cis_scorer.py` | 3 update_weights tests | VERIFIED | `test_update_weights_changes_weights_and_version`, `test_update_weights_recomputes_array`, `test_score_uses_updated_weights` — all pass |
| `tests/unit/service_tests/test_signal_generator_weights.py` | 3 CIS DB weight tests | VERIFIED | `test_load_cis_weights_updates_scorer`, `test_load_cis_weights_no_learned_keeps_bootstrap`, `test_load_cis_weights_db_error_keeps_current` — all pass |
| `tests/unit/intelligence/test_weight_updater.py` | 38 weight updater tests | VERIFIED | All 38 pass: binary labels, cluster map, shadow filter, cluster training thresholds, version counter |
| `tests/unit/intelligence/test_signal_ledger.py` | is_shadow + _build_feature_rows tests | VERIFIED | 41 tests pass including `test_to_insert_params_length_39`, `test_build_feature_rows_*` |
| `tests/unit/service_tests/test_signal_generator_features.py` | Atomic write tests | VERIFIED | 7 tests pass including `test_write_signal_with_features_atomic` |
| `tests/unit/scripts/test_promote_shadow.py` | Promotion gate tests | VERIFIED | 6 tests pass including `test_rejects_insufficient_samples_shadow`, `test_promotes_significant_improvement` |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `services/signal_generator_service.py` | `src/intelligence/trading/cis_scorer.py` | `update_weights()` call from `_load_cis_weights_from_db()` | WIRED | Line 1431: `self._cis_scorer.update_weights(w, v)` |
| `services/signal_generator_service.py` | `src/core/database_manager.py` | `execute_query` for SELECT from cis_weights | WIRED | Line 1393: `await self.db_manager.execute_query("""SELECT DISTINCT ON...`)` |
| `src/intelligence/weight_updater.py` | `src/core/database_manager.py` | `run_weight_update` queries signal_ledger with outcome filter | WIRED | Line 260: query with `outcome IS NOT NULL AND is_shadow = FALSE` |
| `src/intelligence/weight_updater.py` | `production/migrations/034_cis_learning_loop.sql` | writes to cis_weights with asset_cluster column | WIRED | `_write_weights_to_db()` INSERT at line 220 includes `asset_cluster` |
| `services/signal_generator_service.py` | `src/intelligence/trading/signal_ledger.py` | `_write_signal_with_features` calls `to_insert_params` | WIRED | Line 1082 calls `_write_signal_with_features`; method uses `entry.to_insert_params()` at line 1338 |
| `services/signal_generator_service.py` | `src/core/database_manager.py` | `conn.transaction()` for atomic write | WIRED | Line 1340: `async with conn.transaction():` |
| `production/scripts/promote_shadow.py` | `src/core/database_manager.py` | queries signal_ledger for matched pairs | WIRED | Line 97: `conn.fetch("""SELECT outcome, is_shadow FROM signal_ledger...`)` |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| LEARN-01 | 031-01 | CIS scorer loads learned weights from `cis_weights` DB at runtime; refreshes every 30 min; falls back to bootstrap when `sample_size < 100` or DB unavailable | SATISFIED | `_cis_weights_refresh_loop` + `_load_cis_weights_from_db` + `CISScorer.update_weights()`; bootstrap fallback when empty result |
| LEARN-02 | 031-02 | Weight updater trains on binary win/loss labels; replaces `signal_quality` proxy target | SATISFIED | `WIN_OUTCOMES` frozenset; `y = np.array([1.0 if ... in WIN_OUTCOMES else 0.0])` |
| LEARN-03 | 031-01 | `cis_weights` extended with `asset_cluster` + `timeframe`; five clusters defined | SATISFIED | Migration 034 adds `asset_cluster TEXT NOT NULL DEFAULT 'global'`; new unique index confirmed in live DB |
| LEARN-04 | 031-02 | Weight learner trains per `(asset_cluster, timeframe)` when N >= 100; falls back to global when sparse | SATISFIED | Cluster grouping loop in `run_weight_update()`; `if len(group_rows) < MIN_SAMPLES_FULL: continue` |
| FEAT-01 | 031-03 | `signal_features` hypertable captures raw feature values at signal fire time | SATISFIED | `_build_feature_rows()` called with mid-bar features at signal evaluation time; hypertable confirmed in live DB |
| FEAT-02 | 031-03 | `signal_features` write committed atomically with `signal_ledger` in `signal_generator_service` | SATISFIED | `_write_signal_with_features()` wraps both in `async with conn.transaction()` |
| SHAD-01 | 031-03 | `is_shadow BOOLEAN NOT NULL DEFAULT FALSE` added to `signal_ledger` | SATISFIED | `is_shadow` column confirmed in live DB; `LedgerEntry.is_shadow` field at signal_ledger.py:80 |
| SHAD-02 | 031-03 | CLI promotion gate: two-sample proportion z-test, p < 0.05 AND N >= 200 required | SATISFIED | `promote_shadow.py` with statsmodels `proportions_ztest`; `MIN_SAMPLES = 200`; one-sided test; 6 unit tests pass |

No orphaned requirements — all 8 IDs (LEARN-01 through LEARN-04, FEAT-01, FEAT-02, SHAD-01, SHAD-02) are claimed by plans 031-01, 031-02, 031-03 and confirmed implemented.

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `services/signal_generator_service.py` | 57 | `insert_signals` imported but never called (dead import) | Info | No functional impact; old write path fully replaced by `_write_signal_with_features` at line 1082 |

No blocker or warning anti-patterns found in Phase 31 files. The dead import of `insert_signals` is cosmetic only.

---

### Human Verification Required

**1. Live DB weight reload cycle**

**Test:** Restart `indicagent-signal-generator` service and inspect the log file at `logs/signal_generator.log` for the startup weight load message.
**Expected:** Log entry: `"No learned CIS weights with sample_size >= 100 — using bootstrap"` (since cis_weights is fresh post-migration) or `"Loaded weights from DB"` if weights exist.
**Why human:** Requires live service inspection; cannot verify log output programmatically in this context.

**2. Atomic write integration on live signal fire**

**Test:** Wait for a live signal to fire (or replay historical bars), then query: `SELECT COUNT(*) FROM signal_features WHERE signal_id = '<new_signal_id>';`
**Expected:** Non-zero row count — feature rows exist for the signal.
**Why human:** Requires live market data flow; cannot run end-to-end atomicity verification statically.

---

### Gaps Summary

No gaps. All 13 observable truths verified. All 8 requirement IDs satisfied. All key links wired. Test suites pass (1901/1905 unit tests pass; 4 pre-existing failures in `test_historical_backfill.py`, `test_signals_route.py`, `test_settings.py` are unrelated to Phase 31 — no Phase 31 commits touched those files).

---

_Verified: 2026-03-17T01:40:50Z_
_Verifier: Claude (gsd-verifier)_
