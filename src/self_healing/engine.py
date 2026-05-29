"""Self-healing engine: Alertmanager webhook integration with remediation strategies.

Design decisions:
- Double webhook auth (HTTP layer in 109-05 + engine layer here) is intentional
  defense-in-depth. The engine may be invoked from non-HTTP paths in future.
- Prometheus URL is read from PROMETHEUS_URL env var; fail-closed on measurement
  failure (no remediation without pre-state measurement).
- Idempotency and rate limiting are ledger-backed (durable across restarts).
- flush_connection_pool is fully implemented via ManagedPool with graceful drain,
  CREATE, SELECT 1 verify, rollback-on-failure, and REMEDIATION_POOL_FLUSH_TOTAL.
"""

import asyncio
import os
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import aiohttp
import structlog
from fastapi import HTTPException

from src.observability.metrics import (
    REMEDIATION_CIRCUIT_BREAKER_OPEN_TOTAL,
    REMEDIATION_MEASURE_FAILED_TOTAL,
    REMEDIATION_POOL_FLUSH_TOTAL,
    WEBHOOK_AUTH_FAILED_TOTAL,
    WEBHOOK_RECEIVED_TOTAL,
    WEBHOOK_VALIDATION_FAILED_TOTAL,
)
from src.self_healing.ledger import RemediationLedger, RemediationRecord
from src.self_healing.pool_manager import ManagedPool
from src.self_healing.strategies import (
    IMPLEMENTED_ACTIONS,
    REMEDIATION_STRATEGIES,
    RemediationStrategy,
    disable_strategy,
    state_variable_to_strategy_key,
)

logger = structlog.get_logger(__name__)


@dataclass
class AlertRequest:
    alert_id: str
    fired_at: datetime
    severity: str
    state_variable: str
    current_value: float
    threshold: float
    labels: dict
    reason: str | None = None


@dataclass
class RemediationResult:
    remediation_id: str
    status: str
    pre_value: float | None
    post_value: float | None
    duration_ms: int
    error: str | None


