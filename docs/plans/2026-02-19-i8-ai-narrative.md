# I8 AI Narrative Service Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build `AINarrativeService` — a standalone async service that synthesizes aggregated trading signals into concise LLM-generated market narratives via local Ollama, publishing to a `narratives:SYMBOL:TIMEFRAME` Redis stream.

**Architecture:** Subscribes to `signals:SYMBOL:TIMEFRAME:aggregated` (already only fires on selected setups — free cost control). Parses signal, builds structured prompt, calls Ollama `qwen3:8b` via `asyncio.to_thread` (zero new deps), publishes narrative to Redis stream + hash cache. Follows the exact service pattern of `signal_orchestrator_service.py`.

**Tech Stack:** Python, asyncio, redis.asyncio, urllib.request (built-in), structlog, Prometheus, Ollama HTTP API

---

## Before You Start

Confirm baseline tests pass:

```bash
/home/brandon-goyette/development/indicagent/.venv/bin/python3 -m pytest tests/ --ignore=tests/integration -q 2>/dev/null | tail -5
```

Expected: 345 passing, 0 failures. If not, stop and investigate.

**Key files to understand:**
- `signal_orchestrator_service.py` — exact template for this service (service class, config, metrics, loops)
- `src/core/stream_keys.py` — where we add `narratives()` helper
- `config/signal_orchestrator.json` — template for new config file
- `tests/unit/service_tests/test_signal_orchestrator_helpers.py` — template for helper tests

---

## Task 1: Add `narratives` stream key + pure helper functions

**Files:**
- Modify: `src/core/stream_keys.py`
- Create: `services/ai_narrative_service.py` (helpers only)
- Create: `tests/unit/service_tests/test_ai_narrative_helpers.py`

**Step 1: Write the failing tests**

Create `tests/unit/service_tests/test_ai_narrative_helpers.py`:

```python
"""Tests for pure helper functions in ai_narrative_service."""

from services.ai_narrative_service import build_narrative_prompt, parse_aggregated_signal


def _make_fields(direction: int = 1, **overrides) -> dict[bytes, bytes]:
    """Build a bytes-keyed field dict like xreadgroup returns."""
    base: dict[bytes, bytes] = {
        b"symbol": b"ESH6",
        b"timeframe": b"5m",
        b"timestamp": b"2026-02-19T14:05:00",
        b"direction": str(direction).encode(),
        b"confidence": b"0.74",
        b"confluence_score": b"0.81",
        b"setup_plugin": b"trad_TrendFollowing",
        b"signal_type": b"trend_following",
        b"entry_price": b"5102.50",
        b"stop_loss": b"5094.00",
        b"targets": b"5112.00,5118.50",
        b"regime_context": b"trending_up",
        b"supporting_factors": b"BOS confirmed, RSI bullish",
    }
    for k, v in overrides.items():
        key = k.encode() if isinstance(k, str) else k
        val = v.encode() if isinstance(v, str) else v
        base[key] = val
    return base


def test_parse_aggregated_signal_bullish():
    """Bullish signal (direction=1) is parsed to typed dict with correct fields."""
    result = parse_aggregated_signal(_make_fields(direction=1))
    assert result is not None
    assert result["direction"] == 1
    assert result["direction_label"] == "Bullish"
    assert result["symbol"] == "ESH6"
    assert result["confidence"] == 0.74
    assert result["entry_price"] == "5102.50"


def test_parse_aggregated_signal_bearish():
    """Bearish signal (direction=-1) has direction_label='Bearish'."""
    result = parse_aggregated_signal(_make_fields(direction=-1))
    assert result is not None
    assert result["direction"] == -1
    assert result["direction_label"] == "Bearish"


def test_parse_aggregated_signal_skips_zero_direction():
    """direction=0 returns None — no narrative needed for neutral bars."""
    result = parse_aggregated_signal(_make_fields(direction=0))
    assert result is None


def test_build_narrative_prompt_contains_key_fields():
    """Prompt contains entry price, stop, symbol, supporting factors, and /no_think prefix."""
    signal = parse_aggregated_signal(_make_fields(direction=1))
    prompt = build_narrative_prompt(signal)
    assert "ESH6" in prompt
    assert "5102.50" in prompt        # entry_price
    assert "5094.00" in prompt        # stop_loss
    assert "BOS confirmed" in prompt  # supporting_factors
    assert "/no_think" in prompt      # suppress qwen3 thinking overhead
    assert "Bullish" in prompt
```

