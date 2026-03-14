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
import os
import signal
import sys
import time
from collections import defaultdict, deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pandas as pd
import structlog
from pydantic import ValidationError

from src.config.settings import Settings, get_active_contracts
from src.core.database_manager import DatabaseManager
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.service_utils import TF_SECONDS, min_bars_for_tf, setup_service_logging
from src.core.stream_keys import (
    message_key,
    topic_intelligence,
    topic_intelligence_i7,
    topic_market_ticks,
    topic_signals,
    topic_signals_aggregated,
)
from src.intelligence.plugins import registry
from src.intelligence.register_plugins import TIER_I7, register_all_plugins
from src.intelligence.schemas import IntelligenceEvent
from src.intelligence.trading.aggregator import AggregatedResult, aggregate
from src.intelligence.trading.signal_ledger import LedgerEntry, insert_signals
from src.intelligence.trading.trade_framer import frame_trade
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

# Minimum bars between published signals per timeframe. Prevents condition
# re-fires (same setup firing every bar while condition persists).
# Day-trading focus: 1m=3 bars (3 min cooldown), higher TFs=2 bars.
MIN_BARS_BETWEEN_SIGNALS: dict[str, int] = {"1m": 3, "5m": 2, "15m": 2, "1h": 2}
# TF_SECONDS imported from src.core.service_utils (shared with signal_lifecycle_service)

# QUAL-04: per-setup cooldown — prevents same setup/direction recycling within N bars.
# Keyed by (symbol, tf, setup_plugin, direction); independent of the bar-level _signal_gate.
# Day-trading focus: 1m=3 bars (3 min), higher TFs=2 bars (matches MIN_BARS_BETWEEN_SIGNALS pattern).
_SIGNAL_COOLDOWN_BARS: dict[str, int] = {"1m": 3, "5m": 2, "15m": 2, "1h": 2}

# QUAL-02: alpha decay half-life — bars after which a repeated same-setup/direction signal
# has its confidence multiplied by max(0.0, 1.0 - bars_since / half_life).
# Starting values — replace with learned values after 90 days of outcome data.
# Regress half-life against Sharpe per TF when data justifies it.
ALPHA_HALF_LIFE_BARS: dict[str, int] = {"1m": 10, "5m": 6, "15m": 4, "1h": 3}

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

MARKET_CONTEXT_KEYS: tuple[str, ...] = (
    "trend_regime",
    "volatility_regime",
    "trend_confidence",
    "atr_14",
    "rsi_14",
    "ctf_score",
    "swing_pattern",
    "trend_strength",
    "volatility_percentile",
    "hmm_regime_state",
)

logger = structlog.get_logger(__name__)


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


def build_ledger_entries(
    result: AggregatedResult,
    symbol: str,
    timeframe: str,
    timestamp: datetime,
    features: dict[str, Any],
    signal_computed_at: datetime | None = None,
    quote: dict[str, float | None] | None = None,
    determined_at: datetime | None = None,
) -> list[LedgerEntry]:
    """Build LedgerEntry list from an AggregatedResult."""
    if not result.all_ranked:
        return []

    market_ctx = {k: features.get(k, None) for k in MARKET_CONTEXT_KEYS
                  if features.get(k) is not None}

    _quote = quote or {}
    entries = []
    for sig in result.all_ranked:
        rank = sig.get("composite_rank", 99)
        is_regime_eligible = sig.get("regime_eligible", True)
        # Regime-suppressed signals persist to ledger for observability, not selection.
        # was_selected is always False for regime-suppressed signals.
        was_selected = (rank == 1 and result.selected_signal is not None and is_regime_eligible)
        # Determine status based on regime eligibility
        entry_status = "pending" if is_regime_eligible else "regime_suppressed"
        direction = int(sig.get("direction", 0))
        zone_low = sig.get("entry_zone_low") or None
        zone_high = sig.get("entry_zone_high") or None
        ask = _quote.get("ask")
        bid = _quote.get("bid")
        market_price = ask if direction == 1 else bid
        entries.append(LedgerEntry(
            signal_id=str(uuid4()),
            timestamp=timestamp,
            symbol=symbol,
            timeframe=timeframe,
            setup_plugin=sig.get("setup_plugin", "unknown"),
            signal_type=sig.get("signal_type", "unknown"),
            direction=direction,
            entry_price=float(sig.get("entry_price", 0.0)),
            stop_loss=float(sig.get("stop_loss", 0.0)),
            targets=[float(t) for t in sig.get("targets", [])],
            confidence=float(sig.get("confidence", 0.0)),
            confluence_score=float(sig.get("confluence_score", 0.0)),
            regime_context=str(sig.get("regime_context", "")),
            supporting_factors=list(sig.get("supporting_factors", [])),
            was_selected=was_selected,
            num_signals_bar=result.num_signals_fired,
            num_agreeing=result.num_agreeing,
            num_conflicting=result.num_conflicting,
            resolution_method=result.resolution_method,
            composite_rank=rank,
            market_context=market_ctx,
            status=entry_status,
            feature_ts=timestamp,
            feature_tf=timeframe,
            cis_score=result.cis_score,
            bucket_scores=result.bucket_scores,
            weights_version=result.weights_version,
            signal_quality=None,
            signal_computed_at=signal_computed_at,
            # Institutional lifecycle fields
            determined_at=determined_at,
            ask_at_signal=ask,
            bid_at_signal=bid,
            market_price_at_signal=market_price,
            entry_zone_low=zone_low,
            entry_zone_high=zone_high,
            zone_valid_at_signal=_is_zone_valid(direction, market_price, zone_low, zone_high),
        ))
    return entries


