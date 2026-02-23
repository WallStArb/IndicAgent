> **HISTORICAL DOCUMENT** — `intelligence_processor_service.py` was deleted in Phase 1 (2026-02-23). References to it in this doc are for historical context only. The canonical service is now `market_analysis_service.py`.

# Signal Orchestrator Service — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build `SignalOrchestratorService` — a single service that runs 5 I7 setup plugins on every bar, aggregates signals, persists all results to `signal_ledger`, publishes winners to SSE, and tracks signal lifecycle outcomes.

**Architecture:** Subscribes to `intelligence:*:*` stream (enriched with OHLCV fields — one modification to the upstream service). Maintains a bar history deque per symbol:timeframe. On each bar: run plugins → aggregate → insert ledger → publish winner → evaluate open signals → persist transitions.

**Tech Stack:** Python asyncio, redis-py, asyncpg, pandas, structlog, prometheus-client. All imports follow the pattern in `services/intelligence_processor_service.py`.

---

## Reference Files

Before starting, read these:
- `services/intelligence_processor_service.py` — service pattern to follow exactly
- `src/intelligence/trading/aggregator.py` — `aggregate()` function
- `src/intelligence/trading/signal_ledger.py` — `LedgerEntry`, `insert_signals()`, `update_signal_status()`, `get_active_signals()`
- `src/intelligence/trading/lifecycle_tracker.py` — `evaluate_signal()`, `Transition`
- `src/intelligence/trading/signal_schema.py` — `make_signal()`, field names
- `src/core/stream_keys.py` — `intelligence()`, `signals_aggregated()`, `intelligence_pattern()`
- `src/config/settings.py` — `get_point_value(symbol)` helper

---

## Task 1: Enrich Intelligence Stream with OHLCV

The intelligence stream currently carries only feature fields. Add the triggering bar's OHLCV so downstream services need only one stream.

**Files:**
- Modify: `services/intelligence_processor_service.py`
- Test: `tests/unit/service_tests/test_intelligence_processor_ohlcv.py`

**Step 1: Write the failing test**

```python
# tests/unit/service_tests/test_intelligence_processor_ohlcv.py
"""Tests that intelligence_processor_service enriches published messages with OHLCV."""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


@pytest.mark.asyncio
async def test_publish_intelligence_includes_ohlcv_fields():
    """Published intelligence message must include open/high/low/close/volume."""
    from services.intelligence_processor_service import IntelligenceProcessorService

    with patch("services.intelligence_processor_service.start_metrics_server"):
        svc = IntelligenceProcessorService()

    svc.redis_client = AsyncMock()
    svc.redis_client.xadd = AsyncMock()
    svc.env_prefix = ""

    bar_data = {
        "open": 5100.25, "high": 5105.50, "low": 5098.75,
        "close": 5103.00, "volume": 12345,
    }
    intelligence = {"trend_regime": 0.65, "atr_14": 12.5}
    from datetime import datetime, timezone
    ts = datetime(2026, 2, 18, 10, 0, 0, tzinfo=timezone.utc)

    await svc._publish_intelligence("ESH6", "5m", intelligence, ts, bar_data)

    call_args = svc.redis_client.xadd.call_args
    message = call_args[0][1]  # second positional arg is the message dict

    assert message["open"] == "5100.25"
    assert message["high"] == "5105.5"
    assert message["low"] == "5098.75"
    assert message["close"] == "5103.0"
    assert message["volume"] == "12345"
    assert message["trend_regime"] == "0.65"


@pytest.mark.asyncio
async def test_publish_intelligence_backward_compat_no_bar_data():
    """bar_data is optional — existing callers without it still work."""
    from services.intelligence_processor_service import IntelligenceProcessorService

    with patch("services.intelligence_processor_service.start_metrics_server"):
        svc = IntelligenceProcessorService()

    svc.redis_client = AsyncMock()
    svc.redis_client.xadd = AsyncMock()
    svc.env_prefix = ""

    from datetime import datetime, timezone
    ts = datetime(2026, 2, 18, 10, 0, 0, tzinfo=timezone.utc)

    # Must not raise even without bar_data
    await svc._publish_intelligence("ESH6", "5m", {"trend_regime": 0.5}, ts)

    assert svc.redis_client.xadd.called
```

**Step 2: Run test to verify it fails**

```bash
cd /home/brandon-goyette/development/indicagent
python -m pytest tests/unit/service_tests/test_intelligence_processor_ohlcv.py -v
```
Expected: FAIL — `_publish_intelligence` doesn't accept `bar_data` yet.

**Step 3: Modify `_publish_intelligence` in `intelligence_processor_service.py`**

Find the `_publish_intelligence` method (around line 588). Change its signature and add OHLCV fields:

```python
async def _publish_intelligence(
    self,
    symbol: str,
    timeframe: str,
    intelligence: dict[str, Any],
    timestamp: datetime,
    bar_data: dict[str, Any] | None = None,
) -> None:
    stream_name = sk_intelligence(self.env_prefix, symbol, timeframe)
    message: dict[str, str] = {
        "timestamp": timestamp.isoformat(),
        "symbol": symbol,
        "timeframe": timeframe,
    }
    # Include raw bar OHLCV so downstream services need only one stream
    if bar_data:
        message["open"]   = str(bar_data.get("open", ""))
        message["high"]   = str(bar_data.get("high", ""))
        message["low"]    = str(bar_data.get("low", ""))
        message["close"]  = str(bar_data.get("close", ""))
        message["volume"] = str(bar_data.get("volume", ""))
    for k, v in intelligence.items():
        message[k] = str(v)

    await self.redis_client.xadd(stream_name, message, maxlen=1000, approximate=True)
```

Then find the call site in `_process_single_bar` (where `_publish_intelligence` is called). Change it to pass `bar_data`:

```python
if intelligence:
    await self._publish_intelligence(
        symbol, timeframe, intelligence, bar_data["timestamp"], bar_data
    )
```

**Step 4: Run test to verify it passes**

```bash
python -m pytest tests/unit/service_tests/test_intelligence_processor_ohlcv.py -v
```
Expected: PASS (2 tests)

**Step 5: Run full suite to confirm no regressions**

```bash
python -m pytest tests/unit/ -q
```
Expected: all existing tests still passing.

**Step 6: Commit**

```bash
git add services/intelligence_processor_service.py tests/unit/service_tests/test_intelligence_processor_ohlcv.py
git commit -m "feat: enrich intelligence stream with OHLCV bar fields"
```

