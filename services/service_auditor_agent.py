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

from src.config.settings import Settings
from src.core.agent.base import BaseAgent
from src.core.kafka_utils import KafkaProducerClient
from src.core.stream_keys import topic_health_events, topic_health_events_dlq

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
    lag_threshold_messages: int   # 0 = not a Kafka consumer
    dag_order: int                # lower = restart first
    market_hours_only: bool


SERVICE_REGISTRY: list[ServiceSpec] = [
    ServiceSpec("indicagent-ibkr-provider",          9129,  0,    1, False),
    ServiceSpec("indicagent-provider-merger",         9130,  500,  2, True),
    ServiceSpec("indicagent-bar-aggregator-compute",  9120,  500,  3, True),
    ServiceSpec("indicagent-bar-auditor",             9123,  200,  3, True),
    ServiceSpec("indicagent-bar-writer",              9121,  1000, 4, True),
    ServiceSpec("indicagent-intelligence-pipeline@1", 9125,  500,  5, True),
    ServiceSpec("indicagent-feature-writer",          9116,  1000, 6, True),
    ServiceSpec("indicagent-signal-tracker",          9115,  500,  6, True),
    ServiceSpec("indicagent-signal-writer",           9119,  500,  6, True),
    ServiceSpec("indicagent-ai-narrative",            9113,  200,  7, True),
    ServiceSpec("indicagent-llm-writer",              9117,  500,  7, True),
    ServiceSpec("indicagent-cross-asset",             9118,  200,  7, True),
]