def _build_i7_payload(
    result: AggregatedResult,
    timestamp: datetime,
    symbol: str,
    timeframe: str,
) -> dict:
    """Build the intelligence_i7 stream message from an AggregatedResult.

    Publishes all_ranked as a compact JSON list. is_winner flags the aggregator's
    selected signal so the ML layer can learn from both selected and counterfactual
    signals.
    """
    selected_plugin = None
    if result.selected_signal is not None:
        selected_plugin = result.selected_signal.get("setup_plugin")

    signals_out = []
    for sig in result.all_ranked:
        is_winner = (
            sig.get("composite_rank") == 1
            and selected_plugin is not None
            and sig.get("setup_plugin") == selected_plugin
            and sig.get("regime_eligible", True)
        )
        targets = sig.get("targets") or []
        signals_out.append({
            "setup_type": sig.get("signal_type", "unknown"),
            "confidence": float(sig.get("confidence", 0.0)),
            "direction": int(sig.get("direction", 0)),
            "regime_eligible": bool(sig.get("regime_eligible", True)),
            "suppression_reason": sig.get("suppression_reason"),
            "entry": float(sig.get("entry_price", 0.0)),
            "stop": float(sig.get("stop_loss", 0.0)),
            "target": float(targets[0]) if targets and targets[0] is not None else None,
            "composite_rank": int(sig.get("composite_rank", 99)),
            "is_winner": is_winner,
        })

    return {
        "ts": timestamp.isoformat(),
        "symbol": symbol,
        "tf": timeframe,
        "data": json.dumps(signals_out),
    }


