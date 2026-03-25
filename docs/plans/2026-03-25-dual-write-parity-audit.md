# Parity Audit: Dual-Write Instrumentation (Feature Historian)

## Objective
Enable a "Shadow Mode" for feature persistence. The `FeaturePipelineService` will continue its legacy DB-write path while simultaneously publishing to the new `intelligence.feature.journal` Kafka topic, allowing the `FeatureHistorianAgent` to write a shadow record for parity verification.

## Strategy: The "Dual-Write" Protocol
1.  **Dual-Write Instrumentation:** Instrument `FeaturePipelineService` to publish to Kafka (the "Agentic Path") while maintaining the existing legacy SQL path.
2.  **Parity Monitoring:** The `FeatureHistorianAgent` writes to a separate, temporary `feature_snapshots_shadow` table.
3.  **Audit Engine:** Implement a comparison script that validates row-level parity (ts, symbol, tf, feature_vector) between `intelligence_features` and `feature_snapshots_shadow`.

## Implementation Steps
1. **Producer Instrumentation:** Update `FeaturePipelineService` to use `KafkaProducerClient` to emit records.
2. **Schema Validation:** Ensure the published Kafka payload matches the `FeatureRepository` expected schema.
3. **Shadow Table Setup:** Run `CREATE TABLE feature_snapshots_shadow (LIKE intelligence_features INCLUDING ALL);`.
4. **Agentic Redirect:** Point `FeatureHistorianAgent` to write to `feature_snapshots_shadow`.

## Verification
- **Success Criteria:** 100% row-level matching over a 24-hour observation period.
- **Latency Check:** Confirm Agentic path Kafka latency (p99) is < 2ms.
- **Fail-Safe:** If shadow parity fails, Agentic path is ignored, and DB write remains the source of truth.
