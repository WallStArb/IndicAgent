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
        f"Setup: {signal['setup_plugin']} — {signal['direction_label']}"
        f" (confidence {confidence_pct})\n"
        f"Entry: {signal['entry_price']} | Stop: {signal['stop_loss']}"
        f" | Targets: {signal['targets']}\n"
        f"Regime: {signal['regime_context']}\n"
        f"Factors: {signal['supporting_factors']}"
    )


async def call_ollama_async(
    base_url: str,
    model: str,
    prompt: str,
    timeout: float = 15.0,
    num_predict: int = 500,
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
            "options": {"num_predict": num_predict},
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
        structlog.get_logger(__name__).warning(
            "Ollama call failed", model=model, error=str(exc)
        )
        return None


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
        self.consumer_group = "ai_narrative"
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
                "num_predict": 500,
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
                return  # finally will xack

            prompt = build_narrative_prompt(signal_data)
            t0 = time.time()
            narrative_text = await call_ollama_async(
                self.ollama_base_url,
                self.ollama_model,
                prompt,
                self.ollama_timeout,
                int(self.config["ollama"].get("num_predict", 500)),
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

        except Exception as e:
            self.logger.error(
                "Error processing signal message",
                symbol=symbol,
                timeframe=timeframe,
                error=str(e),
            )
            self.error_count_total.inc()
            self._error_count += 1
        finally:
            await self.redis_client.xack(stream_name, self.consumer_group, message_id)

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