class SignalGeneratorService:
    """Execute I7 setup plugins, aggregate signals, and persist to signal_ledger."""

    # Class-level defaults — overridden per-instance in __init__.
    # Required by the __new__ test pattern (CLAUDE.md): attributes accessed via
    # hasattr() on bare __new__ instances must be defined at class level.
    _perf_weights: dict[str, float] = {}  # noqa: RUF012
    _drift_penalties: dict[tuple[str, str], float] = {}  # noqa: RUF012

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

        settings = Settings()
        self.env_name = settings.env_name or ""
        self.env_prefix = f"{settings.env_name}:" if settings.env_name else ""
        self._kafka_bootstrap = getattr(settings, "kafka_bootstrap_servers", "localhost:19092")

        # In-process live quotes dict: symbol → {"bid": float, "ask": float}
        # Populated by ticks topic handler. Replaces Redis HGETALL for price:SYMBOL:latest.
        self._live_quotes: dict[str, dict] = {}

        self.bar_history: dict[str, deque] = defaultdict(lambda: deque(maxlen=200))
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
        # _perf_weights_refresh_loop(). Empty dict = neutral (all multipliers=1.0).
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
                "symbols": get_active_contracts(_settings),
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

    def _update_gate(self, symbol: str, tf: str, direction: int, timestamp: datetime, signal_id: str) -> None:
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
                async for _topic, key, payload in resolution_consumer.messages():
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

    async def _seed_bar_history_from_db(self) -> None:
        """Seed bar_history from intelligence_features to eliminate warmup delay on restart.

        Queries min_bars_for_tf(tf) recent bars per (symbol, tf) from
        intelligence_features table and populates bar_history dict.

        Gracefully degrades if DB unavailable: logs WARNING and proceeds
        with empty bar_history (live warmup fallback).
        """
        import asyncio

        if not self.db_manager:
            self.logger.warning("DB seed failed - falling back to live warmup", reason="no db_manager")
            return

        active_contracts = get_active_contracts()
        timeframes = self.config["service"]["timeframes"]
        # Pre-compute min_bars per TF (pure dict lookup, same for all symbols)
        min_bars_per_tf = {tf: min_bars_for_tf(tf) for tf in timeframes}
        seeded_count = 0

        async def _fetch_one(symbol: str, tf: str) -> tuple[str, str, list]:
            min_bars = min_bars_per_tf[tf]
            query = f"""
                SELECT ts, bar
                FROM intelligence_features
                WHERE symbol = $1 AND tf = $2
                ORDER BY ts DESC
                LIMIT {min_bars}
            """
            result = await self.db_manager.execute_query(query, symbol, tf)
            return symbol, tf, result or []

        try:
            tasks = [
                _fetch_one(symbol, tf)
                for symbol in active_contracts
                for tf in timeframes
            ]
            results = await asyncio.gather(*tasks)

            for symbol, tf, rows in results:
                if not rows:
                    continue
                key = f"{symbol}:{tf}"
                # DB returns DESC (newest first); reverse to append oldest→newest
                for row in reversed(rows):
                    bar_json = row["bar"]
                    self.bar_history[key].append({
                        "open": bar_json.get("o"),
                        "high": bar_json.get("h"),
                        "low": bar_json.get("l"),
                        "close": bar_json.get("c"),
                        "volume": bar_json.get("v"),
                        "timestamp": row["ts"],
                    })
                    seeded_count += 1

            self.logger.info(
                "Seeded bar_history",
                seeded_count=seeded_count,
                symbols_count=len(active_contracts),
                tfs_count=len(timeframes),
            )

        except Exception as e:
            self.logger.warning("DB seed failed - falling back to live warmup", error=str(e))
            # bar_history remains empty, service proceeds with live warmup

    async def _handle_ticks_message(self, symbol: str, payload: dict) -> None:
        """KAFKA-06: Update _live_quotes with latest tick for symbol.

        Called when a message arrives on the market.ticks topic.
        Key is SYMBOL (no TF). Keeps only the latest tick per symbol.
        """
        self._live_quotes[symbol] = payload

    async def _setup_kafka_clients(self) -> None:
        """Initialize Kafka consumer (intelligence + ticks) and producer (signals)."""
        self._kafka_consumer = KafkaConsumerClient(
            topic_intelligence(self.env_name),
            topic_market_ticks(self.env_name),
            bootstrap_servers=self._kafka_bootstrap,
            group_id="signal_generator_group",
            auto_offset_reset="latest",
        )
        await self._kafka_consumer.start()
        self.logger.info("Kafka consumer started", topics=[
            topic_intelligence(self.env_name),
            topic_market_ticks(self.env_name),
        ])

        self._kafka_producer = KafkaProducerClient(self._kafka_bootstrap)
        await self._kafka_producer.start()
        self.logger.info("Kafka producer started")

    async def stop(self) -> None:
        self.logger.info("Stopping Signal Generator Service")
        self.running = False
        self.shutdown_requested = True
        self.shutdown_event.set()
        if self._kafka_consumer:
            await self._kafka_consumer.stop()
        if self._kafka_producer:
            await self._kafka_producer.stop()
        if self.db_manager:
            await self.db_manager.close()
        self.logger.info("Signal Generator Service stopped")

    def _get_df(self, key: str) -> pd.DataFrame:
        if self._df_cache.get(key) is None:
            self._df_cache[key] = pd.DataFrame(list(self.bar_history[key]))
        return self._df_cache[key]

    def _run_setup_plugins(self, frames: dict[str, Any]) -> list[dict]:
        """Run all I7 setup plugins and return only directional signals.

        Each signal dict is tagged with regime_type from the plugin attribute
        (Option B from RESEARCH.md — tag at plugin execution, keeps aggregator stateless).
        """
        signals = []
        for name in I7_PLUGINS:
            t0 = time.time()
            try:
                plugin = registry.get_pattern(name)
                result = plugin.compute_full(frames)
                elapsed = time.time() - t0
                if result and result.get("direction", 0) != 0:
                    result["setup_plugin"] = name
                    # Tag with regime_type from plugin attribute for slow-clock gate
                    result["regime_type"] = getattr(plugin, "regime_type", "any")
                    signals.append(result)
                    record_plugin_execution(name, "", "", elapsed, "success", "I7")
                else:
                    record_plugin_execution(name, "", "", elapsed, "no_signal", "I7")
            except Exception as e:
                self.logger.warning("I7 plugin failed", plugin=name, error=str(e))
                record_plugin_execution(name, "", "", time.time() - t0, "error", "I7")
        return signals

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

        raw_signals = self._run_setup_plugins(frames)
        # QUAL-04: per-setup cooldown — strip same setup/direction within N bars.
        # Runs before aggregation so blocked signals never enter alpha decay path.
        raw_signals = self._filter_setup_cooldown(symbol, timeframe, raw_signals, timestamp)

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
        # regime_data is None if authority TF not yet seen → aggregate() skips gate.
        authority_tf = _REGIME_AUTHORITY_TF.get(timeframe, timeframe)
        regime_data = self._regime_cache.get(symbol, {}).get(authority_tf)

        # QUAL-09: Read KS drift penalty from Redis for this symbol/TF.
        # One Redis GET per bar evaluation — negligible overhead.
        drift_penalty = await self._read_drift_penalty(symbol, timeframe)

        result = aggregate(
            raw_signals,
            trend_regime=trend_regime,
            features=features,
            regime_data=regime_data,
            perf_weights=self._perf_weights,
            drift_penalty=drift_penalty,
        )

        # Apply structural trade framing to the winning signal
        if result.selected_signal:
            atr = float(features.get("atr_14") or 0.0)
            sig = result.selected_signal
            frame = frame_trade(
                setup_type=sig.get("signal_type", ""),
                direction=int(sig.get("direction", 1)),
                entry=float(sig.get("entry_price", 0.0)),
                features=features,
                atr=atr,
            )
            if not frame.viable:
                self.logger.info(
                    "Signal filtered: RR gate",
                    symbol=symbol,
                    timeframe=timeframe,
                    signal_type=sig.get("signal_type"),
                    reason=frame.rejection_reason,
                )
                result = AggregatedResult(
                    selected_signal=None,
                    all_ranked=result.all_ranked,
                    resolution_method="rr_filtered",
                    num_signals_fired=result.num_signals_fired,
                    num_agreeing=result.num_agreeing,
                    num_conflicting=result.num_conflicting,
                )
            else:
                result.selected_signal.update({
                    "entry_price":    frame.entry,
                    "entry_type":     frame.entry_type,
                    "stop_loss":      frame.stop,
                    "stop_type":      frame.stop_type,
                    "targets":        [t.price for t in frame.targets],
                    "target_labels":  [t.label for t in frame.targets],
                    "target_types":   [t.level_type for t in frame.targets],
                    "rr_t1":          frame.rr_t1,
                    "rr_t2":          frame.rr_t2,
                    "rr_t3":          frame.rr_t3,
                    "framing_method": frame.method,
                    "entry_zone_low":  frame.zone_low,
                    "entry_zone_high": frame.zone_high,
                })

        signal_computed_at = datetime.now(tz=UTC) if source == "live" else None
        determined_at = signal_computed_at  # same wall-clock snapshot

        # Fetch live quote for institutional fields from in-process dict (KAFKA-06)
        live_quote: dict[str, float | None] = {"bid": None, "ask": None}
        if source == "live":
            live_quote = _extract_live_quote(self._live_quotes, symbol)

        # Emit bar-to-signal latency for live events with known close time
        if source == "live" and bar_close_ts is not None and signal_computed_at is not None:
            BAR_TO_SIGNAL_LATENCY.labels(symbol=symbol, tf=timeframe).observe(
                (signal_computed_at - bar_close_ts).total_seconds()
            )

        entries = build_ledger_entries(
            result, symbol, timeframe, timestamp, features,
            signal_computed_at=signal_computed_at,
            quote=live_quote,
            determined_at=determined_at,
        )

        # ── Signal gate: suppress condition re-fires and direction flips ─────────────
        # Prevents same setup re-publishing every bar the condition persists (onset-only).
        # Also blocks direction flip until prior signal resolves (direction=0 exit event).
        if result.selected_signal:
            _direction = int(result.selected_signal.get("direction", 0))
            if self._check_gate(symbol, timeframe, _direction, timestamp):
                self.logger.debug(
                    "Signal gated",
                    symbol=symbol,
                    timeframe=timeframe,
                    direction=_direction,
                    gate=self._signal_gate.get((symbol, timeframe)),
                )
                result = AggregatedResult(
                    selected_signal=None,
                    all_ranked=result.all_ranked,
                    resolution_method="gate_suppressed",
                    num_signals_fired=result.num_signals_fired,
                    num_agreeing=result.num_agreeing,
                    num_conflicting=result.num_conflicting,
                    cis_score=result.cis_score,
                    bucket_scores=result.bucket_scores,
                    weights_version=result.weights_version,
                )

        # STREAM PUBLISH FIRST (hot tier — consistent with platform architecture)
        published_signal = False
        if result.selected_signal and self._kafka_producer:
            sig = result.selected_signal
            message = {
                k: str(v) for k, v in sig.items()
                if isinstance(v, (str, int, float, bool))
            }
            # Promote individual targets as scalar fields
            targets = sig.get("targets") or []
            target_labels = sig.get("target_labels") or []
            if targets:
                message["profit_target"] = str(float(targets[0]))
                if len(targets) > 1:
                    message["profit_target_2"] = str(float(targets[1]))
                if len(targets) > 2:
                    message["profit_target_3"] = str(float(targets[2]))
            # Serialise list fields as JSON strings
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
            # Thread timing + price-at-creation fields
            if signal_computed_at:
                message["signal_computed_at"] = signal_computed_at.isoformat()
            if bar_close_ts:
                message["bar_close_ts"] = bar_close_ts.isoformat()
            # Bar close price — the price at which the triggering bar closed
            message["bar_close_price"] = str(float(bar.get("close", 0)))
            # Live quote snapshot at signal creation — enables entry distance calculation
            direction = int(sig.get("direction", 0))
            ask = live_quote.get("ask")
            bid = live_quote.get("bid")
            if ask is not None:
                message["ask_at_signal"] = str(ask)
            if bid is not None:
                message["bid_at_signal"] = str(bid)
            market_price = ask if direction == 1 else bid
            if market_price is not None:
                message["market_price_at_signal"] = str(market_price)
            # Inject signal_id from winning LedgerEntry (UUID assigned in build_ledger_entries)
            selected_entry = next((e for e in entries if e.was_selected), None)
            message["signal_id"] = selected_entry.signal_id if selected_entry else ""
            if selected_entry and selected_entry.zone_valid_at_signal is not None:
                message["zone_valid_at_signal"] = (
                    "1" if selected_entry.zone_valid_at_signal else "0"
                )
            msg_key = message_key(symbol, timeframe)
            # Publish to both signals and signals.aggregated topics
            try:
                await self._kafka_producer.publish(
                    topic_signals(self.env_name), message, key=msg_key
                )
                await self._kafka_producer.publish(
                    topic_signals_aggregated(self.env_name), message, key=msg_key
                )
                published_signal = True
            except Exception as e:
                self.logger.warning("Kafka publish failed for signal", error=str(e))
                published_signal = False

            if published_signal and result.selected_signal:
                _sig_id = message.get("signal_id", "")
                _pub_direction = int(result.selected_signal.get("direction", 0))
                self._update_gate(symbol, timeframe, _pub_direction, timestamp, _sig_id)
                # QUAL-02: record alpha decay fire state for the published setup.
                # Reset bars_since=0 so the next fire for this setup starts fresh decay.
                _pub_plugin = result.selected_signal.get("setup_plugin", "")
                if _pub_plugin:
                    _decay_key = (symbol, timeframe, _pub_plugin, _pub_direction)
                    self._setup_last_fire[_decay_key] = {"bars_since": 0}

        # DB INSERT SECOND (cold tier)
        if entries and self.db_manager:
            try:
                await insert_signals(self.db_manager, entries)
            except Exception:
                raise
            selected_count = sum(1 for e in entries if e.was_selected)
            self.signals_generated_total.inc(len(entries))
            self.signals_selected_total.inc(selected_count)
            self._total_signals += len(entries)

        # Publish all_ranked to intelligence.i7 Kafka topic (DATA-01)
        if self._kafka_producer:
            i7_msg = _build_i7_payload(result, timestamp, symbol, timeframe)
            try:
                await self._kafka_producer.publish(
                    topic_intelligence_i7(self.env_name),
                    i7_msg,
                    key=message_key(symbol, timeframe),
                )
            except Exception as e:
                self.logger.warning("Kafka publish failed for i7", error=str(e))

        elapsed_ms = (time.time() - calc_start) * 1000
        self.bars_processed_total.inc()
        self.calculation_duration_ms.set(elapsed_ms)
        self._total_bars += 1

        self.logger.debug(
            "Bar processed",
            symbol=symbol,
            timeframe=timeframe,
            signals_fired=result.num_signals_fired,
            selected=result.selected_signal is not None,
            resolution=result.resolution_method,
            calc_ms=round(elapsed_ms, 2),
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

            key = f"{symbol}:{timeframe}"
            bar_with_ts = {**bar, "timestamp": timestamp}
            self.bar_history[key].append(bar_with_ts)
            self._df_cache[key] = None

            frames = {
                "main": self._get_df(key),
                "features": features,
            }

            await self._process_bar(
                symbol, timeframe, bar, features, frames, timestamp,
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
        """Consume from intelligence and market.ticks topics via Kafka."""
        if not self._kafka_consumer:
            return
        _intel_topic = topic_intelligence(self.env_name)
        _ticks_topic = topic_market_ticks(self.env_name)
        try:
            async for topic, key, payload in self._kafka_consumer.messages():
                if self.shutdown_requested:
                    break
                try:
                    if topic == _intel_topic:
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
        Called at startup and every 4h by _drift_penalties_refresh_loop().

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
            self.logger.debug(
                "drift_penalties refreshed from DB", n_entries=len(new_penalties)
            )
        except Exception as exc:
            self.logger.warning("Failed to refresh drift_penalties from DB", error=str(exc))

    async def _drift_penalties_refresh_loop(self) -> None:
        """Refresh _drift_penalties from drift_state DB every 4h."""
        _REFRESH_INTERVAL = 4 * 3600
        while self.running and not self.shutdown_requested:
            try:
                try:
                    await asyncio.wait_for(self.shutdown_event.wait(), timeout=_REFRESH_INTERVAL)
                    break
                except TimeoutError:
                    pass
                if self.shutdown_requested:
                    break
                await self._refresh_drift_penalties_from_db()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.logger.warning("Drift penalties refresh error", error=str(exc))
                await asyncio.sleep(30)

    async def _read_drift_penalty(self, symbol: str, timeframe: str) -> float:
        """QUAL-09: Read KS drift penalty from in-process _drift_penalties dict.

        Phase 30: No longer reads Redis. Uses dict populated by _refresh_drift_penalties_from_db().
        Falls back to 1.0 (no penalty) when no entry exists for this symbol/TF.
        """
        return self._drift_penalties.get((symbol, timeframe), 1.0)

    async def _perf_weights_refresh_loop(self) -> None:
        """Refresh perf weights from Redis every 60 minutes."""
        _REFRESH_INTERVAL = 3600
        while self.running and not self.shutdown_requested:
            try:
                try:
                    await asyncio.wait_for(self.shutdown_event.wait(), timeout=_REFRESH_INTERVAL)
                    break
                except TimeoutError:
                    pass
                if self.shutdown_requested:
                    break
                await self._load_perf_weights()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.warning("Perf weights refresh error", error=str(e))
                await asyncio.sleep(30)

    async def start(self) -> None:
        self.logger.info("Starting Signal Generator Service", config=self.config["service"])
        try:
            await self._connect_database()
            # Seed bar_history from intelligence_features (warmup logic)
            await self._seed_bar_history_from_db()
            await self._setup_kafka_clients()
            self.running = True
            # Load perf weights at startup so first bar already has weights
            await self._load_perf_weights()
            # Load drift penalties at startup from drift_state DB table
            await self._refresh_drift_penalties_from_db()
            tasks = [
                asyncio.create_task(self._process_loop()),
                asyncio.create_task(self._health_monitor_loop()),
                asyncio.create_task(self._perf_weights_refresh_loop()),
                asyncio.create_task(self._drift_penalties_refresh_loop()),
                asyncio.create_task(self._resolution_listener_loop()),
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

    svc = SignalGeneratorService(args.config)
    try:
        await svc.start()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    asyncio.run(main())
