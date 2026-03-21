#!/usr/bin/env python3
"""
Signal Generator Service — I7 plugin execution and aggregation

Subscribes to intelligence:SYMBOL:TF stream (enriched with OHLCV by
market_analysis_service). On each bar: runs all I7 setup plugins,
aggregates signals, inserts all to signal_ledger, publishes winner to
signals:SYMBOL:TF:aggregated.

Lifecycle tracking (pending→active→exit, P&L) is handled separately by
signal_lifecycle_service, which subscribes to market:SYMBOL:1m directly.
"""

from __future__ import annotations

import asyncio
import json
import signal
import sys
import time
import zoneinfo
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import numpy as np
import pandas as pd
import structlog
from prometheus_client import Counter as _PrometheusCounter
from pydantic import ValidationError

from src.config.settings import Settings, get_active_symbols
from src.core.bar_history import BarHistory
from src.core.database_manager import DatabaseManager
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.plugin_validator import PluginValidator
from src.core.schemas.bar_message import BarMessage
from src.core.service_utils import (
    TF_SECONDS,
    TF_TTL_BARS,
    parse_roll_event,
    setup_service_logging,
)
from src.core.stream_keys import (
    message_key,
    topic_cross_asset,
    topic_intelligence,
    topic_market_ticks,
    topic_quality_gated,
    topic_signals,
    topic_signals_aggregated,
    topic_system_events,
    topic_winner,
)
from src.intelligence.cross_asset_features import resolve_eq_index_base
from src.intelligence.plugins import registry
from src.intelligence.register_plugins import TIER_I7, register_all_plugins
from src.intelligence.schemas import IntelligenceEvent
from src.intelligence.trading.cis_scorer import CISScorer
from src.intelligence.trading.signal_ledger import (
    LedgerEntry,
    SignalStatus,
    insert_signals_with_features,
)
from src.intelligence.trading.signal_schema import make_signal, validate_signal
from src.monitoring.ks_drift_monitor import DRIFT_PENALTIES
from src.observability.metrics import (
    BAR_TO_SIGNAL_LATENCY,
    counter,
    gauge,
    record_plugin_execution,
    start_metrics_server,
)

# I7 plugin names — imported from register_plugins (single source of truth)
I7_PLUGINS = TIER_I7

# Prometheus counter for signal validation failures (per D-17).
# Uses raw prometheus_client.Counter with labels (project helper counter() doesn't support labels).
SIGNAL_VALIDATION_FAILURES = _PrometheusCounter(
    "signal_validation_failures_total",
    "Signal validation failures before aggregation",
    ["plugin"],
)

# Minimum bars between published signals per timeframe. Prevents condition
# re-fires (same setup firing every bar while condition persists).
# Day-trading focus: 1m=3 bars (3 min cooldown), higher TFs=2 bars.
MIN_BARS_BETWEEN_SIGNALS: dict[str, int] = {"1m": 3, "5m": 2, "15m": 2, "1h": 2}
# TF_SECONDS imported from src.core.service_utils (shared with signal_lifecycle_service)

# QUAL-04: per-setup cooldown — prevents same setup/direction recycling within N bars.
# Keyed by (symbol, tf, setup_plugin, direction); independent of the bar-level _signal_gate.
# Day-trading focus: 1m=3 bars (3 min), higher TFs=2 bars (matches MIN_BARS_BETWEEN_SIGNALS).
_SIGNAL_COOLDOWN_BARS: dict[str, int] = {"1m": 3, "5m": 2, "15m": 2, "1h": 2}

# QUAL-02: alpha decay half-life — bars after which a repeated same-setup/direction signal
# has its confidence multiplied by max(0.0, 1.0 - bars_since / half_life).
# Starting values — replace with learned values after 90 days of outcome data.
# Regress half-life against Sharpe per TF when data justifies it.
ALPHA_HALF_LIFE_BARS: dict[str, int] = {"1m": 10, "5m": 8, "15m": 8, "1h": 6}

# TF_TTL_BARS imported from src.core.service_utils — single source of truth.

# Slow-clock regime authority: maps each TF to the higher-TF whose HMM regime
# is used for gating. Avoids gating 1m signals on noisy 1m HMM.
# If the authority TF stream is not subscribed, cache entry is absent → gate skipped.
# 1h signals gate on 4h HMM. If 4h stream not subscribed, cache entry absent → gate skipped.
_REGIME_AUTHORITY_TF: dict[str, str] = {
    "1m": "5m",
    "5m": "15m",
    "15m": "1h",
    "1h": "4h",
    "4h": "1d",
    "1d": "1d",
}

# Phase 35 TOD: Eastern Time zone for hour extraction
_ET = zoneinfo.ZoneInfo("America/New_York")

# Phase 35 TOD: session priors per (regime_type, hour_et) — expanded to individual hour keys.
# NY open (09:30-10:00): hour 9. Lunch chop (11:30-13:00): hours 11, 12.
# London close (14:00-15:00): hour 14. MOC (15:30-16:00): hour 15.
_TOD_SESSION_PRIORS: dict[tuple[str, int], float] = {
    ("trend",           9): 1.10,
    ("mean_reversion",  9): 1.00,
    ("any",             9): 1.00,
    ("trend",          11): 0.90,
    ("mean_reversion", 11): 0.90,
    ("any",            11): 0.90,
    ("trend",          12): 0.90,
    ("mean_reversion", 12): 0.90,
    ("any",            12): 0.90,
    ("mean_reversion", 14): 1.08,
    ("any",            15): 1.10,
}
_TOD_ALPHA = 20.0    # prior weight in virtual observations
_TOD_CLAMP = (0.7, 1.3)

# ---------------------------------------------------------------------------
# Phase 35: CIS Kalman filter — local-level 1D model (KAL-01 / KAL-02)
# ---------------------------------------------------------------------------
_CIS_KALMAN_DEFAULTS: dict[str, dict[str, float]] = {
    "1m":  {"Q": 0.01, "R": 0.08},
    "5m":  {"Q": 0.01, "R": 0.06},
    "15m": {"Q": 0.01, "R": 0.04},
    "1h":  {"Q": 0.01, "R": 0.02},
}


def _load_cis_kalman_params() -> dict[str, dict[str, float]]:
    """Load per-TF CIS Kalman Q/R from config/kalman_parameters.json.

    Falls back to _CIS_KALMAN_DEFAULTS if file missing or 'cis_kalman' key absent.
    Degrades gracefully — service never crashes on missing config file.
    """
    config_path = Path(__file__).parent.parent / "config" / "kalman_parameters.json"
    try:
        data = json.loads(config_path.read_text())
        params = data.get("cis_kalman", _CIS_KALMAN_DEFAULTS)
        return {tf: dict(v) for tf, v in params.items()}
    except Exception:
        return dict(_CIS_KALMAN_DEFAULTS)


_CIS_KALMAN_PARAMS: dict[str, dict[str, float]] = _load_cis_kalman_params()


def _cis_kalman_update(
    raw_cis: float,
    x_est: float,
    P_est: float,
    Q: float,
    R: float,
) -> tuple[float, float]:
    """One predict+update step of the local-level 1D Kalman filter on CIS score.

    Exact recursion from KalmanTrendPlugin — applied to CIS in [-1, 1] space.
    Returns (new_x_est, new_P_est).
    """
    P_pred = P_est + Q
    K = P_pred / (P_pred + R)
    x_new = x_est + K * (raw_cis - x_est)
    P_new = (1.0 - K) * P_pred
    return x_new, P_new



logger = structlog.get_logger(__name__)

# Valid timeframes published by cross_asset_service — bounds _cross_asset_cache keys
_CROSS_ASSET_VALID_TFS: frozenset[str] = frozenset({"1m", "5m", "15m", "1h"})

# ---------------------------------------------------------------------------
# Phase 42: pattern_reliability weight cache (15-min TTL)
# ---------------------------------------------------------------------------
_pattern_reliability_cache: dict[str, float] | None = None
_pattern_reliability_cache_ts: datetime | None = None
_pattern_reliability_cache_ttl_sec: int = 900  # 15 minutes


