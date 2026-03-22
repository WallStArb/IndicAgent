"""Shared utilities for IndicAgent services.

Centralises boilerplate that is otherwise copy-pasted across all six
service files: logging setup and timeframe bar thresholds.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import structlog

# Fraction of successful plugin executions to record as Prometheus metrics.
# 1-in-10 reduces write pressure on the hot path; errors are always recorded.
#
# Usage pattern (modulo sampling):
#   call_count += 1
#   if call_count % PLUGIN_METRICS_SAMPLE_RATE == 0:
#       record_plugin_execution(...)
#
# This samples 1-in-N successful calls, reducing Prometheus write pressure
# by (1 - 1/N). With rate=10, 90% reduction in write operations.
#
# Rationale:
# - Plugin executions occur on every bar for every symbol/timeframe combination.
# - Prometheus write operations have non-zero overhead on the hot path.
# - 1-in-10 sampling provides 90% reduction with minimal observability loss.
# - Errors are always recorded (no sampling) for safety and full audit coverage.
PLUGIN_METRICS_SAMPLE_RATE: int = 10

# Seed lookback multiplier: bars_needed * tf_seconds * this = time window for DB seed queries.
# 48× gives ~2 days for 1m bars, covering IBKR maintenance gaps and weekend crypto outages.
SEED_LOOKBACK_MULTIPLIER: int = 48

# Minimum unique bars required before publishing per timeframe.
# 1m uses 120 (2 hours) for plugin warm-up quality.
# All higher TFs use 26 — enough for EMA-26 and Stochastic-14.
_MIN_BARS_FOR_TF: dict[str, int] = {
    "1m": 120,
    "5m": 26,
    "15m": 26,
    "1h": 26,
    "4h": 26,
    "1d": 26,
}


def min_bars_for_tf(timeframe: str, default: int = 26) -> int:
    """Return minimum unique bars required before emitting output for a given TF."""
    return _MIN_BARS_FOR_TF.get(timeframe, default)


# Seconds per bar for each configured timeframe.
# Used for cooldown / elapsed-bar calculations across services.
TF_SECONDS: dict[str, int] = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}

# Seconds from period start to period close per timeframe.
# 1m is omitted: for 1m bars ts IS the close time, no offset needed.
# For all higher TFs ts is the period start; close = ts + duration.
TF_DURATIONS: dict[str, int] = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}

# Timeframes published by cross_asset_service — shared by all pipeline services
CROSS_ASSET_VALID_TFS: frozenset[str] = frozenset({"1m", "5m", "15m", "1h"})

# Per-TF signal TTL (bars). Lifecycle evaluation window per timeframe.
# 1m=20 min, 5m=60 min, 15m=2 hr, 1h=6 hr.
# Single source of truth — imported by signal_generator_service and lifecycle_replay.
TF_TTL_BARS: dict[str, int] = {
    "1m": 20,
    "5m": 12,
    "15m": 8,
    "1h": 6,
}


def bar_close_ts(ts: datetime, tf: str) -> datetime:
    """Return actual bar close time.

    For 1m bars, ts is already the close timestamp.
    For 5m/15m/1h bars, ts is the period start — close = ts + tf_duration.
    Unknown timeframes return ts unchanged (zero offset).
    """
    return ts + timedelta(seconds=TF_DURATIONS.get(tf, 0))


def should_skip_plugin(
    plugin: Any,
    instrument: Any | None,
    skipped_counter: Any,
    plugin_name: str,
) -> bool:
    """Return True (and increment counter) if plugin should be skipped for this asset class.

    Pass plugin_name explicitly since not all plugins expose .name at call-site.
    """
    if instrument is None:
        return False
    from src.core.models import _ALL_ASSET_CLASSES

    allowed: frozenset = getattr(plugin, "valid_asset_classes", _ALL_ASSET_CLASSES)
    if instrument.asset_class not in allowed:
        skipped_counter.labels(
            plugin_name=plugin_name,
            asset_class=instrument.asset_class.value,
        ).inc()
        return True
    return False


def parse_roll_event(event: dict, logger: Any) -> tuple[str, str] | None:
    """Validate and extract (old_symbol, new_symbol) from a roll event payload.

    Returns None (and logs a warning) if the event is not a roll event or is missing fields.
    Shared across all services that subscribe to system.events.
    """
    if event.get("event_type") != "roll":
        return None
    try:
        return event["old_symbol"], event["new_symbol"]
    except KeyError as exc:
        logger.warning("roll_event_missing_fields", error=str(exc))
        return None


def setup_service_logging(log_file: str, level: str = "INFO", backup_count: int = 5) -> None:
    """Configure structlog and stdlib logging for a service.

    Creates the log directory if it does not exist, attaches a
    10 MB rotating file handler, and applies the standard structlog
    processor chain used by all IndicAgent services.

    Should be called once during service ``__init__``, before the first
    log statement.
    """
    log_dir = Path(log_file).parent
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=backup_count
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
        level=getattr(logging, level),
        handlers=[file_handler],
        format="%(message)s",
    )
