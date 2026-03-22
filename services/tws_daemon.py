#!/usr/bin/env python3
"""
TWS Daemon - Kafka-native bar and tick publisher (Phase 30: Redpanda migration)

Reads 1-minute bars from IBKR via IBKRProvider and publishes to Redpanda:
  - Bars  -> dev.market.bars  (key: SYMBOL:1m)
  - Ticks -> dev.market.ticks (key: SYMBOL)

Replaces production/daemons/high_frequency_tws_daemon.py Redis XADD calls.
DragonflyDB writes are fully removed. ib_insync logic remains in src/providers/ibkr.py.

Version: 1.0.1
Last Updated: 2026-03-22
Status: Current 
"""

from __future__ import annotations

import asyncio
import random
import signal
import sys
import threading
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from datetime import time as dtime
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from zoneinfo import ZoneInfo

import numpy as np
import structlog
from prometheus_client import start_http_server

from src.config.contracts import derive_roll_chain, get_roll_window
from src.config.settings import Settings, get_active_contracts
from src.core.kafka_utils import KafkaProducerClient
from src.core.stream_keys import (
    message_key,
    topic_market_bars,
    topic_market_ticks,
    topic_system_events,
)
from src.observability.metrics import counter as prom_counter
from src.observability.metrics import gauge as prom_gauge
from src.providers import IBKRProvider

logger = structlog.get_logger(__name__)

# Simplified tick types for futures - avoid Error 321
FUTURES_TICK_TYPES = {
    "essential": "",
    "volume": "233",
    "all": "233",
}

# Minimum bars in window before roll detection is attempted
_ROLL_MIN_WINDOW = 20