**Step 2: Run tests to verify they fail**

```bash
/home/brandon-goyette/development/indicagent/.venv/bin/python3 -m pytest \
  tests/unit/service_tests/test_ai_narrative_helpers.py -v
```

Expected: FAIL — `services.ai_narrative_service` does not exist.

**Step 3: Add `narratives` to `stream_keys.py`**

In `src/core/stream_keys.py`, add after `signals_aggregated` (line 42):

```python
def narratives(env_prefix: str, symbol: str, timeframe: str) -> str:
    return f"{env_prefix}narratives:{symbol}:{timeframe}"
```

**Step 4: Create `services/ai_narrative_service.py` with pure helpers**

```python
#!/usr/bin/env python3
"""
AI Narrative Service — I8 LLM synthesis of trading signals into human-readable narratives

Subscribes to signals:SYMBOL:TF:aggregated stream. For each selected signal,
builds a structured prompt, calls Ollama (qwen3:8b), and publishes a narrative
to narratives:SYMBOL:TF stream and narrative:SYMBOL:TF:latest hash.

Version: 1.0.0
Last Updated: 2026-02-19
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
import urllib.request
from asyncio import to_thread
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from logging.handlers import RotatingFileHandler  # noqa: E402

import redis.asyncio as redis  # noqa: E402
import structlog  # noqa: E402

from src.config.settings import Settings  # noqa: E402
from src.core.stream_keys import narratives as sk_narratives  # noqa: E402
from src.core.stream_keys import signals_aggregated  # noqa: E402
from src.observability.metrics import counter, gauge, start_metrics_server  # noqa: E402


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are a professional futures trading analyst. "
    "Given a market signal, write a concise 2-3 sentence trading narrative. "
    "Be specific about price levels and directional bias. No disclaimers."
)


# ---------------------------------------------------------------------------
# Pure helper functions (no I/O — easy to test)
# ---------------------------------------------------------------------------

def parse_aggregated_signal(fields: dict[bytes, bytes]) -> dict[str, Any] | None:
    """Parse a signals:aggregated stream message into a typed signal dict.

    Returns None if direction is 0 (no actionable signal to narrate).
    """
    def _get(key: str, default: str = "") -> str:
        raw = fields.get(key.encode(), b"")
        return (raw.decode() if isinstance(raw, bytes) else str(raw)).strip() or default

    direction = int(float(_get("direction", "0")))
    if direction == 0:
        return None

    return {
        "symbol": _get("symbol"),
        "timeframe": _get("timeframe"),
        "timestamp": _get("timestamp"),
        "direction": direction,
        "direction_label": "Bullish" if direction > 0 else "Bearish",
        "confidence": float(_get("confidence", "0.0")),
        "confluence_score": float(_get("confluence_score", "0.0")),
        "setup_plugin": _get("setup_plugin"),
        "signal_type": _get("signal_type"),
        "entry_price": _get("entry_price"),
        "stop_loss": _get("stop_loss"),
        "targets": _get("targets"),
        "regime_context": _get("regime_context"),
        "supporting_factors": _get("supporting_factors"),
    }


def build_narrative_prompt(signal: dict[str, Any]) -> str:
    """Build the Ollama user message from a parsed signal dict."""
    confidence_pct = f"{signal['confidence']:.0%}"
    return (
        f"/no_think\n\n"
        f"Symbol: {signal['symbol']}, Timeframe: {signal['timeframe']}\n"
        f"Setup: {signal['setup_plugin']} — {signal['direction_label']} (confidence {confidence_pct})\n"
        f"Entry: {signal['entry_price']} | Stop: {signal['stop_loss']} | Targets: {signal['targets']}\n"
        f"Regime: {signal['regime_context']}\n"
        f"Factors: {signal['supporting_factors']}"
    )
```

**Step 5: Run tests to verify they pass**

```bash
/home/brandon-goyette/development/indicagent/.venv/bin/python3 -m pytest \
  tests/unit/service_tests/test_ai_narrative_helpers.py -v
```

Expected: PASS (4 tests).

**Step 6: Commit**

```bash
git add src/core/stream_keys.py \
        services/ai_narrative_service.py \
        tests/unit/service_tests/test_ai_narrative_helpers.py
git commit -m "feat: add narratives stream key and I8 pure helper functions"
```

---

## Task 2: Ollama client + service class + config

