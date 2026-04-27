---
phase: 64-i6-confluence-expansion-cross-tf-plugins-macro-context-service
plan: 03A
type: execute
wave: 2
depends_on: ["64-00", "64-01"]
deferred: false
files_modified:
  - src/intelligence/macro/constants.py
  - src/intelligence/macro/yield_curve.py
  - src/intelligence/schemas.py
  - services/macro_compute_agent.py
  - services/indicagent-macro-compute.service
  - src/core/stream_keys.py
  - src/intelligence/trading/confidence_utils.py
  - src/config/settings.py
  - tests/unit/intelligence/test_yield_curve.py
  - tests/unit/service_tests/test_macro_compute_agent.py
autonomous: true
requirements: []

must_haves:
  truths:
    - "MacroComputeAgent extends BaseAgent for Renaissance observability (Phase 71)"
    - "Yield curve slope computed from ZT/ZN/ZB/ZF rate futures (data available)"
    - "MacroComputeAgent subscribes to topic_market_bars for rate futures bar data"
    - "Yield curve output published to topic_macro_signals (new Kafka topic)"
    - "MacroComputeAgent writes to macro_features hypertable (new table)"
    - "Macro factors appear in frames['cross_asset'] payload (injection point reused)"
    - "Yield curve signal backtested on 6 months historical data (Plan 00 tool)"
    - "Yield curve degrades gracefully when rate futures absent"
    - "Backtest validation: IC > 0.05 AND p < 0.01 before shadow deployment"
  artifacts:
    - path: "src/intelligence/macro/yield_curve.py"
      provides: "Yield curve slope macro factor"
      contains: "compute_yield_curve_slope()"
    - path: "services/macro_compute_agent.py"
      provides: "Macro factors service (extends BaseAgent)"
      contains: "MacroComputeAgent"
    - path: "services/indicagent-macro-compute.service"
      provides: "Systemd unit for MacroComputeAgent"
      contains: "WatchdogSec=0, NotifyAccess=main (no sd_notify)"
    - path: "src/core/stream_keys.py"
      provides: "New Kafka topic functions"
      contains: "topic_macro_signals()"
    - path: "src/intelligence/schemas.py"
      provides: "MacroSignals schema"
      contains: "yield_curve_slope, yield_curve_regime"
  key_links:
    - from: "services/macro_compute_agent.py"
      to: "src/core/agent/base.py"
      via: "class MacroComputeAgent(BaseAgent)"
      pattern: "from src.core.agent.base import BaseAgent"
    - from: "services/macro_compute_agent.py"
      to: "src/intelligence/macro/yield_curve.py"
      via: "imports compute_yield_curve_slope()"
      pattern: "from src.intelligence.macro.yield_curve import compute_yield_curve_slope"
    - from: "services/macro_compute_agent.py"
      to: "src/config/settings.py"
      via: "uses Settings for Kafka bootstrap, DB URL"
      pattern: "self.settings = Settings()"
    - from: "services/macro_compute_agent.py"
      to: "src/core/stream_keys.py"
      via: "subscribes to topic_market_bars, publishes to topic_macro_signals"
      pattern: "topic_market_bars(env_name), topic_macro_signals(env_name)"
    - from: "services/macro_compute_agent.py"
      to: "TimescaleDB"
      via: "writes to macro_features hypertable"
      pattern: "INSERT INTO macro_features"
---

<objective>
Create MacroComputeAgent service (extends BaseAgent for full Renaissance observability) and implement yield curve slope macro factor from rate futures (ZT/ZN/ZB/ZF). Subscribe to topic_market_bars for rate futures bar data, compute yield curve slope, publish to topic_macro_signals, persist to macro_features hypertable, inject into frames['cross_asset'] for pipeline consumption.

Purpose: First macro factor implementation using available data (ZT/ZN/ZB/ZF rate futures). Separate service architecture (not merged into CrossAssetComputeAgent) for clean separation of concerns, independent deployment/testing/scaling.
Prerequisite: At least 1 of 5 cross-TF plugins from Plan 01 must pass validation gate (IC > 0.05). If cross-TF plugins show no signal, macro factors (further removed from price action) are unlikely to either.
Output: Working MacroComputeAgent service in shadow mode with yield curve slope signal, validated on historical data (IC > 0.05).
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/64-i6-confluence-expansion-cross-tf-plugins-macro-context-service/64-CONTEXT.md
@.planning/phases/64-i6-confluence-expansion-cross-tf-plugins-macro-context-service/64-RENAISSANCE-REVIEW-R&D.md
@.planning/phases/64-i6-confluence-expansion-cross-tf-plugins-macro-context-service/64-00-PLAN.md
@.planning/phases/64-i6-confluence-expansion-cross-tf-plugins-macro-context-service/64-01-PLAN.md

