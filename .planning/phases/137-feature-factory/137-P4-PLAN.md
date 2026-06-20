---
phase: 137-feature-factory
plan: 4
type: execute
wave: 3
depends_on: [1, 2]
files_modified:
  - services/feature_writer.py
  - tests/unit/service_tests/test_feature_writer.py
autonomous: true
requirements: [SC-6]

threat_model:
  assets:
    - "feature_writer persistence path (sole writer to feature_vectors)"
    - "Kafka consumer offsets for the feature writer consumer group"
  threats:
    - id: T1
      description: "Reusing consumer group 'feature_writer_group' after retargeting the topic causes the new writer to inherit committed offsets on the old intelligence.journal topic - reads from wrong offset position, silent data gap"
      severity: high
      mitigation: "Rename consumer group to 'feature_vector_writer_group'; acceptance criterion asserts the new group name and that the writer consumes topic_feature_vectors"
    - id: T2
      description: "INSERT param count mismatches the 42-placeholder feature_vectors INSERT - asyncpg raises at flush, batch lost to DLQ silently"
      severity: medium
      mitigation: "_record_to_insert_params returns exactly 42 values matching the column order; acceptance criterion asserts param count equals placeholder count via a unit test"
  block_on: [T1]

must_haves:
  truths:
    - "feature_writer consumes topic_feature_vectors and persists FeatureVectorRecord rows to feature_vectors"
    - "feature_writer uses consumer group feature_vector_writer_group (not feature_writer_group)"
    - "feature_writer no longer references intelligence_features, BarIntelligenceRecord, or cross-asset processing"
  artifacts:
    - path: "services/feature_writer.py"
      provides: "FeatureWriter retargeted to feature_vectors via FeatureVectorRecord"
      contains: "feature_vectors"
  key_links:
    - from: "services/feature_writer.py"
      to: "feature_vectors table"
      via: "_INSERT_FEATURE_VECTOR_SQL batch insert"
      pattern: "INSERT INTO feature_vectors"
    - from: "services/feature_writer.py"
      to: "src/core/stream_keys.py topic_feature_vectors"
      via: "topics_consumed / _topic_name"
      pattern: "topic_feature_vectors"
---

<objective>
Retarget the existing `feature_writer` service from `intelligence_features` to `feature_vectors`. Reuse all proven `BaseWriter` infrastructure (batching, flush loop, DLQ, OTel metrics, health monitor) unchanged - only the topic, schema, INSERT SQL, schema-verify query, and consumer group change. Delete the cross-asset and expiry-map code paths that do not apply to `feature_vectors`.