**Files:**
- Modify: `services/ai_narrative_service.py` (add `call_ollama_async` + `AINarrativeService`)
- Create: `config/ai_narrative_service.json`
- Create: `tests/unit/service_tests/test_ai_narrative_service.py`

**Step 1: Write the failing tests**

Create `tests/unit/service_tests/test_ai_narrative_service.py`:

```python
"""Tests for AINarrativeService class."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_service():
    """Instantiate AINarrativeService with all external deps mocked."""
    with (
        patch("services.ai_narrative_service.start_metrics_server"),
        patch("services.ai_narrative_service.counter", return_value=MagicMock()),
        patch("services.ai_narrative_service.gauge", return_value=MagicMock()),
        patch("services.ai_narrative_service.Settings") as mock_settings,
    ):
        mock_settings.return_value.env_name = ""
        from services.ai_narrative_service import AINarrativeService
        return AINarrativeService()


def test_service_initializes_with_default_config():
    """Service creates expected attributes from default config."""
    svc = _make_service()
    assert svc.ollama_model == "qwen3:8b"
    assert svc.ollama_timeout == 15.0
    assert "ESH6" in svc.config["service"]["symbols"]
    assert svc.env_prefix == ""


@pytest.mark.asyncio
async def test_process_message_skips_zero_direction():
    """direction=0 → no Ollama call, message acked anyway."""
    svc = _make_service()
    svc.redis_client = AsyncMock()

    fields = {
        b"direction": b"0",
        b"symbol": b"ESH6",
        b"timeframe": b"5m",
        b"timestamp": b"2026-02-19T14:05:00",
    }
    with patch("services.ai_narrative_service.call_ollama_async") as mock_ollama:
        await svc._process_single_message(
            "ESH6", "5m", fields, "signals:ESH6:5m:aggregated", b"1-0"
        )
        mock_ollama.assert_not_called()
    svc.redis_client.xack.assert_called_once()


@pytest.mark.asyncio
async def test_process_message_publishes_narrative():
    """Valid bullish signal → Ollama called → narrative published to stream + hash."""
    svc = _make_service()
    svc.redis_client = AsyncMock()

    fields = {
        b"direction": b"1",
        b"symbol": b"ESH6",
        b"timeframe": b"5m",
        b"timestamp": b"2026-02-19T14:05:00",
        b"confidence": b"0.74",
        b"confluence_score": b"0.81",
        b"setup_plugin": b"trad_TrendFollowing",
        b"signal_type": b"trend_following",
        b"entry_price": b"5102.50",
        b"stop_loss": b"5094.00",
        b"targets": b"5112.00",
        b"regime_context": b"trending_up",
        b"supporting_factors": b"BOS confirmed",
    }
    fake_narrative = "ES is establishing a trend-following setup at 5102.50."

    with patch(
        "services.ai_narrative_service.call_ollama_async",
        return_value=fake_narrative,
    ):
        await svc._process_single_message(
            "ESH6", "5m", fields, "signals:ESH6:5m:aggregated", b"1-0"
        )

    # Stream publish
    svc.redis_client.xadd.assert_called_once()
    stream_name, msg = svc.redis_client.xadd.call_args[0]
    assert "narratives:ESH6:5m" in stream_name
    assert msg["narrative"] == fake_narrative
    assert msg["action_bias"] == "bullish"
    # Hash cache
    svc.redis_client.hset.assert_called_once()
    svc.redis_client.expire.assert_called_once()
    # Ack
    svc.redis_client.xack.assert_called_once()


@pytest.mark.asyncio
async def test_process_message_handles_ollama_failure():
    """Ollama returns None → no stream publish, message still acked."""
    svc = _make_service()
    svc.redis_client = AsyncMock()

    fields = {
        b"direction": b"1",
        b"symbol": b"ESH6",
        b"timeframe": b"5m",
        b"timestamp": b"2026-02-19T14:05:00",
        b"confidence": b"0.74",
        b"confluence_score": b"0.0",
        b"setup_plugin": b"trad_TrendFollowing",
        b"signal_type": b"trend_following",
        b"entry_price": b"5102.50",
        b"stop_loss": b"5094.00",
        b"targets": b"5112.00",
        b"regime_context": b"trending_up",
        b"supporting_factors": b"RSI bullish",
    }
    with patch("services.ai_narrative_service.call_ollama_async", return_value=None):
        await svc._process_single_message(
            "ESH6", "5m", fields, "signals:ESH6:5m:aggregated", b"1-0"
        )

    svc.redis_client.xadd.assert_not_called()
    svc.redis_client.xack.assert_called_once()
```

