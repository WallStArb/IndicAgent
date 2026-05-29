"""ConfigConsumerMixin — two-phase config integration for BaseAgent.

Phase A: _pre_setup_config_load()
  Called BEFORE _setup() so service-specific setup can read OPS config values
  (e.g., thresholds, feature flags). NON-FATAL on DB failure.

Phase B: _setup_config_consumer()
  Called AFTER _setup(). Subscribes to topic_config_updates for hot-reload.
  NON-FATAL on Kafka failure. Skipped for INFRA/STRUCT layers.

Storm prevention: _config_prefixes allowlist filters Kafka messages cheaply
  (no parse, no work) so agents ignore irrelevant key changes.

Codex HIGH finding addressed: config snapshot loads BEFORE _setup(), not after.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime
from typing import Any

import structlog

from src.config.config_service import ConfigService
from src.core.kafka_utils import KafkaConsumerClient
from src.core.stream_keys import topic_config_updates
from src.observability.metrics import (
    CONFIG_LAST_RELOAD_TIMESTAMP_SECONDS,
    CONFIG_RELOAD_LATENCY_SECONDS,
    CONFIG_RELOAD_TOTAL,
    CONFIG_STALE_TOTAL,
)


class ConfigConsumerMixin:
    """Mixin that adds two-phase config integration to BaseAgent.

    Subclasses may override:
      _config_layer = "INFRA"   # skip Kafka subscription (INFRA/STRUCT agents)
      _config_prefixes = ("regime.", "swarm.")  # accept only these key prefixes
    """

    # Per-instance state — initialized in __init__ via mixin protocol.
    # BaseAgent.__init__ sets these explicitly so class attrs are just documentation.
    _config_cache: dict[str, Any]
    _config_layer: str = "OPS"
    _config_prefixes: tuple[str, ...] = ()
    _config_consumer: KafkaConsumerClient | None
    _config_reload_task: asyncio.Task | None  # type: ignore[type-arg]
    _config_loaded: bool

    async def _pre_setup_config_load(self) -> None:
        """Phase A: load OPS snapshot BEFORE service _setup().

        Called from BaseAgent.start() BEFORE await self._setup() so that _setup()
        can read OPS config values (e.g., thresholds, feature flags). This addresses
        the Codex HIGH finding: "BaseAgent lifecycle ordering may be wrong".

        NON-FATAL: on DB failure, _config_cache stays empty (first start) or
        retains last-known-good values (if already populated). Service continues
        with code defaults.

        Emits CONFIG_STALE_TOTAL on failure with agent_id and reason labels.
        """
        try:
            svc = ConfigService(self.settings.database_url)  # type: ignore[attr-defined]
            await svc.initialize()
            snapshot = await svc.list()
            # Filter by prefixes if set; otherwise accept all OPS keys
            if self._config_prefixes:
                self._config_cache = {
                    k: v for k, v in snapshot.items() if k.startswith(self._config_prefixes)
                }
            else:
                self._config_cache = dict(snapshot)
            self._config_loaded = True
            CONFIG_LAST_RELOAD_TIMESTAMP_SECONDS.set(
                time.time(), {"agent_id": self.name}  # type: ignore[attr-defined]
            )
            structlog.get_logger().info(
                "config.snapshot.loaded",
                agent=self.name,  # type: ignore[attr-defined]
                keys=len(self._config_cache),
            )
        except Exception as exc:
            CONFIG_STALE_TOTAL.add(
                1,
                {
                    "agent_id": self.name,  # type: ignore[attr-defined]
                    "reason": type(exc).__name__,
                },
            )
            structlog.get_logger().warning(
                "config.snapshot.load_failed",
                agent=self.name,  # type: ignore[attr-defined]
                error=str(exc),
            )
            # Do NOT re-raise — NON-FATAL

    async def _setup_config_consumer(self) -> None:
        """Phase B: subscribe to Kafka AFTER service _setup() completes.

        Hot-reload via Kafka requires Kafka to be reachable. Service _setup()
        should not depend on Kafka for config; if it needs OPS values they came
        from the Phase A snapshot.

        NON-FATAL. If self._config_layer != "OPS", skip subscription (INFRA/STRUCT
        services don't hot-reload, and the outbox dispatcher itself skips to avoid
        circular dependency).

        IMPORTANT: KafkaConsumerClient takes the topic(s) as its FIRST positional
        argument at construction time. There is NO subscribe method — topics are
        bound at __init__. The correct Settings attribute is `kafka_bootstrap_servers`
        (NOT `kafka_brokers`); see services/alerting_agent.py line 51.
        """
        if self._config_layer != "OPS":
            return
        try:
            self._config_consumer = KafkaConsumerClient(
                topic_config_updates(self.env_name),  # type: ignore[attr-defined]
                bootstrap_servers=self.settings.kafka_bootstrap_servers,  # type: ignore[attr-defined]
                group_id=f"{self.name}_config_consumer",  # type: ignore[attr-defined]
            )
            await self._config_consumer.start()
            # NOTE: topic was bound at construction time (KafkaConsumerClient first positional arg).
            self._config_reload_task = asyncio.create_task(self._reload_config_loop())
        except Exception as exc:
            CONFIG_STALE_TOTAL.add(
                1,
                {
                    "agent_id": self.name,  # type: ignore[attr-defined]
                    "reason": "kafka_subscribe_failed",
                },
            )
            structlog.get_logger().warning(
                "config.consumer.setup_failed",
                agent=self.name,  # type: ignore[attr-defined]
                error=str(exc),
            )
            # Do NOT re-raise — NON-FATAL

    async def _reload_config_loop(self) -> None:
        """Kafka message loop with prefix filtering to avoid reload storms.

        Per consensus LOW finding: every agent ignores keys outside its
        _config_prefixes allowlist cheaply (dict lookup; no parse, no work,
        no metric noise).

        Records CONFIG_RELOAD_LATENCY_SECONDS = (now - changed_at) for each
        accepted key (per Gemini suggestion: detect agents falling behind the
        update stream).
        """
        try:
            async for _topic, _key, payload in self._config_consumer.messages():  # type: ignore[union-attr]
                try:
                    config_key = payload.get("config_key")
                    if not config_key:
                        continue
                    # Prefix filter: skip irrelevant keys cheaply
                    if self._config_prefixes and not config_key.startswith(self._config_prefixes):
                        continue
                    value_type = payload.get("value_type", "string")
                    parsed = self._parse_config_value(payload.get("config_value"), value_type)
                    self._config_cache[config_key] = parsed
                    self._config_loaded = True
                    # Latency: changed_at -> now
                    changed_at_iso = payload.get("changed_at")
                    if changed_at_iso:
                        try:
                            changed_at = datetime.fromisoformat(
                                changed_at_iso.replace("Z", "+00:00")
                            )
                            lag_s = (datetime.now(UTC) - changed_at).total_seconds()
                            CONFIG_RELOAD_LATENCY_SECONDS.record(
                                lag_s, {"agent_id": self.name}  # type: ignore[attr-defined]
                            )
                        except Exception:
                            pass
                    CONFIG_RELOAD_TOTAL.add(
                        1,
                        {
                            "agent_id": self.name,  # type: ignore[attr-defined]
                            "key": config_key,
                        },
                    )
                    CONFIG_LAST_RELOAD_TIMESTAMP_SECONDS.set(
                        time.time(), {"agent_id": self.name}  # type: ignore[attr-defined]
                    )
                    # Phase 109: subclass hook for post-reload reactions.
                    # No-op by default; exceptions from the hook are caught and do NOT
                    # terminate the loop.
                    try:
                        await self._on_config_message_received(config_key, parsed)
                    except Exception as hook_exc:
                        structlog.get_logger().warning(
                            "config.hook_failed",
                            agent=self.name,  # type: ignore[attr-defined]
                            error=str(hook_exc),
                        )
                except Exception as exc:
                    CONFIG_STALE_TOTAL.add(
                        1,
                        {
                            "agent_id": self.name,  # type: ignore[attr-defined]
                            "reason": "parse_failed",
                        },
                    )
                    structlog.get_logger().warning(
                        "config.parse_failed",
                        agent=self.name,  # type: ignore[attr-defined]
                        error=str(exc),
                    )
                if not self.running:  # type: ignore[attr-defined]
                    break
        except Exception as exc:
            CONFIG_STALE_TOTAL.add(
                1,
                {
                    "agent_id": self.name,  # type: ignore[attr-defined]
                    "reason": "consumer_loop_failed",
                },
            )
            structlog.get_logger().error(
                "config.consumer.loop_failed",
                agent=self.name,  # type: ignore[attr-defined]
                error=str(exc),
            )

    async def _teardown_config_consumer(self) -> None:
        """Cancel reload task and stop Kafka consumer on agent shutdown."""
        if self._config_reload_task is not None:
            self._config_reload_task.cancel()
            try:
                await self._config_reload_task
            except asyncio.CancelledError:
                pass
            self._config_reload_task = None
        if self._config_consumer is not None:
            try:
                await self._config_consumer.stop()
            except Exception:
                pass
            self._config_consumer = None

    def get_config(self, key: str, default: Any = None) -> Any:
        """Return cached config value for key, or default if not present."""
        return self._config_cache.get(key, default)

    def _parse_config_value(self, value: str | None, value_type: str) -> Any:
        """Parse raw string config value into the typed Python value.

        Supported value_types: int, float, bool, json, string (default).
        Invalid conversions fall back to the raw string.
        """
        if value is None:
            return None
        try:
            if value_type == "int":
                return int(value)
            if value_type == "float":
                return float(value)
            if value_type == "bool":
                return value.lower() in ("true", "1", "yes")
            if value_type == "json":
                return json.loads(value)
            return str(value)
        except (ValueError, TypeError, json.JSONDecodeError):
            return str(value)

    async def _on_config_message_received(self, key: str, value: Any) -> None:
        """No-op hook called after each accepted Kafka config message is cached.

        Subclasses (e.g., ServiceAuditorAgent in Plan 05 Task 3) override this to
        react to specific config_key updates (e.g., reload lag-threshold map on
        alert.lag.* keys) WITHOUT having to override the whole _reload_config_loop.

        Exceptions raised by the hook are caught and logged by the loop; they do NOT
        break consumption.
        """
        return None
