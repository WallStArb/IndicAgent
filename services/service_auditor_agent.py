"""ServiceAuditorAgent — pipeline health monitor and self-healer.

Hybrid three-layer design:
  systemd  -> process liveness (WatchdogSec kills hung processes)
  Prometheus -> metrics/lag (15s check cycle via /api/v1/query)
  This agent -> intelligence: graduated response, DAG-ordered restarts, audit trail

Graduated response policy:
  HEALTHY   no action
  DEGRADED  lag > threshold, 2 consecutive checks -> emit degraded event
  RESTART   dead/failed/StartLimitHit -> reset-failed + start -> emit restart event
  ESCALATE  3 restarts in 10 min -> DLQ + stop retrying -> emit escalated event
  RECOVERED returns healthy -> emit recovered event with duration_degraded_s

Every state transition is persisted to service_health_events (TimescaleDB) and
published to system.health.events (Kafka) -- both are permanent audit trails.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import aiohttp
import asyncpg

from src.config.settings import get_settings
from src.core.agent.base import BaseAgent
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.stream_keys import topic_health_events, topic_health_events_dlq, topic_roll_events
from src.observability.metrics import SERVICE_AUDITOR_SERVICE_RESTARTS_TOTAL

_ESCALATION_WINDOW = timedelta(minutes=10)
_ESCALATION_THRESHOLD = 3
_PROMETHEUS_URL = "http://localhost:9090/api/v1/query"


# ---------------------------------------------------------------------------
# Service registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ServiceSpec:
    unit: str
    metrics_port: int | None
    lag_threshold_messages: int  # 0 = not a Kafka consumer
    dag_order: int  # lower = restart first
    market_hours_only: bool


SERVICE_REGISTRY: list[ServiceSpec] = [
    ServiceSpec("indicagent-ibkr-provider", 9129, 0, 1, False),
    ServiceSpec("indicagent-provider-merger", 9130, 500, 2, True),
    ServiceSpec("indicagent-bar-aggregator-compute", 9120, 500, 3, True),
    ServiceSpec("indicagent-bar-auditor", 9123, 200, 3, True),
    ServiceSpec("indicagent-bar-writer", 9121, 1000, 4, True),
    ServiceSpec("indicagent-intelligence-pipeline@1", 9125, 500, 5, True),
    ServiceSpec("indicagent-feature-writer", 9116, 1000, 6, True),
    ServiceSpec("indicagent-signal-tracker", 9115, 500, 6, True),
    ServiceSpec("indicagent-signal-writer", 9119, 500, 6, True),
    ServiceSpec("indicagent-ai-narrative", 9113, 200, 7, True),
    ServiceSpec("indicagent-llm-writer", 9117, 500, 7, True),
    ServiceSpec("indicagent-cross-asset", 9118, 200, 7, True),
]

# Pre-sorted once — dag_order is immutable, re-sorting every 15s is wasteful
_SORTED_REGISTRY: list[ServiceSpec] = sorted(SERVICE_REGISTRY, key=lambda s: s.dag_order)

# Maps persistence_consumer_lag agent_id label -> systemd unit name
_AGENT_ID_TO_UNIT: dict[str, str] = {
    "bar_writer_agent": "indicagent-bar-writer",
    "bar_aggregator_agent": "indicagent-bar-aggregator-compute",
    "intelligence_pipeline_agent": "indicagent-intelligence-pipeline@1",
    "feature_writer_agent": "indicagent-feature-writer",
    "signal_tracker_agent": "indicagent-signal-tracker",
    "signal_writer_agent": "indicagent-signal-writer",
    "ai_narrative_service": "indicagent-ai-narrative",
    "llm_writer_service": "indicagent-llm-writer",
    "cross_asset_service": "indicagent-cross-asset",
    "bar_auditor_agent": "indicagent-bar-auditor",
    "provider_merger_agent": "indicagent-provider-merger",
}


# ---------------------------------------------------------------------------
# Per-service runtime state
# ---------------------------------------------------------------------------


@dataclass
class ServiceState:
    degraded_since: datetime | None = None
    degraded_check_count: int = 0
    restart_times: list[datetime] = field(default_factory=list)
    escalated: bool = False
    last_known_state: str = "healthy"


# ---------------------------------------------------------------------------
# Pure helpers (no I/O -- easily unit-testable)
# ---------------------------------------------------------------------------


def _parse_systemctl_show(output: str) -> tuple[str, str]:
    """Parse 'systemctl show --property=ActiveState,SubState' stdout."""
    props: dict[str, str] = {}
    for line in output.strip().splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            props[k.strip()] = v.strip()
    return props.get("ActiveState", "unknown"), props.get("SubState", "unknown")


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class ServiceAuditorAgent(BaseAgent):
    """Monitors all pipeline services, self-heals, and audits every event."""

    def __init__(self) -> None:
        _settings = get_settings()
        super().__init__(
            name="service_auditor_agent",
            metrics_port=9131,
            max_idle_seconds=600,
            settings=_settings,
        )
        self._db_pool: asyncpg.Pool | None = None
        self._http_session: aiohttp.ClientSession | None = None
        self._kafka_producer: KafkaProducerClient | None = None
        self._roll_consumer: KafkaConsumerClient | None = None
        self._service_states: dict[str, ServiceState] = {
            s.unit: ServiceState() for s in SERVICE_REGISTRY
        }
        self._handled_rolls: set[tuple[str, str]] = set()
        self._topics_produced = [
            topic_health_events(self.env_name),
            topic_health_events_dlq(self.env_name),
        ]
        self._prometheus_check_interval = 15
        self._systemd_check_interval = 30
        self._heartbeat_interval = 60

    @property
    def topics_produced(self) -> list[str]:
        return self._topics_produced

    async def _setup(self) -> None:
        self._db_pool = await asyncpg.create_pool(
            self.settings.database_url, min_size=1, max_size=3
        )
        self._http_session = aiohttp.ClientSession()
        self._kafka_producer = KafkaProducerClient(
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
        )
        await self._kafka_producer.start()
        self._roll_consumer = KafkaConsumerClient(
            topic_roll_events(self.env_name),
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
            group_id="service_auditor_roll_consumer",
            auto_offset_reset="latest",
        )
        await self._roll_consumer.start()
        self.logger.info(
            "service_auditor_agent.setup_complete",
            services=len(SERVICE_REGISTRY),
            env=self.env_name,
        )


    async def _teardown(self) -> None:
        if self._kafka_producer:
            await self._kafka_producer.stop()
        if self._roll_consumer:
            await self._roll_consumer.stop()
        if self._http_session:
            await self._http_session.close()
        if self._db_pool:
            await self._db_pool.close()

    async def _run(self) -> None:
        # lag_task created by BaseAgent.start() at line 155
        prom_task = asyncio.create_task(self._prometheus_check_loop())
        sysd_task = asyncio.create_task(self._systemd_check_loop())
        hb_task = asyncio.create_task(self._heartbeat_loop())
        roll_task = asyncio.create_task(self._roll_consumer_loop())
        await self._stop_event.wait()
        for t in (prom_task, sysd_task, hb_task, roll_task):
            t.cancel()
        for t in (prom_task, sysd_task, hb_task, roll_task):
            try:
                await t
            except asyncio.CancelledError:
                pass

    # -- Check loops ----------------------------------------------------------

    async def _prometheus_check_loop(self) -> None:
        while self.running:
            await asyncio.sleep(self._prometheus_check_interval)
            try:
                health_set, lag_map = await asyncio.gather(
                    self._fetch_prometheus_health(),
                    self._fetch_prometheus_lag(),
                )
                for spec in _SORTED_REGISTRY:
                    has_metrics = spec.unit in health_set
                    lag = lag_map.get(spec.unit, 0)
                    active = "active" if has_metrics else "unknown"
                    sub = "running" if has_metrics else "no_metrics"
                    await self._evaluate_service(spec, active, sub, lag, has_metrics)
            except Exception as exc:
                self.logger.error("service_auditor.prometheus_check_failed", error=str(exc))

    async def _systemd_check_loop(self) -> None:
        while self.running:
            await asyncio.sleep(self._systemd_check_interval)
            try:
                for spec in _SORTED_REGISTRY:
                    active, sub = await self._check_systemd_state(spec.unit)
                    if active in ("failed", "inactive") or sub == "start-limit-hit":
                        await self._evaluate_service(spec, active, sub, 0, False)
            except Exception as exc:
                self.logger.error("service_auditor.systemd_check_failed", error=str(exc))

    async def _heartbeat_loop(self) -> None:
        while self.running:
            await asyncio.sleep(self._heartbeat_interval)
            try:
                await self._emit_health_event(
                    service="service_auditor_agent",
                    event_type="heartbeat",
                    previous_state="healthy",
                    reason=None,
                    lag_messages=None,
                    restart_count=None,
                    duration_degraded_s=None,
                )
            except Exception as exc:
                self.logger.error("service_auditor.heartbeat_failed", error=str(exc))

    # -- Graduated response ---------------------------------------------------

    async def _evaluate_service(
        self,
        spec: ServiceSpec,
        active_state: str,
        sub_state: str,
        lag_messages: int,
        has_metrics: bool,
    ) -> None:
        state = self._service_states[spec.unit]
        if state.escalated:
            return

        now = datetime.now(UTC)
        is_dead = active_state in ("failed", "inactive") or sub_state == "start-limit-hit"
        is_laggy = spec.lag_threshold_messages > 0 and lag_messages > spec.lag_threshold_messages

        # -- RESTART ----------------------------------------------------------
        if is_dead:
            state.restart_times = [t for t in state.restart_times if now - t < _ESCALATION_WINDOW]

            if len(state.restart_times) >= _ESCALATION_THRESHOLD:
                state.escalated = True
                duration = (
                    (now - state.degraded_since).total_seconds() if state.degraded_since else None
                )
                await self._emit_health_event(
                    service=spec.unit,
                    event_type="escalated",
                    previous_state=state.last_known_state,
                    reason=f"{active_state}/{sub_state}",
                    lag_messages=None,
                    restart_count=len(state.restart_times),
                    duration_degraded_s=duration,
                )
                await self._send_to_dlq(
                    {"service": spec.unit, "restart_count": len(state.restart_times)},
                    Exception("escalation threshold reached"),
                )
                await self._dispatch_webhook(
                    "CRITICAL",
                    f"Service escalated: {spec.unit}",
                    f"{len(state.restart_times)} restarts in 10 min — stopped retrying.",
                )
                self.logger.error("service_auditor.escalated", service=spec.unit)
                return

            if not state.degraded_since:
                state.degraded_since = now
            state.restart_times.append(now)
            await self._emit_health_event(
                service=spec.unit,
                event_type="restart",
                previous_state=state.last_known_state,
                reason=f"{active_state}/{sub_state}",
                lag_messages=None,
                restart_count=len(state.restart_times),
                duration_degraded_s=None,
            )
            state.last_known_state = "restarting"
            await self._restart_service(spec)
            return

        # -- DEGRADED ---------------------------------------------------------
        if is_laggy:
            if not state.degraded_since:
                state.degraded_since = now
            state.degraded_check_count += 1
            if state.degraded_check_count >= 2:
                await self._emit_health_event(
                    service=spec.unit,
                    event_type="degraded",
                    previous_state=state.last_known_state,
                    reason=f"lag={lag_messages}>{spec.lag_threshold_messages}",
                    lag_messages=lag_messages,
                    restart_count=len(state.restart_times),
                    duration_degraded_s=None,
                )
                state.last_known_state = "degraded"
            return

        # -- RECOVERED --------------------------------------------------------
        if state.last_known_state in ("degraded", "restarting"):
            duration = (
                (now - state.degraded_since).total_seconds() if state.degraded_since else None
            )
            await self._emit_health_event(
                service=spec.unit,
                event_type="recovered",
                previous_state=state.last_known_state,
                reason=None,
                lag_messages=lag_messages,
                restart_count=len(state.restart_times),
                duration_degraded_s=duration,
            )

        state.degraded_since = None
        state.degraded_check_count = 0
        state.last_known_state = "healthy"

    # -- systemd interface ----------------------------------------------------

    async def _check_systemd_state(self, unit: str) -> tuple[str, str]:
        """Query systemd unit state via subprocess list args (no shell injection)."""
        proc = await asyncio.create_subprocess_exec(
            "systemctl",
            "show",
            unit,
            "--property=ActiveState,SubState",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        return _parse_systemctl_show(stdout.decode())

    async def _restart_service(self, spec: ServiceSpec) -> None:
        """reset-failed clears StartLimitBurst; start re-launches the unit."""
        self.logger.warning("service_auditor.restarting", service=spec.unit)
        for cmd_args in (
            ["systemctl", "reset-failed", spec.unit],
            ["systemctl", "start", spec.unit],
        ):
            proc = await asyncio.create_subprocess_exec(
                *cmd_args,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                self.logger.error(
                    "service_auditor.restart_cmd_failed",
                    args=cmd_args,
                    stderr=stderr.decode().strip(),
                )
        # Increment metric after successful restart
        SERVICE_AUDITOR_SERVICE_RESTARTS_TOTAL.labels(service_name=spec.unit).inc()

    # -- Prometheus interface -------------------------------------------------

    async def _fetch_prometheus_health(self) -> set[str]:
        results = await self._query_prometheus("indicagent_service_health > 0")
        return {r["metric"].get("service", "") for r in results}

    async def _fetch_prometheus_lag(self) -> dict[str, int]:
        results = await self._query_prometheus("persistence_consumer_lag")
        out: dict[str, int] = {}
        for r in results:
            unit = _AGENT_ID_TO_UNIT.get(r["metric"].get("agent_id", ""))
            if unit:
                out[unit] = int(float(r["value"][1]))
        return out

    async def _query_prometheus(self, query: str) -> list[dict]:
        assert self._http_session is not None
        async with self._http_session.get(
            _PROMETHEUS_URL,
            params={"query": query},
            timeout=aiohttp.ClientTimeout(total=5),
        ) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
        return data.get("data", {}).get("result", [])

    # -- Persistence ----------------------------------------------------------

    async def _emit_health_event(
        self,
        service: str,
        event_type: str,
        previous_state: str | None,
        reason: str | None,
        lag_messages: int | None,
        restart_count: int | None,
        duration_degraded_s: float | None,
    ) -> None:
        now = datetime.now(UTC)
        self.logger.info(
            "service_auditor.event",
            service=service,
            event_type=event_type,
            reason=reason,
        )
        async with self._db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO service_health_events
                  (ts, service, event_type, previous_state, reason,
                   lag_messages, restart_count, duration_degraded_s)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                now,
                service,
                event_type,
                previous_state,
                reason,
                lag_messages,
                restart_count,
                duration_degraded_s,
            )
        await self._kafka_producer.publish(
            topic_health_events(self.env_name),
            {
                "ts": now.isoformat(),
                "service": service,
                "event_type": event_type,
                "previous_state": previous_state,
                "reason": reason,
                "lag_messages": lag_messages,
                "restart_count": restart_count,
                "duration_degraded_s": duration_degraded_s,
            },
            service,
        )

    async def _send_to_dlq(self, payload: dict, error: Exception) -> None:
        self.logger.error(
            "service_auditor.dlq",
            service=payload.get("service"),
            error=str(error),
        )
        await self._kafka_producer.publish(
            topic_health_events_dlq(self.env_name),
            payload,
            payload.get("service", "unknown"),
        )

    async def _dispatch_webhook_http(self, url: str, payload: dict, log_name: str) -> bool:
        """Generic webhook dispatcher with unified error handling.

        Returns True on success, False on failure. Logs at appropriate level.
        """
        try:
            assert self._http_session is not None
            async with self._http_session.post(
                url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status in (200, 204):
                    self.logger.info("webhook.success", service=log_name)
                    return True
                else:
                    self.logger.warning("webhook.failed", status=resp.status, service=log_name)
                    return False
        except Exception as exc:
            self.logger.error("webhook.error", service=log_name, error=str(exc))
            return False

    async def _notify_telegram(self, title: str, body: str) -> None:
        """POST CRITICAL alert to Telegram bot. No-op if token not configured."""
        token = self.settings.telegram_bot_token
        chat_id = self.settings.telegram_chat_id
        if not token or not chat_id:
            return
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        text = f"*[CRITICAL]* {title}\n{body}"
        await self._dispatch_webhook_http(
            url,
            {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            "telegram",
        )

    async def _notify_discord(self, title: str, body: str, severity: str) -> None:
        """POST HIGH/MEDIUM alert to Discord webhook. No-op if URL not configured."""
        url = self.settings.discord_webhook_url
        if not url:
            return
        content = f"**[{severity}]** {title}\n{body}"
        await self._dispatch_webhook_http(url, {"content": content}, "discord")

    # -- Roll automation -------------------------------------------------------

    async def _roll_consumer_loop(self) -> None:
        """Consume topic_roll_events and trigger ibkr-provider restart on roll_complete."""
        if self._roll_consumer is None:
            return
        async for _topic, _key, payload in self._roll_consumer.messages():
            if self._stop_event.is_set():
                break
            try:
                await self._handle_roll_event(payload)
            except Exception as exc:
                self.logger.error("roll_consumer.error", error=str(exc))

    async def _handle_roll_event(self, payload: dict) -> None:
        """Process a RollEvent. Deduped by (symbol, new_contract) — handles both
        volume and calendar detection methods without double-restarting ibkr-provider."""
        symbol = payload.get("symbol", "")
        new_contract = payload.get("new_contract", "")
        old_contract = payload.get("old_contract", "")

        if not symbol or not new_contract:
            return

        dedup_key = (symbol, new_contract)

        # Size-based dedup to prevent unbounded growth
        if len(self._handled_rolls) > 1000:
            self._handled_rolls.clear()

        if dedup_key in self._handled_rolls:
            self.logger.debug("roll_consumer.dedup_skip", symbol=symbol, new_contract=new_contract)
            return

        self._handled_rolls.add(dedup_key)
        detection_method = payload.get("detection_method", "volume")
        self.logger.info(
            "roll_automation.triggered",
            symbol=symbol,
            old_contract=old_contract,
            new_contract=new_contract,
            detection_method=detection_method,
        )

        await self._dispatch_webhook(
            "HIGH",
            f"Futures roll: {symbol} {old_contract} → {new_contract}",
            "Restarting indicagent-ibkr-provider to subscribe to new front-month contract.",
        )
        await self._restart_ibkr_provider()

    async def _restart_ibkr_provider(self) -> None:
        """Restart indicagent-ibkr-provider via sudo systemctl.

        Requires sudoers entry (one-time manual setup):
            bg ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart indicagent-ibkr-provider

        Uses async subprocess to avoid blocking the event loop.
        """
        cmd = ["sudo", "systemctl", "restart", "indicagent-ibkr-provider"]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            if proc.returncode != 0:
                self.logger.error(
                    "roll_automation.restart_failed",
                    service="indicagent-ibkr-provider",
                    returncode=proc.returncode,
                    stderr=stderr.decode() if stderr else "",
                )
                return
            SERVICE_AUDITOR_SERVICE_RESTARTS_TOTAL.labels(
                service_name="indicagent-ibkr-provider"
            ).inc()
            self.logger.info("roll_automation.restart_complete", service="indicagent-ibkr-provider")
        except Exception as exc:
            self.logger.error(
                "roll_automation.restart_failed",
                service="indicagent-ibkr-provider",
                error=str(exc),
            )

    async def _dispatch_webhook(self, severity: str, title: str, body: str) -> None:
        """Route alert to correct contact point(s) based on severity.

        CRITICAL  -> Telegram only (immediate DM)
        HIGH      -> Discord only (#indicagent-ops)
        MEDIUM    -> Discord only (#indicagent-ops)
        Other     -> no-op (log at debug)
        """
        if severity == "CRITICAL":
            await self._notify_telegram(title, body)
        elif severity in ("HIGH", "MEDIUM"):
            await self._notify_discord(title, body, severity)
        else:
            self.logger.debug("dispatch_webhook.unknown_severity", severity=severity)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import asyncio

    asyncio.run(ServiceAuditorAgent().start())