**Step 2: Run tests to verify they fail**

```bash
/home/brandon-goyette/development/indicagent/.venv/bin/python3 -m pytest \
  tests/unit/service_tests/test_ai_narrative_service.py -v
```

Expected: FAIL — `call_ollama_async`, `AINarrativeService`, `_process_single_message` do not exist.

**Step 3: Add `call_ollama_async` to `services/ai_narrative_service.py`**

Add after `build_narrative_prompt`, before the service class:

```python
async def call_ollama_async(
    base_url: str,
    model: str,
    prompt: str,
    timeout: float = 15.0,
) -> str | None:
    """Call Ollama /api/chat in a thread. Returns narrative text or None on failure.

    Uses asyncio.to_thread so the event loop stays free during the blocking HTTP call.
    No new dependencies — uses stdlib urllib.request.
    """
    def _call() -> str | None:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "options": {"num_predict": 200},
        }
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{base_url}/api/chat",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read())
            return result.get("message", {}).get("content", "").strip() or None

    try:
        return await to_thread(_call)
    except Exception as exc:
        return None
```

**Step 4: Add `AINarrativeService` class to `services/ai_narrative_service.py`**

Append after `call_ollama_async`:

```python
# ---------------------------------------------------------------------------
# Service class
# ---------------------------------------------------------------------------

class AINarrativeService:
    """Synthesize aggregated trading signals into LLM-generated market narratives."""

    def __init__(self, config_file: str | None = None):
        self.running = False
        self.shutdown_requested = False
        self.start_time = datetime.now(tz=UTC)

        self.config = self._load_config(config_file)
        self._setup_logging()

        self.redis_client: redis.Redis | None = None
        self.consumer_group = f"ai_narrative_{int(time.time())}"
        self.consumer_name = f"narrative_{os.getpid()}"

        settings = Settings()
        self.env_prefix = f"{settings.env_name}:" if settings.env_name else ""

        self.ollama_base_url: str = self.config["ollama"]["base_url"]
        self.ollama_model: str = self.config["ollama"]["model"]
        self.ollama_timeout: float = float(self.config["ollama"]["timeout_sec"])

        self.narratives_generated_total = counter(
            "narrative_generated_total",
            "Total narratives generated by AI",
        )
        self.narratives_skipped_total = counter(
            "narrative_skipped_total",
            "Total signals skipped (direction=0 or Ollama failure)",
        )
        self.ollama_latency_ms = gauge(
            "narrative_ollama_latency_ms",
            "Ollama call latency in milliseconds",
        )
        self.service_uptime_seconds = gauge(
            "narrative_service_uptime_seconds",
            "Service uptime in seconds",
        )
        self.error_count_total = counter(
            "narrative_errors_total",
            "Total errors in narrative service",
        )

        self._total_narratives = 0
        self._error_count = 0

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self.logger = structlog.get_logger(__name__)
        start_metrics_server(port=9113)

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
            "service": {
                "symbols": ["ESH6", "NQH6", "RTYH6"],
                "timeframes": ["5m", "15m"],
                "processing_interval": 0.1,
                "health_check_interval": 30,
            },
            "ollama": {
                "base_url": "http://localhost:11434",
                "model": "qwen3:8b",
                "timeout_sec": 15.0,
            },
            "logging": {
                "level": "INFO",
                "file": "logs/ai_narrative.log",
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

    async def _setup_consumer_groups(self) -> None:
        for tf in self.config["service"]["timeframes"]:
            for sym in self.config["service"]["symbols"]:
                stream_name = signals_aggregated(self.env_prefix, sym, tf)
                try:
                    await self.redis_client.xgroup_create(
                        stream_name, self.consumer_group, "0", mkstream=True
                    )
                except Exception:
                    pass  # Group already exists

    async def stop(self) -> None:
        self.logger.info("Stopping AI Narrative Service")
        self.running = False
        self.shutdown_requested = True
        if self.redis_client:
            await self.redis_client.aclose()
        self.logger.info("AI Narrative Service stopped")

    # ------------------------------------------------------------------
    # Per-message processing
    # ------------------------------------------------------------------

    async def _process_single_message(
        self,
        symbol: str,
        timeframe: str,
        fields: dict[bytes, bytes],
        stream_name: str,
        message_id: bytes,
    ) -> None:
        try:
            signal_data = parse_aggregated_signal(fields)
            if signal_data is None:
                self.narratives_skipped_total.inc()
                await self.redis_client.xack(stream_name, self.consumer_group, message_id)
                return

            prompt = build_narrative_prompt(signal_data)
            t0 = time.time()
            narrative_text = await call_ollama_async(
                self.ollama_base_url,
                self.ollama_model,
                prompt,
                self.ollama_timeout,
            )
            latency_ms = (time.time() - t0) * 1000
            self.ollama_latency_ms.set(latency_ms)

            if narrative_text:
                stream_out = sk_narratives(self.env_prefix, symbol, timeframe)
                narrative_msg = {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "timestamp": signal_data["timestamp"],
                    "narrative": narrative_text,
                    "action_bias": signal_data["direction_label"].lower(),
                    "confidence": str(signal_data["confidence"]),
                    "model": self.ollama_model,
                    "latency_ms": str(int(latency_ms)),
                }
                await self.redis_client.xadd(
                    stream_out, narrative_msg, maxlen=100, approximate=True
                )
                cache_key = f"{self.env_prefix}narrative:{symbol}:{timeframe}:latest"
                await self.redis_client.hset(cache_key, mapping=narrative_msg)
                await self.redis_client.expire(cache_key, 90)
                self.narratives_generated_total.inc()
                self._total_narratives += 1
                self.logger.info(
                    "Narrative published",
                    symbol=symbol,
                    timeframe=timeframe,
                    bias=signal_data["direction_label"],
                    latency_ms=round(latency_ms, 1),
                )
            else:
                self.narratives_skipped_total.inc()
                self.logger.warning(
                    "Ollama returned no narrative",
                    symbol=symbol,
                    timeframe=timeframe,
                )

            await self.redis_client.xack(stream_name, self.consumer_group, message_id)

        except Exception as e:
            self.logger.error(
                "Error processing signal message",
                symbol=symbol,
                timeframe=timeframe,
                error=str(e),
            )
            self.error_count_total.inc()
            self._error_count += 1

    # ------------------------------------------------------------------
    # Main service loops
    # ------------------------------------------------------------------

    async def _process_loop(self) -> None:
        self.logger.info("Starting signal stream processing loop")

        while self.running and not self.shutdown_requested:
            try:
                for tf in self.config["service"]["timeframes"]:
                    for sym in self.config["service"]["symbols"]:
                        stream_name = signals_aggregated(self.env_prefix, sym, tf)
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

    async def _health_monitor_loop(self) -> None:
        while self.running and not self.shutdown_requested:
            try:
                uptime = int((datetime.now(tz=UTC) - self.start_time).total_seconds())
                self.service_uptime_seconds.set(uptime)
                interval = self.config["service"]["health_check_interval"]
                if uptime % interval == 0:
                    self.logger.info(
                        "Health check",
                        uptime=uptime,
                        narratives_generated=self._total_narratives,
                        errors=self._error_count,
                    )
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in health monitor", error=str(e))
                await asyncio.sleep(5)

    async def start(self) -> None:
        self.logger.info("Starting AI Narrative Service", config=self.config["service"])
        try:
            await self._connect_redis()
            await self._setup_consumer_groups()

            self.running = True
            tasks = [
                asyncio.create_task(self._process_loop()),
                asyncio.create_task(self._health_monitor_loop()),
            ]
            self.logger.info("AI Narrative Service started")
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            self.logger.error("Failed to start service", error=str(e))
            raise
        finally:
            await self.stop()


async def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="AI Narrative Service")
    parser.add_argument("--config", help="Configuration file path")
    parser.add_argument("--foreground", action="store_true", help="Run in foreground")
    args = parser.parse_args()

    svc = AINarrativeService(args.config)

    if args.foreground:
        print("Starting AI Narrative Service in foreground...")
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

**Step 5: Create `config/ai_narrative_service.json`**

```json
{
  "redis": {
    "host": "localhost",
    "port": 6379,
    "db": 0
  },
  "service": {
    "symbols": ["ESH6", "NQH6", "RTYH6"],
    "timeframes": ["5m", "15m"],
    "processing_interval": 0.1,
    "health_check_interval": 30
  },
  "ollama": {
    "base_url": "http://localhost:11434",
    "model": "qwen3:8b",
    "timeout_sec": 15.0
  },
  "logging": {
    "level": "INFO",
    "file": "logs/ai_narrative.log",
    "max_size": "10MB",
    "backup_count": 5
  }
}
```

**Step 6: Run all tests to verify they pass**

```bash
/home/brandon-goyette/development/indicagent/.venv/bin/python3 -m pytest \
  tests/unit/service_tests/test_ai_narrative_helpers.py \
  tests/unit/service_tests/test_ai_narrative_service.py -v
