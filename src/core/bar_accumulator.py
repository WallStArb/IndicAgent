"""BarAccumulator — session-aware 1m→HTF bar aggregator.

BarAccumulator receives 1m BarMessage objects and emits completed higher-timeframe
bars (5m, 15m, 1h) with source="htf_derived". It replaces the stateful aggregation
logic currently embedded in TimeframeBuilder with a typed, testable module.

Design decisions:
- Input: 1m bars only; non-1m bars return [] without error
- Output: list[BarMessage] of completed HTF bars for each boundary crossed
- OHLCV aggregation: open=first.open, high=max, low=min, close=last.close, volume=sum
- source: all emitted bars have source="htf_derived"
- session parameter: TradingSession controls session-break behavior
- Session break: partial accumulated bar is closed and emitted at session boundary;
  new accumulator state starts fresh for the next session

TradingSession:
- Holds session break schedule for the instrument's session type
- is_session_break(prev_ts_seconds, curr_ts_seconds) returns True when a session
  boundary falls between the two timestamps
- Prevents bar data from two different trading sessions being merged into one bar
"""

from __future__ import annotations

import structlog
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from src.core.schemas.bar_message import BarMessage, SessionType
from src.core.timeframe_builder import _floor_to_period

logger = structlog.get_logger(__name__)