@services/cross_asset_service.py (DO NOT MODIFY — separate service)
@services/intelligence_pipeline_agent.py
@src/core/agent/base.py
@src/core/stream_keys.py
@src/config/settings.py
@src/intelligence/macro/constants.py (from Plan 01)

<interfaces>
<!-- Key types and contracts -->

From src/core/agent/base.py (EXTEND this for Renaissance observability):
```python
class MacroComputeAgent(BaseAgent):
    """Macro factors microservice.
    
    Extends BaseAgent for Renaissance-style observability:
    - Structured logging via structlog (agent_id bound)
    - Consumer lag reporting (_report_consumer_lag)
    - OTel tracing (init_tracing, get_tracer)
    - Prometheus metrics (auto-start if metrics_port set)
    - SIGTERM/SIGINT graceful drain
    - Crash detection (AGENT_CRASH_TOTAL counter)
    - Stall detection (AGENT_LAST_MESSAGE_TIMESTAMP_SECONDS gauge)
    """
    
    agent_id: str = "macro_compute_agent"
    
    def __init__(self) -> None:
        settings = Settings()
        self._settings = settings  # Phase 71 convention
        self._window_bars: int = settings.macro_window_bars  # Rolling window size
        self._kafka_bootstrap: str = settings.kafka_bootstrap_servers
        self._database_url: str = settings.database_url
    
    async def _setup(self) -> None:
        """Initialize Kafka, DB, metrics."""
        # Kafka consumer for topic_market_bars
        # Kafka producer for topic_macro_signals
        # Database pool for macro_features hypertable
        # Metrics server (if metrics_port set)
        # Tracer (if tracing enabled)
    
    async def _teardown(self) -> None:
        """Graceful shutdown."""
    
    async def _run(self) -> None:
        """Main loop — consume bars, compute macro, publish signals."""
        # Subscribe to topic_market_bars
        # For each bar: if symbol in MACRO_RATE_FUTURES:
        #   - Update rolling window
        #   - Compute yield curve slope
        #   - Publish to topic_macro_signals
        #   - Write to macro_features hypertable
        # Handle SIGTERM/SIGINT drain
```

From src/intelligence/macro/yield_curve.py (CREATE this):
```python
"""Yield curve slope macro factor.

Computes yield curve slope from rate futures prices (ZT, ZN, ZB, ZF).
Rate futures trade inverse to yields: price up = yield down.

Outputs:
    yield_curve_slope: float [-1, +1]
        - Positive: Curve steepening (short rates down more than long)
        - Negative: Curve flattening (short rates up more than long)
        - Near 0: Curve stable
    yield_curve_regime: str
        - steepening: Bullish steepening
        - flattening: Bearish flattening
        - inverted: Yield curve inverted
        - normal: Normal yield curve
"""

from __future__ import annotations

from collections import deque
from typing import Any

import numpy as np


def compute_yield_curve_slope(
    bars: dict[str, deque],
    lookback: int = 10,
) -> dict[str, Any]:
    """Compute yield curve slope from rate futures.
    
    Args:
        bars: Dict mapping symbol → deque of recent bars (OHLCV dicts)
        lookback: Number of bars to average (default: 10)
    
    Returns:
        dict with yield_curve_slope (float) and yield_curve_regime (str)
    
    Implementation:
        1. Extract close prices for ZT, ZN, ZB, ZF
        2. Compute yield proxy: yield = -log(price / 100)  # Price down = yield up
        3. Compute slope: ZT_yield - ZB_yield (short - long)
        4. Normalize slope via tanh for gradient in [-1, +1]
        5. Classify regime based on slope magnitude + ZT-ZB relationship
    """
    # Extract recent closes (average over lookback for stability)
    slopes = []
    for i in range(lookback):
        try:
            zt_close = bars["ZT"][-i]["close"] if len(bars["ZT"]) > i else None
            zn_close = bars["ZN"][-i]["close"] if len(bars["ZN"]) > i else None
            zb_close = bars["ZB"][-i]["close"] if len(bars["ZB"]) > i else None
            
            if None in (zt_close, zn_close, zb_close):
                continue
            
            # Yield proxy: price down = yield up
            # Use -log(price / 100) to convert to yield basis points
            zt_yield = -np.log(zt_close / 100.0)
            zb_yield = -np.log(zb_close / 100.0)
            
            # Slope: short-term yield minus long-term yield
            slope = zt_yield - zb_yield
            slopes.append(slope)
        except (IndexError, KeyError):
            continue
    
    if not slopes:
        return {
            "yield_curve_slope": 0.0,
            "yield_curve_regime": "normal",
        }
    
    # Average slope
    avg_slope = np.mean(slopes)
    
    # Normalize via tanh: 0.01 = 1% steepening -> tanh(0.01 * 100) ≈ 0.76
    slope_normalized = np.tanh(avg_slope * 100.0)  # [-1, +1]
    
    # Regime classification
    if avg_slope > 0.005:  # >0.5% steepening
        regime = "steepening"
    elif avg_slope < -0.005:  # >0.5% flattening
        regime = "flattening"
    elif zb_yield > zt_yield:  # Inverted
        regime = "inverted"
    else:
        regime = "normal"
    
    return {
        "yield_curve_slope": float(slope_normalized),
        "yield_curve_regime": regime,
    }
```