class RollMonitor:
    """Calendar-driven futures roll detection with volume z-score confirmation.

    Algorithm (D-17, Phase 47):
    1. Track per-base-symbol rolling window of current bar volumes
    2. On each bar: check if today is inside the contract roll window
       (get_roll_window() from contracts.py — calendar-driven, not volume-ratio-driven)
    3. If inside roll window AND window has >= 20 bars:
       compute z-score of current volume vs rolling mean/std
    4. If z_score < -2.0 (volume DROP of 2+ std devs): increment confirmation counter
    5. After 3 consecutive confirming bars: fire roll confirmed
    6. 30-minute cooldown per base symbol after any confirmed roll
    7. Time-of-day gating adjusts detection window by ET session
    8. Paper account detection skips unavailable contracts

    D-16 fix: update_volume() takes only current_vol (old two-vol ratio logic removed).
    D-19: PAPER_SKIP_CONTRACTS guard preserved for paper account compatibility.

    Feature flag ROLL_MONITOR_ENABLED=false: check_roll always returns False.
    """

    # Segmented volume ratio thresholds (kept for get_threshold() backward compat)
    VOLUME_THRESHOLDS: dict[str, float] = {
        "ES": 1.2, "NQ": 1.2, "RTY": 1.2, "YM": 1.2,   # equity index
        "CL": 1.5, "GC": 1.5, "SI": 1.5, "HG": 1.5,    # energy/metals
        "ZN": 1.4, "ZF": 1.4, "ZB": 1.4, "ZT": 1.4,    # rates
    }

    # Paper account contracts known to be unavailable
    PAPER_SKIP_CONTRACTS: set[str] = {"BZJ6", "NGJ6", "ZWH6"}

    # Paper account ib_host values (per CONTEXT.md decision)
    PAPER_ACCOUNT_HOSTS: set[str] = {"192.168.1.157", "127.0.0.1"}

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._is_paper = self._is_paper_account()
        self._window_size = settings.roll_monitor_window_size          # 100
        self._confirmation_required = settings.roll_confirmation_bars   # 3
        self._cooldown_minutes = settings.roll_monitor_cooldown_min    # 30
        self._postroll_bars = settings.roll_monitor_postroll_bars      # 10
        self._tod_gated = settings.roll_time_of_day_gated

        # Per-base-symbol rolling state
        # base symbol -> deque of float volumes (single value per bar — D-16 fix)
        self._volume_windows: dict[str, deque] = {}
        # Per-base-symbol consecutive confirmation count for z-score < -2.0 bars
        self._confirmation_counts: dict[str, int] = defaultdict(int)
        self._cooldown_until: dict[str, datetime] = {}
        self._postroll_remaining: dict[str, int] = {}

    @property
    def _confirmation_count(self) -> dict[str, int]:
        """Backward-compat alias for _confirmation_counts (used in tests)."""
        return self._confirmation_counts

    # ------------------------------------------------------------------
    # Paper account detection
    # ------------------------------------------------------------------

    def _is_paper_account(self) -> bool:
        """Detect paper account via ib_host setting."""
        return self._settings.ib_host in self.PAPER_ACCOUNT_HOSTS

    def should_skip_symbol(self, symbol: str) -> bool:
        """Return True if symbol should be skipped (paper account + unavailable contract)."""
        return self._is_paper and symbol in self.PAPER_SKIP_CONTRACTS

    # ------------------------------------------------------------------
    # Threshold helpers
    # ------------------------------------------------------------------

    def get_threshold(self, base_symbol: str) -> float:
        """Return segmented volume ratio threshold for base symbol."""
        return self.VOLUME_THRESHOLDS.get(
            base_symbol, self._settings.roll_monitor_threshold_default
        )

    def _apply_tod_adjustment(self, threshold: float, utc_now: datetime) -> float | None:
        """Adjust threshold by time-of-day (Eastern Time).

        Returns:
            None   — skip detection entirely (post-close window 16–18 ET)
            float  — adjusted threshold
        """
        if not self._tod_gated:
            return threshold
        et = utc_now.astimezone(ZoneInfo("America/New_York"))
        hour_et = et.hour
        if 16 <= hour_et < 18:   # post-close: skip detection entirely
            return None
        if 9 <= hour_et < 11:    # pre-open: stricter threshold
            return threshold * 1.3
        if hour_et == 15:        # close: more sensitive
            return threshold * 0.9
        return threshold          # standard RTH / overnight

    # ------------------------------------------------------------------
    # Volume window management
    # ------------------------------------------------------------------

    def update_volume(self, base_symbol: str, current_vol: float) -> None:
        """Append current bar volume to rolling window.

        D-16 fix: signature changed from (base_symbol, current_vol, next_vol) to
        (base_symbol, current_vol). The old ratio logic used next_vol but the call
        site always passed the same value for both, producing ratio=1.0 always.
        The new z-score algorithm needs only the current bar's volume.
        """
        if base_symbol not in self._volume_windows:
            self._volume_windows[base_symbol] = deque(maxlen=self._window_size)
        self._volume_windows[base_symbol].append(current_vol)

    # ------------------------------------------------------------------
    # Roll detection logic
    # ------------------------------------------------------------------

    def check_roll(self, base_symbol: str, utc_now: datetime) -> bool:
        """Check if roll conditions are met for base_symbol.

        Calendar + z-score algorithm (D-17, Phase 47):
        1. Gate on calendar roll window: get_roll_window() must return non-None
        2. Require >= 20 bars in volume window
        3. Compute z-score of current bar volume vs rolling history
        4. If z_score < -2.0 (volume DROP): increment confirmation counter
        5. Return True after N consecutive confirming bars; reset and cooldown

        Returns True on confirmed roll.
        Side-effects: increments/resets _confirmation_counts; sets _cooldown_until.
        Caller must schedule _on_roll_confirmed() when this returns True.
        """
        # Calendar gate: only detect during known roll windows
        try:
            roll_window = get_roll_window(base_symbol, utc_now.date())
        except ValueError:
            # base_symbol not in FUTURES_ROLL_CYCLES — no roll detection possible
            return False

        if roll_window is None:
            # Outside any roll window — reset confirmation streak
            self._confirmation_counts[base_symbol] = 0
            return False

        window = self._volume_windows.get(base_symbol)
        if window is None or len(window) < _ROLL_MIN_WINDOW:
            return False

        # Cooldown check
        cooldown_until = self._cooldown_until.get(base_symbol)
        if cooldown_until is not None and utc_now < cooldown_until:
            return False

        # Time-of-day gating (optional)
        if self._tod_gated:
            threshold = self.get_threshold(base_symbol)
            adj_threshold = self._apply_tod_adjustment(threshold, utc_now)
            if adj_threshold is None:
                return False

        # Z-score: detect volume DROP below 2 std devs (front contract losing volume to back)
        arr = np.array(window)
        mean_vol = arr[:-1].mean()
        std_vol = arr[:-1].std()
        if std_vol < 1e-9:
            # No variation in history — cannot compute meaningful z-score
            return False

        current_vol = arr[-1]
        z_score = (current_vol - mean_vol) / std_vol

        if z_score < -2.0:
            self._confirmation_counts[base_symbol] = (
                self._confirmation_counts.get(base_symbol, 0) + 1
            )
        else:
            self._confirmation_counts[base_symbol] = 0

        if self._confirmation_counts.get(base_symbol, 0) >= self._confirmation_required:
            # Confirmed roll — reset counter and start cooldown
            self._confirmation_counts[base_symbol] = 0
            self._cooldown_until[base_symbol] = utc_now + timedelta(
                minutes=self._cooldown_minutes
            )
            logger.info(
                "Roll detected",
                base_symbol=base_symbol,
                z_score=round(z_score, 3),
                roll_window_start=str(roll_window[0]),
                roll_window_end=str(roll_window[1]),
            )
            return True

        return False

    # ------------------------------------------------------------------
    # Roll event publishing
    # ------------------------------------------------------------------

    async def _on_roll_confirmed(
        self,
        base_symbol: str,
        old_symbol: str,
        roll_gap: float = 0.0,
        roll_direction: str = "unknown",
        db_manager=None,
        kafka_producer=None,
        env_name: str = "",
    ) -> None:
        """Publish roll event to Kafka and update contract_metadata atomically.

        D-20: new_symbol is now derived from derive_roll_chain(base_symbol) — the caller
        no longer needs to pass it. Price comparison is unavailable at detection time,
        so roll_gap defaults to 0.0 and roll_direction defaults to "unknown".

        Args:
            base_symbol: Base futures symbol (e.g. "ES")
            old_symbol:  Front-month contract being replaced (e.g. "ESM6")
            roll_gap:    Price gap at roll boundary (0.0 when unknown at detection time)
            roll_direction: "up", "down", or "unknown"
            db_manager:  DatabaseManager instance (optional — skipped if None)
            kafka_producer: KafkaProducerClient instance (optional — skipped if None)
            env_name:    Kafka env prefix
        """
        # D-20: Derive new_symbol from roll chain — no next-contract subscription needed
        chain = derive_roll_chain(base_symbol)
        new_symbol = chain[0]["roll_to"] if chain else old_symbol

        detected_at = datetime.now(UTC)
        payload = {
            "event_type": "roll",
            "base_symbol": base_symbol,
            "old_symbol": old_symbol,
            "new_symbol": new_symbol,
            "roll_gap": roll_gap,
            "roll_direction": roll_direction,
            "roll_premium_pct": roll_gap,  # INTEL-04: roll_premium_pct flows through payload
            "detected_at": detected_at.isoformat(),
        }

        # Publish to Kafka system.events topic
        if kafka_producer is not None:
            try:
                await kafka_producer.publish(
                    topic_system_events(env_name),
                    {k: str(v) for k, v in payload.items()},
                    key=base_symbol,
                )
            except Exception as exc:
                logger.warning("Roll event Kafka publish failed", error=str(exc))

        # Atomic DB update: toggle is_front_month + insert system_events row
        if db_manager is not None:
            try:
                await db_manager.execute(
                    """
                    UPDATE contract_metadata
                       SET is_front_month = false
                     WHERE base_symbol = $1 AND is_front_month = true
                    """,
                    base_symbol,
                )
                await db_manager.execute(
                    """
                    UPDATE contract_metadata
                       SET is_front_month = true,
                           roll_detected_at = $2,
                           roll_gap = $3,
                           roll_direction = $4,
                           confirmation_count = confirmation_count + 1
                     WHERE symbol = $1
                    """,
                    new_symbol,
                    detected_at,
                    roll_gap,
                    roll_direction,
                )
                await db_manager.execute(
                    """
                    INSERT INTO system_events
                        (event_type, base_symbol, old_symbol, new_symbol,
                         roll_gap, roll_direction, detected_at)
                    VALUES ('roll', $1, $2, $3, $4, $5, $6)
                    """,
                    base_symbol,
                    old_symbol,
                    new_symbol,
                    roll_gap,
                    roll_direction,
                    detected_at,
                )
            except Exception as exc:
                logger.error("Roll event DB update failed", error=str(exc))


