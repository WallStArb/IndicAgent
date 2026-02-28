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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from logging.handlers import RotatingFileHandler  # noqa: E402

import redis.asyncio as redis  # noqa: E402
import structlog  # noqa: E402

from src.config.settings import Settings, get_active_contracts  # noqa: E402
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

# Per-signal narrative gating
_NARRATIVE_ELIGIBLE_TFS = {"5m", "15m", "1h"}
_NARRATIVE_MIN_CONFIDENCE = 0.70

GROUP_SYSTEM_PROMPT = (
    "You are a professional multi-asset futures analyst. "
    "Given signals across related instruments, write a concise 2-3 sentence "
    "group synthesis covering cross-asset themes and directional bias. "
    "Be specific. No disclaimers."
)

# Asset group definitions — contract codes for active front-month (Feb 2026)
ASSET_GROUPS: dict[str, list[str]] = {
    "equity":    ["ESH6", "NQH6", "RTYH6", "YMH6", "VXH6"],
    "energy":    ["CLJ6", "BZJ6", "NGJ6"],
    "metals":    ["GCJ6", "SIH6", "HGH6", "PLJ6"],
    "rates":     ["ZNH6", "ZFH6", "ZBH6", "ZTH6", "SR1H6"],
    "fx_crypto": ["6EH6", "6JH6", "BTCH6"],
    "ag":        ["ZSH6", "ZCH6", "ZWH6"],
}

# Reverse lookup: contract_code → group_name
SYMBOL_TO_GROUP: dict[str, str] = {
    sym: group
    for group, symbols in ASSET_GROUPS.items()
    for sym in symbols
}

# TFs considered for group synthesis signal state
_GROUP_SYNTHESIS_TFS = ("5m", "15m", "1h")


def build_group_synthesis_prompt(
    group_name: str,
    signals: dict[str, dict],
) -> str:
    """Build a phi4-mini prompt for group-level cross-asset synthesis.

    Args:
        group_name: e.g. "equity"
        signals: dict keyed by "SYMBOL:TF" → parsed signal dict.
                 Only non-zero direction signals should be passed.
    """
    if not signals:
        lines = [f"Group {group_name}: no active signals at this time."]
    else:
        lines = []
        for key, sig in sorted(signals.items()):
            sym, tf = key.split(":", 1)
            confidence_pct = f"{sig.get('confidence', 0):.0%}"
            lines.append(
                f"- {sym} {tf}: {sig.get('direction_label', 'Neutral')} "
                f"(confidence {confidence_pct}) | {sig.get('setup_plugin', 'unknown')} "
                f"| {sig.get('regime_context', 'unknown')}"
            )

    signal_block = "\n".join(lines)
    return (
        f"/no_think\n\n"
        f"Group: {group_name}\n"
        f"Current signals:\n{signal_block}\n\n"
        f"Write a 2-3 sentence cross-asset synthesis for this group."
    )


def extract_group_fingerprint(
    signals: dict[str, dict],
) -> dict[str, tuple[int, str]]:
    """Extract a comparable fingerprint from a signals dict.

    Only includes entries where direction != 0 (actionable signals).
    Returns dict of "SYMBOL:TF" → (direction, regime_context).
    """
    return {
        key: (int(sig.get("direction", 0)), str(sig.get("regime_context", "")))
        for key, sig in signals.items()
        if int(sig.get("direction", 0)) != 0
    }


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
        "profit_target": _get("profit_target"),        # promoted scalar from targets[0]
        "risk_reward_ratio": _get("risk_reward_ratio"),
        "regime_context": _get("regime_context"),
        "supporting_factors": _get("supporting_factors"),
    }


