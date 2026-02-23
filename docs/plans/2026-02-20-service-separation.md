> **HISTORICAL DOCUMENT** — `intelligence_processor_service.py` was deleted in Phase 1 (2026-02-23). This plan describes the migration that created `market_analysis_service.py`. References to `intelligence_processor_service.py` are for historical context only.

# Service Separation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Refactor the 8-service pipeline into clearly separated, single-responsibility processes — eliminating I1 triple-computation, extracting signal lifecycle from signal generation, and retiring obsolete services.

**Architecture:** `indicator_service` computes all I1 plugins and publishes one combined OHLCV+features message per bar to `indicators:SYMBOL:TF`. `market_analysis_service` (renamed `intelligence_processor_service`) consumes that stream, runs I3→I4→I5→SMC→I6, and publishes to `intelligence:SYMBOL:TF`. `signal_tracker_service` (new) extracts lifecycle tracking from the signal orchestrator and subscribes to `market:SYMBOL:1m` independently.

**Tech Stack:** Python 3.13, redis.asyncio, structlog, asyncio, pytest. Plugin registry via `src/intelligence/plugins.py`.

**Design reference:** `docs/architecture/service-separation.md`

**Test command:** `.venv/bin/python3 -m pytest tests/unit/ --ignore=tests/integration -q`

---

## Task 1: Create `indicator_service.py` — standalone I1 computation

This service replaces the inline I1 block inside `intelligence_processor_service` and consolidates the two existing indicator services. It reads `market:SYMBOL:*`, runs all I1 plugins via the plugin registry, and publishes one combined OHLCV+I1 message to `indicators:SYMBOL:TF`.

**Files:**
- Create: `services/indicator_service.py`
- Create: `tests/unit/service_tests/test_indicator_service.py`
- Create: `config/indicator_service.json`

**Reference (inline I1 block to extract):**
`services/intelligence_processor_service.py:441-459` — the `for plugin_name in I1_PLUGINS` loop inside `_calculate_intelligence`.

---

### Step 1.1: Write the failing test for `build_i1_message`

A pure helper function: given bar_data (OHLCV dict) and a features dict (I1 outputs), it returns a Redis-ready flat dict with all fields as strings.

```python
# tests/unit/service_tests/test_indicator_service.py

import pytest

def test_build_i1_message_includes_ohlcv_and_features():
    """Combined message must contain OHLCV fields AND I1 feature outputs."""
    from services.indicator_service import build_i1_message
    from datetime import datetime

    bar = {"open": 5300.0, "high": 5305.0, "low": 5299.0, "close": 5303.0, "volume": 1000}
    features = {"rsi_14": 58.3, "macd": 2.1, "atr_14": 4.5}
    ts = datetime(2026, 2, 20, 10, 0, 0)

    msg = build_i1_message(bar, features, ts, symbol="ES", timeframe="1m")

    assert msg["open"] == "5300.0"
    assert msg["high"] == "5305.0"
    assert msg["close"] == "5303.0"
    assert msg["volume"] == "1000"
    assert msg["rsi_14"] == "58.3"
    assert msg["macd"] == "2.1"
    assert msg["timestamp"] == ts.isoformat()
    assert msg["symbol"] == "ES"
    assert msg["timeframe"] == "1m"


def test_build_i1_message_skips_non_scalar_features():
    """Non-scalar values (lists, dicts) must be excluded from message."""
    from services.indicator_service import build_i1_message
    from datetime import datetime

    bar = {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 500}
    features = {"rsi_14": 55.0, "targets": [101.0, 102.0], "meta": {"x": 1}}
    ts = datetime(2026, 2, 20, 10, 0, 0)

    msg = build_i1_message(bar, features, ts, symbol="ES", timeframe="1m")

    assert "rsi_14" in msg
    assert "targets" not in msg
    assert "meta" not in msg


def test_parse_indicators_message_splits_ohlcv_and_features():
    """parse_indicators_message must split OHLCV from feature fields."""
    from services.indicator_service import parse_indicators_message

    raw = {
        b"timestamp": b"2026-02-20T10:00:00",
        b"symbol": b"ES",
        b"timeframe": b"1m",
        b"open": b"5300.0",
        b"high": b"5305.0",
        b"low": b"5299.0",
        b"close": b"5303.0",
        b"volume": b"1000",
        b"rsi_14": b"58.3",
        b"macd": b"2.1",
    }

    bar, features = parse_indicators_message(raw)

    assert bar["open"] == 5300.0
    assert bar["close"] == 5303.0
    assert bar["volume"] == 1000
    assert features["rsi_14"] == 58.3
    assert features["macd"] == 2.1
    assert "open" not in features
    assert "timestamp" not in features
```

### Step 1.2: Run test to confirm failure

```bash
.venv/bin/python3 -m pytest tests/unit/service_tests/test_indicator_service.py -v
```
Expected: `ImportError: cannot import name 'build_i1_message' from 'services.indicator_service'`

---

### Step 1.3: Write `services/indicator_service.py`

The service is structurally a stripped-down `intelligence_processor_service.py`. Copy the scaffold (Redis connection, consumer group, bar history, signal handler, health loop) and implement only I1 logic.