class TwsDaemon:
    """Kafka-native TWS daemon: publishes bars to market.bars and ticks to market.ticks."""

    def __init__(
        self, host: str | None = None, port: int | None = None, client_id: int | None = None
    ):
        self.settings = Settings()
        self.host = host or self.settings.ib_host
        self.port = port or self.settings.ib_port
        self.client_id = client_id or self.settings.ib_client_id

        self.provider: IBKRProvider | None = None

        self.running = False
        self.connected = False

        # High-frequency metrics
        self.ticks_processed = 0
        self.bars_processed = 0
        self.dropped_ticks = 0
        self.start_time: datetime | None = None
        self.last_health_check = 0
        self.reconnects = 0

        self.contracts = [c.model_dump() for c in get_active_contracts(self.settings)]
        self._symbol_to_base: dict[str, str] = {
            c["symbol"]: c.get("base", c["symbol"]) for c in self.contracts
        }
        self.health_check_interval = 30

        # Stream namespacing by environment (e.g., dev, prod)
        self.env_name = self.settings.env_name.strip()

        # Market hours
        self.market_hours = MarketHoursManager()
        self.current_mode: str | None = None
        self.mode_check_interval = 60
        self.last_mode_check_ts = 0.0

        # Seen bar dedup (last 30 bars per symbol)
        self.seen_bar_timestamps: dict[str, set[str]] = defaultdict(set)
        self.seen_bar_timestamps_order: dict[str, list[str]] = defaultdict(list)

        # Metrics
        self.metrics_port = int(self.settings.metrics_port)
        self.m_ticks = prom_counter("indicagent_ticks_total", "Total ticks processed")
        self.m_dropped = prom_counter(
            "indicagent_ticks_dropped_total", "Dropped ticks due to backpressure"
        )
        from prometheus_client import Counter as _Counter

        self.m_dropped_by_reason = _Counter(
            "indicagent_tws_ticks_dropped_reason_total",
            "Dropped ticks by reason",
            labelnames=("reason",),
        )
        self.m_bars = prom_counter("indicagent_bars_total", "Total bars processed")
        self.m_reconnects = prom_counter("indicagent_ibkr_reconnects_total", "IBKR reconnects")
        self.m_drift = prom_counter("indicagent_bar_drift_total", "Discrepancies between 5s-derived and official bars")
        self.g_connected = prom_gauge("indicagent_ibkr_connected", "1 when connected")
        self.g_tick_queue = prom_gauge("indicagent_tick_queue_size", "Async tick queue depth")

        # Roll monitor (Phase 38) — disabled by default via feature flag
        self._roll_monitor = RollMonitor(self.settings)

        # Kafka producer (replaces async_redis XADD calls)
        self._kafka_producer: KafkaProducerClient = KafkaProducerClient(
            bootstrap_servers=self.settings.kafka_bootstrap_servers
        )

        # Async loop (for tick loop + bar polling)
        self.use_async_publish = bool(self.settings.hf_async_publish)
        self.loop: asyncio.AbstractEventLoop | None = None
        self.loop_thread: threading.Thread | None = None
        self._reconnect_delay = 1.0
        self._rtb_task: asyncio.Future | None = None
        self._official_task: asyncio.Future | None = None
        self._heartbeat_task: asyncio.Future | None = None

        # Per-symbol RTB state: symbol -> {open, high, low, close, volume, bar_minute, emitted}
        self._rtb_state: dict[str, dict] = {}
        # Reconciliation state: symbol -> {ts: OHLCVBar}
        self._official_bars_cache: dict[str, dict[str, Any]] = defaultdict(dict)

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        logger.info(
            "TWS Daemon (Kafka) initialized",
            host=host,
            port=port,
            client_id=client_id,
            target_contracts=len(self.contracts),
        )

    def _signal_handler(self, signum, frame):
        logger.info("Shutdown signal received", signal=signum)
        self.running = False

    def connect_tws(self) -> bool:
        try:
            self.provider = IBKRProvider(host=self.host, port=self.port, client_id=self.client_id)
            if self.loop:
                fut = asyncio.run_coroutine_threadsafe(self.provider.connect(), self.loop)
                connected = fut.result(timeout=30)
            else:
                connected = asyncio.run(self.provider.connect())

            if connected:
                self.connected = True
                self.g_connected.set(1)
                self.current_mode = self.market_hours.get_mode(datetime.now())
                self._qualify_all_instruments()
                logger.info("Connected to TWS via IBKRProvider")
                return True
            else:
                logger.error("TWS connection failed")
                return False
        except Exception as e:
            logger.error("TWS connection error", error=str(e))
            return False

    def _qualify_all_instruments(self) -> None:
        if not self.provider:
            return
        for instrument in get_active_contracts(self.settings):
            try:
                if self.loop:
                    fut = asyncio.run_coroutine_threadsafe(
                        self.provider.qualify_instrument(instrument), self.loop
                    )
                    fut.result(timeout=10)
                else:
                    asyncio.run(self.provider.qualify_instrument(instrument))
            except Exception as e:
                logger.warning("qualify_instrument failed", symbol=instrument.symbol, error=str(e))

    async def _rtb_loop(self) -> None:
        """Consume 5-second RealTimeBars from IBKRProvider and aggregate to 1m bars.

        Maintains per-symbol OHLCV state. Data is EMITTED by _heartbeat_loop
        to ensure deterministic timing even during quiet periods (FX/Crypto).
        """
        if not self.provider:
            return
        symbols = [c["symbol"] for c in self.contracts]

        def _init_state(minute=None) -> dict:
            return {
                "bar_minute": minute,
                "open": None,
                "high": None,
                "low": None,
                "close": None,
                "volume": 0.0,
                "last_update": time.time(),
                "emitted": False
            }

        try:
            async for symbol, rtb in self.provider.stream_real_time_bars(symbols):
                if not self.running:
                    break
                try:
                    bar_minute = rtb.time.replace(second=0, microsecond=0)
                    s = self._rtb_state.setdefault(symbol, _init_state(bar_minute))

                    # If this 5s bar belongs to a newer minute than our current state,
                    # it means the heartbeat should have already emitted the old one.
                    # We update state to the new minute.
                    if s["bar_minute"] is not None and bar_minute > s["bar_minute"]:
                        if not s["emitted"]:
                            # Force emit the stale bar if the heartbeat was late
                            await self._emit_bar(symbol, s)
                        s.update(_init_state(bar_minute))

                    if s["bar_minute"] is None or bar_minute >= s["bar_minute"]:
                        if s["open"] is None:
                            s["open"] = rtb.open_
                        s["high"] = max(s["high"] or rtb.high, rtb.high)
                        s["low"] = min(s["low"] or rtb.low, rtb.low)
                        s["close"] = rtb.close
                        s["volume"] += rtb.volume
                        s["last_update"] = time.time()

                    # Publish 5s close as price update for dashboard
                    await self._kafka_producer.publish(
                        topic_market_ticks(self.env_name),
                        {
                            "symbol": symbol,
                            "price": str(rtb.close),
                            "timestamp": rtb.time.isoformat(),
                            "source": "ibkr",
                        },
                        key=symbol,
                    )
                    self.ticks_processed += 1
                    self.m_ticks.inc()

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.warning("RTB loop error", symbol=symbol, error=str(e))

        except asyncio.CancelledError:
            logger.info("RTB loop cancelled")

    async def _official_bars_loop(self) -> None:
        """Consume official, audited 1m bars from IBKR for reconciliation."""
        if not self.provider:
            return
        symbols = [c["symbol"] for c in self.contracts]

        try:
            async for symbol, bar in self.provider.stream_official_bars(symbols):
                if not self.running:
                    break
                # Store in cache for heartbeat/emit to compare
                ts_str = bar.timestamp.isoformat()
                self._official_bars_cache[symbol][ts_str] = bar

                # Cleanup old cache entries (keep last 20)
                if len(self._official_bars_cache[symbol]) > 20:
                    oldest_ts = sorted(self._official_bars_cache[symbol].keys())[0]
                    del self._official_bars_cache[symbol][oldest_ts]

        except asyncio.CancelledError:
            logger.info("Official bars loop cancelled")
        except Exception as e:
            logger.error("Official bars loop error", error=str(e))

    async def _heartbeat_loop(self) -> None:
        """Deterministic bar emission loop.

        Runs every 1s. Checks if current_time > bar_minute + 61s.
        If yes, emits the bar regardless of whether new data arrived.
        """
        while self.running:
            try:
                now_utc = datetime.now(UTC)
                # Check all active symbols for minutes that need sealing
                for symbol in self._symbol_to_base:
                    s = self._rtb_state.get(symbol)
                    if not s or not s["bar_minute"]:
                        continue

                    # If we are at least 1 second into the NEXT minute, emit the PREVIOUS minute
                    # e.g. at 10:01:01, emit the 10:00:00 bar.
                    if now_utc >= s["bar_minute"] + timedelta(seconds=61) and not s["emitted"]:
                        await self._emit_bar(symbol, s)
                        s["emitted"] = True

                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Heartbeat loop error", error=str(e))
                await asyncio.sleep(1)

    async def _emit_bar(self, symbol: str, state: dict) -> None:
        """Publish completed 1m bar and perform reconciliation with official source."""
        bar_minute = state["bar_minute"]
        bar_timestamp = bar_minute.isoformat()

        # Dedup guard
        if bar_timestamp in self.seen_bar_timestamps[symbol]:
            return
        self.seen_bar_timestamps[symbol].add(bar_timestamp)
        order = self.seen_bar_timestamps_order[symbol]
        order.append(bar_timestamp)
        if len(order) > 30:
            evicted = order.pop(0)
            self.seen_bar_timestamps[symbol].discard(evicted)

        # 1. Reconciliation (Renaissance Audit)
        official = self._official_bars_cache.get(symbol, {}).get(bar_timestamp)
        drift_detected = False
        if official:
            # Check close price drift (threshold: 0.01%)
            price_diff = abs(float(state["close"]) - official.close)
            if price_diff > (official.close * 0.0001):
                drift_detected = True
                self.m_drift.inc()
                logger.warning(
                    "Data drift detected",
                    symbol=symbol,
                    ts=bar_timestamp,
                    derived=state["close"],
                    official=official.close,
                    diff=price_diff
                )

        # Handle the case where state is completely empty (no 5s data for the minute)
        # Use official bar data if available, otherwise flat bar from prev close
        if state["open"] is None:
            if official:
                state.update({
                    "open": official.open,
                    "high": official.high,
                    "low": official.low,
                    "close": official.close,
                    "volume": official.volume
                })
            else:
                # Flat bar would require previous close state; for now just log warning
                logger.warning("No data for bar emission", symbol=symbol, ts=bar_timestamp)
                return

        bar_data = {
            "timestamp": bar_timestamp,
            "symbol": symbol,
            "timeframe": "1m",
            "open": str(state["open"]),
            "high": str(state["high"]),
            "low": str(state["low"]),
            "close": str(state["close"]),
            "volume": str(state["volume"]),
            "source": "authoritative",
            "bar_close_ts": bar_timestamp,
            "is_reconciled": bool(official),
            "drift_detected": drift_detected
        }
        await self._kafka_producer.publish(
            topic_market_bars(self.env_name),
            bar_data,
            key=message_key(symbol, "1m"),
        )
        self.bars_processed += 1
        self.m_bars.inc()
        logger.info(
            "1m bar emitted",
            symbol=symbol,
            close=state["close"],
            vol=state["volume"],
            reconciled=bool(official)
        )

        # Roll monitor (futures only)
        base_symbol = self._symbol_to_base.get(symbol, symbol)
        bar_utc = (bar_minute if bar_minute.tzinfo is not None
                   else bar_minute.replace(tzinfo=UTC))
        self._roll_monitor.update_volume(base_symbol, float(state["volume"]))
        if self._roll_monitor.check_roll(base_symbol, bar_utc):
            await self._roll_monitor._on_roll_confirmed(
                base_symbol=base_symbol, old_symbol=symbol,
                kafka_producer=self._kafka_producer, env_name=self.env_name,
            )

    def health_check(self) -> None:
        if not self.running or not self.start_time:
            return
        current_time = time.time()
        if current_time - self.last_health_check < self.health_check_interval:
            return
        self.last_health_check = current_time
        elapsed = (datetime.now() - self.start_time).total_seconds()
        tick_rate = self.ticks_processed / elapsed if elapsed > 0 else 0
        performance = "HIGH" if tick_rate > 50 else "MEDIUM" if tick_rate > 10 else "LOW"
        logger.info(
            "Health check",
            uptime_minutes=round(elapsed / 60, 2),
            ticks_processed=self.ticks_processed,
            bars_processed=self.bars_processed,
            tick_rate_per_sec=round(tick_rate, 2),
            performance=performance,
        )

    def run(self) -> None:
        logger.info("Starting TWS Daemon (Kafka)")

        try:
            start_http_server(self.metrics_port)
            logger.info("Prometheus metrics server started", port=self.metrics_port)
        except Exception as e:
            logger.warning("Failed to start metrics server", error=str(e))

        if self.use_async_publish:
            self.loop = asyncio.new_event_loop()

            def _run_loop(loop: asyncio.AbstractEventLoop) -> None:
                asyncio.set_event_loop(loop)
                loop.run_forever()

            self.loop_thread = threading.Thread(target=_run_loop, args=(self.loop,), daemon=True)
            self.loop_thread.start()

            # Start Kafka producer in the async loop
            asyncio.run_coroutine_threadsafe(self._kafka_producer.start(), self.loop).result(
                timeout=10
            )

        if not self.connect_tws():
            logger.error("TWS connection required for operation")
            return

        if self.loop:
            self._rtb_task = asyncio.run_coroutine_threadsafe(self._rtb_loop(), self.loop)
            self._official_task = asyncio.run_coroutine_threadsafe(self._official_bars_loop(), self.loop)
            self._heartbeat_task = asyncio.run_coroutine_threadsafe(self._heartbeat_loop(), self.loop)

        self.running = True
        self.start_time = datetime.now()

        logger.info("TWS Daemon started successfully")

        while self.running:
            try:
                if self.connected and self.provider and not self.provider.is_connected():
                    logger.warning("Provider reports disconnected")
                    self.connected = False
                    self._on_disconnected()

                if not self.connected:
                    logger.warning("Disconnected from TWS, attempting reconnect...")
                    if self.connect_tws():
                        if self.loop:
                            self._rtb_task = asyncio.run_coroutine_threadsafe(
                                self._rtb_loop(), self.loop
                            )
                            self._official_task = asyncio.run_coroutine_threadsafe(
                                self._official_bars_loop(), self.loop
                            )
                            self._heartbeat_task = asyncio.run_coroutine_threadsafe(
                                self._heartbeat_loop(), self.loop
                            )
                        self.m_reconnects.inc()
                        self.reconnects += 1
                        self._reconnect_delay = 1.0
                    else:
                        time.sleep(self._reconnect_delay)
                        self._reconnect_delay = min(
                            self._reconnect_delay * 2 + random.uniform(0.0, 0.5), 16.0
                        )
                        continue

                now_ts = time.time()
                if now_ts - self.last_mode_check_ts >= self.mode_check_interval:
                    self.last_mode_check_ts = now_ts
                    self.current_mode = self.market_hours.get_mode(datetime.now())

                self.health_check()
                time.sleep(0.1)

            except KeyboardInterrupt:
                logger.info("Keyboard interrupt received")
                break
            except Exception as e:
                logger.error("Processing error", error=str(e))
                time.sleep(1.0)

        self.cleanup()

    def _on_disconnected(self, *args):
        logger.warning("TWS disconnected event received")
        self.connected = False
        self.g_connected.set(0)
        for task in [self._rtb_task, self._official_task, self._heartbeat_task]:
            if task is not None and not task.done():
                task.cancel()
        logger.info("Background tasks cancelled for reconnect")

    def cleanup(self) -> None:
        logger.info("Cleaning up TWS Daemon...")
        self.running = False

        # Stop Kafka producer
        if self.loop and self._kafka_producer:
            try:
                fut = asyncio.run_coroutine_threadsafe(self._kafka_producer.stop(), self.loop)
                fut.result(timeout=5)
            except Exception as e:
                logger.warning("Kafka producer stop failed", error=str(e))

        if self.provider and self.provider.is_connected():
            try:
                if self.loop:
                    fut = asyncio.run_coroutine_threadsafe(self.provider.disconnect(), self.loop)
                    fut.result(timeout=5)
                else:
                    asyncio.run(self.provider.disconnect())
                logger.info("Disconnected from TWS")
            except Exception as e:
                logger.warning("TWS disconnect error", error=str(e))

        if self.loop:
            try:
                self.loop.call_soon_threadsafe(self.loop.stop)
                if self.loop_thread:
                    self.loop_thread.join(timeout=2.0)
            except Exception:
                pass

        if self.start_time:
            elapsed = (datetime.now() - self.start_time).total_seconds()
            tick_rate = self.ticks_processed / elapsed if elapsed > 0 else 0
            logger.info(
                "TWS Daemon session complete",
                uptime_seconds=round(elapsed, 2),
                ticks_processed=self.ticks_processed,
                bars_processed=self.bars_processed,
                avg_tick_rate=round(tick_rate, 2),
            )

        logger.info("TWS Daemon cleanup complete")


class MarketHoursManager:
    """Minimal CME market hours manager for RTH/ETH/CLOSED classification."""

    def __init__(self) -> None:
        self.tz = ZoneInfo("US/Eastern")

    def get_mode(self, now_utc: datetime) -> str:
        now_et = now_utc.astimezone(self.tz)
        wd = now_et.weekday()
        t = now_et.time()

        if wd == 5:
            return "CLOSED"
        if wd == 6:
            return "ETH" if t >= dtime(18, 0) else "CLOSED"

        if dtime(17, 0) <= t < dtime(18, 0):
            return "CLOSED"
        if dtime(9, 30) <= t < dtime(16, 0):
            return "RTH"
        return "ETH"


def main():
    import argparse

    _settings = Settings()
    parser = argparse.ArgumentParser(description="TWS Daemon (Kafka)")
    parser.add_argument("--host", default=_settings.ib_host)
    parser.add_argument("--port", type=int, default=_settings.ib_port)
    parser.add_argument("--client-id", type=int, default=_settings.ib_client_id)

    args = parser.parse_args()

    daemon = TwsDaemon(host=args.host, port=args.port, client_id=args.client_id)
    daemon.run()


if __name__ == "__main__":
    main()