def build_narrative_prompt(signal: dict[str, Any]) -> str:
    """Build the Ollama user message from a parsed signal dict."""
    confidence_pct = f"{signal['confidence']:.0%}"
    target_str = (
        f"{signal['profit_target']} (R:R {signal['risk_reward_ratio']})"
        if signal.get("profit_target") and signal.get("risk_reward_ratio")
        else signal.get("profit_target") or "not specified"
    )
    return (
        f"/no_think\n\n"
        f"Symbol: {signal['symbol']}, Timeframe: {signal['timeframe']}\n"
        f"Setup: {signal['setup_plugin']} — {signal['direction_label']}"
        f" (confidence {confidence_pct})\n"
        f"Entry: {signal['entry_price']} | Stop: {signal['stop_loss']}"
        f" | Target: {target_str}\n"
        f"Regime: {signal['regime_context']}\n"
        f"Factors: {signal['supporting_factors']}"
    )


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
        self._stream_map: dict[str, tuple[str, str]] = {}

        self._build_chains()

        # In-memory cache: "SYMBOL:TF" → latest parsed signal dict (any direction)
        self._latest_signals: dict[str, dict] = {}

        # Metrics for group synthesis
        self.group_narratives_generated = counter(
            "narrative_group_generated_total",
            "Total group narratives generated",
        )

        self.shutdown_event = asyncio.Event()

        self.logger = structlog.get_logger(__name__)
        start_metrics_server(port=9113)

    # ------------------------------------------------------------------
    # Chain construction
    # ------------------------------------------------------------------

    def _build_chains(self) -> None:
        from src.intelligence.llm_providers import LLMChain, OllamaProvider, OpenRouterProvider

        settings = Settings()
        api_key = getattr(settings, "openrouter_api_key", None) or ""

        pcfg = self.config["providers"]
        or_url = pcfg["openrouter_base_url"]
        ol_url = pcfg["ollama_base_url"]

        def _make_provider(spec: dict):
            if spec["type"] == "openrouter":
                return OpenRouterProvider(spec["model"], api_key=api_key, base_url=or_url)
            return OllamaProvider(spec["model"], base_url=ol_url)

        self.per_signal_chain = LLMChain([_make_provider(s) for s in pcfg["per_signal"]])
        self.group_chain = LLMChain([_make_provider(s) for s in pcfg["group"]])

        self._per_signal_timeout = float(pcfg["openrouter_timeout_sec"])
        self._group_timeout = float(pcfg["openrouter_timeout_sec"])

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
                "symbols": get_active_contracts(_settings),
                "timeframes": ["1m", "5m", "15m", "1h"],
                "processing_interval": 0.1,
                "health_check_interval": 30,
            },
            "ollama": {
                "base_url": "http://localhost:11434",
                "model": "qwen3:8b",
                "group_model": "phi4-mini:3.8b",
                "timeout_sec": 60.0,  # was 120.0; qwen3:8b needs ~60s max on CPU
                "num_predict": 500,
            },
            "providers": {
                "openrouter_base_url": "https://openrouter.ai/api/v1",
                "openrouter_timeout_sec": 30.0,
                "ollama_base_url": "http://localhost:11434",
                "ollama_timeout_sec": 60.0,
                "per_signal": [
                    {"type": "openrouter", "model": "meta-llama/llama-3.3-70b-instruct:free"},
                    {"type": "openrouter", "model": "arcee-ai/trinity-large-preview:free"},
                    {"type": "ollama",     "model": "qwen3:8b"},
                ],
                "group": [
                    {"type": "openrouter", "model": "stepfun/step-3.5-flash:free"},
                    {"type": "openrouter", "model": "arcee-ai/trinity-large-preview:free"},
                    {"type": "ollama",     "model": "phi4-mini:3.8b"},
                ],
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

    def _register_signal_handlers(self, loop: asyncio.AbstractEventLoop) -> None:
        """Register SIGINT/SIGTERM handlers that wake the asyncio event loop."""
        def _handle_signal() -> None:
            self.logger.info("Received shutdown signal")
            self.shutdown_requested = True
            self.running = False
            self.shutdown_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _handle_signal)
            except (NotImplementedError, RuntimeError):
                # Fallback for environments where add_signal_handler is not supported
                signal.signal(sig, lambda s, f: _handle_signal())

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
                        stream_name, self.consumer_group, "$", mkstream=True
                    )
                except Exception:
                    # Group exists — force-reset to current tail to skip stale backlog
                    try:
                        await self.redis_client.xgroup_setid(
                            stream_name, self.consumer_group, "$"
                        )
                    except Exception:
                        pass
                self._stream_map[stream_name] = (sym, tf)

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
    ) -> bool:
        try:
            signal_data = parse_aggregated_signal(fields)
            if signal_data is None:
                self.narratives_skipped_total.inc()
                return True

            # Always cache latest signal for group synthesis (regardless of per-signal filter)
            cache_key_mem = f"{symbol}:{timeframe}"
            self._latest_signals[cache_key_mem] = signal_data

            # Gate: per-signal narrative only for eligible TFs and high-confidence signals
            if timeframe not in _NARRATIVE_ELIGIBLE_TFS:
                self.narratives_skipped_total.inc()
                self.logger.debug(
                    "Per-signal narrative skipped: ineligible TF",
                    symbol=symbol, timeframe=timeframe,
                )
                return True

            if signal_data["confidence"] <= _NARRATIVE_MIN_CONFIDENCE:
                self.narratives_skipped_total.inc()
                self.logger.debug(
                    "Per-signal narrative skipped: low confidence",
                    symbol=symbol, timeframe=timeframe,
                    confidence=signal_data["confidence"],
                )
                return True

            prompt = build_narrative_prompt(signal_data)
            t0 = time.time()
            narrative_text = await self.per_signal_chain.generate(
                prompt,
                SYSTEM_PROMPT,
                max_tokens=500,
                timeout=self._per_signal_timeout,
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
                    "model": self.per_signal_chain.last_provider_id or "unknown",
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
            return True

        except Exception as e:
            self.logger.error(
                "Error processing signal message",
                symbol=symbol,
                timeframe=timeframe,
                error=str(e),
            )
            self.error_count_total.inc()
            self._error_count += 1
            return False

    # ------------------------------------------------------------------
    # Main service loops
    # ------------------------------------------------------------------

    async def _process_loop(self) -> None:
        self.logger.info("Starting signal stream processing loop")
        all_streams = {name: ">" for name in self._stream_map}
        while self.running and not self.shutdown_requested:
            try:
                messages = await self.redis_client.xreadgroup(
                    self.consumer_group, self.consumer_name,
                    all_streams, count=10, block=1000,
                )
                for stream_bytes, msgs in messages:
                    stream_name = (
                        stream_bytes.decode()
                        if isinstance(stream_bytes, bytes)
                        else stream_bytes
                    )
                    symbol, timeframe = self._stream_map[stream_name]
                    to_ack: list[bytes] = []
                    for message_id, fields in msgs:
                        ok = await self._process_single_message(
                            symbol, timeframe, fields, stream_name, message_id
                        )
                        if ok:
                            to_ack.append(message_id)
                    if to_ack:
                        await self.redis_client.xack(
                            stream_name, self.consumer_group, *to_ack
                        )
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in narrative processing loop", error=str(e))
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

    async def _synthesize_group(self, group_name: str) -> None:
        """Check if group state changed and publish synthesis if so."""
        group_symbols = ASSET_GROUPS.get(group_name, [])

        # Gather current signals for this group across synthesis TFs
        current_signals: dict[str, dict] = {}
        for sym in group_symbols:
            for tf in _GROUP_SYNTHESIS_TFS:
                key = f"{sym}:{tf}"
                sig = self._latest_signals.get(key)
                if sig and sig.get("direction", 0) != 0:
                    current_signals[key] = sig

        # Compute fingerprint
        current_fp = extract_group_fingerprint(current_signals)

        # Compare with persisted state
        state_redis_key = f"{self.env_prefix}narrative:group:{group_name}:state"
        raw_state = await self.redis_client.hget(state_redis_key, "fingerprint_json")
        prior_fp_raw = json.loads(raw_state) if raw_state else {}
        # Redis JSON round-trip: tuples become lists; normalize for comparison
        prior_fp = {k: tuple(v) for k, v in prior_fp_raw.items()}

        if current_fp == prior_fp:
            return  # Nothing changed

        # Persist fingerprint BEFORE calling Ollama so a timeout/error doesn't
        # cause a retry loop on the next 30-second cycle.  If signals change
        # *during* the call the next iteration will detect the new fingerprint.
        await self.redis_client.hset(
            state_redis_key,
            "fingerprint_json",
            json.dumps({k: list(v) for k, v in current_fp.items()}),
        )
        await self.redis_client.expire(state_redis_key, 86400)  # 24h TTL

        # Build prompt and call group chain
        prompt = build_group_synthesis_prompt(group_name, current_signals)
        t0 = time.time()
        narrative_text = await self.group_chain.generate(
            prompt,
            GROUP_SYSTEM_PROMPT,
            max_tokens=300,
            timeout=self._group_timeout,
        )
        latency_ms = (time.time() - t0) * 1000

        if narrative_text:
            from src.core.stream_keys import narratives_group as sk_narratives_group
            stream_out = sk_narratives_group(self.env_prefix, group_name)
            ts = datetime.now(tz=UTC).isoformat()
            msg = {
                "group": group_name,
                "narrative": narrative_text,
                "timestamp": ts,
                "model": self.group_chain.last_provider_id or "unknown",
                "latency_ms": str(int(latency_ms)),
            }
            await self.redis_client.xadd(stream_out, msg, maxlen=50, approximate=True)
            cache_key_hash = f"{self.env_prefix}narrative:group:{group_name}:latest"
            await self.redis_client.hset(cache_key_hash, mapping=msg)
            await self.redis_client.expire(cache_key_hash, 3600)  # 1 hour TTL

            self.group_narratives_generated.inc()
            self.logger.info(
                "Group narrative published",
                group=group_name,
                signals=len(current_signals),
                latency_ms=round(latency_ms, 1),
            )
        else:
            self.logger.warning("Group Ollama returned no narrative", group=group_name)

    async def _group_synthesis_loop(self) -> None:
        """Run group synthesis every 30s — fires Ollama only on material changes."""
        self.logger.info("Starting group synthesis loop")
        while self.running and not self.shutdown_requested:
            try:
                try:
                    await asyncio.wait_for(self.shutdown_event.wait(), timeout=30)
                    break  # shutdown requested
                except TimeoutError:
                    pass  # normal — run synthesis
                if self.shutdown_requested:
                    break
                for group_name in ASSET_GROUPS:
                    if self.shutdown_requested:
                        break
                    try:
                        await self._synthesize_group(group_name)
                    except Exception as exc:
                        self.logger.error(
                            "Group synthesis failed", group=group_name, error=str(exc)
                        )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.logger.error("Error in group synthesis loop", error=str(exc))
                await asyncio.sleep(5)

    async def start(self) -> None:
        self.logger.info("Starting AI Narrative Service", config=self.config["service"])
        try:
            loop = asyncio.get_running_loop()
            self._register_signal_handlers(loop)
            await self._connect_redis()
            await self._setup_consumer_groups()

            self.running = True
            tasks = [
                asyncio.create_task(self._process_loop()),
                asyncio.create_task(self._health_monitor_loop()),
                asyncio.create_task(self._group_synthesis_loop()),
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