From src/core/stream_keys.py (ADD new topic function):
```python
def topic_macro_signals(env: str = "dev") -> str:
    """Kafka topic for macro factor signals.
    
    Published by: MacroComputeAgent
    Consumed by: IntelligencePipelineComputeAgent (injected into frames["cross_asset"])
    DataWriterAgent writes to: macro_features hypertable
    
    Topic naming: <env>.macro_signals (dots only, no colons)
    """
    return f"{env}.macro_signals"
```

From TimescaleDB (CREATE new hypertable):
```sql
-- Macro factors hypertable
CREATE TABLE IF NOT EXISTS macro_features (
    ts TIMESTAMPTZ NOT NULL,
    symbol VARCHAR(32) NOT NULL,
    timeframe VARCHAR(8) NOT NULL,
    yield_curve_slope DOUBLE PRECISION,
    yield_curve_regime VARCHAR(32),
    PRIMARY KEY (ts, symbol, timeframe)
);

SELECT create_hypertable('macro_features', 'ts', 
  chunk_time_interval => INTERVAL '1 day',
  if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS idx_macro_features_symbol 
  ON macro_features(symbol, ts DESC);
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
<title>Create MacroComputeAgent service</title>
<dependencies></dependencies>
<work_estimate>3 hours</work_estimate>
<description>
Create services/macro_compute_agent.py:

```python
#!/usr/bin/env python3
"""Macro Factors Service.

Computes macro factors (yield curve, flight-to-quality, USD strength)
from cross-asset bar data and publishes to macro_signals topic.

Service lifecycle follows BaseAgent canonical pattern (Phase 071):
  - __init__: configure settings, logging, metrics
  - _setup(): Kafka, DB, tracing
  - _run(): main loop — consume, compute, publish
  - _teardown(): graceful shutdown

Version: 1.0.0
Last Updated: 2026-04-26
"""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from datetime import UTC, datetime
from pathlib import Path

import structlog

from src.config.settings import Settings
from src.core.agent.base import BaseAgent
from src.core.database_manager import DatabaseManager
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.service_utils import setup_service_logging
from src.core.stream_keys import message_key, topic_macro_signals, topic_market_bars
from src.intelligence.macro.constants import MACRO_RATE_FUTURES
from src.intelligence.macro.yield_curve import compute_yield_curve_slope
from src.observability.metrics import AGENT_CRASH_TOTAL, PERSISTENCE_CONSUMER_LAG, counter, gauge, start_metrics_server


logger = structlog.get_logger(__name__)