```python
#!/usr/bin/env python3
"""
Indicator Service — I1 technical indicator computation

Reads market bars from Redis Streams, runs all 23 I1 plugins via the
plugin registry, and publishes ONE combined OHLCV+indicators message per
bar to indicators:SYMBOL:TF. Downstream services consume this single
message — no coordination across multiple indicator messages needed.

Replaces: indicators_processor_service.py + indicators_enhanced_service.py
          + the inline I1 block in intelligence_processor_service.py
"""

import asyncio
import json
import logging
import os
import signal
import sys
import time
from collections import defaultdict, deque
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pandas as pd
import redis.asyncio as redis
import structlog

from src.config.settings import Settings, get_active_contracts
from src.core.stream_keys import indicators as sk_indicators
from src.core.stream_keys import market as sk_market
from src.intelligence.plugins import registry
from src.intelligence.register_plugins import register_all_plugins
from src.observability.metrics import counter, gauge, record_plugin_execution, start_metrics_server

# Must match names in register_plugins.py
I1_PLUGINS = [
    "RSI", "MovingAverages", "MACD", "ATR", "BollingerBands", "Stochastic",
    "CCI", "WilliamsR", "MFI", "OBV", "VWAP", "Supertrend", "ROC_PPO",
    "ind_CMF", "ind_Aroon", "ind_HistoricalVolatility",
    "ind_ChandelierExit", "ind_ParabolicSAR", "ind_StochRSI",
]

_OHLCV_FIELDS = frozenset({"timestamp", "symbol", "timeframe", "open", "high", "low", "close", "volume", "source"})


def build_i1_message(
    bar: dict[str, Any],
    features: dict[str, Any],
    timestamp: datetime,
    symbol: str,
    timeframe: str,
) -> dict[str, str]:
    """Build a flat string-valued Redis message combining OHLCV and I1 features.

    Only scalar values (str, int, float, bool) are included. Lists and dicts
    are silently dropped — Redis stream fields must be flat strings.
    """
    msg: dict[str, str] = {
        "timestamp": timestamp.isoformat(),
        "symbol": symbol,
        "timeframe": timeframe,
        "open": str(bar.get("open", "")),
        "high": str(bar.get("high", "")),
        "low": str(bar.get("low", "")),
        "close": str(bar.get("close", "")),
        "volume": str(int(bar.get("volume", 0))),
    }
    for k, v in features.items():
        if isinstance(v, (str, int, float, bool)):
            msg[k] = str(v)
    return msg


def parse_indicators_message(
    fields: dict[bytes, bytes],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split an indicators stream message into (bar_dict, features_dict).

    bar_dict has float OHLCV values. features_dict has all other numeric
    fields as floats. Used by market_analysis_service to consume this stream.
    """
    bar: dict[str, Any] = {}
    features: dict[str, Any] = {}

    for raw_key, raw_val in fields.items():
        key = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
        val = raw_val.decode() if isinstance(raw_val, bytes) else str(raw_val)

        if key in _OHLCV_FIELDS:
            if key == "open":
                bar["open"] = float(val)
            elif key == "high":
                bar["high"] = float(val)
            elif key == "low":
                bar["low"] = float(val)
            elif key == "close":
                bar["close"] = float(val)
            elif key == "volume":
                bar["volume"] = int(float(val))
        else:
            try:
                features[key] = float(val)
            except (ValueError, TypeError):
                features[key] = val

    return bar, features


class IndicatorService:
    """Compute I1 technical indicators and publish one combined message per bar."""

    def __init__(self, config_file: str | None = None):
        self.running = False
        self.shutdown_requested = False
        self.start_time = datetime.now()
        self.config = self._load_config(config_file)
        self._setup_logging()

        register_all_plugins()

        self.redis_client: redis.Redis | None = None
        self.consumer_group = f"indicator_service_{int(time.time())}"
        self.consumer_name = f"indicator_consumer_{os.getpid()}"

        settings = Settings()
        self.env_prefix = f"{settings.env_name}:" if settings.env_name else ""

        self.bar_history: dict[str, deque] = defaultdict(lambda: deque(maxlen=200))

        self.bars_processed_total = counter(
            "indicator_bars_processed_total",
            "Total market bars processed by indicator service",
        )
        self.service_uptime_seconds = gauge(
            "indicator_service_uptime_seconds",
            "Indicator service uptime in seconds",
        )
        self.error_count_total = counter(
            "indicator_errors_total",
            "Total errors in indicator service",
        )

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        self.logger = structlog.get_logger(__name__)

    def _load_config(self, config_file: str | None) -> dict[str, Any]:
        default: dict[str, Any] = {
            "redis": {"host": "localhost", "port": 6379, "db": 0},
            "service": {
                "symbols": get_active_contracts(),
                "timeframes": ["1m", "5m", "15m", "1h", "4h", "1d"],
                "min_history_bars": 120,
                "processing_interval": 0.1,
            },
            "metrics_port": 9109,
            "logging": {
                "level": "INFO",
                "file": "logs/indicator_service.log",
            },
        }
        if config_file and Path(config_file).exists():
            with open(config_file) as f:
                user_config = json.load(f)
            for k, v in user_config.items():
                if isinstance(v, dict) and k in default:
                    default[k].update(v)
                else:
                    default[k] = v
        return default

    def _setup_logging(self) -> None:
        log_dir = Path(self.config["logging"]["file"]).parent
        log_dir.mkdir(exist_ok=True)
        file_handler = RotatingFileHandler(
            self.config["logging"]["file"], maxBytes=10 * 1024 * 1024, backupCount=5
        )
        structlog.configure(
            processors=[
                structlog.stdlib.filter_by_level,
                structlog.stdlib.add_logger_name,
                structlog.stdlib.add_log_level,
                structlog.stdlib.PositionalArgumentsFormatter(),
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.processors.UnicodeDecoder(),
                structlog.processors.JSONRenderer(),
            ],
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )
        logging.basicConfig(
            level=getattr(logging, self.config["logging"]["level"]),
            handlers=[file_handler],
            format="%(message)s",
        )

    def _signal_handler(self, signum: int, frame: Any) -> None:
        self.logger.info("Received shutdown signal", signal=signum)
        self.shutdown_requested = True

    def _run_i1_plugins(self, frames: dict[str, Any]) -> dict[str, Any]:
        """Run all I1 plugins and return merged feature dict."""
        features: dict[str, Any] = {}
        for plugin_name in I1_PLUGINS:
            t0 = time.time()
            try:
                p = registry.get_indicator(plugin_name)
                result = p.compute_full(frames)
                features.update(result)
                record_plugin_execution(plugin_name, "", "", time.time() - t0, "success", "I1")
            except Exception as e:
                self.logger.warning("I1 plugin failed", plugin=plugin_name, error=str(e))
                record_plugin_execution(plugin_name, "", "", time.time() - t0, "error", "I1")
        return features

    async def _process_single_bar(
        self,
        symbol: str,
        timeframe: str,
        fields: dict[bytes, bytes],
        stream_name: str,
        message_id: bytes,
    ) -> None:
        try:
            bar_ts = datetime.fromisoformat(fields[b"timestamp"].decode())
            bar_source = fields.get(b"source", b"").decode()
            bar_data = {
                "timestamp": bar_ts,
                "open": float(fields[b"open"].decode()),
                "high": float(fields[b"high"].decode()),
                "low": float(fields[b"low"].decode()),
                "close": float(fields[b"close"].decode()),
                "volume": int(float(fields[b"volume"].decode())),
            }

            key = f"{symbol}:{timeframe}"

            if bar_source == "authoritative":
                # Silently correct history, skip pipeline
                history = self.bar_history[key]
                if history and history[-1]["timestamp"] == bar_ts:
                    history[-1] = bar_data
                else:
                    history.append(bar_data)
                await self.redis_client.xack(stream_name, self.consumer_group, message_id)
                return

            self.bar_history[key].append(bar_data)

            min_bars = self.config["service"]["min_history_bars"]
            if len(self.bar_history[key]) < min_bars:
                await self.redis_client.xack(stream_name, self.consumer_group, message_id)
                return

            df = pd.DataFrame(list(self.bar_history[key]))
            frames = {"main": df}

            features = self._run_i1_plugins(frames)

            msg = build_i1_message(bar_data, features, bar_ts, symbol, timeframe)
            out_stream = sk_indicators(self.env_prefix, symbol, timeframe)
            await self.redis_client.xadd(out_stream, msg, maxlen=1000, approximate=True)

            self.bars_processed_total.inc()
            await self.redis_client.xack(stream_name, self.consumer_group, message_id)

            self.logger.debug(
                "I1 published",
                symbol=symbol,
                timeframe=timeframe,
                features=len(features),
            )

        except Exception as e:
            self.logger.error(
                "Error processing bar", symbol=symbol, timeframe=timeframe, error=str(e)
            )
            self.error_count_total.inc()

    async def _connect_redis(self) -> None:
        self.redis_client = redis.Redis(
            host=self.config["redis"]["host"],
            port=self.config["redis"]["port"],
            db=self.config["redis"]["db"],
            decode_responses=False,
        )
        await self.redis_client.ping()
        self.logger.info("Connected to Redis")

    async def _setup_consumer_groups(self) -> None:
        for timeframe in self.config["service"]["timeframes"]:
            for symbol in self.config["service"]["symbols"]:
                stream_name = sk_market(self.env_prefix, symbol, timeframe)
                try:
                    await self.redis_client.xgroup_create(
                        stream_name, self.consumer_group, "0", mkstream=True
                    )
                except Exception:
                    pass

    async def _process_market_data(self) -> None:
        while self.running and not self.shutdown_requested:
            try:
                for timeframe in self.config["service"]["timeframes"]:
                    for symbol in self.config["service"]["symbols"]:
                        stream_name = sk_market(self.env_prefix, symbol, timeframe)
                        messages = await self.redis_client.xreadgroup(
                            self.consumer_group,
                            self.consumer_name,
                            {stream_name: ">"},
                            count=10,
                            block=100,
                        )
                        for _stream, msgs in messages:
                            for message_id, fields in msgs:
                                await self._process_single_bar(
                                    symbol, timeframe, fields, stream_name, message_id
                                )
                await asyncio.sleep(self.config["service"]["processing_interval"])
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in processing loop", error=str(e))
                self.error_count_total.inc()
                await asyncio.sleep(1)

    async def _health_monitor_loop(self) -> None:
        while self.running and not self.shutdown_requested:
            try:
                uptime = int((datetime.now() - self.start_time).total_seconds())
                self.service_uptime_seconds.set(uptime)
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break

    async def start(self) -> None:
        self.logger.info("Starting Indicator Service", config=self.config["service"])
        try:
            await self._connect_redis()
            start_metrics_server(port=self.config.get("metrics_port", 9109))
            await self._setup_consumer_groups()
            self.running = True
            tasks = [
                asyncio.create_task(self._process_market_data()),
                asyncio.create_task(self._health_monitor_loop()),
            ]
            self.logger.info("Indicator Service started")
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            self.logger.error("Failed to start indicator service", error=str(e))
            raise
        finally:
            await self.stop()

    async def stop(self) -> None:
        self.logger.info("Stopping Indicator Service")
        self.running = False
        self.shutdown_requested = True
        if self.redis_client:
            await self.redis_client.aclose()
        self.logger.info("Indicator Service stopped")


async def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Indicator Service")
    parser.add_argument("--config", help="Config file path")
    args = parser.parse_args()
    service = IndicatorService(args.config)
    try:
        await service.start()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    asyncio.run(main())
```