async def _load_pattern_reliability_weights(
    db_manager: DatabaseManager,
) -> dict[str, float]:
    """Load pattern confidence weights from pattern_reliability table with 15-min cache.

    Returns preloaded dict for injection into frames["pattern_weights"].
    Bootstrap priors (is_bootstrap=true) always included; calibrated weights
    (sample_size >= 30) override bootstrap when available.
    """
    global _pattern_reliability_cache, _pattern_reliability_cache_ts

    if db_manager is None:
        return _pattern_reliability_cache if _pattern_reliability_cache is not None else {}

    now = datetime.now(UTC)
    if (
        _pattern_reliability_cache is not None
        and _pattern_reliability_cache_ts is not None
        and (now - _pattern_reliability_cache_ts).total_seconds()
        < _pattern_reliability_cache_ttl_sec
    ):
        return _pattern_reliability_cache

    try:
        rows = await db_manager.execute_query("""
            SELECT pattern_name, base_confidence
            FROM pattern_reliability
            WHERE is_bootstrap = true OR sample_size >= 30
        """)
        weights = {r["pattern_name"]: float(r["base_confidence"]) for r in rows}
        _pattern_reliability_cache = weights
        _pattern_reliability_cache_ts = now
        logger.info(f"Pattern reliability weights loaded from DB: {len(weights)} patterns")
        return weights
    except Exception as exc:
        logger.warning(f"Pattern reliability load failed, using fallback: {exc}")
        return {}  # Plugin will use its own fallback_weights


def _apply_alpha_decay(
    sig: dict,
    tf: str,
    last_fire_state: dict | None,
) -> None:
    """QUAL-02: Apply alpha decay to signal confidence in-place.

    If the same setup/direction fired recently (within ALPHA_HALF_LIFE_BARS bars),
    the repeated fire carries less information value. Confidence is multiplied by:
        multiplier = max(0.0, 1.0 - bars_since / half_life)

    Args:
        sig: Signal dict — confidence is mutated in place.
        tf: Timeframe string used to look up half-life.
        last_fire_state: Dict with "bars_since" key from _setup_last_fire, or None
            if this is the first fire for this setup/direction (no decay applied).
    """
    if last_fire_state is None:
        return  # First fire — no decay
    bars_since = last_fire_state.get("bars_since", 0)
    half_life = ALPHA_HALF_LIFE_BARS.get(tf, 6)
    multiplier = max(0.0, 1.0 - bars_since / half_life)
    sig["confidence"] = round(float(sig.get("confidence", 0.0)) * multiplier, 4)


def _parse_intelligence_event(fields: dict) -> IntelligenceEvent | None:
    """Parse intelligence stream message into typed IntelligenceEvent.

    Handles both Kafka payload dicts (string keys) and legacy Redis bytes dicts.
    Returns None and logs a warning if the message is malformed or version unknown.
    """
    # Try string key (Kafka JSON dict) first, then bytes key (legacy Redis)
    raw = fields.get("event") or fields.get(b"event", b"")
    if not raw:
        return None
    try:
        return IntelligenceEvent.model_validate_json(raw)
    except (ValidationError, ValueError) as e:
        logger.warning("Failed to parse IntelligenceEvent", error=str(e))
        return None


def _build_features_from_event(event: IntelligenceEvent) -> dict[str, Any]:
    """Build a features dict from a typed IntelligenceEvent for I7 plugins.

    Flattens all sub-models so every I7 plugin gets the features it needs.
    Legacy key aliases are preserved for signal_ledger market_context stability.
    """
    f: dict[str, Any] = {}

    # I1 — all fields including extras (VWAP, etc.)
    for k, v in event.i1.model_dump().items():
        if v is not None:
            f[k] = v
    # BB aliases: plugins may expect bb_middle / bb_upper / bb_lower
    f["bb_middle"] = event.i1.bb_20_2_mid
    f["bb_upper"] = event.i1.bb_20_2_upper
    f["bb_lower"] = event.i1.bb_20_2_lower

    # I2 — composite events (crossovers, threshold extremes, volume events)
    for k, v in event.i2.model_dump().items():
        if v is not None:
            f[k] = v

    # Close price — used by bridge composites stored in I2 (DonchianPosition etc.)
    f["close_price"] = event.bar.c

    # I3 — swing, S/R, trend structure
    for k, v in event.i3.model_dump().items():
        if v is not None:
            f[k] = v
    # SR aliases: plugins use sr_nearest_support / sr_nearest_resistance
    f["sr_nearest_support"] = event.i3.nearest_support
    f["sr_nearest_resistance"] = event.i3.nearest_resistance

    # I4 — regimes, GARCH, Kalman
    for k, v in event.i4.model_dump().items():
        if v is not None:
            f[k] = v
    # Legacy key aliases
    f["vol_regime"] = event.i4.vol_regime
    f["volatility_regime"] = event.i4.vol_regime
    f["volatility_percentile"] = event.i4.vol_percentile
    f["hmm_regime_state"] = event.smc.hmm_regime

    # I5 — squeeze_fired, rsi divergence, momentum, patterns
    for k, v in event.i5.model_dump().items():
        if v is not None:
            f[k] = v

    # SMC — all 61 fields (sweep_*, fvg_*, ob_*, bsl_*, ssl_*, S/D zones, etc.)
    for k, v in event.smc.model_dump().items():
        if v is not None:
            f[k] = v

    # I6 — cross-timeframe confluence
    for k, v in event.i6.model_dump().items():
        if v is not None:
            f[k] = v

    return f


def _extract_live_quote(live_quotes: dict, symbol: str) -> dict[str, float | None]:
    """Extract live bid/ask from _live_quotes in-process dict.

    Returns {"bid": None, "ask": None} if no entry exists for the symbol,
    matching the prior HGETALL-miss semantics.
    """
    entry = live_quotes.get(symbol)
    if not entry:
        return {"bid": None, "ask": None}

    def _parse(key: str) -> float | None:
        val = entry.get(key)
        if val is None:
            return None
        try:
            f = float(val)
            return f if f > 0 else None
        except (TypeError, ValueError):
            return None

    return {"bid": _parse("bid"), "ask": _parse("ask")}


def _is_zone_valid(
    direction: int,
    market_price: float | None,
    entry_zone_low: float | None,
    entry_zone_high: float | None,
) -> bool | None:
    """True if market price is still reachable (within or near zone)."""
    if market_price is None or entry_zone_low is None or entry_zone_high is None:
        return None
    if direction == 1:
        return market_price <= entry_zone_high
    else:
        return market_price >= entry_zone_low


