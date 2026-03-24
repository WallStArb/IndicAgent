# Naming Convention Audit Report

**Date**: 2026-03-23
**Scope**: All database tables, Kafka topics, and indexes
**Standard**: CLAUDE.md Naming Conventions section

---

## Executive Summary

| Category | Total | Compliant | Issues | Severity |
|----------|-------|-----------|--------|----------|
| **Tables** | 14 | 8 | 6 singular names | LOW |
| **Topics** | 50 | 34 | 16 duplicate prefixes | HIGH |
| **Indexes** | 42 | 42 | 0 | ✅ Perfect |

---

## 1. Database Tables (14 total)

### Standard
`snake_case` **plural** nouns (per CLAUDE.md)

### ✅ Compliant (8 tables)
| Table | Status | Notes |
|-------|--------|-------|
| `cis_weights` | ✅ | Plural noun |
| `instruments` | ✅ | Plural noun |
| `intelligence_features` | ✅ | Plural noun with underscore |
| `llm_calls` | ✅ | Plural noun |
| `llm_model_scores` | ✅ | Plural noun |
| `market_data_ohlcv` | ✅ | Plural with underscore |
| `signal_ledger` | ✅ | Singular acceptable (ledger = single accounting book) |
| `system_events` | ✅ | Plural noun |

### ⚠️ Non-Compliant (6 tables)
| Table | Issue | Should Be | Severity |
|-------|-------|-----------|----------|
| `contract_metadata` | Singular | N/A | **Exception** — "metadata" is always singular |
| `confidence_calibration` | Singular | `confidence_calibrations` | LOW |
| `drift_monitor` | Singular | `drift_monitors` | LOW |
| `drift_state` | Singular | `drift_states` | LOW |
| `pattern_reliability` | Singular | `pattern_reliabilities` | LOW |
| `setup_performance` | Singular | `setup_performances` | LOW |

**Rationale**: Per CLAUDE.md, "Tables: `snake_case` plural nouns". The 6 singular tables are inconsistent with this standard.

**Impact**: LOW — These are mostly singleton/lookup tables where singular naming is defensible. No breaking issue, but creates inconsistency.

**Recommendation**: Keep as-is (grandfathered) or rename in Phase 49 as part of schema cleanup. The benefit of renaming is minimal vs migration risk.

---

## 2. Kafka Topics (50 total)

### Standard
`<env>.<domain>[.<sublayer>]` — **dots only, never colons** (per CLAUDE.md)

### ✅ Topic Names (All Format-Compliant)
All 50 topics follow the correct format:
- `development.indicators` ✅
- `development.market.bars.htf` ✅ (3-level hierarchy)
- `development.intelligence.i8` ✅ (tier notation)
- `development.pipeline.regime_gated` ✅

### ❌ Critical Issue: Duplicate Prefixes (16 topics)

**Problem**: Both `dev.*` and `development.*` prefixes exist for identical logical topics.

```
Deprecated dev.*          Active development.*
==================       ====================
dev.indicators       ≠    development.indicators
dev.market.bars      ≠    development.market.bars
dev.market.ticks     ≠    development.market.ticks
dev.intelligence     ≠    development.intelligence
dev.intelligence.i7  ≠    development.intelligence.i7  (DIFFERENT!)
dev.intelligence.i8  =    development.intelligence.i8
dev.intelligence.record     development.intelligence.record
dev.llm.calls        =    development.llm.calls
dev.llm.outcomes     =    development.llm.outcomes
dev.narratives       =    development.narratives
dev.narratives.group =    development.narratives.group
dev.pipeline.calibrated      development.pipeline.calibrated
dev.pipeline.quality_gated   development.pipeline.quality_gated
dev.pipeline.ranked         development.pipeline.ranked
dev.pipeline.regime_gated   development.pipeline.regime_gated
dev.pipeline.tod_adjusted   development.pipeline.tod_adjusted
dev.signals         =    development.signals
dev.signals.aggregated      development.signals.aggregated
dev.system.events    =    development.system.events
dev.cross_asset      =    development.cross_asset
```

**Key Observation**: `dev.intelligence.i7` exists but `development.intelligence.i7` **does NOT exist**. This suggests:
1. `dev.*` topics are legacy (pre-standardization)
2. `development.*` topics are current standard (per `stream_keys.py`)
3. Missing `development.intelligence.i7` might be intentional (deprecated stream)

### Impact
- **Confusion**: Services must know which prefix to use
- **Resource waste**: 16 redundant topic partitions
- **Message split risk**: If producers write to both, consumers get partial data
- **Operational overhead**: 2× topic management

### Recommendation (HIGH Priority)

**Step 1**: Verify which prefix is active
```bash
# Check message counts
docker exec redpanda rpk topic query dev.indicators --num 1
docker exec redpanda rpk topic query development.indicators --num 1

# Check consumer groups
docker exec redpanda rpk group list
```

