---
phase: 137-feature-factory
plan: 2
type: execute
wave: 1
depends_on: []
files_modified:
  - src/core/stream_keys.py
  - src/intelligence/schemas.py
autonomous: true
requirements: [SC-2]

threat_model:
  assets:
    - "topic_feature_vectors Kafka topic key (sole transport contract between pipeline and writer)"
    - "FeatureVector / FeatureVectorRecord schema (the wire + persistence contract)"
  threats:
    - id: T1
      description: "Hardcoded topic string in pipeline or writer instead of stream_keys function - DAG Invariant 4 violation, silent topic mismatch between producer and consumer"
      severity: medium
      mitigation: "topic_feature_vectors added to stream_keys.py; downstream plans (P4, P6) import it; acceptance criterion asserts the function exists and returns env-prefixed dotted topic"
    - id: T2
      description: "FeatureVector field set drifts from the 35 locked primitives, producing writer INSERT param-count mismatch or silent column omission"
      severity: medium
      mitigation: "Acceptance criterion asserts FeatureVector has exactly 35 fields matching the binding column list; frozen dataclass with no defaults forces every field to be supplied"
  block_on: []

must_haves:
  truths:
    - "topic_feature_vectors(env) returns an env-prefixed dotted Kafka topic string"
    - "FeatureVector frozen dataclass has exactly 35 float fields matching the locked primitive names"
    - "FeatureVectorRecord carries symbol, tf, bar_ts, pipeline_version, regime, regime_label_source, and the FeatureVector"
  artifacts:
    - path: "src/core/stream_keys.py"
      provides: "topic_feature_vectors + topic_feature_vectors_dlq topic key functions"
      contains: "def topic_feature_vectors"
    - path: "src/intelligence/schemas.py"
      provides: "FeatureVector + FeatureVectorRecord dataclasses"
      contains: "class FeatureVector"
  key_links:
    - from: "src/intelligence/schemas.py FeatureVectorRecord"
      to: "src/intelligence/schemas.py FeatureVector"
      via: "vector field of type FeatureVector"
      pattern: "vector: FeatureVector"
---

<objective>
Add the transport and data contracts that every downstream Phase 137 component shares: the `topic_feature_vectors` Kafka topic key (and its DLQ), and the `FeatureVector` / `FeatureVectorRecord` dataclasses in `schemas.py`. These are pure additive scaffolding - no behavior change - so they can land in parallel with the schema/APR plan (P1).

Purpose: P3 (FeatureFactory) returns a `FeatureVector`; P4 (writer) deserializes a `FeatureVectorRecord` and reads the topic; P6 (pipeline) publishes to the topic. All three need these symbols to exist first.
Output: `topic_feature_vectors`/`topic_feature_vectors_dlq` in stream_keys; `FeatureVector` (35 frozen float fields) + `FeatureVectorRecord` (wire envelope) in schemas.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/137-feature-factory/137-CONTEXT.md
@.planning/phases/137-feature-factory/137-RESEARCH.md
@.planning/phases/137-feature-factory/A-PATTERNS.md
@CLAUDE.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add topic_feature_vectors and DLQ to stream_keys.py</name>
  <files>src/core/stream_keys.py</files>
  <read_first>
    - src/core/stream_keys.py (read env_prefix at line ~41, topic_intelligence_journal at line ~147 as the exact copy template, and the DLQ block around topic_feature_writer_dlq at line ~371)
    - .planning/phases/137-feature-factory/A-PATTERNS.md (section "src/core/stream_keys.py" - exact function bodies and insert locations)
  </read_first>
  <action>
    Add two module-level functions copying the structure of `topic_intelligence_journal`:
    `topic_feature_vectors(env_name: str) -> str` returning `f"{env_prefix(env_name)}intelligence.feature_vectors"`, inserted directly after `topic_intelligence_journal`.
    `topic_feature_vectors_dlq(env_name: str) -> str` returning `f"{env_prefix(env_name)}intelligence.feature_vectors.dlq"`, inserted in the DLQ block near `topic_feature_writer_dlq`.
    Topic uses dots only (DAG Invariant 4). Do not hardcode the env prefix - use env_prefix(env_name). Add docstrings noting publisher (IntelligencePipeline) and consumer (feature_writer).
  </action>
  <verify>
    .venv/bin/python -c "from src.core.stream_keys import topic_feature_vectors, topic_feature_vectors_dlq; print(topic_feature_vectors('development')); print(topic_feature_vectors_dlq('development'))"
  </verify>
  <acceptance_criteria>
    - `from src.core.stream_keys import topic_feature_vectors, topic_feature_vectors_dlq` succeeds
    - `topic_feature_vectors('development')` returns a string ending in `intelligence.feature_vectors`
    - `topic_feature_vectors_dlq('development')` returns a string ending in `intelligence.feature_vectors.dlq`
    - Returned topic strings contain no underscores in the dotted suffix (dots-only rule)
  </acceptance_criteria>