class SignalGeneratorService:
    """Execute I7 setup plugins, aggregate signals, and persist to signal_ledger."""

    # Class-level defaults — overridden per-instance in __init__.
    # Required by the __new__ test pattern (CLAUDE.md): attributes accessed via
    # hasattr() on bare __new__ instances must be defined at class level.
    _perf_weights: dict[str, float] = {}  # noqa: RUF012
    _drift_penalties: dict[tuple[str, str], float] = {}  # noqa: RUF012
    _cis_weights_cache: dict = {}  # noqa: RUF012

    def __init__(self, config_file: str | None = None):
        self.running = False
        self.shutdown_requested = False
        self.shutdown_event = asyncio.Event()
        self.start_time = datetime.now(tz=UTC)

        self.config = self._load_config(config_file)
        self._setup_logging()

        register_all_plugins()
        registry.validate_tier(I7_PLUGINS, "I7")

        self.db_manager: DatabaseManager | None = None
        self._kafka_consumer: KafkaConsumerClient | None = None
        self._kafka_producer: KafkaProducerClient | None = None
        # DAG pipeline: producer publishes I7 signals to QualityGate stage entry point.
        # Winner consumer receives selected signals from WinnerSelector stage for DB writes.
        self._dag_winner_consumer: KafkaConsumerClient | None = None

        settings = Settings()
        self.env_name = settings.env_name or ""
        self.env_prefix = f"{settings.env_name}:" if settings.env_name else ""
        self._kafka_bootstrap = getattr(settings, "kafka_bootstrap_servers", "localhost:19092")
        self._roll_monitor_enabled = getattr(settings, "roll_monitor_enabled", False)

        # In-process live quotes dict: symbol → {"bid": float, "ask": float}
        # Populated by ticks topic handler. Replaces Redis HGETALL for price:SYMBOL:latest.
        self._live_quotes: dict[str, dict] = {}

        self._bar_history: BarHistory = BarHistory(maxlen=200)
        self._stream_map: dict[str, tuple[str, str]] = {}
        self._df_cache: dict[str, pd.DataFrame | None] = {}
        # Regime cache for slow-clock gating (SIGINT-04).
        # Structure: {symbol: {tf: {"hmm_regime": float, "hmm_regime_prob": float,
        #                           "hmm_regime_duration": float}}}
        # Updated on every IntelligenceEvent arrival; used by _process_bar() to look
        # up the authority TF regime data for regime gating in aggregate().
        self._regime_cache: dict[str, dict[str, dict]] = defaultdict(dict)
        # Performance weights cache: setup_plugin → perf_multiplier [0.5, 1.5].
        # Loaded from Redis at startup and refreshed every 60 min by
        # _run_refresh_loop("perf_weights",...). Empty dict = neutral (all multipliers=1.0).
        self._perf_weights: dict[str, float] = {}
        # QUAL-09: KS drift penalty cache — (symbol, tf) → float penalty [0.70, 1.0].
        # Read from Redis per bar evaluation. Absent key → penalty=1.0 (no drift).
        self._drift_penalties: dict[tuple[str, str], float] = {}
        # Gate dict: tracks last published signal per (symbol, timeframe) to prevent
        # condition re-fires (cooldown) and direction flips before prior signal resolves.
        # In-memory only — resets on service restart (first signal post-restart publishes).
        self._signal_gate: dict[tuple[str, str], dict] = {}
        # QUAL-04: per-setup cooldown — keyed by (symbol, tf, setup_plugin, direction).
        # Value = datetime when the cooldown was set (used with TF_SECONDS to compute
        # bars elapsed at filter time). Independent of _signal_gate (aggregated-winner level).
        self._setup_cooldown: dict[tuple[str, str, str, int], datetime] = {}
        # QUAL-02: alpha decay state — keyed by (symbol, tf, setup_plugin, direction).
        # Value = {"bars_since": int} — incremented each bar for that (symbol, tf).
        # Reset to {"bars_since": 0} after each fire. Separate from _setup_cooldown.
        self._setup_last_fire: dict[tuple[str, str, str, int], dict] = {}
        # CIS scorer instance — loaded with bootstrap weights at startup, updated
        # every 30 minutes from the cis_weights table by _run_refresh_loop("cis_weights",...).
        self._cis_scorer: CISScorer = CISScorer()
        # CIS weights cache: (asset_cluster, timeframe) -> (weights_dict, version)
        # Populated by _load_cis_weights_from_db(); used for per-cluster weight lookup.
        self._cis_weights_cache: dict[tuple[str, str], tuple[dict[str, float], int]] = {}

        # Phase 35: Calibration + TOD multiplier + CIS Kalman state
        self._calibration_curves: dict[tuple[str, str], tuple[np.ndarray, np.ndarray]] = {}   # (plugin_name, tf) -> (breakpoints, values)
        self._tod_multipliers: dict = {}      # (regime_type, tf, hour_et) -> float multiplier
        self._cis_kalman_state: dict = {}     # (symbol, tf) -> {x_est, P_est} — used in plan 03

        # Phase 037: Cross-asset intelligence cache (keyed by tf)
        self._cross_asset_enabled: bool = getattr(settings, "cross_asset_enabled", False)
        self._cross_asset_cache: dict[str, dict] = {}  # tf -> latest cross_asset payload

        # Phase 041: Higher-timeframe intelligence cache for HTF context injection
        # Plain dict - bounded by active symbol set in practice (~50 symbols)
        self._htf_intel_cache: dict[str, dict] = {}  # "{symbol}:1h" -> latest 1h intel features

        self.bars_processed_total = counter(
            "generator_bars_processed_total",
            "Total intelligence events processed by signal generator",
        )
        self.signals_generated_total = counter(
            "generator_signals_generated_total",
            "Total signals inserted to signal_ledger",
        )
        self.signals_selected_total = counter(
            "generator_signals_selected_total",
            "Total signals where was_selected=True",
        )
        self.calculation_duration_ms = gauge(
            "generator_calculation_duration_ms",
            "Per-bar processing time in milliseconds",
        )
        self.service_uptime_seconds = gauge(
            "generator_service_uptime_seconds",
            "Signal generator service uptime in seconds",
        )
        self.error_count_total = counter(
            "generator_errors_total",
            "Total errors encountered by signal generator",
        )

        self._total_bars = 0
        self._total_signals = 0
        self._error_count = 0

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self.logger = structlog.get_logger(__name__)
        start_metrics_server(port=9112)

    def _load_config(self, config_file: str | None) -> dict[str, Any]:
        try:
            _settings = Settings()
        except Exception as e:
            logger.warning("Settings() failed in _load_config — using defaults", error=str(e))
            _settings = None

        default_config: dict[str, Any] = {
            "database": {
                "url": (
                    _settings.database_url
                    if _settings and getattr(_settings, "database_url", None)
                    else "postgresql://postgres:postgres@localhost:5432/indicagent"
                )
            },
            "service": {
                "symbols": get_active_symbols(_settings),
                # 4h and 1d intentionally excluded: day-trading focus. 4h bars close 4×/day,
                # 1d once/day — signal latency too high for intraday entries. Extend in a future
                # phase if swing-trading scope is added.
                "timeframes": ["1m", "5m", "15m", "1h"],
                "min_history_bars": 50,
                "processing_interval": 0.1,
                "health_check_interval": 30,
            },
            "logging": {
                "level": "INFO",
                "file": "logs/signal_generator_service.log",
                "max_size": "10MB",
                "backup_count": 5,
            },
        }

        if config_file and Path(config_file).exists():
            with open(config_file) as f:
                user_config = json.load(f)
            for key, value in user_config.items():
                if isinstance(value, dict) and key in default_config:
                    default_config[key].update(value)
                else:
                    default_config[key] = value

        return default_config

    def _setup_logging(self) -> None:
        setup_service_logging(
            self.config["logging"]["file"],
            level=self.config["logging"].get("level", "INFO"),
            backup_count=self.config["logging"].get("backup_count", 5),
        )

    def _check_gate(self, symbol: str, tf: str, direction: int, timestamp: datetime) -> bool:
        """Return True (suppress signal) if gate blocks this signal, False (allow) otherwise.

        Suppresses if:
        1. Cooldown: bars since last published signal < MIN_BARS_BETWEEN_SIGNALS[tf]
        2. Flip-while-unresolved: direction changed AND prior signal not resolved
        Returns False (allow) if no prior gate entry exists (first signal always publishes).
        """
        gate = self._signal_gate.get((symbol, tf))
        if gate is None:
            return False  # No prior signal — always allow

        tf_secs = TF_SECONDS.get(tf, 60)
        min_bars = MIN_BARS_BETWEEN_SIGNALS.get(tf, 2)
        bars_since = (timestamp - gate["bar_ts"]).total_seconds() / tf_secs

        # Cooldown: same or different direction — suppress if too soon
        if bars_since < min_bars:
            return True

        # Direction flip while prior signal is still live — suppress
        if direction != gate["direction"] and not gate["resolved"]:
            return True

        return False

    def _update_gate(
        self, symbol: str, tf: str, direction: int, timestamp: datetime, signal_id: str
    ) -> None:
        """Record gate state after a signal is successfully published to the stream."""
        self._signal_gate[(symbol, tf)] = {
            "direction": direction,
            "bar_ts": timestamp,
            "signal_id": signal_id,
            "resolved": False,
        }

    def _filter_setup_cooldown(
        self,
        symbol: str,
        tf: str,
        signals: list[dict],
        timestamp: datetime,
    ) -> list[dict]:
        """QUAL-04: Filter signals blocked by per-setup cooldown gate.

        Prevents same setup/direction from recycling within _SIGNAL_COOLDOWN_BARS bars.
        Runs before aggregation (before alpha decay path) so blocked signals never enter ranking.

        The cooldown dict stores the fire timestamp per (symbol, tf, plugin, direction).
        At filter time, bars_elapsed is computed from (timestamp - fired_at) / tf_seconds.
        A signal is blocked if bars_elapsed < _SIGNAL_COOLDOWN_BARS[tf].

        Returns the subset of signals that passed the gate.
        """
        tf_secs = TF_SECONDS.get(tf, 60)
        cooldown_bars = _SIGNAL_COOLDOWN_BARS.get(tf, 2)

        accepted = []
        for sig in signals:
            plugin = sig.get("setup_plugin", "")
            direction = int(sig.get("direction", 0))
            key = (symbol, tf, plugin, direction)

            fired_at = self._setup_cooldown.get(key)
            if fired_at is not None:
                bars_elapsed = (timestamp - fired_at).total_seconds() / tf_secs
                if bars_elapsed < cooldown_bars:
                    # Blocked by cooldown — skip before alpha decay
                    self.logger.debug(
                        "Signal cooldown-blocked",
                        symbol=symbol,
                        tf=tf,
                        plugin=plugin,
                        direction=direction,
                        bars_elapsed=round(bars_elapsed, 2),
                        cooldown_bars=cooldown_bars,
                    )
                    continue

            accepted.append(sig)
            # Register/refresh cooldown for this setup+direction
            self._setup_cooldown[key] = timestamp

        return accepted

    async def _resolution_listener_loop(self) -> None:
        """Monitor signals.aggregated topic for direction=0 lifecycle exit events.

        Signal lifecycle service publishes direction=0 to signals.aggregated
        when a signal exits (any outcome). When we see direction=0, mark the gate for
        that (symbol, tf) as resolved — allowing direction flips on the next bar.
        Uses a separate Kafka consumer subscribed to signals.aggregated.
        """
        try:
            resolution_consumer = KafkaConsumerClient(
                topic_signals_aggregated(self.env_name),
                bootstrap_servers=self._kafka_bootstrap,
                group_id="signal_generator_resolution",
                auto_offset_reset="latest",
            )
            await resolution_consumer.start()
            try:
                async for _topic, _key, payload in resolution_consumer.messages():
                    if self.shutdown_requested:
                        break
                    try:
                        direction_raw = payload.get("direction", "")
                        if not direction_raw:
                            continue
                        try:
                            direction_val = int(float(str(direction_raw)))
                        except (ValueError, TypeError):
                            continue
                        if direction_val != 0:
                            continue
                        # direction=0 → lifecycle exit; mark gate resolved
                        sym = str(payload.get("symbol", ""))
                        tf = str(payload.get("timeframe", ""))
                        if (sym, tf) in self._signal_gate:
                            self._signal_gate[(sym, tf)]["resolved"] = True
                            self.logger.debug("Gate resolved", symbol=sym, timeframe=tf)
                    except Exception as e:
                        self.logger.warning("Resolution listener message error", error=str(e))
            except asyncio.CancelledError:
                pass
            finally:
                await resolution_consumer.stop()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.logger.warning("Resolution listener failed to start", error=str(e))

    def _signal_handler(self, signum: int, frame: Any) -> None:
        self.logger.info("Received shutdown signal", signal=signum)
        self.shutdown_requested = True

    async def _connect_database(self) -> None:
        try:
            self.db_manager = DatabaseManager(self.config["database"]["url"])
            await self.db_manager.initialize()
            self.logger.info("Connected to database")
        except Exception as e:
            self.logger.warning("Database unavailable, persistence disabled", error=str(e))
            self.db_manager = None

    async def _handle_ticks_message(self, symbol: str, payload: dict) -> None:
        """KAFKA-06: Update _live_quotes with latest tick for symbol.

        Called when a message arrives on the market.ticks topic.
        Key is SYMBOL (no TF). Keeps only the latest tick per symbol.
        """
        self._live_quotes[symbol] = payload

    async def _handle_roll_event(self, event: dict) -> None:
        """Migrate bar_history keys from old_symbol to new_symbol on futures roll.

        Delegates to BarHistory.migrate_symbol() which atomically renames all
        (old_symbol, tf) keys to (new_symbol, tf) without dropping any buffered bars.
        Also invalidates the df_cache for both symbols so the next bar triggers a rebuild.
        """
        result = parse_roll_event(event, self.logger)
        if result is None:
            return
        old_symbol, new_symbol = result

        self._bar_history.migrate_symbol(old_symbol, new_symbol)
        # Invalidate df_cache for both symbols across all TFs
        for tf in ["1m", "5m", "15m", "1h"]:
            self._df_cache.pop(f"{old_symbol}:{tf}", None)
            self._df_cache.pop(f"{new_symbol}:{tf}", None)
        self.logger.info(
            "roll_bar_history_migrated",
            old=old_symbol,
            new=new_symbol,
        )

    async def _setup_kafka_clients(self) -> None:
        """Initialize Kafka consumer (intelligence + ticks) and producer (signals)."""
        topics: list[str] = [
            topic_intelligence(self.env_name),
            topic_market_ticks(self.env_name),
        ]
        if self._roll_monitor_enabled:
            topics.append(topic_system_events(self.env_name))
        if self._cross_asset_enabled:
            topics.append(topic_cross_asset(self.env_name))

        self._kafka_consumer = KafkaConsumerClient(
            *topics,
            bootstrap_servers=self._kafka_bootstrap,
            group_id="signal_generator_group",
            auto_offset_reset="latest",
        )
        await self._kafka_consumer.start()
        self.logger.info(
            "Kafka consumer started",
            topics=topics,
        )

        self._kafka_producer = KafkaProducerClient(self._kafka_bootstrap)
        await self._kafka_producer.start()
        self.logger.info("Kafka producer started")

        # DAG pipeline: winner consumer — receives selected signals from WinnerSelector stage.
        # Separate consumer group so it doesn't interfere with the main intelligence consumer.
        self._dag_winner_consumer = KafkaConsumerClient(
            topic_winner(self.env_name),
            bootstrap_servers=self._kafka_bootstrap,
            group_id="signal_generator_winner_group",
            auto_offset_reset="latest",
        )
        await self._dag_winner_consumer.start()
        self.logger.info(
            "DAG winner consumer started",
            topic=topic_winner(self.env_name),
        )

    async def stop(self) -> None:
        self.logger.info("Stopping Signal Generator Service")
        self.running = False
        self.shutdown_requested = True
        self.shutdown_event.set()
        if self._kafka_consumer:
            await self._kafka_consumer.stop()
        if self._kafka_producer:
            await self._kafka_producer.stop()
        if self._dag_winner_consumer:
            await self._dag_winner_consumer.stop()
        if self.db_manager:
            await self.db_manager.close()
        self.logger.info("Signal Generator Service stopped")

    def _get_df(self, symbol: str, tf: str) -> pd.DataFrame:
        key = f"{symbol}:{tf}"
        if self._df_cache.get(key) is None:
            self._df_cache[key] = self._bar_history.to_dataframe(symbol, tf)
        return self._df_cache[key]

    def _run_setup_plugins(
        self,
        frames: dict[str, Any],
        symbol: str = "",
        timeframe: str = "",
        timestamp: datetime | None = None,
        ttl_bars: int = 10,
    ) -> tuple[list[dict], dict]:
        """Run all I7 setup plugins and return validated signals + always-log metadata.

        Per D-29/D-30: make_signal() is the single construction point; validate_signal()
        gates every signal before it reaches downstream processing.

        Per D-15/D-16/D-17/D-18: validation failures emit ERROR log + Prometheus counter
        + drop (never silent, never crash).

        Returns:
            (signals, plugin_metadata) where:
            - signals: list of validated signal.v1 dicts (direction != 0, passed validation)
            - plugin_metadata: always-log fields from DivergenceStack regardless of signal fire

        Each signal dict is tagged with regime_type from the plugin attribute
        (Option B from RESEARCH.md — tag at plugin execution, keeps aggregator stateless).
        """
        signals = []
        plugin_metadata: dict = {}
        ts_str = timestamp.isoformat() if timestamp is not None else ""
        close_price = 0.0
        df = frames.get("main")
        if df is not None and len(df) > 0:
            close_price = float(df["close"].iloc[-1])

        for name in I7_PLUGINS:
            t0 = time.time()
            try:
                plugin = registry.get_pattern(name)
                result = plugin.compute_full(frames)
                elapsed = time.time() - t0
                # Capture DivergenceStack always-log fields regardless of signal direction
                if name == "trad_DivergenceStack" and result:
                    if result.get("div_weighted_score") is not None:
                        plugin_metadata["divergence_scoring"] = {
                            "div_weighted_score": result.get("div_weighted_score"),
                            "div_n_agreeing": result.get("div_n_agreeing"),
                            "rsi_div_score": result.get("rsi_div_score"),
                            "macd_div_score": result.get("macd_div_score"),
                            "vol_div_score": result.get("vol_div_score"),
                            "obv_div_score": result.get("obv_div_score"),
                            "cmf_div_score": result.get("cmf_div_score"),
                        }
                if result and result.get("direction", 0) != 0:
                    # Per D-29: construct canonical signal.v1 via make_signal() factory
                    try:
                        signal = make_signal(
                            symbol=symbol,
                            timeframe=timeframe,
                            timestamp=ts_str,
                            signal_type=result["signal_type"],
                            setup_plugin=name,
                            direction=result["direction"],
                            entry_price=result.get("entry_price", close_price),
                            stop_loss=result["stop_loss"],
                            targets=result["targets"],
                            confidence=result["confidence"],
                            regime_context=result.get("regime_context", "any"),
                            confluence_score=result.get("confluence_score", 0.0),
                            supporting_factors=result.get("supporting_factors", []),
                            invalidation_conditions=result.get("invalidation_conditions", []),
                            ttl_bars=result.get("ttl_bars", ttl_bars),
                        )
                    except (KeyError, TypeError) as e:
                        self.logger.error(
                            "make_signal_construction_failed",
                            plugin=name,
                            error=str(e),
                            result_keys=list(result.keys()),
                        )
                        SIGNAL_VALIDATION_FAILURES.labels(plugin=name).inc()
                        record_plugin_execution(name, "", "", elapsed, "error", "I7")
                        continue

                    # Per D-30: validate before aggregation — drop invalid signals
                    if not validate_signal(signal):
                        self.logger.error(
                            "signal_validation_failed",
                            plugin=name,
                            signal=signal,
                            reason="validate_signal returned False",
                        )
                        SIGNAL_VALIDATION_FAILURES.labels(plugin=name).inc()
                        record_plugin_execution(name, "", "", elapsed, "validation_failed", "I7")
                        continue  # Drop invalid signal — never reaches aggregator (per D-18)

                    # Preserve extra plugin-output fields used downstream (e.g. regime_type tag,
                    # dual_divergence, tod_multiplier) that aren't part of signal.v1 schema
                    signal["regime_type"] = getattr(plugin, "regime_type", "any")
                    if "dual_divergence" in result:
                        signal["dual_divergence"] = result["dual_divergence"]
                    if "setup_variant" in result:
                        signal["setup_variant"] = result["setup_variant"]
                    if "stop_basis" in result:
                        signal["stop_basis"] = result["stop_basis"]

                    signals.append(signal)
                    record_plugin_execution(name, "", "", elapsed, "success", "I7")
                else:
                    record_plugin_execution(name, "", "", elapsed, "no_signal", "I7")
            except Exception as e:
                self.logger.warning("I7 plugin failed", plugin=name, error=str(e))
                record_plugin_execution(name, "", "", time.time() - t0, "error", "I7")
        return signals, plugin_metadata

    async def _process_bar(
        self,
        symbol: str,
        timeframe: str,
        bar: dict[str, Any],
        features: dict[str, Any],
        frames: dict[str, Any],
        timestamp: datetime,
        bar_close_ts: datetime | None = None,
        source: str = "live",
    ) -> None:
        """Generate signals, aggregate, persist, and publish winner."""
        df = frames.get("main")
        min_bars = self.config["service"]["min_history_bars"]
        if df is None or len(df) < min_bars:
            return

        calc_start = time.time()

        # Phase 041: Merge HTF VP levels into features with htf_1h_ prefix
        # _select_vp() in trade_framer reads these keys in its fallback branch
        htf_frame = frames.get("htf_1h", {})
        if htf_frame:
            htf_poc = htf_frame.get("poc_price") or htf_frame.get("poc_price_rolling")
            htf_vah = htf_frame.get("vah") or htf_frame.get("vah_rolling")
            htf_val = htf_frame.get("val") or htf_frame.get("val_rolling")
            if htf_poc is not None:
                features["htf_1h_poc_price"] = float(htf_poc)
            if htf_vah is not None:
                features["htf_1h_vah"] = float(htf_vah)
            if htf_val is not None:
                features["htf_1h_val"] = float(htf_val)

        # Apply per-TF TTL — make_signal() receives this value so signals are constructed
        # with the correct TTL from the start. TF_TTL_BARS is the single source of truth.
        tf_ttl = TF_TTL_BARS.get(timeframe, 10)

        raw_signals, _plugin_metadata = self._run_setup_plugins(
            frames,
            symbol=symbol,
            timeframe=timeframe,
            timestamp=timestamp,
            ttl_bars=tf_ttl,
        )

        # QUAL-04: per-setup cooldown — strip same setup/direction within N bars.
        # Runs before aggregation so blocked signals never enter alpha decay path.
        raw_signals = self._filter_setup_cooldown(symbol, timeframe, raw_signals, timestamp)

        # Phase 35 TOD-02: Apply Bayesian-smoothed TOD multiplier to each signal's confidence
        # PRE-CIS: multiplier affects bucket contribution → signal selection, not just ranking.
        # Lookup key: (regime_type, timeframe, hour_et); fallback to 1.0 (neutral).
        _bar_hour_et = timestamp.astimezone(_ET).hour
        for sig in raw_signals:
            _regime_t = sig.get("regime_type", "any")
            _tod_mult = self._tod_multipliers.get((_regime_t, timeframe, _bar_hour_et), 1.0)
            if _tod_mult != 1.0:
                sig["confidence"] = round(float(sig.get("confidence", 0.0)) * _tod_mult, 4)
                sig["tod_multiplier"] = _tod_mult  # logged in signal dict for observability

        # QUAL-02: alpha decay — increment bars_since for all tracked (symbol, tf) entries,
        # then apply decay to each signal's confidence BEFORE calling aggregate().
        # This preserves original confidence in signal_ledger (ledger uses post-decay values
        # from signal dicts, which are snapshots at fire time).
        for key in list(self._setup_last_fire):
            if key[0] == symbol and key[1] == timeframe:
                self._setup_last_fire[key]["bars_since"] = (
                    self._setup_last_fire[key].get("bars_since", 0) + 1
                )
        for sig in raw_signals:
            plugin = sig.get("setup_plugin", "")
            direction = int(sig.get("direction", 0))
            key = (symbol, timeframe, plugin, direction)
            _apply_alpha_decay(sig, timeframe, self._setup_last_fire.get(key))

        trend_regime = float(features.get("trend_regime", 0.0))
        # Look up authority TF regime data for slow-clock gating (SIGINT-04).
        authority_tf = _REGIME_AUTHORITY_TF.get(timeframe, timeframe)
        regime_data = self._regime_cache.get(symbol, {}).get(authority_tf)

        # QUAL-09: Read KS drift penalty from in-process dict for this symbol/TF.
        drift_penalty = await self._read_drift_penalty(symbol, timeframe)

        # DAG pipeline: publish each signal to quality_gated topic (QualityGate stage entry).
        # The 6-stage DAG (QualityGate→RegimeGate→TODAdjuster→Calibrator→Ranker→WinnerSelector)
        # processes signals and emits the winner back on the winner topic.
        # _consume_winner_signals() receives winners and handles DB writes + downstream publish.
        if raw_signals and self._kafka_producer:
            _dag_meta = {
                "trend_regime": trend_regime,
                "regime_data": regime_data,
                "perf_weights": self._perf_weights,
                "drift_penalty": drift_penalty,
                "timeframe": timeframe,
                "symbol": symbol,
                "timestamp": timestamp.isoformat(),
                "bar_close_ts": bar_close_ts.isoformat() if bar_close_ts else None,
                "source": source,
                # Include features subset for DAG context
                "hmm_regime": features.get("hmm_regime"),
                "hmm_regime_prob": features.get("hmm_regime_prob"),
                "hmm_regime_duration": features.get("hmm_regime_duration"),
            }
            _quality_gated_topic = topic_quality_gated(self.env_name)
            for sig in raw_signals:
                dag_msg = {**sig, **_dag_meta}
                # Ensure direction and numeric fields are serializable
                dag_msg["direction"] = int(sig.get("direction", 0))
                dag_msg["confidence"] = float(sig.get("confidence", 0.0))
                try:
                    await self._kafka_producer.publish(
                        _quality_gated_topic,
                        dag_msg,
                        key=message_key(symbol, timeframe),
                    )
                except Exception as _dag_err:
                    self.logger.warning(
                        "DAG publish failed",
                        symbol=symbol,
                        timeframe=timeframe,
                        setup_plugin=sig.get("setup_plugin"),
                        error=str(_dag_err),
                    )
            self.logger.debug(
                "dag_signals_published",
                symbol=symbol,
                timeframe=timeframe,
                signal_count=len(raw_signals),
            )

        # Emit bar-to-signal latency metric even for DAG path
        signal_computed_at = datetime.now(tz=UTC) if source == "live" else None
        if source == "live" and bar_close_ts is not None and signal_computed_at is not None:
            BAR_TO_SIGNAL_LATENCY.labels(symbol=symbol, tf=timeframe).observe(
                (signal_computed_at - bar_close_ts).total_seconds()
            )

        elapsed_ms = (time.time() - calc_start) * 1000
        self.bars_processed_total.inc()
        self.calculation_duration_ms.set(elapsed_ms)
        self._total_bars += 1

        self.logger.debug(
            "Bar processed (DAG path)",
            symbol=symbol,
            timeframe=timeframe,
            signals_fired=len(raw_signals),
            calc_ms=round(elapsed_ms, 2),
        )


    async def _consume_winner_signals(self) -> None:
        """Consume winner signals from DAG pipeline and write to DB + publish downstream.

        Runs as a parallel async task alongside _process_loop(). Receives signals from
        WinnerSelector stage (pipeline.winner topic), creates LedgerEntry, writes to
        signal_ledger, and publishes to signals.aggregated for signal_lifecycle_service.

        Uses SignalStatus.PENDING (enum) not the raw string "pending" — CHECK constraint safe.
        """
        if not self._dag_winner_consumer:
            return
        try:
            async for _topic, _key, payload in self._dag_winner_consumer.messages():
                if self.shutdown_requested:
                    break
                try:
                    # WinnerSelector stage produces: {selected_signal, all_ranked,
                    # resolution_method, symbol, timeframe, timestamp, ...}
                    selected_signal = payload.get("selected_signal")
                    if not selected_signal:
                        # No winner this bar (no signals fired or all suppressed)
                        continue

                    symbol = str(payload.get("symbol", ""))
                    timeframe = str(payload.get("timeframe", ""))
                    if not symbol or not timeframe:
                        self.logger.warning(
                            "winner_missing_symbol_tf", payload_keys=list(payload.keys())
                        )
                        continue

                    # Parse timestamp
                    ts_raw = payload.get("timestamp", "")
                    try:
                        timestamp = datetime.fromisoformat(str(ts_raw))
                    except (ValueError, TypeError):
                        timestamp = datetime.now(tz=UTC)

                    signal_computed_at = datetime.now(tz=UTC)

                    # Build message for signals + signals.aggregated topics
                    sig = selected_signal
                    message: dict = {
                        k: str(v)
                        for k, v in sig.items()
                        if isinstance(v, (str, int, float, bool))
                    }
                    targets = sig.get("targets") or []
                    target_labels = sig.get("target_labels") or []
                    if targets:
                        message["profit_target"] = str(float(targets[0]))
                        if len(targets) > 1:
                            message["profit_target_2"] = str(float(targets[1]))
                        if len(targets) > 2:
                            message["profit_target_3"] = str(float(targets[2]))
                    message["target_labels"] = json.dumps(target_labels)
                    message["target_types"] = json.dumps(sig.get("target_types") or [])
                    # RR fields
                    entry_p = float(sig.get("entry_price", 0))
                    stop_p = float(sig.get("stop_loss", 0))
                    risk = abs(entry_p - stop_p)
                    if risk > 0 and targets:
                        message["risk_reward_ratio"] = str(
                            round(abs(float(targets[0]) - entry_p) / risk, 2)
                        )
                    message["timestamp"] = timestamp.isoformat()
                    message["symbol"] = symbol
                    message["timeframe"] = timeframe
                    message["signal_computed_at"] = signal_computed_at.isoformat()
                    # Generate once; reuse in message and LedgerEntry to avoid ID mismatch
                    _winner_signal_id = str(sig.get("signal_id", "") or uuid4())
                    message["signal_id"] = _winner_signal_id
                    message["was_selected"] = "1"
                    # Propagate cis_score if present from WinnerSelector stage
                    if payload.get("cis_score") is not None:
                        message["cis_score"] = str(payload["cis_score"])
                    msg_key = message_key(symbol, timeframe)

                    # Build LedgerEntry from winner signal for DB write
                    # Uses SignalStatus enum — respects Phase 39 CHECK constraints
                    direction = int(sig.get("direction", 0))
                    all_ranked = payload.get("all_ranked", [selected_signal])
                    entries: list[LedgerEntry] = []
                    for rank_idx, ranked_sig in enumerate(all_ranked, start=1):
                        _ranked_id = str(ranked_sig.get("signal_id") or "")
                        _is_winner = _ranked_id == _winner_signal_id or (
                            not _ranked_id
                            and ranked_sig.get("setup_plugin") == sig.get("setup_plugin")
                            and ranked_sig.get("regime_eligible", True)
                        )
                        _status = (
                            SignalStatus.PENDING
                            if ranked_sig.get("regime_eligible", True)
                            else SignalStatus.REGIME_SUPPRESSED
                        )
                        _direction = int(ranked_sig.get("direction", 0))
                        entries.append(
                            LedgerEntry(
                                signal_id=_ranked_id or str(uuid4()),
                                timestamp=timestamp,
                                symbol=symbol,
                                timeframe=timeframe,
                                setup_plugin=str(ranked_sig.get("setup_plugin", "unknown")),
                                signal_type=str(ranked_sig.get("signal_type", "unknown")),
                                direction=_direction,
                                entry_price=float(ranked_sig.get("entry_price", 0.0)),
                                stop_loss=float(ranked_sig.get("stop_loss", 0.0)),
                                targets=[
                                    float(t) for t in (ranked_sig.get("targets") or [])
                                ],
                                confidence=float(ranked_sig.get("confidence", 0.0)),
                                confluence_score=float(
                                    ranked_sig.get("confluence_score", 0.0)
                                ),
                                regime_context=str(ranked_sig.get("regime_context", "")),
                                supporting_factors=list(
                                    ranked_sig.get("supporting_factors", [])
                                ),
                                was_selected=_is_winner,
                                num_signals_bar=len(all_ranked),
                                num_agreeing=int(payload.get("num_agreeing", 0)),
                                num_conflicting=int(payload.get("num_conflicting", 0)),
                                resolution_method=str(
                                    payload.get("resolution_method", "dag_winner")
                                ),
                                composite_rank=rank_idx,
                                status=_status,
                                feature_ts=timestamp,
                                feature_tf=timeframe,
                                signal_computed_at=signal_computed_at,
                            )
                        )

                    # Plugin-level shadow mode (IS_SHADOW=True on plugin class)
                    for entry in entries:
                        plugin_instance = registry.patterns.get(entry.setup_plugin)
                        if plugin_instance is not None and getattr(
                            plugin_instance, "IS_SHADOW", False
                        ):
                            entry.is_shadow = True

                    # Gate check: suppress re-fires and direction flips
                    _winner_direction = direction
                    if self._check_gate(symbol, timeframe, _winner_direction, timestamp):
                        self.logger.debug(
                            "winner_signal_gated",
                            symbol=symbol,
                            timeframe=timeframe,
                            direction=_winner_direction,
                        )
                        continue

                    # STREAM PUBLISH FIRST (hot tier)
                    published_signal = False
                    if self._kafka_producer:
                        try:
                            await self._kafka_producer.publish(
                                topic_signals(self.env_name), message, key=msg_key
                            )
                            await self._kafka_producer.publish(
                                topic_signals_aggregated(self.env_name), message, key=msg_key
                            )
                            published_signal = True
                        except Exception as _pub_err:
                            self.logger.warning(
                                "winner_kafka_publish_failed",
                                symbol=symbol,
                                timeframe=timeframe,
                                error=str(_pub_err),
                            )

                    if published_signal:
                        self._update_gate(
                            symbol, timeframe, _winner_direction, timestamp,
                            message["signal_id"]
                        )
                        _pub_plugin = sig.get("setup_plugin", "")
                        if _pub_plugin:
                            _decay_key = (symbol, timeframe, _pub_plugin, _winner_direction)
                            self._setup_last_fire[_decay_key] = {"bars_since": 0}

                    # DB INSERT (cold tier) — atomic signal_ledger + signal_features write
                    if entries and self.db_manager:
                        try:
                            # Pass empty features dict — winner carries its own data
                            await insert_signals_with_features(
                                self.db_manager.pool, entries, {}
                            )
                            selected_count = sum(1 for e in entries if e.was_selected)
                            self.signals_generated_total.inc(len(entries))
                            self.signals_selected_total.inc(selected_count)
                            self._total_signals += len(entries)
                        except Exception as _db_err:
                            self.logger.error(
                                "winner_db_write_failed",
                                symbol=symbol,
                                timeframe=timeframe,
                                error=str(_db_err),
                            )

                    self.logger.debug(
                        "winner_signal_processed",
                        symbol=symbol,
                        timeframe=timeframe,
                        setup_plugin=sig.get("setup_plugin"),
                        published=published_signal,
                        entries_count=len(entries),
                    )

                except asyncio.CancelledError:
                    break
                except Exception as _e:
                    self.logger.exception(
                        "winner_consumer_message_error", error=str(_e)
                    )
        except asyncio.CancelledError:
            pass
        except Exception as _outer_err:
            self.logger.warning(
                "winner_consumer_loop_failed", error=str(_outer_err)
            )

    async def _process_single_message(
        self,
        symbol: str,
        timeframe: str,
        fields: dict,
        stream_name: str,
        message_id: bytes | None,
    ) -> bool:
        try:
            event = _parse_intelligence_event(fields)
            if event is None:
                # Malformed or missing event — ack and skip (do not crash)
                return True

            # Update regime cache for slow-clock gating (SIGINT-04).
            # Cache the HMM regime from every IntelligenceEvent so _process_bar()
            # can look up the authority TF (higher-TF) regime when gating signals.
            if event.smc is not None and event.smc.hmm_regime is not None:
                self._regime_cache[symbol][timeframe] = {
                    "hmm_regime": event.smc.hmm_regime,
                    "hmm_regime_prob": event.smc.hmm_regime_prob or 0.0,
                    "hmm_regime_duration": event.smc.hmm_regime_duration or 0,
                }

            timestamp = event.ts
            bar = {
                "open": event.bar.o,
                "high": event.bar.h,
                "low": event.bar.l,
                "close": event.bar.c,
                "volume": event.bar.v,
            }
            features = _build_features_from_event(event)

            # Phase 041: Cache 1h intel for HTF injection into short-TF frames
            if timeframe == "1h":
                self._htf_intel_cache[f"{symbol}:1h"] = features

            # Append typed BarMessage to BarHistory (D-43, D-45)
            # OHLCVBar uses SHORT field names: o, h, l, c, v
            bar_msg = BarMessage(
                ts=event.ts,
                symbol=symbol,
                tf=timeframe,
                open=event.bar.o,
                high=event.bar.h,
                low=event.bar.l,
                close=event.bar.c,
                volume=event.bar.v,
                source="ibkr_named",
                session_type=event.session_type,
                gap_preceding=False,
            )
            self._bar_history.append(bar_msg)
            key = f"{symbol}:{timeframe}"
            self._df_cache[key] = None

            frames = {
                "main": self._get_df(symbol, timeframe),
                "features": features,
                "timeframe": timeframe,  # Phase 041: enables TF guard in VWAP/session plugins
            }

            # Phase 037: Inject cross-asset frames for EQ_INDEX symbols when enabled
            if self._cross_asset_enabled and resolve_eq_index_base(symbol) is not None:
                frames["cross_asset"] = self._cross_asset_cache.get(
                    timeframe, {"ready": False}
                )
                frames["cross_asset_5m"] = self._cross_asset_cache.get(
                    "5m", {"ready": False}
                )

            # Phase 041: Inject HTF 1h context for short-TF bars
            if timeframe in ("1m", "5m", "15m"):
                frames["htf_1h"] = self._htf_intel_cache.get(f"{symbol}:1h", {})

            # Phase 42: inject pattern_reliability weights for CandlestickPatternSetup
            frames["pattern_weights"] = await _load_pattern_reliability_weights(self.db_manager)

            await self._process_bar(
                symbol,
                timeframe,
                bar,
                features,
                frames,
                timestamp,
                bar_close_ts=event.bar_close_ts,
                source=event.source,
            )
            return True

        except Exception as e:
            self.logger.error(
                "Error processing message",
                symbol=symbol,
                timeframe=timeframe,
                error=str(e),
            )
            self.error_count_total.inc()
            self._error_count += 1
            return False

    async def _process_loop(self) -> None:
        """Consume from intelligence, market.ticks, and optionally system.events topics."""
        if not self._kafka_consumer:
            return
        _intel_topic = topic_intelligence(self.env_name)
        _ticks_topic = topic_market_ticks(self.env_name)
        _sys_events_topic = topic_system_events(self.env_name)
        _cross_asset_topic = topic_cross_asset(self.env_name) if self._cross_asset_enabled else ""
        try:
            async for topic, key, payload in self._kafka_consumer.messages():
                if self.shutdown_requested:
                    break
                try:
                    if topic == _sys_events_topic:
                        await self._handle_roll_event(payload)
                    elif self._cross_asset_enabled and topic == _cross_asset_topic:
                        # Cache latest cross-asset snapshot by timeframe
                        try:
                            tf = payload.get("tf", "")
                            if tf in _CROSS_ASSET_VALID_TFS and payload.get("ready"):
                                self._cross_asset_cache[tf] = payload
                        except Exception as _xa_err:
                            self.logger.warning("cross_asset_parse_failed", error=str(_xa_err))
                    elif topic == _intel_topic:
                        # key = "SYMBOL:TF"
                        if key:
                            parts = key.split(":", 1)
                            if len(parts) == 2:
                                symbol, timeframe = parts[0], parts[1]
                            else:
                                symbol = parts[0]
                                timeframe = payload.get("timeframe", "")
                        else:
                            symbol = payload.get("symbol", "")
                            timeframe = payload.get("timeframe", "")
                        if symbol and timeframe:
                            await self._process_single_message(
                                symbol, timeframe, payload, topic, None
                            )
                    elif topic == _ticks_topic:
                        # key = "SYMBOL"
                        symbol = key or payload.get("symbol", "")
                        if symbol:
                            await self._handle_ticks_message(symbol, payload)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    self.logger.error("Error in processing loop", error=str(e))
                    self.error_count_total.inc()
                    self._error_count += 1
        except asyncio.CancelledError:
            pass

    async def _health_monitor_loop(self) -> None:
        while self.running and not self.shutdown_requested:
            try:
                uptime = int((datetime.now(tz=UTC) - self.start_time).total_seconds())
                self.service_uptime_seconds.set(uptime)
                interval = self.config["service"]["health_check_interval"]
                self.logger.info(
                    "Health check",
                    uptime=uptime,
                    bars_processed=self._total_bars,
                    signals_generated=self._total_signals,
                    errors=self._error_count,
                )
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in health monitor", error=str(e))
                await asyncio.sleep(5)

    async def _load_perf_weights(self) -> None:
        """Load perf multiplier dict from setup_performance DB table.

        Phase 30: Replaces Redis GET setup_performance:weights with direct DB query.
        Reads win_rate and avg_pnl_r for setups with sample_size >= 30 and builds
        the perf_weights dict in the same format as the old Redis-cached version.
        """
        if not self.db_manager:
            self.logger.debug("_load_perf_weights: no db_manager — skipping")
            return
        query = """
            SELECT setup_plugin, win_rate, avg_pnl_r
            FROM setup_performance
            WHERE sample_size >= 30
        """  # noqa: S608
        try:
            async with self.db_manager.pool.acquire() as conn:
                rows = await conn.fetch(query)
            if not rows:
                self.logger.debug("Perf weights: no eligible setups in setup_performance")
                return
            # Build perf_weights dict in the same format as the old Redis-cached version.
            # Rank by avg_pnl_r descending to compute perf_multiplier in [0.5, ~1.5].
            n = len(rows)
            sorted_rows = sorted(rows, key=lambda r: float(r["avg_pnl_r"] or 0), reverse=True)
            weights: dict[str, float] = {}
            for rank, row in enumerate(sorted_rows):
                multiplier = 0.5 + ((n - 1 - rank) / n) if n > 1 else 1.0
                weights[row["setup_plugin"]] = round(multiplier, 4)
            self._perf_weights = weights
            self.logger.debug("Perf weights loaded from DB", n_setups=len(weights))
        except Exception as exc:
            self.logger.warning("Failed to load perf weights from DB", error=str(exc))

    async def _refresh_drift_penalties_from_db(self) -> None:
        """QUAL-09: Load KS drift penalties from drift_state DB table into _drift_penalties dict.

        Phase 30: Replaces per-bar Redis GET with a 4h batch refresh from DB.
        Called at startup and every 4h by _run_refresh_loop("drift_penalties",...).

        Only reads KS rows (tf != '_cusum'). CUSUM rows are for setup_performance_updater.
        """
        if not self.db_manager:
            self.logger.debug("_refresh_drift_penalties_from_db: no db_manager — skipping")
            return
        query = """
            SELECT symbol, tf, ks_severity
            FROM drift_state
            WHERE tf != '_cusum'
        """  # noqa: S608
        try:
            async with self.db_manager.pool.acquire() as conn:
                rows = await conn.fetch(query)
            new_penalties: dict[tuple[str, str], float] = {}
            for row in rows:
                severity = row["ks_severity"]
                new_penalties[(row["symbol"], row["tf"])] = DRIFT_PENALTIES.get(severity, 1.0)
            self._drift_penalties = new_penalties
            self.logger.debug("drift_penalties refreshed from DB", n_entries=len(new_penalties))
        except Exception as exc:
            self.logger.warning("Failed to refresh drift_penalties from DB", error=str(exc))

    async def _run_refresh_loop(
        self,
        name: str,
        interval_s: int | float,
        fn: Callable[[], Awaitable[None]],
        backoff_s: int = 30,
    ) -> None:
        """Shared refresh loop: sleep interval_s, call fn, repeat until shutdown.

        On exception, sleeps backoff_s before retrying to prevent spin on persistent errors.
        """
        while self.running and not self.shutdown_requested:
            try:
                try:
                    await asyncio.wait_for(
                        self.shutdown_event.wait(), timeout=interval_s
                    )
                    break  # shutdown_event was set
                except TimeoutError:
                    pass
                if self.shutdown_requested:
                    break
                await fn()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.logger.error(f"{name} refresh loop error", error=str(exc))
                await asyncio.sleep(backoff_s)

    async def _read_drift_penalty(self, symbol: str, timeframe: str) -> float:
        """QUAL-09: Read KS drift penalty from in-process _drift_penalties dict.

        Phase 30: No longer reads Redis. Uses dict populated by _refresh_drift_penalties_from_db().
        Falls back to 1.0 (no penalty) when no entry exists for this symbol/TF.
        """
        return self._drift_penalties.get((symbol, timeframe), 1.0)

    async def _load_cis_weights_from_db(self) -> None:
        """Load per-cluster learned weights from cis_weights table.

        Only rows with sample_size >= 100 are considered.
        Updates self._cis_scorer with global weights when available.
        Falls back to bootstrap on empty result or DB error.
        """
        if self.db_manager is None:
            return
        try:
            rows = await self.db_manager.execute_query(
                """
                SELECT DISTINCT ON (asset_cluster, timeframe)
                    asset_cluster, timeframe, version, sample_size,
                    trend_w, momentum_w, structure_w, pattern_w,
                    institutional_w, regime_w
                FROM cis_weights
                WHERE sample_size >= 100
                ORDER BY asset_cluster, timeframe, version DESC
                """
            )
            if not rows:
                self.logger.info(
                    "No learned CIS weights with sample_size >= 100 — using bootstrap"
                )
                return
            for row in rows:
                weights = {
                    "trend": row["trend_w"],
                    "momentum": row["momentum_w"],
                    "structure": row["structure_w"],
                    "pattern": row["pattern_w"],
                    "institutional": row["institutional_w"],
                    "regime": row["regime_w"],
                }
                cluster = row["asset_cluster"]
                tf = row["timeframe"]
                self._cis_weights_cache[(cluster, tf)] = (weights, row["version"])
                self.logger.info(
                    "Loaded weights from DB",
                    cluster=cluster,
                    tf=tf,
                    version=row["version"],
                    sample_size=row["sample_size"],
                )
            # Update the global scorer with global/global weights when available.
            # Phase 35 will extend this to per-cluster routing.
            global_key = ("global", "global")
            if global_key in self._cis_weights_cache:
                w, v = self._cis_weights_cache[global_key]
                self._cis_scorer.update_weights(w, v)
        except Exception as exc:
            self.logger.warning(
                "CIS weights refresh error — keeping current weights", error=str(exc)
            )

    async def _load_calibration_curves_from_db(self) -> None:
        """Load isotonic calibration curves from confidence_calibration table every 30 min."""
        if self.db_manager is None:
            return
        try:
            rows = await self.db_manager.execute_query(
                "SELECT plugin_name, timeframe, breakpoints, values "
                "FROM confidence_calibration WHERE sample_size >= 100"
            )
            new_cache: dict[tuple[str, str], tuple[np.ndarray, np.ndarray]] = {}
            for row in rows:
                key = (row["plugin_name"], row["timeframe"])
                new_cache[key] = (
                    np.array(row["breakpoints"], dtype=np.float64),
                    np.array(row["values"], dtype=np.float64),
                )
            self._calibration_curves = new_cache
            self.logger.debug("calibration_curves_loaded", n_curves=len(new_cache))
        except Exception as exc:
            self.logger.warning("calibration_curves_refresh_error", error=str(exc))

    async def _load_tod_multipliers_from_db(self) -> None:
        """Load Bayesian-smoothed TOD multipliers per (regime_type, timeframe, hour_et).

        Uses regime_type_at_fire column (added by migration 038). Pre-Phase-35 rows
        have NULL and are bucketed as 'any' via COALESCE.
        """
        if self.db_manager is None:
            return
        try:
            rows = await self.db_manager.execute_query(
                """
                SELECT
                    COALESCE(regime_type_at_fire, 'any') AS regime_type,
                    timeframe,
                    EXTRACT(HOUR FROM timestamp AT TIME ZONE 'America/New_York')::int AS hour_et,
                    COUNT(*)::float AS n,
                    SUM(CASE WHEN outcome IN ('target_1','target_1_2','target_full')
                             THEN 1 ELSE 0 END)::float AS wins
                FROM signal_ledger
                WHERE outcome IS NOT NULL AND is_shadow = FALSE
                GROUP BY 1, 2, 3
                """
            )
            # Compute overall win rate as baseline (prior denominator) — single pass
            total_n = total_wins = 0.0
            for r in rows:
                total_n += r["n"]
                total_wins += r["wins"]
            global_win_rate = (total_wins / total_n) if total_n > 0 else 0.5
            global_win_rate = max(0.01, global_win_rate)  # avoid div-by-zero

            new_multipliers: dict = {}
            for row in rows:
                regime_type = str(row["regime_type"])
                timeframe = str(row["timeframe"])
                hour_et = int(row["hour_et"])
                n = float(row["n"])
                wins = float(row["wins"])
                empirical_wr = (wins / n) if n > 0 else global_win_rate
                empirical_ratio = empirical_wr / global_win_rate

                prior_ratio = _TOD_SESSION_PRIORS.get((regime_type, hour_et), 1.0)
                raw_mult = (_TOD_ALPHA * prior_ratio + n * empirical_ratio) / (_TOD_ALPHA + n)
                clamped = max(_TOD_CLAMP[0], min(_TOD_CLAMP[1], raw_mult))
                new_multipliers[(regime_type, timeframe, hour_et)] = round(clamped, 4)

            # Cold-start: if no DB data yet, seed from session priors so warm-start
            # intent of _TOD_SESSION_PRIORS is fulfilled before signals accumulate.
            if not new_multipliers:
                for (regime_t, hour_et), prior_ratio in _TOD_SESSION_PRIORS.items():
                    clamped = max(_TOD_CLAMP[0], min(_TOD_CLAMP[1], prior_ratio))
                    for tf in ("1m", "5m", "15m", "1h"):
                        new_multipliers[(regime_t, tf, hour_et)] = round(clamped, 4)
            self._tod_multipliers = new_multipliers
            self.logger.debug("tod_multipliers_loaded", n_cells=len(new_multipliers))
        except Exception as exc:
            self.logger.warning("tod_multipliers_refresh_error", error=str(exc))

    async def start(self) -> None:
        self.logger.info("Starting Signal Generator Service", config=self.config["service"])
        try:
            await self._connect_database()
            await self._setup_kafka_clients()
            self.running = True
            # Load perf weights at startup so first bar already has weights
            await self._load_perf_weights()
            # Load drift penalties at startup from drift_state DB table
            await self._refresh_drift_penalties_from_db()
            # Load CIS weights at startup — first bar uses learned weights immediately
            await self._load_cis_weights_from_db()
            # Phase 35: Load calibration curves and TOD multipliers at startup
            await self._load_calibration_curves_from_db()
            await self._load_tod_multipliers_from_db()
            tasks = [
                asyncio.create_task(self._process_loop()),
                asyncio.create_task(self._health_monitor_loop()),
                asyncio.create_task(self._run_refresh_loop("perf_weights", 3600, self._load_perf_weights)),
                asyncio.create_task(self._run_refresh_loop("drift_penalties", 14400, self._refresh_drift_penalties_from_db)),
                asyncio.create_task(self._resolution_listener_loop()),
                asyncio.create_task(self._run_refresh_loop("cis_weights", 1800, self._load_cis_weights_from_db)),
                asyncio.create_task(self._run_refresh_loop("calibration_curves", 1800, self._load_calibration_curves_from_db)),
                asyncio.create_task(self._run_refresh_loop("tod_multipliers", 14400, self._load_tod_multipliers_from_db)),
                # DAG pipeline: consume winners from WinnerSelector stage for DB writes
                asyncio.create_task(self._consume_winner_signals()),
            ]
            self.logger.info("Signal Generator Service started")
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            self.logger.error("Failed to start signal generator", error=str(e))
            raise
        finally:
            await self.stop()


async def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Signal Generator Service")
    parser.add_argument("--config", help="Configuration file path")
    args = parser.parse_args()

    # Register plugins first so the validator sees a populated registry
    register_all_plugins()

    # Run plugin validation before starting service
    validator = PluginValidator()
    try:
        validator.validate_all()
        print("✅ Plugin validation passed")
    except RuntimeError as e:
        print(f"❌ Plugin validation failed: {e}")
        sys.exit(1)

    svc = SignalGeneratorService(args.config)
    try:
        await svc.start()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    asyncio.run(main())