### Step 1.4: Run tests to confirm they pass

```bash
.venv/bin/python3 -m pytest tests/unit/service_tests/test_indicator_service.py -v
```
Expected: 3 PASSED

### Step 1.5: Write `config/indicator_service.json`

```json
{
  "redis": {
    "host": "localhost",
    "port": 6379,
    "db": 0
  },
  "service": {
    "symbols": ["ESH6", "NQH6", "RTYH6", "CLK6", "GCM6", "NGK6"],
    "timeframes": ["1m", "5m", "15m", "1h"],
    "min_history_bars": 120,
    "processing_interval": 0.1
  },
  "metrics_port": 9109,
  "logging": {
    "level": "INFO",
    "file": "logs/indicator_service.log"
  }
}
```

### Step 1.6: Run full test suite to confirm no regressions

```bash
.venv/bin/python3 -m pytest tests/unit/ --ignore=tests/integration -q
```
Expected: 453+ passed, 0 failed.

### Step 1.7: Commit

```bash
git add services/indicator_service.py config/indicator_service.json \
        tests/unit/service_tests/test_indicator_service.py
git commit -m "feat: add indicator_service — standalone I1 computation, one combined msg per bar"
```

---

## Task 2: Update `intelligence_processor_service.py` → `market_analysis_service.py`