---

## Task 2: Helper Functions (parse + assemble)

These are pure functions — no Redis, no DB, easy to test in isolation. Build them first so the service class is thin.

**Files:**
- Create: `services/signal_orchestrator_service.py` (helpers section only)
- Test: `tests/unit/service_tests/test_signal_orchestrator_helpers.py`

**Step 1: Write the failing tests**

```python
# tests/unit/service_tests/test_signal_orchestrator_helpers.py
"""Tests for signal orchestrator helper functions."""
import pytest
from datetime import datetime, timezone


# ── parse_intelligence_message ────────────────────────────────────────────────

def test_parse_message_extracts_bar_fields():
    from services.signal_orchestrator_service import parse_intelligence_message

    msg = {
        b"timestamp": b"2026-02-18T10:00:00",
        b"symbol": b"ESH6",
        b"timeframe": b"5m",
        b"open": b"5100.25",
        b"high": b"5105.50",
        b"low": b"5098.75",
        b"close": b"5103.00",
        b"volume": b"12345",
        b"trend_regime": b"0.65",
        b"atr_14": b"12.5",
    }
    bar, features = parse_intelligence_message(msg)

    assert bar["open"] == 5100.25
    assert bar["high"] == 5105.50
    assert bar["low"] == 5098.75
    assert bar["close"] == 5103.00
    assert bar["volume"] == 12345
    assert "trend_regime" not in bar


def test_parse_message_extracts_feature_fields():
    from services.signal_orchestrator_service import parse_intelligence_message

    msg = {
        b"timestamp": b"2026-02-18T10:00:00",
        b"symbol": b"ESH6",
        b"timeframe": b"5m",
        b"open": b"5100.0",
        b"high": b"5105.0",
        b"low": b"5099.0",
        b"close": b"5103.0",
        b"volume": b"10000",
        b"trend_regime": b"0.65",
        b"atr_14": b"12.5",
        b"rsi_14": b"58.3",
    }
    bar, features = parse_intelligence_message(msg)

    assert features["trend_regime"] == 0.65
    assert features["atr_14"] == 12.5
    assert features["rsi_14"] == 58.3
    assert "open" not in features
    assert "symbol" not in features


def test_parse_message_handles_non_numeric_feature():
    """Non-numeric feature values are stored as strings (don't crash)."""
    from services.signal_orchestrator_service import parse_intelligence_message

    msg = {
        b"timestamp": b"2026-02-18T10:00:00",
        b"symbol": b"ESH6",
        b"timeframe": b"5m",
        b"open": b"5100.0",
        b"high": b"5105.0",
        b"low": b"5099.0",
        b"close": b"5103.0",
        b"volume": b"10000",
        b"trend_regime": b"0.65",
        b"hmm_regime_state": b"trending",
    }
    bar, features = parse_intelligence_message(msg)
    assert features["hmm_regime_state"] == "trending"


# ── build_ledger_entries ──────────────────────────────────────────────────────

def _make_signal(plugin: str, direction: int, rank: int) -> dict:
    return {
        "type": "signal.v1",
        "symbol": "ESH6",
        "timeframe": "5m",
        "timestamp": "2026-02-18T10:00:00",
        "signal_type": "trend_following",
        "setup_plugin": plugin,
        "direction": direction,
        "entry_price": 5103.0,
        "stop_loss": 5083.0,
        "targets": [5123.0, 5143.0, 5163.0],
        "confidence": 0.72,
        "risk_reward_ratio": 1.0,
        "regime_context": "trending_bull",
        "confluence_score": 0.8,
        "supporting_factors": ["trend_regime"],
        "invalidation_conditions": [],
        "ttl_bars": 20,
        "composite_rank": rank,
    }


def test_build_ledger_entries_winner_has_was_selected_true():
    from services.signal_orchestrator_service import build_ledger_entries
    from src.intelligence.trading.aggregator import AggregatedResult

    winner = _make_signal("trad_TrendFollowing", 1, 1)
    result = AggregatedResult(
        selected_signal=winner,
        all_ranked=[winner],
        resolution_method="sole",
        num_signals_fired=1,
        num_agreeing=1,
        num_conflicting=0,
    )
    ts = datetime(2026, 2, 18, 10, 0, 0, tzinfo=timezone.utc)
    features = {"trend_regime": 0.65, "ctf_score": 0.8}

    entries = build_ledger_entries(result, "ESH6", "5m", ts, features)

    assert len(entries) == 1
    assert entries[0].was_selected is True
    assert entries[0].symbol == "ESH6"
    assert entries[0].timeframe == "5m"
    assert entries[0].resolution_method == "sole"
    assert entries[0].num_signals_bar == 1


def test_build_ledger_entries_loser_has_was_selected_false():
    from services.signal_orchestrator_service import build_ledger_entries
    from src.intelligence.trading.aggregator import AggregatedResult

    winner = _make_signal("trad_LiquiditySweepReclaim", 1, 1)
    loser = _make_signal("trad_TrendFollowing", 1, 2)
    result = AggregatedResult(
        selected_signal=winner,
        all_ranked=[winner, loser],
        resolution_method="priority",
        num_signals_fired=2,
        num_agreeing=2,
        num_conflicting=0,
    )
    ts = datetime(2026, 2, 18, 10, 0, 0, tzinfo=timezone.utc)

    entries = build_ledger_entries(result, "ESH6", "5m", ts, {})

    assert len(entries) == 2
    assert entries[0].was_selected is True   # rank 1
    assert entries[1].was_selected is False  # rank 2


def test_build_ledger_entries_no_signal_all_false():
    from services.signal_orchestrator_service import build_ledger_entries
    from src.intelligence.trading.aggregator import AggregatedResult

    sig1 = _make_signal("trad_TrendFollowing", 1, 1)
    sig2 = _make_signal("trad_MeanReversion", -1, 2)
    result = AggregatedResult(
        selected_signal=None,
        all_ranked=[sig1, sig2],
        resolution_method="no_signal",
        num_signals_fired=2,
        num_agreeing=0,
        num_conflicting=2,
    )
    ts = datetime(2026, 2, 18, 10, 0, 0, tzinfo=timezone.utc)

    entries = build_ledger_entries(result, "ESH6", "5m", ts, {})

    assert len(entries) == 2
    assert all(e.was_selected is False for e in entries)


def test_build_ledger_entries_snapshots_market_context():
    from services.signal_orchestrator_service import build_ledger_entries, MARKET_CONTEXT_KEYS
    from src.intelligence.trading.aggregator import AggregatedResult

    winner = _make_signal("trad_TrendFollowing", 1, 1)
    result = AggregatedResult(
        selected_signal=winner,
        all_ranked=[winner],
        resolution_method="sole",
        num_signals_fired=1,
        num_agreeing=1,
        num_conflicting=0,
    )
    ts = datetime(2026, 2, 18, 10, 0, 0, tzinfo=timezone.utc)
    features = {k: 0.5 for k in MARKET_CONTEXT_KEYS}
    features["extra_field"] = 99.9

    entries = build_ledger_entries(result, "ESH6", "5m", ts, features)

    ctx = entries[0].market_context
    assert "extra_field" not in ctx
    for k in MARKET_CONTEXT_KEYS:
        assert k in ctx


def test_build_ledger_entries_returns_empty_when_no_ranked():
    from services.signal_orchestrator_service import build_ledger_entries
    from src.intelligence.trading.aggregator import AggregatedResult

    result = AggregatedResult(
        selected_signal=None,
        all_ranked=[],
        resolution_method="no_signal",
        num_signals_fired=0,
        num_agreeing=0,
        num_conflicting=0,
    )
    ts = datetime(2026, 2, 18, 10, 0, 0, tzinfo=timezone.utc)
    assert build_ledger_entries(result, "ESH6", "5m", ts, {}) == []
```

**Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/unit/service_tests/test_signal_orchestrator_helpers.py -v
```
Expected: FAIL — module doesn't exist yet.

**Step 3: Create `services/signal_orchestrator_service.py` with helper functions**

```python
#!/usr/bin/env python3
"""
Signal Orchestrator Service — I7 plugin execution, aggregation, and lifecycle tracking

Subscribes to intelligence:SYMBOL:TF stream (enriched with OHLCV by intelligence_processor).
On each bar: runs 5 I7 setup plugins, aggregates signals, inserts all to signal_ledger,
publishes winner to signals:SYMBOL:TF:aggregated, and tracks open signal lifecycle.

Version: 1.0.0
Last Updated: 2026-02-18
Status: Production Ready
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from logging.handlers import RotatingFileHandler  # noqa: E402

import pandas as pd  # noqa: E402
import redis.asyncio as redis  # noqa: E402
import structlog  # noqa: E402

from src.config.settings import Settings, get_point_value  # noqa: E402
from src.core.database_manager import DatabaseManager  # noqa: E402
from src.core.stream_keys import (  # noqa: E402
    intelligence_pattern,
    signals_aggregated,
)
from src.intelligence.plugins import registry  # noqa: E402
from src.intelligence.register_plugins import register_all_plugins  # noqa: E402
from src.intelligence.trading.aggregator import AggregatedResult, aggregate  # noqa: E402
from src.intelligence.trading.lifecycle_tracker import evaluate_signal  # noqa: E402
from src.intelligence.trading.signal_ledger import (  # noqa: E402
    LedgerEntry,
    get_active_signals,
    insert_signals,
    update_signal_status,
)
from src.observability.metrics import (  # noqa: E402
    counter,
    gauge,
    record_plugin_execution,
    start_metrics_server,
)

# I7 trading setup plugin names (must match names in register_plugins.py)
I7_PLUGINS = [
    "trad_TrendFollowing",
    "trad_MeanReversion",
    "trad_LiquiditySweepReclaim",
    "trad_MTFAlignment",
    "trad_SqueezeExpansion",
]

# Fields that are metadata / OHLCV — everything else is a feature
_META_FIELDS = frozenset({
    "timestamp", "symbol", "timeframe",
    "open", "high", "low", "close", "volume",
})

# Fixed set of features to snapshot as market_context JSONB.
# Must remain stable across versions — ML training depends on consistent feature vectors.
MARKET_CONTEXT_KEYS: tuple[str, ...] = (
    "trend_regime",
    "volatility_regime",
    "trend_confidence",
    "atr_14",
    "rsi_14",
    "ctf_score",
    "swing_pattern",
    "trend_strength",
    "volatility_percentile",
    "hmm_regime_state",
)

# TTL bars by timeframe: how many bars before an unfilled signal expires
_TTL_BY_TIMEFRAME: dict[str, int] = {
    "1m": 30,
    "5m": 20,
    "15m": 12,
    "1h": 6,
}
_TTL_DEFAULT = 10


# ---------------------------------------------------------------------------
# Pure helper functions (no I/O — easy to test)
# ---------------------------------------------------------------------------

def parse_intelligence_message(
    fields: dict[bytes, bytes],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split an intelligence stream message into (bar_dict, features_dict).

    bar_dict contains OHLCV values as floats/int.
    features_dict contains all other numeric fields as floats; non-numeric as strings.
    """
    bar: dict[str, Any] = {}
    features: dict[str, Any] = {}

    for raw_key, raw_val in fields.items():
        key = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
        val = raw_val.decode() if isinstance(raw_val, bytes) else str(raw_val)

        if key in _META_FIELDS:
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
            # timestamp/symbol/timeframe not added to bar — caller knows them
        else:
            try:
                features[key] = float(val)
            except (ValueError, TypeError):
                features[key] = val

    return bar, features


def build_ledger_entries(
    result: AggregatedResult,
    symbol: str,
    timeframe: str,
    timestamp: datetime,
    features: dict[str, Any],
) -> list[LedgerEntry]:
    """Build LedgerEntry list from an AggregatedResult.

    All ranked signals are logged (winners and losers). was_selected=True only
    for the rank-1 signal when a winner was chosen.
    """
    if not result.all_ranked:
        return []

    market_ctx = {k: features.get(k, None) for k in MARKET_CONTEXT_KEYS
                  if features.get(k) is not None}

    entries = []
    for sig in result.all_ranked:
        rank = sig.get("composite_rank", 99)
        was_selected = (rank == 1 and result.selected_signal is not None)
        entries.append(LedgerEntry(
            signal_id=str(uuid4()),
            timestamp=timestamp,
            symbol=symbol,
            timeframe=timeframe,
            setup_plugin=sig.get("setup_plugin", "unknown"),
            signal_type=sig.get("signal_type", "unknown"),
            direction=int(sig.get("direction", 0)),
            entry_price=float(sig.get("entry_price", 0.0)),
            stop_loss=float(sig.get("stop_loss", 0.0)),
            targets=[float(t) for t in sig.get("targets", [])],
            confidence=float(sig.get("confidence", 0.0)),
            confluence_score=float(sig.get("confluence_score", 0.0)),
            regime_context=str(sig.get("regime_context", "")),
            supporting_factors=list(sig.get("supporting_factors", [])),
            was_selected=was_selected,
            num_signals_bar=result.num_signals_fired,
            num_agreeing=result.num_agreeing,
            num_conflicting=result.num_conflicting,
            resolution_method=result.resolution_method,
            composite_rank=rank,
            market_context=market_ctx,
            status="pending",
        ))
    return entries
