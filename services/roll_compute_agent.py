#!/usr/bin/env python3
"""
RollComputeAgent — DB-ignorant futures roll detection agent.

Consumes market.bars topic, runs RollMonitor (calendar + volume z-score algorithm),
and publishes typed RollEvent to market.events.roll when a roll is confirmed.

The agent is DB-ignorant per the Renaissance Agentic DAG spec:
- No DB reads or writes
- No topic_system_events dual-publish
- Publishes ONLY to topic_roll_events

RollMonitor is kept private inside this module (not in src/intelligence/)
per research recommendation — it is a pure data-stream computation that
does not fit the plugin tier hierarchy.

Golden Signals (D-17):
- events_consumed_total: bars consumed from market.bars
- rolls_detected_total: roll events confirmed and published
- detection_latency_seconds: time to run check_roll() per bar
- detection_errors_total: exceptions during bar processing

Metrics port: 9122

Version: 1.0.0
Last Updated: 2026-03-28
Status: Phase 053.3 Plan 03
"""

from __future__ import annotations

import asyncio
import sys
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import structlog

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from zoneinfo import ZoneInfo

from prometheus_client import Counter, Histogram

from src.config.contracts import derive_roll_chain, get_roll_window
from src.config.settings import Settings, get_active_contracts
from src.core.agent.base import BaseAgent
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.schemas.market_events import RollEvent
from src.core.stream_keys import topic_market_bars, topic_roll_events

# Minimum bars in window before roll detection is attempted
_ROLL_MIN_WINDOW = 20

_logger = structlog.get_logger(__name__)

# Module-level Prometheus metrics — avoids duplicate registration on re-instantiation
_EVENTS_CONSUMED = Counter("roll_compute_events_consumed_total", "Bars consumed from market.bars", ["agent"])
_ROLLS_DETECTED = Counter("roll_compute_rolls_detected_total", "Roll events confirmed and published", ["agent"])
_DETECTION_LATENCY = Histogram("roll_compute_detection_latency_seconds", "Roll detection latency per bar", ["agent"])
_DETECTION_ERRORS = Counter("roll_compute_detection_errors_total", "Exceptions during bar processing", ["agent"])


