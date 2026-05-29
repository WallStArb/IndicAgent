"""Remediation strategy registry for the self-healing engine.

All rate limiting and idempotency tracking is delegated to RemediationLedger
(durable DB-backed queries). No in-memory state is maintained here.
"""

from dataclasses import dataclass

import structlog


@dataclass
class RemediationStrategy:
    action: str
    state_variable: str
    threshold: float
    max_per_hour: int
    timeout_seconds: int
    enabled: bool = False  # OFF by default per CONTEXT.md locked decision


REMEDIATION_STRATEGIES: dict[str, RemediationStrategy] = {
    "disk_usage_high": RemediationStrategy(
        action="delete_old_logs",
        state_variable="disk_usage",
        threshold=80.0,
        max_per_hour=3,
        timeout_seconds=30,
        enabled=False,
    ),
    "consumer_lag_high": RemediationStrategy(
        action="restart_consumer",
        state_variable="consumer_lag",
        threshold=1000.0,
        max_per_hour=2,
        timeout_seconds=60,
        enabled=False,
    ),
    # Fully implemented in Phase 109: graceful drain + pool.close() + create_pool() +
    # SELECT 1 verify + rollback-on-failure. Rate-limited to 5/hour by the engine via
    # remediation_ledger. Enabled by default so the strategy is live; the global "OFF by
    # default" guard for Phase 109 is the alert-level config (alerts are off until
    # operator enables them), not the strategy registry itself.
    "db_pool_exhausted": RemediationStrategy(
        action="flush_connection_pool",
        state_variable="db_pool_usage",
        threshold=90.0,
        max_per_hour=5,
        timeout_seconds=30,
        enabled=True,
    ),
}

# Set of action names that have a real implementation in engine._execute_action.
IMPLEMENTED_ACTIONS: frozenset[str] = frozenset(
    {
        "delete_old_logs",
        "restart_consumer",
        "flush_connection_pool",
    }
)

# Maps state_variable strings (from Alertmanager webhook payloads) to strategy keys.
_STATE_VARIABLE_TO_STRATEGY: dict[str, str] = {
    "disk_usage": "disk_usage_high",
    "consumer_lag": "consumer_lag_high",
    "db_pool_usage": "db_pool_exhausted",
}


def state_variable_to_strategy_key(state_variable: str) -> str | None:
    """Return the strategy key for a given state_variable, or None if not mapped."""
    return _STATE_VARIABLE_TO_STRATEGY.get(state_variable)


def disable_strategy(strategy_key: str, reason: str = "low_success_rate") -> None:
    """Disable a strategy in-place. Called by the engine when success rate < 80%."""
    if strategy_key in REMEDIATION_STRATEGIES:
        REMEDIATION_STRATEGIES[strategy_key].enabled = False
        structlog.get_logger().warning(
            "strategy_auto_disabled", strategy=strategy_key, reason=reason
        )
