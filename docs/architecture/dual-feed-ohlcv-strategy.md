# Pipeline Data Flow Architecture: Dual-Feed OHLCV Strategy

## Overview
To achieve Renaissance-grade data integrity, IndicAgent utilizes a dual-feed OHLCV strategy in the TWS Daemon. This architecture mitigates the trade-off between low-latency bar aggregation (the "hot" path) and authoritative data auditing (the "audit" path).

## Data Streams
1. **Real-Time Stream (`market.ticks`)**:
   - **Source**: 5-second `RealTimeBars` from IBKR via `stream_real_time_bars`.
   - **Purpose**: Provides low-latency, 5-second granularity data to power real-time intelligence features and I1 technical indicator calculations.
   - **Aggregation**: The `TwsDaemon` aggregates these 5s bars into 1m bars for downstream pipeline ingestion.

2. **Official Audit Stream (`market.bars`)**:
   - **Source**: 1-minute `OfficialBars` from IBKR via `stream_official_bars`.
   - **Purpose**: Provides authoritative, auditable 1-minute ground-truth data for reconciliation and drift detection.

## Canonical 1440-Bar Grid
To ensure a continuous time-series index for ML modeling, the pipeline enforces a gap-free grid of 1440 bars per day for every active instrument.
- **Flat Bars**: During periods of zero volume, the aggregation services (`TwsDaemon`, `TimeframeBuilder`) emit a "flat bar" containing the last traded `close` price, `volume = 0`, and the `is_flat_bar: true` flag.
- **Downstream Benefit**: This preserves the temporal index of the hypertable, allowing for seamless seasonal ML analysis without requiring complex gap-filling logic in downstream feature or signal services.

## Reconciliation & Drift Detection
- The `TwsDaemon` maintains an internal `_official_bars_cache` (last 20 bars).
- Upon sealing each 1m bar (aggregated from the 5s stream), the daemon compares the derived `close` price against the `OfficialBar` close.
- **Drift Threshold**: A drift of >0.01% triggers a `drift_detected` warning and increments the `indicagent_bar_drift_total` counter.
- **Empty Bar & Continuity Handling**: If a 1-minute period has no aggregated data from the 5-second stream, the daemon attempts to backfill the OHLCV values using the authoritative 1-minute Official Bar stream. If neither is available, it emits a flat bar (or skips to prevent pollution if even authoritative data is missing).

## Architectural Documentation Reference
- **Service**: `services/tws_daemon.py`
- **Topic Configuration**: `production/scripts/kafka_init_topics.py`
- **Stream Keys**: `src/core/stream_keys.py`