Remove the inline I1 block. Change consumer from `market:SYMBOL:TF` to `indicators:SYMBOL:TF`. Parse OHLCV + I1 features from the incoming message. Rename the file.

**Files:**
- Create: `services/market_analysis_service.py` (from intelligence_processor_service.py)
- Create: `tests/unit/service_tests/test_market_analysis_service.py`
- Create: `config/market_analysis_service.json`
- Keep `services/intelligence_processor_service.py` until Task 5 cleanup

**Key change:** `_process_single_bar` currently reads from `market:SYMBOL:TF` and calls `_calculate_intelligence` which starts with the I1 block. After this task, it reads from `indicators:SYMBOL:TF` and `_calculate_intelligence` starts directly at I3.

---

### Step 2.1: Write failing test for `_parse_indicators_message` integration

```python
# tests/unit/service_tests/test_market_analysis_service.py

def test_market_analysis_service_imports():
    """Ensure market_analysis_service exists and has the right class."""
    from services.market_analysis_service import MarketAnalysisService
    svc = MarketAnalysisService()
    assert hasattr(svc, "_run_analysis_pipeline")


def test_run_analysis_pipeline_requires_features():
    """Pipeline must return empty dict when features are empty (no I1 output)."""
    from services.market_analysis_service import MarketAnalysisService
    import pandas as pd

    svc = MarketAnalysisService()
    frames = {"main": pd.DataFrame([
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 500}
    ] * 30), "features": {}}

    # Without I1 features, I3/I4 plugins may still run but features must stay dict
    result = svc._run_analysis_pipeline("ES", "1m", frames)
    assert isinstance(result, dict)
```

### Step 2.2: Run test to confirm failure

```bash
.venv/bin/python3 -m pytest tests/unit/service_tests/test_market_analysis_service.py -v
```
Expected: `ModuleNotFoundError: No module named 'services.market_analysis_service'`

---

### Step 2.3: Create `services/market_analysis_service.py`

Copy `services/intelligence_processor_service.py` to `services/market_analysis_service.py` then make these targeted changes:

**Change 1 — Class name:** `IntelligenceProcessorService` → `MarketAnalysisService`

**Change 2 — Consumer stream:** In `_setup_consumer_groups` and `_process_market_data`, change:
```python
# FROM:
stream_name = sk_market(self.env_prefix, symbol, timeframe)
# TO:
from src.core.stream_keys import indicators as sk_indicators_key
stream_name = sk_indicators_key(self.env_prefix, symbol, timeframe)
```

**Change 3 — Bar parsing:** In `_process_single_bar`, the incoming message is from `indicators:SYMBOL:TF`, which contains OHLCV + I1 features as flat fields. Import and use `parse_indicators_message` from `indicator_service`:

```python
# At top of file:
from services.indicator_service import parse_indicators_message

# In _process_single_bar, replace the raw field decoding block with:
bar_data, i1_features = parse_indicators_message(fields)
bar_ts = datetime.fromisoformat(fields[b"timestamp"].decode())
bar_data["timestamp"] = bar_ts
# bar_source handling: indicators stream has no "source" field — skip authoritative filter
```

**Change 4 — Remove I1 block:** In `_calculate_intelligence`, remove lines 441-459 (the `for plugin_name in I1_PLUGINS` loop). Instead, accept `i1_features` as a parameter and use it as the initial `features` dict:

```python
# Signature change:
async def _calculate_intelligence(
    self, symbol: str, timeframe: str, timestamp: datetime, i1_features: dict
) -> dict[str, float]:
    ...
    features: dict[str, Any] = dict(i1_features)  # start with I1 already populated
    frames["features"] = features

    # I3 block starts here (unchanged)
    ...
```

**Change 5 — Pass i1_features:** In `_process_single_bar`, pass i1_features to `_calculate_intelligence`:
```python
intelligence = await self._calculate_intelligence(
    symbol, timeframe, bar_data["timestamp"], i1_features
)
```

**Change 6 — Extract `_run_analysis_pipeline`** for testability (also needed for the test above):
```python
def _run_analysis_pipeline(
    self, symbol: str, timeframe: str, frames: dict[str, Any]
) -> dict[str, Any]:
    """Run I3→I4→I5→SMC→I6 synchronously. Returns merged feature dict."""
    features: dict[str, Any] = dict(frames.get("features", {}))
    frames["features"] = features
    # I3, I4, I5, SMC, I6 loops (same as current _calculate_intelligence body)
    ...
    return features
```

**Change 7 — Rename config key in logging:**
```python
"file": "logs/market_analysis_service.log",
```

**Change 8 — Metrics port:** Change from `9111` to a new port `9114` (to avoid conflict):
```python
start_metrics_server(port=9114)
```

### Step 2.4: Run tests

```bash
.venv/bin/python3 -m pytest tests/unit/service_tests/test_market_analysis_service.py \
    tests/unit/service_tests/test_intelligence_processor.py \
    tests/unit/service_tests/test_intelligence_source_filter.py \
    tests/unit/service_tests/test_intelligence_processor_ohlcv.py -v
```
Expected: all PASSED (existing tests still pass since the old file is unchanged).

### Step 2.5: Write `config/market_analysis_service.json`

```json
{
  "redis": {
    "host": "localhost",
    "port": 6379,
    "db": 0
  },
  "service": {
    "symbols": ["ESH6", "NQH6", "RTYH6", "CLK6", "GCM6", "NGK6"],
    "timeframes": ["1m", "5m", "15m", "1h"],
    "min_history_bars": 120,
    "processing_interval": 0.1
  },
  "metrics_port": 9114,
  "logging": {
    "level": "INFO",
    "file": "logs/market_analysis_service.log"
  }
}
```