# ---------------------------------------------------------------------------
# RollMonitor — extracted from tws_daemon.py / data_provider_agent.py
# DB-ignorant: no DB writes. DB event publishing removed entirely.
# ML features captured before reset: _last_volume_zscore, _last_confirmation_count
# ---------------------------------------------------------------------------


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

    D-13: volume_zscore and confirmation_count captured before reset as ML features.
    D-16 fix: update_volume() takes only current_vol (old two-vol ratio logic removed).
    D-18: PAPER_SKIP_CONTRACTS guard preserved for paper account compatibility.
    DB write method removed — DB writes dropped, RollComputeAgent publishes RollEvent.
    """

    # Segmented volume ratio thresholds (kept for get_threshold() backward compat)
    VOLUME_THRESHOLDS: dict[str, float] = {
        "ES": 1.2, "NQ": 1.2, "RTY": 1.2, "YM": 1.2,   # equity index
        "CL": 1.5, "GC": 1.5, "SI": 1.5, "HG": 1.5,    # energy/metals
        "ZN": 1.4, "ZF": 1.4, "ZB": 1.4, "ZT": 1.4,    # rates
    }

    # Paper account contracts known to be unavailable (D-18)
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

        # D-13: ML features captured before counter reset
        self._last_volume_zscore: float = 0.0
        self._last_confirmation_count: int = 0

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

        D-13: Captures _last_volume_zscore and _last_confirmation_count before reset.

        Returns True on confirmed roll.
        Side-effects: increments/resets _confirmation_counts; sets _cooldown_until.
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

        # Time-of-day gating: skip detection entirely during post-close window (16-18 ET)
        if self._tod_gated:
            if self._apply_tod_adjustment(self.get_threshold(base_symbol), utc_now) is None:
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

        # D-13: Capture z-score before any potential reset
        self._last_volume_zscore = float(z_score)

        if z_score < -2.0:
            self._confirmation_counts[base_symbol] = self._confirmation_counts.get(base_symbol, 0) + 1
        else:
            self._confirmation_counts[base_symbol] = 0

        if self._confirmation_counts.get(base_symbol, 0) >= self._confirmation_required:
            # D-13: Capture confirmation_count before reset
            self._last_confirmation_count = self._confirmation_counts[base_symbol]
            # Confirmed roll — reset counter and start cooldown
            self._confirmation_counts[base_symbol] = 0
            self._cooldown_until[base_symbol] = utc_now + timedelta(
                minutes=self._cooldown_minutes
            )
            _logger.info(
                "Roll detected",
                base_symbol=base_symbol,
                z_score=round(z_score, 3),
                roll_window_start=str(roll_window[0]),
                roll_window_end=str(roll_window[1]),
            )
            return True

        return False


# ---------------------------------------------------------------------------
# CalendarRollScheduler — deterministic calendar-based roll detection
# ---------------------------------------------------------------------------


class CalendarRollScheduler:
    """Calendar-driven roll scheduler: fires once per cycle at roll_end date.

    Independent of volume data — uses get_roll_window() from contracts.py to
    determine the scheduled roll_end date (expiry - 3 days) for each base symbol.

    Fires when today >= roll_end AND this cycle hasn't fired yet.
    Keyed by base_symbol → roll_end_date to be idempotent within a cycle.

    Serves as a safety-net fallback: if volume detection missed the roll,
    calendar fires at the scheduled date regardless. If volume already fired,
    ContractMetadataWriterAgent's idempotency check prevents double-execution.
    """

    def __init__(self) -> None:
        # Maps base_symbol → roll_end date of the last fired cycle (O(1) lookup, bounded by symbol count)
        self._fired: dict[str, date] = {}

    def check_calendar_roll(self, base_symbol: str, utc_now: datetime) -> bool:
        """Return True if calendar roll should fire for base_symbol at utc_now.

        Fires when:
        1. get_roll_window() returns a non-None window
        2. today >= roll_end date
        3. base_symbol has not already fired for this roll_end

        Returns False when outside any roll window, symbol unknown, or already fired.
        Side-effect: records base_symbol → roll_end in _fired on first True return.
        """
        try:
            roll_window = get_roll_window(base_symbol, utc_now.date())
        except ValueError:
            return False

        if roll_window is None:
            return False

        _roll_start, roll_end = roll_window

        if utc_now.date() < roll_end:
            return False

        if self._fired.get(base_symbol) == roll_end:
            return False

        self._fired[base_symbol] = roll_end
        return True

    def get_last_fired_roll_end(self, base_symbol: str) -> date | None:
        """Return the roll_end date of the last fired cycle for base_symbol, or None."""
        return self._fired.get(base_symbol)


# ---------------------------------------------------------------------------
# RollComputeAgent — BaseAgent lifecycle, consumes market.bars, publishes RollEvent
# ---------------------------------------------------------------------------


class RollComputeAgent(BaseAgent):
    """DB-ignorant roll detection agent.

    Consumes market.bars, runs RollMonitor per bar, publishes typed RollEvent
    to topic_roll_events when a roll is confirmed.

    No DB writes — DB-ignorant per Layer 1 spec (D-14).
    No dual-publish to system events topic — single output channel (D-03).
    """

    def __init__(self) -> None:
        settings = Settings()
        metrics_port = 9122  # config-before-super pattern
        super().__init__(name="roll_compute_agent", metrics_port=metrics_port)
        self._kafka_bootstrap: str = settings.kafka_bootstrap_servers
        self._roll_monitor = RollMonitor(settings)
        self._calendar_scheduler = CalendarRollScheduler()
        self._kafka_producer: KafkaProducerClient | None = None
        self._kafka_consumer: KafkaConsumerClient | None = None
        self._symbol_to_base: dict[str, str] = {
            c.symbol: c.base or c.symbol
            for c in get_active_contracts(settings)
        }

        # Cache labeled metric objects — avoids per-bar registry lookup on hot path
        self._events_consumed_lbl = _EVENTS_CONSUMED.labels(agent=self.name)
        self._detection_latency_lbl = _DETECTION_LATENCY.labels(agent=self.name)
        self._rolls_detected_lbl = _ROLLS_DETECTED.labels(agent=self.name)
        self._detection_errors_lbl = _DETECTION_ERRORS.labels(agent=self.name)

    @property
    def topics_consumed(self) -> list[str]:
        return [topic_market_bars(self.env_name)]

    @property
    def topics_produced(self) -> list[str]:
        return [topic_roll_events(self.env_name)]

    async def _setup(self) -> None:
        """Connect Kafka producer and consumer."""
        self._kafka_producer = KafkaProducerClient(bootstrap_servers=self._kafka_bootstrap)
        await self._kafka_producer.start()
        self._kafka_consumer = KafkaConsumerClient(
            topic_market_bars(self.env_name),
            bootstrap_servers=self._kafka_bootstrap,
            group_id="roll_compute_consumer",
        )
        await self._kafka_consumer.start()


    async def _teardown(self) -> None:
        """Drain and close Kafka connections."""
        if self._kafka_consumer:
            await self._kafka_consumer.stop()
        if self._kafka_producer:
            await self._kafka_producer.stop()

    def _resolve_contracts(self, base_symbol: str, fallback: str) -> tuple[str, str]:
        """Return (old_contract, new_contract) from the roll chain.

        Falls back to (fallback, fallback) if chain derivation fails or chain is empty.
        Callers should treat old == new as an unresolved chain and skip publishing.
        """
        try:
            chain = derive_roll_chain(base_symbol)
            if chain and len(chain) >= 2:
                return chain[-2]["symbol"], chain[-1]["symbol"]
            if chain:
                return fallback, chain[0].get("roll_to", fallback)
        except Exception as exc:
            self.logger.warning(
                "roll_chain_derivation_failed",
                base_symbol=base_symbol,
                error=str(exc),
            )
        return fallback, fallback

    async def _run(self) -> None:
        """Main loop: consume bars, run RollMonitor, publish RollEvent on confirmed roll."""
        roll_topic = topic_roll_events(self.env_name)
        async for _topic, _key, payload in self._kafka_consumer.messages():
            if not self.running:
                break
            symbol = ""
            try:
                symbol = payload.get("symbol", "")
                base_symbol = self._symbol_to_base.get(symbol, symbol)
                volume = float(payload.get("volume", 0))
                bar_ts_str = payload.get("timestamp", "")

                self._events_consumed_lbl.inc()
                self._roll_monitor.update_volume(base_symbol, volume)

                bar_utc: datetime
                if bar_ts_str:
                    bar_utc = datetime.fromisoformat(bar_ts_str)
                    if bar_utc.tzinfo is None:
                        bar_utc = bar_utc.replace(tzinfo=UTC)
                else:
                    bar_utc = datetime.now(UTC)

                with self._detection_latency_lbl.time():
                    rolled = self._roll_monitor.check_roll(base_symbol, bar_utc)

                if rolled:
                    old_contract, new_contract = self._resolve_contracts(base_symbol, symbol)
                    if old_contract == new_contract:
                        self.logger.warning(
                            "roll_contracts_unresolved",
                            base_symbol=base_symbol,
                            fallback=symbol,
                        )
                    else:
                        roll_event = RollEvent(
                            symbol=base_symbol,
                            old_contract=old_contract,
                            new_contract=new_contract,
                            roll_gap_price=0.0,   # price gap computed by downstream consumer
                            roll_gap_pct=0.0,
                            detection_ts=bar_utc,
                            volume_zscore=self._roll_monitor._last_volume_zscore,
                            confirmation_count=self._roll_monitor._last_confirmation_count,
                            detection_method="volume",
                        )
                        await self._kafka_producer.publish(
                            roll_topic,
                            roll_event.model_dump(mode="json"),
                            key=base_symbol,
                        )
                        self._rolls_detected_lbl.inc()
                        self.logger.info(
                            "roll_detected",
                            symbol=base_symbol,
                            old_contract=old_contract,
                            new_contract=new_contract,
                            volume_zscore=roll_event.volume_zscore,
                            confirmation_count=roll_event.confirmation_count,
                            detection_method="volume",
                        )

                # Calendar check — independent of volume; fires at scheduled roll_end date
                if self._calendar_scheduler.check_calendar_roll(base_symbol, bar_utc):
                    cal_old, cal_new = self._resolve_contracts(base_symbol, symbol)
                    if cal_old == cal_new:
                        self.logger.warning(
                            "calendar_roll_contracts_unresolved",
                            base_symbol=base_symbol,
                            fallback=symbol,
                        )
                    else:
                        cal_event = RollEvent(
                            symbol=base_symbol,
                            old_contract=cal_old,
                            new_contract=cal_new,
                            roll_gap_price=0.0,
                            roll_gap_pct=0.0,
                            detection_ts=bar_utc,
                            volume_zscore=0.0,
                            confirmation_count=0,
                            detection_method="calendar",
                        )
                        await self._kafka_producer.publish(
                            roll_topic,
                            cal_event.model_dump(mode="json"),
                            key=base_symbol,
                        )
                        self._rolls_detected_lbl.inc()
                        self.logger.info(
                            "calendar_roll_fired",
                            symbol=base_symbol,
                            old_contract=cal_old,
                            new_contract=cal_new,
                        )
            except Exception as exc:
                self._detection_errors_lbl.inc()
                self.logger.error("roll_detection_error", error=str(exc), symbol=symbol)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    agent = RollComputeAgent()
    await agent.start()


if __name__ == "__main__":
    asyncio.run(main())
