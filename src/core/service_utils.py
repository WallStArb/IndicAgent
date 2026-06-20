"""Shared utilities for IndicAgent services.

Centralises boilerplate that is otherwise copy-pasted across all six
service files: logging setup and timeframe bar thresholds.
"""

from __future__ import annotations

import logging
import re as _re
from datetime import UTC, datetime, timedelta
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


def tf_to_seconds(tf: str) -> int:
    """Return wall-clock seconds per bar for the given timeframe.

    Uses TF_SECONDS as the source of truth. Unknown timeframes default to
    60 seconds (1m equivalent) — callers must guard against unexpected TF values.

    Used for expires_at computation: expires_at = timestamp + ttl_bars * tf_to_seconds(tf).
    """
    return TF_SECONDS.get(tf, 60)


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
    "15m": 10,
    "1h": 8,
    "4h": 6,
    "1d": 4,
}

# Tick sizes per instrument for price rounding.
# Unknown symbols get full precision (no rounding).
TICK_SIZES: dict[str, float] = {
    # FX pairs — pipette (0.00001)
    "EURUSD": 0.00001,
    "GBPUSD": 0.00001,
    "USDCHF": 0.00001,
    "AUDUSD": 0.00001,
    "NZDUSD": 0.00001,
    "USDCAD": 0.00001,
    # JPY pairs — 0.001
    "USDJPY": 0.001,
    "EURJPY": 0.001,
    "GBPJPY": 0.001,
    # Index futures — 0.25
    "ES": 0.25,
    "NQ": 0.25,
    "YM": 1.0,
    "RTY": 0.10,
    # Rate futures — 1/64
    "ZN": 0.015625,
    "ZB": 0.015625,
    "ZF": 0.015625,
    "ZT": 0.015625,
    # Commodity futures
    "CL": 0.01,
    "NG": 0.001,
    "GC": 0.10,
    "SI": 0.001,
    "ZW": 0.25,
    "ZC": 0.25,
    "ZS": 0.25,
    # Commodity futures (continued)
    "HG": 0.0005,
    # Equities/ETFs — 0.01
    "SPY": 0.01,
    "QQQ": 0.01,
    "IWM": 0.01,
    "AAPL": 0.01,
    # Bond/fixed-income ETFs — 0.01
    "SHY": 0.01,
    "IEF": 0.01,
    "TLT": 0.01,
    "HYG": 0.01,
    "LQD": 0.01,
    "EMB": 0.01,
    # Sector ETFs — 0.01
    "XLF": 0.01,
    "XLE": 0.01,
    "XLK": 0.01,
    "GLD": 0.01,
    "SLV": 0.01,
    # VIX
    "VIX": 0.01,
    "VX": 0.05,
}


def get_tick_size(symbol: str) -> float:
    """Get minimum tick size for symbol, stripping futures expiry codes if needed.

    Falls back to 0.01 (US equity/ETF default) rather than 0, which would silently
    bypass the emission stop-distance gate for unknown instruments.
    """
    tick = TICK_SIZES.get(symbol)
    if tick is not None:
        return tick
    # Strip futures expiry code: ZTM6 → ZT, NGN6 → NG, ESH7 → ES
    base = _re.sub(r"[A-Z]\d+$", "", symbol)
    if base != symbol:
        tick = TICK_SIZES.get(base)
        if tick is not None:
            return tick
    return 0.01  # Conservative default — prevents gate bypass for unknown instruments


def round_to_tick(price: float, symbol: str) -> float:
    """Round price to the nearest tick for the given symbol.

    Returns the price unchanged for unknown instruments (preserving full precision).
    Use get_tick_size() when a non-zero fallback is needed (e.g. the emission gate).
    """
    tick = TICK_SIZES.get(symbol)
    if tick is None:
        base = _re.sub(r"[A-Z]\d+$", "", symbol)
        if base != symbol:
            tick = TICK_SIZES.get(base)
    if not tick:
        return price
    return round(round(price / tick) * tick, 10)


def is_signal_stale(signal_ts: datetime, tf: str, now: datetime, multiplier: int = 2) -> bool:
    """Return True if signal_ts is older than multiplier × TF duration.

    Use to skip signals whose market context has expired before LLM dispatch.
    """
    max_age_s = multiplier * TF_SECONDS.get(tf, 300)
    return (now - signal_ts).total_seconds() > max_age_s


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
        skipped_counter.add(
            1,
            {"plugin_name": plugin_name, "asset_class": instrument.asset_class.value},
        )
        return True
    return False


def normalize_session_type(value: str | None, default: str = "rth") -> str:
    """Return a canonical session_type string, handling legacy enum repr format.

    Old code serialised SessionType enums via str(), producing "SessionType.RTH"
    instead of "rth". This function normalises both formats so services reading
    from DB or Kafka are not affected by that legacy data.
    """
    st = value or default
    if st.startswith("SessionType."):
        name = st.split(".", 1)[1].upper()
        from src.core.schemas.bar_message import SessionType  # local import avoids circular

        st = SessionType.__members__.get(name, SessionType(default)).value
    return st


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


_configured_log_file: str | None = None


def setup_service_logging(log_file: str, level: str = "INFO", backup_count: int = 3) -> None:
    """Configure structlog and stdlib logging for a service.

    Creates the log directory if it does not exist, attaches a
    10 MB rotating file handler, and applies the standard structlog
    processor chain used by all IndicAgent services.

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
    )
