"""Shared utilities for IndicAgent services.

Centralises boilerplate that is otherwise copy-pasted across all six
service files: logging setup and timeframe bar thresholds.
"""

from __future__ import annotations

import logging
import sys
from datetime import UTC, datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType

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


def bar_close_ts(ts: datetime, tf: str) -> datetime:
    """Return actual bar close time.

    For 1m bars, ts is already the close timestamp.
    For 5m/15m/1h bars, ts is the period start — close = ts + tf_duration.
    Unknown timeframes return ts unchanged (zero offset).
    """
    return ts + timedelta(seconds=TF_DURATIONS.get(tf, 0))


def parse_iso_ts(ts: str | bytes | datetime | None) -> datetime | None:
    """Parse ISO-8601 timestamp to UTC-aware datetime for asyncpg timestamptz columns.

    Handles:
    - ISO-8601 strings (with or without 'Z' suffix)
    - bytes (decoded first)
    - datetime objects (passed through with UTC fix)
    - None (returns None)

    Returns timezone-aware UTC datetime or None if parsing fails.

    This centralizes timestamp parsing logic that was duplicated across
    lifecycle_writer_agent, signal_writer_agent, feature_writer_agent, and swarm_writer_agent.
    """
    if ts is None:
        return None
    if isinstance(ts, bytes):
        ts = ts.decode()
    if isinstance(ts, str):
        try:
            dt = datetime.fromisoformat(ts)
        except (ValueError, TypeError):
            return None
    else:
        dt = ts

    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def format_iso_ts(dt: datetime) -> str:
    """Format datetime to ISO-8601 with Z suffix for Kafka/JSON serialization."""
    return dt.isoformat().replace("+00:00", "Z")


def parse_training_window_end(raw: str) -> datetime:
    """Parse a --training-window-end CLI arg into a UTC-aware datetime.

    Unlike parse_iso_ts, naive datetimes are rejected (not silently assumed UTC) —
    this is the OOS holdout enforcement point (docs/plans/OOS-EVAL-PROTOCOL.md);
    a caller passing a naive value likely meant a different timezone and needs to
    find out immediately, not have it silently reinterpreted as UTC.
    """
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        raise ValueError(
            "--training-window-end must be timezone-aware ISO 8601 (UTC). "
            "Naive datetimes are rejected to preserve the UTC-only invariant."
        )
    return dt.astimezone(UTC)


_configured_log_file: str | None = None


def _log_uncaught_exception(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_tb: TracebackType | None,
) -> None:
    """`sys.excepthook` replacement installed by `setup_service_logging` (todo 315).

    Python's default excepthook writes an uncaught exception's traceback straight to
    `sys.stderr`, bypassing this module's `RotatingFileHandler` entirely -- if a shell
    wrapper's own `>> logfile 2>&1` redirection (opened once at process start) is the
    only thing capturing stderr, that traceback is lost the moment the app's own
    rotation (`maxBytes=10MB`, hit organically by log volume on a busy run -- confirmed
    root cause of `regime_writer.log`'s undocumented ~7-15min rotation cadence, todo 315)
    renames the file out from under that stale shell-level fd. Routing through the
    already-configured logger instead lands the traceback in whichever generation is
    currently named `log_file` -- the file handler reopens by path on every rotation,
    the shell redirect does not. Still calls the original hook afterward (preserves the
    stderr print for a live terminal), so this only adds a durable second copy, not a
    behavior change for anyone watching the process interactively.
    """
    if issubclass(exc_type, KeyboardInterrupt):
        # Ctrl-C is operator-initiated, not a real crash -- don't log it as one.
        _ORIGINAL_EXCEPTHOOK(exc_type, exc_value, exc_tb)
        return
    logging.getLogger("uncaught_exception").critical(
        "Uncaught exception", exc_info=(exc_type, exc_value, exc_tb)
    )
    _ORIGINAL_EXCEPTHOOK(exc_type, exc_value, exc_tb)


_ORIGINAL_EXCEPTHOOK = sys.excepthook


def setup_service_logging(log_file: str, level: str = "INFO", backup_count: int = 3) -> None:
    """Configure structlog and stdlib logging for a service.

    Creates the log directory if it does not exist, attaches a
    10 MB rotating file handler, and applies the standard structlog
    processor chain used by all IndicAgent services. Also installs a
    `sys.excepthook` that routes uncaught exceptions through this same rotation-safe
    handler (todo 315) -- the one gap a `RotatingFileHandler` alone doesn't close,
    since Python's default crash-traceback path bypasses the logging system.

    Should be called once during service ``__init__``, before the first
    log statement.

    Idempotent: the first call wins — subsequent calls are no-ops.
    This prevents BaseDaemon.__init__ from overwriting a pre-configured log path.
    """
    global _configured_log_file
    if _configured_log_file is not None:
        return
    _configured_log_file = log_file
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
        force=True,
    )
    sys.excepthook = _log_uncaught_exception