```

**Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/unit/service_tests/test_signal_orchestrator_helpers.py -v
```
Expected: PASS (8 tests)

**Step 5: Commit**

```bash
git add services/signal_orchestrator_service.py tests/unit/service_tests/test_signal_orchestrator_helpers.py
git commit -m "feat: signal orchestrator helpers - parse + assemble ledger entries"
```

---

## Task 3: Service Class Skeleton

**Files:**
- Modify: `services/signal_orchestrator_service.py` (add class)
- Test: `tests/unit/service_tests/test_signal_orchestrator_init.py`

**Step 1: Write the failing tests**

```python
# tests/unit/service_tests/test_signal_orchestrator_init.py
"""Tests for SignalOrchestratorService initialization."""
from unittest.mock import patch
import pytest


def test_service_loads_default_config():
    from services.signal_orchestrator_service import SignalOrchestratorService

    with patch("services.signal_orchestrator_service.start_metrics_server"):
        svc = SignalOrchestratorService()

    assert "symbols" in svc.config["service"]
    assert "timeframes" in svc.config["service"]
    assert svc.config["service"]["min_history_bars"] == 50


def test_service_loads_custom_config(tmp_path):
    import json
    config_file = tmp_path / "test_config.json"
    config_file.write_text(json.dumps({
        "service": {"symbols": ["ESH6"], "timeframes": ["15m"]}
    }))

    from services.signal_orchestrator_service import SignalOrchestratorService

    with patch("services.signal_orchestrator_service.start_metrics_server"):
        svc = SignalOrchestratorService(str(config_file))

    assert svc.config["service"]["symbols"] == ["ESH6"]
    assert svc.config["service"]["timeframes"] == ["15m"]


def test_service_builds_point_value_map():
    from services.signal_orchestrator_service import SignalOrchestratorService

    with patch("services.signal_orchestrator_service.start_metrics_server"):
        svc = SignalOrchestratorService()

    # Must have point_values for configured symbols
    # Each symbol maps to its contract's point_value (or 1.0 if unknown)
    assert isinstance(svc.point_values, dict)
    for sym in svc.config["service"]["symbols"]:
        assert sym in svc.point_values
        assert isinstance(svc.point_values[sym], float)
```

**Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/unit/service_tests/test_signal_orchestrator_init.py -v
```
Expected: FAIL — class doesn't exist yet.

**Step 3: Add `SignalOrchestratorService` class to `services/signal_orchestrator_service.py`**

Append this class after the helper functions:

```python
class SignalOrchestratorService:
    """Execute I7 setup plugins, aggregate signals, persist, and track lifecycle."""

    def __init__(self, config_file: str | None = None):
        self.running = False
        self.shutdown_requested = False
        self.start_time = datetime.now(tz=timezone.utc)

        self.config = self._load_config(config_file)
        self._setup_logging()

        register_all_plugins()

        self.redis_client: redis.Redis | None = None
        self.db_manager: DatabaseManager | None = None
        self.consumer_group = f"signal_orchestrator_{int(time.time())}"
        self.consumer_name = f"orchestrator_{os.getpid()}"

        settings = Settings()
        self.env_prefix = f"{settings.env_name}:" if settings.env_name else ""

        # Bar history per symbol:timeframe key
        self.bar_history: dict[str, deque] = defaultdict(lambda: deque(maxlen=200))

        # point_value lookup: symbol → dollars per point
        self.point_values: dict[str, float] = {
            sym: float(get_point_value(sym) or 1.0)
            for sym in self.config["service"]["symbols"]
        }

        # Prometheus metrics
        self.bars_processed_total = counter(
            "orchestrator_bars_processed_total",
            "Total intelligence events processed by orchestrator",
        )
        self.signals_generated_total = counter(
            "orchestrator_signals_generated_total",
            "Total signals inserted to signal_ledger",
        )
        self.signals_selected_total = counter(
            "orchestrator_signals_selected_total",
            "Total signals where was_selected=True",
        )
        self.lifecycle_transitions_total = counter(
            "orchestrator_lifecycle_transitions_total",
            "Total signal status updates",
        )
        self.calculation_duration_ms = gauge(
            "orchestrator_calculation_duration_ms",
            "Per-bar processing time in milliseconds",
        )
        self.active_signals_count = gauge(
            "orchestrator_active_signals_count",
            "Current count of pending/active signals",
        )
        self.service_uptime_seconds = gauge(
            "orchestrator_service_uptime_seconds",
            "Orchestrator service uptime in seconds",
        )
        self.error_count_total = counter(
            "orchestrator_errors_total",
            "Total errors encountered by orchestrator",
        )

        self._total_bars = 0
        self._total_signals = 0
        self._total_transitions = 0
        self._error_count = 0

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self.logger = structlog.get_logger(__name__)
        start_metrics_server(port=9112)

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def _load_config(self, config_file: str | None) -> dict[str, Any]:
        try:
            _settings = Settings()
        except Exception:
            _settings = None

        default_config: dict[str, Any] = {
            "redis": {"host": "localhost", "port": 6379, "db": 0},
            "database": {
                "url": (
                    _settings.database_url
                    if _settings and getattr(_settings, "database_url", None)
                    else "postgresql://postgres:postgres@localhost:5432/indicagent"
                )
            },
            "service": {
                "symbols": ["ESH6", "NQH6", "RTYH6"],
                "timeframes": ["5m", "15m"],
                "min_history_bars": 50,
                "processing_interval": 0.1,
                "health_check_interval": 30,
            },
            "logging": {
                "level": "INFO",
                "file": "logs/signal_orchestrator.log",
                "max_size": "10MB",
                "backup_count": 5,
            },
        }

        if config_file and Path(config_file).exists():
            with open(config_file) as f:
                user_config = json.load(f)
            for key, value in user_config.items():
                if isinstance(value, dict) and key in default_config:
                    default_config[key].update(value)
                else:
                    default_config[key] = value

        return default_config

    def _setup_logging(self) -> None:
        log_dir = Path(self.config["logging"]["file"]).parent
        log_dir.mkdir(exist_ok=True)

        file_handler = RotatingFileHandler(
            self.config["logging"]["file"],
            maxBytes=10 * 1024 * 1024,
            backupCount=self.config["logging"].get("backup_count", 5),
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

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

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
            self.logger.warning("Database unavailable, persistence disabled", error=str(e))
            self.db_manager = None

    async def _setup_consumer_groups(self) -> None:
        for tf in self.config["service"]["timeframes"]:
            for sym in self.config["service"]["symbols"]:
                from src.core.stream_keys import intelligence as sk_intel
                stream_name = sk_intel(self.env_prefix, sym, tf)
                try:
                    await self.redis_client.xgroup_create(
                        stream_name, self.consumer_group, "0", mkstream=True
                    )
                except Exception:
                    pass  # Group already exists

    async def stop(self) -> None:
        self.logger.info("Stopping Signal Orchestrator Service")
        self.running = False
        self.shutdown_requested = True
        if self.redis_client:
            await self.redis_client.aclose()
        if self.db_manager:
            await self.db_manager.close()
        self.logger.info("Signal Orchestrator Service stopped")
```

**Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/unit/service_tests/test_signal_orchestrator_init.py -v
```
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add services/signal_orchestrator_service.py tests/unit/service_tests/test_signal_orchestrator_init.py
git commit -m "feat: signal orchestrator service skeleton"
```

---

## Task 4: Signal Generation Path

The core logic: run I7 plugins, aggregate, insert, publish.

**Files:**
- Modify: `services/signal_orchestrator_service.py` (add `_run_setup_plugins`, `_process_bar` signal section)
- Test: `tests/unit/service_tests/test_signal_orchestrator_signal_gen.py`

**Step 1: Write the failing tests**

```python
# tests/unit/service_tests/test_signal_orchestrator_signal_gen.py
"""Tests for signal generation path: plugins → aggregate → insert → publish."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


def _make_frames(n_bars: int = 60) -> dict:
    import pandas as pd
    import numpy as np
    bars = pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=n_bars, freq="5min"),
        "open":  5100.0 + np.random.randn(n_bars),
        "high":  5105.0 + np.random.randn(n_bars),
        "low":   5095.0 + np.random.randn(n_bars),
        "close": 5100.0 + np.random.randn(n_bars),
        "volume": np.random.randint(1000, 5000, n_bars),
    })
    return {"main": bars, "features": {"trend_regime": 0.7, "atr_14": 12.5}}


def _make_service():
    with patch("services.signal_orchestrator_service.start_metrics_server"):
        from services.signal_orchestrator_service import SignalOrchestratorService
        return SignalOrchestratorService()


def test_run_setup_plugins_returns_only_directional_signals():
    """Only signals with direction != 0 are returned."""
    svc = _make_service()

    from src.intelligence.register_plugins import register_all_plugins
    register_all_plugins()

    frames = _make_frames(60)
    signals = svc._run_setup_plugins(frames)

    # All returned signals must have a real direction
    for sig in signals:
        assert sig.get("direction", 0) != 0
        assert "setup_plugin" in sig


def test_run_setup_plugins_handles_plugin_failure_gracefully():
    """If a plugin raises, the others still run."""
    svc = _make_service()

    from src.intelligence.register_plugins import register_all_plugins
    register_all_plugins()

    from src.intelligence.plugins import registry
    original = registry.get_pattern("trad_TrendFollowing").compute_full

    def boom(frames):
        raise RuntimeError("plugin exploded")

    registry.get_pattern("trad_TrendFollowing").compute_full = boom
    try:
        frames = _make_frames(60)
        signals = svc._run_setup_plugins(frames)
        # Should not raise; other plugins still ran (result may be empty or not)
        assert isinstance(signals, list)
    finally:
        registry.get_pattern("trad_TrendFollowing").compute_full = original


@pytest.mark.asyncio
async def test_process_bar_inserts_signals_when_plugins_fire():
    """When plugins produce signals, they are inserted into signal_ledger."""
    svc = _make_service()
    svc.db_manager = MagicMock()
    svc.redis_client = AsyncMock()
    svc.redis_client.xadd = AsyncMock()

    # Mock insert_signals to capture calls
    with patch("services.signal_orchestrator_service.insert_signals", new=AsyncMock()) as mock_insert:
        with patch("services.signal_orchestrator_service.get_active_signals", new=AsyncMock(return_value=[])):
            frames = _make_frames(60)
            bar = {"open": 5100.0, "high": 5105.0, "low": 5098.0, "close": 5103.0, "volume": 10000}
            features = {"trend_regime": 0.7, "atr_14": 12.5, "ctf_score": 0.8}
            ts = datetime(2026, 2, 18, 10, 0, 0, tzinfo=timezone.utc)

            # Inject fake plugin signals
            fake_signal = {
                "type": "signal.v1", "signal_type": "trend_following",
                "setup_plugin": "trad_TrendFollowing", "direction": 1,
                "entry_price": 5103.0, "stop_loss": 5083.0,
                "targets": [5123.0, 5143.0, 5163.0],
                "confidence": 0.72, "risk_reward_ratio": 1.0,
                "regime_context": "trending_bull", "confluence_score": 0.8,
                "supporting_factors": [], "invalidation_conditions": [],
                "ttl_bars": 20, "symbol": "ESH6", "timeframe": "5m",
                "timestamp": "2026-02-18T10:00:00",
            }
            with patch.object(svc, "_run_setup_plugins", return_value=[fake_signal]):
                await svc._process_bar("ESH6", "5m", bar, features, frames, ts)

        # insert_signals was called with at least one entry
        assert mock_insert.called
        entries = mock_insert.call_args[0][1]
        assert len(entries) >= 1


@pytest.mark.asyncio
async def test_process_bar_publishes_winner_to_redis():
    """When aggregate selects a winner, it publishes to signals_aggregated stream."""
    svc = _make_service()
    svc.db_manager = MagicMock()
    svc.redis_client = AsyncMock()
    svc.redis_client.xadd = AsyncMock()

    with patch("services.signal_orchestrator_service.insert_signals", new=AsyncMock()):
        with patch("services.signal_orchestrator_service.get_active_signals", new=AsyncMock(return_value=[])):
            fake_signal = {
                "type": "signal.v1", "signal_type": "trend_following",
                "setup_plugin": "trad_TrendFollowing", "direction": 1,
                "entry_price": 5103.0, "stop_loss": 5083.0,
                "targets": [5123.0, 5143.0, 5163.0],
                "confidence": 0.72, "risk_reward_ratio": 1.0,
                "regime_context": "trending_bull", "confluence_score": 0.8,
                "supporting_factors": [], "invalidation_conditions": [],
                "ttl_bars": 20, "symbol": "ESH6", "timeframe": "5m",
                "timestamp": "2026-02-18T10:00:00",
            }
            bar = {"open": 5100.0, "high": 5105.0, "low": 5098.0, "close": 5103.0, "volume": 10000}
            features = {"trend_regime": 0.7, "ctf_score": 0.8}
            ts = datetime(2026, 2, 18, 10, 0, 0, tzinfo=timezone.utc)
            frames = _make_frames(60)

            with patch.object(svc, "_run_setup_plugins", return_value=[fake_signal]):
                await svc._process_bar("ESH6", "5m", bar, features, frames, ts)

    # xadd must have been called for the aggregated stream
    assert svc.redis_client.xadd.called


@pytest.mark.asyncio
async def test_process_bar_skips_when_too_few_bars():
    """Processing is skipped when bar history is below min_history_bars."""
    svc = _make_service()
    svc.db_manager = MagicMock()
    svc.redis_client = AsyncMock()

    with patch("services.signal_orchestrator_service.insert_signals", new=AsyncMock()) as mock_insert:
        import pandas as pd
        # Only 10 bars — below min_history_bars=50
        frames = {"main": pd.DataFrame({"close": [100.0] * 10}), "features": {}}
        bar = {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000}
        ts = datetime(2026, 2, 18, 10, 0, 0, tzinfo=timezone.utc)

        await svc._process_bar("ESH6", "5m", bar, {}, frames, ts)

    assert not mock_insert.called
```

**Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/unit/service_tests/test_signal_orchestrator_signal_gen.py -v
```
Expected: FAIL — `_run_setup_plugins` and `_process_bar` don't exist yet.

**Step 3: Add signal generation methods to the service class**

Add these methods inside `SignalOrchestratorService`:

```python
    # ------------------------------------------------------------------
    # Signal generation
    # ------------------------------------------------------------------

    def _run_setup_plugins(self, frames: dict[str, Any]) -> list[dict]:
        """Run all 5 I7 setup plugins and return only directional signals."""
        signals = []
        for name in I7_PLUGINS:
            t0 = time.time()
            try:
                plugin = registry.get_pattern(name)
                result = plugin.compute_full(frames)
                elapsed = time.time() - t0
                if result and result.get("direction", 0) != 0:
                    result["setup_plugin"] = name
                    signals.append(result)
                    record_plugin_execution(name, "", "", elapsed, "success", "I7")
                else:
                    record_plugin_execution(name, "", "", elapsed, "no_signal", "I7")
            except Exception as e:
                self.logger.warning("I7 plugin failed", plugin=name, error=str(e))
                record_plugin_execution(name, "", "", time.time() - t0, "error", "I7")
        return signals

    async def _process_bar(
        self,
        symbol: str,
        timeframe: str,
        bar: dict[str, Any],
        features: dict[str, Any],
        frames: dict[str, Any],
        timestamp: datetime,
    ) -> None:
        """Full per-bar pipeline: generate signals, aggregate, persist, track lifecycle."""
        df = frames.get("main")
        min_bars = self.config["service"]["min_history_bars"]
        if df is None or len(df) < min_bars:
            return

        calc_start = time.time()

        # --- Signal generation ---
        raw_signals = self._run_setup_plugins(frames)
        trend_regime = float(features.get("trend_regime", 0.0))
        result = aggregate(raw_signals, trend_regime=trend_regime)

        entries = build_ledger_entries(result, symbol, timeframe, timestamp, features)
        if entries and self.db_manager:
            await insert_signals(self.db_manager, entries)
            selected_count = sum(1 for e in entries if e.was_selected)
            self.signals_generated_total.inc(len(entries))
            self.signals_selected_total.inc(selected_count)
            self._total_signals += len(entries)

        if result.selected_signal and self.redis_client:
            stream_name = signals_aggregated(self.env_prefix, symbol, timeframe)
            message = {
                k: str(v) for k, v in result.selected_signal.items()
                if isinstance(v, (str, int, float, bool))
            }
            message["timestamp"] = timestamp.isoformat()
            message["symbol"] = symbol
            message["timeframe"] = timeframe
            await self.redis_client.xadd(stream_name, message, maxlen=200, approximate=True)

        # --- Lifecycle tracking ---
        await self._track_lifecycle(symbol, timeframe, bar, timestamp)

        elapsed_ms = (time.time() - calc_start) * 1000
        self.bars_processed_total.inc()
        self.calculation_duration_ms.set(elapsed_ms)
        self._total_bars += 1

        self.logger.debug(
            "Bar processed",
            symbol=symbol,
            timeframe=timeframe,
            signals_fired=result.num_signals_fired,
            selected=result.selected_signal is not None,
            resolution=result.resolution_method,
            calc_ms=round(elapsed_ms, 2),
        )
```

**Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/unit/service_tests/test_signal_orchestrator_signal_gen.py -v
```
Expected: PASS (5 tests)

**Step 5: Commit**

```bash
git add services/signal_orchestrator_service.py tests/unit/service_tests/test_signal_orchestrator_signal_gen.py
git commit -m "feat: signal orchestrator signal generation path"
```

---

## Task 5: Lifecycle Tracking Path

**Files:**
- Modify: `services/signal_orchestrator_service.py` (add `_track_lifecycle`)
- Test: `tests/unit/service_tests/test_signal_orchestrator_lifecycle.py`

**Step 1: Write the failing tests**

```python
# tests/unit/service_tests/test_signal_orchestrator_lifecycle.py
"""Tests for lifecycle tracking path."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


def _make_service():
    with patch("services.signal_orchestrator_service.start_metrics_server"):
        from services.signal_orchestrator_service import SignalOrchestratorService
        return SignalOrchestratorService()


def _active_signal(signal_id: str, status: str = "pending", direction: int = 1) -> dict:
    return {
        "signal_id": signal_id,
        "status": status,
        "direction": direction,
        "entry_price": 5103.0,
        "stop_loss": 5083.0,
        "targets": [5123.0, 5143.0, 5163.0],
        "ttl_bars": 20,
        "bars_elapsed": 0,
        "point_value": 50.0,
        "timeframe": "5m",
    }


@pytest.mark.asyncio
async def test_track_lifecycle_activates_pending_signal():
    """Pending signal transitions to active when high >= entry."""
    svc = _make_service()
    svc.db_manager = MagicMock()

    pending = _active_signal("test-uuid-1", status="pending", direction=1)

    with patch("services.signal_orchestrator_service.get_active_signals",
               new=AsyncMock(return_value=[pending])):
        with patch("services.signal_orchestrator_service.update_signal_status",
                   new=AsyncMock()) as mock_update:
            bar = {"open": 5100.0, "high": 5104.0, "low": 5099.0, "close": 5103.0}
            ts = datetime(2026, 2, 18, 10, 5, 0, tzinfo=timezone.utc)
            await svc._track_lifecycle("ESH6", "5m", bar, ts)

    mock_update.assert_called_once()
    call_kwargs = mock_update.call_args.kwargs
    assert call_kwargs["status"] == "active"


@pytest.mark.asyncio
async def test_track_lifecycle_stops_out_active_signal():
    """Active signal transitions to stopped_out when low <= stop_loss."""
    svc = _make_service()
    svc.db_manager = MagicMock()

    active = _active_signal("test-uuid-2", status="active", direction=1)

    with patch("services.signal_orchestrator_service.get_active_signals",
               new=AsyncMock(return_value=[active])):
        with patch("services.signal_orchestrator_service.update_signal_status",
                   new=AsyncMock()) as mock_update:
            # Low dips below stop_loss (5083.0)
            bar = {"open": 5085.0, "high": 5086.0, "low": 5080.0, "close": 5082.0}
            ts = datetime(2026, 2, 18, 10, 10, 0, tzinfo=timezone.utc)
            await svc._track_lifecycle("ESH6", "5m", bar, ts)

    mock_update.assert_called_once()
    call_kwargs = mock_update.call_args.kwargs
    assert call_kwargs["status"] == "stopped_out"
    assert call_kwargs["pnl_r"] < 0


@pytest.mark.asyncio
async def test_track_lifecycle_skips_different_timeframe_signals():
    """Signals from a different timeframe are NOT evaluated on this bar."""
    svc = _make_service()
    svc.db_manager = MagicMock()

    signal_1h = _active_signal("test-uuid-3", status="pending")
    signal_1h["timeframe"] = "1h"  # This is a 1h signal

    with patch("services.signal_orchestrator_service.get_active_signals",
               new=AsyncMock(return_value=[signal_1h])):
        with patch("services.signal_orchestrator_service.update_signal_status",
                   new=AsyncMock()) as mock_update:
            # We're processing a 5m bar
            bar = {"open": 5100.0, "high": 5104.0, "low": 5099.0, "close": 5103.0}
            ts = datetime(2026, 2, 18, 10, 5, 0, tzinfo=timezone.utc)
            await svc._track_lifecycle("ESH6", "5m", bar, ts)

    assert not mock_update.called  # 1h signal not evaluated on 5m bar


@pytest.mark.asyncio
async def test_track_lifecycle_no_update_when_no_transition():
    """No DB update when signal price conditions aren't met."""
    svc = _make_service()
    svc.db_manager = MagicMock()

    pending = _active_signal("test-uuid-4", status="pending", direction=1)

    with patch("services.signal_orchestrator_service.get_active_signals",
               new=AsyncMock(return_value=[pending])):
        with patch("services.signal_orchestrator_service.update_signal_status",
                   new=AsyncMock()) as mock_update:
            # High (5101) below entry (5103) — no activation
            bar = {"open": 5098.0, "high": 5101.0, "low": 5097.0, "close": 5099.0}
            ts = datetime(2026, 2, 18, 10, 5, 0, tzinfo=timezone.utc)
            await svc._track_lifecycle("ESH6", "5m", bar, ts)

    assert not mock_update.called
```

**Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/unit/service_tests/test_signal_orchestrator_lifecycle.py -v
```
Expected: FAIL — `_track_lifecycle` doesn't exist yet.

**Step 3: Add `_track_lifecycle` to the service class**

```python
    # ------------------------------------------------------------------
    # Lifecycle tracking
    # ------------------------------------------------------------------

    async def _track_lifecycle(
        self,
        symbol: str,
        timeframe: str,
        bar: dict[str, Any],
        timestamp: datetime,
    ) -> None:
        """Evaluate open signals and persist any state transitions."""
        if not self.db_manager:
            return

        active = await get_active_signals(self.db_manager, symbol=symbol)
        # Only evaluate signals that belong to THIS timeframe
        relevant = [s for s in active if s.get("timeframe") == timeframe]
        self.active_signals_count.set(len(relevant))

        for sig in relevant:
            # Inject point_value from settings (not stored in DB)
            sig_with_pv = {
                **sig,
                "point_value": self.point_values.get(symbol, 1.0),
            }
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
            self._total_transitions += 1
            self.logger.info(
                "Signal transition",
                signal_id=transition.signal_id,
                new_status=transition.new_status,
                exit_reason=transition.exit_reason,
                pnl_r=transition.pnl_r,
            )
```

**Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/unit/service_tests/test_signal_orchestrator_lifecycle.py -v
```
Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add services/signal_orchestrator_service.py tests/unit/service_tests/test_signal_orchestrator_lifecycle.py
git commit -m "feat: signal orchestrator lifecycle tracking path"
```

---

## Task 6: Main Loop, Health Monitor, Config, Entry Point

Wire the service into a runnable process.

**Files:**
- Modify: `services/signal_orchestrator_service.py` (add `start`, loop, health monitor, `main()`)
- Create: `config/signal_orchestrator.json`

**Step 1: Add `start`, `_process_loop`, `_health_monitor_loop`, and `main()` to the service**

```python
    # ------------------------------------------------------------------
    # Main service loop
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self.logger.info("Starting Signal Orchestrator Service", config=self.config["service"])
        try:
            await self._connect_redis()
            await self._connect_database()
            await self._setup_consumer_groups()

            self.running = True
            tasks = [
                asyncio.create_task(self._process_loop()),
                asyncio.create_task(self._health_monitor_loop()),
            ]
            self.logger.info("Signal Orchestrator Service started")
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            self.logger.error("Failed to start orchestrator", error=str(e))
            raise
        finally:
            await self.stop()

    async def _process_loop(self) -> None:
        """Consume intelligence stream events and process each bar."""
        from src.core.stream_keys import intelligence as sk_intel

        self.logger.info("Starting intelligence stream processing loop")

        while self.running and not self.shutdown_requested:
            try:
                for tf in self.config["service"]["timeframes"]:
                    for sym in self.config["service"]["symbols"]:
                        stream_name = sk_intel(self.env_prefix, sym, tf)
                        messages = await self.redis_client.xreadgroup(
                            self.consumer_group,
                            self.consumer_name,
                            {stream_name: ">"},
                            count=10,
                            block=100,
                        )
                        for _stream, msgs in messages:
                            for message_id, fields in msgs:
                                await self._process_single_message(
                                    sym, tf, fields, stream_name, message_id
                                )

                await asyncio.sleep(self.config["service"]["processing_interval"])

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in processing loop", error=str(e))
                self.error_count_total.inc()
                self._error_count += 1
                await asyncio.sleep(1)

    async def _process_single_message(
        self,
        symbol: str,
        timeframe: str,
        fields: dict[bytes, bytes],
        stream_name: str,
        message_id: bytes,
    ) -> None:
        try:
            raw_ts = fields.get(b"timestamp", b"").decode()
            timestamp = datetime.fromisoformat(raw_ts) if raw_ts else datetime.now(tz=timezone.utc)

            bar, features = parse_intelligence_message(fields)

            # Buffer bar in history
            key = f"{symbol}:{timeframe}"
            bar_with_ts = {**bar, "timestamp": timestamp}
            self.bar_history[key].append(bar_with_ts)

            df_history = list(self.bar_history[key])
            import pandas as pd
            frames = {
                "main": pd.DataFrame(df_history),
                "features": features,
            }

            await self._process_bar(symbol, timeframe, bar, features, frames, timestamp)
            await self.redis_client.xack(stream_name, self.consumer_group, message_id)

        except Exception as e:
            self.logger.error(
                "Error processing message",
                symbol=symbol,
                timeframe=timeframe,
                error=str(e),
            )
            self.error_count_total.inc()
            self._error_count += 1

    async def _health_monitor_loop(self) -> None:
        while self.running and not self.shutdown_requested:
            try:
                uptime = int((datetime.now(tz=timezone.utc) - self.start_time).total_seconds())
                self.service_uptime_seconds.set(uptime)
                interval = self.config["service"]["health_check_interval"]
                if uptime % interval == 0:
                    self.logger.info(
                        "Health check",
                        uptime=uptime,
                        bars_processed=self._total_bars,
                        signals_generated=self._total_signals,
                        lifecycle_transitions=self._total_transitions,
                        errors=self._error_count,
                    )
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in health monitor", error=str(e))
                await asyncio.sleep(5)


async def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Signal Orchestrator Service")
    parser.add_argument("--config", help="Configuration file path")
    parser.add_argument("--foreground", action="store_true", help="Run in foreground")
    args = parser.parse_args()

    svc = SignalOrchestratorService(args.config)

    if args.foreground:
        print("Starting Signal Orchestrator Service in foreground...")
        print("Press Ctrl+C to stop")

    try:
        await svc.start()
    except KeyboardInterrupt:
        print("\nService stopped by user")
    except Exception as e:
        print(f"Service failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
```

**Step 2: Create `config/signal_orchestrator.json`**

```json
{
  "redis": {
    "host": "localhost",
    "port": 6379,
    "db": 0
  },
  "database": {
    "url": "postgresql://postgres:postgres@localhost:5432/indicagent"
  },
  "service": {
    "symbols": ["ESH6", "NQH6", "RTYH6"],
    "timeframes": ["5m", "15m"],
    "min_history_bars": 50,
    "processing_interval": 0.1,
    "health_check_interval": 30
  },
  "logging": {
    "level": "INFO",
    "file": "logs/signal_orchestrator.log",
    "max_size": "10MB",
    "backup_count": 5
  }
}
```

**Step 3: Run full test suite**

```bash
python -m pytest tests/unit/ -q
```
Expected: all tests pass, 0 errors.

**Step 4: Smoke test the service starts**

```bash
python services/signal_orchestrator_service.py --foreground &
sleep 3
kill %1
```
Expected: "Starting Signal Orchestrator Service" logged, no crash.

**Step 5: Commit**

```bash
git add services/signal_orchestrator_service.py config/signal_orchestrator.json
git commit -m "feat: signal orchestrator main loop, health monitor, and config"
```

---

## Task 7: Final Verification

**Step 1: Run full test suite + lint**

```bash
python -m pytest tests/unit/ -v --tb=short
python -m ruff check services/signal_orchestrator_service.py
```
Expected: all tests pass, 0 lint errors.

**Step 2: Count new tests**

```bash
python -m pytest tests/unit/service_tests/test_intelligence_processor_ohlcv.py \
    tests/unit/service_tests/test_signal_orchestrator_helpers.py \
    tests/unit/service_tests/test_signal_orchestrator_init.py \
    tests/unit/service_tests/test_signal_orchestrator_signal_gen.py \
    tests/unit/service_tests/test_signal_orchestrator_lifecycle.py \
    -v --co -q
```
Expected: ~22 tests collected.

**Step 3: Update CLAUDE.md**

Run skill: `revise-claude-md` to update plugin/service counts and note signal data collection is now active.

**Step 4: Final commit**

```bash
git add -A
git commit -m "docs: update CLAUDE.md — signal orchestrator complete, data collection active"
```

---

## Summary

| Task | Files | Tests |
|------|-------|-------|
| 1. Enrich intelligence stream | `intelligence_processor_service.py` | 2 |
| 2. Parse + assemble helpers | `signal_orchestrator_service.py` | 8 |
| 3. Service skeleton | `signal_orchestrator_service.py` | 3 |
| 4. Signal generation path | `signal_orchestrator_service.py` | 5 |
| 5. Lifecycle tracking | `signal_orchestrator_service.py` | 4 |
| 6. Main loop + config | `signal_orchestrator_service.py`, `config/` | smoke test |
| 7. Verification | — | full suite |

**Total new tests: ~22**

After this plan executes, `signal_ledger` starts accumulating data immediately. At ~18 signals/day across ES/NQ/RTY on 5m+15m, the ML calibration dataset (~500 signals) will be ready in ~28 days.