</task>

<task type="auto">
  <name>Task 2: Add FeatureVector and FeatureVectorRecord dataclasses to schemas.py</name>
  <files>src/intelligence/schemas.py</files>
  <read_first>
    - src/intelligence/schemas.py (read the import block lines 1-31 and the existing models; insert AFTER existing Pydantic models - do not disturb TIER_DB_COLUMNS, OHLCVBar, IntelligenceEvent, BarIntelligenceRecord)
    - .planning/phases/137-feature-factory/A-PATTERNS.md (section "src/intelligence/schemas.py" - exact FeatureVector and FeatureVectorRecord definitions)
    - .planning/phases/137-feature-factory/137-CONTEXT.md (`<specifics>` - the 35 primitive names grouped by cadence; field names must match exactly)
  </read_first>
  <action>
    Add a stdlib `@dataclass(frozen=True)` `FeatureVector` (NOT a Pydantic model, per D-08) with exactly 35 fields, all typed `float`, no defaults, named and ordered exactly: Bar-level (14): momentum_z_5, momentum_z_20, range_position, bar_close_pos, gap_z, informed_flow, volume_z, ofi_z, cvd_slope_z, cmf, rel_volume, vwap_dev_sigma, atr_z, vol_ratio. Session-level (4): poc_dist_atr, va_position, sr_support_dist, sr_resist_dist. Regime-level (7): hmm_regime_prob, hmm_entropy, hurst, shannon, garch_ratio, hma_slope_z, adx. Cross-asset (3): vix_z, flight_quality, yield_slope_z. Calendar (5): in_ny_session, in_overlap, dow_sin, dow_cos, month_position. Cross-timeframe (3): ctf_momentum, ctf_vwap_align, ctf_regime_align.

    Add a `@dataclass(frozen=True)` `FeatureVectorRecord` wire envelope with fields: symbol: str, tf: str, bar_ts: datetime, pipeline_version: str, regime: str | None, regime_label_source: str, vector: FeatureVector. Ensure `dataclasses` and `datetime` are imported (datetime already imported per existing block).
  </action>
  <verify>
    .venv/bin/python -c "import dataclasses as dc; from src.intelligence.schemas import FeatureVector, FeatureVectorRecord; flds=[f.name for f in dc.fields(FeatureVector)]; assert len(flds)==35, len(flds); print('fields', len(flds)); print('frozen', FeatureVector.__dataclass_params__.frozen)"
  </verify>
  <acceptance_criteria>
    - `from src.intelligence.schemas import FeatureVector, FeatureVectorRecord` succeeds
    - `len(dataclasses.fields(FeatureVector)) == 35`
    - `FeatureVector.__dataclass_params__.frozen is True`
    - The set of FeatureVector field names equals the 35 names listed in 137-CONTEXT.md `<specifics>`
    - FeatureVectorRecord has a field `vector` annotated `FeatureVector` and a field `regime_label_source` annotated `str`
    - Existing symbols still import: `.venv/bin/python -c "from src.intelligence.schemas import BarIntelligenceRecord, TIER_DB_COLUMNS"` exits 0
  </acceptance_criteria>
</task>

</tasks>

<verification>
- topic_feature_vectors + DLQ importable and env-prefixed
- FeatureVector frozen dataclass with exactly 35 named float fields
- FeatureVectorRecord wraps FeatureVector with persistence metadata
- No existing schemas.py exports broken
</verification>

<success_criteria>
SC-2 (FeatureVector frozen dataclass) partially satisfied: the dataclass contract exists with all 35 primitives. FeatureFactory.compute() producing it is P3.
</success_criteria>

<output>
After completion, create `.planning/phases/137-feature-factory/137-P2-SUMMARY.md`
</output>