```

Expected: PASS (8 tests total: 4 helpers + 4 service).

**Step 7: Commit**

```bash
git add services/ai_narrative_service.py \
        config/ai_narrative_service.json \
        tests/unit/service_tests/test_ai_narrative_service.py
git commit -m "feat: add I8 AI narrative service with Ollama synthesis"
```

---

## Task 3: Final Verification and CLAUDE.md Update

**Step 1: Run the full test suite**

```bash
/home/brandon-goyette/development/indicagent/.venv/bin/python3 -m pytest tests/ --ignore=tests/integration -q 2>/dev/null | tail -10
```

Expected: 353+ passing (345 + 8 new), 0 failures.

**Step 2: Run the linter**

```bash
/home/brandon-goyette/development/indicagent/.venv/bin/ruff check \
  src/core/stream_keys.py \
  services/ai_narrative_service.py
```

Expected: 0 errors. If any, fix them before proceeding.

**Step 3: Update CLAUDE.md**

In `CLAUDE.md`:

1. Update the Status line (top) to reflect I8 is operational and test count:
   ```
   Status: I1-I7 Phase 2 signal orchestration active + I8 AI narratives — 41 plugins + 4 aggregation components + SignalOrchestrator + AINarrativeService, 353 tests
   ```

2. Add `services/ai_narrative_service.py` to the Production Services list:
   ```
   - `services/ai_narrative_service.py` - I8 AI narrative synthesis: LLM narratives from selected signals via Ollama (Health: `:9113/metrics`)
   ```

3. In the Pipeline Flow section, extend the diagram to show narratives:
   ```
   → Signal Orchestrator → signals:SYMBOL:TF:aggregated
                               ↓
                        AINarrativeService (Ollama qwen3:8b)
                               ↓
                        narratives:SYMBOL:TF → SSE → Dashboard
   ```

4. Update Intelligence Tiers section:
   ```
   - **I8 AI Intelligence** — AINarrativeService: LLM synthesis of selected signals into human-readable narratives via Ollama qwen3:8b — WORKING
   ```

5. Update Development Priorities to remove I8 (done) and reprioritize:
   ```
   1. **Dashboard narrative panel** — Wire narratives:SYMBOL:TF to SSE + add dashboard panel
   2. **More regime models** — GARCH volatility, Kalman filter trend, chart patterns
   3. **I7 Trading Outputs Phase 2** — 9 more setup plugins
   ```

6. Update Plugin System count if needed.

**Step 4: Commit CLAUDE.md**

```bash
git add docs/for-ai-assistants/CLAUDE.md
git commit -m "docs: update CLAUDE.md — I8 AI narrative service complete"
```

**Step 5: Manual smoke test (optional, requires live Ollama + Redis)**

```bash
# Check Ollama is running
curl -s http://localhost:11434/api/tags | python3 -m json.tool | grep "qwen3:8b"

# Run service with foreground flag
/home/brandon-goyette/development/indicagent/.venv/bin/python3 \
  services/ai_narrative_service.py \
  --config config/ai_narrative_service.json \
  --foreground
```

Watch for `"Narrative published"` log lines when signals fire.

---

## Summary

**Files created:**
- `services/ai_narrative_service.py` — full service (pure helpers + Ollama client + service class)
- `config/ai_narrative_service.json` — runtime config
- `tests/unit/service_tests/test_ai_narrative_helpers.py` — 4 pure-function tests
- `tests/unit/service_tests/test_ai_narrative_service.py` — 4 service tests

**Files modified:**
- `src/core/stream_keys.py` — added `narratives()` helper
- `docs/for-ai-assistants/CLAUDE.md` — version + status update

**What this enables:**
- First human-readable output from the I1–I7 signal pipeline
- Validates signal quality via readable narratives
- Zero new pip dependencies (stdlib urllib + asyncio.to_thread)
- Natural cost control (LLM only called on selected signals, max ~6 calls/min)