class MacroComputeAgent(BaseAgent):
    """Macro factors microservice — extends BaseAgent.
    
    Subscribes to market_bars topic, computes macro factors from
    cross-asset instruments (rate futures, FX pairs, ETFs),
    publishes results to macro_signals topic.
    
    Migrated to BaseAgent for Renaissance-style observability (Phase 071).
    Inherits crash metrics, stall detection, and alert publishing.
    """
    
    agent_id: str = "macro_compute_agent"
    
    def __init__(self) -> None:
        settings = Settings()
        self._settings = settings
        self._window_bars: int = settings.macro_window_bars
        self._kafka_bootstrap: str = settings.kafka_bootstrap_servers
        self._database_url: str = settings.database_url
        
        # Rolling windows keyed by symbol
        min_needed = self._window_bars + 1
        self._bar_windows: dict[str, deque] = defaultdict(
            lambda: deque(maxlen=min_needed)
        )
        
        # Setup logging BEFORE super().__init__
        setup_service_logging("logs/macro_compute_agent.log")
        
        # Call parent constructor
        super().__init__()
    
    async def _setup(self) -> None:
        """Initialize Kafka, DB, metrics."""
        # Start metrics server if configured
        if self._settings.macro_metrics_port:
            start_metrics_server(self._settings.macro_metrics_port)
            logger.info(
                "metrics.started",
                port=self._settings.macro_metrics_port,
            )
        
        # Initialize database connection pool
        self._db_manager = DatabaseManager(self._database_url)
        await self._db_manager.initialize()
        
        # Initialize Kafka consumer for market_bars
        self._consumer = KafkaConsumerClient(
            bootstrap_servers=self._kafka_bootstrap,
            topic=topic_market_bars(self._settings.env_name),
            group_id="macro_consumer",
            auto_offset_reset="latest",
        )
        await self._consumer.start()
        
        # Initialize Kafka producer for macro_signals
        self._producer = KafkaProducerClient(
            bootstrap_servers=self._kafka_bootstrap,
        )
        await self._producer.start()
        
        logger.info(
            "macro_compute_agent.setup",
            window_bars=self._window_bars,
            rate_futures=list(MACRO_RATE_FUTURES),
        )
    
    async def _teardown(self) -> None:
        """Graceful shutdown."""
        await self._consumer.stop()
        await self._producer.stop()
        await self._db_manager.close()
        logger.info("macro_compute_agent.teardown")
    
    async def _run(self) -> None:
        """Main loop — consume bars, compute macro, publish signals."""
        logger.info("macro_compute_agent.started")
        
        try:
            async for msg in self._consumer.messages():
                # Parse bar message
                bar = self._parse_bar(msg.value)
                
                if bar is None:
                    continue
                
                # Update rolling window
                symbol = bar["symbol"]
                self._bar_windows[symbol].append(bar)
                
                # Only compute macro if we have enough data
                # AND symbol is a macro instrument
                if (symbol in MACRO_RATE_FUTURES and
                    len(self._bar_windows[symbol]) >= self._window_bars):
                    
                    # Compute yield curve slope
                    macro_result = compute_yield_curve_slope(
                        dict(self._bar_windows),
                        lookback=self._window_bars,
                    )
                    
                    # Publish to macro_signals topic
                    await self._publish_macro_signal(macro_result)
                    
                    # Persist to macro_features table
                    await self._persist_to_db(macro_result)
                    
                    logger.debug(
                        "macro.computed",
                        symbol=symbol,
                        yield_curve_slope=macro_result["yield_curve_slope"],
                    )
                
                # Report consumer lag
                self._report_consumer_lag()
        
        except asyncio.CancelledError:
            logger.info("macro_compute_agent.shutdown")
            raise
        except Exception as e:
            logger.exception("macro_compute_agent.error", error=str(e))
            AGENT_CRASH_TOTAL.labels(agent_id=self.agent_id).inc()
            raise
    
    def _parse_bar(self, msg_value: bytes) -> dict | None:
        """Parse Kafka bar message."""
        # TODO: Implement bar parsing based on actual message format
        # Should return dict with ts, symbol, tf, open, high, low, close, volume
        pass
    
    async def _publish_macro_signal(self, macro_result: dict) -> None:
        """Publish macro signal to Kafka."""
        # TODO: Publish to topic_macro_signals
        # Include: ts, symbol, tf, yield_curve_slope, yield_curve_regime
        pass
    
    async def _persist_to_db(self, macro_result: dict) -> None:
        """Persist macro result to TimescaleDB."""
        # TODO: INSERT INTO macro_features
        pass