### Step 2.6: Run full test suite

```bash
.venv/bin/python3 -m pytest tests/unit/ --ignore=tests/integration -q
```
Expected: 453+ passed, 0 failed.

### Step 2.7: Commit

```bash
git add services/market_analysis_service.py config/market_analysis_service.json \
        tests/unit/service_tests/test_market_analysis_service.py
git commit -m "feat: add market_analysis_service — consumes indicators stream, drops inline I1"
```

---

## Task 3: Create `signal_tracker_service.py` — extract lifecycle tracking

The lifecycle tracking code in `signal_orchestrator_service.py:484-547` (`_track_lifecycle` method) belongs in a separate process. The tracker subscribes to `market:SYMBOL:1m` (not the intelligence stream — it only needs OHLCV to check stop/target prices).

**Files:**
- Create: `services/signal_tracker_service.py`
- Create: `tests/unit/service_tests/test_signal_tracker_service.py`
- Create: `config/signal_tracker_service.json`

---

### Step 3.1: Write failing tests

```python
# tests/unit/service_tests/test_signal_tracker_service.py

def test_signal_tracker_service_imports():
    from services.signal_tracker_service import SignalTrackerService
    svc = SignalTrackerService()
    assert hasattr(svc, "_evaluate_signals_against_bar")


def test_evaluate_signals_against_bar_no_db_returns_empty():
    """Without a DB connection, evaluation must return empty list (not raise)."""
    from services.signal_tracker_service import SignalTrackerService
    svc = SignalTrackerService()
    svc.db_manager = None  # Simulate no DB

    import asyncio
    transitions = asyncio.get_event_loop().run_until_complete(
        svc._evaluate_signals_against_bar("ES", "1m", {"high": 5305.0, "low": 5298.0, "close": 5303.0})
    )
    assert transitions == []


def test_evaluate_signals_against_bar_calls_evaluate_signal(monkeypatch):
    """Each active signal must be passed through evaluate_signal."""
    from services.signal_tracker_service import SignalTrackerService
    from unittest.mock import AsyncMock, patch, MagicMock

    svc = SignalTrackerService()
    svc.db_manager = MagicMock()
    svc.point_values = {"ES": 50.0}

    fake_signal = {
        "signal_id": "abc",
        "symbol": "ES",
        "timeframe": "1m",
        "direction": 1,
        "entry_price": 5300.0,
        "stop_loss": 5295.0,
        "targets": [5310.0],
        "status": "active",
        "bars_open": 2,
        "timeframe_ttl": 30,
    }

    import asyncio
    with patch("services.signal_tracker_service.get_active_signals", new=AsyncMock(return_value=[fake_signal])):
        with patch("services.signal_tracker_service.evaluate_signal", return_value=None) as mock_eval:
            asyncio.get_event_loop().run_until_complete(
                svc._evaluate_signals_against_bar("ES", "1m", {"high": 5305.0, "low": 5299.0, "close": 5303.0})
            )
            mock_eval.assert_called_once()
```

### Step 3.2: Run test to confirm failure

```bash
.venv/bin/python3 -m pytest tests/unit/service_tests/test_signal_tracker_service.py -v
```
Expected: `ModuleNotFoundError`

---

### Step 3.3: Write `services/signal_tracker_service.py`

Extract `_track_lifecycle` from `signal_orchestrator_service.py` into this standalone service. The key difference: this service subscribes to `market:SYMBOL:1m` (not `intelligence:SYMBOL:TF`) — it only needs bar OHLCV to evaluate stops and targets.