class SelfHealingEngine:
    """Control-theory-based remediation: sensor → setpoint → error → actuator → feedback."""

    def __init__(self, managed_pool: ManagedPool) -> None:
        self._managed_pool = managed_pool
        self._ledger = RemediationLedger(managed_pool.pool)
        self._http_session: aiohttp.ClientSession | None = None
        # Engine-layer auth (defense-in-depth alongside HTTP-layer auth in 109-05)
        self._webhook_secret = os.getenv("CONFIG_WEBHOOK_SHARED_SECRET")
        # PROMETHEUS_URL from env (not hardcoded); fail-closed on measurement failure
        self._prometheus_url = os.getenv("PROMETHEUS_URL", "http://localhost:9090").rstrip("/")
        self._service_auditor_restart_url = os.getenv(
            "SERVICE_AUDITOR_RESTART_URL", "http://localhost:12224/restart"
        )
        self._mountpoint_allowlist = frozenset({"/var/log", "/tmp", "/home/bg/dev/indicagent/logs"})
        self._unit_prefix = "indicagent-"

    async def initialize(self) -> None:
        """Create HTTP session for outbound calls (Prometheus, service auditor)."""
        self._http_session = aiohttp.ClientSession()

    async def close(self) -> None:
        """Close HTTP session."""
        if self._http_session:
            await self._http_session.close()

    async def handle_webhook(self, payload: dict[str, Any]) -> RemediationResult:
        """Entry point for Alertmanager webhook payloads.

        Engine-layer auth check (defense-in-depth): validates CONFIG_WEBHOOK_SHARED_SECRET
        when set. HTTP-layer auth in 109-05 is the primary gate; this is secondary.
        """
        # Engine-layer secret validation (defense-in-depth)
        if self._webhook_secret:
            secret = payload.get("webhook_secret") or payload.get("shared_secret")
            if secret != self._webhook_secret:
                WEBHOOK_AUTH_FAILED_TOTAL.add(1, {"layer": "engine", "reason": "invalid_secret"})
                raise HTTPException(status_code=401, detail="Invalid webhook shared secret")

        try:
            fired_at_raw = payload.get("fired_at") or datetime.now(UTC).isoformat()
            alert = AlertRequest(
                alert_id=payload.get("alert_id") or str(uuid.uuid4()),
                fired_at=datetime.fromisoformat(fired_at_raw.replace("Z", "+00:00")),
                severity=payload.get("severity", "WARNING"),
                state_variable=payload.get("state_variable", ""),
                current_value=float(payload.get("current_value", 0)),
                threshold=float(payload.get("threshold", 0)),
                labels=payload.get("labels", {}),
                reason=payload.get("reason"),
            )
        except (ValueError, TypeError) as exc:
            WEBHOOK_VALIDATION_FAILED_TOTAL.add(1, {"reason": "invalid_payload"})
            raise HTTPException(status_code=400, detail=f"Invalid payload: {exc}") from exc

        WEBHOOK_RECEIVED_TOTAL.add(
            1,
            {"severity": alert.severity, "state_variable": alert.state_variable},
        )

        # Durable idempotency: check ledger (not in-memory set; survives restarts)
        if await self._ledger.alert_already_processed(alert.alert_id):
            return RemediationResult(
                remediation_id="",
                status="no_action",
                pre_value=None,
                post_value=None,
                duration_ms=0,
                error="Already processed (durable)",
            )

        return await self.execute_remediation(alert)

    async def execute_remediation(self, alert: AlertRequest) -> RemediationResult:
        """Control loop: measure pre-state → circuit breaker → strategy → action → measure post-state → record."""
        # Fail-closed: no action without a Prometheus measurement
        pre_value = await self._measure_state(alert.state_variable)
        if pre_value is None:
            REMEDIATION_MEASURE_FAILED_TOTAL.add(
                1, {"state_variable": alert.state_variable, "phase": "pre"}
            )
            return RemediationResult(
                remediation_id="",
                status="no_action",
                pre_value=None,
                post_value=None,
                duration_ms=0,
                error="Prometheus measurement unavailable (fail-closed)",
            )

        # No action needed if current value is within threshold
        if pre_value <= alert.threshold:
            return RemediationResult(
                remediation_id="",
                status="no_action",
                pre_value=pre_value,
                post_value=pre_value,
                duration_ms=0,
                error=None,
            )

        # Circuit breaker: pause ALL remediation if >50% of last-5-min attempts failed
        open_, reason = await self._check_circuit_breaker()
        if open_:
            REMEDIATION_CIRCUIT_BREAKER_OPEN_TOTAL.add(1, {"reason": "failure_rate_exceeded"})
            return RemediationResult(
                remediation_id="",
                status="no_action",
                pre_value=pre_value,
                post_value=None,
                duration_ms=0,
                error=reason,
            )

        strategy_key = state_variable_to_strategy_key(alert.state_variable)
        if not strategy_key:
            return RemediationResult(
                remediation_id="",
                status="no_strategy",
                pre_value=pre_value,
                post_value=None,
                duration_ms=0,
                error=f"No strategy for state_variable={alert.state_variable}",
            )

        strategy = REMEDIATION_STRATEGIES.get(strategy_key)
        if not strategy or not strategy.enabled:
            return RemediationResult(
                remediation_id="",
                status="no_strategy",
                pre_value=pre_value,
                post_value=None,
                duration_ms=0,
                error=f"Strategy {strategy_key} not enabled",
            )

        if strategy.action not in IMPLEMENTED_ACTIONS:
            return RemediationResult(
                remediation_id="",
                status="no_strategy",
                pre_value=pre_value,
                post_value=None,
                duration_ms=0,
                error=f"Action {strategy.action} not implemented",
            )

        # Durable rate limit: count via ledger (survives restarts)
        attempts = await self._ledger.attempts_in_last_hour(strategy.action)
        if attempts >= strategy.max_per_hour:
            return RemediationResult(
                remediation_id="",
                status="no_action",
                pre_value=pre_value,
                post_value=None,
                duration_ms=0,
                error=f"Rate limit exceeded ({attempts}/{strategy.max_per_hour})",
            )

        start = time.monotonic()
        remediation_id = str(uuid.uuid4())

        try:
            async with asyncio.timeout(strategy.timeout_seconds):
                await self._execute_action(strategy, alert)

            post_value = await self._measure_state(alert.state_variable)
            duration_ms = int((time.monotonic() - start) * 1000)

            if post_value is None:
                REMEDIATION_MEASURE_FAILED_TOTAL.add(
                    1,
                    {"state_variable": alert.state_variable, "phase": "post"},
                )
                outcome = "partial"
            else:
                outcome = "success" if post_value < alert.threshold else "partial"

            await self._ledger.record(
                RemediationRecord(
                    timestamp=datetime.now(UTC),
                    remediation_id=remediation_id,
                    alert_id=alert.alert_id,
                    state_variable=alert.state_variable,
                    pre_value=pre_value,
                    post_value=post_value,
                    target_value=alert.threshold,
                    action=strategy.action,
                    outcome=outcome,
                    duration_ms=duration_ms,
                    error_message=None,
                    changed_by="self_healing_engine",
                    reason=alert.reason,
                )
            )
            await self._maybe_auto_disable(strategy_key, strategy.action)

            return RemediationResult(
                remediation_id=remediation_id,
                status=outcome,
                pre_value=pre_value,
                post_value=post_value,
                duration_ms=duration_ms,
                error=None,
            )

        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            await self._ledger.record(
                RemediationRecord(
                    timestamp=datetime.now(UTC),
                    remediation_id=remediation_id,
                    alert_id=alert.alert_id,
                    state_variable=alert.state_variable,
                    pre_value=pre_value,
                    post_value=None,
                    target_value=alert.threshold,
                    action=strategy.action,
                    outcome="failed",
                    duration_ms=duration_ms,
                    error_message=str(exc),
                    changed_by="self_healing_engine",
                    reason=alert.reason,
                )
            )
            await self._maybe_auto_disable(strategy_key, strategy.action)

            return RemediationResult(
                remediation_id=remediation_id,
                status="failed",
                pre_value=pre_value,
                post_value=None,
                duration_ms=duration_ms,
                error=str(exc),
            )

    async def _check_circuit_breaker(self) -> tuple[bool, str | None]:
        """Return (open, reason). open=True means STOP - do not run any remediation.

        Queries remediation_ledger for the last 5 minutes across ALL actions. If
        total >= 4 attempts AND (failed / total) > 0.5, the breaker is OPEN.

        Minimum-sample gate (>=4) prevents a single early failure from tripping
        the breaker. Failure definition: outcome IN ('failed', 'partial').
        """
        cutoff = datetime.now(UTC) - timedelta(minutes=5)
        async with self._managed_pool.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT "
                "  COUNT(*) AS total, "
                "  SUM(CASE WHEN outcome IN ('failed','partial') THEN 1 ELSE 0 END) AS failed "
                "FROM remediation_ledger WHERE timestamp >= $1",
                cutoff,
            )
        total = int(row["total"] or 0) if row else 0
        failed = int(row["failed"] or 0) if row else 0

        if total < 4:
            return (False, None)
        if failed / total > 0.5:
            return (
                True,
                f"circuit_breaker_open total={total} failed={failed} ratio={failed/total:.2f}",
            )
        return (False, None)

    async def _maybe_auto_disable(self, strategy_key: str, action: str) -> None:
        """Disable strategy if success rate < 80% with at least 10 samples."""
        rate, count = await self._ledger.get_success_rate(action)
        if count >= 10 and rate < 0.8:
            disable_strategy(strategy_key, reason=f"success_rate={rate:.2f} over {count} attempts")

    async def _measure_state(self, state_variable: str) -> float | None:
        """Query Prometheus for the current value of state_variable.

        Returns None on any failure (FAIL-CLOSED: no remediation without measurement).
        PROMETHEUS_URL is read from env; configurable, not hardcoded.
        """
        if not self._http_session:
            return None
        url = f"{self._prometheus_url}/api/v1/query"
        try:
            async with self._http_session.get(
                url,
                params={"query": state_variable},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status != 200:
                    logger.warning(
                        "prometheus.non_200",
                        status=resp.status,
                        query=state_variable,
                    )
                    return None
                data = await resp.json()
                results = data.get("data", {}).get("result", [])
                if not results:
                    return None
                return float(results[0]["value"][1])
        except (aiohttp.ClientError, TimeoutError, ValueError, KeyError, IndexError) as exc:
            logger.warning(
                "prometheus.query_failed",
                state_variable=state_variable,
                error=str(exc),
                url=self._prometheus_url,
            )
            return None

    async def _execute_action(self, strategy: RemediationStrategy, alert: AlertRequest) -> None:
        """Dispatch to specific action implementation."""
        if strategy.action == "delete_old_logs":
            mountpoint = alert.labels.get("mountpoint", "/var/log")
            if mountpoint not in self._mountpoint_allowlist:
                raise ValueError(
                    f"Mountpoint {mountpoint!r} not in allowlist "
                    f"{sorted(self._mountpoint_allowlist)}"
                )
            await self._delete_old_logs(mountpoint)
        elif strategy.action == "restart_consumer":
            unit = alert.labels.get("service") or ""
            if not unit.startswith(self._unit_prefix):
                raise ValueError(f"Unit name {unit!r} does not start with {self._unit_prefix!r}")
            await self._restart_service(unit)
        elif strategy.action == "flush_connection_pool":
            await self._flush_connection_pool()
        else:
            raise NotImplementedError(f"Action {strategy.action} is not implemented")

    async def _delete_old_logs(self, mountpoint: str) -> None:
        """Delete log files older than 7 days from the specified mountpoint."""
        subprocess.run(
            ["find", mountpoint, "-name", "*.log", "-mtime", "+7", "-delete"],
            check=True,
            capture_output=True,
            timeout=30,
        )

    async def _restart_service(self, unit: str) -> None:
        """Restart a systemd unit via the service auditor restart endpoint."""
        if not self._http_session:
            raise RuntimeError("HTTP session not initialized")
        async with self._http_session.post(
            self._service_auditor_restart_url,
            json={"unit": unit},
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            resp.raise_for_status()

    async def _flush_connection_pool(self) -> None:
        """Graceful flush of the managed DB pool via ManagedPool.flush().

        ManagedPool.flush() implements:
          - Creates a NEW asyncpg pool via create_pool() with same URL/kwargs
          - Verifies the new pool with SELECT 1
          - Rolls back (closes new pool, KEEPS old pool) on health-check failure
          - Atomically swaps self._pool only after verification succeeds
          - Gracefully drains old pool (asyncpg pool.close, terminate() fallback)

        Emits REMEDIATION_POOL_FLUSH_TOTAL{outcome=success|failed} on every attempt.
        Re-raises on failure so execute_remediation records outcome="failed" in ledger.

        IMPORTANT: After a successful flush, self._ledger holds a reference to the
        OLD pool object. Re-bind it to the new pool so subsequent ledger writes succeed.
        """
        try:
            timing = await self._managed_pool.flush()
            logger.info("pool_flush_success", **timing)
            REMEDIATION_POOL_FLUSH_TOTAL.add(1, {"outcome": "success"})
            # Re-bind ledger to the refreshed pool
            self._ledger = RemediationLedger(self._managed_pool.pool)
        except Exception as exc:
            REMEDIATION_POOL_FLUSH_TOTAL.add(1, {"outcome": "failed"})
            logger.critical("pool_flush_failed", error=str(exc))
            raise
