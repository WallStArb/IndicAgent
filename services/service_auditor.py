"""ServiceAuditor — pipeline health monitor and self-healer.

Hybrid three-layer design:
  systemd  -> process liveness (WatchdogSec kills hung processes)
  Prometheus -> metrics/lag (15s check cycle via /api/v1/query)
  This agent -> graduated response, DAG-ordered restarts, audit trail

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
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import _path_bootstrap  # noqa: F401 -- project root on sys.path
import aiohttp
import asyncpg

from src.config.settings import get_active_contracts, get_settings
from src.core.agent.base import BaseDaemon
from src.core.database_manager import create_pool as create_db_pool
from src.core.kafka_utils import KafkaProducerClient
from src.core.models import SESSION_REGISTRY
from src.core.stream_keys import (
    topic_alert_requests,
    topic_health_events,
    topic_health_events_dlq,
)
from src.observability.metrics import (
    CONSUMER_STALL_DETECTED_TOTAL,
    SERVICE_AUDITOR_SERVICE_RESTARTS_TOTAL,
    SERVICE_UP_GAUGE,
)

# Constants
_ESCALATION_WINDOW = timedelta(minutes=10)
_ESCALATION_THRESHOLD = 3
_PROMETHEUS_URL = "http://localhost:9090/api/v1/query"
_SVC_DATA_PROVIDER = "indicagent-ibkr-provider"
_STALL_THRESHOLD_SECONDS = 120  # lowered from 360 per Phase 108 D-23 (verified against observed message cadence pre-deploy)


# ---------------------------------------------------------------------------
# DAG topology: unit name -> restart priority (lower = restart first)
# Changes rarely -- much smaller than the old ServiceSpec registry.
_DAG_ORDER: dict[str, int] = {
    # Priority 0 — infrastructure sentinels: must exist before any consumer starts
    "indicagent-redpanda-ready": 0,  # infra tier: Redpanda readiness sentinel
    "indicagent-redpanda-watchdog": 0,  # infra tier: Redpanda liveness watchdog
    "indicagent-timescaledb-ready": 0,  # infra tier: TimescaleDB readiness sentinel
    # Layer 1 — data ingestion
    "indicagent-ibkr-provider": 1,  # priority 1: root data source; nothing upstream
    "indicagent-bar-replay": 1,  # priority 1: alternate data source; parallel with ibkr-provider
    "indicagent-provider-merger": 2,  # priority 2: downstream of ibkr-provider (1)
    # Layer 2 — bar processing
    "indicagent-bar-aggregator": 3,  # priority 3: downstream of provider-merger (2)
    "indicagent-bar-auditor": 3,  # priority 3: parallel with bar-aggregator (3)
    "indicagent-bar-writer": 4,  # priority 4: downstream of bar-aggregator (3)
    # Layer 3 — intelligence pipeline (I1-I7)
    "indicagent-cross-asset": 5,  # priority 5: cross-asset context; intelligence-pipeline depends on its topic output
    "indicagent-macro-compute": 5,  # priority 5: parallel with cross-asset (5)
    "indicagent-intelligence-pipeline": 6,  # priority 6: downstream of cross-asset (5) and bar-aggregator (4); upstream of feature/signal writers (7+)
    # Layer 4 — persistence writers (parallel, all consume pipeline output)
    "indicagent-feature-writer": 7,  # priority 7: downstream of intelligence-pipeline (6)
    "indicagent-signal-tracker-compute": 7,  # priority 7: downstream of intelligence-pipeline (6)
    "indicagent-signal-writer": 7,  # priority 7: downstream of intelligence-pipeline (6)
    "indicagent-lifecycle-writer": 7,  # priority 7: downstream of intelligence-pipeline (6)
    "indicagent-lineage-writer": 7,  # priority 7: downstream of intelligence-pipeline (6)
    "indicagent-ctx-writer": 7,  # priority 7: downstream of intelligence-pipeline (6)
    # Layer 5 — AI/LLM layer (consumes intelligence journal / i7 signals)
    "indicagent-alpha-swarm": 8,  # priority 8: downstream of signal-writer (7)
    "indicagent-narrative-compute": 8,  # priority 8: downstream of intelligence-pipeline (6)
    "indicagent-llm-writer": 8,  # priority 8: downstream of alpha-swarm / narrative-compute (8)
    "indicagent-swarm-ledger-writer": 8,  # priority 8: downstream of alpha-swarm (8)
    # Layer 6 — analytics and rolling metrics (consume ledger / lifecycle events)
    "indicagent-signal-metrics-compute": 8,  # priority 8: downstream of signal-writer (7)
    "indicagent-signal-metrics-writer": 8,  # priority 8: downstream of signal-metrics-compute (8)
    "indicagent-graduation-compute": 8,  # priority 8: downstream of signal-ledger writes (7)
    "indicagent-graduation-writer": 8,  # priority 8: downstream of graduation-compute (8)
    "indicagent-ml-training": 8,  # oneshot timer service; no lag threshold needed
    "indicagent-ml-signal-training-materialize": 8,  # oneshot timer service; no lag threshold needed
    "indicagent-memory-batch": 8,  # oneshot: nightly 21:00 memory backfill + calibration promotion
    # Timer-triggered oneshot analytics (inactive between runs is correct — not failures)
    "indicagent-weight-updater": 8,  # oneshot: timer-triggered, not a daemon
    "indicagent-shadow-auditor": 8,  # oneshot: timer-triggered, not a daemon
    "indicagent-shadow-validator": 8,  # oneshot: weekly Mon 07:00 UTC, promotion-only
    "indicagent-feature-parity-auditor": 8,  # oneshot: timer-triggered, not a daemon
    "indicagent-confidence-calibration-monitor": 8,  # oneshot: timer-triggered, not a daemon
    "indicagent-signal-probe-auditor": 8,  # oneshot: timer-triggered, not a daemon
    "indicagent-ml-orchestrator": 8,  # oneshot: timer-triggered, not a daemon
    "indicagent-ml-data-quality": 8,  # oneshot: timer-triggered, not a daemon
    "indicagent-ml-discovery": 8,  # oneshot: timer-triggered, not a daemon
    "indicagent-feature-validation": 8,  # oneshot: timer-triggered daily, not a daemon
    "indicagent-hmm-training": 8,  # oneshot: timer-triggered monthly, not a daemon
    # Phase 138 IC pipeline oneshots (inactive between IC pipeline runs is correct)
    "indicagent-regime-writer": 8,  # oneshot; populates feature_vectors.regime
    "indicagent-forward-return-writer": 8,  # oneshot; LEAD() forward returns -> forward_returns
    "indicagent-ic-engine": 8,  # oneshot; Spearman IC -> feature_ic_scores
    # Layer 7 — audit, parity, alerting (observe everything, act on anomalies)
    "indicagent-signal-auditor": 9,  # priority 9: observes signals written by layer 7 writers
    "indicagent-signal-replay": 9,  # priority 9: observes signal-ledger state
    "indicagent-alerting-agent": 9,  # priority 9: depends on all above for alert sources
    "indicagent-dlq-drain": 9,  # priority 9: writes DLQ topics from all above layers to dlq_events
    # Phase 109 services (config foundation + self-healing engine).
    # Lag thresholds for these units, when needed, will be seeded into config_state
    # under alert.lag.* keys by Plan 05 Task 3.
    "indicagent-config-service": 9,  # priority 9: OPS config HTTP API (port 9001)
    "indicagent-outbox-dispatcher": 9,  # priority 9: transactional outbox -> Kafka publisher
    "indicagent-self-healing-agent": 9,  # priority 9: Alertmanager webhook + remediation engine
    # Layer 8 — top-level services (API, dashboard — always-on, no DAG dependency)
    "indicagent-api": 10,  # priority 10: always-on top-level; no upstream ordering constraint
    "indicagent-dashboard": 10,  # priority 10: always-on top-level; no upstream ordering constraint
    # Layer 9 — meta: monitors and restarts all of the above
    "indicagent-service-auditor": 11,  # priority 11: meta-monitor; must be uniquely highest so it never shares a restart wave with the services it monitors
}

# Lag thresholds are loaded from config_state (alert.lag.* keys) via
# ServiceAuditor._load_lag_thresholds() at startup and hot-reloaded via
# _on_config_message_received when alert.lag.* Kafka updates arrive.
# The original 21 entries were seeded into config_schema and config_state
# by production/migrations/109_config_foundation.sql (Phase 109 Plan 05 Task 3).

# Maps persistence_consumer_lag agent_id label -> systemd unit name.
# Keys MUST match the auto-derived agent_id from BaseDaemon._to_snake_case(ClassName)
# because that becomes the agent_id label on PERSISTENCE_CONSUMER_LAG in base.py.
_AGENT_ID_TO_UNIT: dict[str, str] = {
    "bar_writer": "indicagent-bar-writer",
    "bar_aggregator": "indicagent-bar-aggregator",
    "intelligence_pipeline": "indicagent-intelligence-pipeline",
    "feature_vector_writer": "indicagent-feature-writer",
    "signal_tracker": "indicagent-signal-tracker-compute",
    "signal_writer": "indicagent-signal-writer",
    "llm_writer": "indicagent-llm-writer",
    "cross_asset_analyzer": "indicagent-cross-asset",
    "bar_auditor": "indicagent-bar-auditor",
    "provider_merger": "indicagent-provider-merger",
    "lifecycle_writer": "indicagent-lifecycle-writer",
    "lineage_writer": "indicagent-lineage-writer",
    "signal_metrics_analyzer": "indicagent-signal-metrics-compute",
    "signal_metrics_writer": "indicagent-signal-metrics-writer",
    "alpha_swarm": "indicagent-alpha-swarm",
    "narrative_swarm": "indicagent-narrative-compute",
    "swarm_ledger_writer": "indicagent-swarm-ledger-writer",
    "macro_analyzer": "indicagent-macro-compute",
    "signal_auditor": "indicagent-signal-auditor",
    "graduation_analyzer": "indicagent-graduation-compute",
    "graduation_writer": "indicagent-graduation-writer",
    "context_writer": "indicagent-ctx-writer",
    "bar_replay_provider": "indicagent-bar-replay",
    "signal_replay_auditor": "indicagent-signal-replay",
    "dlq_writer": "indicagent-dlq-drain",
    # Phase 109 services (config foundation + self-healing engine).
    # Lag thresholds for these units, when needed, will be seeded into config_state
    # under alert.lag.* keys by Plan 05 Task 3.
    "config_service": "indicagent-config-service",
    "outbox_dispatcher_agent": "indicagent-outbox-dispatcher",
    "self_healer": "indicagent-self-healing-agent",
}

# Timer-triggered oneshot services — ML batch services inactive (dead) between runs is correct
# behavior per CLAUDE.md; do not restart them on the auditor's schedule. Systemd timers control
# their execution.
_ONESHOT_UNITS: frozenset[str] = frozenset(
    {
        "indicagent-redpanda-ready",  # Type=oneshot, RemainAfterExit=yes; infra sentinel, inactive between boots is correct
        "indicagent-redpanda-watchdog",  # Type=oneshot timer; inactive between 2-min runs is correct
        "indicagent-timescaledb-ready",  # Type=oneshot, RemainAfterExit=yes; infra sentinel, inactive between boots is correct
        "indicagent-weight-updater",
        "indicagent-shadow-auditor",
        "indicagent-shadow-validator",  # weekly Mon 07:00 UTC, 5-gate promotion check
        "indicagent-signal-probe-auditor",
        "indicagent-ml-orchestrator",
        "indicagent-ml-data-quality",
        "indicagent-ml-discovery",
        "indicagent-ml-training",
        "indicagent-ml-signal-training-materialize",
        "indicagent-roll-batch",
        "indicagent-memory-batch",  # Type=oneshot, timer-triggered nightly 21:00; D-06 jobs: memory-epoch/memory-regime/memory-backfill/memory-promote
        "indicagent-feature-validation",  # Type=oneshot, timer-triggered daily
        "indicagent-hmm-training",  # Type=oneshot, timer-triggered monthly
        "indicagent-feature-parity-auditor",  # Type=oneshot, timer-triggered
        "indicagent-confidence-calibration-monitor",  # Type=oneshot, timer-triggered
        # Phase 138 IC pipeline oneshots — inactive between IC pipeline runs is correct
        "indicagent-regime-writer",  # Type=oneshot; inactive between IC pipeline runs is correct
        "indicagent-forward-return-writer",  # Type=oneshot; inactive between IC pipeline runs is correct
        "indicagent-ic-engine",  # Type=oneshot; inactive between IC pipeline runs is correct
    }
)


# ---------------------------------------------------------------------------
# Per-service runtime state
# ---------------------------------------------------------------------------


@dataclass
class ServiceState:
    """Per-service runtime state for graduated response tracking."""

    degraded_since: datetime | None = None
    degraded_check_count: int = 0
    restart_times: list[datetime] = field(default_factory=list)
    escalated: bool = False
    last_known_state: str = "healthy"


# ---------------------------------------------------------------------------
# Pure helpers (no I/O -- easily unit-testable)
# ---------------------------------------------------------------------------


def _parse_systemctl_show(output: str) -> tuple[str, str]:
    """Parse systemctl show output into (ActiveState, SubState) tuple.

    Args:
        output: Raw stdout from systemctl show --property=ActiveState,SubState

    Returns:
        Tuple of (active_state, sub_state) with "unknown" as fallback.
    """
    props: dict[str, str] = {}
    for line in output.strip().splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            props[k.strip()] = v.strip()
    return props.get("ActiveState", "unknown"), props.get("SubState", "unknown")


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class ServiceAuditor(BaseDaemon):
    """Monitors all pipeline services, self-heals, and audits every event.

    Hybrid three-layer design:
    - systemd for process liveness (WatchdogSec kills hung processes)
    - Prometheus for metrics/lag (15s check cycle)
    - This agent for graduated response, DAG-ordered restarts, and audit trail

    Every state transition is persisted to service_health_events and published
    to system.health.events -- both are permanent audit trails.
    """

    def __init__(self) -> None:
        _settings = get_settings()
        super().__init__(
            name="service_auditor_agent",
            max_idle_seconds=600,
            settings=_settings,
        )
        self._db_pool: asyncpg.Pool | None = None
        self._http_session: aiohttp.ClientSession | None = None
        self._kafka_producer: KafkaProducerClient | None = None
        # Populated dynamically via _discover_services() at runtime
        self._service_states: dict[str, ServiceState] = {}
        self._topics_produced = [
            topic_health_events(self.env_name),
            topic_health_events_dlq(self.env_name),
        ]
        self._prometheus_check_interval = 15
        self._systemd_check_interval = 30
        self._heartbeat_interval = 60
        # Phase 109 Plan 05 Task 3: lag thresholds loaded from config DB at startup,
        # hot-reloaded via _on_config_message_received on alert.lag.* Kafka updates.
        # _config_prefixes restricts mixin reload to alert.lag.* keys only (avoids storm).
        self._config_prefixes = ("alert.lag.",)
        self._lag_thresholds: dict[str, int] = {}

    @property
    def topics_produced(self) -> list[str]:
        return self._topics_produced

    async def _setup(self) -> None:
        self._db_pool = await create_db_pool(
            self.settings.database_url, pool_name="service_auditor", min_size=1, max_size=3
        )
        self._http_session = aiohttp.ClientSession()
        self._kafka_producer = KafkaProducerClient(
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
        )
        await self._kafka_producer.start()
        # Wire _producer for BaseDaemon._send_alert() to use
        self._producer = self._kafka_producer
        # Phase 109 Plan 05 Task 3: load lag thresholds from config cache (populated
        # by _pre_setup_config_load before _setup is called).
        await self._load_lag_thresholds()
        self.logger.info(
            "service_auditor.setup_complete",
            env=self.env_name,
            lag_threshold_count=len(self._lag_thresholds),
        )

    async def _load_lag_thresholds(self) -> None:
        """Load lag thresholds from config_state (alert.lag.* keys). NON-FATAL.

        Called at _setup() time (after _pre_setup_config_load populates _config_cache)
        and on hot-reload via _on_config_message_received when alert.lag.* Kafka
        updates arrive.

        Key format in config_state: 'alert.lag.<unit-name-kebab>'
        (e.g., 'alert.lag.feature-writer' -> 'indicagent-feature-writer': int).
        """
        try:
            result: dict[str, int] = {}
            for key, value in self._config_cache.items():
                if not key.startswith("alert.lag."):
                    continue
                unit_suffix = key[len("alert.lag.") :]
                full_unit = f"indicagent-{unit_suffix}"
                try:
                    result[full_unit] = int(value)
                except (TypeError, ValueError):
                    continue
            self._lag_thresholds = result
        except Exception as error:
            self.logger.warning("lag_thresholds.load_failed", error=str(error))

    async def _on_config_message_received(self, key: str, value: object) -> None:
        """Hot-reload lag thresholds when alert.lag.* config keys change.

        Plan 03 mixin already updated self._config_cache before invoking this hook.
        ServiceAuditor only needs to refresh its derived view of alert.lag.* keys.
        """
        if key.startswith("alert.lag."):
            await self._load_lag_thresholds()

    async def _teardown(self) -> None:
        if self._kafka_producer:
            await self._kafka_producer.stop()
        if self._http_session:
            await self._http_session.close()
        if self._db_pool:
            await self._db_pool.close()

    async def _run(self) -> None:
        # lag_task created by BaseDaemon.start() at line 155
        prom_task = asyncio.create_task(self._prometheus_check_loop())
        sysd_task = asyncio.create_task(self._systemd_check_loop())
        hb_task = asyncio.create_task(self._heartbeat_loop())
        await self._stop_event.wait()
        for t in (prom_task, sysd_task, hb_task):
            t.cancel()
        for t in (prom_task, sysd_task, hb_task):
            try:
                await t
            except asyncio.CancelledError:
                pass

    # -- Dynamic discovery ----------------------------------------------------

    async def _discover_services(self) -> list[str]:
        """Discover all indicagent systemd units dynamically via systemctl list-units."""
        proc = await asyncio.create_subprocess_exec(
            "systemctl",
            "list-units",
            "--all",
            "--no-legend",
            "--no-pager",
            "indicagent-*",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        units = []
        for line in stdout.decode().strip().splitlines():
            parts = line.split()
            if not parts:
                continue
            # Strip leading bullet character (● for failed units in systemctl output)
            unit_raw = parts[0].lstrip("●").strip()
            if not unit_raw:
                # Bullet was the only token; actual unit name is next token
                unit_raw = parts[1] if len(parts) > 1 else ""
            unit = unit_raw.removesuffix(".service")
            if unit:
                units.append(unit)
        return sorted(units, key=lambda u: _DAG_ORDER.get(u, 99))

    # -- Check loops ----------------------------------------------------------

    async def _check_feature_pipeline_freshness(self) -> None:
        """SQL-based freshness check replacing parity_auditor (Phase 104).

        Queries check_feature_pipeline_freshness() and publishes alerts for
        any (symbol, tf) with gaps exceeding the threshold.
        """
        if not self._db_pool:
            return
        try:
            async with self._db_pool.acquire() as conn:
                stale = await conn.fetch("SELECT * FROM check_feature_pipeline_freshness()")
            for row in stale:
                self.logger.warning(
                    "service_auditor.feature_stale",
                    symbol=row["symbol"],
                    tf=row["tf"],
                    gap_minutes=round(row["gap_minutes"], 1),
                )
                await self._kafka_producer.publish(
                    topic_alert_requests(self.env_name),
                    {
                        "alert_type": "feature_pipeline_stale",
                        "symbol": row["symbol"],
                        "tf": row["tf"],
                        "gap_minutes": round(row["gap_minutes"], 1),
                    },
                    row["symbol"],
                )
        except Exception as error:
            self.logger.error("service_auditor.freshness_check_failed", error=str(error))

    async def _prometheus_check_loop(self) -> None:
        while self.running:
            await asyncio.sleep(self._prometheus_check_interval)
            try:
                health_set, lag_map, data_flow = await asyncio.gather(
                    self._fetch_prometheus_health(),
                    self._fetch_prometheus_lag(),
                    self._fetch_provider_data_flow(),
                )
                units = await self._discover_services()
                for unit in units:
                    if unit not in self._service_states:
                        self._service_states[unit] = ServiceState()
                    has_metrics = unit in health_set
                    lag = lag_map.get(unit, 0)
                    active = "active" if has_metrics else "unknown"
                    sub = "running" if has_metrics else "no_metrics"
                    bars_per_sec = data_flow.get(unit, 0.0)
                    lag_threshold = self._lag_thresholds.get(unit, 0)
                    await self._evaluate_service_dynamic(
                        unit, active, sub, lag, lag_threshold, has_metrics, bars_per_sec
                    )
                    SERVICE_UP_GAUGE.add(1 if has_metrics else 0, {"unit": unit})

                # Stall detection: restart agents that have stopped processing messages
                # but whose systemd unit is still reported as active (in-process watchdog
                # may be disabled or itself stuck).
                stalled_units = await self._fetch_stalled_agents()
                for unit in stalled_units:
                    if unit in _ONESHOT_UNITS:
                        continue  # timer-triggered; systemd timer handles restart
                    self.logger.warning(
                        "service_auditor.stall_detected",
                        unit=unit,
                        threshold_seconds=_STALL_THRESHOLD_SECONDS,
                    )
                    CONSUMER_STALL_DETECTED_TOTAL.add(1, {"unit": unit})
                    await self._restart_service_by_unit(unit)

                # Feature pipeline freshness (replaces parity_auditor)
                await self._check_feature_pipeline_freshness()
            except Exception as error:
                self.logger.error("service_auditor.prometheus_check_failed", error=str(error))

    async def _systemd_check_loop(self) -> None:
        while self.running:
            await asyncio.sleep(self._systemd_check_interval)
            try:
                units = await self._discover_services()
                for unit in units:
                    if unit not in self._service_states:
                        self._service_states[unit] = ServiceState()
                    active, sub = await self._check_systemd_state(unit)
                    if active in ("failed", "inactive") or sub == "start-limit-hit":
                        lag_threshold = self._lag_thresholds.get(unit, 0)
                        await self._evaluate_service_dynamic(
                            unit, active, sub, 0, lag_threshold, False
                        )
            except Exception as error:
                self.logger.error("service_auditor.systemd_check_failed", error=str(error))

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
            except Exception as error:
                self.logger.error("service_auditor.heartbeat_failed", error=str(error))

    # -- Graduated response ---------------------------------------------------

    async def _evaluate_service_dynamic(
        self,
        unit: str,
        active_state: str,
        sub_state: str,
        lag_messages: int,
        lag_threshold: int,
        has_metrics: bool,
        bars_per_sec: float = 0.0,
    ) -> None:
        # ML batch services inactive (dead) between runs is correct — do not restart.
        # Timer-triggered oneshots must only be started by systemd timers, not the auditor.
        if unit in _ONESHOT_UNITS:
            return

        state = self._service_states[unit]
        if state.escalated:
            return

        now = datetime.now(UTC)
        is_dead = active_state in ("failed", "inactive") or sub_state == "start-limit-hit"
        is_laggy = lag_threshold > 0 and lag_messages > lag_threshold

        # -- DATA STOPPAGE DETECTION (IBKR provider only) --------------------
        # Only meaningful when at least one active instrument's session is open;
        # outside market hours bars_per_sec=0 is expected and must not trigger
        # restart-thrashing.
        if (
            unit == _SVC_DATA_PROVIDER
            and bars_per_sec == 0.0
            and has_metrics
            and self._any_active_session_open(now)
        ):
            if not state.degraded_since:
                state.degraded_since = now
            state.degraded_check_count += 1
            if state.degraded_check_count >= 2:  # 2 checks = 30 seconds
                await self._emit_health_event(
                    service=unit,
                    event_type="data_stoppage",
                    previous_state=state.last_known_state,
                    reason="bars/sec=0 for >30s during active session",
                    lag_messages=None,
                    restart_count=len(state.restart_times),
                    duration_degraded_s=None,
                )
                await self._send_alert(
                    "HIGH",
                    f"Provider data stoppage: {unit}",
                    {"reason": "bars_per_sec=0 for 30s during active session"},
                )
                state.last_known_state = "restarting"
                await self._restart_service_by_unit(unit)
                return
            # Preserve the counter across iterations -- skip the healthy-reset
            # tail below. Without this return, lines at the bottom of the
            # function zero degraded_check_count every cycle and the
            # >=2 gate is never reached.
            return
        # ------------------------------------------------------------------

        # -- RESTART ----------------------------------------------------------
        if is_dead:
            state.restart_times = [t for t in state.restart_times if now - t < _ESCALATION_WINDOW]

            if len(state.restart_times) >= _ESCALATION_THRESHOLD:
                state.escalated = True
                duration = (
                    (now - state.degraded_since).total_seconds() if state.degraded_since else None
                )
                await self._emit_health_event(
                    service=unit,
                    event_type="escalated",
                    previous_state=state.last_known_state,
                    reason=f"{active_state}/{sub_state}",
                    lag_messages=None,
                    restart_count=len(state.restart_times),
                    duration_degraded_s=duration,
                )
                await self._send_to_dlq(
                    {"service": unit, "restart_count": len(state.restart_times)},
                    Exception("escalation threshold reached"),
                )
                await self._send_alert(
                    "CRITICAL",
                    f"Service escalated: {unit} -- {len(state.restart_times)} restarts in 10 min",  # noqa: E501
                    {"restart_count": len(state.restart_times)},
                )
                self.logger.error("service_auditor.escalated", service=unit)
                return

            if not state.degraded_since:
                state.degraded_since = now
            state.restart_times.append(now)
            await self._emit_health_event(
                service=unit,
                event_type="restart",
                previous_state=state.last_known_state,
                reason=f"{active_state}/{sub_state}",
                lag_messages=None,
                restart_count=len(state.restart_times),
                duration_degraded_s=None,
            )
            state.last_known_state = "restarting"
            await self._restart_service_by_unit(unit)
            return

        # -- DEGRADED ---------------------------------------------------------
        if is_laggy:
            if not state.degraded_since:
                state.degraded_since = now
            state.degraded_check_count += 1
            if state.degraded_check_count >= 2:
                await self._emit_health_event(
                    service=unit,
                    event_type="degraded",
                    previous_state=state.last_known_state,
                    reason=f"lag={lag_messages}>{lag_threshold}",
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
                service=unit,
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

    async def _restart_service_by_unit(self, unit: str) -> None:
        """reset-failed clears StartLimitBurst; start re-launches the unit."""
        self.logger.warning("service_auditor.restarting", service=unit)
        for cmd_args in (
            ["systemctl", "reset-failed", unit],
            ["systemctl", "start", unit],
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
        # Increment metric after restart attempt
        SERVICE_AUDITOR_SERVICE_RESTARTS_TOTAL.add(1, {"service_name": unit})

    # -- Prometheus interface -------------------------------------------------

    async def _fetch_prometheus_health(self) -> set[str]:
        """Fetch set of healthy unit names from Prometheus up{} metric.

        With the collapsed Prometheus config (single OTel Collector scrape),
        per-service up{} metrics are no longer scraped directly. This method
        returns an empty set as a safe degraded fallback -- the systemd check
        loop provides the primary health signal post-OTel migration.
        """
        try:
            results = await self._query_prometheus('up{job=~"indicagent.*"}')
            healthy: set[str] = set()
            for r in results:
                if r["value"][1] == "1":
                    job = r["metric"].get("job", "")
                    # Match job name directly to unit (job names are unit names in OTel scrape)
                    if job in _DAG_ORDER:
                        healthy.add(job)
            return healthy
        except Exception:
            return set()

    async def _fetch_prometheus_lag(self) -> dict[str, int]:
        results = await self._query_prometheus("persistence_consumer_lag")
        out: dict[str, int] = {}
        for r in results:
            unit = _AGENT_ID_TO_UNIT.get(r["metric"].get("agent_id", ""))
            if unit:
                out[unit] = int(float(r["value"][1]))
        return out

    async def _fetch_stalled_agents(self) -> list[str]:
        """Return systemd unit names for agents whose last-message timestamp is stale.

        Queries the agent_last_message_timestamp_seconds gauge (set by BaseDaemon
        ._record_message_consumed). An agent is stalled when:
          now - last_ts > _STALL_THRESHOLD_SECONDS (360s)
        AND the metric series exists (ts > 0 -- cold-start false-positive guard).

        The 60s grace above the in-process _stall_watchdog (300s) prevents racing:
        the watchdog exits via sys.exit(1) at 300s so systemd restarts the process;
        this detector fires at 360s only for cases where the in-process watchdog
        has been disabled or has itself stalled.

        Label key is "agent_id" -- matches BaseDaemon._last_msg_ts_attrs = {"agent_id": name}.
        """
        try:
            results = await self._query_prometheus("agent_last_message_timestamp_seconds")
        except Exception as error:
            self.logger.warning("service_auditor.stall_fetch_failed", error=str(error))
            return []

        now = time.time()
        stalled: list[str] = []
        seen: set[str] = set()
        for r in results:
            agent_name = r["metric"].get("agent_id", "")
            if not agent_name:
                continue
            unit = _AGENT_ID_TO_UNIT.get(agent_name)
            if unit is None or unit in seen:
                continue
            ts = float(r["value"][1])
            # Cold-start guard: ts == 0 means the metric was never set (no messages yet).
            # Skip to avoid false positives on freshly-started agents.
            if ts <= 0:
                continue
            if now - ts > _STALL_THRESHOLD_SECONDS:
                stalled.append(unit)
                seen.add(unit)
        return stalled

    def _any_active_session_open(self, now: datetime) -> bool:
        """True if any active instrument's trading session is open at `now`.

        Gates data-stoppage detection so overnight/weekend/holiday quiet
        periods do not trigger restart-thrashing. Fails open (returns True)
        on settings lookup error so genuine stoppages still surface.
        """
        try:
            instruments = get_active_contracts(self.settings)
        except Exception as error:
            self.logger.warning(
                "service_auditor.session_lookup_failed",
                error=str(error),
            )
            return True
        for inst in instruments:
            session = SESSION_REGISTRY.get(inst.session_id)
            if session is not None and session.is_open(now):
                return True
        return False

    async def _fetch_provider_data_flow(self) -> dict[str, float]:
        """Check provider bars/second rate to detect data stoppage."""
        # Query rate of bars produced over last 5 minutes
        results = await self._query_prometheus("rate(provider_bars_produced_total[5m])")
        out: dict[str, float] = {}
        for r in results:
            provider = r["metric"].get("provider", "")
            if provider == "ibkr":
                out[_SVC_DATA_PROVIDER] = float(r["value"][1])
                break
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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import asyncio

    asyncio.run(ServiceAuditor().start())