# Maps persistence_consumer_lag agent_id label -> systemd unit name
_AGENT_ID_TO_UNIT: dict[str, str] = {
    "bar_writer_agent":             "indicagent-bar-writer",
    "bar_aggregator_agent":         "indicagent-bar-aggregator-compute",
    "intelligence_pipeline_agent":  "indicagent-intelligence-pipeline@1",
    "feature_writer_agent":         "indicagent-feature-writer",
    "signal_tracker_agent":         "indicagent-signal-tracker",
    "signal_writer_agent":          "indicagent-signal-writer",
    "ai_narrative_service":         "indicagent-ai-narrative",
    "llm_writer_service":           "indicagent-llm-writer",
    "cross_asset_service":          "indicagent-cross-asset",
    "bar_auditor_agent":            "indicagent-bar-auditor",
    "provider_merger_agent":        "indicagent-provider-merger",
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


def _agent_id_to_unit(agent_id: str) -> str | None:
    return _AGENT_ID_TO_UNIT.get(agent_id)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class ServiceAuditorAgent(BaseAgent):
    """Monitors all pipeline services, self-heals, and audits every event."""

    def __init__(self) -> None:
        settings = Settings()
        super().__init__(name="service_auditor_agent", metrics_port=9131)
        self._settings = settings
        self._env_name: str = getattr(settings, "env_prefix", "") or ""
        self._db_pool: asyncpg.Pool | None = None
        self._kafka_producer: KafkaProducerClient | None = None
        self._service_states: dict[str, ServiceState] = {
            s.unit: ServiceState() for s in SERVICE_REGISTRY
        }
        self._prometheus_check_interval = 15
        self._systemd_check_interval = 30
        self._heartbeat_interval = 60

    @property
    def topics_produced(self) -> list[str]:
        return [
            topic_health_events(self._env_name),
            topic_health_events_dlq(self._env_name),
        ]

    async def _setup(self) -> None:
        self._db_pool = await asyncpg.create_pool(
            self._settings.database_url, min_size=1, max_size=3
        )
        self._kafka_producer = KafkaProducerClient(
            bootstrap_servers=self._settings.kafka_bootstrap_servers,
        )
        await self._kafka_producer.start()
        self.logger.info(
            "service_auditor_agent.setup_complete",
            services=len(SERVICE_REGISTRY),
            env=self._env_name,
        )

    async def _teardown(self) -> None:
        if self._kafka_producer:
            await self._kafka_producer.stop()
        if self._db_pool:
            await self._db_pool.close()

    async def _run(self) -> None:
        prom_task = asyncio.create_task(self._prometheus_check_loop())
        sysd_task = asyncio.create_task(self._systemd_check_loop())
        hb_task   = asyncio.create_task(self._heartbeat_loop())
        await self._stop_event.wait()
        for t in (prom_task, sysd_task, hb_task):
            t.cancel()
        for t in (prom_task, sysd_task, hb_task):
            try:
                await t
            except asyncio.CancelledError:
                pass

    # -- Check loops ----------------------------------------------------------

    async def _prometheus_check_loop(self) -> None:
        while self.running:
            await asyncio.sleep(self._prometheus_check_interval)
            try:
                health_set = await self._fetch_prometheus_health()
                lag_map    = await self._fetch_prometheus_lag()
                for spec in sorted(SERVICE_REGISTRY, key=lambda s: s.dag_order):
                    has_metrics = spec.unit in health_set
                    lag = lag_map.get(spec.unit, 0)
                    active = "active" if has_metrics else "unknown"
                    sub    = "running" if has_metrics else "no_metrics"
                    await self._evaluate_service(spec, active, sub, lag, has_metrics)
            except Exception as exc:
                self.logger.error("service_auditor.prometheus_check_failed", error=str(exc))

    async def _systemd_check_loop(self) -> None:
        while self.running:
            await asyncio.sleep(self._systemd_check_interval)
            try:
                for spec in sorted(SERVICE_REGISTRY, key=lambda s: s.dag_order):
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

        is_dead  = active_state in ("failed", "inactive") or sub_state == "start-limit-hit"
        is_laggy = spec.lag_threshold_messages > 0 and lag_messages > spec.lag_threshold_messages

        # -- RESTART ----------------------------------------------------------
        if is_dead:
            now = datetime.now(UTC)
            state.restart_times = [t for t in state.restart_times if now - t < _ESCALATION_WINDOW]

            if len(state.restart_times) >= _ESCALATION_THRESHOLD:
                state.escalated = True
                duration = (
                    (now - state.degraded_since).total_seconds()
                    if state.degraded_since else None
                )
                await self._emit_health_event(
                    service=spec.unit, event_type="escalated",
                    previous_state=state.last_known_state,
                    reason=f"{active_state}/{sub_state}",
                    lag_messages=None, restart_count=len(state.restart_times),
                    duration_degraded_s=duration,
                )
                await self._send_to_dlq(
                    {"service": spec.unit, "restart_count": len(state.restart_times)},
                    Exception("escalation threshold reached"),
                )
                self.logger.error("service_auditor.escalated", service=spec.unit)
                return

            if not state.degraded_since:
                state.degraded_since = now
            state.restart_times.append(now)
            await self._emit_health_event(
                service=spec.unit, event_type="restart",
                previous_state=state.last_known_state,
                reason=f"{active_state}/{sub_state}",
                lag_messages=None, restart_count=len(state.restart_times),
                duration_degraded_s=None,
            )
            state.last_known_state = "restarting"
            await self._restart_service(spec)
            return

        # -- DEGRADED ---------------------------------------------------------
        if is_laggy:
            if not state.degraded_since:
                state.degraded_since = datetime.now(UTC)
            state.degraded_check_count += 1
            if state.degraded_check_count >= 2:
                await self._emit_health_event(
                    service=spec.unit, event_type="degraded",
                    previous_state=state.last_known_state,
                    reason=f"lag={lag_messages}>{spec.lag_threshold_messages}",
                    lag_messages=lag_messages, restart_count=len(state.restart_times),
                    duration_degraded_s=None,
                )
                state.last_known_state = "degraded"
            return

        # -- RECOVERED --------------------------------------------------------
        if state.last_known_state in ("degraded", "restarting"):
            duration = (
                (datetime.now(UTC) - state.degraded_since).total_seconds()
                if state.degraded_since else None
            )
            await self._emit_health_event(
                service=spec.unit, event_type="recovered",
                previous_state=state.last_known_state,
                reason=None,
                lag_messages=lag_messages, restart_count=len(state.restart_times),
                duration_degraded_s=duration,
            )

        state.degraded_since = None
        state.degraded_check_count = 0
        state.last_known_state = "healthy"

    # -- systemd interface ----------------------------------------------------

    async def _check_systemd_state(self, unit: str) -> tuple[str, str]:
        """Query systemd unit state via subprocess list args (no shell injection)."""
        proc = await asyncio.create_subprocess_exec(
            "systemctl", "show", unit,
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
            ["systemctl", "start",        spec.unit],
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
                    args=cmd_args, stderr=stderr.decode().strip(),
                )

    # -- Prometheus interface -------------------------------------------------

    async def _fetch_prometheus_health(self) -> set[str]:
        results = await self._query_prometheus("indicagent_service_health > 0")
        return {r["metric"].get("service", "") for r in results}

    async def _fetch_prometheus_lag(self) -> dict[str, int]:
        results = await self._query_prometheus("persistence_consumer_lag")
        out: dict[str, int] = {}
        for r in results:
            unit = _agent_id_to_unit(r["metric"].get("agent_id", ""))
            if unit:
                out[unit] = int(float(r["value"][1]))
        return out

    async def _query_prometheus(self, query: str) -> list[dict]:
        async with aiohttp.ClientSession() as session:
            async with session.get(
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
            service=service, event_type=event_type, reason=reason,
        )
        async with self._db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO service_health_events
                  (ts, service, event_type, previous_state, reason,
                   lag_messages, restart_count, duration_degraded_s)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                now, service, event_type, previous_state, reason,
                lag_messages, restart_count, duration_degraded_s,
            )
        await self._kafka_producer.publish(
            topic_health_events(self._env_name),
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
            service=payload.get("service"), error=str(error),
        )
        await self._kafka_producer.publish(
            topic_health_events_dlq(self._env_name),
            payload,
            payload.get("service", "unknown"),
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import asyncio
    from src.core.service_utils import setup_service_logging
    setup_service_logging("logs/service_auditor_agent.log")
    asyncio.run(ServiceAuditorAgent().start())