```python
#!/usr/bin/env python3
"""
Signal Tracker Service — open signal lifecycle management

Subscribes to market:SYMBOL:1m. For each bar, queries the signal_ledger
for active signals on that symbol/timeframe and evaluates whether they have
hit their stop loss, take profit targets, or expired via TTL.

Decoupled from signal_generator_service so that lifecycle tracking continues
even when the intelligence pipeline is stopped for maintenance.
"""

import asyncio
import json
import logging
import os
import signal
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import redis.asyncio as redis
import structlog

from src.config.settings import Settings, get_active_contracts, get_point_value
from src.core.database_manager import DatabaseManager
from src.core.stream_keys import market as sk_market
from src.intelligence.trading.lifecycle_tracker import evaluate_signal
from src.intelligence.trading.signal_ledger import get_active_signals, update_signal_status
from src.observability.metrics import counter, gauge, start_metrics_server

_TTL_BY_TIMEFRAME: dict[str, int] = {"1m": 30, "5m": 20, "15m": 12, "1h": 6}
_TTL_DEFAULT = 10


class SignalTrackerService:
    """Evaluate open signal lifecycle per incoming market bar."""

    def __init__(self, config_file: str | None = None):
        self.running = False
        self.shutdown_requested = False
        self.start_time = datetime.now(tz=UTC)
        self.config = self._load_config(config_file)
        self._setup_logging()

        self.redis_client: redis.Redis | None = None
        self.db_manager: DatabaseManager | None = None
        self.consumer_group = f"signal_tracker_{int(time.time())}"
        self.consumer_name = f"tracker_{os.getpid()}"

        settings = Settings()
        self.env_prefix = f"{settings.env_name}:" if settings.env_name else ""

        self.point_values: dict[str, float] = {
            sym: float(get_point_value(sym) or 1.0)
            for sym in self.config["service"]["symbols"]
        }

        self.lifecycle_transitions_total = counter(
            "tracker_lifecycle_transitions_total",
            "Total signal lifecycle transitions",
        )
        self.active_signals_count = gauge(
            "tracker_active_signals_count",
            "Current count of open signals",
        )
        self.service_uptime_seconds = gauge(
            "tracker_service_uptime_seconds",
            "Signal tracker uptime in seconds",
        )
        self.error_count_total = counter(
            "tracker_errors_total",
            "Total errors in signal tracker",
        )

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        self.logger = structlog.get_logger(__name__)

    def _load_config(self, config_file: str | None) -> dict[str, Any]:
        try:
            _settings = Settings()
        except Exception:
            _settings = None

        default: dict[str, Any] = {
            "redis": {"host": "localhost", "port": 6379, "db": 0},
            "database": {
                "url": (
                    _settings.database_url
                    if _settings and getattr(_settings, "database_url", None)
                    else "postgresql://postgres:postgres@localhost:5432/indicagent"
                )
            },
            "service": {
                "symbols": get_active_contracts(),
                "timeframes": ["1m", "5m", "15m", "1h"],
                "processing_interval": 0.1,
            },
            "metrics_port": 9115,
            "logging": {
                "level": "INFO",
                "file": "logs/signal_tracker_service.log",
            },
        }
        if config_file and Path(config_file).exists():
            with open(config_file) as f:
                user_config = json.load(f)
            for k, v in user_config.items():
                if isinstance(v, dict) and k in default:
                    default[k].update(v)
                else:
                    default[k] = v
        return default

    def _setup_logging(self) -> None:
        log_dir = Path(self.config["logging"]["file"]).parent
        log_dir.mkdir(exist_ok=True)
        file_handler = RotatingFileHandler(
            self.config["logging"]["file"], maxBytes=10 * 1024 * 1024, backupCount=5
        )
        structlog.configure(
            processors=[
                structlog.stdlib.filter_by_level,
                structlog.stdlib.add_logger_name,
                structlog.stdlib.add_log_level,
                structlog.stdlib.PositionalArgumentsFormatter(),
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.processors.UnicodeDecoder(),
                structlog.processors.JSONRenderer(),
            ],
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )
        logging.basicConfig(
            level=getattr(logging, self.config["logging"]["level"]),
            handlers=[file_handler],
            format="%(message)s",
        )

    def _signal_handler(self, signum: int, frame: Any) -> None:
        self.logger.info("Received shutdown signal", signal=signum)
        self.shutdown_requested = True

    async def _evaluate_signals_against_bar(
        self,
        symbol: str,
        timeframe: str,
        bar: dict[str, Any],
    ) -> list[Any]:
        """Evaluate all active signals for this symbol/timeframe against bar OHLCV.

        Returns list of transitions applied (empty if db_manager is None).
        """
        if not self.db_manager:
            return []

        active = await get_active_signals(self.db_manager, symbol=symbol)
        relevant = [s for s in active if s.get("timeframe") == timeframe]
        self.active_signals_count.set(len(relevant))

        transitions = []
        timestamp = datetime.now(tz=UTC)

        for sig in relevant:
            sig_with_pv = {**sig, "point_value": self.point_values.get(symbol, 1.0)}
            try:
                transition = evaluate_signal(
                    sig_with_pv,
                    high=float(bar["high"]),
                    low=float(bar["low"]),
                    close=float(bar["close"]),
                )
            except Exception as e:
                self.logger.warning(
                    "Lifecycle evaluation failed",
                    signal_id=sig.get("signal_id"),
                    error=str(e),
                )
                continue

            if transition is None:
                continue

            activated_at = timestamp if transition.new_status == "active" else None
            exit_at = timestamp if transition.exit_reason else None

            await update_signal_status(
                self.db_manager,
                transition.signal_id,
                status=transition.new_status,
                activated_at=activated_at,
                exit_at=exit_at,
                exit_price=transition.exit_price,
                exit_reason=transition.exit_reason,
                pnl_ticks=transition.pnl_ticks,
                pnl_r=transition.pnl_r,
                pnl_dollars=transition.pnl_dollars,
            )
            self.lifecycle_transitions_total.inc()
            self.logger.info(
                "Signal transition",
                signal_id=transition.signal_id,
                new_status=transition.new_status,
                exit_reason=transition.exit_reason,
                pnl_r=transition.pnl_r,
            )
            transitions.append(transition)

        return transitions

    async def _process_single_bar(
        self,
        symbol: str,
        timeframe: str,
        fields: dict[bytes, bytes],
        stream_name: str,
        message_id: bytes,
    ) -> None:
        try:
            bar = {
                "high": float(fields[b"high"].decode()),
                "low": float(fields[b"low"].decode()),
                "close": float(fields[b"close"].decode()),
            }
            for tf in self.config["service"]["timeframes"]:
                await self._evaluate_signals_against_bar(symbol, tf, bar)

            await self.redis_client.xack(stream_name, self.consumer_group, message_id)

        except Exception as e:
            self.logger.error(
                "Error processing bar", symbol=symbol, error=str(e)
            )
            self.error_count_total.inc()

    async def _connect_redis(self) -> None:
        self.redis_client = redis.Redis(
            host=self.config["redis"]["host"],
            port=self.config["redis"]["port"],
            db=self.config["redis"]["db"],
            decode_responses=False,
        )
        await self.redis_client.ping()
        self.logger.info("Connected to Redis")

    async def _connect_database(self) -> None:
        try:
            self.db_manager = DatabaseManager(self.config["database"]["url"])
            await self.db_manager.initialize()
            self.logger.info("Connected to database")
        except Exception as e:
            self.logger.warning("Database unavailable, lifecycle tracking disabled", error=str(e))
            self.db_manager = None

    async def _setup_consumer_groups(self) -> None:
        # Subscribe to market:SYMBOL:1m only — OHLCV is all we need
        for symbol in self.config["service"]["symbols"]:
            stream_name = sk_market(self.env_prefix, symbol, "1m")
            try:
                await self.redis_client.xgroup_create(
                    stream_name, self.consumer_group, "0", mkstream=True
                )
            except Exception:
                pass

    async def _process_loop(self) -> None:
        while self.running and not self.shutdown_requested:
            try:
                for symbol in self.config["service"]["symbols"]:
                    stream_name = sk_market(self.env_prefix, symbol, "1m")
                    messages = await self.redis_client.xreadgroup(
                        self.consumer_group,
                        self.consumer_name,
                        {stream_name: ">"},
                        count=10,
                        block=100,
                    )
                    for _stream, msgs in messages:
                        for message_id, fields in msgs:
                            await self._process_single_bar(
                                symbol, "1m", fields, stream_name, message_id
                            )
                await asyncio.sleep(self.config["service"]["processing_interval"])
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in tracker loop", error=str(e))
                self.error_count_total.inc()
                await asyncio.sleep(1)

    async def _health_monitor_loop(self) -> None:
        while self.running and not self.shutdown_requested:
            try:
                uptime = int((datetime.now(tz=UTC) - self.start_time).total_seconds())
                self.service_uptime_seconds.set(uptime)
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break

    async def start(self) -> None:
        self.logger.info("Starting Signal Tracker Service", config=self.config["service"])
        try:
            await self._connect_redis()
            await self._connect_database()
            start_metrics_server(port=self.config.get("metrics_port", 9115))
            await self._setup_consumer_groups()
            self.running = True
            tasks = [
                asyncio.create_task(self._process_loop()),
                asyncio.create_task(self._health_monitor_loop()),
            ]
            self.logger.info("Signal Tracker Service started")
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            self.logger.error("Failed to start signal tracker", error=str(e))
            raise
        finally:
            await self.stop()

    async def stop(self) -> None:
        self.logger.info("Stopping Signal Tracker Service")
        self.running = False
        self.shutdown_requested = True
        if self.redis_client:
            await self.redis_client.aclose()
        if self.db_manager:
            await self.db_manager.close()
        self.logger.info("Signal Tracker Service stopped")


async def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Signal Tracker Service")
    parser.add_argument("--config", help="Config file path")
    args = parser.parse_args()
    service = SignalTrackerService(args.config)
    try:
        await service.start()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    asyncio.run(main())
```