def main() -> None:
    """Entry point for systemd service."""
    agent = MacroComputeAgent()
    asyncio.run(agent.start())


if __name__ == "__main__":
    main()
```

Key implementation notes:
- Extends BaseAgent for full Renaissance observability
- Uses self._settings (Phase 71 convention)
- setup_service_logging() called BEFORE super().__init__
- Subscribes to topic_market_bars, publishes to topic_macro_signals
- Rolling windows per symbol (deque for efficiency)
- Only computes macro for symbols in MACRO_RATE_FUTURES
- _report_consumer_lag() called each iteration
- AGENT_CRASH_TOTAL labeled with agent_id
</description>
<acceptance_criteria>
- [ ] MacroComputeAgent extends BaseAgent
- [ ] _setup() initializes Kafka, DB, metrics
- [ ] _run() consumes market_bars, computes macro, publishes signals
- [ ] _teardown() graceful shutdown
- [ ] Subscribe to topic_market_bars, publish to topic_macro_signals
- [ ] Rolling windows per symbol (deque maxlen)
- [ ] Only compute for MACRO_RATE_FUTURES symbols
- [ ] Consumer lag reporting works
- [ ] Crash metrics labeled correctly
</acceptance_criteria>
</task>

<task type="auto" tdd="true">
<title>Create systemd unit for MacroComputeAgent</title>
<dependencies>create MacroComputeAgent service</dependencies>
<work_estimate>0.5 hours</work_estimate>
<description>
Create services/indicagent-macro-compute.service:

```ini
[Unit]
Description=IndicAgent Macro Factors Service — Yield curve, flight-to-quality, USD strength
Documentation=https://github.com/your-repo/indicagent
After=network.target redpanda.service timescaledb.service
Wants=timescaledb.service

[Service]
Type=simple
User=indicagent
Group=indicagent
WorkingDirectory=/home/bg/dev/indicagent
Environment="PATH=/home/bg/dev/indicagent/.venv/bin"
EnvironmentFile=-/home/bg/dev/indicagent/.env
ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/macro_compute_agent.py
Restart=always
RestartSec=10

# Logs go to file (setup_service_logging), NOT journald
StandardOutput=null
StandardError=journal

# Security
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

