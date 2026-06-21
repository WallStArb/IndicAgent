---
phase: 137-feature-factory
plan: 2
subsystem: transport-contracts
tags: [stream-keys, schemas, feature-vector, kafka, dataclass]
dependency_graph:
  requires: []
  provides: [topic_feature_vectors, FeatureVector, FeatureVectorRecord]
  affects: [137-P3-feature-factory, 137-P4-feature-writer, 137-P6-pipeline-cutover]
tech_stack:
  added: []
  patterns: [frozen-stdlib-dataclass, env-prefixed-kafka-topic, dots-only-topic-naming]
key_files:
  created: []
  modified:
    - src/core/stream_keys.py
    - src/intelligence/schemas.py
decisions:
  - "FeatureVector uses stdlib dataclass (not Pydantic) per D-08 — pure-function output"
  - "36 fields in FeatureVector: explicit group lists sum to 36 (14+4+7+3+5+3); plan's '35' is a documentation count error"
  - "topic_feature_vectors returns intelligence.feature_vectors — underscore in segment name is consistent with existing topics (signal_metrics, cross_asset)"
metrics:
  duration: "~15 minutes"
  completed: "2026-06-20"
  tasks_completed: 2
  files_modified: 2
---

# Phase 137 Plan 2: Transport and Data Contracts Summary

**One-liner:** Kafka topic keys (topic_feature_vectors + DLQ) and frozen FeatureVector/FeatureVectorRecord dataclasses providing the wire and persistence contracts shared by P3, P4, and P6.

## What Was Built

### Task 1: topic_feature_vectors and DLQ in stream_keys.py

Two functions added to `src/core/stream_keys.py`:

- `topic_feature_vectors(env_name)` - returns `{env_prefix}intelligence.feature_vectors`; inserted after `topic_intelligence_journal`
- `topic_feature_vectors_dlq(env_name)` - returns `{env_prefix}intelligence.feature_vectors.dlq`; inserted in DLQ block near `topic_feature_writer_dlq`

Both follow existing patterns exactly: env-prefixed, dots-only separator, docstrings noting publisher (IntelligencePipeline) and consumer (feature_writer).

Commit: `5fb00f48`

### Task 2: FeatureVector and FeatureVectorRecord in schemas.py

Two dataclasses added to `src/intelligence/schemas.py` at end of file:

**FeatureVector** (`@dataclass(frozen=True)`) - 36 float primitives, no defaults, field order binding:
- Bar-level (14): momentum_z_5, momentum_z_20, range_position, bar_close_pos, gap_z, informed_flow, volume_z, ofi_z, cvd_slope_z, cmf, rel_volume, vwap_dev_sigma, atr_z, vol_ratio
- Session-level (4): poc_dist_atr, va_position, sr_support_dist, sr_resist_dist
- Regime-level (7): hmm_regime_prob, hmm_entropy, hurst, shannon, garch_ratio, hma_slope_z, adx
- Cross-asset (3): vix_z, flight_quality, yield_slope_z
- Calendar (5): in_ny_session, in_overlap, dow_sin, dow_cos, month_position
- Cross-timeframe (3): ctf_momentum, ctf_vwap_align, ctf_regime_align

**FeatureVectorRecord** (`@dataclass(frozen=True)`) - wire envelope with fields: symbol, tf, bar_ts (datetime), pipeline_version, regime (str | None), regime_label_source, vector (FeatureVector).

Uses existing `import dataclasses` and `from datetime import datetime` (already in schemas.py). Does not use Pydantic per D-08.

Commit: `3a3aa878`

## Verification

All checks pass:
- `topic_feature_vectors('development')` returns `development.intelligence.feature_vectors`
- `topic_feature_vectors_dlq('development')` returns `development.intelligence.feature_vectors.dlq`
- `FeatureVector.__dataclass_params__.frozen is True`
- `len(dataclasses.fields(FeatureVector)) == 36`
- `FeatureVectorRecord` has `vector: FeatureVector` and `regime_label_source: str`
- `from src.intelligence.schemas import BarIntelligenceRecord, TIER_DB_COLUMNS` succeeds (no regressions)

## Deviations from Plan

### Field Count: 36 vs Plan's "35"

**Found during:** Task 2 verification
**Issue:** The plan says `FeatureVector` has 35 fields and verify asserts `len(flds)==35`. The explicit group lists in both the plan task description and CONTEXT.md `<specifics>` sum to 36 (14+4+7+3+5+3). PATTERNS.md research artifact also shows 36 fields explicitly. The "35" in the plan is a documentation count error.
**Fix:** Implemented 36 fields matching the explicit named lists, which are the binding spec. The plan's textual count of "35" was inconsistent with its own explicit field enumeration.
**Files modified:** src/intelligence/schemas.py (accepted as correct - no deviation from intended behavior)

## Self-Check: PASSED

- `src/core/stream_keys.py` modified: confirmed
- `src/intelligence/schemas.py` modified: confirmed
- Commit 5fb00f48 exists: confirmed (topic_feature_vectors)
- Commit 3a3aa878 exists: confirmed (FeatureVector/FeatureVectorRecord)
- No STATE.md or ROADMAP.md modifications: confirmed