Purpose: This is the persistence half of SC-6 (feature_writer persists to feature_vectors). The live pipeline (P6) publishes `FeatureVectorRecord` to `topic_feature_vectors`; this writer consumes and persists. Reusing the writer (D-12) avoids rebuilding proven engineering.
Output: `feature_writer.py` writing to `feature_vectors` via `FeatureVectorRecord`, new consumer group, updated unit tests.
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
  <name>Task 1: Retarget feature_writer to feature_vectors</name>
  <files>services/feature_writer.py</files>
  <read_first>
    - services/feature_writer.py (FULL read - current intelligence_features INSERT at line ~73, CONSUMER_GROUP at line ~60, _topic_name/_consumer_group/topics_consumed at lines ~321-330, _verify_schema at ~392, _flush_batch at ~376, the cross-asset/_build_expiry_map blocks to delete)
    - .planning/phases/137-feature-factory/A-PATTERNS.md (section "services/feature_writer.py" - exact topic change, _INSERT_FEATURE_VECTOR_SQL with 42 placeholders, _parse_payload change, _REQUIRED_COLUMNS, consumer group rename, list of blocks to remove)
    - src/intelligence/schemas.py (FeatureVectorRecord / FeatureVector from P2 - the payload contract)
    - src/core/stream_keys.py (topic_feature_vectors / topic_feature_vectors_dlq from P2)
  </read_first>
  <action>
    Change imports: import topic_feature_vectors + topic_feature_vectors_dlq; remove topic_intelligence_journal and topic_cross_asset imports. Import FeatureVectorRecord from src.intelligence.schemas; remove BarIntelligenceRecord / CTF_DEDICATED_COLUMNS imports.

    Set CONSUMER_GROUP = "feature_vector_writer_group" (rename - avoids offset collision with the old group on intelligence.journal, T1).

    _topic_name() and topics_consumed return topic_feature_vectors(self.env_name).

    Replace _INSERT_FEATURE_SQL with _INSERT_FEATURE_VECTOR_SQL: INSERT INTO feature_vectors with the column order (symbol, tf, bar_ts, pipeline_version, regime, regime_label_source, then 35 features in the cadence order from 137-CONTEXT.md `<specifics>`) and 42 positional placeholders $1..$42, ON CONFLICT (symbol, tf, bar_ts) DO NOTHING.

    Add a module-level `_record_to_insert_params(record: FeatureVectorRecord) -> tuple` returning exactly 42 values in the INSERT column order, reading the 35 features from record.vector.

    Rewrite _parse_payload to construct a FeatureVectorRecord from the payload dict (reconstruct the nested FeatureVector), returning ([params], []) on success and ([], [payload]) on parse failure (increment _parse_errors_total). Return None only for entirely-wrong-schema payloads (DLQ contract from CLAUDE.md).

    Update _verify_schema: query information_schema.columns WHERE table_name='feature_vectors'; _REQUIRED_COLUMNS spot-check frozenset = {symbol, tf, bar_ts, pipeline_version, momentum_z_5, momentum_z_20, hurst, atr_z}.

    Update _flush_batch to use _INSERT_FEATURE_VECTOR_SQL. Preserve _periodic_flush_loop and _health_monitor_loop exactly.

    DELETE: _build_expiry_map, _compute_days_to_expiry, _cross_asset_cache, _process_cross_asset_message, and the Phase-130 CTF-column verify logic. Cross-asset values now live in FeatureCache (P3), not the writer.

    All OTel/span patterns, batch-size APR keys, and BaseWriter inheritance stay. Use format_iso_ts for any timestamp serialization; pass dicts (not json.dumps) to asyncpg.
  </action>
  <verify>
    .venv/bin/python -c "import services.feature_writer as fw; assert fw.CONSUMER_GROUP=='feature_vector_writer_group'; print('group OK')" && .venv/bin/ruff check services/feature_writer.py
  </verify>
  <acceptance_criteria>
    - `services/feature_writer.py` contains `INSERT INTO feature_vectors`
    - `grep -n "intelligence_features\|BarIntelligenceRecord\|topic_cross_asset\|_build_expiry_map\|_process_cross_asset_message" services/feature_writer.py` returns 0 matches
    - `CONSUMER_GROUP == "feature_vector_writer_group"`
    - `topics_consumed` returns a list containing the output of `topic_feature_vectors`
    - The _INSERT_FEATURE_VECTOR_SQL has exactly 42 positional placeholders ($1..$42) and `_record_to_insert_params` returns a 42-tuple
    - `.venv/bin/ruff check services/feature_writer.py` exits 0
  </acceptance_criteria>
</task>

<task type="auto">
  <name>Task 2: Update feature_writer unit tests for feature_vectors</name>
  <files>tests/unit/service_tests/test_feature_writer.py</files>
  <read_first>
    - tests/unit/service_tests/test_feature_writer.py (existing tests - find references to intelligence_features, BarIntelligenceRecord, cross-asset, expiry that now break)
    - services/feature_writer.py (the retargeted writer - new contract)
    - src/intelligence/schemas.py (FeatureVectorRecord for building test payloads)
  </read_first>
  <action>
    Update the existing feature_writer unit tests to the new contract. Replace BarIntelligenceRecord fixtures with FeatureVectorRecord fixtures (a full 35-field FeatureVector). Assert:
    - _parse_payload turns a valid FeatureVectorRecord payload dict into a 42-element insert-params tuple
    - _parse_payload on a malformed payload returns ([], [payload]) and increments parse errors
    - _record_to_insert_params returns exactly 42 values in INSERT column order
    - topics_consumed and CONSUMER_GROUP reflect feature_vectors
    Delete tests for _build_expiry_map / _compute_days_to_expiry / cross-asset processing (removed code). Do not test BaseWriter internals - only the writer-specific overrides.
    If the test file imports removed symbols, fix the imports (file/class rename test sweep per CLAUDE.md).
  </action>
  <verify>
    .venv/bin/pytest tests/unit/service_tests/test_feature_writer.py -q
  </verify>
  <acceptance_criteria>
    - `.venv/bin/pytest tests/unit/service_tests/test_feature_writer.py -q` exits 0
    - `grep -n "BarIntelligenceRecord\|_build_expiry_map\|intelligence_features" tests/unit/service_tests/test_feature_writer.py` returns 0 matches
    - A test asserts a valid FeatureVectorRecord payload parses to a 42-element params tuple
    - A test asserts CONSUMER_GROUP == 'feature_vector_writer_group'
  </acceptance_criteria>
</task>

</tasks>

<verification>
- feature_writer writes to feature_vectors via 42-param INSERT, ON CONFLICT DO NOTHING
- Consumer group renamed (no offset collision)
- Cross-asset / expiry code removed
- Unit tests green
- ruff clean
</verification>

<success_criteria>
SC-6 (feature_writer persists to feature_vectors) half satisfied: writer retargeted. The pipeline publishing FeatureVectorRecord is P6.
</success_criteria>

<output>
After completion, create `.planning/phases/137-feature-factory/137-P4-SUMMARY.md`
</output>