Key points:
- No WatchdogSec (agents don't implement sd_notify)
- Logs to logs/macro_compute_agent.log (NOT journald)
- Restart=always for service resilience
- Wants timescaledb (DB dependency)
```

Enable service:
```bash
sudo cp services/indicagent-macro-compute.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable indicagent-macro-compute.service
# Don't start yet — wait for testing
```
</description>
<acceptance_criteria>
- [ ] systemd unit file created
- [ ] No WatchdogSec (correct — no sd_notify)
- [ ] Logs to file (StandardOutput=null)
- [ ] Restart=always
- [ ] Wants timescaledb.service
- [ ] Installed in /etc/systemd/system/
- [ ] systemctl daemon-reload successful
</acceptance_criteria>
</task>

<task type="auto" tdd="true">
<title>Add topic_macro_signals to stream_keys.py</title>
<dependencies>create systemd unit for MacroComputeAgent</dependencies>
<work_estimate>0.5 hours</work_estimate>
<description>
Update src/core/stream_keys.py:

Add new topic function:
```python
def topic_macro_signals(env: str = "dev") -> str:
    """Kafka topic for macro factor signals.
    
    Published by: MacroComputeAgent
    Consumed by: IntelligencePipelineComputeAgent (frames["cross_asset"])
    DataWriterAgent writes to: macro_features hypertable
    
    Topic naming: <env>.macro_signals (dots only, no colons)
    """
    return f"{env}.macro_signals"
```

Add to module exports if needed.
</description>
<acceptance_criteria>
- [ ] topic_macro_signals() function added
- [ ] Returns "{env}.macro_signals"
- [ ] Docstring explains producer/consumer/writer
- [ ] Function exported from module
</acceptance_criteria>
</task>

<task type="auto" tdd="true">
<title>Create macro_features hypertable migration</title>
<dependencies>add topic_macro_signals to stream_keys.py</dependencies>
<work_estimate>0.5 hours</work_estimate>
<description>
Create migrations/NNN_macro_features.sql:

```sql
-- Macro factors hypertable
-- Stores computed macro factors (yield curve, flight-to-quality, USD strength)
-- Time partitioned by ts (1 day chunks)

CREATE TABLE IF NOT EXISTS macro_features (
    ts TIMESTAMPTZ NOT NULL,
    symbol VARCHAR(32) NOT NULL,
    timeframe VARCHAR(8) NOT NULL,
    
    -- Yield curve slope factor
    yield_curve_slope DOUBLE PRECISION,
    yield_curve_regime VARCHAR(32),
    
    -- Flight-to-quality factor (added in Plan 03B)
    -- ftq_score DOUBLE PRECISION,
    -- ftq_regime VARCHAR(32),
    
    -- USD strength factor (added in Plan 03C)
    -- usd_strength_score DOUBLE PRECISION,
    -- usd_strength_regime VARCHAR(32),
    
    PRIMARY KEY (ts, symbol, timeframe)
);

-- Create hypertable
SELECT create_hypertable('macro_features', 'ts',
  chunk_time_interval => INTERVAL '1 day',
  if_not_exists => TRUE
);

-- Indexes for queries
CREATE INDEX IF NOT EXISTS idx_macro_features_symbol
  ON macro_features(symbol, ts DESC);

CREATE INDEX IF NOT EXISTS idx_macro_features_timeframe
  ON macro_features(timeframe, ts DESC);

-- Add comment
COMMENT ON TABLE macro_features IS 'Macro factors: yield curve, flight-to-quality, USD strength';
```

Run migration:
```bash
psql -U postgres -d indicagent -f migrations/NNN_macro_features.sql
```
</description>
<acceptance_criteria>
- [ ] migrations/NNN_macro_features.sql created
- [ ] macro_features table created
- [ ] Hypertable created on ts column
- [ ] Indexes created on symbol, timeframe
- [ ] Migration executes successfully
</acceptance_criteria>
</task>

<task type="auto" tdd="true">
<title>Backtest yield curve factor on historical data</title>
<dependencies>create macro_features hypertable migration</dependencies>
<work_estimate>1 hour</work_estimate>
<description>
Create tools/backtest_yield_curve.py:

```python
"""Backtest yield curve factor on historical rate futures data."""

from datetime import datetime, timedelta
import asyncpg
import pandas as pd
from src.intelligence.macro.yield_curve import compute_yield_curve_slope

async def backtest_yield_curve(
    start_date: datetime,
    end_date: datetime,
) -> pd.DataFrame:
    """Backtest yield curve on historical ZT/ZN/ZB/ZF data."""
    
    # Load rate futures bars from market_data_ohlcv
    conn = await asyncpg.connect(settings.database_url)
    
    rows = await conn.fetch("""
        SELECT ts, symbol, tf, open, high, low, close, volume
        FROM market_data_ohlcv
        WHERE ts BETWEEN $1 AND $2
          AND symbol IN ('ZT', 'ZN', 'ZB', 'ZF')
        ORDER BY ts, symbol
    """, start_date, end_date)
    
    await conn.close()
    
    # Group by timestamp, build windows per symbol
    df = pd.DataFrame(rows, columns=["ts", "symbol", "tf", "open", "high", "low", "close", "volume"])
    
    # Sliding window backtest (similar to plugin backtest)
    results = []
    for ts, group in df.groupby("ts"):
        # Build bars dict
        bars = {}
        for symbol, subgrp in group.groupby("symbol"):
            bars[symbol] = deque(subgrp.to_dict("records"), maxlen=100)
        
        # Compute yield curve
        yc_result = compute_yield_curve_slope(bars, lookback=10)
        
        results.append({
            "ts": ts,
            "yield_curve_slope": yc_result["yield_curve_slope"],
            "yield_curve_regime": yc_result["yield_curve_regime"],
        })
    
    return pd.DataFrame(results)
```

Run backtest:
```bash
python tools/backtest_yield_curve.py \
  --start 2025-10-01 --end 2026-04-01 \
  --output /tmp/yield_curve_backtest.csv
```

Validate:
```bash
python tools/validate_i6_backtest.py \
  --input /tmp/yield_curve_backtest.csv \
  --field yield_curve_slope \
  --min-ic 0.05 --alpha 0.01
```

**Feature selection:**
- **IC > 0.05:** Deploy MacroComputeAgent to shadow mode
- **IC 0.02-0.05:** Tweak parameters (lookback window, normalization)
- **IC < 0.02:** Kill yield curve factor, don't invest in FX data for USD strength
</description>
<acceptance_criteria>
- [ ] backtest_yield_curve.py created
- [ ] Loads ZT/ZN/ZB/ZF bars from market_data_ohlcv
- [ ] Computes yield_curve_slope using sliding window
- [ ] Outputs CSV with ts, yield_curve_slope, yield_curve_regime
- [ ] Validation tool computes IC/p-value
- [ ] Feature selection applied (keep/tweak/kill)
</acceptance_criteria>
</task>

<task type="auto" tdd="true">
<title>Deploy MacroComputeAgent to shadow mode</title>
<dependencies>backtest yield curve factor on historical data</dependencies>
<work_estimate>0.5 hours</work_estimate>
<description>
If yield curve backtest validates (IC > 0.05):

1. Start MacroComputeAgent:
```bash
sudo systemctl start indicagent-macro-compute.service
```

2. Verify service health:
```bash
# Check service status
sudo systemctl status indicagent-macro-compute.service

# Check logs
tail -f logs/macro_compute_agent.log

# Check consumer lag
# (Grafana dashboard or direct query)
```

3. Verify macro_signals topic:
```bash
# Verify messages flowing to topic
docker exec redpanda rpk topic consume dev.macro_signals --num 5
```

4. Verify macro_features table:
```bash
docker exec timescaledb psql -U postgres -d indicagent -c "
  SELECT * FROM macro_features 
  ORDER BY ts DESC 
  LIMIT 5;
"
```

5. Monitor for 1 hour, check for errors
</description>
<acceptance_criteria>
- [ ] MacroComputeAgent starts successfully
- [ ] Logs show "macro_compute_agent.started"
- [ ] Messages appear in dev.macro_signals topic
- [ ] Rows appear in macro_features table
- [ ] No errors in logs for 1 hour
- [ ] Service running in shadow mode (not connected to trading)
</acceptance_criteria>
</task>

<task type="auto" tdd="true">
<title>Create unit tests for yield curve and service</title>
<dependencies>deploy MacroComputeAgent to shadow mode</dependencies>
<work_estimate>1.5 hours</work_estimate>
<description>
Create unit tests:

tests/unit/intelligence/test_yield_curve.py:
- test_compute_yield_curve_slope(): Mock bars data, verify output range
- test_yield_curve_steepening_regime(): ZT up, ZB down → steepening
- test_yield_curve_flattening_regime(): ZT down, ZB up → flattening
- test_yield_curve_inverted_regime(): ZB yield > ZT yield → inverted
- test_insufficient_data(): Empty bars → returns 0.0, "normal"

tests/unit/service_tests/test_macro_compute_agent.py:
- test_setup(): Verify Kafka, DB, metrics initialized
- test_market_bars_subscription(): Verify subscribes to topic_market_bars
- test_macro_signal_published(): Verify publishes to topic_macro_signals
- test_db_persistence(): Verify writes to macro_features table
- test_base_agent_observability(): Verify structured logging, metrics, traces

Use mock Kafka/DB (no live infra required).
</description>
<acceptance_criteria>
- [ ] test_yield_curve.py created with 5 tests
- [ ] test_macro_compute_agent.py created with 5 tests
- [ ] All tests use mocks (no live infra)
- [ ] pytest -v passes
- [ ] Coverage > 80%
</acceptance_criteria>
</task>

</tasks>

<checkout>
<checklist>
- [ ] MacroComputeAgent service created (extends BaseAgent)
- [ ] yield_curve.py factor function created
- [ ] topic_macro_signals() added to stream_keys.py
- [ ] macro_features hypertable created
- [ ] systemd unit installed
- [ ] Backtest completed with IC/p-value results
- [ ] Feature selection applied (keep/tweak/kill)
- [ ] If validated: deployed to shadow mode
- [ ] Unit tests pass
- [ ] Service healthy: consuming, computing, publishing
- [ ] Prerequisite met: At least 1 Plan 01 plugin passed validation (IC > 0.05)
</checklist>
</checkout>

---

*Plan 64-03A: Yield Curve Slope Macro Factor*
*Renaissance R&D Approach: Build what we have, validate before investing in more data*