### Step 3.4: Run tests

```bash
.venv/bin/python3 -m pytest tests/unit/service_tests/test_signal_tracker_service.py -v
```
Expected: 3 PASSED.

### Step 3.5: Write `config/signal_tracker_service.json`

```json
{
  "redis": {"host": "localhost", "port": 6379, "db": 0},
  "database": {"url": "postgresql://postgres:postgres@localhost:5432/indicagent"},
  "service": {
    "symbols": ["ESH6", "NQH6", "RTYH6"],
    "timeframes": ["1m", "5m", "15m", "1h"],
    "processing_interval": 0.1
  },
  "metrics_port": 9115,
  "logging": {"level": "INFO", "file": "logs/signal_tracker_service.log"}
}
```

### Step 3.6: Run full suite

```bash
.venv/bin/python3 -m pytest tests/unit/ --ignore=tests/integration -q
```
Expected: 453+ passed, 0 failed.

### Step 3.7: Commit

```bash
git add services/signal_tracker_service.py config/signal_tracker_service.json \
        tests/unit/service_tests/test_signal_tracker_service.py
git commit -m "feat: add signal_tracker_service — lifecycle tracking extracted from orchestrator"
```

---

## Task 4: Rename `signal_orchestrator_service.py` → `signal_generator_service.py`

Remove lifecycle tracking from the orchestrator. Drop the `_track_lifecycle` method, its call, and imports only used for lifecycle. Rename the file and class.

**Files:**
- Create: `services/signal_generator_service.py` (copy + strip lifecycle)
- Modify: `tests/unit/service_tests/test_signal_orchestrator_lifecycle.py` — add deprecation note
- Create: `config/signal_generator_service.json`

---

### Step 4.1: Write failing import test

```python
# Add to: tests/unit/service_tests/test_signal_orchestrator_signal_gen.py

def test_signal_generator_service_imports():
    """signal_generator_service must exist as the renamed orchestrator."""
    from services.signal_generator_service import SignalGeneratorService
    svc = SignalGeneratorService()
    assert hasattr(svc, "_run_setup_plugins")
    assert not hasattr(svc, "_track_lifecycle")  # lifecycle moved to signal_tracker_service
```

### Step 4.2: Run to confirm failure

```bash
.venv/bin/python3 -m pytest tests/unit/service_tests/test_signal_orchestrator_signal_gen.py::test_signal_generator_service_imports -v
```

### Step 4.3: Create `services/signal_generator_service.py`

Copy `services/signal_orchestrator_service.py` and make these changes:

**Remove from imports:**
```python
# REMOVE these — only used by _track_lifecycle:
from src.intelligence.trading.lifecycle_tracker import evaluate_signal
from src.intelligence.trading.signal_ledger import get_active_signals, update_signal_status
```
Keep: `insert_signals`, `LedgerEntry` — still used for signal insertion.

**Remove from `__init__`:**
```python
# REMOVE — only used by _track_lifecycle:
self.lifecycle_transitions_total = counter(...)
self.active_signals_count = gauge(...)
self.point_values: dict[str, float] = {...}
```

**Remove `_track_lifecycle` method entirely** (lines 484-547 in original).

**Remove lifecycle call from `_process_bar`:**
```python
# REMOVE this line from _process_bar:
await self._track_lifecycle(symbol, timeframe, bar, timestamp)
```

**Rename:**
- Class: `SignalOrchestratorService` → `SignalGeneratorService`
- Log string: `"Signal Orchestrator Service"` → `"Signal Generator Service"`
- Config log file: `"logs/signal_orchestrator.log"` → `"logs/signal_generator_service.log"`

### Step 4.4: Run tests

```bash
.venv/bin/python3 -m pytest tests/unit/service_tests/ -v
```
Expected: all PASSED. The existing orchestrator tests test `_run_setup_plugins`, `build_ledger_entries`, `parse_intelligence_message` — none of these change.

### Step 4.5: Write `config/signal_generator_service.json`

