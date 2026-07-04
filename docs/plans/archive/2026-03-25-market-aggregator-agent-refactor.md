# Refactor Plan: MarketAggregatorAgent (I0 Entry Point)

**Last Updated:** 2026-05-02

## Objective
Convert `market_analysis_service.py` into a high-performance `MarketAggregatorAgent` (I0). This agent serves as the DAG entry point, converting raw market ticks into standardized 1m OHLCV bars with sub-millisecond latency.

## Scope & Impact
- **Affected File:** `services/market_analysis_service.py` -> `services/market_aggregator_agent.py`
- **Impact:** Decouples tick aggregation from database I/O.
- **Principle:** "Compute Locality." Aggregation is CPU/Memory intensive and must be isolated from DB-bound latency.

## Implementation Steps
1. **Remove DB Dependencies:** Strip `DatabaseManager`, direct SQL queries, and legacy I/O.
2. **Standardize Agent Protocol:** Ensure compliance with `AGENT_STANDARD.md` (SIGTERM drain, OTel instrumentation).
3. **Kafka Integration:** Ensure consumption from `topic_market_ticks` and production to `topic_market_bars`.
4. **Resilience:** Wrap the accumulation loop in a graceful shutdown that flushes pending bars to Kafka before exiting.

## Verification
- **Throughput:** Ensure `events_produced_total` is incrementing correctly.
- **Latency:** Verify `plugin_execution_seconds` is within sub-millisecond bounds.
- **Data Integrity:** Verify that OHLCV bars produced match the legacy logic (Parity Check).