# Module-level constant: timeframe string → minutes
_TF_MINUTES: dict[str, int] = {"5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}
# Cached tuple of all timeframe keys (avoids list() conversion on every BarAccumulator init)
_ALL_TFS: tuple[str, ...] = tuple(_TF_MINUTES.keys())

_ET = ZoneInfo("America/New_York")
_RTH_OPEN_ET = time(9, 30)
_RTH_CLOSE_ET = time(16, 0)


def _rth_boundaries_utc(day: date) -> tuple[int, int]:
    """Return (rth_open_utc, rth_close_utc) Unix timestamps for the given calendar day.

    Uses America/New_York so DST transitions are handled automatically.
    """
    open_dt = datetime.combine(day, _RTH_OPEN_ET, tzinfo=_ET).astimezone(UTC)
    close_dt = datetime.combine(day, _RTH_CLOSE_ET, tzinfo=_ET).astimezone(UTC)
    return int(open_dt.timestamp()), int(close_dt.timestamp())


class TradingSession:
    """Holds session break schedule for session-aware partial bar close (D-14).

    Session break = boundary where partial accumulated bar must be closed and
    emitted rather than carried forward into the next session.

    Args:
        session_type: The session type governing break detection logic.
    """

    def __init__(self, session_type: SessionType = SessionType.RTH) -> None:
        self.session_type = session_type

    def is_session_break(self, prev_ts: int, curr_ts: int) -> bool:
        """Return True if a session boundary falls between prev_ts and curr_ts.

        Args:
            prev_ts: Unix timestamp (seconds) of the previous bar's open time.
            curr_ts: Unix timestamp (seconds) of the current bar's open time.

        Returns:
            True when a session boundary falls strictly between prev_ts and curr_ts.
            False when both timestamps are within the same session window.
        """
        if self.session_type in (SessionType.CRYPTO, SessionType.FX):
            # 24h/24-5 continuous sessions — no intraday breaks
            return False

        # For RTH and ETH: check if any session boundary falls between prev_ts and curr_ts.
        # Boundaries are computed per calendar day using America/New_York so DST is correct.
        prev_date = datetime.fromtimestamp(prev_ts, tz=UTC).date()
        curr_date = datetime.fromtimestamp(curr_ts, tz=UTC).date()

        current = prev_date
        while current <= curr_date:
            rth_open, rth_close = _rth_boundaries_utc(current)
            for boundary_ts in (rth_open, rth_close):
                if prev_ts < boundary_ts <= curr_ts:
                    return True
            current = date.fromordinal(current.toordinal() + 1)

        return False


class BarAccumulator:
    """Session-aware 1m→HTF bar aggregator.

    Receives 1m BarMessage objects and emits completed higher-timeframe bars.
    Each (symbol, tf) combination maintains independent accumulator state.

    Args:
        timeframes: List of target timeframe strings to accumulate into.
                    Defaults to all supported HTF timeframes.
        session:    TradingSession for session-break detection. Defaults to
                    TradingSession(SessionType.RTH).
    """

    def __init__(
        self,
        timeframes: list[str] | None = None,
        session: TradingSession | None = None,
    ) -> None:
        self._timeframes = timeframes or _ALL_TFS
        self._session = session or TradingSession()
        self._accumulators: dict[str, dict] = {}  # key = "{symbol}:{tf}"
        self._last_session_boundary_log: dict[str, float] = {}  # key -> timestamp
        self._session_boundary_log_max_size = 100  # Prevent unbounded growth

    def update(self, bar_1m: BarMessage) -> list[BarMessage]:
        """Process a 1m bar and return any completed HTF bars.

        For each target timeframe, checks whether the 1m bar crosses the
        next TF boundary. If it does, emits the completed bar with
        source="htf_derived" and starts a new accumulator for that TF.

        Also handles session breaks: if prev_ts and curr_ts span a session
        boundary, the partial bar is closed and emitted before accumulating
        the new bar into a fresh state.

        Args:
            bar_1m: A completed 1m BarMessage. Non-1m bars return [] immediately.

        Returns:
            List of completed BarMessage objects (may be empty, or contain one
            completed bar per timeframe that crossed a boundary this bar).
        """
        if bar_1m.tf != "1m":
            return []

        completed: list[BarMessage] = []
        curr_ts = int(bar_1m.ts.timestamp())

        for tf in self._timeframes:
            tf_minutes = _TF_MINUTES.get(tf)
            if tf_minutes is None:
                continue

            key = f"{bar_1m.symbol}:{tf}"
            period_ts = _floor_to_period(curr_ts, tf_minutes)
            acc = self._accumulators.get(key)

            if acc is not None:
                # Session break check with logging
                if self._session.is_session_break(acc["last_ts"], curr_ts):
                    # Log session boundary (rate limited to prevent spam)
                    # Use bar timestamp instead of system call to avoid hot-path overhead
                    last_log = self._last_session_boundary_log.get(key, 0)
                    if bar_1m.ts.timestamp() - last_log > 300:  # Log at most once per 5min per symbol
                        logger.info(
                            "bar_accumulator.session_boundary",
                            symbol=bar_1m.symbol,
                            tf=tf,
                            prev_ts=datetime.fromtimestamp(acc["last_ts"], UTC).isoformat(),
                            curr_ts=datetime.fromtimestamp(curr_ts, UTC).isoformat(),
                        )
                        self._last_session_boundary_log[key] = bar_1m.ts.timestamp()
                        # Prune old entries to prevent unbounded growth
                        self._prune_session_boundary_log()

                    # Close partial bar
                    completed.append(self._build_bar(bar_1m.symbol, tf, acc))
                    acc = None

                elif acc["period_ts"] != period_ts:
                    # Window boundary crossed — emit the completed accumulator
                    completed.append(self._build_bar(bar_1m.symbol, tf, acc))
                    acc = None

            if acc is None:
                # Start a new accumulator
                self._accumulators[key] = self._new_accumulator(bar_1m, period_ts)
            else:
                # Defensive check for corruption (debug mode only to avoid hot-path overhead)
                if __debug__ and not self._is_accumulator_valid(acc):
                    logger.warning(
                        "bar_accumulator.corrupted_state",
                        symbol=bar_1m.symbol,
                        tf=tf,
                        accumulator_keys=list(acc.keys()),
                        resetting=True
                    )
                    acc = None
                    self._accumulators[key] = self._new_accumulator(bar_1m, period_ts)
                else:
                    # Update existing accumulator
                    acc["high"] = max(acc["high"], bar_1m.high)
                    acc["low"] = min(acc["low"], bar_1m.low)
                    acc["close"] = bar_1m.close
                    acc["volume"] += bar_1m.volume
                    acc["last_ts"] = curr_ts
                    # Update period_ts in case it shifted (shouldn't happen but be safe)
                    acc["period_ts"] = period_ts
                    # HTF is_flat_bar = True only when ALL constituent 1m bars were flat (D-10)
                    acc["all_flat"] = acc["all_flat"] and bar_1m.is_flat_bar

        return completed

    def current_partial(self, symbol: str, tf: str) -> BarMessage | None:
        """Return the in-progress (not yet complete) bar for (symbol, tf).

        Returns None if no 1m bars have been accumulated for (symbol, tf) yet.
        The returned bar has source="htf_derived" and reflects the OHLCV state
        of all 1m bars accumulated so far in the current TF window.
        """
        key = f"{symbol}:{tf}"
        acc = self._accumulators.get(key)
        if acc is None:
            return None
        return self._build_bar(symbol, tf, acc)

    def _new_accumulator(self, bar: BarMessage, period_ts: int) -> dict:
        """Create new accumulator state."""
        return {
            "period_ts": period_ts,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
            "last_ts": int(bar.ts.timestamp()),
            "session_type": bar.session_type,
            "all_flat": bar.is_flat_bar,
        }

    def _is_accumulator_valid(self, acc: dict) -> bool:
        """Defensive check for accumulator state corruption."""
        required_keys = {"period_ts", "open", "high", "low", "close", "volume", "last_ts"}
        if not all(k in acc for k in required_keys):
            return False

        # Validate data types
        if not isinstance(acc["high"], (int, float)):
            return False
        if not isinstance(acc["low"], (int, float)):
            return False

        # Validate OHLC sanity
        if acc["high"] < acc["low"]:  # Invalid: high can't be less than low
            return False

        return True

    def _prune_session_boundary_log(self) -> None:
        """Remove oldest entries from session boundary log to prevent unbounded growth."""
        if len(self._last_session_boundary_log) > self._session_boundary_log_max_size:
            # Remove oldest 20% of entries
            num_to_remove = len(self._last_session_boundary_log) // 5
            oldest_items = sorted(
                self._last_session_boundary_log.items(),
                key=lambda x: x[1]
            )[:num_to_remove]
            for key, _ in oldest_items:
                del self._last_session_boundary_log[key]

    def _build_bar(self, symbol: str, tf: str, acc: dict) -> BarMessage:
        """Build a BarMessage from accumulator state."""
        return BarMessage(
            ts=datetime.fromtimestamp(acc["period_ts"], tz=UTC),
            symbol=symbol,
            tf=tf,
            open=acc["open"],
            high=acc["high"],
            low=acc["low"],
            close=acc["close"],
            volume=acc["volume"],
            source="htf_derived",
            session_type=acc.get("session_type", SessionType.RTH),
            gap_preceding=False,
            is_flat_bar=acc.get("all_flat", False),
        )