```json
{
  "redis": {"host": "localhost", "port": 6379, "db": 0},
  "database": {"url": "postgresql://postgres:postgres@localhost:5432/indicagent"},
  "service": {
    "symbols": ["ESH6", "NQH6", "RTYH6"],
    "timeframes": ["1m", "5m", "15m", "1h"],
    "min_history_bars": 50,
    "processing_interval": 0.1
  },
  "logging": {"level": "INFO", "file": "logs/signal_generator_service.log"}
}
```

### Step 4.6: Run full suite

```bash
.venv/bin/python3 -m pytest tests/unit/ --ignore=tests/integration -q
```
Expected: 453+ passed, 0 failed.

### Step 4.7: Commit

```bash
git add services/signal_generator_service.py config/signal_generator_service.json \
        tests/unit/service_tests/test_signal_orchestrator_signal_gen.py
git commit -m "feat: add signal_generator_service — I7 execution only, lifecycle tracking removed"
```

---

## Task 5: Retire obsolete services and update all references

**Files to delete:**
- `services/indicators_processor_service.py`
- `services/indicators_enhanced_service.py`

**Files to audit (may delete):**
- `services/coordination_parallel_service.py` — check if anything imports it or if any systemd unit refers to it

**Files to update:**
- `docs/for-ai-assistants/CLAUDE.md` — service table and run commands
- `README.md` — Quick Start run commands
- `services/README.md` — already updated in docs commit; verify systemd unit names

---

### Step 5.1: Verify no remaining imports of retired services

```bash
grep -r "indicators_processor_service\|indicators_enhanced_service" \
    --include="*.py" --include="*.md" --include="*.json" \
    . --exclude-dir=.git --exclude-dir=.venv --exclude-dir=dashboard/node_modules
```
Expected: zero results (only the files themselves).

### Step 5.2: Delete the retired service files

```bash
git rm services/indicators_processor_service.py services/indicators_enhanced_service.py
```

### Step 5.3: Audit `coordination_parallel_service.py`

```bash
grep -r "coordination_parallel_service" \
    --include="*.py" --include="*.md" --include="*.json" \
    . --exclude-dir=.git --exclude-dir=.venv --exclude-dir=dashboard/node_modules
```

If zero references and no unique logic not replicated by Redis consumer groups: `git rm services/coordination_parallel_service.py`

If still referenced: leave it and note it for a follow-up.

### Step 5.4: Update `CLAUDE.md` service commands section

In `docs/for-ai-assistants/CLAUDE.md`, find the `# Individual services` block (around line 70) and update:

```bash
# FROM (partial):
python services/indicators_processor_service.py --config config/indicator_processor_service.json
python services/indicators_enhanced_service.py --config config/enhanced_indicator_processor.json
python services/intelligence_processor_service.py --config config/intelligence_processor.json
python services/signal_orchestrator_service.py --config config/signal_orchestrator.json

# TO:
python services/indicator_service.py --config config/indicator_service.json
python services/market_analysis_service.py --config config/market_analysis_service.json
python services/signal_generator_service.py --config config/signal_generator_service.json
python services/signal_tracker_service.py --config config/signal_tracker_service.json
```

Also update the health endpoints table (`:9114` for market_analysis, `:9115` for signal_tracker).

Also fix the known issue in `### Development Priorities`:
- Add the 6 Track A indicator names to `I1_PLUGINS` in `indicator_service.py` (they are already included in the plan above — verify the list matches exactly).

### Step 5.5: Update `README.md` Quick Start commands

Find the run commands block (around line 120) and update to match the new service names.

### Step 5.6: Run full test suite and lint

```bash
.venv/bin/python3 -m pytest tests/unit/ --ignore=tests/integration -q
.venv/bin/ruff check . --fix
```
Expected: 453+ passed, 0 ruff errors.

### Step 5.7: Commit

```bash
git add -A
git commit -m "refactor: retire indicator_{processor,enhanced}_service, update all doc references"
```

---

## Task 6: Fix Track A I1_PLUGINS gap (bonus — trivial, do last)

The 6 Track A indicators (registered in registry but absent from `I1_PLUGINS`) are already included in `indicator_service.py` above. This task confirms they work in the new service.

### Step 6.1: Verify I1_PLUGINS list in `indicator_service.py` includes all 6

```python
# Must be present in I1_PLUGINS in services/indicator_service.py:
"ind_CMF", "ind_Aroon", "ind_HistoricalVolatility",
"ind_ChandelierExit", "ind_ParabolicSAR", "ind_StochRSI",
```

### Step 6.2: Run the existing Track A tests

```bash
.venv/bin/python3 -m pytest tests/unit/intelligence/test_cmf.py \
    tests/unit/intelligence/test_aroon.py \
    tests/unit/intelligence/test_historical_volatility.py \
    tests/unit/intelligence/test_chandelier.py \
    tests/unit/intelligence/test_parabolic_sar.py \
    tests/unit/intelligence/test_stochastic_rsi.py -v
```
Expected: all PASSED (these already pass — verifying the indicator logic is sound).

### Step 6.3: Commit (if any changes were needed)

```bash
git add services/indicator_service.py
git commit -m "fix: include 6 Track A indicators in indicator_service I1_PLUGINS"
```

---

## Completion Checklist

- [ ] `indicator_service.py` exists, tests pass, publishes combined OHLCV+I1 message
- [ ] `market_analysis_service.py` exists, consumes `indicators:SYMBOL:TF`, no inline I1
- [ ] `signal_tracker_service.py` exists, subscribes to `market:SYMBOL:1m`, tracks lifecycle
- [ ] `signal_generator_service.py` exists, no `_track_lifecycle`, no lifecycle imports
- [ ] `indicators_processor_service.py` deleted
- [ ] `indicators_enhanced_service.py` deleted
- [ ] `coordination_parallel_service.py` audited (deleted or noted)
- [ ] CLAUDE.md run commands updated
- [ ] README.md Quick Start updated
- [ ] Full test suite: 453+ passed, 0 ruff errors
- [ ] 6 Track A indicators in I1_PLUGINS and confirmed in pipeline
