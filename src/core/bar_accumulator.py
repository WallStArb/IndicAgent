"""BarAccumulator — session-aware 1m→HTF bar aggregator.

BarAccumulator receives 1m BarMessage objects and emits completed higher-timeframe
bars (5m, 15m, 1h) with source="htf_derived". It replaces the stateful aggregation
logic currently embedded in TimeframeBuilder with a typed, testable module.

Design decisions (D-12, D-13, D-14, D-15):
- Input: 1m bars only; non-1m bars return [] without error (D-15)
- Output: list[BarMessage] of completed HTF bars for each boundary crossed
- OHLCV aggregation: open=first.open, high=max, low=min, close=last.close, volume=sum
- source: all emitted bars have source="htf_derived" (D-13)
- session parameter: TradingSession controls session-break behavior (D-14)
- Session break: partial accumulated bar is closed and emitted at session boundary;
  new accumulator state starts fresh for the next session

TradingSession (D-14):
- Holds session break schedule for the instrument's session type
- is_session_break(prev_ts_seconds, curr_ts_seconds) returns True when a session
  boundary falls between the two timestamps
- Prevents bar data from two different trading sessions being merged into one bar

Implementation: Wave 1 (44.1-02).
"""

from __future__ import annotations

from datetime import UTC, datetime

from src.core.schemas.bar_message import BarMessage, SessionType
from src.core.timeframe_builder import _floor_to_period

# Module-level constant: timeframe string → minutes
_TF_MINUTES: dict[str, int] = {"5m": 5, "15m": 15, "1h": 60}

# Session boundaries as UTC seconds-of-day
# RTH: 09:30 ET = 13:30 UTC, 16:00 ET = 20:00 UTC
_RTH_OPEN_UTC_SOD = 13 * 3600 + 30 * 60   # 48600
_RTH_CLOSE_UTC_SOD = 20 * 3600             # 72000
# ETH (pre-open) → RTH boundary: 09:30 ET = 13:30 UTC
_ETH_TO_RTH_UTC_SOD = 13 * 3600 + 30 * 60  # 48600


def _utc_sod(ts: int) -> int:
    """Return the seconds-of-day (0..86399) for a UTC Unix timestamp."""
    return ts % 86400


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

        # For RTH and ETH: check if any known session boundary falls between prev and curr.
        # We check two boundaries per day:
        #   1. RTH open: 09:30 ET = 13:30 UTC (sod=48600)
        #   2. RTH close: 16:00 ET = 20:00 UTC (sod=72000)
        # A boundary at absolute time B falls between prev_ts and curr_ts when
        # prev_ts < B <= curr_ts (exclusive start, inclusive end).
        boundaries = (_RTH_OPEN_UTC_SOD, _RTH_CLOSE_UTC_SOD)

        # Iterate over all days spanned by [prev_ts, curr_ts]
        # For each day, check if any boundary timestamp falls in the interval.
        prev_day_start = (prev_ts // 86400) * 86400
        curr_day_start = (curr_ts // 86400) * 86400

        day = prev_day_start
        while day <= curr_day_start:
            for boundary_sod in boundaries:
                boundary_ts = day + boundary_sod
                if prev_ts < boundary_ts <= curr_ts:
                    return True
            day += 86400

        return False


class BarAccumulator:
    """Session-aware 1m→HTF bar aggregator.

    Receives 1m BarMessage objects and emits completed higher-timeframe bars.
    Each (symbol, tf) combination maintains independent accumulator state.

    Args:
        timeframes: List of target timeframe strings to accumulate into.
                    Defaults to ["5m", "15m", "1h"].
        session:    TradingSession for session-break detection. Defaults to
                    TradingSession(SessionType.RTH).
    """

    def __init__(
        self,
        timeframes: list[str] | None = None,
        session: TradingSession | None = None,
    ) -> None:
        self._timeframes = timeframes or ["5m", "15m", "1h"]
        self._session = session or TradingSession()
        self._accumulators: dict[str, dict] = {}  # key = "{symbol}:{tf}"

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
                # Check session break first (D-14)
                if self._session.is_session_break(acc["last_ts"], curr_ts):
                    # Close partial bar at session boundary
                    completed.append(self._build_bar(bar_1m.symbol, tf, acc))
                    acc = None

                elif acc["period_ts"] != period_ts:
                    # Window boundary crossed — emit the completed accumulator
                    completed.append(self._build_bar(bar_1m.symbol, tf, acc))
                    acc = None

            if acc is None:
                # Start a new accumulator
                self._accumulators[key] = {
                    "period_ts": period_ts,
                    "open": bar_1m.open,
                    "high": bar_1m.high,
                    "low": bar_1m.low,
                    "close": bar_1m.close,
                    "volume": bar_1m.volume,
                    "last_ts": curr_ts,
                    "session_type": bar_1m.session_type,
                }
            else:
                # Update existing accumulator
                acc["high"] = max(acc["high"], bar_1m.high)
                acc["low"] = min(acc["low"], bar_1m.low)
                acc["close"] = bar_1m.close
                acc["volume"] += bar_1m.volume
                acc["last_ts"] = curr_ts
                # Update period_ts in case it shifted (shouldn't happen but be safe)
                acc["period_ts"] = period_ts

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
        )