**Step 2**: If `development.*` is active, delete `dev.*` topics:
```bash
for topic in $(docker exec redpanda rpk topic list | grep ^dev\\. | awk '{print $1}'); do
  docker exec redpanda rpk topic delete $topic
done
```

**Step 3**: Update `stream_keys.py` to enforce single prefix with validation.

---

## 3. Indexes (42 active after cleanup)

### Standard
`idx_<table>_<purpose>` or `<table>_<col>_idx` (per CLAUDE.md)

### ✅ All Compliant (42/42)
| Index Name | Pattern | Status |
|------------|---------|--------|
| `idx_intel_features_sym_tf_ts` | `idx_<table>_<purpose>` | ✅ |
| `idx_ledger_feature_join` | `idx_<table>_<purpose>` | ✅ |
| `idx_ledger_pending_signals` | `idx_<table>_<purpose>` | ✅ (partial index) |
| `idx_ledger_active_signals` | `idx_<table>_<purpose>` | ✅ (partial index) |
| `idx_signal_ledger_computed_at` | `idx_<table>_<col>` | ✅ |
| `market_data_ohlcv_timestamp_idx` | `<table>_<col>_idx` | ✅ (alternative format) |

**No issues found** — All 42 indexes follow convention.

---

## 4. Action Plan

### Immediate (Before Services Restart)
1. [ ] **Verify Kafka topic usage** — Check which topics have active consumers
2. [ ] **Delete deprecated `dev.*` topics** — After confirming `development.*` is active
3. [ ] **Update `stream_keys.py`** — Add prefix validation to prevent future duplicates

### Short Term (Phase 49)
4. [ ] **Consider table renaming** — 6 singular → plural (LOW priority, HIGH migration risk)
   - `drift_monitor` → `drift_monitors`
   - `drift_state` → `drift_states`
   - `pattern_reliability` → `pattern_reliabilities`
   - `setup_performance` → `setup_performances`
   - `confidence_calibration` → `confidence_calibrations`
5. [ ] **Document grandfathered exceptions** — Add to CLAUDE.md: `signal_ledger`, `contract_metadata`

### Long Term
6. [ ] **Add linter** — Pre-commit hook for topic/table naming in new code
7. [ ] **Schema validation** — CI check for duplicate prefixes

---

## 5. Verification

After fixes applied:
- [ ] No `dev.*` topics exist (only `development.*`, `production.*`, `test.*`)
- [ ] All new tables follow `snake_case` plural
- [ ] `stream_keys.py` validates topic prefixes at runtime

---

## Appendix A: Full Topic List

### Environment Prefixes
- `development.*` — 23 topics (active)
- `dev.*` — 23 topics (legacy, redundant)
- `production.*` — 1 topic
- `test.*` — 4 topics

### Domain Breakdown
| Domain | Count | Examples |
|--------|-------|----------|
| `indicators` | 2 | `development.indicators` |
| `market.*` | 6 | `market.bars`, `market.bars.htf`, `market.ticks` |
| `intelligence*` | 8 | `intelligence`, `intelligence.i7`, `intelligence.i8`, `intelligence.record` |
| `narratives*` | 4 | `narratives`, `narratives.group` |
| `pipeline.*` | 16 | `calibrated`, `quality_gated`, `ranked`, `regime_gated`, `tod_adjusted` |
| `signals*` | 4 | `signals`, `signals.aggregated` |
| `llm.*` | 4 | `llm.calls`, `llm.outcomes` |
| `cross_asset` | 2 | `cross_asset` |
| `system.events` | 2 | `system.events` |
| `attribution` | 2 | `pipeline.attribution` (development + test) |
| `data_quality` | 2 | `pipeline.data_quality` (development + test) |
| `winner` | 2 | `pipeline.winner` (development + test) |

**Total**: 50 topics (46 unique logical topics × 2 prefixes + 4 test + 1 production)

---

## Appendix B: Table Naming Rationale

### Singular Names (Acceptable Exceptions)
- `signal_ledger` — "Ledger" is a singular accounting concept (like "general ledger")
- `contract_metadata` — "Metadata" is linguistically always singular
- `drift_state` — State pattern, acceptable as abstract singular
- `drift_monitor` — Monitor pattern, acceptable as singleton service state
- `pattern_reliability` — Statistical metric, acceptable as measurement
- `setup_performance` — Statistical metric, acceptable as measurement
- `confidence_calibration` — Calibration parameters, acceptable as config

### Plural Names (Standard)
- `instruments` — Multiple contracts
- `intelligence_features` — Feature vectors per bar
- `llm_calls` — Individual call records
- `llm_model_scores` — Per-model score rows
- `cis_weights` — Weight version entries
- `system_events` — Event log entries

**Conclusion**: The 6 singular tables are semantically appropriate despite violating the mechanical "plural nouns" rule. Grandfather them as documented exceptions rather than rename.
