# Refactor Plan: FeaturePipelineService Producer Instrumentation

## Objective
Convert `FeaturePipelineService` into a pure ComputeAgent that emits journaled Kafka events. Remove direct database I/O to maximize pipeline throughput and eliminate database-induced latency.

## Scope & Impact
- **Affected File:** `services/feature_pipeline_service.py`
- **Impact:** Decouples high-frequency feature computation from database I/O.
- **Dependency Migration:** Move `market_data_ohlcv` writing logic to a new `MarketDataHistorianAgent` if persistence is still needed, or confirm it's handled by other daemons.

## Implementation Steps
1. **Remove DB Dependencies:** Strip `DatabaseManager`, `_INSERT_OHLCV_SQL`, and related DB orchestration logic.
2. **Instrument Producer:** Configure `KafkaProducerClient` to publish processed features to `intelligence.feature.journal` (using `IntelligenceJournal` Pydantic model).
3. **Dual-Write (Parity):** Keep legacy `_INSERT_OHLCV_SQL` for the 24-hour verification window (shadow mode) but wrap it in an `if LEGACY_PERSISTENCE_ENABLED:` toggle.
4. **Agentic Loop:** Ensure the producer loop publishes the journal payload immediately after compute completion, fulfilling the "Observe-Decide-Act" pattern.

## Verification
- **Log Parity:** Compare `feature_historian_shadow` row counts against legacy `intelligence_features` table.
- **Latency Verification:** Monitor `pipeline_latency_ms` via Prometheus; confirm no spikes after DB-write removal.
- **No Data Loss:** Ensure all features published to Kafka are correctly received by `FeatureHistorianAgent`.
