"""Shared utilities for IndicAgent services.

Centralises boilerplate that is otherwise copy-pasted across all six
service files: logging setup and timeframe bar thresholds.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

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


def bar_close_ts(ts: datetime, tf: str) -> datetime:
    """Return actual bar close time.

    For 1m bars, ts is already the close timestamp.
    For 5m/15m/1h bars, ts is the period start — close = ts + tf_duration.
    Unknown timeframes return ts unchanged (zero offset).
    """
    return ts + timedelta(seconds=TF_DURATIONS.get(tf, 0))


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
